from __future__ import annotations

import importlib
import shutil
import subprocess
import time
import types
from fastapi.testclient import TestClient

from aia_web.app import (
    _aia_cli_command,
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
    client = TestClient(create_app(UnreadableRunService()), base_url="http://127.0.0.1")

    for path in ("/api/runs/run-1/result", "/api/runs/run-1/actions"):
        response = client.get(path)
        assert response.status_code == 409
        assert response.json() == {"error": "Evidence Bundle 무결성 검증 실패"}
        assert "Evidence Bundle Integrity Failure" not in response.text


def test_result_api_returns_the_expected_shape() -> None:
    service = FakeService()
    client = TestClient(create_app(service), base_url="http://127.0.0.1")

    response = client.get("/api/runs/run-1/result")

    assert response.status_code == 200
    assert response.json() == service.get_result("run-1")


def test_retired_workbench_terminal_routes_are_not_registered() -> None:
    app = create_app(FakeService())

    route_paths = {route.path for route in app.routes}

    assert "/api/runs/{session_id}/terminal/status" not in route_paths
    assert "/api/runs/{session_id}/terminal" not in route_paths


def test_result_api_returns_safe_reason_on_integrity_failure() -> None:
    client = TestClient(create_app(UnreadableRunService()), base_url="http://127.0.0.1")

    response = client.get("/api/runs/run-1/result")

    assert response.status_code == 409
    assert response.json() == {"error": "Evidence Bundle 무결성 검증 실패"}


def test_incident_api_returns_the_expected_shape() -> None:
    service = FakeService()
    client = TestClient(create_app(service), base_url="http://127.0.0.1")

    response = client.get("/api/runs/run-1/incidents/a1")

    assert response.status_code == 200
    assert response.json() == service.get_incident("run-1", "a1")


def test_incident_api_returns_not_found_for_unknown_incident() -> None:
    class NoIncidentService(FakeService):
        def get_incident(self, session_id, action_id):
            raise KeyError(action_id)

    client = TestClient(create_app(NoIncidentService()), base_url="http://127.0.0.1")

    response = client.get("/api/runs/run-1/incidents/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Incident not found"}


def test_console_info_api_returns_cli_prefix_and_hook_path() -> None:
    client = TestClient(create_app(FakeService()), base_url="http://127.0.0.1")

    api_response = client.get("/api/console-info")

    assert api_response.status_code == 200
    body = api_response.json()
    assert body["cli_prefix"] == _console_cli_prefix()
    assert body["hook_path"] == str(CodexHookInstaller().path)


def test_spa_route_serves_built_index_or_a_clear_placeholder() -> None:
    client = TestClient(create_app(FakeService()), base_url="http://127.0.0.1")

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
    response = TestClient(create_app(FakeService()), base_url="http://127.0.0.1").post("/api/hook/setup")

    assert response.status_code == 200
    assert response.json()["installed"] is True
    assert response.json()["posttool_installed"] is True
    assert response.json()["trust_required"] is True
    assert response.json()["hook_path"] == str(tmp_path / "hooks.json")


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


def test_frozen_console_shows_the_bundled_cli_even_inside_a_checkout(monkeypatch, tmp_path) -> None:
    web_module = importlib.import_module("aia_web.app")
    desktop_path = tmp_path / "AIA" / "AIA.exe"
    desktop_path.parent.mkdir(parents=True)
    desktop_path.touch()
    cli_path = tmp_path / "aia-cli" / "aia-cli.exe"
    cli_path.parent.mkdir(parents=True)
    cli_path.touch()

    monkeypatch.setattr(web_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(web_module.sys, "executable", str(desktop_path))

    assert web_module._console_module_cli_prefix() == web_module.subprocess.list2cmdline([str(cli_path)])


def test_hook_verification_child_never_inherits_the_desktop_stdin(monkeypatch, tmp_path) -> None:
    web_module = importlib.import_module("aia_web.app")
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(stdout='{"verified": true}')

    monkeypatch.setattr(web_module.subprocess, "run", fake_run)

    payload, status = web_module._run_hook_verification(tmp_path)

    assert status == 200 and payload["verified"] is True
    assert seen["stdin"] is web_module.subprocess.DEVNULL


def test_hook_verification_start_failure_is_reported_not_a_server_error(monkeypatch, tmp_path) -> None:
    web_module = importlib.import_module("aia_web.app")

    def failing_run(command, **kwargs):
        raise OSError(6, "The handle is invalid")

    monkeypatch.setattr(web_module.subprocess, "run", failing_run)

    payload, status = web_module._run_hook_verification(tmp_path)

    assert status == 503
    assert payload == {"verified": False, "protection_claim": "PROTECTION_NOT_PROVEN", "reason": "HOOK_VERIFICATION_START_FAILED"}


def test_console_can_request_hook_verification_without_changing_trust(monkeypatch) -> None:
    def fake_verify(control_root, *, timeout=180.0):
        assert timeout == 180.0
        return {"verified": True, "reason": "SESSION_BOUND_HOOK_EVENT_OBSERVED"}, 200

    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_run_hook_verification", fake_verify)
    client = TestClient(create_app(FakeService()), base_url="http://127.0.0.1")

    response = client.post("/api/hook/verify")

    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_console_maps_validation_errors_to_bad_request() -> None:
    client = TestClient(create_app(FakeService()), base_url="http://127.0.0.1")
    response = client.post("/api/runs", json={"workspace": "invalid", "task": "inspect"})
    assert response.status_code == 400
    assert "workspace validation failed" in response.json()["error"]


def test_console_policy_preview_is_non_executing_and_returns_decision() -> None:
    client = TestClient(create_app(FakeService()), base_url="http://127.0.0.1")

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
    client = TestClient(create_app(service), base_url="http://127.0.0.1")

    created = client.post(
        "/api/runs",
        json={"workspace": "C:/workspace", "interactive": True},
    )
    assert created.status_code == 202
    assert service.created_payloads[-1]["interactive"] is True


def test_many_finished_runs_api_responses_match_with_cached_parsing(tmp_path, monkeypatch) -> None:
    run_count = 8
    control_root = tmp_path / "control"
    sessions_root = control_root / "sessions"
    sessions_root.mkdir(parents=True)
    for index in range(run_count):
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
    client = TestClient(create_app(service), base_url="http://127.0.0.1")
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
        assert len(cold_runs.json()["runs"]) == run_count
        assert cold_runs.json() == warm_runs.json()
        assert cold_preflight.json() == warm_preflight.json()
        assert version_probes == 1
        print(
            f"{run_count}-run API timings ms: "
            f"/api/runs {cold_runs_ms:.2f} -> {warm_runs_ms:.2f}; "
            f"/api/preflight {cold_preflight_ms:.2f} -> {warm_preflight_ms:.2f}"
        )
    finally:
        service.shutdown()


def test_console_policy_editor_api_validates_and_saves_strict_document(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    client = TestClient(create_app(service), base_url="http://127.0.0.1")
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


def test_saved_custom_policy_survives_an_app_restart(tmp_path) -> None:
    control = tmp_path / "control"
    service = RunApplicationService(control)
    client = TestClient(create_app(service), base_url="http://127.0.0.1")
    try:
        assert client.get("/api/policy/custom").json() == {"path": None, "document": None}
        template = client.get("/api/policy/templates/PROTECTED_DEVELOPMENT").json()["document"]
        custom = {**template, "profile": "CUSTOM", "policy_id": "aia-user-restart", "policy_version": "1"}
        saved = client.post("/api/policy/save", json={"document": custom, "path": str(tmp_path / "custom.json")})
        assert saved.status_code == 200
        # A policy saved by anything but the custom editor is not taken as the user's choice.
        other = client.post("/api/policy/save", json={"document": template, "path": str(tmp_path / "other.json")})
        assert other.status_code == 200
    finally:
        service.shutdown()

    # The desktop app starts each launch with an empty WebView profile; the server still knows.
    relaunched = RunApplicationService(control)
    client = TestClient(create_app(relaunched), base_url="http://127.0.0.1")
    try:
        remembered = client.get("/api/policy/custom").json()
        assert remembered["path"] == saved.json()["path"]
        assert remembered["document"]["rules"] == custom["rules"]
        # A file that no longer validates is never offered for a run.
        (tmp_path / "custom.json").write_text("{}", encoding="utf-8")
        assert client.get("/api/policy/custom").json() == {"path": None, "document": None}
    finally:
        relaunched.shutdown()
