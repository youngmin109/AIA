from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

import aia.checkpoint as checkpoint_module
from aia import (
    CheckpointArtifactError,
    CheckpointRefusedError,
    CheckpointValidity,
    LeaseOwnershipError,
    ManifestEntry,
    ManifestEntryType,
    PolicyProfile,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    UnsupportedFilesystemEntryError,
    WorkspaceChangedDuringCheckpoint,
    WorkspaceLeaseManager,
    WorkspaceOwnerUnverifiableError,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
    validate_checkpoint,
)


class FakeProcessIdentity:
    def __init__(self, values: dict[int, float] | None = None) -> None:
        self.values = values or {}

    def __call__(self, pid: int) -> float:
        if pid not in self.values:
            raise ProcessLookupError(pid)
        return self.values[pid]


def _prepared_workspace(
    tmp_path: Path,
    *,
    owner_pid: int = 101,
    owner_create_time: float = 10.5,
) -> tuple[Path, ProtectedRunSession, object, WorkspaceLeaseManager]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    control_root = tmp_path / "control"
    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    session.transition(
        SessionStatus.PREPARING,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    identities = FakeProcessIdentity({owner_pid: owner_create_time})
    lease_manager = WorkspaceLeaseManager(
        control_root,
        process_identity_provider=identities,
    )
    context = prepare_protection(
        session,
        resolved,
        control_root,
        lease_manager=lease_manager,
        owner_pid=owner_pid,
        owner_process_create_time=owner_create_time,
    )
    return workspace, session, context, lease_manager


def _create_checkpoint(
    tmp_path: Path,
    *,
    checkpoint_id: str | None = None,
) -> tuple[Path, ProtectedRunSession, object, WorkspaceLeaseManager, object]:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        checkpoint_id=checkpoint_id,
        created_at=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
    )
    return workspace, session, context, lease_manager, checkpoint


def test_checkpoint_requires_preparing_session(tmp_path: Path) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    session.transition(SessionStatus.ABORTED)

    with pytest.raises(CheckpointRefusedError):
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
        )

    assert session.status is SessionStatus.ABORTED
    assert workspace.is_dir()


def test_checkpoint_captures_full_workspace_and_control_root_boundary(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_bytes(b"TOP_SECRET=keep\n")
    (workspace / ".hidden").write_text("hidden", encoding="utf-8")
    (workspace / "empty.txt").write_bytes(b"")
    (workspace / "src").mkdir()
    (workspace / "src" / "auth.py").write_text("allow", encoding="utf-8")
    (workspace / "logs" / "empty").mkdir(parents=True)

    _, session, context, lease_manager, checkpoint = _create_checkpoint(tmp_path)

    assert checkpoint.validity is CheckpointValidity.VALID
    assert checkpoint.checkpoint_path.is_relative_to(
        context.control_directory.parent.parent
    )
    assert not checkpoint.checkpoint_path.is_relative_to(workspace)
    assert checkpoint.file_count == 4
    assert checkpoint.directory_count == 3
    assert checkpoint.total_bytes == len("TOP_SECRET=keep\n") + 6 + 5
    assert checkpoint.session_id == session.session_id
    assert (checkpoint.checkpoint_path / "workspace" / ".env").read_text(
        encoding="utf-8"
    ) == "TOP_SECRET=keep\n"
    assert (
        checkpoint.checkpoint_path / "workspace" / "logs" / "empty"
    ).is_dir()


def test_manifest_has_relative_sorted_file_and_directory_entries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "nested").mkdir()
    (workspace / "nested" / "file.txt").write_text("file", encoding="utf-8")
    workspace, _, _, _, checkpoint = _create_checkpoint(tmp_path)

    entries = checkpoint.manifest
    assert [entry.relative_path for entry in entries] == sorted(
        entry.relative_path for entry in entries
    )
    assert all("\\" not in entry.relative_path for entry in entries)
    assert any(entry.entry_type is ManifestEntryType.FILE for entry in entries)
    assert any(entry.entry_type is ManifestEntryType.DIRECTORY for entry in entries)
    assert all(not entry.relative_path.startswith("/") for entry in entries)


