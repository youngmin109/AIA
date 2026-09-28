from __future__ import annotations

import importlib
import shutil
import subprocess
import time
from fastapi.testclient import TestClient

from aia_web.app import (
    _aia_cli_command,
    _coalesce_terminal_output,
    _console_cli_prefix,
    create_app,
)
from aia_app.service import RunApplicationService
from aia.codex_installation import CodexHookInstaller
from aia.adapters.codex import CodexAdapter
from aia import ProcessIdentityStatus, SessionFinalizer
from tests.test_finalization import _session


class FakeService:
    def __init__(self):
        self.created_payloads = []

    def policy_profiles(self):
        return [{"value": "BASIC_DEVELOPMENT", "label": "Basic Development"}]

    def preview_policy(self, payload):
        if payload.get("path") == "invalid":
            raise ValueError("policy preview failed")
        return {
            "policy_id": "basic",
            "policy_version": "1.0",
            "profile": payload.get("policy_profile", "BASIC_DEVELOPMENT"),
            "operation": payload["operation"],
            "target_kind": "COMMAND" if payload["operation"] == "EXECUTE" else "PATH",
            "policy_decision": "VIOLATION",
            "operation_effect": "DENY",
            "asset_type": "SECRET",
            "matched_rule_ids": ["secret-files"],
            "audit_record": False,
            "reason": None,
            "limitation": None,
        }

    def list_runs(self):
        return []

    def preflight(self, *, runs=None):
        return {
            "ready": True,
            "readiness_code": "READY",
            "next_step": "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다.",
            "checks": [
                {
                    "name": "codex_executable",
                    "label": "Codex 실행 파일",
                    "ok": True,
                    "detail": "codex.exe",
                }
            ],
            "hook_trust": {
                "status": "MANUAL_REVIEW_REQUIRED",
                "detail": "Codex에서 /hooks를 검토하세요.",
            },
            "hook_activation": {
                "status": "CURRENTLY_VERIFIED",
                "detail": "현재 Hook이 검증되었습니다.",
            },
            "codex_hook_trust": {
                "available": True,
                "hooks": [
                    {"event": "preToolUse", "trust_status": "MODIFIED"},
                    {"event": "postToolUse", "trust_status": "UNTRUSTED"},
                ],
            },
            "next_steps": [],
        }

    def create_protected_run(self, payload):
        self.created_payloads.append(payload)
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
            "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1, "hook_broker": "HEALTHY"},
            "stop": {"requested": False, "error": None},
            "policy": {"id": "basic", "profile": "BASIC_DEVELOPMENT", "version": "1.0"},
            "result_available": True,
            "evidence_summary": {
                "available": True,
                "filesystem_events": 2,
                "pretool_events": 1,
                "posttool_events": 1,
                "sensor_health_events": 1,
            },
            "sensor_health": {"FILESYSTEM_WATCHER": "HEALTHY"},
            "session": {"agent": "codex", "status": "RUNNING", "session_id": session_id, "workspace": "C:/workspace"},
        }

    def get_terminal_status(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "mode": "web_terminal",
            "status": "RUNNING",
            "pid": 1234,
            "rows": 32,
            "cols": 120,
            "started_at": None,
            "ended_at": None,
            "error": None,
        }

    def drain_terminal_output(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return []

    def read_terminal_output(self, session_id, *, after_sequence=0):
        if session_id != "run-1":
            raise KeyError(session_id)
        assert after_sequence >= 0
        return []

    def send_terminal_input(self, session_id, value):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id}

    def submit_terminal_input(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id}

    def resize_terminal(self, session_id, rows, cols):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id, "rows": rows, "cols": cols}

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
            "launch_mode": "web_terminal",
            "session_status": "COMPLETED",
            "recovery_status": "RESTORED",
            "integrity_status": "VERIFIED",
            "policy_id": "basic",
            "policy_version": "1.0",
            "actions": self.get_run_actions(session_id),
            "sensor_summary": [
                {
                    "sensor": "AGENT_HOOK",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
                {
                    "sensor": "FILESYSTEM_WATCHER",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
                {
                    "sensor": "PROCESS_RUNTIME",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
            ],
            "limitations": ["Local console does not provide remote access."],
        }

    def get_recovery_status(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "available": True,
            "workspace_matches": False,
            "status": "NOT_ATTEMPTED",
            "integrity_status": "NOT_CHECKED",
            "manual_recovery": False,
            "reason": None,
        }

    def restore_run(self, session_id, *, confirm):
        if session_id != "run-1":
            raise KeyError(session_id)
        if confirm is not True:
            raise ValueError("전체 Workspace 복구 확인이 필요합니다.")
        return {
            "session_id": session_id,
            "recovery_result": {"recovery_status": "RESTORED"},
            "integrity_result": {"integrity_status": "VERIFIED"},
        }

    def get_report(self, session_id):
        return "# AIA Security Report\n"

    def get_result_json(self, session_id):
        return b'{"bundle_status":"VALID"}'

    def request_stop(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id, "status": "STOP_REQUESTED"}

    def reconcile_orphaned_run(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "reconciled": True,
            "session_id": session_id,
            "reason": "ORPHAN_RECONCILED_AFTER_ROOT_CHECK",
        }

    def get_raw_evidence(self, session_id):
        return [{"evidence_id": "e1", "payload_keys": ["operation"]}]

    def shutdown(self, wait=True):
        return None


class UnreadableRunService(FakeService):
    def get_run_status(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")

    def get_result(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")

    def get_run_actions(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")


def test_unreadable_run_record_returns_safe_integrity_reason_not_raw_exception() -> None:
    client = TestClient(create_app(UnreadableRunService()))

    for path in ("/api/runs/run-1/result", "/api/runs/run-1/actions"):
        response = client.get(path)
        assert response.status_code == 409
        assert response.json() == {"error": "Evidence Bundle 무결성 검증 실패"}
        assert "Evidence Bundle Integrity Failure" not in response.text


def test_result_api_returns_the_expected_shape() -> None:
    service = FakeService()
    client = TestClient(create_app(service))

    response = client.get("/api/runs/run-1/result")

    assert response.status_code == 200
    assert response.json() == service.get_result("run-1")


def test_result_api_returns_safe_reason_on_integrity_failure() -> None:
    client = TestClient(create_app(UnreadableRunService()))

    response = client.get("/api/runs/run-1/result")

    assert response.status_code == 409
    assert response.json() == {"error": "Evidence Bundle 무결성 검증 실패"}


def test_incident_api_returns_the_expected_shape() -> None:
    service = FakeService()
    client = TestClient(create_app(service))

    response = client.get("/api/runs/run-1/incidents/a1")

    assert response.status_code == 200
    assert response.json() == service.get_incident("run-1", "a1")


def test_incident_api_returns_not_found_for_unknown_incident() -> None:
    class NoIncidentService(FakeService):
        def get_incident(self, session_id, action_id):
            raise KeyError(action_id)

    client = TestClient(create_app(NoIncidentService()))

    response = client.get("/api/runs/run-1/incidents/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Incident not found"}


def test_console_info_api_returns_cli_prefix_and_hook_path() -> None:
    client = TestClient(create_app(FakeService()))

    api_response = client.get("/api/console-info")

    assert api_response.status_code == 200
    body = api_response.json()
    assert body["cli_prefix"] == _console_cli_prefix()
    assert body["hook_path"] == str(CodexHookInstaller().path)


def test_spa_route_serves_built_index_or_a_clear_placeholder() -> None:
    client = TestClient(create_app(FakeService()))

    for path in ("/", "/runs/run-1", "/some/deep/link"):
        response = client.get(path)
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert "<div id=\"root\">" in response.text
        else:
            assert "npm run build" in response.text


def test_hook_setup_endpoint_installs_hook_without_terminal_command(tmp_path, monkeypatch) -> None:
    import importlib

    web_app = importlib.import_module("aia_web.app")

    class FakeInstaller:
        path = tmp_path / "hooks.json"

        def install(self):
            self.path.write_text('{"hooks": {}}', encoding="utf-8")
            return self.path

        def is_posttool_installed(self):
            return True

    monkeypatch.setattr(web_app, "CodexHookInstaller", FakeInstaller)
    response = TestClient(create_app(FakeService())).post("/api/hook/setup")

    assert response.status_code == 200
    assert response.json()["installed"] is True
    assert response.json()["posttool_installed"] is True
    assert response.json()["trust_required"] is True
    assert response.json()["hook_path"] == str(tmp_path / "hooks.json")


def test_workbench_terminal_socket_accepts_input_and_resize() -> None:
    client = TestClient(create_app(FakeService()))
    with client.websocket_connect("/api/runs/run-1/terminal") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "status"
        assert first["status"] == "RUNNING"
        websocket.send_json({"type": "input", "data": "hello"})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "input"
        websocket.send_json({"type": "submit"})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "submit"
        websocket.send_json({"type": "resize", "rows": 40, "cols": 140})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "resize"
        assert accepted["cols"] == 140


def test_workbench_terminal_status_checks_are_throttled() -> None:
    class CountingService(FakeService):
        def __init__(self):
            super().__init__()
            self.terminal_status_calls = 0

        def get_terminal_status(self, session_id):
            self.terminal_status_calls += 1
            return super().get_terminal_status(session_id)

    service = CountingService()
    client = TestClient(create_app(service))
    with client.websocket_connect("/api/runs/run-1/terminal") as websocket:
        assert websocket.receive_json()["type"] == "status"
        time.sleep(0.85)

    # The socket loop still notices a terminal exit quickly, but it does not
    # query the PTY on every 100 ms output tick when no status changed.
    assert 2 <= service.terminal_status_calls <= 5


def test_workbench_terminal_socket_replays_bounded_output_after_reconnect() -> None:
    class ReplayService(FakeService):
        _output = [
            {"type": "output", "sequence": 1, "data": "first", "recorded_at": "2026-01-01T00:00:00+00:00"},
            {"type": "output", "sequence": 2, "data": "second", "recorded_at": "2026-01-01T00:00:01+00:00"},
        ]

        def read_terminal_output(self, session_id, *, after_sequence=0):
            super().read_terminal_output(session_id, after_sequence=after_sequence)
            return [item for item in self._output if item["sequence"] > after_sequence]

    client = TestClient(create_app(ReplayService()))
    with client.websocket_connect("/api/runs/run-1/terminal") as first_connection:
        first_batch = first_connection.receive_json()
        assert first_batch["sequence"] == 2
        assert first_batch["data"] == "firstsecond"
        assert first_connection.receive_json()["type"] == "status"

    with client.websocket_connect("/api/runs/run-1/terminal") as second_connection:
        second_batch = second_connection.receive_json()
        assert second_batch["sequence"] == 2
        assert second_batch["data"] == "firstsecond"


def test_large_terminal_replay_is_coalesced_without_losing_order() -> None:
    items = [
        {
            "type": "output",
            "sequence": index,
            "data": f"chunk-{index}",
            "recorded_at": f"2026-01-01T00:00:{index:02d}+00:00",
        }
        for index in range(1, 41)
    ]

    batches = _coalesce_terminal_output(items)

    assert len(batches) < len(items)
    assert [batch["sequence"] for batch in batches] == [40]
    assert "".join(batch["data"] for batch in batches) == "".join(item["data"] for item in items)


def test_small_live_terminal_output_is_batched_to_reduce_transport_churn() -> None:
    items = [
        {
            "type": "output",
            "sequence": 1,
            "data": "first",
            "recorded_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "type": "output",
            "sequence": 2,
            "data": "second",
            "recorded_at": "2026-01-01T00:00:01+00:00",
        },
    ]

    batches = _coalesce_terminal_output(items)

    assert len(batches) == 1
    assert batches[0]["sequence"] == 2
    assert batches[0]["data"] == "firstsecond"


def test_frozen_console_reuses_trusted_desktop_entrypoint_for_diagnostics(
    monkeypatch, tmp_path
) -> None:
    web_module = importlib.import_module("aia_web.app")
    desktop_path = tmp_path / "AIA.exe"
    desktop_path.touch()

    monkeypatch.setattr(web_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(web_module.sys, "executable", str(desktop_path))

    command = _aia_cli_command("hook", "verify", "--json")

    assert command == [str(desktop_path), "hook", "verify", "--json"]
    assert "-m" not in command


def test_frozen_console_prefers_sibling_cli_for_diagnostics(monkeypatch, tmp_path) -> None:
    web_module = importlib.import_module("aia_web.app")
    desktop_path = tmp_path / "AIA" / "AIA.exe"
    desktop_path.parent.mkdir(parents=True)
    desktop_path.touch()
    cli_path = tmp_path / "aia-cli" / "aia-cli.exe"
    cli_path.parent.mkdir(parents=True)
    cli_path.touch()

    monkeypatch.setattr(web_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(web_module.sys, "executable", str(desktop_path))

    assert _aia_cli_command("doctor") == [str(cli_path), "doctor"]


def test_source_console_uses_python_module_cli(monkeypatch) -> None:
    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module.sys, "frozen", False, raising=False)
    monkeypatch.setattr(web_module.sys, "executable", "python-test")

    assert _aia_cli_command("doctor") == ["python-test", "-m", "aia.cli", "doctor"]


def test_console_can_request_hook_verification_without_changing_trust(monkeypatch) -> None:
    def fake_verify(control_root, *, timeout=180.0):
        assert timeout == 180.0
        return {"verified": True, "reason": "SESSION_BOUND_HOOK_EVENT_OBSERVED"}, 200

    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_run_hook_verification", fake_verify)
    client = TestClient(create_app(FakeService()))

    response = client.post("/api/hook/verify")

    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_console_maps_validation_errors_to_bad_request() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.post("/api/runs", json={"workspace": "invalid", "task": "inspect"})
    assert response.status_code == 400
    assert "workspace validation failed" in response.json()["error"]


def test_console_policy_preview_is_non_executing_and_returns_decision() -> None:
    client = TestClient(create_app(FakeService()))

    response = client.post(
        "/api/policy/preview",
        json={"operation": "READ", "path": ".env"},
    )

    assert response.status_code == 200
    assert response.json()["policy_decision"] == "VIOLATION"
    assert response.json()["asset_type"] == "SECRET"

    invalid = client.post(
        "/api/policy/preview",
        json={"operation": "READ", "path": "invalid"},
    )
    assert invalid.status_code == 400
    assert "policy preview failed" in invalid.json()["error"]


def test_console_supports_session_first_interactive_run() -> None:
    service = FakeService()
    client = TestClient(create_app(service))

    created = client.post(
        "/api/runs",
        json={"workspace": "C:/workspace", "interactive": True},
    )
    assert created.status_code == 202
    assert service.created_payloads[-1]["interactive"] is True


def test_many_finished_runs_api_responses_match_with_cached_parsing(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    sessions_root = control_root / "sessions"
    sessions_root.mkdir(parents=True)
    for index in range(150):
        fixture_root = tmp_path / "fixtures" / str(index)
        session, store, _action = _session(fixture_root)
        SessionFinalizer(evidence_store=store).finalize(
            session,
            process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        )
        source = fixture_root / "control" / "sessions" / session.session_id
        shutil.move(str(source), str(sessions_root / session.session_id))

    codex_executable = tmp_path / "codex.exe"
    codex_executable.write_bytes(b"codex fixture")
    monkeypatch.setattr(
        CodexAdapter,
        "_path_candidates",
        lambda _self: (codex_executable,),
    )
    monkeypatch.setattr(CodexAdapter, "_windows_install_candidates", lambda _self: ())
    version_probes = 0

    def fake_version_probe(*_args, **_kwargs):
        nonlocal version_probes
        version_probes += 1
        return subprocess.CompletedProcess([], 0, b"Codex 1.2.3", b"")

    monkeypatch.setattr(subprocess, "run", fake_version_probe)
    monkeypatch.setattr(CodexHookInstaller, "is_installed", lambda _self: False)
    monkeypatch.setattr(CodexHookInstaller, "is_posttool_installed", lambda _self: False)
    monkeypatch.setattr(CodexHookInstaller, "has_aia_runtime", lambda *_args: False)
    service = RunApplicationService(control_root)
    client = TestClient(create_app(service))
    try:
        started = time.perf_counter()
        cold_runs = client.get("/api/runs")
        cold_runs_ms = (time.perf_counter() - started) * 1000
        service._completed_runs_cache = None
        started = time.perf_counter()
        warm_runs = client.get("/api/runs")
        warm_runs_ms = (time.perf_counter() - started) * 1000

        service._completed_runs_cache = None
        service.reader._result_cache.clear()
        service.reader._metadata_cache.clear()
        started = time.perf_counter()
        cold_preflight = client.get("/api/preflight")
        cold_preflight_ms = (time.perf_counter() - started) * 1000
        service._completed_runs_cache = None
        started = time.perf_counter()
        warm_preflight = client.get("/api/preflight")
        warm_preflight_ms = (time.perf_counter() - started) * 1000
        assert cold_runs.status_code == warm_runs.status_code == 200
        assert cold_preflight.status_code == warm_preflight.status_code == 200
        assert len(cold_runs.json()["runs"]) == 150
        assert cold_runs.json() == warm_runs.json()
        assert cold_preflight.json() == warm_preflight.json()
        assert version_probes == 1
        print(
            "150-run API timings ms: "
            f"/api/runs {cold_runs_ms:.2f} -> {warm_runs_ms:.2f}; "
            f"/api/preflight {cold_preflight_ms:.2f} -> {warm_preflight_ms:.2f}"
        )
    finally:
        service.shutdown()


def test_console_policy_editor_api_validates_and_saves_strict_document(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    client = TestClient(create_app(service))
    document = {
        "정책명": "웹 사용자 정책",
        "정책ID": "web-policy",
        "정책버전": "1.0",
        "스키마버전": "1",
        "기본효과": "기록",
        "규칙": [
            {
                "규칙ID": "secret-read",
                "우선순위": 100,
                "자산유형": "비밀정보",
                "경로패턴": [".env"],
                "행위효과": {"읽기": "금지"},
            }
        ],
    }
    try:
        validated = client.post("/api/policy/validate", json={"document": document})
        assert validated.status_code == 200
        assert validated.json()["rule_count"] == 1
        saved = client.post(
            "/api/policy/save",
            json={"document": document, "path": str(tmp_path / "web-policy.json")},
        )
        assert saved.status_code == 200
        assert saved.json()["path"].endswith("web-policy.json")
        invalid = client.post(
            "/api/policy/validate",
            json={"document": {**document, "알수없는키": True}},
        )
        assert invalid.status_code == 400
    finally:
        service.shutdown()
