from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from aia_app.dto import CreateRunRequest, DTOValidationError
from aia_app.presenters import action_view, incident_view, result_view
from aia_app.readers import ResultBundleReader
from aia_app.registry import RunRecord, RunRegistry
from aia import (
    ActionTargetKind,
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementRoute,
    Operation,
    PolicyDecision,
)
from aia_app.service import (
    ApplicationValidationError,
    RunApplicationService,
    _sensor_summary_is_verified,
    _sensors_runtime_healthy,
)


def make_record(tmp_path, session_id: str = "session-1") -> RunRecord:
    return RunRecord(
        session_id=session_id,
        workspace=tmp_path,
        agent="codex",
        model=None,
        policy_profile="BASIC_DEVELOPMENT",
        policy_id="basic-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="inspect",
        created_at=datetime.now(timezone.utc),
    )


def test_create_request_rejects_unknown_fields_and_bounds_task() -> None:
    with pytest.raises(DTOValidationError, match="unknown request fields"):
        CreateRunRequest.from_mapping({"workspace": ".", "unexpected": True})
    with pytest.raises(DTOValidationError, match="too large"):
        CreateRunRequest.from_mapping({"workspace": ".", "task": "x" * 50_001})


def test_create_request_normalizes_mode_and_preserves_explicit_profile() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "mode": "audit", "policy_profile": "CONSERVATIVE_SECURITY"}
    )
    assert request.mode == "AUDIT"
    assert request.policy_profile == "CONSERVATIVE_SECURITY"


def test_create_request_can_explicitly_open_interactive_session() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "interactive": True}
    )

    assert request.interactive is True
    assert request.task == ""


def test_registry_snapshot_excludes_runtime_and_isolated_lists(tmp_path) -> None:
    registry = RunRegistry()
    record = make_record(tmp_path)
    record.runtime["secret"] = "internal"
    record.actions.append({"action_id": "a1"})
    registry.add(record)
    snapshot = registry.snapshot(record.session_id)
    assert snapshot is not None
    assert snapshot.runtime == {}
    snapshot.actions.append({"action_id": "a2"})
    assert registry.require(record.session_id).actions == [{"action_id": "a1"}]


def test_registry_snapshots_exclude_runtime(tmp_path) -> None:
    registry = RunRegistry()
    record = make_record(tmp_path)
    record.runtime["secret"] = "internal"
    registry.add(record)

    snapshots = registry.snapshots()

    assert len(snapshots) == 1
    assert snapshots[0].runtime == {}


def test_application_lists_live_runs_without_runtime_contents(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["secret"] = "do-not-expose"
    service.registry.add(record)
    try:
        runs = service.list_runs()
        assert runs[0]["session_id"] == record.session_id
        assert "do-not-expose" not in repr(runs)
        assert runs[0]["protection_state"] == "STARTING"
    finally:
        service.shutdown()


def test_live_refresh_exposes_redacted_hook_action_before_run_finishes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    action = SimpleNamespace(
        action_id="action-live",
        operation=Operation.DELETE,
        target_kind=ActionTargetKind.FILE,
        canonical_path=".env",
        evidence_ids=("evidence-live",),
    )
    event = SimpleNamespace(
        action=action,
        policy_evaluation=SimpleNamespace(
            policy_decision=PolicyDecision.VIOLATION,
            matched_rule_ids=("deny-env",),
            asset_type=None,
        ),
        attribution=SimpleNamespace(
            grade=AttributionGrade.EXACT,
            reason="DIRECT_TRUSTED_HOOK",
        ),
        gate_result=SimpleNamespace(
            action=EnforcementAction.NONE,
            decision=EnforcementDecision.CONTAIN,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            route=EnforcementRoute.PRETOOL_BLOCK,
        ),
    )
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(event,),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY")),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)

        assert record.protection_state == "ACTIVE_VERIFIED"
        assert record.hook_event_count == 1
        assert record.actions[0]["action_id"] == "action-live"
        assert record.incidents[0]["enforcement_route"] == "PRETOOL_BLOCK"
        assert "raw_command" not in repr(record.actions)
    finally:
        service.shutdown()


def test_verified_sensor_summary_requires_healthy_runtime_and_clean_stop() -> None:
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "AGENT_HOOK",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
        ]
    ) is True
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "FAILED",
                "final_sensor_state": "STOPPED",
            }
        ]
    ) is False
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "FAILED",
            }
        ]
    ) is False
    assert _sensor_summary_is_verified([]) is False


