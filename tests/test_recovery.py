from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path

import pytest

import aia.recovery as recovery_module
from aia import (
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    IntegrityStatus,
    PolicyProfile,
    PolicyDecision,
    ProcessTerminationOutcome,
    ProcessTerminationResult,
    RecoveryCoordinator,
    RecoveryStatus,
    SessionMode,
    SessionStatus,
    ProtectedRunSession,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)
from aia.checkpoint import validate_checkpoint
from aia.integrity import IntegrityVerifier
from aia.process_identity import ProcessIdentity
from aia.evidence import ObservationStage


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _FakeProcessIdentity:
    def __init__(self, values: dict[int, float] | None = None) -> None:
        self.values = values or {101: 10.5}

    def __call__(self, pid: int) -> float:
        if pid not in self.values:
            raise ProcessLookupError(pid)
        return self.values[pid]


def _fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "protected").mkdir()
    (workspace / "nested").mkdir()
    (workspace / "protected" / "deleted.txt").write_text("delete baseline", encoding="utf-8")
    (workspace / "protected" / "modified.txt").write_text("original", encoding="utf-8")
    (workspace / "nested" / "keep.txt").write_text("keep", encoding="utf-8")
    (workspace / "empty-dir").mkdir()
    (workspace / ".env").write_text("AIA_TEST_SECRET=baseline", encoding="utf-8")

    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    session.transition(SessionStatus.PREPARING, at=NOW)
    identities = _FakeProcessIdentity()
    lease_manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    context = prepare_protection(
        session,
        resolved,
        tmp_path / "control",
        lease_manager=lease_manager,
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        created_at=NOW,
    )
    session.transition(SessionStatus.READY, at=NOW)
    session.transition(SessionStatus.RUNNING, at=NOW)
    gate = EnforcementGateResult(
        action_id="action-016",
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
        policy_fingerprint="policy-016",
        root_process_identity=ProcessIdentity(2001, 1),
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )
    termination = ProcessTerminationResult(
        termination_id="termination-016",
        aia_session_id=session.session_id,
        launch_id="launch-016",
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
    return workspace, session, context.workspace_lease, lease_manager, checkpoint, gate, termination


def _coordinator(lease_manager: WorkspaceLeaseManager, verifier=None) -> RecoveryCoordinator:
    return RecoveryCoordinator(lease_manager, integrity_verifier=verifier)


def test_recovery_restores_whole_workspace_and_verifies(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "deleted.txt").unlink()
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")
    (workspace / "unexpected.txt").write_text("created", encoding="utf-8")
    (workspace / "unexpected-dir").mkdir()
    (workspace / "unexpected-dir" / "new.txt").write_text("created", encoding="utf-8")
    (workspace / "empty-dir").rmdir()
    (workspace / "nested" / "keep.txt").rename(workspace / "nested" / "moved.txt")

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.RESTORED
    assert result.integrity_status is IntegrityStatus.VERIFIED
    assert result.verified_recovery_success
    assert (workspace / "protected" / "deleted.txt").read_text(encoding="utf-8") == "delete baseline"
    assert (workspace / "protected" / "modified.txt").read_text(encoding="utf-8") == "original"
    assert (workspace / "nested" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (workspace / "nested" / "moved.txt").exists()
    assert not (workspace / "unexpected.txt").exists()
    assert not (workspace / "unexpected-dir").exists()
    assert (workspace / "empty-dir").is_dir()
    assert result.recovery.planned_operation_count > 0


def test_recovery_replay_is_noop_after_restore(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")

    coordinator = _coordinator(lease_manager)
    restored = coordinator.recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )
    assert restored.verified_recovery_success

    replay = coordinator.recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert replay.recovery_status is RecoveryStatus.NOT_REQUIRED
    assert replay.integrity_status is IntegrityStatus.VERIFIED
    assert replay.recovery.planned_operation_count == 0
    assert replay.recovery.attempted_operation_count == 0


def test_recovery_and_integrity_are_independent(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")

    class _TamperingVerifier(IntegrityVerifier):
        def verify(self, checkpoint, *, workspace=None, session=None):
            target = Path(workspace or checkpoint.workspace)
            (target / "protected" / "modified.txt").write_text("tampered after restore", encoding="utf-8")
            return super().verify(checkpoint, workspace=workspace, session=session)

    result = _coordinator(lease_manager, _TamperingVerifier()).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.RESTORED
    assert result.integrity_status is IntegrityStatus.FAILED
    assert "protected/modified.txt" in result.integrity.changed_paths


def test_already_baseline_is_not_required_but_is_verified(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.NOT_REQUIRED
    assert result.integrity_status is IntegrityStatus.VERIFIED
    assert result.recovery.attempted_operation_count == 0


def test_termination_failure_refuses_without_workspace_mutation(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    before = (workspace / "protected" / "modified.txt").read_bytes()
    failed_gate = replace(
        gate,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.FAILED,
    )
    failed_termination = replace(
        termination,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.FAILED,
        outcome=ProcessTerminationOutcome.PARTIAL,
    )
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")

    result = _coordinator(lease_manager).recover(
        failed_gate,
        failed_termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.REFUSED
    assert result.integrity_status is IntegrityStatus.NOT_CHECKED
    assert (workspace / "protected" / "modified.txt").read_bytes() != before


def test_pretool_block_and_refuse_do_not_recover(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")
    blocked_gate = replace(
        gate,
        route=EnforcementRoute.PRETOOL_BLOCK,
        action=EnforcementAction.BLOCKED,
    )
    blocked = _coordinator(lease_manager).recover(
        blocked_gate,
        None,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )
    assert blocked.recovery_status is RecoveryStatus.NOT_REQUIRED
    assert blocked.integrity_status is IntegrityStatus.NOT_CHECKED
    assert (workspace / "protected" / "modified.txt").read_text(encoding="utf-8") == "changed"

    refused_gate = replace(
        gate,
        decision=EnforcementDecision.REFUSE,
        route=EnforcementRoute.NONE,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
    )
    refused = _coordinator(lease_manager).recover(
        refused_gate,
        None,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )
    assert refused.recovery_status is RecoveryStatus.NOT_REQUIRED
    assert refused.integrity_status is IntegrityStatus.NOT_CHECKED


def test_missing_checkpoint_is_unavailable_after_successful_termination(tmp_path: Path):
    _, session, lease, lease_manager, _, gate, termination = _fixture(tmp_path)

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=None,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.RECOVERY_UNAVAILABLE
    assert result.integrity_status is IntegrityStatus.NOT_CHECKED


def test_checkpoint_tamper_causes_zero_workspace_mutation(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")
    checkpoint.manifest_path.write_text("tampered", encoding="utf-8")

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.RECOVERY_UNAVAILABLE
    assert result.integrity_status is IntegrityStatus.NOT_CHECKED
    assert (workspace / "protected" / "modified.txt").read_text(encoding="utf-8") == "changed"


def test_file_directory_type_conflicts_are_restored(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "deleted.txt").unlink()
    (workspace / "protected" / "deleted.txt").mkdir()
    (workspace / "empty-dir").rmdir()
    (workspace / "empty-dir").write_text("wrong type", encoding="utf-8")

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.RESTORED
    assert result.integrity_status is IntegrityStatus.VERIFIED
    assert (workspace / "protected" / "deleted.txt").is_file()
    assert (workspace / "empty-dir").is_dir()


def test_checkpoint_source_content_is_revalidated_before_file_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    target = workspace / "protected" / "modified.txt"
    target.write_text("changed", encoding="utf-8")
    source = checkpoint.checkpoint_path / "workspace" / "protected" / "modified.txt"
    original_read_source = recovery_module._read_source
    source_reads = 0

    assert validate_checkpoint(checkpoint).is_valid
    assert any(
        operation.relative_path == "protected/modified.txt"
        for operation in _coordinator(lease_manager).build_plan(checkpoint, workspace=workspace).operations
    )

    def tamper_before_copy(checkpoint_arg, entry):
        nonlocal source_reads
        if entry.relative_path == "protected/modified.txt":
            source_reads += 1
            if source_reads == 2:
                source.write_text("tampered", encoding="utf-8")
        return original_read_source(checkpoint_arg, entry)

    monkeypatch.setattr(recovery_module, "_read_source", tamper_before_copy)
    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert source_reads == 2
    assert result.recovery_status is RecoveryStatus.FAILED
    assert result.integrity_status is IntegrityStatus.FAILED
    assert result.recovery.failed_paths == ("protected/modified.txt",)
    assert target.read_text(encoding="utf-8") == "changed"


def test_checkpoint_source_type_is_revalidated_before_file_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    target = workspace / "protected" / "modified.txt"
    target.write_text("changed", encoding="utf-8")
    source = checkpoint.checkpoint_path / "workspace" / "protected" / "modified.txt"
    original_read_source = recovery_module._read_source
    source_reads = 0

    assert validate_checkpoint(checkpoint).is_valid

    def replace_with_directory_before_copy(checkpoint_arg, entry):
        nonlocal source_reads
        if entry.relative_path == "protected/modified.txt":
            source_reads += 1
            if source_reads == 2:
                source.unlink()
                source.mkdir()
        return original_read_source(checkpoint_arg, entry)

    monkeypatch.setattr(recovery_module, "_read_source", replace_with_directory_before_copy)
    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert source_reads == 2
    assert result.recovery_status is RecoveryStatus.FAILED
    assert result.integrity_status is IntegrityStatus.FAILED
    assert result.recovery.failed_paths == ("protected/modified.txt",)
    assert target.read_text(encoding="utf-8") == "changed"


def test_current_symlink_is_refused_without_following_external_target(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("outside", encoding="utf-8")
    link = workspace / "external-link"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    result = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.REFUSED
    assert result.integrity_status is IntegrityStatus.NOT_CHECKED
    assert outside.read_text(encoding="utf-8") == "outside"


def test_partial_restore_is_failed_and_still_runs_integrity(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    (workspace / "protected" / "deleted.txt").unlink()
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")
    coordinator = _coordinator(lease_manager)
    original_apply = coordinator._apply_operation
    calls = 0

    def fail_second(operation, *, checkpoint, workspace):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise recovery_module._RecoveryOperationFailure("TEST_OPERATION_FAILURE")
        return original_apply(operation, checkpoint=checkpoint, workspace=workspace)

    coordinator._apply_operation = fail_second
    result = coordinator.recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )

    assert result.recovery_status is RecoveryStatus.FAILED
    assert result.integrity_status is IntegrityStatus.FAILED
    assert result.recovery.succeeded_operation_count == 1
    assert result.recovery.failed_operation_count == 1


def test_session_mismatch_and_lease_loss_refuse_without_mutation(tmp_path: Path):
    workspace, session, lease, lease_manager, checkpoint, gate, termination = _fixture(tmp_path)
    other = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=session.policy_id,
        policy_version=session.policy_version,
    )
    other.transition(SessionStatus.PREPARING, at=NOW)
    other.transition(SessionStatus.READY, at=NOW)
    other.transition(SessionStatus.RUNNING, at=NOW)
    mismatch = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=other,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )
    assert mismatch.recovery_status is RecoveryStatus.REFUSED
    assert mismatch.integrity_status is IntegrityStatus.NOT_CHECKED

    lease_manager.release(lease)
    lease_loss = _coordinator(lease_manager).recover(
        gate,
        termination,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=lease,
    )
    assert lease_loss.recovery_status is RecoveryStatus.REFUSED
    assert lease_loss.integrity_status is IntegrityStatus.NOT_CHECKED
