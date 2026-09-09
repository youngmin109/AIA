"""Control-root, active-policy, and workspace-lease preparation contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import time
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .policy import (
    Operation,
    PolicyProfile,
    PolicyRule,
    PolicyValidationError,
    ResolvedPolicy,
    SecurityAssetPolicy,
)
from .session import (
    ProtectedRunSession,
    SessionStatus,
    WorkspaceValidationError,
    canonicalize_workspace,
)


class ProtectionError(ValueError):
    """Base error for static protected-run preparation."""


class ControlRootValidationError(ProtectionError):
    """Raised when the AIA control root crosses the workspace boundary."""


class ActivePolicyFreezeError(ProtectionError):
    """Raised when an active policy cannot be frozen safely."""


class ActivePolicyIdentityMismatch(ActivePolicyFreezeError):
    """Raised when session and resolved policy identity do not match."""


class ActivePolicyAlreadyFrozen(ActivePolicyFreezeError):
    """Raised when an active policy artifact already exists for a session."""

    code = "ALREADY_FROZEN"


class ActivePolicyConflict(ActivePolicyFreezeError):
    """Raised when an existing session artifact has different content."""

    code = "ACTIVE_POLICY_CONFLICT"


class ActivePolicyArtifactError(ActivePolicyFreezeError):
    """Raised when the active policy artifact cannot be used safely."""


class WorkspaceLeaseError(ProtectionError):
    """Base error for workspace lease operations."""


class WorkspaceBusyError(WorkspaceLeaseError):
    """Raised when a live matching workspace lease already exists."""

    code = "WORKSPACE_BUSY"

    def __init__(self, existing_lease: "WorkspaceLease") -> None:
        self.existing_lease = existing_lease
        super().__init__(
            f"workspace is protected by session {existing_lease.session_id}"
        )


class WorkspaceOwnerUnverifiableError(WorkspaceLeaseError):
    """Raised when an existing lease owner cannot be verified safely."""

    code = "OWNER_UNVERIFIABLE"

    def __init__(self, existing_lease: "WorkspaceLease") -> None:
        self.existing_lease = existing_lease
        super().__init__(
            "workspace lease owner cannot be verified; takeover is refused"
        )


class LeaseOwnershipError(WorkspaceLeaseError):
    """Raised when a caller cannot prove current lease ownership."""


class LeaseArtifactError(WorkspaceLeaseError):
    """Raised when a lease artifact is malformed or unusable."""


class ProtectionPreparationError(ProtectionError):
    """Raised when static preparation cannot produce a context."""


ProcessIdentityProvider = Callable[[int], float]


class LeaseOwnerStatus(StrEnum):
    """Result of verifying the process that owns an existing lease."""

    LIVE_MATCH = "LIVE_MATCH"
    STALE_PROCESS_GONE = "STALE_PROCESS_GONE"
    STALE_PID_REUSED = "STALE_PID_REUSED"
    OWNER_UNVERIFIABLE = "OWNER_UNVERIFIABLE"


OwnerVerificationStatus = LeaseOwnerStatus
OwnerUnverifiableError = WorkspaceOwnerUnverifiableError


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProtectionError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_session_id(session_id: str) -> str:
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or session_id in {".", ".."}
        or any(separator in session_id for separator in ("/", "\\"))
    ):
        raise ProtectionError("session_id is not a safe directory name")
    return session_id


def _is_nested(first: Path, second: Path) -> bool:
    """Return whether first is second or is contained by second."""

    return first == second or first.is_relative_to(second)


@dataclass(frozen=True, slots=True)
class ControlRoot:
    """Canonical AIA control data root separated from one workspace."""

    workspace: Path
    path: Path
    sessions_path: Path
    leases_path: Path

    @classmethod
    def for_workspace(
        cls,
        workspace: str | Path,
        control_root: str | Path,
    ) -> "ControlRoot":
        try:
            workspace_path = canonicalize_workspace(workspace)
        except WorkspaceValidationError as error:
            raise ControlRootValidationError(str(error)) from error

        try:
            candidate = Path(control_root).expanduser().resolve(strict=False)
            if candidate.exists() and not candidate.is_dir():
                raise ControlRootValidationError(
                    f"control_root must be a directory: {candidate}"
                )
            if _is_nested(candidate, workspace_path) or _is_nested(
                workspace_path,
                candidate,
            ):
                raise ControlRootValidationError(
                    "control_root and workspace must not overlap"
                )
            candidate.mkdir(parents=True, exist_ok=True)
            root_path = candidate.resolve(strict=True)
        except ControlRootValidationError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise ControlRootValidationError(
                f"control_root cannot be created safely: {control_root!r}"
            ) from error

        sessions_path = root_path / "sessions"
        leases_path = root_path / "workspaces"
        try:
            sessions_path.mkdir(parents=True, exist_ok=True)
            leases_path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ControlRootValidationError(
                "control_root subdirectories cannot be created"
            ) from error
        return cls(
            workspace=workspace_path,
            path=root_path,
            sessions_path=sessions_path.resolve(strict=True),
            leases_path=leases_path.resolve(strict=True),
        )

    create = for_workspace

    def session_directory(self, session_id: str) -> Path:
        safe_id = _safe_session_id(session_id)
        candidate = self.sessions_path / safe_id
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ControlRootValidationError(
                f"session control directory cannot be created: {candidate}"
            ) from error
        if not resolved.is_relative_to(self.path):
            raise ControlRootValidationError(
                "session control directory escaped control_root"
            )
        return resolved

    def workspace_lease_directory(self, workspace: str | Path) -> Path:
        try:
            workspace_path = canonicalize_workspace(workspace)
        except WorkspaceValidationError as error:
            raise ControlRootValidationError(str(error)) from error
        if workspace_path != self.workspace:
            raise ControlRootValidationError(
                "workspace does not match the control root binding"
            )
        identity = workspace_identity(workspace_path)
        directory = self.leases_path / identity
        try:
            directory.mkdir(parents=True, exist_ok=True)
            resolved = directory.resolve(strict=True)
        except OSError as error:
            raise ControlRootValidationError(
                f"workspace lease directory cannot be created: {directory}"
            ) from error
        if not resolved.is_relative_to(self.path):
            raise ControlRootValidationError(
                "workspace lease directory escaped control_root"
            )
        return resolved


def workspace_identity(workspace: str | Path) -> str:
    """Return a deterministic, non-path filename for a canonical workspace."""

    canonical = canonicalize_workspace(workspace)
    identity_text = str(canonical).replace("\\", "/").casefold()
    return hashlib.sha256(identity_text.encode("utf-8")).hexdigest()


def _coerce_control_root(
    workspace: Path,
    control_root: ControlRoot | str | Path,
) -> ControlRoot:
    if isinstance(control_root, ControlRoot):
        if control_root.workspace != workspace:
            raise ControlRootValidationError(
                "control root is bound to another workspace"
            )
        return control_root
    return ControlRoot.for_workspace(workspace, control_root)


@contextmanager
def _exclusive_file_lock(lock_path: Path):
    """Serialize lease inspection and replacement with a stdlib file lock."""

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise LeaseArtifactError(
            f"workspace lease lock cannot be acquired: {lock_path}"
        ) from error


def _rule_mapping(rule: PolicyRule) -> dict[str, Any]:
    operation_effects = {
        operation.value: effect.value
        for operation, effect in sorted(
            rule.operation_effects.items(),
            key=lambda item: item[0].value,
        )
    }
    result: dict[str, Any] = {
        "asset_type": rule.asset_type.value,
        "operation_effects": operation_effects,
        "priority": rule.priority,
        "rule_id": rule.rule_id,
    }
    if rule.path_patterns:
        result["path_patterns"] = list(rule.path_patterns)
    else:
        result["command_patterns"] = list(rule.command_patterns)
    return result


def policy_content_mapping(resolved_policy: ResolvedPolicy) -> dict[str, Any]:
    """Return policy content excluding session artifact metadata."""

    policy = resolved_policy.policy
    rules = sorted(
        (_rule_mapping(rule) for rule in policy.rules),
        key=lambda rule: (rule["rule_id"], rule["priority"]),
    )
    return {
        "default_effect": policy.default_effect.value,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "profile": resolved_policy.profile.value,
        "rules": rules,
        "schema_version": policy.schema_version,
    }


def serialize_policy_content(resolved_policy: ResolvedPolicy) -> bytes:
    """Serialize policy content deterministically for hashing."""

    return json.dumps(
        policy_content_mapping(resolved_policy),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def policy_content_sha256(resolved_policy: ResolvedPolicy) -> str:
    return hashlib.sha256(serialize_policy_content(resolved_policy)).hexdigest()


@dataclass(frozen=True, slots=True)
class ActivePolicySnapshot:
    session_id: str
    policy_id: str
    policy_version: str
    profile: PolicyProfile
    frozen_at: datetime
    artifact_path: Path
    sha256: str
    policy: SecurityAssetPolicy

    @property
    def policy_content_sha256(self) -> str:
        return self.sha256

    @property
    def frozen_policy(self) -> SecurityAssetPolicy:
        return self.policy


class ActivePolicyFreezer:
    """Freeze a validated policy into one session control directory."""

    @staticmethod
    def validate_inputs(
        session: ProtectedRunSession,
        resolved_policy: ResolvedPolicy,
    ) -> None:
        if not isinstance(session, ProtectedRunSession):
            raise ActivePolicyFreezeError(
                "session must be a ProtectedRunSession"
            )
        if not isinstance(resolved_policy, ResolvedPolicy):
            raise ActivePolicyFreezeError(
                "resolved_policy must be a ResolvedPolicy"
            )
        if session.status is not SessionStatus.PREPARING:
            raise ActivePolicyFreezeError(
                "active policy can be frozen only in PREPARING"
            )
        if session.policy_id != resolved_policy.policy_id:
            raise ActivePolicyIdentityMismatch(
                "session policy_id does not match resolved policy"
            )
        if session.policy_version != resolved_policy.policy_version:
            raise ActivePolicyIdentityMismatch(
                "session policy_version does not match resolved policy"
            )

    def freeze(
        self,
        session: ProtectedRunSession,
        resolved_policy: ResolvedPolicy,
        control_root: ControlRoot | str | Path,
        *,
        frozen_at: datetime | None = None,
    ) -> ActivePolicySnapshot:
        self.validate_inputs(session, resolved_policy)
        root = _coerce_control_root(session.workspace, control_root)
        control_directory = root.session_directory(session.session_id)
        artifact_path = control_directory / "active-policy.json"
        content_hash = policy_content_sha256(resolved_policy)
        freeze_time = _aware_utc(
            frozen_at if frozen_at is not None else _now_utc(),
            field_name="frozen_at",
        )
        content = policy_content_mapping(resolved_policy)
        artifact: dict[str, Any] = {
            **content,
            "frozen_at": freeze_time.isoformat(),
            "policy_content_sha256": content_hash,
            "session_id": session.session_id,
        }
        serialized_artifact = json.dumps(
            artifact,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"

        if artifact_path.exists():
            self._raise_existing_artifact(artifact_path, content_hash)
        try:
            with artifact_path.open("xb") as stream:
                stream.write(serialized_artifact)
        except FileExistsError:
            self._raise_existing_artifact(artifact_path, content_hash)
        except OSError as error:
            raise ActivePolicyArtifactError(
                f"active policy artifact cannot be written: {artifact_path}"
            ) from error

        return ActivePolicySnapshot(
            session_id=session.session_id,
            policy_id=resolved_policy.policy_id,
            policy_version=resolved_policy.policy_version,
            profile=resolved_policy.profile,
            frozen_at=freeze_time,
            artifact_path=artifact_path.resolve(strict=True),
            sha256=content_hash,
            policy=resolved_policy.policy,
        )

    def freeze_or_reuse(
        self,
        session: ProtectedRunSession,
        resolved_policy: ResolvedPolicy,
        control_root: ControlRoot | str | Path,
        *,
        frozen_at: datetime | None = None,
    ) -> ActivePolicySnapshot:
        """Freeze once, or reuse the matching immutable artifact on retry."""

        try:
            return self.freeze(
                session,
                resolved_policy,
                control_root,
                frozen_at=frozen_at,
            )
        except ActivePolicyAlreadyFrozen:
            return self.load_existing(
                session,
                resolved_policy,
                control_root,
            )

    def load_existing(
        self,
        session: ProtectedRunSession,
        resolved_policy: ResolvedPolicy,
        control_root: ControlRoot | str | Path,
    ) -> ActivePolicySnapshot:
        """Load an existing artifact only when it matches the resolved policy."""

        self.validate_inputs(session, resolved_policy)
        root = _coerce_control_root(session.workspace, control_root)
        artifact_path = root.session_directory(session.session_id) / "active-policy.json"
        if not artifact_path.exists() or not artifact_path.is_file():
            raise ActivePolicyArtifactError(
                f"active policy artifact does not exist: {artifact_path}"
            )
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ActivePolicyArtifactError(
                f"existing active policy artifact is unreadable: {artifact_path}"
            ) from error
        if not isinstance(artifact, dict):
            raise ActivePolicyArtifactError(
                f"existing active policy artifact must be an object: {artifact_path}"
            )

        expected_content = policy_content_mapping(resolved_policy)
        if artifact.get("policy_content_sha256") != policy_content_sha256(
            resolved_policy
        ):
            raise ActivePolicyConflict(
                f"active policy artifact has different content: {artifact_path}"
            )
        if any(artifact.get(key) != value for key, value in expected_content.items()):
            raise ActivePolicyArtifactError(
                f"active policy artifact content does not match its fingerprint: "
                f"{artifact_path}"
            )
        if artifact.get("session_id") != session.session_id:
            raise ActivePolicyArtifactError(
                f"active policy artifact belongs to another session: {artifact_path}"
            )
        try:
            frozen_at = _aware_utc(
                datetime.fromisoformat(artifact["frozen_at"]),
                field_name="frozen_at",
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ActivePolicyArtifactError(
                f"active policy artifact has invalid frozen_at: {artifact_path}"
            ) from error
        return ActivePolicySnapshot(
            session_id=session.session_id,
            policy_id=resolved_policy.policy_id,
            policy_version=resolved_policy.policy_version,
            profile=resolved_policy.profile,
            frozen_at=frozen_at,
            artifact_path=artifact_path.resolve(strict=True),
            sha256=policy_content_sha256(resolved_policy),
            policy=resolved_policy.policy,
        )

    @staticmethod
    def _raise_existing_artifact(
        artifact_path: Path,
        content_hash: str,
    ) -> None:
        if artifact_path.is_dir():
            raise ActivePolicyArtifactError(
                f"active policy artifact path is a directory: {artifact_path}"
            )
        try:
            existing = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ActivePolicyArtifactError(
                f"existing active policy artifact is unreadable: {artifact_path}"
            ) from error
        if existing.get("policy_content_sha256") == content_hash:
            raise ActivePolicyAlreadyFrozen(
                f"active policy is already frozen: {artifact_path}"
            )
        raise ActivePolicyConflict(
            f"active policy artifact has different content: {artifact_path}"
        )


def freeze_active_policy(
    session: ProtectedRunSession,
    resolved_policy: ResolvedPolicy,
    control_root: ControlRoot | str | Path,
    *,
    frozen_at: datetime | None = None,
) -> ActivePolicySnapshot:
    return ActivePolicyFreezer().freeze(
        session,
        resolved_policy,
        control_root,
        frozen_at=frozen_at,
    )


def _windows_process_create_time(pid: int) -> float:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == 5:  # ERROR_ACCESS_DENIED
            raise PermissionError(error_code, "process access denied", pid)
        raise ProcessLookupError(pid)

    class FileTime(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        success = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not success:
            error_code = ctypes.get_last_error()
            if error_code == 5:  # ERROR_ACCESS_DENIED
                raise PermissionError(error_code, "process access denied", pid)
            raise OSError(error_code, "GetProcessTimes failed", pid)
    finally:
        kernel32.CloseHandle(handle)
    windows_ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    return windows_ticks / 10_000_000 - 11_644_473_600


def _proc_process_create_time(pid: int) -> float:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
        start_ticks = int(fields[21])
        clock_ticks = os.sysconf("SC_CLK_TCK")
        boot_time = float(Path("/proc/stat").read_text().split("btime ", 1)[1].splitlines()[0])
    except PermissionError:
        raise
    except FileNotFoundError as error:
        raise ProcessLookupError(pid) from error
    except (OSError, IndexError, ValueError, AttributeError):
        raise
    return boot_time + start_ticks / clock_ticks


def process_create_time(pid: int) -> float:
    """Read process creation time without adding a runtime dependency."""

    if not isinstance(pid, int) or pid <= 0:
        raise ProcessLookupError(pid)
    if os.name == "nt":
        return _windows_process_create_time(pid)
    return _proc_process_create_time(pid)


def _lease_metadata(lease: "WorkspaceLease") -> dict[str, Any]:
    return {
        "acquired_at": lease.acquired_at.isoformat(),
        "owner_pid": lease.owner_pid,
        "owner_process_create_time": lease.owner_process_create_time,
        "session_id": lease.session_id,
        "workspace": str(lease.workspace),
    }


@dataclass(frozen=True, slots=True)
class StaleLeaseRecord:
    reason: str
    previous_session_id: str | None
    previous_owner_pid: int | None
    previous_owner_process_create_time: float | None
    detected_at: datetime
    artifact_path: Path

    @property
    def session_id(self) -> str | None:
        return self.previous_session_id

    @property
    def owner_pid(self) -> int | None:
        return self.previous_owner_pid

    @property
    def owner_process_create_time(self) -> float | None:
        return self.previous_owner_process_create_time


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    workspace: Path
    session_id: str
    owner_pid: int
    owner_process_create_time: float
    acquired_at: datetime
    artifact_path: Path
    stale_record: StaleLeaseRecord | None = None
    reused: bool = field(default=False, compare=False, repr=False)

    def release(self, manager: "WorkspaceLeaseManager") -> None:
        manager.release(self)


class WorkspaceLeaseManager:
    """Manage one PID/create-time verified lease per canonical workspace."""

    def __init__(
        self,
        control_root: ControlRoot | str | Path,
        *,
        process_identity_provider: ProcessIdentityProvider = process_create_time,
    ) -> None:
        self.control_root = control_root
        self.process_identity_provider = process_identity_provider

    def acquire(
        self,
        workspace: str | Path,
        session_id: str,
        *,
        owner_pid: int | None = None,
        owner_process_create_time: float | None = None,
        acquired_at: datetime | None = None,
    ) -> WorkspaceLease:
        safe_session_id = _safe_session_id(session_id)
        workspace_path = canonicalize_workspace(workspace)
        root = _coerce_control_root(workspace_path, self.control_root)
        lease_directory = root.workspace_lease_directory(workspace_path)
        artifact_path = lease_directory / "lease.json"
        pid = os.getpid() if owner_pid is None else owner_pid
        try:
            create_time = (
                owner_process_create_time
                if owner_process_create_time is not None
                else self.process_identity_provider(pid)
            )
        except (OSError, ProcessLookupError, ValueError) as error:
            raise LeaseOwnershipError(
                f"cannot establish owner process identity for PID {pid}"
            ) from error
        if not isinstance(create_time, (float, int)) or isinstance(create_time, bool):
            raise LeaseOwnershipError("owner process create time must be numeric")

        lease = WorkspaceLease(
            workspace=workspace_path,
            session_id=safe_session_id,
            owner_pid=pid,
            owner_process_create_time=float(create_time),
            acquired_at=_aware_utc(
                acquired_at if acquired_at is not None else _now_utc(),
                field_name="acquired_at",
            ),
            artifact_path=artifact_path.resolve(strict=False),
        )
        with _exclusive_file_lock(lease_directory / ".lease.lock"):
            try:
                self._write_lease_exclusive(artifact_path, lease)
                return lease
            except FileExistsError:
                # The exclusive create is the first ownership decision. From
                # here on, all contenders inspect the same existing artifact
                # while holding the workspace lock.
                existing = self._read_lease(artifact_path)

            existing_lease = self._lease_from_mapping(existing, artifact_path)
            owner_status = self._owner_status(existing)
            if owner_status is LeaseOwnerStatus.LIVE_MATCH:
                if (
                    existing_lease.session_id == safe_session_id
                    and existing_lease.owner_pid == pid
                    and existing_lease.owner_process_create_time
                    == float(create_time)
                ):
                    return replace(existing_lease, reused=True)
                raise WorkspaceBusyError(existing_lease)
            if owner_status is LeaseOwnerStatus.OWNER_UNVERIFIABLE:
                raise WorkspaceOwnerUnverifiableError(existing_lease)

            stale_record = self._preserve_stale(
                artifact_path,
                existing,
                owner_status.value,
            )
            replacement = replace(lease, stale_record=stale_record)
            self._replace_lease_atomically(artifact_path, replacement)
            return replacement

    @staticmethod
    def _write_lease_exclusive(
        artifact_path: Path,
        lease: WorkspaceLease,
    ) -> None:
        try:
            with artifact_path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    _lease_metadata(lease),
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                stream.write("\n")
        except FileExistsError:
            raise
        except OSError as error:
            raise LeaseArtifactError(
                f"workspace lease artifact cannot be written: {artifact_path}"
            ) from error

    @classmethod
    def _replace_lease_atomically(
        cls,
        artifact_path: Path,
        lease: WorkspaceLease,
    ) -> None:
        temporary_path = artifact_path.parent / f".lease-{uuid4().hex}.tmp"
        try:
            cls._write_lease_exclusive(temporary_path, lease)
            os.replace(temporary_path, artifact_path)
        except (OSError, LeaseArtifactError) as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise LeaseArtifactError(
                f"workspace lease artifact cannot be replaced atomically: "
                f"{artifact_path}"
            ) from error

    def _owner_status(
        self,
        existing: Mapping[str, Any],
    ) -> LeaseOwnerStatus:
        try:
            pid = existing["owner_pid"]
            stored_create_time = existing["owner_process_create_time"]
        except KeyError as error:
            raise LeaseArtifactError(
                "workspace lease artifact has no owner identity"
            ) from error
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise LeaseArtifactError("lease owner PID must be a positive integer")
        if not isinstance(stored_create_time, (int, float)) or isinstance(
            stored_create_time,
            bool,
        ):
            raise LeaseArtifactError("lease owner create time must be numeric")
        try:
            current_create_time = self.process_identity_provider(pid)
        except ProcessLookupError:
            return LeaseOwnerStatus.STALE_PROCESS_GONE
        except Exception:
            # Permission errors and other OS/provider failures are evidence
            # gaps. They are never evidence that the owner is stale.
            return LeaseOwnerStatus.OWNER_UNVERIFIABLE
        if not isinstance(current_create_time, (int, float)) or isinstance(
            current_create_time,
            bool,
        ):
            return LeaseOwnerStatus.OWNER_UNVERIFIABLE
        if float(current_create_time) != float(stored_create_time):
            return LeaseOwnerStatus.STALE_PID_REUSED
        return LeaseOwnerStatus.LIVE_MATCH

    def release(
        self,
        lease_or_workspace: WorkspaceLease | str | Path,
        session_id: str | None = None,
        *,
        owner_pid: int | None = None,
        owner_process_create_time: float | None = None,
    ) -> None:
        if isinstance(lease_or_workspace, WorkspaceLease):
            lease = lease_or_workspace
            workspace = lease.workspace
            expected_session_id = lease.session_id
            expected_pid = lease.owner_pid
            expected_create_time = lease.owner_process_create_time
        else:
            workspace = canonicalize_workspace(lease_or_workspace)
            if session_id is None:
                raise LeaseOwnershipError("session_id is required for release")
            expected_session_id = _safe_session_id(session_id)
            expected_pid = os.getpid() if owner_pid is None else owner_pid
            try:
                expected_create_time = (
                    owner_process_create_time
                    if owner_process_create_time is not None
                    else self.process_identity_provider(expected_pid)
                )
            except (OSError, ProcessLookupError, ValueError) as error:
                raise LeaseOwnershipError(
                    "cannot establish releasing process identity"
                ) from error

        root = _coerce_control_root(canonicalize_workspace(workspace), self.control_root)
        lease_directory = root.workspace_lease_directory(workspace)
        artifact_path = lease_directory / "lease.json"
        with _exclusive_file_lock(lease_directory / ".lease.lock"):
            if not artifact_path.exists() or not artifact_path.is_file():
                raise LeaseOwnershipError("workspace lease does not exist")
            current = self._read_lease(artifact_path)
            if current.get("session_id") != expected_session_id:
                raise LeaseOwnershipError("lease is owned by another session")
            if current.get("owner_pid") != expected_pid:
                raise LeaseOwnershipError("lease owner PID does not match")
            try:
                current_create_time = self.process_identity_provider(expected_pid)
            except (OSError, ProcessLookupError, ValueError) as error:
                raise LeaseOwnershipError(
                    "lease owner process is no longer verifiable"
                ) from error
            stored_create_time = current.get("owner_process_create_time")
            if current_create_time != stored_create_time:
                raise LeaseOwnershipError(
                    "lease owner process create time does not match"
                )
            if expected_create_time != stored_create_time:
                raise LeaseOwnershipError("release identity does not match lease")
            try:
                artifact_path.unlink()
            except OSError as error:
                raise LeaseArtifactError(
                    f"workspace lease cannot be released: {artifact_path}"
                ) from error

    def validate_ownership(self, lease: WorkspaceLease) -> WorkspaceLease:
        """Revalidate the current on-disk lease without changing it."""

        if not isinstance(lease, WorkspaceLease):
            raise LeaseOwnershipError("lease must be a WorkspaceLease")
        workspace_path = canonicalize_workspace(lease.workspace)
        root = _coerce_control_root(workspace_path, self.control_root)
        lease_directory = root.workspace_lease_directory(workspace_path)
        artifact_path = lease_directory / "lease.json"
        with _exclusive_file_lock(lease_directory / ".lease.lock"):
            if not artifact_path.exists() or not artifact_path.is_file():
                raise LeaseOwnershipError("workspace lease does not exist")
            current = self._read_lease(artifact_path)
            current_lease = self._lease_from_mapping(current, artifact_path)
            if current_lease.workspace != workspace_path:
                raise LeaseOwnershipError("lease workspace does not match")
            if current_lease.session_id != lease.session_id:
                raise LeaseOwnershipError("lease is owned by another session")
            if current_lease.owner_pid != lease.owner_pid:
                raise LeaseOwnershipError("lease owner PID does not match")
            if (
                current_lease.owner_process_create_time
                != lease.owner_process_create_time
            ):
                raise LeaseOwnershipError(
                    "lease owner process create time does not match"
                )
            owner_status = self._owner_status(current)
            if owner_status is LeaseOwnerStatus.OWNER_UNVERIFIABLE:
                raise WorkspaceOwnerUnverifiableError(current_lease)
            if owner_status is not LeaseOwnerStatus.LIVE_MATCH:
                raise LeaseOwnershipError(
                    f"lease owner is not live: {owner_status.value}"
                )
            return current_lease

    def _read_lease(self, artifact_path: Path) -> dict[str, Any]:
        if artifact_path.is_dir():
            raise LeaseArtifactError(
                f"workspace lease artifact is a directory: {artifact_path}"
            )
        try:
            value = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LeaseArtifactError(
                f"workspace lease artifact is unreadable: {artifact_path}"
            ) from error
        if not isinstance(value, dict):
            raise LeaseArtifactError("workspace lease artifact must be an object")
        return value

    def _stale_reason(self, existing: Mapping[str, Any]) -> str | None:
        status = self._owner_status(existing)
        return None if status is LeaseOwnerStatus.LIVE_MATCH else status.value

    def _preserve_stale(
        self,
        artifact_path: Path,
        existing: Mapping[str, Any],
        reason: str,
    ) -> StaleLeaseRecord:
        detected_at = _now_utc()
        stale_path = artifact_path.parent / f"stale-lease-{uuid4().hex}.json"
        previous_session_id = existing.get("session_id")
        if not isinstance(previous_session_id, str):
            previous_session_id = None
        previous_pid = existing.get("owner_pid")
        if not isinstance(previous_pid, int) or isinstance(previous_pid, bool):
            previous_pid = None
        previous_create_time = existing.get("owner_process_create_time")
        if not isinstance(previous_create_time, (int, float)) or isinstance(
            previous_create_time,
            bool,
        ):
            previous_create_time = None
        record = StaleLeaseRecord(
            reason=reason,
            previous_session_id=previous_session_id,
            previous_owner_pid=previous_pid,
            previous_owner_process_create_time=(
                float(previous_create_time)
                if previous_create_time is not None
                else None
            ),
            detected_at=detected_at,
            artifact_path=stale_path,
        )
        payload = {
            "detected_at": detected_at.isoformat(),
            "owner_pid": record.previous_owner_pid,
            "owner_process_create_time": record.previous_owner_process_create_time,
            "previous_owner_pid": record.previous_owner_pid,
            "previous_owner_process_create_time": record.previous_owner_process_create_time,
            "previous_session_id": record.previous_session_id,
            "reason": record.reason,
            "previous_lease": dict(existing),
            "session_id": record.previous_session_id,
        }
        try:
            with stale_path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
        except OSError as error:
            raise LeaseArtifactError(
                f"stale lease evidence cannot be preserved: {stale_path}"
            ) from error
        return record

    def _lease_from_mapping(
        self,
        value: Mapping[str, Any],
        artifact_path: Path,
        *,
        reused: bool = False,
    ) -> WorkspaceLease:
        try:
            workspace = canonicalize_workspace(value["workspace"])
            session_id = _safe_session_id(value["session_id"])
            owner_pid = value["owner_pid"]
            create_time = value["owner_process_create_time"]
            acquired_at = datetime.fromisoformat(value["acquired_at"])
        except (KeyError, TypeError, ValueError, WorkspaceValidationError) as error:
            raise LeaseArtifactError(
                f"invalid workspace lease artifact: {artifact_path}"
            ) from error
        if not isinstance(owner_pid, int) or isinstance(owner_pid, bool):
            raise LeaseArtifactError("lease owner PID must be an integer")
        if not isinstance(create_time, (int, float)) or isinstance(create_time, bool):
            raise LeaseArtifactError("lease owner create time must be numeric")
        return WorkspaceLease(
            workspace=workspace,
            session_id=session_id,
            owner_pid=owner_pid,
            owner_process_create_time=float(create_time),
            acquired_at=_aware_utc(acquired_at, field_name="acquired_at"),
            artifact_path=artifact_path,
            reused=reused,
        )


LeaseManager = WorkspaceLeaseManager


@dataclass(frozen=True, slots=True)
class ProtectionPreparationContext:
    """Static preparation result; it deliberately does not mean READY."""

    session_id: str
    workspace: Path
    active_policy: ActivePolicySnapshot
    workspace_lease: WorkspaceLease
    control_directory: Path
    prepared_at: datetime

    @property
    def is_static_preparation_complete(self) -> bool:
        return True


def prepare_protection(
    session: ProtectedRunSession,
    resolved_policy: ResolvedPolicy,
    control_root: ControlRoot | str | Path,
    *,
    lease_manager: WorkspaceLeaseManager | None = None,
    owner_pid: int | None = None,
    owner_process_create_time: float | None = None,
    frozen_at: datetime | None = None,
    acquired_at: datetime | None = None,
    prepared_at: datetime | None = None,
) -> ProtectionPreparationContext:
    """Freeze policy and acquire workspace ownership while staying PREPARING."""

    ActivePolicyFreezer.validate_inputs(session, resolved_policy)
    prepared_time = _aware_utc(
        prepared_at if prepared_at is not None else _now_utc(),
        field_name="prepared_at",
    )

    manager = lease_manager or WorkspaceLeaseManager(control_root)
    freezer = ActivePolicyFreezer()
    snapshot = freezer.freeze_or_reuse(
        session,
        resolved_policy,
        control_root,
        frozen_at=frozen_at,
    )
    lease: WorkspaceLease | None = None
    try:
        lease = manager.acquire(
            session.workspace,
            session.session_id,
            owner_pid=owner_pid,
            owner_process_create_time=owner_process_create_time,
            acquired_at=acquired_at,
        )
    except (ProtectionError, OSError, ValueError):
        # The immutable policy artifact is intentionally retained. A later
        # call can reuse it after the competing Workspace Lease is released.
        raise

    try:
        if session.status is not SessionStatus.PREPARING:
            raise ProtectionPreparationError(
                "preparation context cannot change session lifecycle"
            )
        return ProtectionPreparationContext(
            session_id=session.session_id,
            workspace=session.workspace,
            active_policy=snapshot,
            workspace_lease=lease,
            control_directory=snapshot.artifact_path.parent,
            prepared_at=prepared_time,
        )
    except (ProtectionError, OSError, ValueError):
        if lease is not None and not lease.reused:
            try:
                manager.release(lease)
            except ProtectionError:
                pass
        raise


__all__ = [
    "ActivePolicyAlreadyFrozen",
    "ActivePolicyArtifactError",
    "ActivePolicyConflict",
    "ActivePolicyFreezeError",
    "ActivePolicyFreezer",
    "ActivePolicyIdentityMismatch",
    "ActivePolicySnapshot",
    "ControlRoot",
    "ControlRootValidationError",
    "LeaseArtifactError",
    "LeaseOwnerStatus",
    "LeaseManager",
    "LeaseOwnershipError",
    "OwnerUnverifiableError",
    "OwnerVerificationStatus",
    "ProcessIdentityProvider",
    "ProtectionError",
    "ProtectionPreparationContext",
    "ProtectionPreparationError",
    "StaleLeaseRecord",
    "WorkspaceBusyError",
    "WorkspaceLease",
    "WorkspaceLeaseError",
    "WorkspaceLeaseManager",
    "WorkspaceOwnerUnverifiableError",
    "freeze_active_policy",
    "policy_content_mapping",
    "policy_content_sha256",
    "prepare_protection",
    "process_create_time",
    "serialize_policy_content",
    "workspace_identity",
]
