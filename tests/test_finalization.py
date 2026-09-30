from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aia import (
    AttributionGrade,
    AttributionReason,
    AttributionResult,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreSealedError,
    EvidenceBundleVerifier,
    FinalizationError,
    FinalizationRefused,
    IntegrityStatus,
    IntegrityVerificationResult,
    NormalizedAction,
    NormalizationCompleteness,
    ObservationStage,
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyProfile,
    ProcessIdentityStatus,
    ProcessTerminationOutcome,
    ProcessTerminationResult,
    ProtectedRunSession,
    RawEvidenceRecord,
    RawEvidenceStore,
    RecoveryResult,
    RecoveryStatus,
    RecoveryVerificationResult,
    RuntimePolicyEvaluation,
    SessionEndReason,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    SensorHealth,
    SensorStatus,
    WorkspaceLeaseManager,
    verify_evidence_bundle,
)


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _session(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id="policy-017",
        policy_version="1.0.0",
        created_at=NOW,
    )
    session.transition(SessionStatus.PREPARING, at=NOW)
    session.transition(SessionStatus.READY, at=NOW)
    session.transition(SessionStatus.RUNNING, at=NOW)
    store = RawEvidenceStore.for_session(tmp_path / "control", session.session_id)
    evidence = store.append(
        RawEvidenceRecord(
            session_id=session.session_id,
            source=EvidenceSource.FILESYSTEM_WATCHER,
            record_type=EvidenceRecordType.FILESYSTEM_EVENT,
            captured_at=NOW,
            observation_stage=ObservationStage.POST_ACTION,
            payload={"event_type": "modified", "src_path": "protected/main.py"},
            evidence_id="evidence-017",
        )
    )
    action = NormalizedAction(
        action_id="action-017",
        aia_session_id=session.session_id,
        operation=Operation.MODIFY,
        stage=ObservationStage.POST_ACTION,
        target_kind="FILE",
        observed_at=NOW,
        evidence_ids=(evidence.evidence_id,),
        evidence_sources=(EvidenceSource.FILESYSTEM_WATCHER,),
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="canonical-v1",
        canonical_path="protected/main.py",
    )
    return session, store, action


def _gate(session: ProtectedRunSession, *, decision=EnforcementDecision.CONTINUE, action=EnforcementAction.NONE, execution=EnforcementExecutionResult.NOT_ATTEMPTED, route=EnforcementRoute.NONE):
    return EnforcementGateResult(
        action_id="action-017",
        aia_session_id=session.session_id,
        policy_decision=PolicyDecision.COMPLIANT if decision is EnforcementDecision.CONTINUE else PolicyDecision.VIOLATION,
        attribution_grade=AttributionGrade.EXACT,
        decision=decision,
        route=route,
        action=action,
        execution_result=execution,
        stage=ObservationStage.POST_ACTION,
        checked_at=NOW,
        gate_checks=(),
        failure_reasons=(),
        policy_fingerprint="policy-fingerprint",
        root_process_identity=None,
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )


def _termination(session: ProtectedRunSession):
    return ProcessTerminationResult(
        termination_id="termination-017",
        aia_session_id=session.session_id,
        launch_id="launch-017",
        decision=EnforcementDecision.CONTAIN,
        route=EnforcementRoute.PROCESS_TERMINATION,
        action=EnforcementAction.TERMINATED,
        execution_result=EnforcementExecutionResult.SUCCEEDED,
        termination_attempt_count=1,
        outcome=ProcessTerminationOutcome.TERMINATED,
        process_results=(),
        termination_requested_at=NOW,
        termination_started_at=NOW,
        termination_completed_at=NOW,
        gate_to_termination_start_ms=1,
        termination_duration_ms=1,
    )


