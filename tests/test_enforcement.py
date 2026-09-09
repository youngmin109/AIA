from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path

import psutil
import pytest

from aia import (
    ActivePolicySnapshot,
    AttributionGrade,
    AttributionReason,
    AttributionResult,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    EnforcementGateInput,
    EnforcementRoute,
    EvidenceSource,
    HookTrustStatus,
    NormalizedAction,
    Operation,
    ObservationStage,
    PolicyDecision,
    PolicyEffect,
    PolicyProfile,
    ProcessIdentity,
    ProcessRole,
    ProcessRuntimeSensorContext,
    ProtectedLaunchContext,
    ProtectedRunSession,
    RuntimePolicyEvaluation,
    SecurityAssetPolicy,
    SensorHealth,
    SensorStatus,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
)
from aia.process_identity import RootProcessRegistration


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _gate_input(tmp_path: Path, *, stage=ObservationStage.PRE_ACTION):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    control = tmp_path / "control"
    policy = SecurityAssetPolicy(
        schema_version="1.0.3",
        policy_id="policy-014",
        policy_version="1",
        default_effect=PolicyEffect.ALLOW,
        rules=(),
        profile=PolicyProfile.BASIC_DEVELOPMENT,
    )
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
    )
    session.transition(SessionStatus.PREPARING, at=NOW)
    session.transition(SessionStatus.READY, at=NOW)
    session.transition(SessionStatus.RUNNING, at=NOW)
    process = psutil.Process(os.getpid())
    identity = ProcessIdentity(os.getpid(), process.create_time())
    lease_manager = WorkspaceLeaseManager(
        control,
        process_identity_provider=lambda pid: process.create_time(),
    )
    lease = lease_manager.acquire(
        workspace,
        session.session_id,
        owner_pid=os.getpid(),
        owner_process_create_time=process.create_time(),
    )
    snapshot = ActivePolicySnapshot(
        session_id=session.session_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        profile=PolicyProfile.BASIC_DEVELOPMENT,
        frozen_at=NOW,
        artifact_path=control / "policy.json",
        sha256="policy-fingerprint",
        policy=policy,
    )
    action = NormalizedAction(
        action_id="action-014",
        aia_session_id=session.session_id,
        operation=Operation.DELETE,
        stage=stage,
        target_kind="FILE",
        observed_at=NOW,
        evidence_ids=("evidence-1",),
        evidence_sources=(EvidenceSource.AGENT_HOOK,),
        completeness="COMPLETE",
        normalizer_version="1.0.0",
        canonical_path=str(workspace / "protected.txt"),
        tool_use_id="tool-1",
        turn_id="turn-1",
    )
    evaluation = RuntimePolicyEvaluation(
        action_id=action.action_id,
        aia_session_id=session.session_id,
        operation=action.operation,
        stage=stage,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_profile=PolicyProfile.BASIC_DEVELOPMENT,
        active_policy_fingerprint=snapshot.sha256,
        policy_decision=PolicyDecision.VIOLATION,
        operation_effect=PolicyEffect.DENY,
        asset_type="CRITICAL_CODE",
        matched_rule_ids=("rule-1",),
        audit_record=False,
        evaluated_at=NOW,
    )
    attribution = AttributionResult(
        action_id=action.action_id,
        aia_session_id=session.session_id,
        grade=AttributionGrade.EXACT,
        reason_code=AttributionReason.DIRECT_TRUSTED_HOOK,
        reason="trusted test hook",
        tool_use_id="tool-1",
        turn_id="turn-1",
        agent_native_session_id="native-1",
        root_process_identity=identity,
    )
    registration = RootProcessRegistration(
        aia_session_id=session.session_id,
        workspace=workspace,
        root_process_identity=identity,
        registered_at=NOW,
        registration_source="PROTECTED_LAUNCHER",
    )
    sensor_context = ProcessRuntimeSensorContext(
        aia_session_id=session.session_id,
        workspace=workspace,
        root_process_identity=identity,
        status=SensorStatus.HEALTHY,
        started_at=NOW,
        evidence_path=control / "process.jsonl",
        health=SensorHealth(EvidenceSource.PROCESS_RUNTIME, SensorStatus.HEALTHY, NOW),
    )
    launch = ProtectedLaunchContext(
        launch_id="launch-1",
        aia_session_id=session.session_id,
        workspace=workspace,
        agent="codex",
        adapter="test",
        executable=Path("C:/Windows/System32/cmd.exe"),
        prompt_sha256="prompt",
        root_process_identity=identity,
        root_registration=registration,
        process_sensor_context=sensor_context,
        spawned_at=NOW,
        identity_registered_at=NOW,
        process_sensor_healthy_at=NOW,
        running_at=NOW,
        launch_provenance="AIA_SPAWNED_ROOT",
        hook_enforcement_ready_at=NOW,
    )
    health = tuple(
        SensorHealth(source, SensorStatus.HEALTHY, NOW)
        for source in (
            EvidenceSource.AGENT_HOOK,
            EvidenceSource.FILESYSTEM_WATCHER,
            EvidenceSource.PROCESS_RUNTIME,
        )
    )
    value = EnforcementGateInput(
        action=action,
        policy_evaluation=evaluation,
        attribution=attribution,
        session=session,
        active_policy=snapshot,
        launch_context=launch,
        workspace_lease=lease,
        sensor_health=health,
        hook_trust_status=HookTrustStatus.VERIFIED,
        checked_at=NOW,
    )
    return value, lease_manager


