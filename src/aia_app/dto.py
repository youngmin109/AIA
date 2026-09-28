"""Presentation request and view DTOs.

These types carry data between the local web layer and the existing AIA Core.
They do not make security decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aia import Operation, PolicyProfile


class DTOValidationError(ValueError):
    """Raised when a console request cannot be represented safely."""


_ALLOWED_CREATE_KEYS = frozenset(
    {
        "workspace",
        "agent",
        "model",
        "policy_profile",
        "custom_policy_path",
        "protected_paths",
        "mode",
        "interactive",
        "task",
        "launch_mode",
    }
)

_ALLOWED_PREVIEW_KEYS = frozenset(
    {
        "policy_profile",
        "custom_policy_path",
        "operation",
        "path",
        "command",
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
    protected_paths: tuple[str, ...] = ()
    mode: str = "ENFORCE"
    task: str = ""
    interactive: bool = False
    launch_mode: str = "inherit"

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
        raw_protected_paths = value.get("protected_paths", ())
        if not isinstance(raw_protected_paths, (list, tuple)):
            raise DTOValidationError("protected_paths must be a list")
        if len(raw_protected_paths) > 100:
            raise DTOValidationError("protected_paths may contain at most 100 paths")
        protected_paths: list[str] = []
        for item in raw_protected_paths:
            protected_paths.append(_required_text(item, "protected_paths item"))
        mode = _required_text(value.get("mode", "ENFORCE"), "mode").upper()
        task = value.get("task", "")
        if not isinstance(task, str):
            raise DTOValidationError("task must be a string")
        if len(task) > 50_000:
            raise DTOValidationError("task is too large")
        interactive = value.get("interactive", False)
        if not isinstance(interactive, bool):
            raise DTOValidationError("interactive must be a boolean")
        launch_mode = _required_text(value.get("launch_mode", "inherit"), "launch_mode").lower()
        if launch_mode not in {"inherit", "new_terminal", "web_terminal", "codex_app_server"}:
            raise DTOValidationError(
                "launch_mode must be inherit, new_terminal, web_terminal, or codex_app_server"
            )
        if launch_mode in {"new_terminal", "web_terminal", "codex_app_server"} and not interactive:
            raise DTOValidationError(
                f"{launch_mode} launch mode requires interactive mode"
            )
        return cls(
            workspace=workspace,
            agent=agent,
            model=model,
            policy_profile=policy_profile,
            custom_policy_path=custom_policy_path,
            protected_paths=tuple(protected_paths),
            mode=mode,
            task=task,
            interactive=interactive,
            launch_mode=launch_mode,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "custom_policy_path": self.custom_policy_path,
            "protected_paths": list(self.protected_paths),
            "mode": self.mode,
            "model": self.model,
            "policy_profile": self.policy_profile,
            "task": self.task,
            "interactive": self.interactive,
            "workspace": self.workspace,
            "launch_mode": self.launch_mode,
        }


@dataclass(frozen=True, slots=True)
class PolicyPreviewRequest:
    """A non-executing request to inspect one resolved policy decision."""

    operation: str
    path: str | None = None
    command: str | None = None
    policy_profile: str = PolicyProfile.PROTECTED_DEVELOPMENT.value
    custom_policy_path: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PolicyPreviewRequest":
        if not isinstance(value, Mapping):
            raise DTOValidationError("request body must be a JSON object")
        unknown = set(value) - _ALLOWED_PREVIEW_KEYS
        if unknown:
            raise DTOValidationError(
                "unknown request fields: " + ", ".join(sorted(map(str, unknown)))
            )

        operation = _required_text(value.get("operation"), "operation").upper()
        try:
            normalized_operation = Operation(operation)
        except ValueError as error:
            raise DTOValidationError(f"unsupported operation: {operation!r}") from error

        profile = _required_text(
            value.get("policy_profile", PolicyProfile.PROTECTED_DEVELOPMENT.value),
            "policy_profile",
        )
        custom_policy_path = value.get("custom_policy_path")
        if custom_policy_path is not None:
            custom_policy_path = _required_text(custom_policy_path, "custom_policy_path")

        path = value.get("path")
        command = value.get("command")
        if path is not None:
            path = _required_text(path, "path")
        if command is not None:
            command = _required_text(command, "command")
            if len(command) > 50_000:
                raise DTOValidationError("command is too large")

        if normalized_operation is Operation.EXECUTE:
            if path is not None:
                raise DTOValidationError("EXECUTE preview accepts command, not path")
            if command is None:
                raise DTOValidationError("EXECUTE preview requires command")
        else:
            if command is not None:
                raise DTOValidationError("file operation preview accepts path, not command")
            if path is None:
                raise DTOValidationError("file operation preview requires path")

        return cls(
            operation=normalized_operation.value,
            path=path,
            command=command,
            policy_profile=profile,
            custom_policy_path=custom_policy_path,
        )