def _policy(session: ProtectedRunSession, action: NormalizedAction, *, decision=PolicyDecision.COMPLIANT):
    return RuntimePolicyEvaluation(
        action_id=action.action_id,
        aia_session_id=session.session_id,
        operation=action.operation,
        stage=action.stage,
        policy_id=session.policy_id,
        policy_version=session.policy_version,
        policy_profile=PolicyProfile.BASIC_DEVELOPMENT,
        active_policy_fingerprint="policy-fingerprint",
        policy_decision=decision,
        operation_effect=PolicyEffect.DENY if decision is PolicyDecision.VIOLATION else PolicyEffect.ALLOW,
        asset_type="CRITICAL_CODE" if decision is PolicyDecision.VIOLATION else None,
        matched_rule_ids=("rule-017",) if decision is PolicyDecision.VIOLATION else (),
        audit_record=False,
        evaluated_at=NOW,
        path=action.canonical_path,
    )


def test_normal_exit_completes_and_commits_bundle(tmp_path: Path):
    session, store, action = _session(tmp_path)
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(action,),
        policy_evaluations=(_policy(session, action),),
    )

    assert session.status is SessionStatus.COMPLETED
    assert session.end_reason is SessionEndReason.AGENT_EXITED
    assert result.bundle_valid
    assert verify_evidence_bundle(result.bundle.result_directory).is_valid
    assert result.result.schema_version == "aia-result-1"
    assert "user_abort_termination_result" not in result.result.to_mapping()
    assert result.result.action_outcomes[0].operation_effect == "ALLOW"
    assert result.result.to_mapping()["action_outcomes"][0]["operation_effect"] == "ALLOW"
    restored = type(result.result).from_mapping(result.result.to_mapping())
    assert restored.action_outcomes[0].operation_effect == "ALLOW"


@pytest.mark.parametrize(
    "decision",
    [
        "UNSUPPORTED_TOOL_REVIEW_APPROVED",
        "UNSUPPORTED_TOOL_REVIEW_DECLINED",
        "UNSUPPORTED_TOOL_REVIEW_TIMED_OUT",
    ],
)
def test_unsupported_tool_review_decision_is_recorded_in_result_bundle(tmp_path: Path, decision: str):
    session, store, _ = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        limitations=(
            (decision, "UNSUPPORTED_TOOL_USER_APPROVED")
            if decision.endswith("APPROVED")
            else (decision,)
        ),
    )

    bundle_result = json.loads((final.bundle.result_directory / "result.json").read_text(encoding="utf-8"))
    assert final.bundle_valid
    assert decision in bundle_result["limitations"]
    if decision.endswith("APPROVED"):
        assert "UNSUPPORTED_TOOL_USER_APPROVED" in bundle_result["limitations"]


def test_security_containment_is_aborted_even_after_successful_recovery_axis(tmp_path: Path):
    session, store, action = _session(tmp_path)
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        gate_result=_gate(session, decision=EnforcementDecision.CONTAIN, route=EnforcementRoute.PROCESS_TERMINATION),
        termination_result=_termination(session),
        actions=(action,),
        policy_evaluations=(_policy(session, action, decision=PolicyDecision.VIOLATION),),
    )

    assert result.result.session_status is SessionStatus.ABORTED
    assert result.result.session_end_reason is SessionEndReason.SECURITY_CONTAINMENT
    assert result.result.action_outcomes[0].enforcement_action == "TERMINATED"


def test_user_abort_termination_is_recorded_outside_policy_enforcement(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        end_reason=SessionEndReason.USER_ABORT,
        user_abort_termination_result={
            "termination_id": "user-abort-017",
            "status": "SUCCEEDED",
            "outcome": "TERMINATED",
            "root_pid": 1234,
            "root_create_time": 10.5,
            "verified_tree_gone": True,
            "requested_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "reason": None,
        },
    )

    assert result.result.session_status is SessionStatus.ABORTED
    assert result.result.process_termination_result is None
    assert result.result.user_abort_termination_result["status"] == "SUCCEEDED"
    assert result.result.user_abort_termination_result["verified_tree_gone"] is True
    assert any(item.event_type.value == "USER_ABORT_EXECUTED" for item in result.audit_records)
    restored = type(result.result).from_mapping(result.result.to_mapping())
    assert restored.user_abort_termination_result == result.result.user_abort_termination_result