def test_live_verified_state_requires_all_sensors_healthy(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        healthy = SimpleNamespace(health=SimpleNamespace(status="HEALTHY"))
        failed = SimpleNamespace(health=SimpleNamespace(status="FAILED"))
        assert _sensors_runtime_healthy((healthy,)) is True
        assert _sensors_runtime_healthy((healthy, failed)) is False
        assert _sensors_runtime_healthy(()) is False
    finally:
        service.shutdown()


def test_live_state_degrades_when_hook_broker_is_not_running(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY")),
    )
    record.runtime["launcher"] = SimpleNamespace(
        hook_broker=SimpleNamespace(is_running=False),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)

        assert record.protection_state == "DEGRADED"
        assert (
            service.get_run_status(record.session_id)["protection"]["hook_broker"]
            == "FAILED"
        )
    finally:
        service.shutdown()


def test_completed_bundle_requires_verified_sensor_summary(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    session_dir = tmp_path / "control" / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    base = {
        "session_status": "COMPLETED",
        "session_end_reason": "AGENT_EXITED",
        "limitations": [],
        "action_outcomes": [],
        "sensor_summary": [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            }
        ],
    }
    monkeypatch.setattr(service.reader, "read_result", lambda _session_id: dict(base))
    monkeypatch.setattr(
        service.reader,
        "verification",
        lambda _session_id: SimpleNamespace(status=SimpleNamespace(value="VALID")),
    )
    monkeypatch.setattr(service.reader, "hook_event_count", lambda _session_id: 1)
    try:
        assert service._status_from_completed_bundle("session-1")["protection"]["state"] == "COMPLETED_VERIFIED"
        base["sensor_summary"][0]["final_sensor_state"] = "FAILED"
        assert service._status_from_completed_bundle("session-1")["protection"]["state"] == "COMPLETED_DEGRADED"
        base["sensor_summary"][0]["final_sensor_state"] = "STOPPED"
        base["limitations"] = ["HOOK_BROKER_RUNTIME_NOT_VERIFIED"]
        assert service._status_from_completed_bundle("session-1")["protection"]["state"] == "COMPLETED_DEGRADED"
    finally:
        service.shutdown()


def test_recovery_is_requested_only_for_post_action_termination(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["lease_manager"] = object()
    termination = object()
    gate = SimpleNamespace(route=EnforcementRoute.PROCESS_TERMINATION)
    record.runtime["process_termination_result"] = termination
    record.runtime["post_action_gate_results"] = (gate,)
    calls: dict[str, object] = {}

    class FakeRecoveryCoordinator:
        def __init__(self, lease_manager) -> None:
            calls["lease_manager"] = lease_manager

        def recover(self, gate_result, termination_result, **kwargs):
            calls["gate_result"] = gate_result
            calls["termination_result"] = termination_result
            calls["kwargs"] = kwargs
            return SimpleNamespace(
                verified_recovery_success=True,
                integrity_result=SimpleNamespace(integrity_status="VERIFIED"),
            )

    monkeypatch.setattr("aia_app.service.RecoveryCoordinator", FakeRecoveryCoordinator)
    session = SimpleNamespace(session_id=record.session_id, workspace=tmp_path)
    launch_context = SimpleNamespace(launch_id="launch-1")
    try:
        result = service._recover_after_containment(
            record,
            session=session,
            preparation=object(),
            checkpoint=object(),
            lease=object(),
            launch_context=launch_context,
        )

        assert result.verified_recovery_success is True
        assert calls["lease_manager"] is record.runtime["lease_manager"]
        assert calls["gate_result"] is gate
        assert calls["termination_result"] is termination
        assert calls["kwargs"]["expected_launch_id"] == "launch-1"
        assert record.runtime["recovery_verification"] is result
    finally:
        service.shutdown()


def test_pretool_only_block_does_not_trigger_recovery(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["process_termination_result"] = object()
    record.runtime["post_action_gate_results"] = (
        SimpleNamespace(route=EnforcementRoute.PRETOOL_BLOCK),
    )
    monkeypatch.setattr(
        "aia_app.service.RecoveryCoordinator",
        lambda _lease_manager: pytest.fail("Recovery must not run for a pre-tool deny"),
    )
    try:
        result = service._recover_after_containment(
            record,
            session=SimpleNamespace(session_id=record.session_id, workspace=tmp_path),
            preparation=object(),
            checkpoint=object(),
            lease=object(),
            launch_context=SimpleNamespace(launch_id="launch-1"),
        )
        assert result is None
    finally:
        service.shutdown()


def test_presenters_keep_sensitive_target_values_out_of_views() -> None:
    action = {
        "action_id": "a1",
        "operation": "MODIFY",
        "policy_decision": "VIOLATION",
        "attribution_grade": "EXACT",
        "attribution_reason": "hook and process evidence",
        "enforcement_action": "CONTAIN",
        "execution_result": "SUCCEEDED",
        "target": {
            "canonical_path": "C:/workspace/app.py",
            "raw_command": "echo SUPER_SECRET",
            "payload": "SUPER_SECRET",
        },
    }
    view = action_view(action)
    assert view["target"]["display"] == "C:/workspace/app.py"
    assert "raw_command" not in view["target"]
    assert "SUPER_SECRET" not in repr(view)
    incident = incident_view(action)
    assert incident is not None
    assert incident["attribution_class"] == "EXACT"


def test_result_presenter_exposes_recovery_and_integrity_as_separate_axes() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "recovery_result": {"status": "RESTORED"},
            "integrity_result": {"status": "FAILED"},
            "action_outcomes": [],
        },
        "VALID",
    )
    assert view["recovery_status"] == "RESTORED"
    assert view["integrity_status"] == "FAILED"
    assert view["bundle_status"] == "VALID"


def test_result_presenter_exposes_redacted_recovery_and_integrity_counts() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "ABORTED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "recovery_result": {
                "recovery_status": "RESTORED",
                "planned_operation_count": 3,
                "succeeded_operation_count": 3,
                "failed_operation_count": 0,
                "restored_paths": ["a.py", "b.py"],
            },
            "integrity_result": {
                "integrity_status": "VERIFIED",
                "expected_entry_count": 4,
                "actual_entry_count": 4,
                "verification_errors": [],
            },
            "action_outcomes": [],
        },
        "VALID",
    )
    assert view["recovery_summary"]["succeeded_operations"] == 3
    assert view["recovery_summary"]["restored_paths"] == 2
    assert view["integrity_summary"]["expected_entries"] == 4
    assert view["integrity_summary"]["verification_errors"] == 0


