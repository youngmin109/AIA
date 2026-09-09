from __future__ import annotations

from fastapi.testclient import TestClient

from aia_web.app import create_app


class FakeService:
    def policy_profiles(self):
        return [{"value": "BASIC_DEVELOPMENT", "label": "Basic Development"}]

    def create_protected_run(self, payload):
        if payload.get("workspace") == "invalid":
            raise ValueError("workspace validation failed")
        return {"redirect_url": "/runs/run-1", "session_id": "run-1", "status": "CREATED"}

    def validate_workspace(self, path):
        if path == "invalid":
            raise ValueError("workspace validation failed")
        return {"valid": True, "exists": True, "is_directory": True, "canonical_path": path}

    def get_run_status(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "checkpoint": "READY",
            "error": None,
            "incident_count": 1,
            "latest_actions": [],
            "lease": "ACTIVE",
            "mode": "ENFORCE",
            "phase": "RUNNING",
            "policy": {"id": "basic", "profile": "BASIC_DEVELOPMENT", "version": "1.0"},
            "result_available": True,
            "sensor_health": {"FILESYSTEM_WATCHER": "HEALTHY"},
            "session": {"agent": "codex", "status": "RUNNING", "session_id": session_id, "workspace": "C:/workspace"},
        }

    def get_run_actions(self, session_id):
        return [
            {
                "action_id": "a1",
                "operation": "DELETE",
                "policy_effect": "VIOLATION",
                "attribution_class": "PROCESS",
                "enforcement_action": "REFUSE",
                "execution_result": "NOT_ATTEMPTED",
                "target": {"display": "C:/workspace/file.txt"},
            }
        ]

    def get_incidents(self, session_id):
        return [self.get_incident(session_id, "a1")]

    def get_incident(self, session_id, action_id):
        return {
            "action_id": action_id,
            "operation": "DELETE",
            "policy_effect": "VIOLATION",
            "attribution_class": "PROCESS",
            "enforcement_action": "REFUSE",
            "execution_result": "NOT_ATTEMPTED",
            "summary": "DELETE was classified as VIOLATION.",
            "reason": "Hook ingress is unverified.",
            "proof": "Normalized action and evidence identifiers are available.",
            "target": {"display": "C:/workspace/file.txt"},
        }

    def get_result(self, session_id):
        return {
            "bundle_status": "VALID",
            "session_status": "COMPLETED",
            "recovery_status": "RESTORED",
            "integrity_status": "VERIFIED",
            "policy_id": "basic",
            "policy_version": "1.0",
            "actions": self.get_run_actions(session_id),
            "limitations": ["Local console does not provide remote access."],
        }

    def get_report(self, session_id):
        return "# AIA Security Report\n"

    def get_result_json(self, session_id):
        return b'{"bundle_status":"VALID"}'

    def get_raw_evidence(self, session_id):
        return [{"evidence_id": "e1", "payload_keys": ["operation"]}]

    def shutdown(self, wait=True):
        return None


def test_console_routes_render_and_keep_raw_secrets_out_of_html() -> None:
    client = TestClient(create_app(FakeService()))
    assert client.get("/").status_code == 200
    assert client.get("/api/workspaces/validate", params={"path": "C:/workspace"}).json()["valid"] is True
    created = client.post("/api/runs", json={"workspace": "C:/workspace", "task": "inspect"})
    assert created.status_code == 202
    assert created.json()["redirect_url"] == "/runs/run-1"
    live = client.get("/runs/run-1")
    assert live.status_code == 200
    assert "Live execution" in live.text
    assert client.get("/api/runs/run-1").json()["phase"] == "RUNNING"
    assert client.get("/api/runs/run-1/actions").json()["actions"][0]["operation"] == "DELETE"
    incident = client.get("/runs/run-1/incidents/a1")
    assert incident.status_code == 200
    assert "PROCESS" in incident.text
    assert "정책 위반은 확인됐지만" in incident.text
    result = client.get("/runs/run-1/result")
    assert result.status_code == 200
    assert "VERIFIED" in result.text
    assert client.get("/runs/run-1/report").headers["content-type"].startswith("text/markdown")
    assert client.get("/runs/run-1/raw-evidence").json()["evidence"][0]["evidence_id"] == "e1"
    assert client.get("/runs/run-1/result.json").json()["bundle_status"] == "VALID"
    assert "SUPER_SECRET" not in result.text


def test_console_maps_validation_errors_to_bad_request() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.post("/api/runs", json={"workspace": "invalid", "task": "inspect"})
    assert response.status_code == 400
    assert "workspace validation failed" in response.json()["error"]
