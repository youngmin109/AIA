from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from aia_app.dto import CreateRunRequest, DTOValidationError, PolicyPreviewRequest
from aia_app.presenters import action_view, action_summary, incident_view, result_view, safe_event_views
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
    ProcessIdentity,
    ProcessIdentityStatus,
    SessionStatus,
)
from aia_app.service import (
    ApplicationValidationError,
    RunApplicationService,
    _sensor_summary_is_verified,
    _product_sensor_set_present,
    _sensors_runtime_healthy,
)
import aia_app.service as service_module


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


def test_create_request_supports_separate_windows_terminal_only_for_interactive() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "interactive": True, "launch_mode": "new_terminal"}
    )
    assert request.launch_mode == "new_terminal"
    with pytest.raises(DTOValidationError, match="requires interactive"):
        CreateRunRequest.from_mapping(
            {"workspace": ".", "task": "inspect", "launch_mode": "new_terminal"}
        )


def test_new_terminal_launch_maps_to_windows_create_new_console(monkeypatch) -> None:
    monkeypatch.setattr(service_module.os, "name", "nt")
    options = service_module._popen_kwargs_for_launch_mode("new_terminal")
    assert options["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    assert service_module._popen_kwargs_for_launch_mode("inherit") == {}


def test_safe_event_view_never_copies_command_or_secret() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "VIOLATION",
                "enforcement_action": "BLOCKED",
                "execution_result": "SUCCEEDED",
                "target": {
                    "target_kind": "COMMAND",
                    "raw_command": "type SUPER_SECRET",
                },
            }
        ]
    )
    assert events[0]["target_label"] == "명령 실행"
    assert "SUPER_SECRET" not in repr(events)
    assert "type SUPER_SECRET" not in repr(events)


def test_policy_editor_document_is_strictly_validated_and_can_be_saved(tmp_path) -> None:
    document = {
        "정책명": "사용자 보호 정책",
        "정책ID": "user-policy",
        "정책버전": "1.0",
        "스키마버전": "1",
        "기본효과": "기록",
        "규칙": [
            {
                "규칙ID": "deny-env-read",
                "우선순위": 100,
                "자산유형": "비밀정보",
                "경로패턴": [".env"],
                "행위효과": {"읽기": "금지"},
            }
        ],
    }
    summary = RunApplicationService.validate_policy_document(document)
    assert summary["rule_count"] == 1
    saved = RunApplicationService.save_policy_document(
        {"document": document, "path": str(tmp_path / "user-policy.json")}
    )
    assert saved["path"].endswith("user-policy.json")
    assert (tmp_path / "user-policy.json").is_file()


def test_policy_preview_request_validates_target_shape_and_unknown_fields() -> None:
    request = PolicyPreviewRequest.from_mapping(
        {"operation": "read", "path": ".env"}
    )
    assert request.operation == "READ"
    assert request.path == ".env"
    assert request.policy_profile == "PROTECTED_DEVELOPMENT"

    with pytest.raises(DTOValidationError, match="unknown request fields"):
        PolicyPreviewRequest.from_mapping(
            {"operation": "READ", "path": ".env", "asset_type": "WORKSPACE"}
        )
    with pytest.raises(DTOValidationError, match="accepts path"):
        PolicyPreviewRequest.from_mapping(
            {"operation": "READ", "path": ".env", "command": "type .env"}
        )
    with pytest.raises(DTOValidationError, match="requires command"):
        PolicyPreviewRequest.from_mapping({"operation": "EXECUTE"})


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


