"""Deterministic EPIC-017 Result/Bundle integration smoke."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile

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
    IntegrityStatus,
    NormalizedAction,
    NormalizationCompleteness,
    ObservationStage,
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyProfile,
    ProcessIdentity,
    ProcessTerminationOutcome,
    ProcessTerminationResult,
    ProtectedRunSession,
    RecoveryCoordinator,
    RuntimePolicyEvaluation,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
    verify_evidence_bundle,
)
from aia.evidence import RawEvidenceRecord, RawEvidenceStore
from aia.protection import WorkspaceLeaseManager, process_create_time
from aia.recovery import RecoveryStatus


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aia-epic017-smoke-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        protected = workspace / "protected"
        protected.mkdir()
        target = protected / "file.txt"
        target.write_text("baseline", encoding="utf-8")

        resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            created_at=NOW,
        )
        session.transition(SessionStatus.PREPARING, at=NOW)
        identities = WorkspaceLeaseManager(
            root / "control",
            process_identity_provider=lambda pid: process_create_time(pid),
        )
        context = prepare_protection(
            session,
            resolved,
            root / "control",
            lease_manager=identities,
            owner_pid=os.getpid(),
            owner_process_create_time=process_create_time(os.getpid()),
            frozen_at=NOW,
            acquired_at=NOW,
            prepared_at=NOW,
        )
        checkpoint = create_safe_checkpoint(session, context, lease_manager=identities, created_at=NOW)
        session.transition(SessionStatus.READY, at=NOW)
        session.transition(SessionStatus.RUNNING, at=NOW)

        store = RawEvidenceStore.for_session(root / "control", session.session_id)
        evidence = store.append(
            RawEvidenceRecord(
                session_id=session.session_id,
                source=EvidenceSource.FILESYSTEM_WATCHER,
                record_type=EvidenceRecordType.FILESYSTEM_EVENT,
                captured_at=NOW,
                observation_stage=ObservationStage.POST_ACTION,
                payload={"event_type": "deleted", "src_path": "protected/file.txt", "is_directory": False},
                evidence_id="smoke-evidence-017",
            )
        )
        action = NormalizedAction(
            action_id="smoke-action-017",
            aia_session_id=session.session_id,
            operation=Operation.DELETE,
            stage=ObservationStage.POST_ACTION,
            target_kind="FILE",
            observed_at=NOW,
            evidence_ids=(evidence.evidence_id,),
            evidence_sources=(EvidenceSource.FILESYSTEM_WATCHER,),
            completeness=NormalizationCompleteness.COMPLETE,
            normalizer_version="canonical-v1",
            canonical_path="protected/file.txt",
        )
        policy = RuntimePolicyEvaluation(
            action_id=action.action_id,
            aia_session_id=session.session_id,
            operation=Operation.DELETE,
            stage=ObservationStage.POST_ACTION,
            policy_id=context.active_policy.policy_id,
            policy_version=context.active_policy.policy_version,
            policy_profile=context.active_policy.profile,
            active_policy_fingerprint=context.active_policy.sha256,
            policy_decision=PolicyDecision.VIOLATION,
            operation_effect=PolicyEffect.DENY,
            asset_type="CRITICAL_CODE",
            matched_rule_ids=("smoke-rule-017",),
            audit_record=False,
            evaluated_at=NOW,
            path="protected/file.txt",
        )
        attribution = AttributionResult(
            action_id=action.action_id,
            aia_session_id=session.session_id,
            grade=AttributionGrade.EXACT,
            reason_code=AttributionReason.DIRECT_TRUSTED_HOOK,
            reason="trusted protected run evidence",
            supporting_evidence_ids=(evidence.evidence_id,),
        )
        identity = ProcessIdentity(os.getpid(), process_create_time(os.getpid()))
        gate = EnforcementGateResult(
            action_id=action.action_id,
            aia_session_id=session.session_id,
            policy_decision=PolicyDecision.VIOLATION,
            attribution_grade=AttributionGrade.EXACT,
            decision=EnforcementDecision.CONTAIN,
            route=EnforcementRoute.PROCESS_TERMINATION,
            action=EnforcementAction.NONE,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            stage=ObservationStage.POST_ACTION,
            checked_at=NOW,
            gate_checks=(),
            failure_reasons=(),
            policy_fingerprint=context.active_policy.sha256,
            root_process_identity=identity,
            hook_trust_status="VERIFIED",
            sensor_statuses=(),
            lease_status="LIVE_MATCH",
        )
        termination = ProcessTerminationResult(
            termination_id="smoke-termination-017",
            aia_session_id=session.session_id,
            launch_id="smoke-launch-017",
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

        target.unlink()
        recovery = RecoveryCoordinator(identities).recover(
            gate,
            termination,
            session=session,
            checkpoint=checkpoint,
            workspace_lease=context.workspace_lease,
        )
        final = SessionFinalizer(
            evidence_store=store,
            lease_manager=identities,
            workspace_lease=context.workspace_lease,
        ).finalize(
            session,
            gate_result=gate,
            termination_result=termination,
            actions=(action,),
            policy_evaluations=(policy,),
            attribution_results=(attribution,),
            recovery_result=recovery,
            active_policy=context.active_policy,
            checkpoint=checkpoint,
        )
        bundle = verify_evidence_bundle(final.bundle.result_directory)
        if not (
            final.result.session_status is SessionStatus.ABORTED
            and final.result.session_end_reason.value == "SECURITY_CONTAINMENT"
            and recovery.recovery_status is RecoveryStatus.RESTORED
            and recovery.integrity_status is IntegrityStatus.VERIFIED
            and bundle.is_valid
        ):
            return 1
        print("Session: ABORTED / SECURITY_CONTAINMENT")
        print("Policy: VIOLATION")
        print("Attribution: EXACT")
        print("Enforcement: CONTAIN / TERMINATED / SUCCEEDED")
        print("Recovery: RESTORED")
        print("Integrity: VERIFIED")
        print("Bundle: VALID")
        print(f"Report: {final.bundle.result_directory / 'security-report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
