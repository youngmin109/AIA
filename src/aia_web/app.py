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
import secrets
from .local_security import LocalBrowserBoundary

import anyio
from anyio import to_thread

from aia_app.codex_app_server import CodexAppServerError
from aia_app.presenters import recovery_status_view
from aia_app.service import RunApplicationService
from aia.capabilities import product_capabilities
from aia import __version__
from aia.diagnostics import build_support_bundle
from aia.codex_installation import CodexHookInstaller


_ROOT = Path(__file__).resolve().parent
_CODEX_EVENT_WAIT_SECONDS = 5.0
_CODEX_EVENT_BATCH_MAX_CHARS = 64 * 1024
_CLIENT_MESSAGE_MAX_CHARS = 64 * 1024
_CODEX_SEND_TIMEOUT_SECONDS = 5.0
_CODEX_STREAM_TYPES = frozenset({"message.delta", "command.output", "reasoning.delta"})
_CODEX_TERMINAL_STATUSES = frozenset({"EXITED", "FAILED"})
_CODEX_RUN_NOT_FOUND = "보호 실행을 찾을 수 없습니다. 실행 목록을 새로 고친 뒤 다시 열어 주세요."


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

    if getattr(sys, "frozen", False):
        # A packaged build may sit inside a checkout (dist\...); the command the
        # user copies must still be the bundled aia-cli.exe that the installed
        # Hook points to, not the source tree's uv command.
        try:
            return subprocess.list2cmdline(_aia_cli_command())
        except FileNotFoundError:
            pass
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
            # The packaged desktop app frees its hidden console, so its standard
            # input handle is invalid; inheriting it makes Windows refuse to
            # start the child. The verifier reads nothing from stdin.
            stdin=subprocess.DEVNULL,
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
    except OSError:
        return {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": "HOOK_VERIFICATION_START_FAILED",
        }, 503
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


_SPA_INDEX_PATH = _ROOT / "static" / "app" / "index.html"


def _serve_spa() -> HTMLResponse | FileResponse:
    if not _SPA_INDEX_PATH.exists():
        return HTMLResponse(
            "AIA SPA build not found. Run `npm run build` in frontend/.",
            status_code=503,
        )
    return FileResponse(_SPA_INDEX_PATH)


def _register_spa_index_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    def spa_index():
        return _serve_spa()


def _register_catalog_routes(app: FastAPI) -> None:
    @app.get("/api/runs")
    def run_history_api() -> JSONResponse:
        return JSONResponse({"runs": app.state.service.list_runs()})

    @app.get("/api/profiles")
    def profiles() -> JSONResponse:
        return JSONResponse(app.state.service.policy_profiles())

    @app.get("/api/capabilities")
    def capabilities() -> JSONResponse:
        return JSONResponse(product_capabilities())


def _register_policy_routes(app: FastAPI) -> None:
    @app.get('/api/policy/templates/{profile}')
    def policy_template(profile: str) -> JSONResponse:
        from aia import resolve_profile
        from aia.protection import policy_content_mapping
        try:
            resolved = resolve_profile(profile)
            return JSONResponse({'document': policy_content_mapping(resolved)})
        except (OSError, ValueError) as error:
            return JSONResponse({'error': str(error)}, status_code=400)

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


def _register_readiness_routes(app: FastAPI) -> None:
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


def _register_runs_routes(app: FastAPI) -> None:
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
            status = app.state.service.get_run_status(session_id)
            if hasattr(app.state.service, 'get_run_activity'):
                status['activity'] = app.state.service.get_run_activity(session_id, status)
            return JSONResponse(status)
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)


