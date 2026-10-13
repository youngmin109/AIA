"""Safe Checkpoint based Workspace Recovery and Rollback coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from . import checkpoint as checkpoint_module
from .checkpoint import (
    CheckpointValidity,
    ManifestEntry,
    ManifestEntryType,
    SafeCheckpoint,
    UnsupportedFilesystemEntryError,
    WorkspaceChangedDuringCheckpoint,
    validate_checkpoint,
)
from .enforcement import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
)
from .integrity import (
    IntegrityStatus,
    IntegrityVerificationResult,
    IntegrityVerifier,
)
from .process_manager import ProcessTerminationOutcome, ProcessTerminationResult
from .protection import (
    ProtectionError,
    WorkspaceLease,
    WorkspaceLeaseManager,
)
from .session import ProtectedRunSession, SessionStatus, canonicalize_workspace

if TYPE_CHECKING:
    from .launcher import ProtectedLaunchContext


class RecoveryError(ValueError):
    """Base error for Recovery contracts."""


class RecoveryStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    RESTORED = "RESTORED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    RECOVERY_UNAVAILABLE = "RECOVERY_UNAVAILABLE"


RecoveryState = RecoveryStatus


class RecoveryOperationType(StrEnum):
    RESTORE_FILE = "RESTORE_FILE"
    CREATE_DIRECTORY = "CREATE_DIRECTORY"
    REMOVE_UNEXPECTED_FILE = "REMOVE_UNEXPECTED_FILE"
    REMOVE_UNEXPECTED_DIRECTORY = "REMOVE_UNEXPECTED_DIRECTORY"
    REPLACE_TYPE_CONFLICT = "REPLACE_TYPE_CONFLICT"


RecoveryOperation = RecoveryOperationType


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecoveryError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecoveryError("Recovery paths must be non-empty relative paths")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or (parsed.parts and ":" in parsed.parts[0])
    ):
        raise RecoveryError("Recovery path is unsafe")
    return "/".join(parsed.parts)


def _duration(started_at: datetime | None, ended_at: datetime | None) -> float | None:
    if started_at is None or ended_at is None:
        return None
    return max(0.0, (ended_at - started_at).total_seconds() * 1000)


@dataclass(frozen=True, slots=True)
class RecoveryOperationResult:
    """Redacted result for one deterministic Recovery operation."""

    operation: RecoveryOperationType
    relative_path: str
    expected_entry_type: ManifestEntryType | None
    attempted: bool
    succeeded: bool
    reason: str | None = None
    expected_sha256: str | None = None
    final_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", RecoveryOperationType(self.operation))
        object.__setattr__(self, "relative_path", _safe_relative(self.relative_path))
        if self.expected_entry_type is not None:
            object.__setattr__(
                self,
                "expected_entry_type",
                ManifestEntryType(self.expected_entry_type),
            )
        if not isinstance(self.attempted, bool) or not isinstance(self.succeeded, bool):
            raise RecoveryError("operation attempted/succeeded must be bool")
        if self.succeeded and not self.attempted:
            raise RecoveryError("a successful operation must be attempted")
        for field_name in ("expected_sha256", "final_sha256"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise RecoveryError(f"{field_name} must be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class RecoveryPlanOperation:
    """Immutable planned operation produced before Workspace mutation."""

    operation: RecoveryOperationType
    relative_path: str
    expected_entry_type: ManifestEntryType | None = None
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", RecoveryOperationType(self.operation))
        object.__setattr__(self, "relative_path", _safe_relative(self.relative_path))
        if self.expected_entry_type is not None:
            object.__setattr__(
                self,
                "expected_entry_type",
                ManifestEntryType(self.expected_entry_type),
            )


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """Trusted, deterministic plan for one Recovery attempt."""

    operations: tuple[RecoveryPlanOperation, ...]
    current_entry_count: int
    expected_entry_count: int
    workspace_matches: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))
        if self.current_entry_count < 0 or self.expected_entry_count < 0:
            raise RecoveryError("Recovery plan entry counts must be non-negative")


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Immutable Recovery execution result; Integrity is a separate axis."""

    recovery_id: str
    aia_session_id: str
    action_id: str | None
    termination_id: str | None
    checkpoint_id: str | None
    recovery_status: RecoveryStatus
    started_at: datetime | None
    ended_at: datetime
    duration_ms: float | None
    planned_operation_count: int
    attempted_operation_count: int
    succeeded_operation_count: int
    failed_operation_count: int
    restored_paths: tuple[str, ...] = field(default_factory=tuple)
    removed_paths: tuple[str, ...] = field(default_factory=tuple)
    failed_paths: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None
    limitations: tuple[str, ...] = field(default_factory=tuple)
    operation_results: tuple[RecoveryOperationResult, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in ("recovery_id", "aia_session_id"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name):
                raise RecoveryError(f"{field_name} must be non-empty")
        object.__setattr__(self, "recovery_status", RecoveryStatus(self.recovery_status))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", _aware_utc(self.started_at, field_name="started_at"))
        object.__setattr__(self, "ended_at", _aware_utc(self.ended_at, field_name="ended_at"))
        if self.duration_ms is not None and self.duration_ms < 0:
            raise RecoveryError("duration_ms must be non-negative")
        for field_name in (
            "planned_operation_count",
            "attempted_operation_count",
            "succeeded_operation_count",
            "failed_operation_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RecoveryError(f"{field_name} must be non-negative")
        object.__setattr__(self, "operation_results", tuple(self.operation_results))
        for field_name in ("restored_paths", "removed_paths", "failed_paths", "limitations"):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value for value in values):
                raise RecoveryError(f"{field_name} must contain non-empty strings")
            object.__setattr__(self, field_name, values)

    @property
    def status(self) -> RecoveryStatus:
        return self.recovery_status

    @property
    def is_restored(self) -> bool:
        return self.recovery_status is RecoveryStatus.RESTORED


@dataclass(frozen=True, slots=True)
class RecoveryVerificationResult:
    """Combined result that keeps Recovery and Integrity axes independent."""

    recovery: RecoveryResult
    integrity: IntegrityVerificationResult

    @property
    def recovery_result(self) -> RecoveryResult:
        return self.recovery

    @property
    def integrity_result(self) -> IntegrityVerificationResult:
        return self.integrity

    @property
    def recovery_status(self) -> RecoveryStatus:
        return self.recovery.recovery_status

    @property
    def integrity_status(self) -> IntegrityStatus:
        return self.integrity.integrity_status

    @property
    def verified_recovery_success(self) -> bool:
        return (
            self.recovery_status is RecoveryStatus.RESTORED
            and self.integrity_status is IntegrityStatus.VERIFIED
        )


class _RecoverySafetyFailure(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _RecoveryOperationFailure(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _lexical_join(root: Path, relative_path: str) -> Path:
    relative = _safe_relative(relative_path)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    if not candidate.is_relative_to(root):
        raise _RecoverySafetyFailure("PATH_ESCAPE")
    return candidate


def _junction_flag(path: Path) -> bool:
    detector = getattr(path, "is_junction", None)
    try:
        return bool(callable(detector) and detector())
    except OSError as error:
        raise _RecoverySafetyFailure("UNVERIFIABLE_PATH") from error


def _kind(path: Path) -> ManifestEntryType | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _RecoverySafetyFailure("UNVERIFIABLE_PATH") from error
    try:
        return checkpoint_module._classify_entry_info(
            path,
            info,
            is_junction=_junction_flag(path),
        )
    except UnsupportedFilesystemEntryError as error:
        raise _RecoverySafetyFailure("UNSUPPORTED_CURRENT_FILESYSTEM_ENTRY") from error


def _safe_existing_kind(root: Path, relative_path: str) -> ManifestEntryType | None:
    """Check every existing path component without following link-like entries."""

    relative = _safe_relative(relative_path)
    current = root
    for index, part in enumerate(PurePosixPath(relative).parts):
        current = current / part
        kind = _kind(current)
        if kind is None:
            return None
        if index < len(PurePosixPath(relative).parts) - 1 and kind is not ManifestEntryType.DIRECTORY:
            raise _RecoverySafetyFailure("UNSAFE_TARGET_TYPE")
    return kind


def _ensure_directory(root: Path, relative_path: str) -> None:
    relative = _safe_relative(relative_path)
    current = root
    parts = PurePosixPath(relative).parts
    for part in parts:
        current = current / part
        kind = _kind(current)
        if kind is None:
            try:
                current.mkdir()
            except FileExistsError:
                kind = _kind(current)
            except OSError as error:
                raise _RecoveryOperationFailure("DIRECTORY_CREATE_FAILED") from error
        if kind is not None and kind is not ManifestEntryType.DIRECTORY:
            raise _RecoverySafetyFailure("UNSAFE_TARGET_TYPE")


def _remove_directory_tree(path: Path) -> None:
    kind = _kind(path)
    if kind is None:
        return
    if kind is not ManifestEntryType.DIRECTORY:
        raise _RecoverySafetyFailure("UNSAFE_TARGET_TYPE")
    try:
        children = sorted(os.scandir(path), key=lambda item: item.name)
    except OSError as error:
        raise _RecoveryOperationFailure("DIRECTORY_SCAN_FAILED") from error
    for child in children:
        child_path = Path(child.path)
        child_kind = _kind(child_path)
        if child_kind is ManifestEntryType.DIRECTORY:
            _remove_directory_tree(child_path)
        elif child_kind is ManifestEntryType.FILE:
            try:
                child_path.unlink()
            except OSError as error:
                raise _RecoveryOperationFailure("FILE_REMOVE_FAILED") from error
    try:
        path.rmdir()
    except OSError as error:
        raise _RecoveryOperationFailure("DIRECTORY_REMOVE_FAILED") from error


def _remove_path(root: Path, relative_path: str) -> None:
    path = _lexical_join(root, relative_path)
    kind = _safe_existing_kind(root, relative_path)
    if kind is None:
        return
    if kind is ManifestEntryType.DIRECTORY:
        _remove_directory_tree(path)
        return
    try:
        path.unlink()
    except OSError as error:
        raise _RecoveryOperationFailure("FILE_REMOVE_FAILED") from error


def _safe_source_path(checkpoint: SafeCheckpoint, relative_path: str) -> Path:
    snapshot_root = checkpoint.checkpoint_path / "workspace"
    path = _lexical_join(snapshot_root, relative_path)
    _safe_existing_kind(snapshot_root, relative_path)
    return path


def _read_source(checkpoint: SafeCheckpoint, entry: ManifestEntry) -> bytes:
    if entry.entry_type is not ManifestEntryType.FILE:
        raise _RecoveryOperationFailure("EXPECTED_FILE_REQUIRED")
    source = _safe_source_path(checkpoint, entry.relative_path)
    if _kind(source) is not ManifestEntryType.FILE:
        raise _RecoverySafetyFailure("CHECKPOINT_SOURCE_INVALID")
    digest = hashlib.sha256()
    size = 0
    chunks: list[bytes] = []
    try:
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                chunks.append(chunk)
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise _RecoverySafetyFailure("CHECKPOINT_SOURCE_UNREADABLE") from error
    if size != entry.size or digest.hexdigest() != entry.sha256:
        raise _RecoverySafetyFailure("CHECKPOINT_SOURCE_TAMPERED")
    return b"".join(chunks)


def _validate_checkpoint_sources(checkpoint: SafeCheckpoint) -> None:
    for entry in checkpoint.manifest:
        if entry.entry_type is ManifestEntryType.FILE:
            _read_source(checkpoint, entry)
        else:
            source = _safe_source_path(checkpoint, entry.relative_path)
            if _kind(source) is not ManifestEntryType.DIRECTORY:
                raise _RecoverySafetyFailure("CHECKPOINT_SOURCE_INVALID")


def _replace_file(checkpoint: SafeCheckpoint, root: Path, entry: ManifestEntry) -> str:
    content = _read_source(checkpoint, entry)
    target = _lexical_join(root, entry.relative_path)
    parent_relative = "/".join(PurePosixPath(entry.relative_path).parts[:-1])
    if parent_relative:
        _ensure_directory(root, parent_relative)
    existing = _safe_existing_kind(root, entry.relative_path)
    if existing is ManifestEntryType.DIRECTORY:
        raise _RecoverySafetyFailure("UNSAFE_TARGET_TYPE")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=".aia-recovery-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_existing_kind(root, entry.relative_path)
        os.replace(temporary, target)
        temporary = None
    except _RecoverySafetyFailure:
        raise
    except OSError as error:
        raise _RecoveryOperationFailure("FILE_REPLACE_FAILED") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return entry.sha256 or ""


def _remove_descendant(path: str, ancestor: str) -> bool:
    return path != ancestor and path.startswith(ancestor + "/")


def _build_plan(
    checkpoint: SafeCheckpoint,
    workspace: Path,
) -> RecoveryPlan:
    expected = tuple(checkpoint.manifest)
    expected_by_path = {entry.relative_path: entry for entry in expected}
    try:
        current = checkpoint_module._scan_workspace(workspace)
    except UnsupportedFilesystemEntryError as error:
        raise _RecoverySafetyFailure("UNSUPPORTED_CURRENT_FILESYSTEM_ENTRY") from error
    except (WorkspaceChangedDuringCheckpoint, OSError) as error:
        raise _RecoverySafetyFailure("WORKSPACE_SCAN_FAILED") from error
    current_by_path = {entry.relative_path: entry for entry in current}

    conflicts = sorted(
        path
        for path in set(expected_by_path) & set(current_by_path)
        if expected_by_path[path].entry_type is not current_by_path[path].entry_type
    )
    conflict_roots = tuple(
        path
        for path in conflicts
        if not any(_remove_descendant(path, ancestor) for ancestor in conflicts)
    )

    def under_conflict(path: str) -> bool:
        return any(path == root or _remove_descendant(path, root) for root in conflict_roots)

    operations: list[RecoveryPlanOperation] = []
    for path in conflict_roots:
        expected_entry = expected_by_path[path]
        operations.append(
            RecoveryPlanOperation(
                RecoveryOperationType.REPLACE_TYPE_CONFLICT,
                path,
                expected_entry.entry_type,
                expected_entry.sha256,
            )
        )

    missing_directories = [
        entry
        for entry in expected
        if entry.entry_type is ManifestEntryType.DIRECTORY
        and entry.relative_path not in current_by_path
        and not under_conflict(entry.relative_path)
    ]
    for entry in sorted(missing_directories, key=lambda item: (item.relative_path.count("/"), item.relative_path)):
        operations.append(
            RecoveryPlanOperation(
                RecoveryOperationType.CREATE_DIRECTORY,
                entry.relative_path,
                ManifestEntryType.DIRECTORY,
            )
        )

    unexpected_files = [
        entry
        for entry in current
        if entry.relative_path not in expected_by_path
        and entry.entry_type is ManifestEntryType.FILE
        and not under_conflict(entry.relative_path)
    ]
    for entry in sorted(unexpected_files, key=lambda item: item.relative_path):
        operations.append(
            RecoveryPlanOperation(
                RecoveryOperationType.REMOVE_UNEXPECTED_FILE,
                entry.relative_path,
                ManifestEntryType.FILE,
            )
        )

    restore_files = [
        entry
        for entry in expected
        if entry.entry_type is ManifestEntryType.FILE
        and not under_conflict(entry.relative_path)
        and (
            entry.relative_path not in current_by_path
            or current_by_path[entry.relative_path].entry_type is not ManifestEntryType.FILE
            or current_by_path[entry.relative_path].size != entry.size
            or current_by_path[entry.relative_path].sha256 != entry.sha256
        )
    ]
    for entry in restore_files:
        operations.append(
            RecoveryPlanOperation(
                RecoveryOperationType.RESTORE_FILE,
                entry.relative_path,
                ManifestEntryType.FILE,
                entry.sha256,
            )
        )

    unexpected_directories = [
        entry
        for entry in current
        if entry.relative_path not in expected_by_path
        and entry.entry_type is ManifestEntryType.DIRECTORY
        and not under_conflict(entry.relative_path)
    ]
    for entry in sorted(
        unexpected_directories,
        key=lambda item: (-item.relative_path.count("/"), item.relative_path),
    ):
        operations.append(
            RecoveryPlanOperation(
                RecoveryOperationType.REMOVE_UNEXPECTED_DIRECTORY,
                entry.relative_path,
                ManifestEntryType.DIRECTORY,
            )
        )

    return RecoveryPlan(
        operations=tuple(operations),
        current_entry_count=len(current),
        expected_entry_count=len(expected),
        workspace_matches=not operations,
    )


@dataclass(frozen=True, slots=True)
class _RecoveryContext:
    session: ProtectedRunSession
    checkpoint: SafeCheckpoint
    lease: WorkspaceLease
    gate_result: EnforcementGateResult
    termination_result: ProcessTerminationResult
    launch_context: Any | None


class RecoveryCoordinator:
    """Coordinate only safe, post-termination whole-Workspace Recovery."""

    def __init__(
        self,
        lease_manager: WorkspaceLeaseManager,
        *,
        integrity_verifier: IntegrityVerifier | None = None,
    ) -> None:
        if lease_manager is None or not callable(getattr(lease_manager, "validate_ownership", None)):
            raise RecoveryError("lease_manager must validate ownership")
        self.lease_manager = lease_manager
        self.integrity_verifier = integrity_verifier or IntegrityVerifier()

    def build_plan(
        self,
        checkpoint: SafeCheckpoint,
        *,
        workspace: Path | str | None = None,
    ) -> RecoveryPlan:
        target = canonicalize_workspace(workspace or checkpoint.workspace)
        return _build_plan(checkpoint, target)

    def recover(
        self,
        gate_result: EnforcementGateResult,
        termination_result: ProcessTerminationResult | None = None,
        *,
        process_termination_result: ProcessTerminationResult | None = None,
        session: ProtectedRunSession,
        checkpoint: SafeCheckpoint | str | Path | None,
        workspace_lease: WorkspaceLease | None,
        launch_context: "ProtectedLaunchContext | None" = None,
        expected_launch_id: str | None = None,
        workspace: Path | str | None = None,
    ) -> RecoveryVerificationResult:
        if termination_result is None:
            termination_result = process_termination_result
        session_id = getattr(session, "session_id", "unknown")
        action_id = getattr(gate_result, "action_id", None)
        termination_id = getattr(termination_result, "termination_id", None)
        checkpoint_id = getattr(checkpoint, "checkpoint_id", None)
        eligibility = self._check_eligibility(
            gate_result,
            termination_result,
            session=session,
            launch_context=launch_context,
            expected_launch_id=expected_launch_id,
        )
        if eligibility is not None:
            status, reason = eligibility
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=status,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    reason=reason,
                ),
            )

        assert termination_result is not None
        if checkpoint is None:
            reason = "CHECKPOINT_MISSING"
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=None,
                    status=RecoveryStatus.RECOVERY_UNAVAILABLE,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    reason=reason,
                ),
            )

        try:
            safe_checkpoint = self._load_and_validate_checkpoint(checkpoint)
        except _RecoverySafetyFailure as error:
            reason = error.reason
            status = RecoveryStatus.RECOVERY_UNAVAILABLE
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=status,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    reason=reason,
                ),
            )
        checkpoint_id = safe_checkpoint.checkpoint_id

        binding_reason = self._check_bindings(
            safe_checkpoint,
            session=session,
            workspace_lease=workspace_lease,
            workspace=workspace,
            launch_context=launch_context,
        )
        if binding_reason is not None:
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason=binding_reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=binding_reason,
                ),
            )

        target = canonicalize_workspace(workspace or session.workspace)
        try:
            self.lease_manager.validate_ownership(workspace_lease)
            _validate_checkpoint_sources(safe_checkpoint)
            plan = _build_plan(safe_checkpoint, target)
        except ProtectionError:
            reason = "WORKSPACE_LEASE_INVALID"
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=reason,
                ),
            )
        except _RecoverySafetyFailure as error:
            reason = error.reason
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=(
                        RecoveryStatus.RECOVERY_UNAVAILABLE
                        if reason.startswith("CHECKPOINT_")
                        else RecoveryStatus.REFUSED
                    ),
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=reason,
                ),
            )
        except Exception:
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason="RECOVERY_PREFLIGHT_FAILED",
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason="RECOVERY_PREFLIGHT_FAILED",
                ),
            )

        if plan.workspace_matches:
            integrity = self.integrity_verifier.verify(
                safe_checkpoint,
                workspace=target,
                session=session,
            )
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=action_id,
                    termination_id=termination_id,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.NOT_REQUIRED,
                    reason="WORKSPACE_ALREADY_MATCHES_CHECKPOINT",
                    planned_operation_count=0,
                ),
                integrity,
            )

        started_at = datetime.now(timezone.utc)
        operation_results: list[RecoveryOperationResult] = []
        restored_paths: list[str] = []
        removed_paths: list[str] = []
        failed_paths: list[str] = []
        mutation_started = False
        security_failure: str | None = None
        for operation in plan.operations:
            try:
                self.lease_manager.validate_ownership(workspace_lease)
            except ProtectionError:
                security_failure = "WORKSPACE_LEASE_INVALID"
                failed_paths.append(operation.relative_path)
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=False,
                        succeeded=False,
                        reason=security_failure,
                        expected_sha256=operation.expected_sha256,
                    )
                )
                break
            try:
                mutation_started = True
                final_sha256 = self._apply_operation(
                    operation,
                    checkpoint=safe_checkpoint,
                    workspace=target,
                )
                result = RecoveryOperationResult(
                    operation=operation.operation,
                    relative_path=operation.relative_path,
                    expected_entry_type=operation.expected_entry_type,
                    attempted=True,
                    succeeded=True,
                    expected_sha256=operation.expected_sha256,
                    final_sha256=final_sha256,
                )
                operation_results.append(result)
                if operation.operation in {
                    RecoveryOperationType.RESTORE_FILE,
                    RecoveryOperationType.CREATE_DIRECTORY,
                    RecoveryOperationType.REPLACE_TYPE_CONFLICT,
                }:
                    restored_paths.append(operation.relative_path)
                else:
                    removed_paths.append(operation.relative_path)
            except _RecoverySafetyFailure as error:
                security_failure = error.reason
                failed_paths.append(operation.relative_path)
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=True,
                        succeeded=False,
                        reason=error.reason,
                        expected_sha256=operation.expected_sha256,
                    )
                )
                break
            except _RecoveryOperationFailure as error:
                reason = getattr(error, "reason", "RECOVERY_OPERATION_FAILED")
                failed_paths.append(operation.relative_path)
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=True,
                        succeeded=False,
                        reason=reason,
                        expected_sha256=operation.expected_sha256,
                    )
                )

        ended_at = datetime.now(timezone.utc)
        attempted_count = sum(int(item.attempted) for item in operation_results)
        succeeded_count = sum(int(item.succeeded) for item in operation_results)
        failed_count = sum(int(not item.succeeded) for item in operation_results)
        if failed_count == 0:
            status = RecoveryStatus.RESTORED
        elif security_failure is not None and not mutation_started:
            status = RecoveryStatus.REFUSED
        else:
            status = RecoveryStatus.FAILED
        reason = security_failure or (None if status is RecoveryStatus.RESTORED else "RECOVERY_OPERATION_FAILED")
        recovery = RecoveryResult(
            recovery_id=str(uuid4()),
            aia_session_id=session_id,
            action_id=action_id,
            termination_id=termination_id,
            checkpoint_id=checkpoint_id,
            recovery_status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=_duration(started_at, ended_at),
            planned_operation_count=len(plan.operations),
            attempted_operation_count=attempted_count,
            succeeded_operation_count=succeeded_count,
            failed_operation_count=failed_count,
            restored_paths=tuple(restored_paths),
            removed_paths=tuple(removed_paths),
            failed_paths=tuple(failed_paths),
            reason=reason,
            limitations=(
                "RECOVERY_MUTATION_IS_NOT_WHOLE_WORKSPACE_ATOMIC"
                if mutation_started
                else "",
            ) if mutation_started else (),
            operation_results=tuple(operation_results),
        )
        integrity = (
            self.integrity_verifier.verify(
                safe_checkpoint,
                workspace=target,
                session=session,
            )
            if mutation_started
            else IntegrityVerificationResult.not_checked(
                aia_session_id=session_id,
                checkpoint_id=checkpoint_id,
                checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                reason=reason,
            )
        )
        return self._combined(recovery, integrity)

    execute = recover
    restore = recover

    def restore_manual(
        self,
        *,
        session: ProtectedRunSession,
        checkpoint: SafeCheckpoint | str | Path | None,
        workspace_lease: WorkspaceLease | None,
        workspace: Path | str | None = None,
    ) -> RecoveryVerificationResult:
        """Restore a completed run after an explicit user request.

        Manual restoration is deliberately separate from policy containment.
        It requires a valid checkpoint, a newly acquired current lease, and
        the same Workspace binding, but it does not fabricate a policy gate or
        process-termination result.
        """

        session_id = getattr(session, "session_id", "unknown")
        checkpoint_id = getattr(checkpoint, "checkpoint_id", None)
        try:
            safe_checkpoint = self._load_and_validate_checkpoint(checkpoint) if checkpoint is not None else None
        except _RecoverySafetyFailure as error:
            reason = error.reason
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.RECOVERY_UNAVAILABLE,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    reason=reason,
                ),
            )
        if safe_checkpoint is None:
            reason = "CHECKPOINT_MISSING"
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=None,
                    status=RecoveryStatus.RECOVERY_UNAVAILABLE,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    reason=reason,
                ),
            )
        checkpoint_id = safe_checkpoint.checkpoint_id
        binding_reason = self._check_bindings(
            safe_checkpoint,
            session=session,
            workspace_lease=workspace_lease,
            workspace=workspace,
            launch_context=None,
        )
        if binding_reason is not None:
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason=binding_reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=binding_reason,
                ),
            )
        target = canonicalize_workspace(workspace or session.workspace)
        try:
            self.lease_manager.validate_ownership(workspace_lease)
            _validate_checkpoint_sources(safe_checkpoint)
            plan = _build_plan(safe_checkpoint, target)
        except ProtectionError:
            reason = "WORKSPACE_LEASE_INVALID"
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=reason,
                ),
            )
        except _RecoverySafetyFailure as error:
            reason = error.reason
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.RECOVERY_UNAVAILABLE,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=reason,
                ),
            )
        except Exception:
            reason = "RECOVERY_PREFLIGHT_FAILED"
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.REFUSED,
                    reason=reason,
                ),
                IntegrityVerificationResult.not_checked(
                    aia_session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                    reason=reason,
                ),
            )
        if plan.workspace_matches:
            return self._combined(
                self._result(
                    session_id=session_id,
                    action_id=None,
                    termination_id=None,
                    checkpoint_id=checkpoint_id,
                    status=RecoveryStatus.NOT_REQUIRED,
                    reason="WORKSPACE_ALREADY_MATCHES_CHECKPOINT",
                ),
                self.integrity_verifier.verify(
                    safe_checkpoint,
                    workspace=target,
                    session=session,
                ),
            )

        started_at = datetime.now(timezone.utc)
        operation_results: list[RecoveryOperationResult] = []
        restored_paths: list[str] = []
        removed_paths: list[str] = []
        failed_paths: list[str] = []
        mutation_started = False
        security_failure: str | None = None
        for operation in plan.operations:
            try:
                self.lease_manager.validate_ownership(workspace_lease)
                mutation_started = True
                final_sha256 = self._apply_operation(
                    operation,
                    checkpoint=safe_checkpoint,
                    workspace=target,
                )
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=True,
                        succeeded=True,
                        expected_sha256=operation.expected_sha256,
                        final_sha256=final_sha256,
                    )
                )
                if operation.operation in {
                    RecoveryOperationType.RESTORE_FILE,
                    RecoveryOperationType.CREATE_DIRECTORY,
                    RecoveryOperationType.REPLACE_TYPE_CONFLICT,
                }:
                    restored_paths.append(operation.relative_path)
                else:
                    removed_paths.append(operation.relative_path)
            except ProtectionError:
                security_failure = "WORKSPACE_LEASE_INVALID"
                failed_paths.append(operation.relative_path)
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=False,
                        succeeded=False,
                        reason=security_failure,
                        expected_sha256=operation.expected_sha256,
                    )
                )
                break
            except (_RecoverySafetyFailure, _RecoveryOperationFailure) as error:
                reason = getattr(error, "reason", "RECOVERY_OPERATION_FAILED")
                if isinstance(error, _RecoverySafetyFailure):
                    security_failure = reason
                failed_paths.append(operation.relative_path)
                operation_results.append(
                    RecoveryOperationResult(
                        operation=operation.operation,
                        relative_path=operation.relative_path,
                        expected_entry_type=operation.expected_entry_type,
                        attempted=True,
                        succeeded=False,
                        reason=reason,
                        expected_sha256=operation.expected_sha256,
                    )
                )
                if security_failure is not None:
                    break

        ended_at = datetime.now(timezone.utc)
        attempted_count = sum(int(item.attempted) for item in operation_results)
        succeeded_count = sum(int(item.succeeded) for item in operation_results)
        failed_count = sum(int(not item.succeeded) for item in operation_results)
        status = (
            RecoveryStatus.RESTORED
            if failed_count == 0
            else RecoveryStatus.REFUSED
            if security_failure is not None and not mutation_started
            else RecoveryStatus.FAILED
        )
        reason = security_failure or (
            None if status is RecoveryStatus.RESTORED else "RECOVERY_OPERATION_FAILED"
        )
        recovery = RecoveryResult(
            recovery_id=str(uuid4()),
            aia_session_id=session_id,
            action_id=None,
            termination_id=None,
            checkpoint_id=checkpoint_id,
            recovery_status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=_duration(started_at, ended_at),
            planned_operation_count=len(plan.operations),
            attempted_operation_count=attempted_count,
            succeeded_operation_count=succeeded_count,
            failed_operation_count=failed_count,
            restored_paths=tuple(restored_paths),
            removed_paths=tuple(removed_paths),
            failed_paths=tuple(failed_paths),
            reason=reason,
            limitations=("RECOVERY_MUTATION_IS_NOT_WHOLE_WORKSPACE_ATOMIC",)
            if mutation_started
            else (),
            operation_results=tuple(operation_results),
        )
        integrity = (
            self.integrity_verifier.verify(safe_checkpoint, workspace=target, session=session)
            if mutation_started
            else IntegrityVerificationResult.not_checked(
                aia_session_id=session_id,
                checkpoint_id=checkpoint_id,
                checkpoint_fingerprint=safe_checkpoint.checkpoint_content_sha256,
                reason=reason,
            )
        )
        return self._combined(recovery, integrity)

    def _load_and_validate_checkpoint(
        self,
        checkpoint: SafeCheckpoint | str | Path,
    ) -> SafeCheckpoint:
        if isinstance(checkpoint, SafeCheckpoint):
            result = validate_checkpoint(checkpoint)
            if result.validity is not CheckpointValidity.VALID:
                reason = (
                    "CHECKPOINT_MISSING"
                    if not checkpoint.checkpoint_path.exists()
                    else "CHECKPOINT_TAMPERED"
                )
                raise _RecoverySafetyFailure(reason)
            return checkpoint
        checkpoint_path = Path(checkpoint)
        result = validate_checkpoint(checkpoint_path)
        if result.validity is not CheckpointValidity.VALID:
            reason = "CHECKPOINT_MISSING" if not checkpoint_path.exists() else "CHECKPOINT_INVALID"
            raise _RecoverySafetyFailure(reason)
        try:
            metadata, manifest = checkpoint_module._validate_artifact(checkpoint_path)
            return checkpoint_module._checkpoint_from_artifact(
                checkpoint_path,
                metadata,
                manifest,
            )
        except Exception as error:
            raise _RecoverySafetyFailure("CHECKPOINT_INVALID") from error

    def _check_eligibility(
        self,
        gate_result: EnforcementGateResult,
        termination_result: ProcessTerminationResult | None,
        *,
        session: ProtectedRunSession,
        launch_context: Any | None,
        expected_launch_id: str | None,
    ) -> tuple[RecoveryStatus, str] | None:
        if not isinstance(gate_result, EnforcementGateResult):
            return RecoveryStatus.REFUSED, "ENFORCEMENT_RESULT_INVALID"
        if gate_result.aia_session_id != session.session_id:
            return RecoveryStatus.REFUSED, "SESSION_MISMATCH"
        if session.status is not SessionStatus.RUNNING:
            return RecoveryStatus.REFUSED, "SESSION_NOT_RUNNING"
        if gate_result.route is EnforcementRoute.PRETOOL_BLOCK or gate_result.action is EnforcementAction.BLOCKED:
            return RecoveryStatus.NOT_REQUIRED, "PRETOOL_ACTION_BLOCKED"
        if gate_result.decision is not EnforcementDecision.CONTAIN or gate_result.route is not EnforcementRoute.PROCESS_TERMINATION:
            return RecoveryStatus.NOT_REQUIRED, "AUTOMATIC_RECOVERY_NOT_REQUIRED"
        if not isinstance(termination_result, ProcessTerminationResult):
            return RecoveryStatus.REFUSED, "TERMINATION_RESULT_MISSING"
        if termination_result.aia_session_id != session.session_id:
            return RecoveryStatus.REFUSED, "SESSION_MISMATCH"
        if expected_launch_id is not None and termination_result.launch_id != expected_launch_id:
            return RecoveryStatus.REFUSED, "LAUNCH_MISMATCH"
        if launch_context is not None:
            if getattr(launch_context, "launch_id", None) != termination_result.launch_id:
                return RecoveryStatus.REFUSED, "LAUNCH_MISMATCH"
            if getattr(launch_context, "aia_session_id", None) != session.session_id:
                return RecoveryStatus.REFUSED, "SESSION_MISMATCH"
        if (
            termination_result.outcome is not ProcessTerminationOutcome.TERMINATED
            or termination_result.action is not EnforcementAction.TERMINATED
            or termination_result.execution_result is not EnforcementExecutionResult.SUCCEEDED
        ):
            return RecoveryStatus.REFUSED, "ENFORCEMENT_NOT_SAFELY_COMPLETED"
        return None

    def _check_bindings(
        self,
        checkpoint: SafeCheckpoint,
        *,
        session: ProtectedRunSession,
        workspace_lease: WorkspaceLease | None,
        workspace: Path | str | None,
        launch_context: Any | None,
    ) -> str | None:
        if checkpoint.session_id != session.session_id:
            return "SESSION_MISMATCH"
        if checkpoint.workspace != session.workspace:
            return "WORKSPACE_MISMATCH"
        if workspace is not None:
            try:
                if canonicalize_workspace(workspace) != session.workspace:
                    return "WORKSPACE_MISMATCH"
            except Exception:
                return "WORKSPACE_MISMATCH"
        if launch_context is not None:
            try:
                if canonicalize_workspace(launch_context.workspace) != session.workspace:
                    return "WORKSPACE_MISMATCH"
            except Exception:
                return "WORKSPACE_MISMATCH"
        if not isinstance(workspace_lease, WorkspaceLease):
            return "WORKSPACE_LEASE_INVALID"
        if workspace_lease.session_id != session.session_id:
            return "SESSION_MISMATCH"
        if workspace_lease.workspace != session.workspace:
            return "WORKSPACE_MISMATCH"
        return None

    def _apply_operation(
        self,
        operation: RecoveryPlanOperation,
        *,
        checkpoint: SafeCheckpoint,
        workspace: Path,
    ) -> str | None:
        expected = next(
            (
                entry
                for entry in checkpoint.manifest
                if entry.relative_path == operation.relative_path
            ),
            None,
        )
        if operation.operation is RecoveryOperationType.RESTORE_FILE:
            if expected is None:
                raise _RecoveryOperationFailure("EXPECTED_MANIFEST_ENTRY_MISSING")
            return _replace_file(checkpoint, workspace, expected)
        if operation.operation is RecoveryOperationType.CREATE_DIRECTORY:
            _ensure_directory(workspace, operation.relative_path)
            return None
        if operation.operation in {
            RecoveryOperationType.REMOVE_UNEXPECTED_FILE,
            RecoveryOperationType.REMOVE_UNEXPECTED_DIRECTORY,
        }:
            _remove_path(workspace, operation.relative_path)
            return None
        if operation.operation is RecoveryOperationType.REPLACE_TYPE_CONFLICT:
            _remove_path(workspace, operation.relative_path)
            if expected is None:
                raise _RecoveryOperationFailure("EXPECTED_MANIFEST_ENTRY_MISSING")
            if expected.entry_type is ManifestEntryType.DIRECTORY:
                _ensure_directory(workspace, expected.relative_path)
                return None
            return _replace_file(checkpoint, workspace, expected)
        raise _RecoveryOperationFailure("UNKNOWN_RECOVERY_OPERATION")

    @staticmethod
    def _result(
        *,
        session_id: str,
        action_id: str | None,
        termination_id: str | None,
        checkpoint_id: str | None,
        status: RecoveryStatus,
        reason: str | None,
        planned_operation_count: int = 0,
    ) -> RecoveryResult:
        ended_at = datetime.now(timezone.utc)
        return RecoveryResult(
            recovery_id=str(uuid4()),
            aia_session_id=session_id,
            action_id=action_id,
            termination_id=termination_id,
            checkpoint_id=checkpoint_id,
            recovery_status=status,
            started_at=None,
            ended_at=ended_at,
            duration_ms=None,
            planned_operation_count=planned_operation_count,
            attempted_operation_count=0,
            succeeded_operation_count=0,
            failed_operation_count=0,
            reason=reason,
        )

    @staticmethod
    def _combined(
        recovery: RecoveryResult,
        integrity: IntegrityVerificationResult,
    ) -> RecoveryVerificationResult:
        return RecoveryVerificationResult(recovery=recovery, integrity=integrity)


def recover_workspace(
    gate_result: EnforcementGateResult,
    termination_result: ProcessTerminationResult | None,
    *,
    session: ProtectedRunSession,
    checkpoint: SafeCheckpoint | str | Path | None,
    workspace_lease: WorkspaceLease | None,
    lease_manager: WorkspaceLeaseManager,
    launch_context: "ProtectedLaunchContext | None" = None,
) -> RecoveryVerificationResult:
    return RecoveryCoordinator(lease_manager).recover(
        gate_result,
        termination_result,
        session=session,
        checkpoint=checkpoint,
        workspace_lease=workspace_lease,
        launch_context=launch_context,
    )


__all__ = [
    "RecoveryCoordinator",
    "RecoveryError",
    "RecoveryOperation",
    "RecoveryOperationResult",
    "RecoveryOperationType",
    "RecoveryPlan",
    "RecoveryPlanOperation",
    "RecoveryResult",
    "RecoveryStatus",
    "RecoveryState",
    "RecoveryVerificationResult",
    "recover_workspace",
]
