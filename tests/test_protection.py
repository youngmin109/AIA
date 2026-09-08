from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from aia import (
    ActivePolicyAlreadyFrozen,
    ActivePolicyConflict,
    ActivePolicyFreezeError,
    ActivePolicyIdentityMismatch,
    ControlRoot,
    ControlRootValidationError,
    LeaseOwnershipError,
    Operation,
    PolicyEffect,
    PolicyProfile,
    PolicyRule,
    ProtectedRunSession,
    ResolvedPolicy,
    SecurityAssetPolicy,
    SecurityAssetType,
    SessionMode,
    SessionStatus,
    WorkspaceBusyError,
    WorkspaceLeaseManager,
    freeze_active_policy,
    load_policy,
    policy_content_sha256,
    prepare_protection,
    resolve_profile,
)


def make_workspace(tmp_path: Path, name: str = "workspace") -> Path:
    workspace = tmp_path / name
    workspace.mkdir()
    return workspace


def make_session(workspace: Path, resolved: ResolvedPolicy) -> ProtectedRunSession:
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    session.transition(
        SessionStatus.PREPARING,
        at=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
    )
    return session


def basic_policy() -> ResolvedPolicy:
    return resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)


class FakeProcessIdentity:
    def __init__(self, values: dict[int, float] | None = None) -> None:
        self.values = values or {}

    def __call__(self, pid: int) -> float:
        if pid not in self.values:
            raise ProcessLookupError(pid)
        return self.values[pid]


