from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from aia import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    HookEnforcementBridge,
    HookTrustStatus,
    PolicyDecision,
    PreToolEnforcementAdapter,
    PreToolExecutionConfirmation,
    SessionMode,
    evaluate_pretool,
)
from aia.adapters import CodexHookAdapter, CodexHookPayloadError, CodexPreToolPayload

from tests.test_enforcement import _gate_input


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _bridge_payload(bridge: HookEnforcementBridge, value, *, native="native-1"):
    capability = bridge._capability  # test-only construction of the bridge envelope
    assert capability is not None
    return {
        "hook_event_name": "PreToolUse",
        "session_id": native,
        "turn_id": "turn-1",
        "tool_use_id": "tool-1",
        "cwd": str(value.action.canonical_path).split("protected.txt")[0].rstrip("\\/"),
        "tool_name": "Bash",
        "tool_input": {"command": "Remove-Item protected.txt"},
        "aia_session_id": value.session.session_id,
        "aia_launch_id": "launch-1",
        "aia_capability": capability._secret,
    }


def test_trusted_bridge_verifies_session_launch_capability_and_native_id(tmp_path: Path):
    value, _ = _gate_input(tmp_path)
    bridge = HookEnforcementBridge()
    bridge.prepare(
        aia_session_id=value.session.session_id,
        launch_id="launch-1",
        workspace=value.session.workspace,
        control_directory=tmp_path / "control-root",
        at=NOW,
    )

    trusted = bridge.verify(_bridge_payload(bridge, value), session=value.session, launch_context=value.launch_context)
    assert trusted.status is HookTrustStatus.VERIFIED
    assert trusted.ingress_verified
    assert trusted.agent_native_session_id == "native-1"
    assert "secret" not in repr(trusted).casefold()


def test_arbitrary_payload_is_not_trusted(tmp_path: Path):
    value, _ = _gate_input(tmp_path)
    bridge = HookEnforcementBridge()
    bridge.prepare(
        aia_session_id=value.session.session_id,
        launch_id="launch-1",
        workspace=value.session.workspace,
        control_directory=tmp_path / "control-root",
    )

    result = bridge.verify(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "native-1",
            "turn_id": "turn-1",
            "tool_use_id": "tool-1",
            "cwd": str(value.session.workspace),
            "tool_name": "Bash",
            "tool_input": {},
        },
        session=value.session,
        launch_context=value.launch_context,
    )
    assert result.status is HookTrustStatus.UNVERIFIED


def test_native_session_mismatch_cannot_overwrite_first_binding(tmp_path: Path):
    value, _ = _gate_input(tmp_path)
    bridge = HookEnforcementBridge()
    bridge.prepare(
        aia_session_id=value.session.session_id,
        launch_id="launch-1",
        workspace=value.session.workspace,
        control_directory=tmp_path / "control-root",
    )
    first = bridge.verify(_bridge_payload(bridge, value), session=value.session, launch_context=value.launch_context)
    second = bridge.verify(
        _bridge_payload(bridge, value, native="other-native"),
        session=value.session,
        launch_context=value.launch_context,
    )
    assert first.status is HookTrustStatus.VERIFIED
    assert second.status is HookTrustStatus.MISMATCHED
    assert second.reason == "HOOK_NATIVE_SESSION_MISMATCH"
    assert bridge.native_session_id == "native-1"


def test_capability_mismatch_is_unverified_without_secret_in_reason(tmp_path: Path):
    value, _ = _gate_input(tmp_path)
    bridge = HookEnforcementBridge()
    bridge.prepare(
        aia_session_id=value.session.session_id,
        launch_id="launch-1",
        workspace=value.session.workspace,
        control_directory=tmp_path / "control-root",
    )
    payload = _bridge_payload(bridge, value)
    payload["aia_capability"] = "wrong-secret"
    result = bridge.verify(payload, session=value.session, launch_context=value.launch_context)
    assert result.status is HookTrustStatus.UNVERIFIED
    assert result.reason == "CAPABILITY_MISMATCH"
    assert "wrong-secret" not in result.reason


def test_containment_emits_codex_deny_but_not_blocked_claim(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    decision = evaluate_pretool(
        value,
        gate=EnforcementGate(lease_manager=manager),
        pretool_received_at=NOW,
        gate_decided_at=NOW,
    )
    assert decision.gate_result.decision is EnforcementDecision.CONTAIN
    assert decision.gate_result.action is EnforcementAction.NONE
    assert decision.response.to_mapping()["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decision.response.deny_emitted_at == NOW
    assert decision.pretool_gate_latency_ms == 0

    confirmed = decision.confirm(PreToolExecutionConfirmation(True, NOW))
    assert confirmed.action is EnforcementAction.BLOCKED
    assert confirmed.execution_result is EnforcementExecutionResult.SUCCEEDED


def test_deny_ignored_is_failed_without_blocked_claim(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    decision = PreToolEnforcementAdapter(EnforcementGate(lease_manager=manager)).evaluate(value)
    result = decision.confirm(PreToolExecutionConfirmation(False, NOW))
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.FAILED


def test_confirmation_unavailable_is_not_blocked(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    decision = PreToolEnforcementAdapter(EnforcementGate(lease_manager=manager)).evaluate(value)
    result = decision.confirm(PreToolExecutionConfirmation(None, NOW))
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.FAILED
    assert result.reason == "BLOCK_CONFIRMATION_UNAVAILABLE"


def test_continue_and_refuse_use_neutral_response(tmp_path: Path):
    value, manager = _gate_input(tmp_path)
    adapter = PreToolEnforcementAdapter(EnforcementGate(lease_manager=manager))
    compliant = adapter.evaluate(replace(
        value,
        policy_evaluation=replace(
            value.policy_evaluation,
            policy_decision=PolicyDecision.COMPLIANT,
        ),
    ))
    assert compliant.gate_result.decision is EnforcementDecision.CONTINUE
    assert compliant.response.to_mapping() == {}
    assert "allow" not in repr(compliant.response.to_mapping()).casefold()


def test_codex_native_pretool_schema_and_deny_wire_are_explicit():
    payload = {
        "session_id": "native",
        "turn_id": "turn",
        "tool_use_id": "tool",
        "cwd": "C:/workspace",
        "tool_name": "Bash",
        "tool_input": {"command": "echo safe"},
        "hook_event_name": "PreToolUse",
        "model": "gpt-5.5",
        "permission_mode": "default",
        "transcript_path": None,
    }
    parsed = CodexPreToolPayload.from_mapping(payload)
    assert parsed.tool_use_id == "tool"
    with pytest.raises(CodexHookPayloadError):
        CodexPreToolPayload.from_mapping(payload | {"unknown": True})
    assert CodexHookAdapter.is_actual_pretool_deny(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }
    )