def test_manifest_records_exact_sha256_and_size(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    content = b"checkpoint content\n"
    (workspace / "file.txt").write_bytes(content)
    _, _, _, _, checkpoint = _create_checkpoint(tmp_path)

    entry = next(
        entry for entry in checkpoint.manifest if entry.relative_path == "file.txt"
    )
    assert entry.size == len(content)
    assert entry.sha256 == hashlib.sha256(content).hexdigest()


def test_checkpoint_manifest_hashes_match_pinned_fixture(tmp_path: Path) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    (workspace / "empty").mkdir()
    (workspace / "alpha.txt").write_bytes(b"alpha\n")
    (workspace / "empty" / "data.bin").write_bytes(bytes(range(32)))

    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        checkpoint_id="golden",
        created_at=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert checkpoint.manifest_sha256 == (
        "9bd39727be93b4e1ebc08d68bc0f2b60a97f9e2f1de00de909338165db3a468c"
    )
    assert checkpoint.checkpoint_content_sha256 == (
        "bcae20fd556874ba5650eb48169f698674d011e47d4f342f6bde553b13b404f8"
    )
    assert [
        (entry.relative_path, entry.size, entry.sha256)
        for entry in checkpoint.manifest
        if entry.sha256 is not None
    ] == [
        (
            "alpha.txt",
            6,
            "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060",
        ),
        (
            "empty/data.bin",
            32,
            "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd",
        ),
    ]


def test_checkpoint_content_fingerprint_excludes_metadata(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    (first_root / "workspace").mkdir(parents=True)
    (second_root / "workspace").mkdir(parents=True)
    (first_root / "workspace" / "same.txt").write_text("same", encoding="utf-8")
    (second_root / "workspace" / "same.txt").write_text("same", encoding="utf-8")

    first = _create_checkpoint(first_root)
    second = _create_checkpoint(second_root)

    assert first[4].session_id != second[4].session_id
    assert first[4].checkpoint_id != second[4].checkpoint_id
    assert first[4].created_at == second[4].created_at
    assert first[4].checkpoint_content_sha256 == second[4].checkpoint_content_sha256
    assert first[4].manifest_sha256 == second[4].manifest_sha256


def test_file_change_addition_and_deletion_change_fingerprint(tmp_path: Path) -> None:
    workspace, session, context, lease_manager, first = _create_checkpoint(tmp_path)
    first_hash = first.checkpoint_content_sha256
    lease_manager.release(context.workspace_lease)
    (workspace / "new.txt").write_text("new", encoding="utf-8")

    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    next_session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    next_session.transition(SessionStatus.PREPARING)
    next_context = prepare_protection(
        next_session,
        resolved,
        tmp_path / "control",
        lease_manager=lease_manager,
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    second = create_safe_checkpoint(
        next_session,
        next_context,
        lease_manager=lease_manager,
    )

    assert second.checkpoint_content_sha256 != first_hash
    assert session.status is SessionStatus.PREPARING
    assert second.file_count == first.file_count + 1


def test_checkpoint_id_collision_does_not_overwrite(tmp_path: Path) -> None:
    _, session, context, lease_manager, first = _create_checkpoint(
        tmp_path,
        checkpoint_id="fixed-checkpoint",
    )
    original_metadata = first.metadata_path.read_bytes()

    with pytest.raises(CheckpointArtifactError):
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
            checkpoint_id="fixed-checkpoint",
        )

    assert first.metadata_path.read_bytes() == original_metadata


def test_checkpoint_validation_detects_snapshot_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "file.txt").write_text("original", encoding="utf-8")
    _, _, _, _, checkpoint = _create_checkpoint(tmp_path)
    snapshot_file = checkpoint.checkpoint_path / "workspace" / "file.txt"
    snapshot_file.write_text("tampered", encoding="utf-8")

    result = validate_checkpoint(checkpoint)

    assert result.validity is CheckpointValidity.INVALID


def test_checkpoint_validation_detects_unmanifested_file(tmp_path: Path) -> None:
    _, _, _, _, checkpoint = _create_checkpoint(tmp_path)
    (checkpoint.checkpoint_path / "workspace" / "extra.txt").write_text(
        "extra",
        encoding="utf-8",
    )

    result = validate_checkpoint(checkpoint)

    assert result.validity is CheckpointValidity.INVALID


def test_checkpoint_validation_detects_missing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "file.txt").write_text("original", encoding="utf-8")
    _, _, _, _, checkpoint = _create_checkpoint(tmp_path)
    (checkpoint.checkpoint_path / "workspace" / "file.txt").unlink()

    result = validate_checkpoint(checkpoint)

    assert result.validity is CheckpointValidity.INVALID


def test_checkpoint_validation_detects_missing_empty_directory(
    tmp_path: Path,
) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    empty_directory = workspace / "empty"
    empty_directory.mkdir()

    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
    )
    empty_snapshot_directory = checkpoint.checkpoint_path / "workspace" / "empty"
    empty_snapshot_directory.rmdir()
    result = validate_checkpoint(checkpoint)
    assert result.validity is CheckpointValidity.INVALID