def test_protection_failure_termination_is_separate_from_user_abort_and_policy(
    tmp_path: Path,
):
    session, store, _ = _session(tmp_path)
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        end_reason=SessionEndReason.PROTECTION_FAILURE,
        protection_failure_termination_result={
            "termination_id": "protection-failure-017",
            "status": "SUCCEEDED",
            "outcome": "TERMINATED",
            "root_pid": 1234,
            "root_create_time": 10.5,
            "verified_tree_gone": True,
            "requested_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "reason": "HOOK_BROKER_LOST",
            "control": "PROTECTION_FAILURE",
        },
    )

    assert result.result.session_status is SessionStatus.FAILED
    assert result.result.session_end_reason is SessionEndReason.PROTECTION_FAILURE
    assert result.result.user_abort_termination_result is None
    assert result.result.protection_failure_termination_result["status"] == "SUCCEEDED"
    assert any(
        item.event_type.value == "PROTECTION_FAILURE_EXECUTED"
        for item in result.audit_records
    )
    restored = type(result.result).from_mapping(result.result.to_mapping())
    assert (
        restored.protection_failure_termination_result
        == result.result.protection_failure_termination_result
    )


def test_blocked_and_process_refuse_do_not_abort_session(tmp_path: Path):
    session, store, action = _session(tmp_path)
    blocked = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        gate_result=_gate(session, decision=EnforcementDecision.CONTAIN, action=EnforcementAction.BLOCKED, execution=EnforcementExecutionResult.SUCCEEDED, route=EnforcementRoute.PRETOOL_BLOCK),
        actions=(action,),
        policy_evaluations=(_policy(session, action, decision=PolicyDecision.VIOLATION),),
    )
    assert blocked.result.session_status is SessionStatus.COMPLETED

    session2, store2, action2 = _session(tmp_path / "second")
    refused = SessionFinalizer(evidence_store=store2).finalize(
        session2,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        gate_result=_gate(session2, decision=EnforcementDecision.REFUSE),
        actions=(action2,),
        policy_evaluations=(_policy(session2, action2, decision=PolicyDecision.VIOLATION),),
    )
    assert refused.result.session_status is SessionStatus.COMPLETED
    assert refused.result.review_required
    assert "허용" not in refused.report_text


def test_enforcement_results_are_correlated_into_action_outcomes(tmp_path: Path):
    session, store, action = _session(tmp_path)
    blocked = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        enforcement_results=(
            _gate(
                session,
                decision=EnforcementDecision.CONTAIN,
                action=EnforcementAction.BLOCKED,
                execution=EnforcementExecutionResult.SUCCEEDED,
                route=EnforcementRoute.PRETOOL_BLOCK,
            ),
        ),
        actions=(action,),
        policy_evaluations=(_policy(session, action, decision=PolicyDecision.VIOLATION),),
    )

    assert blocked.result.action_outcomes[0].enforcement_decision == "CONTAIN"
    assert blocked.result.action_outcomes[0].enforcement_action == "BLOCKED"
    assert blocked.result.action_outcomes[0].execution_result == "SUCCEEDED"


