from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import statistics
import time

import pytest

from aia import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    HookEnforcementBridge,
    HookTrustStatus,
    PolicyDecision,
    PolicyEngine,
    PreToolEnforcementAdapter,
    PreToolExecutionConfirmation,
    protected_pretool_deny,
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


def test_trusted_bridge_accepts_posttool_event_with_same_session_binding(tmp_path: Path):
    value, _ = _gate_input(tmp_path)
    bridge = HookEnforcementBridge()
    bridge.prepare(
        aia_session_id=value.session.session_id,
        launch_id="launch-1",
        workspace=value.session.workspace,
        control_directory=tmp_path / "control-root",
    )
    payload = _bridge_payload(bridge, value)
    payload.update(
        {
            "hook_event_name": "PostToolUse",
            "tool_response": {"exit_code": 0, "stdout": "secret"},
        }
    )
    trusted = CodexHookAdapter.verify_ingress(
        payload,
        bridge=bridge,
        session=value.session,
        launch_context=value.launch_context,
        expected_event="PostToolUse",
    )
    assert trusted.status is HookTrustStatus.VERIFIED


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


def test_pretool_policy_decision_latency_has_generous_ceiling(
    tmp_path: Path, request
) -> None:
    gate_input, manager = _gate_input(tmp_path)
    policy_engine = PolicyEngine(gate_input.active_policy.policy)
    adapter = PreToolEnforcementAdapter(EnforcementGate(lease_manager=manager))

    def evaluate_decision():
        policy = policy_engine.evaluate(
            asset_type="CRITICAL_CODE",
            operation=gate_input.action.operation,
            path=gate_input.action.canonical_path,
        )
        runtime_policy = replace(
            gate_input.policy_evaluation,
            policy_decision=policy.policy_decision,
            operation_effect=policy.operation_effect,
            matched_rule_ids=policy.matched_rule_ids,
            audit_record=policy.audit_record,
        )
        return adapter.evaluate(replace(gate_input, policy_evaluation=runtime_policy))

    # One warmup avoids measuring first-call initialization in the sample.
    assert evaluate_decision().gate_result.decision is EnforcementDecision.CONTINUE
    durations_ms = []
    for _ in range(100):
        started = time.perf_counter_ns()
        decision = evaluate_decision()
        durations_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        assert decision.gate_result.decision is EnforcementDecision.CONTINUE

    p50_ms = statistics.median(durations_ms)
    ordered = sorted(durations_ms)
    p95_ms = ordered[(95 * len(ordered) + 99) // 100 - 1]
    request.node.user_properties.extend(
        (
            ("pretool_policy_p50_ms", f"{p50_ms:.6f}"),
            ("pretool_policy_p95_ms", f"{p95_ms:.6f}"),
        )
    )
    assert p95_ms < 20, f"PreTool policy decision p50={p50_ms:.3f} ms, p95={p95_ms:.3f} ms"


def test_bound_hook_failures_return_a_conservative_deny_without_payload_values():
    response = protected_pretool_deny("UNTRUSTED_PRETOOL_INGRESS")

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "UNTRUSTED_PRETOOL_INGRESS" in response["reason"]
    assert "secret" not in repr(response).casefold()


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
    posttool = CodexPreToolPayload.from_mapping(
        payload
        | {
            "hook_event_name": "PostToolUse",
            "tool_response": {"exit_code": 0},
        },
        expected_event="PostToolUse",
    )
    assert posttool.hook_event_name == "PostToolUse"
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