def test_live_status_exposes_only_filesystem_evidence_counts(tmp_path) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    record = make_record(tmp_path)
    record.status = "RUNNING"
    service.registry.add(record)
    evidence_path = (
        control_root
        / "sessions"
        / record.session_id
        / "evidence"
        / "raw-evidence.jsonl"
    )
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "source": "FILESYSTEM_WATCHER",
                "record_type": "FILESYSTEM_EVENT",
                "payload": {"src_path": "C:/private.txt"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        status = service.get_run_status(record.session_id)
        assert status["evidence_summary"]["filesystem_events"] == 1
        assert "C:/private.txt" not in repr(status)
    finally:
        service.shutdown()


def test_application_does_not_present_unverified_runtime_as_committed_run(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        service._write_runtime_state_payload(
            "stale-session",
            {
                "schema_version": 1,
                "session_id": "stale-session",
                "session": {
                    "session_id": "stale-session",
                    "status": "COMPLETED",
                    "workspace": str(tmp_path / "workspace"),
                    "agent": "codex",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "protection": {"state": "COMPLETED_DEGRADED", "hook_events": 0},
                "policy": {"id": "basic", "version": "1.0"},
                "result_available": True,
                "result_path": str(tmp_path / "control" / "missing" / "result.json"),
            },
        )

        runs = service.list_runs()

        assert runs[0]["run_classification"] == "UNVERIFIED_RUNTIME_STATE"
        assert runs[0]["bundle_status"] == "UNVERIFIED"
    finally:
        service.shutdown()


def test_application_marks_nonterminal_runtime_snapshot_as_live(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        service._write_runtime_state_payload(
            "live-session",
            {
                "schema_version": 1,
                "session_id": "live-session",
                "session": {
                    "session_id": "live-session",
                    "status": "RUNNING",
                    "workspace": str(tmp_path / "workspace"),
                    "agent": "codex",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1},
                "policy": {"id": "basic", "version": "1.0"},
                "result_available": False,
                "result_path": None,
            },
        )

        runs = service.list_runs()

        assert runs[0]["run_classification"] == "LIVE_PROTECTED_RUN"
        assert runs[0]["bundle_status"] == "PENDING"
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
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="AGENT_HOOK")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="FILESYSTEM_WATCHER")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="PROCESS_RUNTIME")),
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
            {
                "sensor": "PROCESS_RUNTIME",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
        ]
    ) is True
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
    ) is False
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