def test_result_presenter_exposes_codex_block_confirmation() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "block_confirmation_available": True,
                    "reason": "CODEX_HOOK_BLOCKED_EVENT",
                }
            },
            "action_outcomes": [
                {
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                }
            ],
        },
        "VALID",
    )

    assert view["codex_block_confirmation"] == "BLOCK_CONFIRMED"
    assert view["codex_block_confirmation_reason"] == "CODEX_HOOK_BLOCKED_EVENT"


def test_result_presenter_exposes_effective_codex_execution_policy() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "effective_sandbox": "read-only",
                    "effective_approval_policy": "never",
                }
            },
            "action_outcomes": [],
        },
        "VALID",
    )

    assert view["execution_policy_status"] == "DEGRADED"
    assert view["requested_sandbox"] == "workspace-write"
    assert view["effective_sandbox"] == "read-only"
    assert view["effective_approval_policy"] == "never"


def test_result_presenter_does_not_confirm_from_output_metadata_alone() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "block_confirmation_available": True,
                    "reason": "CODEX_BLOCK_AND_NO_RUN_MESSAGE",
                }
            },
            "action_outcomes": [
                {
                    "enforcement_action": "NONE",
                    "execution_result": "FAILED",
                }
            ],
        },
        "VALID",
    )

    assert view["codex_block_confirmation"] == "NOT_CONFIRMED"


