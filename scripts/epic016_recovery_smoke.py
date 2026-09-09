"""Standalone EPIC-016 Recovery + Integrity filesystem smoke."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import psutil

from aia import (
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    PolicyDecision,
    PolicyProfile,
    ProcessIdentity,
    ProcessTerminationOutcome,
    ProcessTerminationResult,
    RecoveryCoordinator,
    RecoveryStatus,
    IntegrityStatus,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)
from aia.evidence import ObservationStage


NOW = datetime.now(timezone.utc)


def _gate(session: ProtectedRunSession, identity: ProcessIdentity) -> EnforcementGateResult:
    return EnforcementGateResult(
        action_id="epic-016-smoke-action",
        aia_session_id=session.session_id,
        policy_decision=PolicyDecision.VIOLATION,
        attribution_grade=AttributionGrade.EXACT,
        decision=EnforcementDecision.CONTAIN,
        route=EnforcementRoute.PROCESS_TERMINATION,
        action=EnforcementAction.TERMINATED,
        execution_result=EnforcementExecutionResult.SUCCEEDED,
        stage=ObservationStage.POST_ACTION,
        checked_at=NOW,
        gate_checks=(),
        failure_reasons=(),
        policy_fingerprint="epic-016-policy",
        root_process_identity=identity,
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )


def _termination(session: ProtectedRunSession) -> ProcessTerminationResult:
    return ProcessTerminationResult(
        termination_id="epic-016-smoke-termination",
        aia_session_id=session.session_id,
        launch_id="epic-016-smoke-launch",
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aia-epic016-smoke-") as directory:
        base = Path(directory)
        workspace = base / "workspace"
        workspace.mkdir()
        (workspace / "protected").mkdir()
        (workspace / "nested").mkdir()
        (workspace / "empty-dir").mkdir()
        (workspace / "protected" / "deleted.txt").write_text("baseline", encoding="utf-8")
        (workspace / "protected" / "modified.txt").write_text("original", encoding="utf-8")
        (workspace / "nested" / "keep.txt").write_text("keep", encoding="utf-8")
        (workspace / ".env").write_text("AIA_SMOKE_SECRET=do-not-print", encoding="utf-8")

        owner = psutil.Process(os.getpid())
        owner_create_time = owner.create_time()
        resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
        )
        session.transition(SessionStatus.PREPARING, at=NOW)
        lease_manager = WorkspaceLeaseManager(
            base / "control",
            process_identity_provider=lambda _pid: owner_create_time,
        )
        context = prepare_protection(
            session,
            resolved,
            base / "control",
            lease_manager=lease_manager,
            owner_pid=owner.pid,
            owner_process_create_time=owner_create_time,
        )
        checkpoint = create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
            created_at=NOW,
        )
        session.transition(SessionStatus.READY, at=NOW)
        session.transition(SessionStatus.RUNNING, at=NOW)

        (workspace / "protected" / "deleted.txt").unlink()
        (workspace / "protected" / "modified.txt").write_text("modified", encoding="utf-8")
        (workspace / "unexpected.txt").write_text("created", encoding="utf-8")
        (workspace / "unexpected-dir").mkdir()
        (workspace / "unexpected-dir" / "new.txt").write_text("created", encoding="utf-8")
        (workspace / "empty-dir").rmdir()
        (workspace / "nested" / "keep.txt").rename(workspace / "nested" / "moved.txt")

        result = RecoveryCoordinator(lease_manager).recover(
            _gate(session, ProcessIdentity(owner.pid, owner_create_time)),
            _termination(session),
            session=session,
            checkpoint=checkpoint,
            workspace_lease=context.workspace_lease,
        )
        print(
            "recovery_result="
            + json.dumps(
                {
                    "recovery": result.recovery_status.value,
                    "integrity": result.integrity_status.value,
                    "verified_recovery_success": result.verified_recovery_success,
                    "planned_operation_count": result.recovery.planned_operation_count,
                    "attempted_operation_count": result.recovery.attempted_operation_count,
                    "failed_paths": result.recovery.failed_paths,
                    "missing_paths": result.integrity.missing_paths,
                    "unexpected_paths": result.integrity.unexpected_paths,
                    "changed_paths": result.integrity.changed_paths,
                    "recovery_duration_ms": result.recovery.duration_ms,
                    "integrity_duration_ms": result.integrity.integrity_duration_ms,
                },
                sort_keys=True,
            )
        )
        if result.recovery_status is not RecoveryStatus.RESTORED:
            return 1
        if result.integrity_status is not IntegrityStatus.VERIFIED:
            return 1
        if not result.verified_recovery_success:
            return 1
        print("PASS: EPIC-016 Recovery + Integrity smoke")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