def test_product_sensor_set_requires_hook_file_and_process() -> None:
    healthy = lambda sensor: SimpleNamespace(
        health=SimpleNamespace(status="HEALTHY", sensor=sensor)
    )
    assert _product_sensor_set_present(
        tuple(healthy(name) for name in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME"))
    ) is True
    assert _product_sensor_set_present(
        (healthy("AGENT_HOOK"), healthy("FILESYSTEM_WATCHER"))
    ) is False


def test_running_state_degrades_when_product_process_sensor_is_missing(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    record.phase = "RUNNING"
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(SimpleNamespace(
            action=SimpleNamespace(
                action_id="action-live",
                operation=Operation.READ,
                target_kind=ActionTargetKind.FILE,
                canonical_path="README.md",
                evidence_ids=("evidence-live",),
            ),
            policy_evaluation=SimpleNamespace(
                policy_decision=PolicyDecision.COMPLIANT,
                matched_rule_ids=(),
                asset_type=None,
            ),
            attribution=SimpleNamespace(
                grade=AttributionGrade.EXACT,
                reason="DIRECT_TRUSTED_HOOK",
            ),
            gate_result=SimpleNamespace(
                action=EnforcementAction.NONE,
                decision=EnforcementDecision.CONTINUE,
                execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
                route=EnforcementRoute.NONE,
            ),
        ),),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="AGENT_HOOK")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="FILESYSTEM_WATCHER")),
    )
    record.runtime["launcher"] = SimpleNamespace(
        hook_broker=SimpleNamespace(is_running=True),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)
        assert record.protection_state == "ACTIVE_DEGRADED"
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
            },
            {
                "sensor": "AGENT_HOOK",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "PROCESS_RUNTIME",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
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


def test_evidence_summary_counts_safe_record_metadata() -> None:
    from aia_app.presenters import evidence_summary

    summary = evidence_summary(
        [
            {"source": "FILESYSTEM_WATCHER", "record_type": "FILESYSTEM_EVENT"},
            {"source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"},
            {"source": "AGENT_HOOK", "record_type": "POSTTOOL_OBSERVED"},
            {"source": "PROCESS_RUNTIME", "record_type": "PROCESS_OBSERVED"},
            {"source": "PROCESS_RUNTIME", "record_type": "PROCESS_EXIT_OBSERVED"},
            {"source": "FILESYSTEM_WATCHER", "record_type": "SENSOR_HEALTH"},
        ]
    )

    assert summary == {
        "available": True,
        "filesystem_events": 1,
        "pretool_events": 1,
        "posttool_events": 1,
        "process_observed": 1,
        "process_exit_observed": 1,
        "sensor_health_events": 1,
    }


def test_result_presenter_aggregates_all_action_outcomes() -> None:
    summary = action_summary(
        {
            "action_outcomes": [
                {
                    "policy_decision": "VIOLATION",
                    "enforcement_decision": "CONTAIN",
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "policy_decision": "COMPLIANT",
                    "enforcement_decision": "CONTINUE",
                    "enforcement_action": "NONE",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "policy_decision": "COMPLIANT",
                    "operation_effect": "AUDIT",
                    "enforcement_decision": "CONTINUE",
                    "enforcement_action": "NONE",
                    "execution_result": "NOT_ATTEMPTED",
                },
                {
                    "policy_decision": "INDETERMINATE",
                    "enforcement_decision": "REFUSE",
                    "enforcement_action": "NONE",
                    "execution_result": "FAILED",
                },
            ]
        }
    )

    assert summary == {
        "total": 4,
        "compliant": 2,
        "audit": 1,
        "violation": 1,
        "indeterminate": 1,
        "contain": 1,
        "blocked": 1,
        "terminated": 0,
        "execution_succeeded": 2,
        "execution_failed": 1,
        "execution_not_attempted": 1,
    }
    assert result_view(
        {"action_outcomes": [{"policy_decision": "VIOLATION"}]}, "VALID"
    )["action_summary"]["total"] == 1


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


def test_result_bundle_reader_can_read_live_metadata_without_valid_bundle(tmp_path) -> None:
    reader = ResultBundleReader(tmp_path)
    evidence_path = tmp_path / "sessions" / "session-1" / "evidence" / "raw-evidence.jsonl"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_id": "e1",
                "source": "AGENT_HOOK",
                "record_type": "PRETOOL_REQUEST",
                "payload": {"command": "secret command"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metadata = reader.read_evidence_metadata("session-1", require_valid=False)

    assert metadata[0]["record_type"] == "PRETOOL_REQUEST"
    assert "command" in metadata[0]["payload_keys"]
    assert "secret command" not in repr(metadata)


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
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
            "CUSTOM",
        }
        assert all(item["description"] for item in profiles)
    finally:
        service.shutdown()


def test_application_policy_preview_uses_resolved_protected_profile(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        blocked = service.preview_policy({"operation": "READ", "path": ".env"})
        assert blocked["policy_decision"] == "VIOLATION"
        assert blocked["operation_effect"] == "DENY"
        assert blocked["asset_type"] == "SECRET"
        assert blocked["matched_rule_ids"] == ["protected-secret-files"]

        allowed = service.preview_policy(
            {"operation": "MODIFY", "path": "src/app.py"}
        )
        assert allowed["policy_decision"] == "COMPLIANT"
        assert allowed["operation_effect"] == "AUDIT"
        assert allowed["asset_type"] is None
        assert allowed["matched_rule_ids"] == []
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
        assert result["readiness_code"] == "READY"
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


def test_application_preflight_reports_actual_trusted_hook_status(tmp_path, monkeypatch) -> None:
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
        lambda _installer: True,
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
                        {"event": "preToolUse", "trust_status": "TRUSTED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["hook_trust"]["status"] == "TRUSTED"
        assert "신뢰된 상태" in result["hook_trust"]["detail"]
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
                        {"event": "preToolUse", "trust_status": "TRUSTED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["ready"] is False
        assert result["readiness_code"] == "HOOK_VERIFICATION_REQUIRED"
        assert "hook verify" in result["next_step"]
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["hook_verification"]["ok"] is False
        assert "hook verify" in checks["hook_verification"]["detail"]
    finally:
        service.shutdown()


def test_application_preflight_exposes_untrusted_hook_remediation(
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
        assert result["ready"] is False
        assert result["readiness_code"] == "CODEX_HOOK_TRUST_REQUIRED"
        assert "/hooks" in result["next_step"]
        assert "aia hook verify" in result["next_step"]
    finally:
        service.shutdown()


def test_application_create_rejects_currently_untrusted_hook(
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
        "aia_app.service.HookVerificationStore.is_current",
        lambda self, installer, executable: True,
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
        with pytest.raises(ApplicationValidationError, match="Hook Trust"):
            service.create_protected_run(
                {"workspace": str(tmp_path), "task": "inspect"}
            )
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


def test_new_run_persists_aia_coordinator_identity(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    service._run = lambda record: None
    try:
        created = service.create_protected_run(
            {"workspace": str(tmp_path), "task": "inspect"}
        )
        state = service._read_runtime_state(created["session_id"])
        assert state["coordinator"]["pid"] > 0
        assert state["coordinator"]["create_time"] >= 0
        assert state["managed_process"] is None
    finally:
        service.shutdown()


def test_runtime_state_persists_verified_agent_root_identity(tmp_path) -> None:
    record = make_record(tmp_path)
    record.runtime["launch_context"] = SimpleNamespace(
        launch_id="launch-1",
        launch_provenance="AIA_SPAWNED_ROOT",
        root_process_identity=ProcessIdentity(pid=4243, create_time=20.0),
    )

    state = RunApplicationService._runtime_state_mapping(record)

    assert state["managed_process"] == {
        "launch_id": "launch-1",
        "launch_provenance": "AIA_SPAWNED_ROOT",
        "root_process_identity": {"pid": 4243, "create_time": 20.0},
    }


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


def test_request_stop_can_terminate_a_verified_root_during_launch(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    record.phase = "LAUNCHING"

    class Launcher:
        status = SimpleNamespace(value="STARTING")

        @staticmethod
        def request_user_abort() -> bool:
            return True

    record.runtime["launcher"] = Launcher()
    service.registry.add(record)
    try:
        result = service.request_stop(record.session_id)
        assert result["accepted"] is True
        assert result["reason"] == "USER_ABORT_DURING_LAUNCH"
        assert record.stop_requested is True
        assert record.protection_state == "STOP_REQUESTED"
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


def test_wait_for_agent_stops_managed_tree_when_hook_broker_is_lost(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    service.registry.add(record)

    class Process:
        def __init__(self):
            self.calls = 0

        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("codex", timeout)
            return 0

    class Launcher:
        hook_broker = SimpleNamespace(is_running=False)

        @staticmethod
        def request_protection_failure_termination_result(reason):
            return {
                "termination_id": "protection-failure-1",
                "status": "SUCCEEDED",
                "outcome": "TERMINATED",
                "verified_tree_gone": True,
                "reason": reason,
                "control": "PROTECTION_FAILURE",
            }

    try:
        assert service._wait_for_agent(record, Process(), Launcher()) == 0
        assert record.protection_state == "DEGRADED"
        assert record.runtime["protection_failure_reason"] == "HOOK_BROKER_LOST"
        assert record.runtime["protection_failure_termination_result"]["status"] == "SUCCEEDED"
    finally:
        service.shutdown()


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


def test_launching_phase_is_visible_while_codex_is_being_registered(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    try:
        service.registry.add(record)
        service._phase(record, "LAUNCHING", SessionStatus.READY)
        record.protection_state = "LAUNCHING"
        status = service.get_run_status(record.session_id)
        assert status["phase"] == "LAUNCHING"
        assert status["session"]["status"] == "READY"
        assert status["protection"]["state"] == "LAUNCHING"
    finally:
        service.shutdown()


def test_launching_phase_is_visible_from_persisted_runtime_state(tmp_path) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    record = make_record(tmp_path)
    observer = RunApplicationService(control_root)
    try:
        service.registry.add(record)
        record.protection_state = "LAUNCHING"
        service._phase(record, "LAUNCHING", SessionStatus.READY)
        status = observer.get_run_status(record.session_id)
        assert status["phase"] == "LAUNCHING"
        assert status["protection"]["state"] == "LAUNCHING"
    finally:
        observer.shutdown()
        service.shutdown()


def _orphaned_runtime_state(session_id: str = "session-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "coordinator": {"pid": 4242, "create_time": 10.0},
        "managed_process": {
            "launch_id": "launch-1",
            "launch_provenance": "AIA_SPAWNED_ROOT",
            "root_process_identity": {"pid": 4243, "create_time": 20.0},
        },
        "session": {
            "agent": "codex",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": None,
            "session_id": session_id,
            "status": "RUNNING",
            "workspace": "C:\\workspace\\orphaned",
        },
        "phase": "RUNNING",
        "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1},
        "checkpoint": "READY",
        "lease": "ACTIVE",
        "mode": "ENFORCE",
        "policy": {"id": "policy", "profile": "BASIC_DEVELOPMENT", "version": "1.0.0"},
        "incident_count": 0,
        "latest_actions": [],
        "sensor_health": {},
        "stop": {"requested": False, "error": None},
        "error": None,
        "result_path": None,
        "result_available": False,
    }


def test_persisted_run_reports_orphaned_when_coordinator_is_gone(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    def verify(identity):
        return ProcessIdentityStatus.PROCESS_GONE

    monkeypatch.setattr("aia_app.service.verify_process_identity", verify)
    state = _orphaned_runtime_state()
    service._write_runtime_state_payload("session-1", state)
    try:
        status = service.get_run_status("session-1")
        assert status["session"]["status"] == "RUNNING"
        assert status["protection"]["state"] == "ORPHANED_DEGRADED"
        assert status["runtime_reconciliation"]["orphaned"] is True
        assert status["runtime_reconciliation"]["action"] == "REVIEW_AND_RESTART"
    finally:
        service.shutdown()


def test_orphan_reconcile_requires_recorded_agent_root_to_be_gone(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    def verify(identity):
        return (
            ProcessIdentityStatus.PROCESS_GONE
            if identity.pid == 4242
            else ProcessIdentityStatus.LIVE_MATCH
        )

    monkeypatch.setattr("aia_app.service.verify_process_identity", verify)
    service._write_runtime_state_payload("session-1", _orphaned_runtime_state())
    try:
        result = service.reconcile_orphaned_run("session-1")
        assert result["reconciled"] is False
        assert result["reason"] == "RECORDED_AGENT_ROOT_NOT_PROVEN_GONE"
        assert not service._read_runtime_state("session-1").get("orphan_reconciliation")
    finally:
        service.shutdown()


def test_orphan_reconcile_acknowledges_only_after_agent_root_identity_is_gone(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", _orphaned_runtime_state())
    try:
        result = service.reconcile_orphaned_run("session-1")
        assert result["reconciled"] is True
        assert result["reason"] == "ORPHAN_RECONCILED_AFTER_ROOT_CHECK"
        assert result["runtime_reconciliation"]["action"] == "RECONCILED"
        persisted = service._read_runtime_state("session-1")
        assert persisted["orphan_reconciliation"]["status"] == "ACKNOWLEDGED"
    finally:
        service.shutdown()


def test_new_run_refuses_workspace_with_unresolved_orphaned_agent(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    state = _orphaned_runtime_state()
    state["session"]["workspace"] = str(tmp_path)
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: (
            ProcessIdentityStatus.PROCESS_GONE
            if identity.pid == 4242
            else ProcessIdentityStatus.LIVE_MATCH
        ),
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        with pytest.raises(ApplicationValidationError, match="정리되지 않은 이전 Protected Run"):
            service.create_protected_run({"workspace": str(tmp_path), "task": "inspect"})
    finally:
        service.shutdown()


def test_new_run_allows_workspace_after_orphan_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    service._run = lambda record: None
    state = _orphaned_runtime_state()
    state["session"]["workspace"] = str(tmp_path)
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        assert service.reconcile_orphaned_run("session-1")["reconciled"] is True
        created = service.create_protected_run({"workspace": str(tmp_path), "task": "inspect"})
        assert created["session_id"]
    finally:
        service.shutdown()