def test_result_presenter_marks_action_incidents_for_result_links() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "action_outcomes": [
                {
                    "action_id": "a1",
                    "operation": "DELETE",
                    "policy_decision": "VIOLATION",
                    "attribution_grade": "EXACT",
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                    "target": {"canonical_path": "secret.txt"},
                },
            ],
        },
        "VALID",
    )
    assert view["actions"][0]["incident"] is True


def test_result_bundle_reader_rejects_path_traversal_and_unverified_bundle(tmp_path) -> None:
    reader = ResultBundleReader(tmp_path)
    with pytest.raises(ValueError, match="invalid session_id"):
        reader.session_directory("../secret")
    with pytest.raises(ValueError, match="Integrity Failure"):
        reader.read_result("missing-session")


def test_result_bundle_reader_preserves_protection_downgrade_in_history(
    tmp_path,
    monkeypatch,
) -> None:
    reader = ResultBundleReader(tmp_path)
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    monkeypatch.setattr(
        reader,
        "read_result",
        lambda _session_id: {
            "session_status": "COMPLETED",
            "session_end_reason": "AGENT_EXITED",
            "limitations": ["CODEX_APPROVAL_POLICY_DOWNGRADED"],
            "action_outcomes": [],
        },
    )
    monkeypatch.setattr(
        reader,
        "verification",
        lambda _session_id: SimpleNamespace(status=SimpleNamespace(value="VALID")),
    )
    monkeypatch.setattr(reader, "hook_event_count", lambda _session_id: 1)
    monkeypatch.setattr(reader, "posttool_event_count", lambda _session_id: 0)

    runs = reader.list_completed()

    assert runs[0]["protection_state"] == "COMPLETED_DEGRADED"