def test_exact_pre_action_violation_is_containment_candidate(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    result = EnforcementGate(lease_manager=manager).evaluate(value)

    assert result.decision is EnforcementDecision.CONTAIN
    assert result.route is EnforcementRoute.PRETOOL_BLOCK
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED


def test_post_action_routes_to_process_termination_without_blocked(tmp_path: Path):
    value, manager = _gate_input(tmp_path, stage=ObservationStage.POST_ACTION)
    result = EnforcementGate(lease_manager=manager).evaluate(value)

    assert result.decision is EnforcementDecision.CONTAIN
    assert result.route is EnforcementRoute.PROCESS_TERMINATION
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED


@pytest.mark.parametrize(
    "grade",
    [AttributionGrade.PROCESS, AttributionGrade.TEMPORAL, AttributionGrade.UNKNOWN],
)
def test_non_exact_violation_is_refused(tmp_path: Path, grade: AttributionGrade):
    value, manager = _gate_input(tmp_path)
    attribution = replace(value.attribution, grade=grade, reason_code=AttributionReason.INSUFFICIENT_EVIDENCE)
    result = EnforcementGate(lease_manager=manager).evaluate(replace(value, attribution=attribution))

    assert result.policy_decision == PolicyDecision.VIOLATION.value
    assert result.decision is EnforcementDecision.REFUSE
    assert result.route is EnforcementRoute.NONE
    assert result.action is EnforcementAction.NONE


def test_compliant_continues_even_with_exact_attribution(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    result = EnforcementGate(lease_manager=manager).evaluate(
        replace(value, policy_evaluation=replace(value.policy_evaluation, policy_decision=PolicyDecision.COMPLIANT))
    )

    assert result.decision is EnforcementDecision.CONTINUE
    assert result.route is EnforcementRoute.NONE
    assert result.action is EnforcementAction.NONE


def test_indeterminate_is_refused(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    result = EnforcementGate(lease_manager=manager).evaluate(
        replace(value, policy_evaluation=replace(value.policy_evaluation, policy_decision=PolicyDecision.INDETERMINATE))
    )

    assert result.decision is EnforcementDecision.REFUSE
    assert "POLICY_INDETERMINATE" in result.failure_reasons


@pytest.mark.parametrize(
    "field",
    ["action_id", "aia_session_id", "active_policy_fingerprint"],
)
def test_correlation_or_policy_mismatch_refuses(tmp_path: Path, field: str):
    value, manager = _gate_input(tmp_path)
    if field == "action_id":
        changed = replace(value.policy_evaluation, action_id="other-action")
        updated = replace(value, policy_evaluation=changed)
    elif field == "aia_session_id":
        changed = replace(value.attribution, aia_session_id="other-session")
        updated = replace(value, attribution=changed)
    else:
        changed = replace(value.policy_evaluation, active_policy_fingerprint="other-policy")
        updated = replace(value, policy_evaluation=changed)
    result = EnforcementGate(lease_manager=manager).evaluate(updated)

    assert result.decision is EnforcementDecision.REFUSE
    assert result.action is EnforcementAction.NONE


def test_audit_mode_refuses_without_automatic_control(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    value.session.mode = SessionMode.AUDIT
    result = EnforcementGate(lease_manager=manager).evaluate(value)

    assert result.decision is EnforcementDecision.REFUSE
    assert result.route is EnforcementRoute.NONE
    assert "AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT" in result.failure_reasons


def test_missing_checkpoint_is_not_a_gate_input(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    result = EnforcementGate(lease_manager=manager).evaluate(value)
    assert result.decision is EnforcementDecision.CONTAIN


def test_sensor_failure_refuses_but_preserves_violation(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    health = tuple(
        replace(item, status=SensorStatus.FAILED)
        if item.sensor is EvidenceSource.FILESYSTEM_WATCHER
        else item
        for item in value.sensor_health
    )
    result = EnforcementGate(lease_manager=manager).evaluate(replace(value, sensor_health=health))

    assert result.policy_decision == PolicyDecision.VIOLATION.value
    assert result.decision is EnforcementDecision.REFUSE
    assert result.action is EnforcementAction.NONE


def test_result_is_immutable(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    result = EnforcementGate(lease_manager=manager).evaluate(value)
    with pytest.raises((AttributeError, TypeError)):
        result.decision = EnforcementDecision.REFUSE
