"""HTTP routes for the local, single-user Security Console."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aia_app.service import RunApplicationService
from aia_app.terminal import TerminalSessionError
from aia.capabilities import product_capabilities
from aia.codex_installation import CodexHookInstaller


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_ROOT / "templates"))
_TERMINAL_OUTPUT_BATCH_MIN_ITEMS = 2
# Keep one browser callback bounded. A smaller batch lets the Workbench's
# frame budget yield to keyboard input while still reducing WebSocket churn.
_TERMINAL_OUTPUT_BATCH_MAX_CHARS = 32 * 1024
_TERMINAL_OUTPUT_MAX_ITEMS_PER_TICK = 128
_TERMINAL_OUTPUT_SEND_TIMEOUT_SECONDS = 2.0
_TERMINAL_STATUS_POLL_INTERVAL_SECONDS = 0.25


def _hidden_process_kwargs() -> dict[str, int]:
    """Keep local diagnostic subprocesses inside the desktop app window."""

    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _aia_cli_command(*arguments: str) -> list[str]:
    """Return the CLI executable appropriate for source or frozen execution.

    In a PyInstaller GUI build ``sys.executable`` is ``AIA.exe`` itself.  Using
    it with ``-m aia.cli`` would launch a second GUI process instead of the
    diagnostic CLI, so the packaged desktop app must invoke the sibling
    ``aia-cli.exe`` explicitly.
    """

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve(strict=False)
        if executable.name.casefold() in {"aia-cli.exe", "aia-cli"}:
            return [str(executable), *arguments]
        candidates = (
            executable.parent / "aia-cli" / "aia-cli.exe",
            executable.parent.parent / "aia-cli" / "aia-cli.exe",
            executable.parent / "aia-cli.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate), *arguments]
        if executable.name.casefold() in {"aia.exe", "aia"}:
            return [str(executable), *arguments]
        raise FileNotFoundError("aia-cli.exe is not installed next to AIA.exe")

    return [sys.executable, "-m", "aia.cli", *arguments]


def _coalesce_terminal_output(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce WebSocket message overhead when replaying terminal history.

    A Workbench reconnect can replay up to 2,000 bounded PTY chunks. Sending
    every chunk as a separate JSON message makes the browser spend most of the
    reconnect window parsing and rendering transport overhead. Keep small live
    reads unchanged for latency and coalesce only a large replay into ordered
    output batches. The final sequence in a batch is sufficient for the
    connection cursor because all preceding data is included in that batch.
    """

    if len(items) < _TERMINAL_OUTPUT_BATCH_MIN_ITEMS:
        return items

    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        last = current[-1]
        batches.append(
            {
                "type": "output",
                "sequence": last.get("sequence", 0),
                "data": "".join(str(item.get("data", "")) for item in current),
                "recorded_at": last.get("recorded_at"),
            }
        )
        current = []
        current_chars = 0

    for item in items:
        data = str(item.get("data", ""))
        if current and current_chars + len(data) > _TERMINAL_OUTPUT_BATCH_MAX_CHARS:
            flush()
        current.append(item)
        current_chars += len(data)
    flush()
    return batches


