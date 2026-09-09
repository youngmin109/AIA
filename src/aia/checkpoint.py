"""Safe Checkpoint creation and trusted Workspace Manifest contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from typing import Any
from uuid import uuid4

from .protection import (
    ControlRoot,
    ProtectionPreparationContext,
    WorkspaceLeaseManager,
    _exclusive_file_lock,
)
from .session import ProtectedRunSession, SessionStatus, canonicalize_workspace


class CheckpointError(ValueError):
    """Base error for Safe Checkpoint operations."""


class CheckpointRefusedError(CheckpointError):
    """Raised when Checkpoint preconditions are not satisfied."""


class CheckpointCreationError(CheckpointError):
    """Raised when a Checkpoint cannot be created safely."""


class CheckpointArtifactError(CheckpointCreationError):
    """Raised when a Checkpoint Artifact cannot be written or validated."""


class WorkspaceChangedDuringCheckpoint(CheckpointCreationError):
    """Raised when the source Workspace is not stable during capture."""

    code = "WORKSPACE_CHANGED_DURING_CHECKPOINT"


class UnsupportedFilesystemEntryError(CheckpointCreationError):
    """Raised when a symlink, reparse point, or special entry is observed."""

    code = "UNSUPPORTED_FILESYSTEM_ENTRY"

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"unsupported filesystem entry: {path}")


class ManifestEntryType(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class CheckpointValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CheckpointError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_checkpoint_id(checkpoint_id: str) -> str:
    if (
        not isinstance(checkpoint_id, str)
        or not checkpoint_id.strip()
        or checkpoint_id in {".", ".."}
        or any(separator in checkpoint_id for separator in ("/", "\\"))
    ):
        raise CheckpointError("checkpoint_id is not a safe directory name")
    return checkpoint_id


def _canonical_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise CheckpointArtifactError("manifest relative_path must be non-empty")
    if "\\" in value or value.startswith("/"):
        raise CheckpointArtifactError(
            "manifest paths must use Workspace-relative '/' separators"
        )
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ":" in parsed.parts[0]:
        raise CheckpointArtifactError("manifest path must be relative")
    if any(part in {"", ".", ".."} for part in parsed.parts):
        raise CheckpointArtifactError("manifest path escapes Workspace")
    return "/".join(parsed.parts)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    relative_path: str
    entry_type: ManifestEntryType
    size: int | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            _canonical_relative_path(self.relative_path),
        )
        entry_type = ManifestEntryType(self.entry_type)
        object.__setattr__(self, "entry_type", entry_type)
        if entry_type is ManifestEntryType.FILE:
            if not isinstance(self.size, int) or self.size < 0:
                raise CheckpointArtifactError("file manifest size must be non-negative")
            if (
                not isinstance(self.sha256, str)
                or len(self.sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.sha256)
            ):
                raise CheckpointArtifactError("file manifest sha256 is invalid")
        elif self.size is not None or self.sha256 is not None:
            raise CheckpointArtifactError(
                "directory manifest entries cannot contain file metadata"
            )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entry_type": self.entry_type.value,
            "relative_path": self.relative_path,
        }
        if self.entry_type is ManifestEntryType.FILE:
            result["sha256"] = self.sha256
            result["size"] = self.size
        return result


@dataclass(frozen=True, slots=True)
class CheckpointValidationResult:
    validity: CheckpointValidity
    reason: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.validity is CheckpointValidity.VALID


@dataclass(frozen=True, slots=True)
class SafeCheckpoint:
    checkpoint_id: str
    session_id: str
    workspace: Path
    created_at: datetime
    checkpoint_path: Path
    manifest_path: Path
    metadata_path: Path
    manifest_sha256: str
    checkpoint_content_sha256: str
    file_count: int
    directory_count: int
    total_bytes: int
    validity: CheckpointValidity
    manifest: tuple[ManifestEntry, ...]

    @property
    def is_valid(self) -> bool:
        return self.validity is CheckpointValidity.VALID


CheckpointSnapshot = SafeCheckpoint
CheckpointDescriptor = SafeCheckpoint


def _entry_sort_key(entry: ManifestEntry) -> str:
    return entry.relative_path


def _sorted_entries(entries: Iterable[ManifestEntry]) -> tuple[ManifestEntry, ...]:
    return tuple(sorted(entries, key=_entry_sort_key))


def _entry_mappings(entries: Iterable[ManifestEntry]) -> list[dict[str, Any]]:
    return [entry.to_mapping() for entry in _sorted_entries(entries)]


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _manifest_mapping(entries: Iterable[ManifestEntry]) -> dict[str, Any]:
    return {
        "entries": _entry_mappings(entries),
        "schema_version": "1.0",
    }


def _manifest_bytes(entries: Iterable[ManifestEntry]) -> bytes:
    return _canonical_json(_manifest_mapping(entries))


def _content_fingerprint_bytes(entries: Iterable[ManifestEntry]) -> bytes:
    return _canonical_json({"entries": _entry_mappings(entries)})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except FileNotFoundError as error:
        raise WorkspaceChangedDuringCheckpoint(
            f"Workspace file disappeared during checkpoint: {path}"
        ) from error
    except OSError as error:
        raise CheckpointCreationError(
            f"Workspace file cannot be read: {path}"
        ) from error
    return size, digest.hexdigest()


def _is_reparse_point(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _entry_kind(path: Path) -> ManifestEntryType:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise WorkspaceChangedDuringCheckpoint(
            f"Workspace entry disappeared during checkpoint: {path}"
        ) from error
    except OSError as error:
        raise CheckpointCreationError(
            f"Workspace entry cannot be inspected: {path}"
        ) from error

    is_junction = getattr(path, "is_junction", None)
    if stat.S_ISLNK(info.st_mode) or (
        callable(is_junction) and is_junction()
    ) or _is_reparse_point(info):
        raise UnsupportedFilesystemEntryError(path)
    if stat.S_ISREG(info.st_mode):
        return ManifestEntryType.FILE
    if stat.S_ISDIR(info.st_mode):
        return ManifestEntryType.DIRECTORY
    raise UnsupportedFilesystemEntryError(path)


def _relative_path(prefix: str, name: str) -> str:
    return name if not prefix else f"{prefix}/{name}"


def _scan_workspace(workspace: Path) -> tuple[ManifestEntry, ...]:
    entries: list[ManifestEntry] = []

    def visit(directory: Path, prefix: str) -> None:
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except FileNotFoundError as error:
            raise WorkspaceChangedDuringCheckpoint(
                f"Workspace directory disappeared during checkpoint: {directory}"
            ) from error
        except OSError as error:
            raise CheckpointCreationError(
                f"Workspace directory cannot be read: {directory}"
            ) from error

        for child in children:
            child_path = Path(child.path)
            relative = _relative_path(prefix, child.name)
            kind = _entry_kind(child_path)
            if kind is ManifestEntryType.DIRECTORY:
                entries.append(
                    ManifestEntry(relative, ManifestEntryType.DIRECTORY)
                )
                visit(child_path, relative)
            else:
                size, digest = _sha256_file(child_path)
                entries.append(
                    ManifestEntry(
                        relative,
                        ManifestEntryType.FILE,
                        size=size,
                        sha256=digest,
                    )
                )

    visit(workspace, "")
    return _sorted_entries(entries)


def _safe_join(root: Path, relative_path: str) -> Path:
    canonical_relative = _canonical_relative_path(relative_path)
    candidate = (root / Path(*canonical_relative.split("/"))).resolve(strict=False)
    resolved_root = root.resolve(strict=True)
    if not candidate.is_relative_to(resolved_root):
        raise CheckpointArtifactError(
            f"Checkpoint path escapes its root: {relative_path}"
        )
    return candidate


def _copy_file(source: Path, target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as source_stream, target.open(
            "xb"
        ) as target_stream:
            while chunk := source_stream.read(1024 * 1024):
                target_stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except FileNotFoundError as error:
        raise WorkspaceChangedDuringCheckpoint(
            f"Workspace file disappeared during copy: {source}"
        ) from error
    except OSError as error:
        raise CheckpointCreationError(
            f"Workspace file cannot be copied: {source}"
        ) from error
    return size, digest.hexdigest()


def _copy_workspace_snapshot(
    workspace: Path,
    entries: Iterable[ManifestEntry],
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for entry in _sorted_entries(entries):
        source = _safe_join(workspace, entry.relative_path)
        target = _safe_join(destination, entry.relative_path)
        if entry.entry_type is ManifestEntryType.DIRECTORY:
            try:
                target.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                if not target.is_dir() or target.is_symlink():
                    raise UnsupportedFilesystemEntryError(target)
            except OSError as error:
                raise CheckpointCreationError(
                    f"Checkpoint directory cannot be created: {entry.relative_path}"
                ) from error
            continue

        if _entry_kind(source) is not ManifestEntryType.FILE:
            raise WorkspaceChangedDuringCheckpoint(
                f"Workspace entry changed type during copy: {source}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        size, digest = _copy_file(source, target)
        if size != entry.size or digest != entry.sha256:
            raise WorkspaceChangedDuringCheckpoint(
                f"Workspace file changed during copy: {entry.relative_path}"
            )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckpointArtifactError(f"Checkpoint JSON is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CheckpointArtifactError(f"Checkpoint JSON must be an object: {path}")
    return value


def _parse_manifest(value: Mapping[str, Any]) -> tuple[ManifestEntry, ...]:
    if value.get("schema_version") != "1.0":
        raise CheckpointArtifactError("unsupported Checkpoint Manifest schema")
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise CheckpointArtifactError("Checkpoint Manifest entries must be a list")
    entries: list[ManifestEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise CheckpointArtifactError("Checkpoint Manifest entry must be an object")
        try:
            entry = ManifestEntry(
                relative_path=raw["relative_path"],
                entry_type=raw["entry_type"],
                size=raw.get("size"),
                sha256=raw.get("sha256"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CheckpointArtifactError("Checkpoint Manifest entry is invalid") from error
        entries.append(entry)
    result = _sorted_entries(entries)
    if len({entry.relative_path for entry in result}) != len(result):
        raise CheckpointArtifactError("Checkpoint Manifest contains duplicate paths")
    if [entry.to_mapping() for entry in result] != raw_entries:
        raise CheckpointArtifactError("Checkpoint Manifest ordering is not deterministic")
    return result


def _metadata_for(
    *,
    checkpoint_id: str,
    session_id: str,
    workspace: Path,
    created_at: datetime,
    checkpoint_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    checkpoint_content_sha256: str,
    entries: tuple[ManifestEntry, ...],
) -> dict[str, Any]:
    files = [entry for entry in entries if entry.entry_type is ManifestEntryType.FILE]
    directories = [
        entry for entry in entries if entry.entry_type is ManifestEntryType.DIRECTORY
    ]
    return {
        "checkpoint_content_sha256": checkpoint_content_sha256,
        "checkpoint_id": checkpoint_id,
        "checkpoint_path": str(checkpoint_path),
        "created_at": created_at.isoformat(),
        "directory_count": len(directories),
        "file_count": len(files),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "schema_version": "1.0",
        "session_id": session_id,
        "total_bytes": sum(entry.size or 0 for entry in files),
        "validity": CheckpointValidity.VALID.value,
        "workspace": str(workspace),
    }


def _write_bytes_exclusive(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(value)
    except FileExistsError:
        raise CheckpointArtifactError(f"Checkpoint Artifact already exists: {path}")
    except OSError as error:
        raise CheckpointArtifactError(f"Checkpoint Artifact cannot be written: {path}") from error


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes_exclusive(path, _canonical_json(value))


def _validate_artifact(
    checkpoint_path: Path,
    *,
    expected_checkpoint_path: Path | None = None,
) -> tuple[dict[str, Any], tuple[ManifestEntry, ...]]:
    checkpoint_path = checkpoint_path.resolve(strict=True)
    manifest_path = checkpoint_path / "manifest.json"
    metadata_path = checkpoint_path / "metadata.json"
    workspace_path = checkpoint_path / "workspace"
    metadata = _read_json(metadata_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = _parse_manifest(_read_json(manifest_path))

    required_metadata = {
        "checkpoint_content_sha256",
        "checkpoint_id",
        "checkpoint_path",
        "created_at",
        "directory_count",
        "file_count",
        "manifest_path",
        "manifest_sha256",
        "schema_version",
        "session_id",
        "total_bytes",
        "validity",
        "workspace",
    }
    if not required_metadata.issubset(metadata):
        raise CheckpointArtifactError("Checkpoint metadata is incomplete")
    if metadata["schema_version"] != "1.0":
        raise CheckpointArtifactError("unsupported Checkpoint metadata schema")
    _safe_checkpoint_id(metadata["checkpoint_id"])
    if not isinstance(metadata["session_id"], str) or not metadata["session_id"]:
        raise CheckpointArtifactError("Checkpoint metadata session_id is invalid")
    if not isinstance(metadata["workspace"], str) or not Path(
        metadata["workspace"]
    ).is_absolute():
        raise CheckpointArtifactError("Checkpoint metadata workspace is invalid")
    try:
        _aware_utc(
            datetime.fromisoformat(metadata["created_at"]),
            field_name="created_at",
        )
    except (TypeError, ValueError) as error:
        raise CheckpointArtifactError(
            "Checkpoint metadata created_at is invalid"
        ) from error
    for field_name in ("file_count", "directory_count", "total_bytes"):
        if not isinstance(metadata[field_name], int) or metadata[field_name] < 0:
            raise CheckpointArtifactError(
                f"Checkpoint metadata {field_name} is invalid"
            )
    for field_name in ("manifest_sha256", "checkpoint_content_sha256"):
        value = metadata[field_name]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise CheckpointArtifactError(
                f"Checkpoint metadata {field_name} is invalid"
            )

    if _sha256_bytes(manifest_bytes) != metadata.get("manifest_sha256"):
        raise CheckpointArtifactError("Checkpoint Manifest SHA-256 mismatch")
    if _sha256_bytes(_content_fingerprint_bytes(manifest)) != metadata.get(
        "checkpoint_content_sha256"
    ):
        raise CheckpointArtifactError("Checkpoint content fingerprint mismatch")
    if metadata.get("validity") != CheckpointValidity.VALID.value:
        raise CheckpointArtifactError("Checkpoint is not marked VALID")

    expected_path = (
        expected_checkpoint_path.resolve(strict=False)
        if expected_checkpoint_path is not None
        else checkpoint_path
    )
    if Path(metadata.get("checkpoint_path", "")).resolve(strict=False) != expected_path:
        raise CheckpointArtifactError("Checkpoint metadata path mismatch")
    if Path(metadata.get("manifest_path", "")).resolve(strict=False) != (
        expected_path / "manifest.json"
    ):
        raise CheckpointArtifactError("Manifest metadata path mismatch")

    actual = _scan_workspace(workspace_path)
    if actual != manifest:
        raise CheckpointArtifactError("Checkpoint Manifest does not match snapshot")
    files = [entry for entry in manifest if entry.entry_type is ManifestEntryType.FILE]
    directories = [
        entry for entry in manifest if entry.entry_type is ManifestEntryType.DIRECTORY
    ]
    if metadata.get("file_count") != len(files):
        raise CheckpointArtifactError("Checkpoint file_count mismatch")
    if metadata.get("directory_count") != len(directories):
        raise CheckpointArtifactError("Checkpoint directory_count mismatch")
    if metadata.get("total_bytes") != sum(entry.size or 0 for entry in files):
        raise CheckpointArtifactError("Checkpoint total_bytes mismatch")
    return metadata, manifest


def _checkpoint_from_artifact(
    checkpoint_path: Path,
    metadata: Mapping[str, Any],
    manifest: tuple[ManifestEntry, ...],
) -> SafeCheckpoint:
    try:
        checkpoint_id = _safe_checkpoint_id(metadata["checkpoint_id"])
        created_at = _aware_utc(
            datetime.fromisoformat(metadata["created_at"]),
            field_name="created_at",
        )
        validity = CheckpointValidity(metadata["validity"])
        session_id = metadata["session_id"]
        workspace = Path(metadata["workspace"]).expanduser().resolve(strict=False)
        manifest_sha256 = metadata["manifest_sha256"]
        content_sha256 = metadata["checkpoint_content_sha256"]
        file_count = metadata["file_count"]
        directory_count = metadata["directory_count"]
        total_bytes = metadata["total_bytes"]
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointArtifactError("Checkpoint metadata is invalid") from error
    if not isinstance(session_id, str) or not session_id:
        raise CheckpointArtifactError("Checkpoint metadata session_id is invalid")
    return SafeCheckpoint(
        checkpoint_id=checkpoint_id,
        session_id=session_id,
        workspace=workspace,
        created_at=created_at,
        checkpoint_path=checkpoint_path.resolve(strict=True),
        manifest_path=(checkpoint_path / "manifest.json").resolve(strict=True),
        metadata_path=(checkpoint_path / "metadata.json").resolve(strict=True),
        manifest_sha256=manifest_sha256,
        checkpoint_content_sha256=content_sha256,
        file_count=file_count,
        directory_count=directory_count,
        total_bytes=total_bytes,
        validity=validity,
        manifest=manifest,
    )


def validate_checkpoint(
    checkpoint: SafeCheckpoint | str | Path,
) -> CheckpointValidationResult:
    """Validate a finalized Checkpoint Artifact without changing it."""

    checkpoint_path = (
        checkpoint.checkpoint_path
        if isinstance(checkpoint, SafeCheckpoint)
        else Path(checkpoint)
    )
    try:
        _validate_artifact(checkpoint_path)
    except Exception as error:
        reason = getattr(error, "code", type(error).__name__)
        return CheckpointValidationResult(CheckpointValidity.INVALID, reason)
    return CheckpointValidationResult(CheckpointValidity.VALID)


validate_safe_checkpoint = validate_checkpoint


def _control_root_for_context(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
) -> ControlRoot:
    control_directory = context.control_directory.resolve(strict=True)
    control_root_path = control_directory.parent.parent
    control_root = ControlRoot.for_workspace(session.workspace, control_root_path)
    expected = control_root.session_directory(session.session_id)
    if expected != control_directory:
        raise CheckpointRefusedError(
            "ProtectionPreparationContext control directory does not match Session"
        )
    return control_root


def _validate_preparation_context(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
) -> None:
    if not isinstance(session, ProtectedRunSession):
        raise CheckpointRefusedError("session must be a ProtectedRunSession")
    if not isinstance(context, ProtectionPreparationContext):
        raise CheckpointRefusedError(
            "context must be a ProtectionPreparationContext"
        )
    if session.status is not SessionStatus.PREPARING:
        raise CheckpointRefusedError("Safe Checkpoint requires PREPARING Session")
    if context.session_id != session.session_id:
        raise CheckpointRefusedError("preparation context session does not match")
    if context.workspace != session.workspace:
        raise CheckpointRefusedError("preparation context Workspace does not match")
    if context.active_policy.session_id != session.session_id:
        raise CheckpointRefusedError("Active Policy does not belong to Session")
    if context.workspace_lease.session_id != session.session_id:
        raise CheckpointRefusedError("Workspace Lease does not belong to Session")
    if context.workspace_lease.workspace != session.workspace:
        raise CheckpointRefusedError("Workspace Lease Workspace does not match")


class SafeCheckpointManager:
    """Create and validate immutable Safe Checkpoints under Control Root."""

    def create(
        self,
        session: ProtectedRunSession,
        context: ProtectionPreparationContext,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        checkpoint_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SafeCheckpoint:
        _validate_preparation_context(session, context)
        control_root = _control_root_for_context(session, context)
        manager = lease_manager or WorkspaceLeaseManager(control_root)
        manager.validate_ownership(context.workspace_lease)

        created_time = _aware_utc(
            created_at if created_at is not None else datetime.now(timezone.utc),
            field_name="created_at",
        )
        checkpoint_id = _safe_checkpoint_id(checkpoint_id or uuid4().hex)
        checkpoints_root = control_root.session_directory(session.session_id) / "checkpoints"
        checkpoints_root.mkdir(parents=True, exist_ok=True)
        final_path = checkpoints_root / checkpoint_id
        staging_path: Path | None = None

        with _exclusive_file_lock(checkpoints_root / ".checkpoint.lock"):
            if final_path.exists():
                raise CheckpointArtifactError(
                    f"Checkpoint Artifact already exists: {final_path}"
                )
            staging_path = checkpoints_root / f".staging-{checkpoint_id}-{uuid4().hex}"
            try:
                staging_path.mkdir()
                staging_workspace = staging_path / "workspace"
                source_entries = _scan_workspace(session.workspace)
                _copy_workspace_snapshot(
                    session.workspace,
                    source_entries,
                    staging_workspace,
                )
                checkpoint_entries = _scan_workspace(staging_workspace)
                if checkpoint_entries != source_entries:
                    raise WorkspaceChangedDuringCheckpoint(
                        "Checkpoint copy does not match source Manifest"
                    )
                source_after = _scan_workspace(session.workspace)
                if source_after != source_entries:
                    raise WorkspaceChangedDuringCheckpoint(
                        "Workspace changed during Checkpoint creation"
                    )

                manifest_bytes = _manifest_bytes(checkpoint_entries)
                manifest_sha256 = _sha256_bytes(manifest_bytes)
                content_sha256 = _sha256_bytes(
                    _content_fingerprint_bytes(checkpoint_entries)
                )
                _write_bytes_exclusive(staging_path / "manifest.json", manifest_bytes)
                metadata = _metadata_for(
                    checkpoint_id=checkpoint_id,
                    session_id=session.session_id,
                    workspace=session.workspace,
                    created_at=created_time,
                    checkpoint_path=final_path,
                    manifest_path=final_path / "manifest.json",
                    manifest_sha256=manifest_sha256,
                    checkpoint_content_sha256=content_sha256,
                    entries=checkpoint_entries,
                )
                _write_json_exclusive(staging_path / "metadata.json", metadata)
                validated_metadata, validated_manifest = _validate_artifact(
                    staging_path,
                    expected_checkpoint_path=final_path,
                )
                os.replace(staging_path, final_path)
                staging_path = None
                return _checkpoint_from_artifact(
                    final_path,
                    validated_metadata,
                    validated_manifest,
                )
            except Exception as error:
                cleanup_error: OSError | None = None
                if staging_path is not None:
                    try:
                        shutil.rmtree(staging_path)
                    except OSError as cleanup_exception:
                        cleanup_error = cleanup_exception
                if cleanup_error is not None:
                    raise CheckpointArtifactError(
                        f"Checkpoint failed and staging cleanup failed: "
                        f"{staging_path}"
                    ) from error
                if isinstance(error, CheckpointError):
                    raise
                raise CheckpointCreationError(
                    "Checkpoint creation failed"
                ) from error

    def validate(
        self,
        checkpoint: SafeCheckpoint | str | Path,
    ) -> CheckpointValidationResult:
        return validate_checkpoint(checkpoint)


CheckpointManager = SafeCheckpointManager


def create_safe_checkpoint(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
    *,
    lease_manager: WorkspaceLeaseManager | None = None,
    checkpoint_id: str | None = None,
    created_at: datetime | None = None,
) -> SafeCheckpoint:
    return SafeCheckpointManager().create(
        session,
        context,
        lease_manager=lease_manager,
        checkpoint_id=checkpoint_id,
        created_at=created_at,
    )


create_checkpoint = create_safe_checkpoint


__all__ = [
    "CheckpointArtifactError",
    "CheckpointCreationError",
    "CheckpointManager",
    "CheckpointDescriptor",
    "CheckpointError",
    "CheckpointRefusedError",
    "CheckpointSnapshot",
    "CheckpointValidity",
    "CheckpointValidationResult",
    "ManifestEntry",
    "ManifestEntryType",
    "SafeCheckpoint",
    "SafeCheckpointManager",
    "UnsupportedFilesystemEntryError",
    "WorkspaceChangedDuringCheckpoint",
    "create_checkpoint",
    "create_safe_checkpoint",
    "validate_checkpoint",
    "validate_safe_checkpoint",
]
