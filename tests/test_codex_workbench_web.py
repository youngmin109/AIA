from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from aia_app.codex_app_server import CodexAppServerSession
from aia_app.registry import RunRecord
from aia_app.service import RunApplicationService
from aia_web.app import _coalesce_codex_events, create_app


FAKE_SERVER = Path(__file__).with_name("fake_codex_app_server.py")


@pytest.fixture
def conversation(tmp_path: Path):
    """A registered live run whose conversation is backed by the fake app-server."""

    service = RunApplicationService(tmp_path / "control")
    record = RunRecord(
        session_id="run-1",
        workspace=tmp_path,
        agent="codex",
        model=None,
        policy_profile="BASIC_DEVELOPMENT",
        policy_id="basic-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="",
        interactive=True,
        launch_mode="codex_app_server",
        created_at=datetime.now(timezone.utc),
    )
    record.status = "RUNNING"
    session = CodexAppServerSession(
        [sys.executable, "-u", str(FAKE_SERVER)], cwd=tmp_path, env=dict(os.environ), client_version="test"
    )
    session.start()
    session.open()
    record.runtime["codex_session"] = session
    service.registry.add(record)
    client = TestClient(create_app(service), base_url="http://127.0.0.1")
    yield client, session
    session.close(force=True)
    service.shutdown()


def _receive_until(websocket, predicate, limit: int = 200) -> list[dict]:
    messages = []
    for _ in range(limit):
        message = websocket.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"predicate not met in {messages}")


def _receive_until_all(websocket, *predicates, limit: int = 200) -> list[dict]:
    """Events are pushed concurrently with command replies, so wait for every
    expected message regardless of arrival order."""

    messages = []
    pending = list(predicates)
    for _ in range(limit):
        message = websocket.receive_json()
        messages.append(message)
        pending = [predicate for predicate in pending if not predicate(message)]
        if not pending:
            return messages
    raise AssertionError(f"predicates not met in {messages}")


def _turn_completed(message: dict) -> bool:
    return message["type"] == "events" and any(e["type"] == "turn.completed" for e in message["events"])


def _accepted(action: str):
    return lambda message: message["type"] == "accepted" and message["action"] == action


def _events(messages: list[dict]) -> list[dict]:
    return [event for message in messages if message["type"] == "events" for event in message["events"]]


def test_coalesce_merges_adjacent_deltas_of_the_same_item_and_keeps_order() -> None:
    events = [
        {"sequence": 1, "type": "message.delta", "item_id": "a", "text": "Hel"},
        {"sequence": 2, "type": "message.delta", "item_id": "a", "text": "lo"},
        {"sequence": 3, "type": "hook", "phase": "started"},
        {"sequence": 4, "type": "message.delta", "item_id": "a", "text": "!"},
        {"sequence": 5, "type": "command.output", "item_id": "c", "text": "x"},
        {"sequence": 6, "type": "command.output", "item_id": "d", "text": "y"},
    ]
    [batch] = _coalesce_codex_events(events)
    assert [(e["type"], e.get("text"), e["sequence"]) for e in batch] == [
        ("message.delta", "Hello", 2),
        ("hook", None, 3),
        ("message.delta", "!", 4),
        ("command.output", "x", 5),
        ("command.output", "y", 6),
    ]


def test_coalesce_splits_large_replays_into_bounded_batches() -> None:
    events = [
        {"sequence": index, "type": "command.output", "item_id": f"c{index}", "text": "x" * 20_000}
        for index in range(1, 9)
    ]
    batches = _coalesce_codex_events(events)
    assert len(batches) > 1
    assert [e["sequence"] for batch in batches for e in batch] == list(range(1, 9))


def test_socket_streams_a_turn_pushed_by_codex(conversation) -> None:
    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        first = _receive_until(websocket, lambda m: m["type"] == "status")
        assert first[-1]["status"] == "READY"
        websocket.send_json({"type": "user_message", "text": "hello codex", "client_id": "c1"})
        messages = _receive_until_all(websocket, _turn_completed, _accepted("user_message"))
        accepted = next(m for m in messages if m["type"] == "accepted")
        assert accepted["client_id"] == "c1"
        assert accepted["action"] == "user_message"
        events = _events(first + messages)
        assert [e["text"] for e in events if e["type"] == "user_message"] == ["hello codex"]
        assert "".join(e["text"] for e in events if e["type"] == "message.delta") == "Hello there"


def test_socket_relays_an_approval_decision_to_codex(conversation) -> None:
    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        websocket.send_json({"type": "user_message", "text": "run it"})
        messages = _receive_until(
            websocket,
            lambda m: m["type"] == "events" and any(e["type"] == "approval.requested" for e in m["events"]),
        )
        request = next(e for e in _events(messages) if e["type"] == "approval.requested")
        websocket.send_json({"type": "approval_decision", "approval_id": request["approval_id"], "decision": "accept"})
        messages = messages + _receive_until_all(websocket, _turn_completed, _accepted("approval_decision"))
        completed = next(e for e in _events(messages) if e["type"] == "command.completed")
        assert completed["status"] == "completed"