def test_manifest_rejects_absolute_and_escape_paths() -> None:
    with pytest.raises(CheckpointArtifactError):
        ManifestEntry("../escape", ManifestEntryType.FILE, 1, "0" * 64)
    with pytest.raises(CheckpointArtifactError):
        ManifestEntry("C:/escape", ManifestEntryType.FILE, 1, "0" * 64)
    with pytest.raises(CheckpointArtifactError):
        ManifestEntry("/escape", ManifestEntryType.FILE, 1, "0" * 64)


def test_unsupported_symlink_is_not_followed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    _, session, context, lease_manager = _prepared_workspace(tmp_path)

    with pytest.raises(UnsupportedFilesystemEntryError):
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
        )


@pytest.mark.parametrize(
    ("mode", "attributes", "is_junction"),
    [
        (stat.S_IFLNK, 0, False),
        (stat.S_IFDIR, 0, True),
        (stat.S_IFDIR, 0x400, False),
    ],
    ids=["symbolic-link", "junction", "reparse-point"],
)
def test_link_like_entry_classification_is_environment_independent(
    mode: int,
    attributes: int,
    is_junction: bool,
) -> None:
    fake_info = SimpleNamespace(st_mode=mode, st_file_attributes=attributes)

    with pytest.raises(UnsupportedFilesystemEntryError) as error:
        checkpoint_module._classify_entry_info(
            Path("fake-link"),
            fake_info,
            is_junction=is_junction,
        )

    assert error.value.code == "UNSUPPORTED_FILESYSTEM_ENTRY"


def test_unsupported_entry_is_rejected_before_snapshot_copy_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    entry = ManifestEntry(
        "external-link",
        ManifestEntryType.FILE,
        size=1,
        sha256="0" * 64,
    )
    copied = False

    def reject_entry(_: Path) -> ManifestEntryType:
        raise UnsupportedFilesystemEntryError(workspace / "external-link")

    def unexpected_copy(*_: object) -> tuple[int, str]:
        nonlocal copied
        copied = True
        return 1, "0" * 64

    monkeypatch.setattr(checkpoint_module, "_entry_kind", reject_entry)
    monkeypatch.setattr(checkpoint_module, "_copy_file", unexpected_copy)

    with pytest.raises(UnsupportedFilesystemEntryError):
        checkpoint_module._copy_workspace_snapshot(
            workspace,
            (entry,),
            tmp_path / "staging-workspace",
        )

    assert copied is False


def test_workspace_change_during_copy_is_not_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    (workspace / "file.txt").write_text("before", encoding="utf-8")
    original_copy = checkpoint_module._copy_workspace_snapshot

    def copy_then_mutate(source: Path, entries: object, destination: Path) -> None:
        original_copy(source, entries, destination)
        (source / "file.txt").write_text("after", encoding="utf-8")

    monkeypatch.setattr(
        checkpoint_module,
        "_copy_workspace_snapshot",
        copy_then_mutate,
    )
    with pytest.raises(WorkspaceChangedDuringCheckpoint) as error:
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
            checkpoint_id="unstable",
        )

    assert error.value.code == "WORKSPACE_CHANGED_DURING_CHECKPOINT"
    checkpoints = context.control_directory / "checkpoints"
    assert not (checkpoints / "unstable").exists()
    assert not list(checkpoints.glob(".staging-*"))


def test_checkpoint_requires_current_lease_ownership(tmp_path: Path) -> None:
    _, session, context, lease_manager = _prepared_workspace(tmp_path)
    lease_manager.release(context.workspace_lease)

    with pytest.raises(LeaseOwnershipError) as error:
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
        )

    assert "lease" in str(error.value).lower()


def test_checkpoint_rejects_lease_owner_identity_mismatch(tmp_path: Path) -> None:
    _, session, context, lease_manager = _prepared_workspace(tmp_path)
    lease_manager.process_identity_provider.values[101] = 99.5

    with pytest.raises(LeaseOwnershipError):
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
        )


def test_owner_unverifiable_refuses_checkpoint(tmp_path: Path) -> None:
    _, session, context, lease_manager = _prepared_workspace(tmp_path)

    def unavailable(_: int) -> float:
        raise PermissionError("access denied")

    lease_manager.process_identity_provider = unavailable
    with pytest.raises(WorkspaceOwnerUnverifiableError):
        create_safe_checkpoint(
            session,
            context,
            lease_manager=lease_manager,
        )


def test_checkpoint_success_keeps_session_preparing(tmp_path: Path) -> None:
    _, session, _, _, checkpoint = _create_checkpoint(tmp_path)

    assert checkpoint.validity is CheckpointValidity.VALID
    assert session.status is SessionStatus.PREPARING
    assert session.started_at is not None
    assert session.ended_at is None