def default_control_root() -> Path:
    configured = os.environ.get("AIA_CONTROL_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".aia" / "control"


def _dashboard_preflight_placeholder() -> dict[str, Any]:
    """Return a safe loading state for the dashboard's deferred preflight."""

    return {
        "ready": False,
        "readiness_code": "CHECKING",
        "next_step": "AIA가 Codex Hook과 로컬 실행 환경을 확인하고 있습니다.",
        "checks": [],
        "hook_trust": {
            "status": "CHECKING",
            "detail": "Codex Hook Trust 상태를 확인하고 있습니다.",
        },
        "hook_activation": {
            "status": "CHECKING",
            "detail": "실제 Hook 연결 상태를 확인하고 있습니다.",
        },
        "codex_hook_trust": {"hooks": []},
        "protection_claim": {
            "status": "CHECKING",
            "detail": "준비 상태 확인이 끝날 때까지 보호 실행을 시작하지 않습니다.",
        },
    }


def _console_project_root() -> Path | None:
    """Return the checkout that is serving this local console, when present."""

    return next(
        (
            candidate
            for candidate in (_ROOT, *_ROOT.parents)
            if (candidate / "pyproject.toml").is_file()
        ),
        None,
    )


def _console_module_cli_prefix() -> str:
    """Return the launcher that bypasses a blocked generated ``aia.exe``."""

    project_root = _console_project_root()
    if project_root is not None:
        return subprocess.list2cmdline(
            [
                "uv",
                "run",
                "--isolated",
                "--project",
                str(project_root),
                "python",
                "-m",
                "aia.cli",
            ]
        )
    # An installed AIA has no checkout-level ``pyproject.toml`` to pass to
    # uv.  Its serving interpreter already contains the package, so use that
    # interpreter directly instead of displaying a command that depends on a
    # project directory that does not exist.
    return subprocess.list2cmdline([sys.executable, "-m", "aia.cli"])


def _console_cli_prefix() -> str:
    """Return the CLI form that avoids a generated Windows console-script EXE."""

    return _console_module_cli_prefix()


def _is_console_diagnostic_run(run: dict[str, Any]) -> bool:
    """Identify known AIA-created probe workspaces for overview display only."""

    workspace = str(run.get("workspace") or "")
    leaf = PureWindowsPath(workspace.replace("/", "\\")).name.casefold()
    return leaf.startswith(("aia-hook-verify-", "aia-path-hook-probe-")) or leaf in {
        "aia-ui-probe",
        "aia-hook-probe",
    }


def _decorate_console_diagnostic_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add an overview-only label without changing persisted run records."""

    return [
        {**run, "dashboard_diagnostic": _is_console_diagnostic_run(run)}
        for run in runs
    ]


def _dashboard_run_view(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Prefer user runs on the dashboard while preserving all history records."""

    decorated = _decorate_console_diagnostic_runs(runs)
    user_runs = [run for run in decorated if not run["dashboard_diagnostic"]]
    return (user_runs or decorated), sum(
        1 for run in decorated if run["dashboard_diagnostic"]
    )


def _run_hook_verification(control_root: Path, *, timeout: float = 180.0) -> tuple[dict[str, Any], int]:
    """Run the existing CLI Hook verification from the local console.

    The console can request verification after the user has reviewed and
    trusted the Hook in Codex.  It never changes Codex trust state itself.
    """

    if timeout <= 0:
        return {"verified": False, "reason": "INVALID_TIMEOUT"}, 400
    try:
        command = _aia_cli_command(
            "hook",
            "verify",
            "--json",
            "--timeout",
            str(timeout),
            "--control-root",
            str(control_root),
        )
    except FileNotFoundError:
        return {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": "AIA_CLI_UNAVAILABLE",
        }, 503
    try:
        completed = subprocess.run(
            command,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 60.0,
            check=False,
            **_hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": "HOOK_VERIFICATION_TIMEOUT",
        }, 504
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": "HOOK_VERIFICATION_OUTPUT_INVALID",
        }, 502
    if not isinstance(payload, dict):
        return {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": "HOOK_VERIFICATION_OUTPUT_INVALID",
        }, 502
    return payload, 200 if payload.get("verified") is True else 409


