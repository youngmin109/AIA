"""Independent Workspace integrity verification for Safe Checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .checkpoint import (
    CheckpointValidity,
    ManifestEntry,
    SafeCheckpoint,
    UnsupportedFilesystemEntryError,
    WorkspaceChangedDuringCheckpoint,
    _scan_workspace,
    validate_checkpoint,
)
from .session import canonicalize_workspace

if TYPE_CHECKING:
    from .session import ProtectedRunSession


class IntegrityError(ValueError):
    """Base error for integrity verification contracts."""


class IntegrityStatus(StrEnum):
    """The independent final Workspace integrity axis."""

    NOT_CHECKED = "NOT_CHECKED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IntegrityError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _tuple_paths(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value for value in result):
        raise IntegrityError("integrity paths must be non-empty strings")
    return result


@dataclass(frozen=True, slots=True)
class IntegrityVerificationResult:
    """Immutable comparison result for a Trusted Checkpoint Manifest."""

    aia_session_id: str
    checkpoint_id: str | None
    integrity_status: IntegrityStatus
    integrity_started_at: datetime | None
    integrity_ended_at: datetime | None
    integrity_duration_ms: float | None
    verified_at: datetime | None
    checkpoint_fingerprint: str | None
    expected_entry_count: int
    actual_entry_count: int
    missing_paths: tuple[str, ...] = field(default_factory=tuple)
    unexpected_paths: tuple[str, ...] = field(default_factory=tuple)
    type_mismatches: tuple[str, ...] = field(default_factory=tuple)
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    verification_errors: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.aia_session_id, str) or not self.aia_session_id:
            raise IntegrityError("aia_session_id must be non-empty")
        object.__setattr__(
            self,
            "integrity_status",
            IntegrityStatus(self.integrity_status),
        )
        for field_name in ("integrity_started_at", "integrity_ended_at", "verified_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _aware_utc(value, field_name=field_name),
                )
        if self.integrity_duration_ms is not None and (
            not isinstance(self.integrity_duration_ms, (int, float))
            or self.integrity_duration_ms < 0
        ):
            raise IntegrityError("integrity_duration_ms must be non-negative")
        for field_name in (
            "expected_entry_count",
            "actual_entry_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise IntegrityError(f"{field_name} must be non-negative")
        for field_name in (
            "missing_paths",
            "unexpected_paths",
            "type_mismatches",
            "changed_paths",
            "verification_errors",
            "limitations",
        ):
            object.__setattr__(
                self,
                field_name,
                _tuple_paths(getattr(self, field_name)),
            )

    @property
    def status(self) -> IntegrityStatus:
        return self.integrity_status

    @property
    def is_verified(self) -> bool:
        return self.integrity_status is IntegrityStatus.VERIFIED

    @classmethod
    def not_checked(
        cls,
        *,
        aia_session_id: str,
        checkpoint_id: str | None = None,
        checkpoint_fingerprint: str | None = None,
        reason: str | None = None,
    ) -> "IntegrityVerificationResult":
        return cls(
            aia_session_id=aia_session_id,
            checkpoint_id=checkpoint_id,
            integrity_status=IntegrityStatus.NOT_CHECKED,
            integrity_started_at=None,
            integrity_ended_at=None,
            integrity_duration_ms=None,
            verified_at=None,
            checkpoint_fingerprint=checkpoint_fingerprint,
            expected_entry_count=0,
            actual_entry_count=0,
            reason=reason,
        )


IntegrityResult = IntegrityVerificationResult
IntegrityVerificationStatus = IntegrityStatus


def _manifest_map(entries: tuple[ManifestEntry, ...]) -> dict[str, ManifestEntry]:
    return {entry.relative_path: entry for entry in entries}


class IntegrityVerifier:
    """Compare a live Workspace against an immutable checkpoint manifest."""

    def __init__(self, *, two_pass: bool = True) -> None:
        self.two_pass = two_pass

    def verify(
        self,
        checkpoint: SafeCheckpoint,
        *,
        workspace: Path | str | None = None,
        session: "ProtectedRunSession | None" = None,
    ) -> IntegrityVerificationResult:
        started_at = datetime.now(timezone.utc)
        session_id = session.session_id if session is not None else checkpoint.session_id
        target = canonicalize_workspace(workspace or checkpoint.workspace)
        errors: list[str] = []
        limitations: list[str] = []
        expected = tuple(checkpoint.manifest)
        expected_by_path = _manifest_map(expected)
        actual_entries: tuple[ManifestEntry, ...] = ()
        first_entries: tuple[ManifestEntry, ...] | None = None

        try:
            checkpoint_validation = validate_checkpoint(checkpoint)
            if (
                checkpoint.validity is not CheckpointValidity.VALID
                or not checkpoint_validation.is_valid
            ):
                errors.append("CHECKPOINT_INVALID")
            else:
                first_entries = _scan_workspace(target)
                actual_entries = first_entries
                if self.two_pass:
                    second_entries = _scan_workspace(target)
                    if second_entries != first_entries:
                        errors.append("WORKSPACE_CHANGED_DURING_INTEGRITY")
                    actual_entries = second_entries
        except UnsupportedFilesystemEntryError:
            errors.append("UNSUPPORTED_CURRENT_FILESYSTEM_ENTRY")
        except (WorkspaceChangedDuringCheckpoint, OSError, ValueError):
            errors.append("INTEGRITY_SCAN_FAILED")
        except Exception:
            errors.append("INTEGRITY_SCAN_FAILED")

        actual_by_path = _manifest_map(actual_entries)
        missing = tuple(sorted(set(expected_by_path) - set(actual_by_path)))
        unexpected = tuple(sorted(set(actual_by_path) - set(expected_by_path)))
        type_mismatches = tuple(
            sorted(
                path
                for path in set(expected_by_path) & set(actual_by_path)
                if expected_by_path[path].entry_type
                is not actual_by_path[path].entry_type
            )
        )
        changed = tuple(
            sorted(
                path
                for path in set(expected_by_path) & set(actual_by_path)
                if expected_by_path[path].entry_type.value == "FILE"
                and (
                    expected_by_path[path].size != actual_by_path[path].size
                    or expected_by_path[path].sha256 != actual_by_path[path].sha256
                )
            )
        )
        if missing:
            errors.append("MISSING_PATHS")
        if unexpected:
            errors.append("UNEXPECTED_PATHS")
        if type_mismatches:
            errors.append("TYPE_MISMATCH")
        if changed:
            errors.append("SHA256_MISMATCH")
        errors = list(dict.fromkeys(errors))
        ended_at = datetime.now(timezone.utc)
        status = IntegrityStatus.VERIFIED if not errors else IntegrityStatus.FAILED
        reason = None if status is IntegrityStatus.VERIFIED else errors[0]
        return IntegrityVerificationResult(
            aia_session_id=session_id,
            checkpoint_id=checkpoint.checkpoint_id,
            integrity_status=status,
            integrity_started_at=started_at,
            integrity_ended_at=ended_at,
            integrity_duration_ms=max(0.0, (ended_at - started_at).total_seconds() * 1000),
            verified_at=ended_at,
            checkpoint_fingerprint=checkpoint.checkpoint_content_sha256,
            expected_entry_count=len(expected),
            actual_entry_count=len(actual_entries),
            missing_paths=missing,
            unexpected_paths=unexpected,
            type_mismatches=type_mismatches,
            changed_paths=changed,
            verification_errors=tuple(errors),
            limitations=tuple(limitations),
            reason=reason,
        )


def verify_integrity(
    checkpoint: SafeCheckpoint,
    *,
    workspace: Path | str | None = None,
    session: "ProtectedRunSession | None" = None,
    two_pass: bool = True,
) -> IntegrityVerificationResult:
    return IntegrityVerifier(two_pass=two_pass).verify(
        checkpoint,
        workspace=workspace,
        session=session,
    )


__all__ = [
    "IntegrityError",
    "IntegrityResult",
    "IntegrityStatus",
    "IntegrityVerificationStatus",
    "IntegrityVerificationResult",
    "IntegrityVerifier",
    "verify_integrity",
]
