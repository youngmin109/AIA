"""PID plus process-create-time identity contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from pathlib import Path
from typing import Any, Callable

import psutil

from .session import canonicalize_workspace


class ProcessIdentityError(ValueError):
    """Raised when a Process Identity or registration is invalid."""


class ProcessIdentityStatus(StrEnum):
    LIVE_MATCH = "LIVE_MATCH"
    PROCESS_GONE = "PROCESS_GONE"
    PID_REUSED = "PID_REUSED"
    OWNER_UNVERIFIABLE = "OWNER_UNVERIFIABLE"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProcessIdentityError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_text(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or any(separator in value for separator in ("/", "\\"))
    ):
        raise ProcessIdentityError(f"{field_name} must be a safe non-empty value")
    return value


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """The minimum stable identity of one operating-system process."""

    pid: int
    create_time: float

    def __post_init__(self) -> None:
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise ProcessIdentityError("pid must be a positive integer")
        if (
            not isinstance(self.create_time, (int, float))
            or isinstance(self.create_time, bool)
            or not math.isfinite(float(self.create_time))
            or float(self.create_time) < 0
        ):
            raise ProcessIdentityError("create_time must be a finite non-negative number")
        object.__setattr__(self, "create_time", float(self.create_time))


@dataclass(frozen=True, slots=True)
class RootProcessRegistration:
    """An externally supplied Root Process binding for one AIA Session."""

    aia_session_id: str
    workspace: Path | str
    root_process_identity: ProcessIdentity
    registered_at: datetime
    registration_source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aia_session_id",
            _safe_text(self.aia_session_id, field_name="aia_session_id"),
        )
        if not isinstance(self.root_process_identity, ProcessIdentity):
            raise ProcessIdentityError(
                "root_process_identity must be a ProcessIdentity"
            )
        object.__setattr__(self, "workspace", canonicalize_workspace(self.workspace))
        object.__setattr__(
            self,
            "registered_at",
            _aware_utc(self.registered_at, field_name="registered_at"),
        )
        object.__setattr__(
            self,
            "registration_source",
            _safe_text(
                self.registration_source,
                field_name="registration_source",
            ),
        )


ProcessFactory = Callable[[int], Any]


def inspect_process_identity(
    identity: ProcessIdentity,
    *,
    process_factory: ProcessFactory = psutil.Process,
) -> tuple[ProcessIdentityStatus, Any | None]:
    """Return identity status and a live process handle when safely available."""

    if not isinstance(identity, ProcessIdentity):
        raise ProcessIdentityError("identity must be a ProcessIdentity")
    try:
        process = process_factory(identity.pid)
        current_create_time = float(process.create_time())
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
        return ProcessIdentityStatus.PROCESS_GONE, None
    except (psutil.AccessDenied, PermissionError, OSError, ValueError, TypeError):
        return ProcessIdentityStatus.OWNER_UNVERIFIABLE, None
    except Exception:
        return ProcessIdentityStatus.OWNER_UNVERIFIABLE, None
    if not math.isfinite(current_create_time):
        return ProcessIdentityStatus.OWNER_UNVERIFIABLE, None
    if current_create_time != identity.create_time:
        return ProcessIdentityStatus.PID_REUSED, process
    return ProcessIdentityStatus.LIVE_MATCH, process


def verify_process_identity(
    identity: ProcessIdentity,
    *,
    process_factory: ProcessFactory = psutil.Process,
) -> ProcessIdentityStatus:
    """Verify PID and create time without treating PID alone as identity."""

    return inspect_process_identity(
        identity,
        process_factory=process_factory,
    )[0]


__all__ = [
    "ProcessFactory",
    "ProcessIdentity",
    "ProcessIdentityError",
    "ProcessIdentityStatus",
    "RootProcessRegistration",
    "inspect_process_identity",
    "verify_process_identity",
]
