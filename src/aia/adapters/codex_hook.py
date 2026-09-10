"""Codex 0.149.1 PreToolUse wire adapter.

This module only translates the native hook envelope.  It does not infer
policy, attribution, or trust from a native ``session_id``.  A caller must
provide the AIA bridge envelope and run it through ``HookEnforcementBridge``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..pretool_enforcement import CodexPreToolResponse, HookEnforcementBridge, TrustedHookIngress
from ..session import ProtectedRunSession


class CodexHookPayloadError(ValueError):
    """Raised for a malformed native Codex PreToolUse payload."""


@dataclass(frozen=True, slots=True)
class CodexPreToolPayload:
    """Native fields observed in the Codex 0.149.1 command hook schema."""

    session_id: str
    turn_id: str
    tool_use_id: str
    cwd: str
    tool_name: str
    tool_input: Any
    hook_event_name: str = "PreToolUse"
    model: str | None = None
    permission_mode: str | None = None
    transcript_path: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_event: str = "PreToolUse",
    ) -> "CodexPreToolPayload":
        if not isinstance(value, Mapping):
            raise CodexHookPayloadError("PreToolUse payload must be an object")
        allowed = {
            "agent_id",
            "agent_type",
            "cwd",
            "hook_event_name",
            "model",
            "permission_mode",
            "session_id",
            "tool_input",
            "tool_name",
            "tool_use_id",
            "transcript_path",
            "turn_id",
            # AIA bridge fields are added outside the native Codex payload.
            "aia_session_id",
            "aia_launch_id",
            "aia_capability",
        }
        if expected_event == "PostToolUse":
            allowed.add("tool_response")
        if set(value) - allowed:
            raise CodexHookPayloadError("unsupported PreToolUse fields")
        required = (
            "session_id",
            "turn_id",
            "tool_use_id",
            "cwd",
            "tool_name",
            "tool_input",
            "hook_event_name",
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise CodexHookPayloadError("missing native PreToolUse fields")
        if value["hook_event_name"] != expected_event:
            raise CodexHookPayloadError("unsupported hook event")
        text_fields = ("session_id", "turn_id", "tool_use_id", "cwd", "tool_name")
        if any(not isinstance(value[key], str) or not value[key].strip() for key in text_fields):
            raise CodexHookPayloadError("native PreToolUse text field is invalid")
        return cls(
            session_id=value["session_id"],
            turn_id=value["turn_id"],
            tool_use_id=value["tool_use_id"],
            cwd=value["cwd"],
            tool_name=value["tool_name"],
            tool_input=value["tool_input"],
            hook_event_name=value["hook_event_name"],
            model=value.get("model"),
            permission_mode=value.get("permission_mode"),
            transcript_path=value.get("transcript_path"),
        )

    def to_mapping(self) -> dict[str, Any]:
        result = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "tool_use_id": self.tool_use_id,
            "cwd": self.cwd,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "hook_event_name": self.hook_event_name,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "transcript_path": self.transcript_path,
        }
        return result


class CodexHookAdapter:
    """Translate native Codex events to the AIA bridge and wire response."""

    @staticmethod
    def verify_ingress(
        payload: Mapping[str, Any],
        *,
        bridge: HookEnforcementBridge,
        session: ProtectedRunSession,
        launch_context: Any | None = None,
        expected_event: str = "PreToolUse",
    ) -> TrustedHookIngress:
        native = CodexPreToolPayload.from_mapping(
            payload,
            expected_event=expected_event,
        )
        return bridge.verify(
            {
                **native.to_mapping(),
                **dict(payload),
            },
            session=session,
            launch_context=launch_context,
            expected_hook_event=expected_event,
        )

    @staticmethod
    def response_mapping(response: CodexPreToolResponse) -> dict[str, Any]:
        return response.to_mapping()

    @staticmethod
    def is_actual_pretool_deny(response: Mapping[str, Any]) -> bool:
        specific = response.get("hookSpecificOutput")
        return (
            isinstance(specific, Mapping)
            and specific.get("hookEventName") == "PreToolUse"
            and specific.get("permissionDecision") == "deny"
        )


__all__ = [
    "CodexHookAdapter",
    "CodexHookPayloadError",
    "CodexPreToolPayload",
]
