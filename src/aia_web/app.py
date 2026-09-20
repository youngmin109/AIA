"""HTTP routes for the local, single-user Security Console."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aia_app.service import RunApplicationService
from aia.capabilities import product_capabilities


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_ROOT / "templates"))
_ACTIVE_RUN_STATUSES = frozenset({"CREATED", "PREPARING", "READY", "RUNNING"})


def _dashboard_activity(service: RunApplicationService, runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return evidence-backed metrics for the active or latest verified run."""

    active = next(
        (
            run
            for run in runs
            if run.get("run_classification") == "LIVE_PROTECTED_RUN"
            and run.get("status") in _ACTIVE_RUN_STATUSES
            and not (run.get("runtime_reconciliation") or {}).get("orphaned")
        ),
        None,
    )
    focus = active or next(
        (
            run
            for run in runs
            if run.get("run_classification") == "PRODUCT_PROTECTED_RUN"
            and run.get("bundle_status") == "VALID"
        ),
        None,
    )
    if focus is None:
        return None

    session_id = focus.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        status = service.get_run_status(session_id)
        actions = service.get_run_actions(session_id)
    except (KeyError, OSError, ValueError):
        return None

    summary = status.get("evidence_summary")
    summary = summary if isinstance(summary, dict) else {}
    targets: set[str] = set()
    for action in actions:
        target = action.get("target") if isinstance(action, dict) else None
        if not isinstance(target, dict):
            continue
        key = next(
            (
                target.get(name)
                for name in ("canonical_path", "source_path", "destination_path", "command_fingerprint")
                if isinstance(target.get(name), str) and target.get(name)
            ),
            None,
        )
        if key:
            targets.add(key.casefold())

    protection_state = (status.get("protection") or {}).get("state") or focus.get("protection_state") or "UNKNOWN"
    friendly_states = {
        "ACTIVE_VERIFIED": "보호 확인됨",
        "ACTIVE_UNVERIFIED": "연결 확인 중",
        "READY_UNVERIFIED": "실행 대기",
        "DEGRADED": "보호 제한",
        "COMPLETED_VERIFIED": "완료 · 보호 확인",
        "COMPLETED_DEGRADED": "완료 · 확인 제한",
        "FAILED_DEGRADED": "실행 오류",
        "ORPHANED_DEGRADED": "상태 확인 필요",
    }
    is_active = focus is active
    return {
        "session_id": session_id,
        "label": "현재 보호 실행" if is_active else "최근 검증 실행",
        "href": f"/runs/{session_id}",
        "protection_state": friendly_states.get(protection_state, protection_state),
        "process_events": summary.get("process_observed"),
        "file_events": summary.get("filesystem_events"),
        "incidents": status.get("incident_count"),
        "unique_targets": len(targets),
        "live": is_active,
    }


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

        runs = app.state.service.list_runs()
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "preflight": app.state.service.preflight(),
                "runs": runs,
                "dashboard_activity": _dashboard_activity(app.state.service, runs),
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
        except (KeyError, ValueError) as exc:
            if isinstance(exc, ValueError):
                return JSONResponse({"error": str(exc)}, status_code=404)
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.get("/api/runs/{session_id}/process-tree")
    def run_process_tree(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(
                {"processes": app.state.service.get_run_process_tree(session_id)}
            )
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.get("/api/runs/{session_id}/workspace-changes")
    def run_workspace_changes(session_id: str) -> JSONResponse:
        try:
            return JSONResponse(
                {"changes": app.state.service.get_run_workspace_changes(session_id)}
            )
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

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
            request, "result.html", {"session_id": session_id, "result": result_data}
        )

    @app.get("/runs/{session_id}/report")
    def report(session_id: str) -> PlainTextResponse:
        try:
            return PlainTextResponse(app.state.service.get_report(session_id), media_type="text/markdown")
        except (KeyError, ValueError) as exc:
            return PlainTextResponse(str(exc), status_code=404)

    @app.get("/runs/{session_id}/audit", response_class=HTMLResponse)
    def audit_trail(request: Request, session_id: str) -> HTMLResponse:
        try:
            records = app.state.service.get_audit_records(session_id)
        except KeyError:
            return _not_found("Run not found")
        except ValueError as exc:
            return _not_found(str(exc))
        return _TEMPLATES.TemplateResponse(
            request,
            "audit.html",
            {"session_id": session_id, "records": records},
        )

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