def test_live_root_cannot_be_claimed_as_normal_completion(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    with pytest.raises(FinalizationRefused):
        SessionFinalizer(evidence_store=store).finalize(
            session,
            process_end_status=ProcessIdentityStatus.LIVE_MATCH,
        )
    assert session.status is SessionStatus.RUNNING


def test_owner_unverifiable_becomes_protection_failure(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.OWNER_UNVERIFIABLE,
    )
    assert result.result.session_status is SessionStatus.FAILED
    assert result.result.session_end_reason is SessionEndReason.PROTECTION_FAILURE
    assert "OWNER_UNVERIFIABLE" in result.result.limitations


@dataclass
class _FakeSensor:
    health_value: SensorHealth

    @property
    def health(self):
        return self.health_value

    def stop(self):
        if self.health_value.status is SensorStatus.HEALTHY:
            self.health_value = SensorHealth(self.health_value.sensor, SensorStatus.STOPPED, NOW, "STOPPED")
        return SimpleNamespace(status=self.health_value.status, health=self.health_value)


def test_sensor_shutdown_preserves_health_history(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    healthy = _FakeSensor(SensorHealth(EvidenceSource.AGENT_HOOK, SensorStatus.HEALTHY, NOW))
    failed = _FakeSensor(SensorHealth(EvidenceSource.PROCESS_RUNTIME, SensorStatus.FAILED, NOW, "OBSERVER_FAILURE"))
    result = SessionFinalizer(evidence_store=store, sensors=(healthy, failed)).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    summaries = {item["sensor"]: item for item in result.result.sensor_summary}
    assert summaries["AGENT_HOOK"]["final_sensor_state"] == "STOPPED"
    assert summaries["PROCESS_RUNTIME"]["runtime_health_before_stop"] == "FAILED"
    assert "SENSOR_RUNTIME_FAILED:PROCESS_RUNTIME" in result.result.limitations


def test_sensor_stop_and_seal_precede_terminal_transition(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    observations: list[SessionStatus] = []

    class _OrderedSensor(_FakeSensor):
        def stop(self):
            observations.append(session.status)
            return super().stop()

    sensor = _OrderedSensor(SensorHealth(EvidenceSource.AGENT_HOOK, SensorStatus.HEALTHY, NOW))
    result = SessionFinalizer(evidence_store=store, sensors=(sensor,)).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    assert observations == [SessionStatus.RUNNING]
    assert result.result.session_status is SessionStatus.COMPLETED
    assert store.sealed


def _restored_verified(session: ProtectedRunSession) -> RecoveryVerificationResult:
    recovery = RecoveryResult(
        recovery_id="recovery-017",
        aia_session_id=session.session_id,
        action_id="action-017",
        termination_id="termination-017",
        checkpoint_id="checkpoint-017",
        recovery_status=RecoveryStatus.RESTORED,
        started_at=NOW,
        ended_at=NOW,
        duration_ms=1,
        planned_operation_count=0,
        attempted_operation_count=0,
        succeeded_operation_count=0,
        failed_operation_count=0,
    )
    integrity = IntegrityVerificationResult(
        aia_session_id=session.session_id,
        checkpoint_id="checkpoint-017",
        integrity_status=IntegrityStatus.VERIFIED,
        integrity_started_at=NOW,
        integrity_ended_at=NOW,
        integrity_duration_ms=1,
        verified_at=NOW,
        checkpoint_fingerprint="checkpoint-fingerprint",
        expected_entry_count=0,
        actual_entry_count=0,
    )
    return RecoveryVerificationResult(recovery, integrity)


def test_finalization_releases_lease_and_next_session_can_acquire(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    identities = {701: 70.1}
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=lambda pid: identities[pid],
    )
    lease = manager.acquire(
        session.workspace,
        session.session_id,
        owner_pid=701,
        owner_process_create_time=70.1,
        acquired_at=NOW,
    )
    result = SessionFinalizer(
        evidence_store=store,
        lease_manager=manager,
        workspace_lease=lease,
    ).finalize(session, process_end_status=ProcessIdentityStatus.PROCESS_GONE)

    assert result.result.session_status is SessionStatus.COMPLETED
    assert not lease.artifact_path.exists()
    next_session = ProtectedRunSession(
        workspace=session.workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id="policy-018",
        policy_version="1.0.0",
        created_at=NOW,
    )
    next_lease = manager.acquire(
        next_session.workspace,
        next_session.session_id,
        owner_pid=701,
        owner_process_create_time=70.1,
        acquired_at=NOW,
    )
    assert next_lease.session_id == next_session.session_id
    manager.release(next_lease)


def test_containment_releases_lease_after_terminal_and_sealed_evidence(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=lambda pid: 70.1,
    )
    lease = manager.acquire(
        session.workspace,
        session.session_id,
        owner_pid=701,
        owner_process_create_time=70.1,
        acquired_at=NOW,
    )
    observed: list[tuple[bool, SessionStatus]] = []

    class _ObservingManager:
        def release(self, value):
            observed.append((store.sealed, session.status))
            manager.release(value)

    result = SessionFinalizer(
        evidence_store=store,
        lease_manager=_ObservingManager(),
        workspace_lease=lease,
    ).finalize(
        session,
        termination_result=_termination(session),
        recovery_result=_restored_verified(session),
    )

    assert observed == [(True, SessionStatus.ABORTED)]
    assert result.result.session_status is SessionStatus.ABORTED
    assert result.result.recovery_result["recovery_status"] == "RESTORED"
    assert result.result.integrity_result["integrity_status"] == "VERIFIED"


def test_lease_release_failure_is_an_operational_limitation(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=lambda pid: 70.1,
    )
    lease = manager.acquire(
        session.workspace,
        session.session_id,
        owner_pid=701,
        owner_process_create_time=70.1,
        acquired_at=NOW,
    )

    class _FailingManager:
        def release(self, value):
            raise RuntimeError("simulated lease release failure")

    result = SessionFinalizer(
        evidence_store=store,
        lease_manager=_FailingManager(),
        workspace_lease=lease,
    ).finalize(session, process_end_status=ProcessIdentityStatus.PROCESS_GONE)

    assert result.result.session_status is SessionStatus.COMPLETED
    assert "LEASE_RELEASE_FAILED" in result.result.limitations
    assert "LEASE_RELEASE_FAILED" in result.report_text
    assert lease.artifact_path.exists()


def test_evidence_seal_rejects_append_and_index_has_lineage_lookup(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    store.build_index()
    seal = store.seal(sealed_at=NOW)
    assert seal.line_count == 1
    assert store.index_path.read_text(encoding="utf-8").find("evidence-017") >= 0
    with pytest.raises(EvidenceStoreSealedError):
        store.append(
            RawEvidenceRecord(
                session_id=session.session_id,
                source=EvidenceSource.FILESYSTEM_WATCHER,
                record_type=EvidenceRecordType.FILESYSTEM_EVENT,
                captured_at=NOW,
                observation_stage=ObservationStage.POST_ACTION,
                payload={"event_type": "modified"},
            )
        )


def test_bundle_tamper_is_invalid_and_does_not_overwrite(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    result_path = final.bundle.result_directory / "result.json"
    original = result_path.read_bytes()
    result_path.write_bytes(original + b" ")
    verification = EvidenceBundleVerifier().verify(final.bundle.result_directory)
    assert not verification.is_valid
    with pytest.raises(FinalizationError):
        SessionFinalizer(evidence_store=store).finalize(session)


def test_finalization_retry_after_commit_failure_keeps_terminal_session(tmp_path: Path):
    session, store, _ = _session(tmp_path)
    state = {"fail": True}

    def write_hook(name: str):
        if name == "security-report.md" and state["fail"]:
            raise OSError("test disk failure")

    from aia import EvidenceBundleCommitter

    committer = EvidenceBundleCommitter(
        store.path.parent.parent,
        write_hook=write_hook,
    )
    finalizer = SessionFinalizer(evidence_store=store, bundle_committer=committer)
    with pytest.raises(FinalizationError):
        finalizer.finalize(session, process_end_status=ProcessIdentityStatus.PROCESS_GONE)
    ended_at = session.ended_at
    assert session.status is SessionStatus.COMPLETED
    state["fail"] = False
    retried = finalizer.finalize(session)
    assert retried.result.result_id == str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, f"{session.session_id}:aia-result-1"))
    assert session.ended_at == ended_at
    assert retried.bundle_valid


def test_raw_command_is_fingerprinted_and_not_repeated_in_result_or_report(tmp_path: Path):
    session, store, action = _session(tmp_path)
    command_action = NormalizedAction(
        action_id="command-action",
        aia_session_id=session.session_id,
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind="COMMAND",
        observed_at=NOW,
        evidence_ids=action.evidence_ids,
        evidence_sources=action.evidence_sources,
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="canonical-v1",
        raw_command="echo FAKE_API_TOKEN=secret-value-123",
    )
    result = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(command_action,),
    )
    serialized = result.result.to_json_bytes().decode("utf-8")
    assert "secret-value-123" not in serialized
    assert "command_fingerprint" in serialized
    assert "secret-value-123" not in result.report_text
