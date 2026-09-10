"""Presentation request and view DTOs.

These types carry data between the local web layer and the existing AIA Core.
They do not make security decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aia import PolicyProfile


class DTOValidationError(ValueError):
    """Raised when a console request cannot be represented safely."""


_ALLOWED_CREATE_KEYS = frozenset(
    {
        "workspace",
        "agent",
        "model",
        "policy_profile",
        "custom_policy_path",
        "mode",
        "interactive",
        "task",
    }
)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DTOValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class CreateRunRequest:
    workspace: str
    agent: str = "codex"
    model: str | None = None
    policy_profile: str = PolicyProfile.PROTECTED_DEVELOPMENT.value
    custom_policy_path: str | None = None
    mode: str = "ENFORCE"
    task: str = ""
    interactive: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CreateRunRequest":
        if not isinstance(value, Mapping):
            raise DTOValidationError("request body must be a JSON object")
        unknown = set(value) - _ALLOWED_CREATE_KEYS
        if unknown:
            raise DTOValidationError(
                "unknown request fields: " + ", ".join(sorted(map(str, unknown)))
            )
        workspace = _required_text(value.get("workspace"), "workspace")
        agent = _required_text(value.get("agent", "codex"), "agent")
        model = value.get("model")
        if model is not None:
            model = _required_text(model, "model")
        policy_profile = _required_text(
            value.get("policy_profile", PolicyProfile.PROTECTED_DEVELOPMENT.value),
            "policy_profile",
        )
        custom_policy_path = value.get("custom_policy_path")
        if custom_policy_path is not None:
            custom_policy_path = _required_text(custom_policy_path, "custom_policy_path")
        mode = _required_text(value.get("mode", "ENFORCE"), "mode").upper()
        task = value.get("task", "")
        if not isinstance(task, str):
            raise DTOValidationError("task must be a string")
        if len(task) > 50_000:
            raise DTOValidationError("task is too large")
        interactive = value.get("interactive", False)
        if not isinstance(interactive, bool):
            raise DTOValidationError("interactive must be a boolean")
        return cls(
            workspace=workspace,
            agent=agent,
            model=model,
            policy_profile=policy_profile,
            custom_policy_path=custom_policy_path,
            mode=mode,
            task=task,
            interactive=interactive,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "custom_policy_path": self.custom_policy_path,
            "mode": self.mode,
            "model": self.model,
            "policy_profile": self.policy_profile,
            "task": self.task,
            "interactive": self.interactive,
            "workspace": self.workspace,
        }