def test_control_root_outside_workspace_is_created(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    control = ControlRoot.for_workspace(workspace, tmp_path / "aia-control")

    assert control.path.is_absolute()
    assert control.path.is_dir()
    assert not control.path.is_relative_to(workspace)
    assert control.sessions_path.is_dir()
    assert control.leases_path.is_dir()


def test_control_root_inside_workspace_is_rejected_before_creation(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    invalid_root = workspace / ".aia-control"

    with pytest.raises(ControlRootValidationError):
        ControlRoot.for_workspace(workspace, invalid_root)

    assert not invalid_root.exists()


def test_control_root_ancestor_of_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    with pytest.raises(ControlRootValidationError):
        ControlRoot.for_workspace(workspace, tmp_path)


def test_session_control_directory_is_session_scoped(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    control = ControlRoot.for_workspace(workspace, tmp_path / "aia-control")

    directory = control.session_directory("session-123")

    assert directory == control.sessions_path / "session-123"
    assert directory.is_dir()
    assert directory.is_relative_to(control.path)


def test_valid_active_policy_freeze_creates_artifact(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = make_session(workspace, resolved)
    frozen_at = datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc)

    snapshot = freeze_active_policy(
        session,
        resolved,
        tmp_path / "aia-control",
        frozen_at=frozen_at,
    )
    artifact = json.loads(snapshot.artifact_path.read_text(encoding="utf-8"))

    assert snapshot.session_id == session.session_id
    assert snapshot.policy_id == resolved.policy_id
    assert snapshot.policy_version == resolved.policy_version
    assert snapshot.profile is PolicyProfile.BASIC_DEVELOPMENT
    assert snapshot.frozen_at == frozen_at
    assert snapshot.sha256 == artifact["policy_content_sha256"]
    assert artifact["session_id"] == session.session_id
    assert artifact["rules"]
    assert session.status is SessionStatus.PREPARING


@pytest.mark.parametrize(
    "field",
    ["policy_id", "policy_version"],
)
def test_policy_identity_mismatch_is_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    values = {
        "workspace": workspace,
        "agent": "codex",
        "mode": SessionMode.ENFORCE,
        "policy_id": resolved.policy_id,
        "policy_version": resolved.policy_version,
    }
    values[field] = "different"
    session = ProtectedRunSession(**values)
    session.transition(SessionStatus.PREPARING)

    with pytest.raises(ActivePolicyIdentityMismatch):
        freeze_active_policy(session, resolved, tmp_path / "aia-control")


def test_policy_freeze_requires_preparing_status(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )

    with pytest.raises(ActivePolicyFreezeError) as error:
        freeze_active_policy(session, resolved, tmp_path / "aia-control")

    assert "PREPARING" in str(error.value)


def test_same_policy_content_has_same_fingerprint_across_sessions(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    first = make_session(workspace, resolved)
    second = make_session(workspace, resolved)
    control_root = tmp_path / "aia-control"

    first_snapshot = freeze_active_policy(
        first,
        resolved,
        control_root,
        frozen_at=datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc),
    )
    second_snapshot = freeze_active_policy(
        second,
        resolved,
        control_root,
        frozen_at=datetime(2026, 1, 1, 1, 6, tzinfo=timezone.utc),
    )

    assert first_snapshot.session_id != second_snapshot.session_id
    assert first_snapshot.frozen_at != second_snapshot.frozen_at
    assert first_snapshot.sha256 == second_snapshot.sha256


def test_policy_content_fingerprint_excludes_session_metadata(
    tmp_path: Path,
) -> None:
    resolved = basic_policy()
    workspace = make_workspace(tmp_path)
    session = make_session(workspace, resolved)

    before = policy_content_sha256(resolved)
    snapshot = freeze_active_policy(session, resolved, tmp_path / "control")
    after = policy_content_sha256(resolved)

    assert snapshot.sha256 == before == after


def test_different_policy_content_cannot_refreeze_same_session(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = make_session(workspace, resolved)
    changed_policy = SecurityAssetPolicy(
        schema_version=resolved.policy.schema_version,
        policy_id=resolved.policy.policy_id,
        policy_version=resolved.policy.policy_version,
        default_effect=PolicyEffect.DENY,
        rules=resolved.policy.rules,
        profile=resolved.profile,
    )
    changed = ResolvedPolicy(
        profile=resolved.profile,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
        source="changed",
        policy=changed_policy,
    )

    freeze_active_policy(session, resolved, tmp_path / "control")

    with pytest.raises(ActivePolicyConflict):
        freeze_active_policy(session, changed, tmp_path / "control")


def test_same_session_refreeze_is_explicit_and_does_not_overwrite(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = make_session(workspace, resolved)
    control_root = tmp_path / "control"
    snapshot = freeze_active_policy(session, resolved, control_root)
    original = snapshot.artifact_path.read_bytes()

    with pytest.raises(ActivePolicyAlreadyFrozen):
        freeze_active_policy(
            session,
            resolved,
            control_root,
            frozen_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )

    assert snapshot.artifact_path.read_bytes() == original


def test_frozen_snapshot_is_independent_of_original_policy_file(
    tmp_path: Path,
) -> None:
    source = next(Path("policies/profiles").glob("기본-개발형.ko.json"))
    document = json.loads(source.read_text(encoding="utf-8"))
    policy_path = tmp_path / "policy.ko.json"
    policy_path.write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded_policy = load_policy(policy_path)
    resolved = ResolvedPolicy(
        profile=PolicyProfile.BASIC_DEVELOPMENT,
        policy_id=loaded_policy.policy_id,
        policy_version=loaded_policy.policy_version,
        source=str(policy_path),
        policy=loaded_policy,
    )
    workspace = make_workspace(tmp_path)
    session = make_session(workspace, resolved)
    snapshot = freeze_active_policy(session, resolved, tmp_path / "control")
    original_hash = snapshot.sha256

    document["기본효과"] = "금지"
    policy_path.write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )

    assert snapshot.sha256 == original_hash
    assert snapshot.policy.default_effect is PolicyEffect.ALLOW


def test_workspace_lease_acquire_stores_pid_and_create_time(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )

    lease = manager.acquire(
        workspace,
        "session-a",
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    metadata = json.loads(lease.artifact_path.read_text(encoding="utf-8"))

    assert lease.workspace == workspace.resolve()
    assert metadata["owner_pid"] == 101
    assert metadata["owner_process_create_time"] == 10.5
    assert lease.artifact_path.is_relative_to(tmp_path / "control")
    assert not lease.artifact_path.is_relative_to(workspace)


def test_live_matching_owner_makes_workspace_busy(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    manager.acquire(
        workspace,
        "session-a",
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    with pytest.raises(WorkspaceBusyError) as error:
        manager.acquire(
            workspace,
            "session-b",
            owner_pid=102,
            owner_process_create_time=20.5,
        )

    assert error.value.code == "WORKSPACE_BUSY"
    assert error.value.existing_lease.session_id == "session-a"


def test_different_workspaces_can_have_concurrent_leases(tmp_path: Path) -> None:
    first_workspace = make_workspace(tmp_path, "first")
    second_workspace = make_workspace(tmp_path, "second")
    identities = FakeProcessIdentity()
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )

    first = manager.acquire(
        first_workspace,
        "session-a",
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    second = manager.acquire(
        second_workspace,
        "session-b",
        owner_pid=102,
        owner_process_create_time=20.5,
    )

    assert first.artifact_path != second.artifact_path


def test_canonical_workspace_paths_conflict(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    alias = workspace / "nested"
    alias.mkdir()
    alias = alias / ".."
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    manager.acquire(
        workspace,
        "session-a",
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    with pytest.raises(WorkspaceBusyError):
        manager.acquire(
            alias,
            "session-b",
            owner_pid=102,
            owner_process_create_time=20.5,
        )


def test_dead_pid_is_preserved_as_stale_evidence(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    old = manager.acquire(
        workspace,
        "old-session",
        owner_pid=201,
        owner_process_create_time=30.5,
    )

    new = manager.acquire(
        workspace,
        "new-session",
        owner_pid=202,
        owner_process_create_time=40.5,
    )

    assert new.stale_record is not None
    assert new.stale_record.reason == "OWNER_PROCESS_NOT_FOUND"
    assert new.stale_record.previous_session_id == old.session_id
    assert new.stale_record.artifact_path.is_file()


def test_pid_reuse_create_time_mismatch_is_stale(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({201: 30.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    manager.acquire(
        workspace,
        "old-session",
        owner_pid=201,
        owner_process_create_time=30.5,
    )
    identities.values[201] = 99.5

    new = manager.acquire(
        workspace,
        "new-session",
        owner_pid=202,
        owner_process_create_time=40.5,
    )

    assert new.stale_record is not None
    assert new.stale_record.reason == "OWNER_PROCESS_CREATE_TIME_MISMATCH"
    assert new.stale_record.previous_owner_pid == 201
    assert new.stale_record.previous_owner_process_create_time == 30.5


def test_other_session_cannot_release_lease(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    lease = manager.acquire(
        workspace,
        "owner-session",
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    with pytest.raises(LeaseOwnershipError):
        manager.release(
            workspace,
            "other-session",
            owner_pid=101,
            owner_process_create_time=10.5,
        )

    assert lease.artifact_path.exists()


def test_owner_session_can_release_lease_after_identity_check(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    lease = manager.acquire(
        workspace,
        "owner-session",
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    manager.release(lease)

    assert not lease.artifact_path.exists()


def test_preparation_context_keeps_session_preparing(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = make_session(workspace, resolved)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )

    context = prepare_protection(
        session,
        resolved,
        tmp_path / "control",
        lease_manager=manager,
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    assert context.session_id == session.session_id
    assert context.active_policy.session_id == session.session_id
    assert context.workspace_lease.session_id == session.session_id
    assert context.control_directory.is_dir()
    assert context.is_static_preparation_complete
    assert session.status is SessionStatus.PREPARING


def test_preparation_fails_before_context_on_policy_mismatch(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id="different",
        policy_version=resolved.policy_version,
    )
    session.transition(SessionStatus.PREPARING)

    with pytest.raises(ActivePolicyIdentityMismatch):
        prepare_protection(session, resolved, tmp_path / "control")

    assert session.status is SessionStatus.PREPARING


def test_preparation_fails_when_lease_is_busy(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    resolved = basic_policy()
    first_session = make_session(workspace, resolved)
    second_session = make_session(workspace, resolved)
    identities = FakeProcessIdentity({101: 10.5})
    manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=identities,
    )
    manager.acquire(
        workspace,
        first_session.session_id,
        owner_pid=101,
        owner_process_create_time=10.5,
    )

    with pytest.raises(WorkspaceBusyError):
        prepare_protection(
            second_session,
            resolved,
            tmp_path / "control",
            lease_manager=manager,
            owner_pid=102,
            owner_process_create_time=20.5,
        )

    assert second_session.status is SessionStatus.PREPARING