def create_app(service: RunApplicationService | None = None) -> FastAPI:
    active_service = service or RunApplicationService(
        default_control_root(),
        require_hook_verification=True,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        active_service.shutdown(wait=False)

    app = FastAPI(
        title="AIA Local Security Console",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.service = active_service
    app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

    # Temporary scoped preview mount for the new React/Vite IDE shell
    # (UI redesign milestone 1-5). Does not touch "/" or any existing Jinja
    # route below; removed once the SPA replaces them (redesign milestone 6).
    _spa_index_path = _ROOT / "static" / "app" / "index.html"

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/{_rest:path}", response_class=HTMLResponse)
    def spa_preview(_rest: str = ""):
        if not _spa_index_path.exists():
            return HTMLResponse(
                "AIA SPA build not found. Run `npm run build` in frontend/.",
                status_code=503,
            )
        return FileResponse(_spa_index_path)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/start", response_class=HTMLResponse)
    def setup(request: Request) -> HTMLResponse:
        """Render the simple first-run setup surface.

        The setup page only changes presentation.  Readiness, Workspace
        validation, policy resolution, and run creation continue to use the
        existing service and API contracts.
        """

        runs = app.state.service.list_runs()
        recent_runs, _diagnostic_run_count = _dashboard_run_view(runs)
        return _TEMPLATES.TemplateResponse(
            request,
            "setup.html",
            {
                "profiles": app.state.service.policy_profiles(),
                "preflight": _dashboard_preflight_placeholder(),
                "setup_preflight_deferred": True,
                "recent_runs": recent_runs[:5],
                "capabilities": product_capabilities(),
                "cli_prefix": _console_cli_prefix(),
                "module_cli_prefix": _console_module_cli_prefix(),
                "cli_project_root": _console_project_root(),
                "is_setup": True,
            },
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        """Render the local product overview without starting an Agent."""

        runs = app.state.service.list_runs()
        dashboard_runs, diagnostic_run_count = _dashboard_run_view(runs)
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "preflight": _dashboard_preflight_placeholder(),
                "dashboard_preflight_deferred": True,
                "runs": runs,
                "dashboard_runs": dashboard_runs,
                "dashboard_diagnostic_count": diagnostic_run_count,
                "capabilities": product_capabilities(),
                "cli_prefix": _console_cli_prefix(),
                "module_cli_prefix": _console_module_cli_prefix(),
                "cli_project_root": _console_project_root(),
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    def new_run(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "new_run.html",
            {
                "profiles": app.state.service.policy_profiles(),
                "preflight": _dashboard_preflight_placeholder(),
                "new_run_preflight_deferred": True,
                "capabilities": product_capabilities(),
                "cli_prefix": _console_cli_prefix(),
                "module_cli_prefix": _console_module_cli_prefix(),
                "cli_project_root": _console_project_root(),
                "hook_path": str(CodexHookInstaller().path),
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def run_history(request: Request) -> HTMLResponse:
        runs = app.state.service.list_runs()
        return _TEMPLATES.TemplateResponse(
            request,
            "history.html",
            {"runs": runs, "history_runs": _decorate_console_diagnostic_runs(runs)},
        )

    @app.get("/api/runs")
    def run_history_api() -> JSONResponse:
        return JSONResponse({"runs": app.state.service.list_runs()})

    @app.get("/api/profiles")
    def profiles() -> JSONResponse:
        return JSONResponse(app.state.service.policy_profiles())

    @app.get("/api/capabilities")
    def capabilities() -> JSONResponse:
        return JSONResponse(product_capabilities())

    @app.post("/api/policy/preview")
    async def preview_policy(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            preview = app.state.service.preview_policy(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(preview)

    @app.post("/api/policy/validate")
    async def validate_policy(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            document = payload.get("document") if isinstance(payload, dict) else None
            return JSONResponse(app.state.service.validate_policy_document(document))
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse({"valid": False, "error": str(exc)}, status_code=400)

    @app.post("/api/policy/save")
    async def save_policy(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            return JSONResponse(app.state.service.save_policy_document(payload))
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            return JSONResponse({"saved": False, "error": str(exc)}, status_code=400)

    @app.get("/api/preflight")
    def preflight() -> JSONResponse:
        return JSONResponse(app.state.service.preflight())

    @app.post("/api/hook/verify")
    def verify_hook() -> JSONResponse:
        control_root = getattr(app.state.service, "control_root", default_control_root())
        payload, status_code = _run_hook_verification(Path(control_root))
        return JSONResponse(payload, status_code=status_code)

    @app.post("/api/hook/setup")
    def setup_hook() -> JSONResponse:
        """Install or refresh AIA's user-level Hook from the local console.

        Codex Trust remains a deliberate user-controlled boundary. This
        endpoint performs the safe, idempotent equivalent of ``aia setup`` so
        the normal product flow does not require a terminal command.
        """

        installer = CodexHookInstaller()
        try:
            path = installer.install()
        except (OSError, ValueError) as error:
            return JSONResponse(
                {
                    "installed": False,
                    "hook_path": str(installer.path),
                    "error": str(error),
                },
                status_code=400,
            )
        return JSONResponse(
            {
                "installed": True,
                "hook_path": str(path),
                "posttool_installed": installer.is_posttool_installed(),
                "trust_required": True,
                "next_step": (
                    "Codex에서 AIA Hook을 처음 한 번 검토·신뢰하세요. "
                    "이미 신뢰했다면 실제 연결 검증을 이어서 진행합니다."
                ),
            }
        )

    @app.get("/api/workspaces/validate")
    def validate_workspace(path: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.validate_workspace(path))
        except ValueError as exc:
            return JSONResponse({"valid": False, "error": str(exc)}, status_code=400)

    @app.post("/api/runs")
    async def create_run(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            created = app.state.service.create_protected_run(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(created, status_code=202)

    @app.get("/runs/{session_id}", response_class=HTMLResponse)
    def live_run(request: Request, session_id: str) -> HTMLResponse:
        try:
            status = app.state.service.get_run_status(session_id)
        except KeyError:
            return _not_found("Run not found")
        except ValueError as exc:
            return _run_unavailable(request, session_id, str(exc))
        return _TEMPLATES.TemplateResponse(
            request, "live_run.html", {"session_id": session_id, "status": status}
        )

    @app.get("/runs/{session_id}/workbench", response_class=HTMLResponse)
    def workbench(request: Request, session_id: str) -> HTMLResponse:
        try:
            status = app.state.service.get_run_status(session_id)
        except KeyError:
            return _not_found("Run not found")
        except ValueError as exc:
            return _run_unavailable(request, session_id, str(exc))
        return _TEMPLATES.TemplateResponse(
            request,
            "workbench.html",
            {"session_id": session_id, "status": status, "is_workbench": True},
        )

    @app.get("/api/runs/{session_id}")
    def run_status(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_run_status(session_id))
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.get("/api/runs/{session_id}/recovery")
    def recovery_status(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_recovery_status(session_id))
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except (OSError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=409)

    @app.post("/api/runs/{session_id}/recovery/restore")
    async def restore_run(request: Request, session_id: str) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        try:
            result = app.state.service.restore_run(
                session_id,
                confirm=isinstance(payload, dict) and payload.get("confirm") is True,
            )
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except (OSError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result, status_code=200)

    @app.get("/api/runs/{session_id}/actions")
    def run_actions(session_id: str) -> JSONResponse:
        try:
            return JSONResponse({"actions": app.state.service.get_run_actions(session_id)})
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except ValueError as exc:
            safe_reason = (
                "Evidence Bundle 무결성 검증 실패"
                if str(exc) == "Evidence Bundle Integrity Failure"
                else "실행 증거를 확인하지 못함"
            )
            return JSONResponse({"error": safe_reason}, status_code=409)

    @app.get("/api/runs/{session_id}/terminal/status")
    def terminal_status(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_terminal_status(session_id))
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.websocket("/api/runs/{session_id}/terminal")
    async def terminal_socket(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        last_status: str | None = None
        last_status_check = 0.0
        last_sequence = 0

        async def send_message(message: dict[str, Any]) -> None:
            """Send one terminal message without starving other local routes.

            The Workbench and its status API share one local Uvicorn event
            loop.  A slow or overloaded browser must not let a burst of PTY
            output monopolize that loop and make new input or status requests
            appear frozen.  The explicit yield also matters on Windows,
            where a small local socket write can complete synchronously.
            """

            try:
                await asyncio.wait_for(
                    websocket.send_json(message),
                    timeout=_TERMINAL_OUTPUT_SEND_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as error:
                raise WebSocketDisconnect(code=1013) from error
            await asyncio.sleep(0)

        async def send_pending_output() -> None:
            nonlocal last_sequence
            items = app.state.service.read_terminal_output(
                session_id,
                after_sequence=last_sequence,
            )
            # Never flush the whole bounded replay in one event-loop turn.
            # Remaining chunks are picked up on the next turn using the final
            # sequence acknowledged below, so a reconnect remains lossless
            # within the PTY ring buffer while live API requests stay usable.
            items = items[:_TERMINAL_OUTPUT_MAX_ITEMS_PER_TICK]
            for item in _coalesce_terminal_output(items):
                await send_message(item)
                last_sequence = max(last_sequence, int(item.get("sequence", last_sequence)))

        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=0.10,
                    )
                    if not isinstance(message, dict):
                        await send_message(
                            {"type": "error", "message": "terminal message must be an object"}
                        )
                    elif message.get("type") == "input":
                        result = app.state.service.send_terminal_input(
                            session_id,
                            message.get("data", ""),
                        )
                        await send_message(
                            {"type": "accepted", "action": "input", **result}
                        )
                    elif message.get("type") == "submit":
                        result = app.state.service.submit_terminal_input(session_id)
                        await send_message(
                            {"type": "accepted", "action": "submit", **result}
                        )
                    elif message.get("type") == "resize":
                        result = app.state.service.resize_terminal(
                            session_id,
                            int(message.get("rows", 32)),
                            int(message.get("cols", 120)),
                        )
                        await send_message(
                            {"type": "accepted", "action": "resize", **result}
                        )
                    else:
                        await send_message(
                            {"type": "error", "message": "unsupported terminal message"}
                        )
                except asyncio.TimeoutError:
                    pass
                except (KeyError, ValueError, TypeError, TerminalSessionError) as error:
                    await send_message({"type": "error", "message": str(error)})

                await send_pending_output()
                now = asyncio.get_running_loop().time()
                if now - last_status_check >= _TERMINAL_STATUS_POLL_INTERVAL_SECONDS:
                    last_status_check = now
                    status = app.state.service.get_terminal_status(session_id)
                    status_name = str(status.get("status", "UNKNOWN"))
                    if status_name != last_status:
                        await send_message({"type": "status", **status})
                        last_status = status_name
                    if status_name in {"FAILED", "EXITED"}:
                        # Send once more before closing so the last prompt/output
                        # is visible in the Workbench.
                        await send_pending_output()
                        await send_message({"type": "closed", "status": status_name})
                        return
        except WebSocketDisconnect:
            return

    @app.post("/api/runs/{session_id}/stop")
    def stop_run(session_id: str) -> JSONResponse:
        try:
            result = app.state.service.request_stop(session_id)
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(result, status_code=202 if result.get("accepted") else 409)

    @app.post("/api/runs/{session_id}/reconcile")
    def reconcile_run(session_id: str) -> JSONResponse:
        try:
            result = app.state.service.reconcile_orphaned_run(session_id)
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(result, status_code=200 if result.get("reconciled") else 409)

    @app.get("/runs/{session_id}/incidents/{action_id}", response_class=HTMLResponse)
    def incident(request: Request, session_id: str, action_id: str) -> HTMLResponse:
        try:
            incident_data = app.state.service.get_incident(session_id, action_id)
        except (KeyError, ValueError):
            return _not_found("Incident not found")
        return _TEMPLATES.TemplateResponse(
            request,
            "incident.html",
            {"session_id": session_id, "incident": incident_data},
        )

    @app.get("/runs/{session_id}/result", response_class=HTMLResponse)
    def result(request: Request, session_id: str) -> HTMLResponse:
        try:
            result_data = app.state.service.get_result(session_id)
        except KeyError:
            return _not_found("Run not found")
        except ValueError as exc:
            return _run_unavailable(request, session_id, str(exc))
        return _TEMPLATES.TemplateResponse(
            request,
            "result.html",
            {
                "session_id": session_id,
                "result": result_data,
                "is_workbench": result_data.get("launch_mode") == "web_terminal",
            },
        )

    @app.get("/runs/{session_id}/report")
    def report(session_id: str) -> PlainTextResponse:
        try:
            return PlainTextResponse(app.state.service.get_report(session_id), media_type="text/markdown")
        except (KeyError, ValueError) as exc:
            return PlainTextResponse(str(exc), status_code=404)

    @app.get("/runs/{session_id}/raw-evidence")
    def raw_evidence(session_id: str) -> JSONResponse:
        try:
            return JSONResponse({"evidence": app.state.service.get_raw_evidence(session_id)})
        except (KeyError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.get("/runs/{session_id}/result.json")
    def result_json(session_id: str) -> Response:
        try:
            return Response(
                app.state.service.get_result_json(session_id),
                media_type="application/json",
            )
        except (KeyError, ValueError) as exc:
            return Response(str(exc), status_code=404, media_type="text/plain")

    return app


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=404)


def _run_unavailable(request: Request, session_id: str, reason: str) -> HTMLResponse:
    """Render a safe, actionable state for an unreadable run record."""

    safe_reason = (
        "Evidence Bundle 무결성 검증 실패"
        if reason == "Evidence Bundle Integrity Failure"
        else "실행 기록의 보호 상태를 확인하지 못함"
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "run_unavailable.html",
        {"session_id": session_id, "reason": safe_reason},
        status_code=409,
    )


app = create_app()
