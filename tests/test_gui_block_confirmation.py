from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event, RLock, Thread
import time
from urllib.request import Request, urlopen

import pytest

from aia import (
    CodexPreToolController,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    PolicyDecision,
    PolicyEffect,
    PreToolEnforcementAdapter,
    RawEvidenceRecord,
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
)
from aia.codex_runtime import CodexHookBroker, CodexPreToolEvent
from aia_app.codex_app_server import CodexAppServerSession, CodexHookEventCollector
from aia_app.gui_block_confirmation import confirm_gui_pretool_blocks, parse_hook_run_id
from tests.test_enforcement import _gate_input


NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
HOOKS_PATH = r"C:\Users\jinhy\.codex\hooks.json"
TURN_ID = "turn-17"
DENIED_ID = "exec-12ebf048-e7ad-454a-98d9-f63ff3d1a675"
ALLOWED_ID = "exec-1d63ce39-8af4-4120-b737-dafacd449234"


def _hook_run_id(tool_use_id: str, *, path: str = HOOKS_PATH, index: int = 0) -> str:
    return f"pre-tool-use:{index}:{path}:{tool_use_id}"


def _hook_event(
    collector: CodexHookEventCollector,
    phase: str,
    tool_use_id: str,
    *,
    path: str = HOOKS_PATH,
    index: int = 0,
    status: str | None = None,
    turn_id: str = TURN_ID,
    event_name: str = "preToolUse",
) -> None:
    method = "hook/started" if phase == "started" else "hook/completed"
    collector.observe_notification(
        method,
        {
            "turnId": turn_id,
            "run": {
                "id": _hook_run_id(tool_use_id, path=path, index=index),
                "eventName": event_name,
                "status": status or ("running" if phase == "started" else "blocked"),
            },
        },
    )


def _snapshot(
    specs: list[dict[str, object]] | None = None,
    *,
    turn_id: str = TURN_ID,
    turn_status: str = "completed",
    exit_code: int = 0,
    unexpected: bool = False,
    missing: bool = False,
) -> object:
    collector = CodexHookEventCollector()
    collector.observe_notification(
        "turn/started", {"turn": {"id": turn_id, "status": "inProgress"}}
    )
    for spec in specs or []:
        tool_use_id = str(spec.get("tool_use_id", DENIED_ID))
        path = str(spec.get("path", HOOKS_PATH))
        index = int(spec.get("index", 0))
        phase = str(spec.get("phase", "both"))
        event_name = str(spec.get("event_name", "preToolUse"))
        event_turn = str(spec.get("turn_id", turn_id))
        status = str(spec.get("status", "blocked"))
        if phase in {"both", "started"}:
            _hook_event(
                collector,
                "started",
                tool_use_id,
                path=path,
                index=index,
                turn_id=event_turn,
                event_name=event_name,
            )
        if phase in {"both", "completed"}:
            _hook_event(
                collector,
                "completed",
                tool_use_id,
                path=path,
                index=index,
                status=status,
                turn_id=event_turn,
                event_name=event_name,
            )
    collector.observe_notification(
        "turn/completed", {"turn": {"id": turn_id, "status": turn_status}}
    )
    if missing:
        collector.mark_missing()
    collector.mark_process_exit(exit_code, unexpected=unexpected)
    return collector.snapshot()