def test_sensitive_content_is_not_in_manifest_or_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    secret = "SECRET_DO_NOT_DUPLICATE"
    (workspace / ".env").write_text(secret, encoding="utf-8")
    workspace, _, _, _, checkpoint = _create_checkpoint(tmp_path)

    manifest_text = checkpoint.manifest_path.read_text(encoding="utf-8")
    metadata_text = checkpoint.metadata_path.read_text(encoding="utf-8")
    assert secret not in manifest_text
    assert secret not in metadata_text
    assert (checkpoint.checkpoint_path / "workspace" / ".env").read_text(
        encoding="utf-8"
    ) == secret


def test_checkpoint_artifact_contains_manifest_and_metadata_only_at_root(
    tmp_path: Path,
) -> None:
    _, _, _, _, checkpoint = _create_checkpoint(tmp_path)

    assert {path.name for path in checkpoint.checkpoint_path.iterdir()} == {
        "workspace",
        "manifest.json",
        "metadata.json",
    }
    metadata = json.loads(checkpoint.metadata_path.read_text(encoding="utf-8"))
    assert metadata["validity"] == "VALID"
    assert metadata["checkpoint_id"] == checkpoint.checkpoint_id


def test_checkpoint_progress_reports_each_stage_and_cannot_fail_it(tmp_path: Path) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    (workspace / "nested").mkdir()
    for name in ("a.txt", "b.txt", "nested/c.txt"):
        (workspace / name).write_text(name, encoding="utf-8")
    reports: list[tuple[str, int, int | None]] = []

    def record_then_fail(stage: str, done: int, total: int | None) -> None:
        reports.append((stage, done, total))
        raise RuntimeError("display failed")

    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        checkpoint_id="with-progress",
        progress=record_then_fail,
    )

    assert checkpoint.checkpoint_id == "with-progress"
    assert [item for item in reports if item[0] == "scan"][-1] == ("scan", 3, None)
    assert [item for item in reports if item[0] == "copy"] == [("copy", n, 3) for n in (1, 2, 3)]
    assert [item for item in reports if item[0] == "verify"][-1] == ("verify", 3, 3)


def test_later_checkpoint_shares_unchanged_files_and_copies_changed_ones(tmp_path: Path) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    (workspace / "same.txt").write_text("unchanged", encoding="utf-8")
    (workspace / "edit.txt").write_text("before", encoding="utf-8")
    first = create_safe_checkpoint(session, context, lease_manager=lease_manager, checkpoint_id="first")
    (workspace / "edit.txt").write_text("after!", encoding="utf-8")
    second = create_safe_checkpoint(session, context, lease_manager=lease_manager, checkpoint_id="second")

    first_same = os.stat(first.checkpoint_path / "workspace" / "same.txt")
    second_same = os.stat(second.checkpoint_path / "workspace" / "same.txt")
    # Unchanged: one file on disk shared by both checkpoints (a hard link).
    assert (first_same.st_dev, first_same.st_ino) == (second_same.st_dev, second_same.st_ino)
    assert second_same.st_nlink == 2
    # Changed: a fresh copy with the new bytes.
    assert (second.checkpoint_path / "workspace" / "edit.txt").read_text(encoding="utf-8") == "after!"
    assert (first.checkpoint_path / "workspace" / "edit.txt").read_text(encoding="utf-8") == "before"
    assert validate_checkpoint(first).validity is CheckpointValidity.VALID
    assert validate_checkpoint(second).validity is CheckpointValidity.VALID

    # Removing the earlier checkpoint leaves the later one complete.
    import shutil

    shutil.rmtree(first.checkpoint_path)
    assert validate_checkpoint(second).validity is CheckpointValidity.VALID
    assert (second.checkpoint_path / "workspace" / "same.txt").read_text(encoding="utf-8") == "unchanged"


def test_checkpoint_copies_when_a_hard_link_is_not_possible(tmp_path: Path, monkeypatch) -> None:
    workspace, session, context, lease_manager = _prepared_workspace(tmp_path)
    (workspace / "same.txt").write_text("unchanged", encoding="utf-8")
    first = create_safe_checkpoint(session, context, lease_manager=lease_manager, checkpoint_id="first")

    def refuse(*_args, **_kwargs):
        raise OSError("hard links are not supported here")

    monkeypatch.setattr(checkpoint_module.os, "link", refuse)
    second = create_safe_checkpoint(session, context, lease_manager=lease_manager, checkpoint_id="second")

    assert os.stat(second.checkpoint_path / "workspace" / "same.txt").st_nlink == 1
    assert validate_checkpoint(first).validity is CheckpointValidity.VALID
    assert validate_checkpoint(second).validity is CheckpointValidity.VALID
