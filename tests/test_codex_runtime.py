from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
import sys

import pytest
import aia.codex_runtime as codex_runtime
import aia.codex_hook_runtime as codex_hook_runtime

from aia import (
    ActionTargetKind,
    CodexHookBroker,
    CodexPreToolController,
    EnforcementRoute,
    EvidenceRecordType,
    EvidenceSource,
    NormalizationCompleteness,
    NormalizedAction,
    ObservationStage,
    Operation,
    RawEvidenceRecord,
    send_hook_payload,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _BinaryStdin(BytesIO):
    @property
    def buffer(self):
        return self


def _native_hook_payload(event: str = "PreToolUse") -> dict[str, object]:
    return {
        "session_id": "native-1",
        "turn_id": "turn-1",
        "tool_use_id": "tool-1",
        "cwd": "C:/workspace/demo",
        "tool_name": "Bash",
        "tool_input": {"command": "echo test"},
        "hook_event_name": event,
    }


def test_bound_pretool_broker_failure_uses_codex_blocking_exit(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("AIA_CODEX_HOOK_ENDPOINT", "http://127.0.0.1:1/pretool")
    monkeypatch.setenv("AIA_CODEX_HOOK_CAPABILITY", "capability")
    monkeypatch.setattr(
        codex_hook_runtime,
        "send_hook_payload",
        lambda payload: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        _BinaryStdin(json.dumps(_native_hook_payload()).encode("utf-8")),
    )

    assert codex_hook_runtime.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "AIA protection unavailable" in captured.err


def test_partially_bound_pretool_does_not_fall_through_to_empty_success(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("AIA_CODEX_HOOK_ENDPOINT", "http://127.0.0.1:1/pretool")
    monkeypatch.delenv("AIA_CODEX_HOOK_CAPABILITY", raising=False)
    monkeypatch.setattr(
        sys,
        "stdin",
        _BinaryStdin(json.dumps(_native_hook_payload()).encode("utf-8")),
    )

    assert codex_hook_runtime.main() == 2
    assert "capability is missing" in capsys.readouterr().err


def test_unbound_hook_failure_remains_neutral(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("AIA_CODEX_HOOK_ENDPOINT", raising=False)
    monkeypatch.delenv("AIA_CODEX_HOOK_CAPABILITY", raising=False)
    monkeypatch.setattr(
        codex_hook_runtime,
        "send_hook_payload",
        lambda payload: (_ for _ in ()).throw(RuntimeError("not bound")),
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        _BinaryStdin(json.dumps(_native_hook_payload()).encode("utf-8")),
    )

    assert codex_hook_runtime.main() == 0
    assert capsys.readouterr().out == ""


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


def test_post_action_derivation_is_separate_from_pretool_action() -> None:
    action = NormalizedAction(
        action_id="pre-action-1",
        aia_session_id="session-1",
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind=ActionTargetKind.COMMAND,
        observed_at=NOW,
        evidence_ids=("pretool-1", "command-1"),
        evidence_sources=(EvidenceSource.AGENT_HOOK,),
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="test",
        raw_command="python canary.py",
        normalized_command="python canary.py",
        tool_use_id="tool-1",
    )
    posttool = RawEvidenceRecord(
        session_id="session-1",
        source=EvidenceSource.AGENT_HOOK,
        record_type=EvidenceRecordType.POSTTOOL_OBSERVED,
        captured_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        observation_stage=ObservationStage.POST_ACTION,
        payload={"tool_use_id": "tool-1", "tool_response_sha256": "a" * 64},
        evidence_id="posttool-1",
    )

    derived = CodexPreToolController._derive_post_action(action, posttool)

    assert action.stage is ObservationStage.PRE_ACTION
    assert derived.stage is ObservationStage.POST_ACTION
    assert derived.action_id != action.action_id
    assert derived.evidence_ids == ("pretool-1", "command-1", "posttool-1")
    assert derived.observed_at == posttool.captured_at


def test_post_action_derivation_rejects_cross_session_evidence() -> None:
    action = NormalizedAction(
        action_id="pre-action-1",
        aia_session_id="session-1",
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind=ActionTargetKind.COMMAND,
        observed_at=NOW,
        evidence_ids=("pretool-1",),
        evidence_sources=(EvidenceSource.AGENT_HOOK,),
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="test",
        raw_command="python canary.py",
    )
    posttool = RawEvidenceRecord(
        session_id="session-2",
        source=EvidenceSource.AGENT_HOOK,
        record_type=EvidenceRecordType.POSTTOOL_OBSERVED,
        captured_at=NOW,
        observation_stage=ObservationStage.POST_ACTION,
        payload={},
        evidence_id="posttool-1",
    )

    with pytest.raises(ValueError, match="Session"):
        CodexPreToolController._derive_post_action(action, posttool)


def test_bypassed_pretool_uses_separate_post_action_containment_callback(
    monkeypatch,
) -> None:
    action = NormalizedAction(
        action_id="pre-action-1",
        aia_session_id="session-1",
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind=ActionTargetKind.COMMAND,
        observed_at=NOW,
        evidence_ids=("pretool-1", "command-1"),
        evidence_sources=(EvidenceSource.AGENT_HOOK,),
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="test",
        raw_command="python canary.py",
        tool_use_id="tool-1",
    )
    posttool = RawEvidenceRecord(
        session_id="session-1",
        source=EvidenceSource.AGENT_HOOK,
        record_type=EvidenceRecordType.POSTTOOL_OBSERVED,
        captured_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        observation_stage=ObservationStage.POST_ACTION,
        payload={"tool_use_id": "tool-1"},
        evidence_id="posttool-1",
    )
    callback_inputs: list[object] = []
    controller = object.__new__(CodexPreToolController)
    controller.session = SimpleNamespace(session_id="session-1")
    controller.preparation_context = SimpleNamespace(
        active_policy=object(),
        workspace_lease=object(),
    )
    controller.filesystem_sensor = None
    controller.hook_sensor = None
    controller.process_sensor_provider = lambda: None
    controller.launch_context_provider = lambda: None
    controller.lease_manager = object()
    controller.post_action_containment_callback = callback_inputs.append
    controller._lock = RLock()
    controller._post_action_containments = []
    controller._errors = []

    class FakeAttributionEngine:
        def __init__(self, *args, **kwargs):
            pass

        def attribute(self, value):
            return SimpleNamespace(action_id=value.action_id, grade="EXACT")

    class FakePolicyEvaluator:
        def __init__(self, *args, **kwargs):
            pass

        def evaluate(self, value):
            return SimpleNamespace(action_id=value.action_id, policy_decision="VIOLATION")

    class FakeGate:
        def __init__(self, *args, **kwargs):
            pass

        def evaluate(self, value):
            return SimpleNamespace(
                decision=codex_runtime.EnforcementDecision.CONTAIN,
                route=codex_runtime.EnforcementRoute.PROCESS_TERMINATION,
            )

    monkeypatch.setattr(codex_runtime, "AttributionEngine", FakeAttributionEngine)
    monkeypatch.setattr(codex_runtime, "RuntimePolicyEvaluator", FakePolicyEvaluator)
    monkeypatch.setattr(codex_runtime, "EnforcementGate", FakeGate)
    monkeypatch.setattr(codex_runtime, "EnforcementGateInput", lambda **value: value)

    event = SimpleNamespace(action=action, records=())
    controller._handle_bypassed_pretool(event, posttool)

    assert len(callback_inputs) == 1
    containment = controller.post_action_containments[0]
    assert containment.action.stage is ObservationStage.POST_ACTION
    assert containment.gate_result.route is EnforcementRoute.PROCESS_TERMINATION
    assert containment.termination_result is None
    assert controller.errors == ()
