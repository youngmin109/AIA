from __future__ import annotations

import json
from pathlib import Path

from aia import CodexHookBroker, send_hook_payload


def test_codex_hook_broker_round_trip_is_capability_authenticated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    received: list[dict] = []

    def handler(payload):
        received.append(dict(payload))
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "test-deny",
            }
        }

    broker = CodexHookBroker(
        capability_secret="test-capability",
        session_id="session-1",
        launch_id="launch-1",
        control_root=tmp_path / "control",
        handler=handler,
    )
    broker.start()
    try:
        environment = broker.environment
        monkeypatch.setenv("AIA_CODEX_HOOK_ENDPOINT", environment["AIA_CODEX_HOOK_ENDPOINT"])
        monkeypatch.setenv("AIA_CODEX_HOOK_CAPABILITY", environment["AIA_CODEX_HOOK_CAPABILITY"])
        payload = {
            "session_id": "native-1",
            "turn_id": "turn-1",
            "tool_use_id": "tool-1",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "hook_event_name": "PreToolUse",
        }

        result = send_hook_payload(payload)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert received == [payload]
    finally:
        broker.stop()


def test_codex_hook_broker_does_not_expose_capability_in_wire_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    broker = CodexHookBroker(
        capability_secret="secret-value",
        session_id="session-1",
        launch_id="launch-1",
        control_root=tmp_path / "control",
        handler=lambda payload: {},
    )
    broker.start()
    try:
        environment = broker.environment
        monkeypatch.setenv("AIA_CODEX_HOOK_ENDPOINT", environment["AIA_CODEX_HOOK_ENDPOINT"])
        monkeypatch.setenv("AIA_CODEX_HOOK_CAPABILITY", environment["AIA_CODEX_HOOK_CAPABILITY"])
        result = send_hook_payload(
            {
                "session_id": "native-1",
                "turn_id": "turn-1",
                "tool_use_id": "tool-1",
                "cwd": str(tmp_path),
                "tool_name": "Bash",
                "tool_input": {},
                "hook_event_name": "PreToolUse",
            }
        )
        assert result == {}
        assert "secret-value" not in json.dumps(result, ensure_ascii=False)
    finally:
        broker.stop()