def _register_run_details_routes(app: FastAPI) -> None:
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
                "product_version": __version__,
                "supported_environment": 'Windows 11 · Codex CLI · 로컬 보호 실행',
            }
        )

    @app.post('/api/support-bundle')
    async def support_bundle():
        bundle = await to_thread.run_sync(lambda: build_support_bundle(control_root=app.state.service.control_root))
        return JSONResponse(bundle, headers={'Cache-Control': 'no-store'})

    @app.get("/api/runs/{session_id}/recovery")
    def recovery_status(session_id: str, checkpoint_id: str | None = None) -> JSONResponse:
        try:
            status = (app.state.service.get_recovery_status(session_id, checkpoint_id)
                      if checkpoint_id is not None else app.state.service.get_recovery_status(session_id))
            response = {
                key: value
                for key, value in status.items()
                if key not in {"recovery_result", "integrity_result"}
            }
            return JSONResponse({**response, **recovery_status_view(status)})
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
            kwargs = {'confirm': isinstance(payload, dict) and payload.get('confirm') is True}
            if isinstance(payload, dict) and 'checkpoint_id' in payload:
                if not isinstance(payload['checkpoint_id'], str) or not payload['checkpoint_id'] or len(payload['checkpoint_id']) > 100:
                    raise ValueError('복구 지점 식별값이 올바르지 않습니다.')
                kwargs['checkpoint_id'] = payload['checkpoint_id']
            if isinstance(payload, dict) and 'expected_fingerprint' in payload:
                if not isinstance(payload['expected_fingerprint'], str) or len(payload['expected_fingerprint']) != 64:
                    raise ValueError('복구 미리보기 확인값이 올바르지 않습니다.')
                kwargs['expected_fingerprint'] = payload['expected_fingerprint']
            result = await to_thread.run_sync(lambda: app.state.service.restore_run(session_id, **kwargs))
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except (OSError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result, status_code=200)

    @app.get('/api/runs/{session_id}/checkpoints')
    async def recovery_points(session_id: str) -> JSONResponse:
        try:
            result = await to_thread.run_sync(lambda: app.state.service.list_recovery_points(session_id))
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except KeyError:
            return JSONResponse({'error': '실행을 찾을 수 없어요.'}, status_code=404)
        except (ValueError, OSError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

    @app.post('/api/runs/{session_id}/checkpoints')
    async def save_recovery_point(request: Request, session_id: str) -> JSONResponse:
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) - {'name'}:
                raise ValueError('복구 지점 저장 요청이 올바르지 않습니다.')
            result = await to_thread.run_sync(lambda: app.state.service.save_recovery_point(session_id, name=payload.get('name', '수동 복구 지점')))
            return JSONResponse(result)
        except KeyError:
            return JSONResponse({'error': '실행을 찾을 수 없어요.'}, status_code=404)
        except (ValueError, OSError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

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


def _register_codex_routes(app: FastAPI) -> None:
    @app.get("/api/codex/models")
    async def codex_models() -> JSONResponse:
        return JSONResponse(await to_thread.run_sync(app.state.service.list_codex_models))

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
        await websocket.accept(subprotocol=websocket.scope.get('aia_local_protocol'))
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
                if events and events[0]['sequence'] > cursor + 1:
                    await send({'type': 'history_gap', 'message': '재연결 전 대화 일부가 메모리 보관 한도를 넘었습니다. 감사 증거와 대화 기록은 별도입니다.',
                                'first_available_sequence': events[0]['sequence']})
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
                "question_answer": lambda message: service.respond_codex_question(
                    session_id,
                    str(message.get("question_id", "")),
                    message.get("answers"),
                ),
                "turn_settings": lambda message: service.set_codex_turn_settings(
                    session_id,
                    message.get("model"),
                    message.get("effort"),
                ),
                "permissions_decision": lambda message: service.respond_codex_permissions(
                    session_id,
                    str(message.get("permissions_id", "")),
                    str(message.get("decision", "")),
                ),
                "elicitation_response": lambda message: service.respond_codex_elicitation(
                    session_id,
                    str(message.get("elicitation_id", "")),
                    str(message.get("action", "")),
                    message.get("content"),
                ),
                "end_session": lambda message: service.end_codex_session(session_id),
            }
            while True:
                raw_message = await websocket.receive_text()
                # Check the size before decoding so an oversized message is never parsed.
                if len(raw_message) > _CLIENT_MESSAGE_MAX_CHARS:
                    await websocket.close(code=1009)
                    return
                message = json.loads(raw_message)
                client_id = message.get("client_id") if isinstance(message, dict) else None
                handler = handlers.get(message.get("type")) if isinstance(message, dict) else None
                if handler is None:
                    await send({"type": "error", "client_id": client_id, "message": "unsupported conversation message"})
                    continue
                try:
                    result = await to_thread.run_sync(handler, message)
                except (KeyError, CodexAppServerError) as error:
                    await send({"type": "error", "client_id": client_id, "action": message.get("type"),
                                "message": str(error) if not isinstance(error, KeyError) else _CODEX_RUN_NOT_FOUND})
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
                    await send({"type": "error", "message": _CODEX_RUN_NOT_FOUND})
            finally:
                group.cancel_scope.cancel()

        async with anyio.create_task_group() as group:
            group.start_soon(guarded, pump, group)
            group.start_soon(guarded, receive, group)
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close()


def _register_run_controls_routes(app: FastAPI) -> None:
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


def _register_result_exports_routes(app: FastAPI) -> None:
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


def _register_spa_fallback_routes(app: FastAPI) -> None:
    # Registered last so the SPA only catches paths no earlier route matched.
    @app.get("/{_full_path:path}", response_class=HTMLResponse)
    def spa_catch_all(_full_path: str):
        return _serve_spa()


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
    local_token = secrets.token_hex(32)
    app.add_middleware(LocalBrowserBoundary, token=local_token)

    @app.get('/api/local-session')
    def local_session():
        return JSONResponse({'token': local_token}, headers={'Cache-Control': 'no-store'})
    app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

    _register_spa_index_routes(app)
    _register_catalog_routes(app)
    _register_policy_routes(app)
    _register_readiness_routes(app)
    _register_runs_routes(app)
    _register_run_details_routes(app)
    _register_codex_routes(app)
    _register_run_controls_routes(app)
    _register_result_exports_routes(app)
    _register_spa_fallback_routes(app)
    return app


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=404)


app = create_app()