def _make_controller(tmp_path: Path, *, tool_ids: tuple[str, ...] = (DENIED_ID, ALLOWED_ID)):
    tmp_path.mkdir(parents=True, exist_ok=True)
    gate_input, manager = _gate_input(tmp_path)
    controller = object.__new__(CodexPreToolController)
    controller._lock = RLock()
    controller._events = []
    controller._errors = []
    records = []
    decisions = []
    for index, tool_use_id in enumerate(tool_ids):
        action_id = f"action-{index + 1}"
        evidence_id = f"evidence-{index + 1}"
        action = replace(
            gate_input.action,
            action_id=action_id,
            evidence_ids=(evidence_id,),
            tool_use_id=tool_use_id,
            turn_id=TURN_ID,
        )
        policy_evaluation = gate_input.policy_evaluation
        if index > 0:
            policy_evaluation = replace(
                policy_evaluation,
                action_id=action_id,
                policy_decision=PolicyDecision.COMPLIANT,
                operation_effect=PolicyEffect.ALLOW,
            )
        else:
            policy_evaluation = replace(policy_evaluation, action_id=action_id)
        attribution = replace(
            gate_input.attribution,
            action_id=action_id,
            tool_use_id=tool_use_id,
            turn_id=TURN_ID,
        )
        call_input = replace(
            gate_input,
            action=action,
            policy_evaluation=policy_evaluation,
            attribution=attribution,
        )
        decision = PreToolEnforcementAdapter(
            EnforcementGate(lease_manager=manager)
        ).evaluate(call_input)
        record = RawEvidenceRecord(
            session_id=gate_input.session.session_id,
            source=EvidenceSource.AGENT_HOOK,
            record_type=EvidenceRecordType.PRETOOL_REQUEST,
            captured_at=NOW,
            observation_stage=ObservationStage.PRE_ACTION,
            payload={"tool_use_id": tool_use_id, "turn_id": TURN_ID},
        )
        event = CodexPreToolEvent(
            tool_use_id=tool_use_id,
            records=(record,),
            action=action,
            policy_evaluation=policy_evaluation,
            attribution=attribution,
            gate_result=decision.gate_result,
            decision=decision,
        )
        controller._events.append(event)
        records.append(record)
        decisions.append(decision)
    return controller, tuple(records), tuple(decisions)


def _append_posttool(records: tuple[RawEvidenceRecord, ...], tool_use_id: str):
    gate_record = records[0]
    return (*records, RawEvidenceRecord(
        session_id=gate_record.session_id,
        source=EvidenceSource.AGENT_HOOK,
        record_type=EvidenceRecordType.POSTTOOL_OBSERVED,
        captured_at=NOW,
        observation_stage=ObservationStage.POST_ACTION,
        payload={"tool_use_id": tool_use_id, "turn_id": TURN_ID},
    ))


def _confirm(controller, records, snapshot, **overrides):
    values = {
        "hook_snapshot": snapshot,
        "evidence_records": records,
        "hooks_path": HOOKS_PATH,
        "broker_drained": True,
        "protected_file_change_count": 0,
        "file_sensor_healthy": True,
        "hook_sensor_healthy": True,
        "interrupted": False,
    }
    values.update(overrides)
    return confirm_gui_pretool_blocks(controller, **values)


def test_parse_hook_run_id_keeps_windows_drive_colon_and_call_suffix() -> None:
    parsed = parse_hook_run_id(_hook_run_id(DENIED_ID))
    assert parsed is not None
    assert parsed.event_type == "pre-tool-use"
    assert parsed.index == 0
    assert parsed.hooks_path == HOOKS_PATH
    assert parsed.call_id == DENIED_ID
    assert parse_hook_run_id("pre-tool-use:0:hooks.json:exec-unknown") is None


def test_gui_confirmation_blocks_only_the_matching_denied_call(tmp_path: Path) -> None:
    controller, records, decisions = _make_controller(tmp_path)
    snapshot = _snapshot([
        {"tool_use_id": DENIED_ID, "status": "blocked"},
        {"tool_use_id": ALLOWED_ID, "index": 2, "status": "completed"},
    ])

    assert decisions[0].gate_result.decision is EnforcementDecision.CONTAIN
    assert decisions[1].gate_result.decision is EnforcementDecision.CONTINUE
    assert _confirm(controller, records, snapshot) == (True,)
    assert controller.events[0].gate_result.action is EnforcementAction.BLOCKED
    assert controller.events[0].gate_result.execution_result is EnforcementExecutionResult.SUCCEEDED
    assert controller.events[1].gate_result.action is EnforcementAction.NONE
    assert controller.events[1].gate_result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED


def test_gui_confirmation_basis_contains_only_counts_and_statuses(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    _confirm(controller, records, _snapshot([{"tool_use_id": DENIED_ID}]))
    basis = controller.events[0].gate_result.confirmation_basis
    assert basis is not None
    serialized = json.dumps(dict(basis), sort_keys=True)
    assert DENIED_ID not in serialized
    assert HOOKS_PATH not in serialized
    assert "command" not in serialized.casefold()
    assert "path" not in serialized.casefold()
    assert "hook_run_id" not in serialized.casefold()
    assert basis["method"] == "app_server_call_identity_1_to_1"
    assert basis["codex_status"] == "blocked"
    assert basis["posttool_absent"] is True
    assert basis["protected_file_change_count"] == 0
    assert basis["turn_status"] == "completed"
    from aia.finalization import SessionFinalizer

    result_mapping = SessionFinalizer._enforcement_mapping(controller.events[0].gate_result)
    assert result_mapping["confirmation_basis"] == dict(basis)


@pytest.mark.parametrize(
    "specs",
    [
        [{"tool_use_id": ALLOWED_ID}],
        [{"tool_use_id": DENIED_ID, "path": r"C:\Other\hooks.json"}],
        [
            {"tool_use_id": DENIED_ID, "index": 0},
            {"tool_use_id": DENIED_ID, "index": 3},
        ],
        [{"tool_use_id": DENIED_ID, "phase": "completed"}],
        [{"tool_use_id": DENIED_ID, "event_name": "postToolUse"}],
        [{"tool_use_id": DENIED_ID, "tool_use_id_override": "unknown-hook-run-id"}],
    ],
    ids=["different-call-id", "other-hook-file", "duplicate-blocked-run", "missing-started", "wrong-event-name", "unknown-run-id"],
)
def test_gui_confirmation_rejects_non_matching_hook_evidence(
    tmp_path: Path, specs: list[dict[str, object]]
) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    normalized_specs = []
    for spec in specs:
        if spec.get("tool_use_id_override"):
            normalized_specs.append({"tool_use_id": str(spec["tool_use_id_override"])})
        else:
            normalized_specs.append(spec)
    assert _confirm(controller, records, _snapshot(normalized_specs)) == (None,)
    assert controller.events[0].gate_result.action is EnforcementAction.NONE
    assert controller.events[0].gate_result.failure_reasons[-1] == "BLOCK_CONFIRMATION_UNAVAILABLE"


def test_gui_confirmation_rejects_codex_completed_status_not_blocked(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    assert _confirm(
        controller,
        records,
        _snapshot([{"tool_use_id": DENIED_ID, "status": "completed"}]),
    ) == (None,)


def test_gui_confirmation_reports_posttool_as_ignored_deny(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    assert _confirm(
        controller,
        _append_posttool(records, DENIED_ID),
        _snapshot([{"tool_use_id": DENIED_ID}]),
    ) == (False,)
    assert "HOOK_ENFORCEMENT_FAILURE" in controller.events[0].gate_result.failure_reasons


@pytest.mark.parametrize(
    "overrides",
    [
        {"protected_file_change_count": 1},
        {"file_sensor_healthy": False},
        {"hook_sensor_healthy": False},
        {"broker_drained": False},
        {"evidence_records": None},
        {"interrupted": True},
    ],
    ids=["protected-file-changed", "file-sensor-unhealthy", "hook-sensor-unhealthy", "broker-barrier-incomplete", "evidence-read-failed", "user-interrupted"],
)
def test_gui_confirmation_fails_closed_when_run_evidence_is_incomplete(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    assert _confirm(
        controller,
        records,
        _snapshot([{"tool_use_id": DENIED_ID}]),
        **overrides,
    ) == (None,)
    assert controller.events[0].gate_result.action is EnforcementAction.NONE


def test_gui_confirmation_rejects_turn_mismatch_and_duplicate_tool_ids(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    mismatch = _snapshot(
        [{"tool_use_id": DENIED_ID, "turn_id": "turn-other"}],
        turn_id="turn-other",
    )
    assert _confirm(controller, records, mismatch) == (None,)

    duplicate_controller, duplicate_records, _ = _make_controller(
        tmp_path / "duplicate", tool_ids=(DENIED_ID, DENIED_ID)
    )
    duplicate_snapshot = _snapshot([{"tool_use_id": DENIED_ID}])
    assert _confirm(duplicate_controller, duplicate_records, duplicate_snapshot) == (None,)
    assert all(item.gate_result.action is EnforcementAction.NONE for item in duplicate_controller.events)


def test_gui_confirmation_fails_closed_for_missing_collector_interrupted_turn_or_dead_process(
    tmp_path: Path,
) -> None:
    controller, records, _ = _make_controller(tmp_path / "missing", tool_ids=(DENIED_ID,))
    assert _confirm(
        controller,
        records,
        _snapshot([{"tool_use_id": DENIED_ID}], missing=True),
    ) == (None,)

    interrupted_controller, interrupted_records, _ = _make_controller(
        tmp_path / "interrupted", tool_ids=(DENIED_ID,)
    )
    assert _confirm(
        interrupted_controller,
        interrupted_records,
        _snapshot([{"tool_use_id": DENIED_ID}], turn_status="interrupted"),
    ) == (None,)

    dead_controller, dead_records, _ = _make_controller(tmp_path / "dead", tool_ids=(DENIED_ID,))
    assert _confirm(
        dead_controller,
        dead_records,
        _snapshot([{"tool_use_id": DENIED_ID}], exit_code=3, unexpected=True),
    ) == (None,)


def test_hook_collector_keeps_actual_run_shape_separate_from_ui_buffer() -> None:
    collector = CodexHookEventCollector()
    session = CodexAppServerSession(
        ["codex", "app-server"],
        cwd=Path("C:/temporary/workspace"),
        env={},
        hook_event_collector=collector,
    )
    session._handle_notification(
        "turn/started", {"turn": {"id": TURN_ID, "status": "inProgress"}}
    )
    session._handle_notification(
        "hook/started",
        {
            "turnId": TURN_ID,
            "run": {
                "id": "pre-tool-use:0:C:\\Users\\jinhy\\.codex\\hooks.json:exec-12ebf048-e7ad-454a-98d9-f63ff3d1a675",
                "eventName": "preToolUse",
                "status": "running",
            },
        },
    )
    session._handle_notification(
        "hook/completed",
        {
            "turnId": TURN_ID,
            "run": {
                "id": "pre-tool-use:0:C:\\Users\\jinhy\\.codex\\hooks.json:exec-12ebf048-e7ad-454a-98d9-f63ff3d1a675",
                "eventName": "preToolUse",
                "status": "blocked",
            },
        },
    )
    session._handle_notification(
        "turn/completed", {"turn": {"id": TURN_ID, "status": "completed"}}
    )
    ui_events = session.read_events()
    assert [event["type"] for event in ui_events] == ["turn.started", "hook", "hook", "turn.completed"]
    assert ui_events[1]["hook_run_id"] == (
        "pre-tool-use:0:C:\\Users\\jinhy\\.codex\\hooks.json:exec-12ebf048-e7ad-454a-98d9-f63ff3d1a675"
    )
    session._events.clear()
    collector.mark_process_exit(0, unexpected=False)
    snapshot = collector.snapshot()
    assert session.read_events() == []
    assert snapshot.collection_complete
    assert [event.phase for event in snapshot.events] == ["started", "completed"]
    assert snapshot.events[0].hook_run_id == (
        "pre-tool-use:0:C:\\Users\\jinhy\\.codex\\hooks.json:exec-12ebf048-e7ad-454a-98d9-f63ff3d1a675"
    )
    assert snapshot.events[1].status == "blocked"
    assert snapshot.turn_statuses[TURN_ID] == "completed"


def test_gui_confirmation_fails_closed_when_call_id_is_missing(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    controller._events[0] = replace(controller._events[0], tool_use_id="")

    assert _confirm(controller, records, _snapshot([{"tool_use_id": DENIED_ID}])) == (None,)
    assert "BLOCK_CONFIRMATION_UNAVAILABLE" in controller.events[0].gate_result.failure_reasons
    assert controller.events[0].gate_result.confirmation_basis["aia_pretool_count"] is None


def test_gui_confirmation_rejects_completed_hook_before_started(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    collector = CodexHookEventCollector()
    collector.observe_notification(
        "turn/started", {"turn": {"id": TURN_ID, "status": "inProgress"}}
    )
    _hook_event(collector, "completed", DENIED_ID, status="blocked")
    _hook_event(collector, "started", DENIED_ID)
    collector.observe_notification(
        "turn/completed", {"turn": {"id": TURN_ID, "status": "completed"}}
    )
    collector.mark_process_exit(0, unexpected=False)

    assert _confirm(controller, records, collector.snapshot()) == (None,)


def test_gui_confirmation_normalizes_hooks_path_case_and_separators(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    assert _confirm(
        controller,
        records,
        _snapshot([{"tool_use_id": DENIED_ID}]),
        hooks_path=r"c:/USERS/JINHY/.CODEX/hooks.json",
    ) == (True,)


def test_gui_confirmation_waits_for_late_posttool_before_finalizing_deny(tmp_path: Path) -> None:
    controller, records, _ = _make_controller(tmp_path, tool_ids=(DENIED_ID,))
    evidence = list(records)
    handler_entered = Event()
    release_handler = Event()
    stop_finished = Event()
    stop_result: list[bool] = []

    def handler(_payload):
        handler_entered.set()
        assert release_handler.wait(3)
        evidence[:] = _append_posttool(tuple(evidence), DENIED_ID)
        return {"ok": True}

    broker = CodexHookBroker(
        capability_secret="test-capability",
        session_id="session-1",
        launch_id="launch-1",
        control_root=Path("C:/temporary/control"),
        handler=handler,
    )
    broker.start()
    environment = broker.environment

    def send_request() -> None:
        request = Request(
            environment["AIA_CODEX_HOOK_ENDPOINT"],
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-AIA-Capability": environment["AIA_CODEX_HOOK_CAPABILITY"],
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert json.loads(response.read()) == {"ok": True}

    request_thread = Thread(target=send_request)
    request_thread.start()
    assert handler_entered.wait(2)
    stopper = Thread(target=lambda: (stop_result.append(broker.stop()), stop_finished.set()))
    stopper.start()
    time.sleep(0.1)
    assert not stop_finished.is_set()
    release_handler.set()
    request_thread.join(timeout=5)
    stopper.join(timeout=5)
    assert not request_thread.is_alive()
    assert not stopper.is_alive()
    assert stop_result == [True]
    assert _confirm(
        controller,
        tuple(evidence),
        _snapshot([{"tool_use_id": DENIED_ID}]),
        broker_drained=stop_result[0],
    ) == (False,)
    assert "HOOK_ENFORCEMENT_FAILURE" in controller.events[0].gate_result.failure_reasons


def test_gui_hook_broker_end_barrier_waits_for_in_flight_request() -> None:
    handler_entered = Event()
    release_handler = Event()
    stop_finished = Event()
    stop_result: list[bool] = []

    def handler(_payload):
        handler_entered.set()
        assert release_handler.wait(3)
        return {"ok": True}

    broker = CodexHookBroker(
        capability_secret="test-capability",
        session_id="session-1",
        launch_id="launch-1",
        control_root=Path("C:/temporary/control"),
        handler=handler,
    )
    broker.start()
    environment = broker.environment

    def send_request() -> None:
        request = Request(
            environment["AIA_CODEX_HOOK_ENDPOINT"],
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-AIA-Capability": environment["AIA_CODEX_HOOK_CAPABILITY"],
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert json.loads(response.read()) == {"ok": True}

    request_thread = Thread(target=send_request)
    request_thread.start()
    assert handler_entered.wait(2)
    stopper = Thread(target=lambda: (stop_result.append(broker.stop()), stop_finished.set()))
    stopper.start()
    time.sleep(0.1)
    assert not stop_finished.is_set()
    release_handler.set()
    request_thread.join(timeout=5)
    stopper.join(timeout=5)
    assert not request_thread.is_alive()
    assert not stopper.is_alive()
    assert stop_result == [True]
    assert broker.in_flight_requests == 0