def test_application_exposes_fixed_profile_choices(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        profiles = service.policy_profiles()
        assert {item["value"] for item in profiles} == {
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
            "CUSTOM",
        }
        assert all(item["description"] for item in profiles)
    finally:
        service.shutdown()


def test_application_preflight_reports_required_and_optional_hook_state(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_posttool_installed",
        lambda _installer: False,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["ready"] is True
        assert result["hook_trust"]["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["hook_activation"]["status"] == "NOT_OBSERVED"
        assert result["protection_claim"]["status"] == "CLAIM_ALLOWED_AFTER_SESSION_EVENT"
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["pretool_hook"]["ok"] is True
        assert checks["posttool_hook"]["optional"] is True
        assert checks["posttool_hook"]["ok"] is False
        assert checks["codex_hook_trust"]["optional"] is True
        assert checks["codex_hook_trust"]["ok"] is False
        assert result["codex_hook_trust"]["hooks"][0]["trust_status"] == "MODIFIED"
    finally:
        service.shutdown()


def test_application_preflight_requires_live_hook_verification_when_enabled(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_posttool_installed",
        lambda _installer: True,
    )
    try:
        result = service.preflight()
        assert result["ready"] is False
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["hook_verification"]["ok"] is False
        assert "hook verify" in checks["hook_verification"]["detail"]
    finally:
        service.shutdown()


def test_application_rejects_run_without_live_hook_verification(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    try:
        with pytest.raises(ApplicationValidationError, match="Hook 검증"):
            service.create_protected_run(
                {"workspace": str(tmp_path), "task": "inspect"}
            )
    finally:
        service.shutdown()


def test_application_rejects_invalid_workspace_before_background_launch(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        with pytest.raises(ApplicationValidationError, match="workspace validation failed"):
            service.create_protected_run(
                {"workspace": str(tmp_path / "missing"), "task": "inspect"}
            )
    finally:
        service.shutdown()


def test_application_rejects_empty_non_interactive_task(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        with pytest.raises(ApplicationValidationError, match="task is required"):
            service.create_protected_run({"workspace": str(tmp_path), "task": ""})
    finally:
        service.shutdown()


def test_application_returns_session_before_worker_finishes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    service._run = lambda record: None
    try:
        created = service.create_protected_run(
            {"workspace": str(tmp_path), "task": "inspect"}
        )
        assert created["session_id"]
        assert created["redirect_url"].endswith(created["session_id"])
        status = service.get_run_status(created["session_id"])
        assert status["protection"]["state"] == "STARTING"
    finally:
        service.shutdown()


def test_runtime_status_can_be_read_from_another_service_process(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    writer = RunApplicationService(control_root)
    record = make_record(tmp_path, session_id="session-1")
    record.status = "RUNNING"
    record.phase = "RUNNING"
    record.protection_state = "ACTIVE_VERIFIED"
    record.checkpoint = "READY"
    record.lease = "ACTIVE"
    writer.registry.add(record)
    writer._persist_runtime_state(record, strict=True)
    reader = RunApplicationService(control_root)
    monkeypatch.setattr(
        reader.reader,
        "read_result",
        lambda requested: (_ for _ in ()).throw(ValueError("not completed")),
    )
    try:
        status = reader.get_run_status(record.session_id)
        assert status["phase"] == "RUNNING"
        assert status["protection"]["state"] == "ACTIVE_VERIFIED"
        assert status["session"]["workspace"] == str(tmp_path)
    finally:
        reader.shutdown()
        writer.shutdown()


def test_list_runs_includes_runtime_state_from_another_service_process(tmp_path) -> None:
    control_root = tmp_path / "control"
    writer = RunApplicationService(control_root)
    record = make_record(tmp_path, session_id="session-1")
    record.status = "RUNNING"
    record.phase = "RUNNING"
    writer.registry.add(record)
    writer._persist_runtime_state(record, strict=True)
    reader = RunApplicationService(control_root)
    try:
        runs = reader.list_runs()
        assert runs[0]["session_id"] == "session-1"
        assert runs[0]["status"] == "RUNNING"
    finally:
        reader.shutdown()
        writer.shutdown()


def test_request_stop_marks_pending_run_without_exposing_runtime(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    service.registry.add(record)
    try:
        result = service.request_stop(record.session_id)
        assert result["accepted"] is True
        assert result["status"] == "STOP_REQUESTED"
        status = service.get_run_status(record.session_id)
        assert status["stop"]["requested"] is True
    finally:
        service.shutdown()


def test_shutdown_requests_stop_for_live_run_before_executor_closes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    record.phase = "READY"
    service.registry.add(record)
    try:
        service.shutdown(wait=True)
        assert record.stop_requested is True
        assert record.protection_state == "STOP_REQUESTED"
    finally:
        # The shutdown above is intentionally part of the assertion.  This
        # second call keeps the test safe if setup fails before that point.
        service.shutdown(wait=True)


def test_request_stop_reports_persisted_terminal_run(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        session_id = "persisted-session"
        monkeypatch.setattr(
            service.reader,
            "read_result",
            lambda requested: {"session_status": "COMPLETED"}
            if requested == session_id
            else {},
        )
        result = service.request_stop(session_id)
        assert result["accepted"] is False
        assert result["status"] == "COMPLETED"
        assert result["reason"] == "RUN_ALREADY_TERMINAL"
    finally:
        service.shutdown()


def test_request_stop_persists_cross_process_user_abort_request(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    session_id = str(uuid4())
    monkeypatch.setattr(
        service.reader,
        "read_result",
        lambda requested: (_ for _ in ()).throw(ValueError("not completed")),
    )
    try:
        result = service.request_stop(session_id)
        assert result["accepted"] is True
        assert result["reason"] == "STOP_REQUEST_STORED"
        request_path = tmp_path / "control" / "stop-requests" / f"{session_id}.json"
        assert request_path.is_file()
        assert json.loads(request_path.read_text(encoding="utf-8"))["reason"] == "USER_ABORT"
    finally:
        service.shutdown()


def test_application_failure_moves_phase_to_terminal_failed(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.phase = "READY"
    try:
        service._fail_record(record, RuntimeError("launch failed"))
        assert record.status == "FAILED"
        assert record.phase == "FAILED"
        assert "launch failed" in record.error
    finally:
        service.shutdown()
