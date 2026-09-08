"""AIA product MVP package."""

from .session import (
    InvalidSessionTransition,
    ProtectedRunSession,
    Session,
    SessionMode,
    SessionStatus,
    SessionValidationError,
    WorkspaceValidationError,
    canonicalize_workspace,
)

__all__ = [
    "InvalidSessionTransition",
    "ProtectedRunSession",
    "Session",
    "SessionMode",
    "SessionStatus",
    "SessionValidationError",
    "WorkspaceValidationError",
    "__version__",
    "canonicalize_workspace",
]
__version__ = "0.1.0"
