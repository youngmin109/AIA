from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import time

import pytest

import aia_app.codex_app_server as app_server
from aia_app.codex_app_server import (
    CodexAppServerError,
    CodexAppServerSession,
    normalize_notification,
)


FAKE_SERVER = Path(__file__).with_name("fake_codex_app_server.py")


def _session(tmp_path: Path, **env: str) -> CodexAppServerSession:
    session = CodexAppServerSession(
        [sys.executable, "-u", str(FAKE_SERVER)],
        cwd=tmp_path,
        env={**os.environ, **env},
        client_version="test",
    )
    session.start()
    return session


def _wait_for(session: CodexAppServerSession, predicate, timeout: float = 10.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = session.read_events()
        if predicate(events):
            return events
        session.wait_events(events[-1]["sequence"] if events else 0, timeout=0.2)
    raise AssertionError(f"condition not met; events={session.read_events()}")


def _types(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


@pytest.fixture
def opened(tmp_path: Path):
    session = _session(tmp_path)
    session.open()
    yield session
    session.close(force=True)


def test_normalize_keeps_only_rendered_fields_and_ignores_unknown_notifications() -> None:
    assert normalize_notification(
        "item/agentMessage/delta", {"itemId": "a1", "delta": "hi", "threadId": "t", "turnId": "u"}
    ) == {"type": "message.delta", "item_id": "a1", "text": "hi"}
    hook = normalize_notification(
        "hook/completed",
        {"turnId": "turn-1", "run": {"id": "h1", "eventName": "preToolUse", "status": "blocked", "durationMs": 4,
                                     "entries": [{"text": "raw hook output"}]}},
    )
    assert hook == {"type": "hook", "phase": "completed", "turn_id": "turn-1", "hook_run_id": "h1",
                    "event_name": "preToolUse", "status": "blocked", "duration_ms": 4}
    assert "raw hook output" not in str(hook)
    assert normalize_notification("thread/tokenUsage/updated", {"tokenUsage": {}}) is None
    assert normalize_notification("some/futureNotification", {}) is None


def test_console_utf8_retries_attach_and_sets_both_code_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClock:
        now = 10.0

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    class FakeKernel32:
        def __init__(self) -> None:
            self.attach_results = iter((False, True))
            self.attach_calls = 0
            self.output_code_pages: list[int] = []
            self.input_code_pages: list[int] = []
            self.free_calls = 0

        def AttachConsole(self, pid: int) -> bool:
            assert pid == 123
            self.attach_calls += 1
            return next(self.attach_results)

        def SetConsoleOutputCP(self, code_page: int) -> bool:
            self.output_code_pages.append(code_page)
            return True

        def SetConsoleCP(self, code_page: int) -> bool:
            self.input_code_pages.append(code_page)
            return True

        def FreeConsole(self) -> None:
            self.free_calls += 1

    clock = FakeClock()
    kernel32 = FakeKernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 123, raising=False)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)

    assert app_server._switch_console_to_utf8(123) is True
    assert kernel32.attach_calls == 2
    assert kernel32.output_code_pages == [65001]
    assert kernel32.input_code_pages == [65001]
    assert kernel32.free_calls == 1


def test_console_utf8_stops_retrying_at_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClock:
        now = 10.0
        sleeps = 0

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.sleeps += 1
            self.now += seconds

    class FakeKernel32:
        attach_calls = 0

        def AttachConsole(self, pid: int) -> bool:
            assert pid == 123
            self.attach_calls += 1
            return False

    clock = FakeClock()
    kernel32 = FakeKernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 123, raising=False)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)

    assert app_server._switch_console_to_utf8(123) is False
    assert clock.now == pytest.approx(12.0)
    assert clock.sleeps == 40
    assert kernel32.attach_calls == 41


def test_open_reports_the_sandbox_and_approval_policy_codex_applied(tmp_path: Path) -> None:
    session = _session(tmp_path, FAKE_APP_SERVER_SANDBOX="readOnly")
    try:
        effective = session.open(sandbox="workspace-write", approval_policy="on-request")
        assert effective == {"model": "fake-model", "approval_policy": "on-request", "sandbox": "readOnly"}
        assert session.snapshot()["status"] == "READY"
        assert session.read_events()[-1]["type"] == "session.ready"
    finally:
        session.close(force=True)