def test_socket_relays_question_answers_to_codex(conversation) -> None:
    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        websocket.send_json({"type": "user_message", "text": "question please"})
        messages = _receive_until(
            websocket,
            lambda m: m["type"] == "events" and any(e["type"] == "question.requested" for e in m["events"]),
        )
        request = next(e for e in _events(messages) if e["type"] == "question.requested")
        websocket.send_json({"type": "question_answer", "question_id": request["question_id"],
                             "answers": {"scope": ["Some"], "token": ["t0ken"]}})
        messages = messages + _receive_until_all(websocket, _turn_completed, _accepted("question_answer"))
        accepted = next(m for m in messages if m["type"] == "accepted")
        assert "t0ken" not in str(accepted)
        answered = next(e for e in _events(messages) if e["type"] == "question.answered")
        assert answered["answers"] == {"scope": ["Some"], "token": None}


def test_diff_text_is_served_on_demand(conversation) -> None:
    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        websocket.send_json({"type": "user_message", "text": "diff please"})
        messages = _receive_until(websocket, _turn_completed)
        update = [e for e in _events(messages) if e["type"] == "diff.updated"][-1]
    response = client.get(f"/api/runs/run-1/codex/diff?turn_id={update['turn_id']}")
    assert response.status_code == 200 and "+hello" in response.json()["diff"]
    assert client.get("/api/runs/run-1/codex/diff?turn_id=nope").status_code == 409
    assert client.get("/api/runs/missing/codex/diff").status_code == 404


def test_socket_reports_rejected_commands_without_closing(conversation) -> None:
    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        websocket.send_json({"type": "user_message", "text": "   ", "client_id": "bad"})
        error = _receive_until(websocket, lambda m: m["type"] == "error")[-1]
        assert error["client_id"] == "bad"
        assert error["action"] == "user_message"
        websocket.send_json({"type": "approval_decision", "approval_id": "missing", "decision": "accept"})
        assert _receive_until(websocket, lambda m: m["type"] == "error")[-1]["action"] == "approval_decision"
        websocket.send_json({"type": "resize"})
        assert "unsupported" in _receive_until(websocket, lambda m: m["type"] == "error")[-1]["message"]
        websocket.send_json({"type": "user_message", "text": "hello again"})
        assert _receive_until(websocket, lambda m: m["type"] == "accepted")[-1]["mode"] == "start"


def test_reconnect_resumes_after_the_last_rendered_event(conversation) -> None:
    client, session = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        websocket.send_json({"type": "user_message", "text": "hello codex"})
        _receive_until_all(websocket, _turn_completed, _accepted("user_message"))
    last = session.snapshot()["last_sequence"]
    with client.websocket_connect(f"ws://127.0.0.1/api/runs/run-1/codex?after={last}") as websocket:
        status = _receive_until(websocket, lambda m: m["type"] == "status")
        assert _events(status) == []
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex?after=0") as websocket:
        replay = _receive_until(websocket, lambda m: m["type"] == "status")
        assert any(e["type"] == "turn.completed" for e in _events(replay))


def test_end_session_lets_codex_exit_and_closes_the_socket(conversation) -> None:
    client, session = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        _receive_until(websocket, lambda m: m["type"] == "status")
        websocket.send_json({"type": "end_session"})
        messages = _receive_until(websocket, lambda m: m["type"] == "closed")
        assert messages[-1]["status"] == "EXITED"
        assert any(e["type"] == "session.exited" and e["unexpected"] is False for e in _events(messages))
    assert session.snapshot()["status"] == "EXITED"


def test_socket_closes_on_an_oversized_client_message_without_parsing_it(conversation) -> None:
    from starlette.websockets import WebSocketDisconnect

    client, _ = conversation
    with client.websocket_connect("ws://127.0.0.1/api/runs/run-1/codex") as websocket:
        _receive_until(websocket, lambda m: m["type"] == "status")
        websocket.send_text("{" + " " * (64 * 1024))
        with pytest.raises(WebSocketDisconnect) as closed:
            _receive_until(websocket, lambda m: False)
    assert closed.value.code == 1009


def test_codex_status_endpoint_and_unknown_run(conversation) -> None:
    client, _ = conversation
    assert client.get("/api/runs/run-1/codex/status").json()["status"] == "READY"
    assert client.get("/api/runs/missing/codex/status").status_code == 404


def test_socket_for_a_run_owned_by_another_aia_window(tmp_path: Path) -> None:
    import json
    import subprocess

    from aia import process_create_time

    session_id = "33333333-2222-4333-8444-555555555555"
    service = RunApplicationService(tmp_path / "control")
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        path = service._runtime_state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1,
            "session_id": session_id,
            "coordinator": {"pid": owner.pid, "create_time": process_create_time(owner.pid)},
            "session": {"session_id": session_id, "status": "RUNNING", "workspace": str(tmp_path), "agent": "codex"},
            "launch_mode": "codex_app_server",
            "phase": "RUNNING",
        }), encoding="utf-8")
        client = TestClient(create_app(service), base_url="http://127.0.0.1")
        with client.websocket_connect(f"ws://127.0.0.1/api/runs/{session_id}/codex") as websocket:
            status = _receive_until(websocket, lambda m: m["type"] == "status")[-1]
            assert status["status"] == "EXTERNAL"
            assert status["owner_pid"] == owner.pid
            websocket.send_json({"type": "user_message", "text": "hello"})
            error = _receive_until(websocket, lambda m: m["type"] == "error")[-1]
            assert "다른 AIA 창" in error["message"]
            websocket.send_json({"type": "end_session", "client_id": "e1"})
            accepted = _receive_until(websocket, lambda m: m["type"] == "accepted")[-1]
            assert accepted["mode"] == "requested_owner"
        assert service._stop_request_reason(session_id) == "END_SESSION"
    finally:
        owner.kill()
        owner.wait()
        service.shutdown()
