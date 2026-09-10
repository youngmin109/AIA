"""HTTP routes for the local, single-user Security Console."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aia_app.service import RunApplicationService


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_ROOT / "templates"))


def default_control_root() -> Path:
    configured = os.environ.get("AIA_CONTROL_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".aia" / "control"


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
    def new_run(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "new_run.html",
            {
                "profiles": app.state.service.policy_profiles(),
                "preflight": app.state.service.preflight(),
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

    @app.get("/api/preflight")
    def preflight() -> JSONResponse:
        return JSONResponse(app.state.service.preflight())

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
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)

    @app.post("/api/runs/{session_id}/stop")
    def stop_run(session_id: str) -> JSONResponse:
        try:
            result = app.state.service.request_stop(session_id)
        except KeyError:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(result, status_code=202 if result.get("accepted") else 409)

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