@pytest.mark.skipif(os.name != "nt", reason="the console code page applies to Windows commands only")
def test_codex_commands_get_a_utf8_console_and_python_utf8_mode(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        environment = session._request("initialize", {"clientInfo": {"name": "t", "version": "0"}})
        assert environment["consoleOutputCodePage"] == 65001
        assert environment["pythonUtf8"] == "1"
        assert session.snapshot()["console_utf8"] is True
    finally:
        session.close(force=True)


def test_explicit_python_utf8_setting_is_preserved(tmp_path: Path) -> None:
    session = _session(tmp_path, PYTHONUTF8="0")
    try:
        environment = session._request("initialize", {"clientInfo": {"name": "t", "version": "0"}})
        assert environment["pythonUtf8"] == "0"
    finally:
        session.close(force=True)


def test_open_refuses_unprotected_sandbox_or_approval_policy(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        with pytest.raises(CodexAppServerError):
            session.open(sandbox="danger-full-access")
        with pytest.raises(CodexAppServerError):
            session.open(approval_policy="never")
    finally:
        session.close(force=True)


def test_message_turn_streams_deltas_and_returns_to_ready(opened: CodexAppServerSession) -> None:
    result = opened.send_message("hello codex")
    assert result["mode"] == "start"
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    kinds = _types(events)
    assert kinds.index("turn.started") < kinds.index("user_message") < kinds.index("message.delta")
    assert "".join(e["text"] for e in events if e["type"] == "message.delta") == "Hello there"
    assert [e["text"] for e in events if e["type"] == "message.completed"] == ["Hello there"]
    assert [e["text"] for e in events if e["type"] == "user_message"] == ["hello codex"]
    _wait_for(opened, lambda _: opened.snapshot()["status"] == "READY")
    assert opened.snapshot()["active_turn_id"] is None


@pytest.mark.parametrize(("decision", "status", "output"), [("accept", "completed", "hi\r\n"), ("decline", "declined", "")])
def test_command_approval_round_trip(opened: CodexAppServerSession, decision: str, status: str, output: str) -> None:
    opened.send_message("run it")
    events = _wait_for(opened, lambda items: "approval.requested" in _types(items))
    request = next(e for e in events if e["type"] == "approval.requested")
    assert request["kind"] == "command"
    assert request["command"] == "echo hi"
    assert "request_id" not in request
    hooks = [e for e in events if e["type"] == "hook"]
    assert [(h["phase"], h["event_name"]) for h in hooks] == [("started", "preToolUse"), ("completed", "preToolUse")]
    assert opened.snapshot()["pending_approvals"][0]["approval_id"] == request["approval_id"]

    opened.respond_approval(request["approval_id"], decision)

    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    completed = next(e for e in events if e["type"] == "command.completed")
    assert completed["status"] == status
    assert "".join(e["text"] for e in events if e["type"] == "command.output") == output
    assert {"type": "approval.resolved", "approval_id": request["approval_id"], "decision": decision}.items() <= next(
        e for e in events if e["type"] == "approval.resolved"
    ).items()
    assert opened.snapshot()["pending_approvals"] == []
    with pytest.raises(CodexAppServerError):
        opened.respond_approval(request["approval_id"], decision)


def test_file_change_approval_carries_the_affected_paths(opened: CodexAppServerSession) -> None:
    opened.send_message("patch notes")
    events = _wait_for(opened, lambda items: "approval.requested" in _types(items))
    request = next(e for e in events if e["type"] == "approval.requested")
    assert request["kind"] == "file_change"
    assert request["paths"] == ["notes.txt"]
    opened.respond_approval(request["approval_id"], "acceptForSession")
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    assert next(e for e in events if e["type"] == "file_change.completed")["status"] == "completed"


def test_invalid_approval_decision_is_rejected_without_answering_codex(opened: CodexAppServerSession) -> None:
    opened.send_message("run it")
    events = _wait_for(opened, lambda items: "approval.requested" in _types(items))
    approval_id = next(e for e in events if e["type"] == "approval.requested")["approval_id"]
    with pytest.raises(CodexAppServerError):
        opened.respond_approval(approval_id, "approved")
    assert opened.snapshot()["pending_approvals"][0]["approval_id"] == approval_id


def test_unsupported_server_request_gets_an_error_reply_instead_of_hanging(opened: CodexAppServerSession) -> None:
    opened.send_message("ask me")
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    assert [e["text"] for e in events if e["type"] == "message.completed"] == ["got-error"]
    assert any(e["type"] == "warning" and "requestUserInput" in e["message"] for e in events)


def test_interrupt_ends_the_active_turn(opened: CodexAppServerSession) -> None:
    opened.send_message("slow task")
    _wait_for(opened, lambda _: opened.snapshot()["status"] == "WORKING")
    assert opened.interrupt()["accepted"] is True
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    assert next(e for e in events if e["type"] == "turn.completed")["status"] == "interrupted"
    _wait_for(opened, lambda _: opened.snapshot()["status"] == "READY")
    assert opened.interrupt() == {"accepted": False, "reason": "NO_ACTIVE_TURN"}


def test_message_during_active_turn_steers_instead_of_starting_a_new_turn(opened: CodexAppServerSession) -> None:
    opened.send_message("slow task")
    _wait_for(opened, lambda _: opened.snapshot()["status"] == "WORKING")
    result = opened.send_message("also check tests")
    assert result["mode"] == "steer"
    events = _wait_for(opened, lambda items: sum(e["type"] == "user_message" for e in items) == 2)
    assert [e["text"] for e in events if e["type"] == "user_message"] == ["slow task", "also check tests"]
    opened.interrupt()


def test_turn_that_finishes_before_its_start_response_does_not_stick_working(opened: CodexAppServerSession) -> None:
    opened.send_message("race condition")
    _wait_for(opened, lambda items: "turn.completed" in _types(items))
    assert opened.snapshot()["status"] == "READY"
    assert opened.snapshot()["active_turn_id"] is None


def test_unexpected_exit_fails_the_session_and_pending_requests(opened: CodexAppServerSession) -> None:
    with pytest.raises(CodexAppServerError):
        opened.send_message("crash now")
    events = _wait_for(opened, lambda items: "session.exited" in _types(items))
    exited = next(e for e in events if e["type"] == "session.exited")
    assert exited == {**exited, "exit_code": 3, "unexpected": True}
    snapshot = opened.snapshot()
    assert snapshot["status"] == "FAILED"
    assert snapshot["error"] == "CODEX_APP_SERVER_EXITED"
    with pytest.raises(CodexAppServerError):
        opened.send_message("hello again")


def test_graceful_close_cancels_pending_approval_and_lets_codex_exit(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.open()
    session.send_message("run it")
    _wait_for(session, lambda items: "approval.requested" in _types(items))
    session.close()
    events = session.read_events()
    assert any(e["type"] == "approval.resolved" and e["decision"] == "cancel" for e in events)
    assert events[-1]["type"] == "session.exited"
    assert events[-1]["unexpected"] is False
    snapshot = session.snapshot()
    assert snapshot["status"] == "EXITED"
    assert snapshot["exit_code"] == 0
    assert snapshot["pending_approvals"] == []


def test_events_replay_from_any_sequence_and_the_buffer_is_bounded(tmp_path: Path) -> None:
    session = CodexAppServerSession(["codex"], cwd=tmp_path, env={})
    session.MAX_EVENTS = 5
    for index in range(8):
        session._append_event({"type": "message.delta", "item_id": "a", "text": str(index)})
    events = session.read_events()
    assert [e["sequence"] for e in events] == [4, 5, 6, 7, 8]
    assert [e["text"] for e in session.read_events(6)] == ["6", "7"]
    assert session.read_events(8) == []
    with pytest.raises(CodexAppServerError):
        session.read_events(-1)


def test_event_text_budget_evicts_oldest_events(tmp_path: Path) -> None:
    session = CodexAppServerSession(["codex"], cwd=tmp_path, env={})
    session.MAX_EVENT_TEXT_CHARS = 10
    session._append_event({"type": "command.output", "text": "123456"})
    session._append_event({"type": "command.output", "text": "abcdef"})
    assert [e["text"] for e in session.read_events()] == ["abcdef"]


def test_wait_events_returns_new_events_or_times_out(tmp_path: Path) -> None:
    session = CodexAppServerSession(["codex"], cwd=tmp_path, env={})
    started = time.monotonic()
    assert session.wait_events(0, timeout=0.1) == []
    assert time.monotonic() - started >= 0.09
    session._append_event({"type": "warning", "message": "x"})
    assert [e["type"] for e in session.wait_events(0, timeout=1.0)] == ["warning"]


def test_send_message_validates_input_before_contacting_codex(opened: CodexAppServerSession) -> None:
    for value in ("", "   ", "x" * (CodexAppServerSession.MAX_INPUT_CHARS + 1)):
        with pytest.raises(CodexAppServerError):
            opened.send_message(value)
