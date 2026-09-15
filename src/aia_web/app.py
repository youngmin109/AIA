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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aia_app.service import RunApplicationService
from aia_app.terminal import TerminalSessionError
from aia.capabilities import product_capabilities


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_ROOT / "templates"))
_TERMINAL_OUTPUT_BATCH_MIN_ITEMS = 16
_TERMINAL_OUTPUT_BATCH_MAX_CHARS = 64 * 1024


def _coalesce_terminal_output(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce WebSocket message overhead when replaying terminal history.

    A Workbench reconnect can replay up to 2,000 bounded PTY chunks. Sending
    every chunk as a separate JSON message makes the browser spend most of the
    reconnect window parsing and rendering transport overhead. Keep small live
    reads unchanged for latency and coalesce only a large replay into ordered
    output batches. The final sequence in a batch is sufficient for the
    connection cursor because all preceding data is included in that batch.
    """

    if len(items) <= _TERMINAL_OUTPUT_BATCH_MIN_ITEMS:
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


def _run_hook_verification(control_root: Path, *, timeout: float = 180.0) -> tuple[dict[str, Any], int]:
    """Run the existing CLI Hook verification from the local console.

    The console can request verification after the user has reviewed and
    trusted the Hook in Codex.  It never changes Codex trust state itself.
    """

    if timeout <= 0:
        return {"verified": False, "reason": "INVALID_TIMEOUT"}, 400
    command = [
        sys.executable,
        "-m",
        "aia.cli",
        "hook",
        "verify",
        "--json",
        "--timeout",
        str(timeout),
        "--control-root",
        str(control_root),
    ]
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

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        """Render the local product overview without starting an Agent."""

        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "preflight": app.state.service.preflight(),
                "runs": app.state.service.list_runs(),
                "capabilities": product_capabilities(),
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    def new_run(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "new_run.html",
            {
                "profiles": app.state.service.policy_profiles(),
                "preflight": app.state.service.preflight(),
                "capabilities": product_capabilities(),
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def run_history(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "history.html",
            {"runs": app.state.service.list_runs()},
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
        return _TEMPLATES.TemplateResponse(
            request, "live_run.html", {"session_id": session_id, "status": status}
        )

    @app.get("/runs/{session_id}/workbench", response_class=HTMLResponse)
    def workbench(request: Request, session_id: str) -> HTMLResponse:
        try:
            status = app.state.service.get_run_status(session_id)
        except (KeyError, ValueError):
            return _not_found("Run not found")
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

    @app.get("/api/runs/{session_id}/actions")
    def run_actions(session_id: str) -> JSONResponse:
        try:
            return JSONResponse({"actions": app.state.service.get_run_actions(session_id)})
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)

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
        last_sequence = 0

        async def send_pending_output() -> None:
            nonlocal last_sequence
            items = app.state.service.read_terminal_output(
                session_id,
                after_sequence=last_sequence,
            )
            for item in _coalesce_terminal_output(items):
                await websocket.send_json(item)
                last_sequence = max(last_sequence, int(item.get("sequence", last_sequence)))

        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=0.10,
                    )
                    if not isinstance(message, dict):
                        await websocket.send_json(
                            {"type": "error", "message": "terminal message must be an object"}
                        )
                    elif message.get("type") == "input":
                        result = app.state.service.send_terminal_input(
                            session_id,
                            message.get("data", ""),
                        )
                        await websocket.send_json(
                            {"type": "accepted", "action": "input", **result}
                        )
                    elif message.get("type") == "submit":
                        result = app.state.service.submit_terminal_input(session_id)
                        await websocket.send_json(
                            {"type": "accepted", "action": "submit", **result}
                        )
                    elif message.get("type") == "resize":
                        result = app.state.service.resize_terminal(
                            session_id,
                            int(message.get("rows", 32)),
                            int(message.get("cols", 120)),
                        )
                        await websocket.send_json(
                            {"type": "accepted", "action": "resize", **result}
                        )
                    else:
                        await websocket.send_json(
                            {"type": "error", "message": "unsupported terminal message"}
                        )
                except asyncio.TimeoutError:
                    pass
                except (KeyError, ValueError, TypeError, TerminalSessionError) as error:
                    await websocket.send_json({"type": "error", "message": str(error)})

                await send_pending_output()
                status = app.state.service.get_terminal_status(session_id)
                status_name = str(status.get("status", "UNKNOWN"))
                if status_name != last_status:
                    await websocket.send_json({"type": "status", **status})
                    last_status = status_name
                if status_name in {"FAILED", "EXITED"}:
                    # Send once more before closing so the last prompt/output
                    # is visible in the Workbench.
                    await send_pending_output()
                    await websocket.send_json({"type": "closed", "status": status_name})
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
        except (KeyError, ValueError) as exc:
            return _not_found(str(exc))
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


app = create_app()
