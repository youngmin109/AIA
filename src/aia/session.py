"""Domain model for one AIA protected run session."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class SessionValidationError(ValueError):
    """Raised when protected session configuration is invalid."""


class WorkspaceValidationError(SessionValidationError):
    """Raised when a workspace cannot be used by a protected session."""


class InvalidSessionTransition(SessionValidationError):
    """Raised when a session status transition is not allowed."""


class SessionMode(StrEnum):
    AUDIT = "AUDIT"
    ENFORCE = "ENFORCE"


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


_TERMINAL_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.ABORTED,
        SessionStatus.FAILED,
    }
)

_ALLOWED_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.CREATED: frozenset(
        {SessionStatus.PREPARING, SessionStatus.ABORTED}
    ),
    SessionStatus.PREPARING: frozenset(
        {SessionStatus.READY, SessionStatus.ABORTED, SessionStatus.FAILED}
    ),
    SessionStatus.READY: frozenset(
        {SessionStatus.RUNNING, SessionStatus.ABORTED, SessionStatus.FAILED}
    ),
    SessionStatus.RUNNING: frozenset(
        {SessionStatus.COMPLETED, SessionStatus.ABORTED, SessionStatus.FAILED}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.ABORTED: frozenset(),
    SessionStatus.FAILED: frozenset(),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _timezone_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionValidationError(
            f"{field_name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SessionValidationError(f"{field_name} must not be empty")
    return value


def canonicalize_workspace(workspace: Path | str) -> Path:
    """Resolve an existing directory to its canonical absolute path."""

    try:
        candidate = Path(workspace).expanduser()
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise WorkspaceValidationError(
            f"workspace must be an existing directory: {workspace!r}"
        ) from error
    if not resolved.is_dir():
        raise WorkspaceValidationError(
            f"workspace must be a directory: {resolved}"
        )
    return resolved


@dataclass(slots=True)
class ProtectedRunSession:
    """AIA's security responsibility unit for one protected workspace run."""

    workspace: Path | str
    agent: str
    mode: SessionMode | str
    policy_id: str
    policy_version: str
    session_id: str = field(
        default_factory=lambda: str(uuid4()),
        init=False,
    )
    agent_native_session_id: str | None = None
    created_at: datetime = field(default_factory=_now_utc)
    started_at: datetime | None = field(default=None, init=False)
    ended_at: datetime | None = field(default=None, init=False)
    status: SessionStatus = field(
        default=SessionStatus.CREATED,
        init=False,
    )

    def __post_init__(self) -> None:
        self.workspace = canonicalize_workspace(self.workspace)
        self.agent = _required_text(self.agent, field_name="agent")
        self.policy_id = _required_text(self.policy_id, field_name="policy_id")
        self.policy_version = _required_text(
            self.policy_version,
            field_name="policy_version",
        )
        self.mode = SessionMode(self.mode)
        if self.agent_native_session_id == "":
            raise SessionValidationError(
                "agent_native_session_id must be non-empty when provided"
            )
        self.created_at = _timezone_aware(
            self.created_at,
            field_name="created_at",
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def can_transition_to(self, new_status: SessionStatus | str) -> bool:
        """Return whether the requested status is an allowed next state."""

        try:
            target = SessionStatus(new_status)
        except ValueError:
            return False
        return target in _ALLOWED_TRANSITIONS[self.status]

    def transition(
        self,
        new_status: SessionStatus | str,
        *,
        at: datetime | None = None,
    ) -> SessionStatus:
        """Apply one validated state transition and its lifecycle timestamp."""

        try:
            target = SessionStatus(new_status)
        except ValueError as error:
            raise InvalidSessionTransition(
                f"unknown session status: {new_status!r}"
            ) from error

        allowed = _ALLOWED_TRANSITIONS[self.status]
        if target not in allowed:
            raise InvalidSessionTransition(
                f"invalid session transition: {self.status} -> {target}"
            )

        transition_time = _timezone_aware(
            at if at is not None else _now_utc(),
            field_name="transition time",
        )
        if target is SessionStatus.PREPARING:
            self.started_at = transition_time
        if target in _TERMINAL_STATUSES:
            self.ended_at = transition_time
        self.status = target
        return self.status

    def transition_to(
        self,
        new_status: SessionStatus | str,
        *,
        at: datetime | None = None,
    ) -> SessionStatus:
        """Explicitly named alias for callers that prefer transition_to."""

        return self.transition(new_status, at=at)


Session = ProtectedRunSession


__all__ = [
    "InvalidSessionTransition",
    "ProtectedRunSession",
    "Session",
    "SessionMode",
    "SessionStatus",
    "SessionValidationError",
    "WorkspaceValidationError",
    "canonicalize_workspace",
]
