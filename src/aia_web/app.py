"""HTTP routes for the local, single-user Security Console."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import contextlib

import anyio
from anyio import to_thread

from aia_app.codex_app_server import CodexAppServerError
from aia_app.service import RunApplicationService
from aia_app.terminal import TerminalSessionError
from aia.capabilities import product_capabilities
from aia.codex_installation import CodexHookInstaller


_ROOT = Path(__file__).resolve().parent
_TERMINAL_OUTPUT_BATCH_MIN_ITEMS = 2
# Keep one browser callback bounded. A smaller batch lets the Workbench's
# frame budget yield to keyboard input while still reducing WebSocket churn.
_TERMINAL_OUTPUT_BATCH_MAX_CHARS = 32 * 1024
_TERMINAL_OUTPUT_MAX_ITEMS_PER_TICK = 128
_TERMINAL_OUTPUT_SEND_TIMEOUT_SECONDS = 2.0
_TERMINAL_STATUS_POLL_INTERVAL_SECONDS = 0.25
# Ceiling on how long freshly-buffered PTY output can sit before this loop's
# next send_pending_output() flushes it to the browser -- the PTY reader
# thread itself blocks on the OS pipe with no added delay, so this is the
# dominant knob for perceived output latency. Kept well above 0 so idle
# sessions don't spin the event loop.
_TERMINAL_OUTPUT_POLL_TIMEOUT_SECONDS = 0.02


_CODEX_EVENT_WAIT_SECONDS = 5.0
_CODEX_EVENT_BATCH_MAX_CHARS = 64 * 1024
_CODEX_SEND_TIMEOUT_SECONDS = 5.0
_CODEX_STREAM_TYPES = frozenset({"message.delta", "command.output", "reasoning.delta"})
_CODEX_TERMINAL_STATUSES = frozenset({"EXITED", "FAILED"})


def _coalesce_codex_events(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Merge adjacent stream deltas and split into bounded WebSocket batches.

    Consecutive text deltas for the same item are concatenated (keeping the
    last sequence) so a burst of tokens costs one render instead of hundreds.
    Every other event is forwarded unchanged and in order.
    """

    merged: list[dict[str, Any]] = []
    for event in events:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and event.get("type") in _CODEX_STREAM_TYPES
            and previous.get("type") == event.get("type")
            and previous.get("item_id") == event.get("item_id")
        ):
            merged[-1] = {**previous, "text": str(previous.get("text", "")) + str(event.get("text", "")),
                          "sequence": event["sequence"], "recorded_at": event.get("recorded_at")}
        else:
            merged.append(dict(event))
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for event in merged:
        size = len(str(event.get("text", ""))) + 200
        if current and current_chars + size > _CODEX_EVENT_BATCH_MAX_CHARS:
            batches.append(current)
            current, current_chars = [], 0
        current.append(event)
        current_chars += size
    if current:
        batches.append(current)
    return batches


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

    _spa_index_path = _ROOT / "static" / "app" / "index.html"

    def _serve_spa() -> HTMLResponse | FileResponse:
        if not _spa_index_path.exists():
            return HTMLResponse(
                "AIA SPA build not found. Run `npm run build` in frontend/.",
                status_code=503,
            )
        return FileResponse(_spa_index_path)

    @app.get("/", response_class=HTMLResponse)
    def spa_index():
        return _serve_spa()

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

    @app.get("/api/runs/{session_id}")
    def run_status(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_run_status(session_id))
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.get("/api/runs/{session_id}/result")
    def result_api(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_result(session_id))
        except KeyError:
            return _not_found("Run not found")
        except ValueError as exc:
            safe_reason = (
                "Evidence Bundle 무결성 검증 실패"
                if str(exc) == "Evidence Bundle Integrity Failure"
                else "실행 기록의 보호 상태를 확인하지 못함"
            )
            return JSONResponse({"error": safe_reason}, status_code=409)

    @app.get("/api/runs/{session_id}/incidents/{action_id}")
    def incident_api(session_id: str, action_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_incident(session_id, action_id))
        except (KeyError, ValueError):
            return _not_found("Incident not found")

    @app.get("/api/console-info")
    def console_info() -> JSONResponse:
        project_root = _console_project_root()
        return JSONResponse(
            {
                "cli_prefix": _console_cli_prefix(),
                "module_cli_prefix": _console_module_cli_prefix(),
                "cli_project_root": str(project_root) if project_root else None,
                "hook_path": str(CodexHookInstaller().path),
            }
        )

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
                        timeout=_TERMINAL_OUTPUT_POLL_TIMEOUT_SECONDS,
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

    @app.get("/api/runs/{session_id}/codex/status")
    def codex_status(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(app.state.service.get_codex_status(session_id))
        except (KeyError, ValueError):
            # An unknown session has no live record and no readable Bundle.
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.websocket("/api/runs/{session_id}/codex")
    async def codex_socket(websocket: WebSocket, session_id: str) -> None:
        """Stream one Workbench conversation and accept user commands.

        Events are pushed as soon as Codex produces them: a sender task waits
        for new events off the event loop, and a receiver task waits for user
        commands without ever being cancelled mid-receive.  ``?after=N``
        resumes after the last event a reconnecting viewer already rendered.
        """

        service = app.state.service
        await websocket.accept()
        try:
            cursor = max(0, int(websocket.query_params.get("after", "0")))
        except ValueError:
            cursor = 0
        send_lock = asyncio.Lock()

        async def send(message: dict[str, Any]) -> None:
            async with send_lock:
                await asyncio.wait_for(websocket.send_json(message), timeout=_CODEX_SEND_TIMEOUT_SECONDS)

        async def status() -> dict[str, Any]:
            return await to_thread.run_sync(service.get_codex_status, session_id)

        async def pump() -> None:
            nonlocal cursor
            last_status: dict[str, Any] | None = None
            first = True
            while True:
                if first:
                    # Replay the backlog and report status right away; only
                    # later iterations long-poll for new events.
                    events = await to_thread.run_sync(
                        lambda: service.read_codex_events(session_id, after_sequence=cursor)
                    )
                    first = False
                else:
                    # A disconnect must not wait for this bounded long-poll
                    # to return; the worker thread ends on its own timeout.
                    events = await to_thread.run_sync(
                        lambda: service.wait_codex_events(
                            session_id,
                            after_sequence=cursor,
                            timeout=_CODEX_EVENT_WAIT_SECONDS,
                        ),
                        abandon_on_cancel=True,
                    )
                for batch in _coalesce_codex_events(events):
                    await send({"type": "events", "events": batch})
                    cursor = batch[-1]["sequence"]
                current = await status()
                if current != last_status:
                    await send({"type": "status", **current})
                    last_status = current
                if current.get("status") in _CODEX_TERMINAL_STATUSES and not events:
                    await send({"type": "closed", "status": current.get("status")})
                    return

        async def receive() -> None:
            handlers = {
                "user_message": lambda message: service.send_codex_message(session_id, str(message.get("text", ""))),
                "interrupt": lambda message: service.interrupt_codex_turn(session_id),
                "approval_decision": lambda message: service.respond_codex_approval(
                    session_id,
                    str(message.get("approval_id", "")),
                    str(message.get("decision", "")),
                ),
                "end_session": lambda message: service.end_codex_session(session_id),
            }
            while True:
                message = await websocket.receive_json()
                client_id = message.get("client_id") if isinstance(message, dict) else None
                handler = handlers.get(message.get("type")) if isinstance(message, dict) else None
                if handler is None:
                    await send({"type": "error", "client_id": client_id, "message": "unsupported conversation message"})
                    continue
                try:
                    result = await to_thread.run_sync(handler, message)
                except (KeyError, CodexAppServerError) as error:
                    await send({"type": "error", "client_id": client_id, "action": message.get("type"),
                                "message": str(error) if not isinstance(error, KeyError) else "Run not found"})
                    continue
                await send({"type": "accepted", "client_id": client_id, "action": message.get("type"), **result})

        async def guarded(part, group: anyio.abc.TaskGroup) -> None:
            # Whichever side ends first (viewer left, Codex exited, unknown
            # run) ends the other one; structured cancellation keeps the
            # handler well-behaved when the server itself cancels it.
            try:
                await part()
            except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
                pass  # the viewer's connection is gone
            except (KeyError, ValueError):
                with contextlib.suppress(WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
                    await send({"type": "error", "message": "Run not found"})
            finally:
                group.cancel_scope.cancel()

        async with anyio.create_task_group() as group:
            group.start_soon(guarded, pump, group)
            group.start_soon(guarded, receive, group)
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close()

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

    # Registered last so it only ever catches paths no earlier route (API,
    # static, WebSocket, or "/") matched -- the SPA owns client-side routing
    # for everything else, including a hard reload on a deep link.
    @app.get("/{_full_path:path}", response_class=HTMLResponse)
    def spa_catch_all(_full_path: str):
        return _serve_spa()

    return app


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=404)


app = create_app()
