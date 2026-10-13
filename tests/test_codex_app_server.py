from __future__ import annotations

import ctypes
import json
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

    assert app_server._switch_console_to_utf8_with_reason(123) == (False, "ATTACH_TIMEOUT:123")
    deadline = 10.0 + app_server._CONSOLE_ATTACH_SECONDS
    assert deadline <= clock.now < deadline + 0.1
    assert kernel32.attach_calls == clock.sleeps + 1


def test_open_reports_the_sandbox_and_approval_policy_codex_applied(tmp_path: Path) -> None:
    session = _session(tmp_path, FAKE_APP_SERVER_SANDBOX="readOnly")
    try:
        effective = session.open(sandbox="workspace-write", approval_policy="on-request")
        assert effective == {"model": "fake-model", "approval_policy": "on-request", "approvals_reviewer": "user", "sandbox": "readOnly"}
        assert session.snapshot()["status"] == "READY"
        assert session.read_events()[-1]["type"] == "session.ready"
    finally:
        session.close(force=True)


@pytest.mark.skipif(os.name != "nt", reason="the console code page applies to Windows commands only")
def test_codex_commands_get_a_utf8_console_and_python_utf8_mode(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        snapshot = session.snapshot()
        assert snapshot["console_utf8"] is True, snapshot["console_utf8_error"]
        assert snapshot["console_utf8_error"] is None
        environment = session._request("initialize", {"clientInfo": {"name": "t", "version": "0"}})
        assert environment["consoleOutputCodePage"] == 65001
        assert environment["pythonUtf8"] == "1"
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


def test_question_round_trip_never_keeps_a_secret_answer(opened: CodexAppServerSession) -> None:
    opened.send_message("question please")
    events = _wait_for(opened, lambda items: "question.requested" in _types(items))
    request = next(e for e in events if e["type"] == "question.requested")
    assert "request_id" not in request
    scope, token = request["questions"]
    assert (scope["id"], scope["allow_other"], [o["label"] for o in scope["options"]]) == ("scope", True, ["All", "Some"])
    assert (token["id"], token["secret"], token["options"]) == ("token", True, [])
    assert opened.snapshot()["pending_questions"][0]["question_id"] == request["question_id"]

    with pytest.raises(CodexAppServerError):
        opened.respond_question(request["question_id"], {"unknown": ["x"]})
    with pytest.raises(CodexAppServerError):
        opened.respond_question(request["question_id"], {"scope": "All"})
    assert opened.snapshot()["pending_questions"], "a rejected answer keeps the question open"

    opened.respond_question(request["question_id"], {"scope": ["All"], "token": ["sk-secret-value"]})

    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    reply = next(e["text"] for e in events if e["type"] == "message.completed")
    assert reply == 'answers={"scope": {"answers": ["All"]}, "token": {"answers": ["sk-secret-value"]}}'
    answered = next(e for e in events if e["type"] == "question.answered")
    assert answered["answers"] == {"scope": ["All"], "token": None}
    # The fake Codex echoes what it received; AIA's own question events never hold the secret.
    assert all("sk-secret-value" not in json.dumps(e) for e in events if e["type"].startswith("question."))
    assert opened.snapshot()["pending_questions"] == []


def test_skipping_a_question_sends_no_answers(opened: CodexAppServerSession) -> None:
    opened.send_message("question please")
    events = _wait_for(opened, lambda items: "question.requested" in _types(items))
    question_id = next(e for e in events if e["type"] == "question.requested")["question_id"]
    assert opened.respond_question(question_id, {})["skipped"] is True
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    assert next(e["text"] for e in events if e["type"] == "message.completed") == "answers={}"


def test_question_resolved_by_codex_is_closed_with_its_deadline(opened: CodexAppServerSession) -> None:
    opened.send_message("question-auto now")
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    request = next(e for e in events if e["type"] == "question.requested")
    assert request["auto_resolve_at"] is not None
    resolved = next(e for e in events if e["type"] == "question.resolved")
    assert (resolved["question_id"], resolved["reason"]) == (request["question_id"], "resolved_by_codex")
    assert opened.snapshot()["pending_questions"] == []


def _elicitation(opened: CodexAppServerSession, text: str) -> dict:
    opened.send_message(text)
    events = _wait_for(opened, lambda items: "elicitation.requested" in _types(items))
    return next(e for e in events if e["type"] == "elicitation.requested")


def _final_reply(opened: CodexAppServerSession) -> tuple[str, list[dict]]:
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    return next(e["text"] for e in events if e["type"] == "message.completed"), events


def test_mcp_form_input_is_validated_and_never_kept_in_events(opened: CodexAppServerSession) -> None:
    request = _elicitation(opened, "mcp-form please")
    assert (request["server"], request["mode"], request["supported"]) == ("tracker", "form", True)
    fields = {field["name"]: field for field in request["fields"]}
    assert fields["project"]["kind"] == "select" and fields["project"]["required"] is True
    assert [option["value"] for option in fields["project"]["options"]] == ["web", "api"]
    assert (fields["count"]["kind"], fields["notify"]["kind"]) == ("integer", "boolean")
    assert opened.snapshot()["pending_elicitations"][0]["elicitation_id"] == request["elicitation_id"]

    for bad in ({"count": 2}, {"project": "mobile"}, {"project": "web", "count": 1.5}, {"project": "web", "extra": 1}):
        with pytest.raises(CodexAppServerError):
            opened.respond_elicitation(request["elicitation_id"], "accept", bad)
    opened.respond_elicitation(request["elicitation_id"], "accept", {"project": "api", "count": 3, "notify": True})

    reply, events = _final_reply(opened)
    assert reply == 'elicitation={"action": "accept", "content": {"count": 3, "notify": true, "project": "api"}}'
    resolved = next(e for e in events if e["type"] == "elicitation.resolved")
    assert resolved["action"] == "accept" and "content" not in resolved
    assert opened.snapshot()["pending_elicitations"] == []


def test_mcp_url_request_shows_the_host_and_accepts_without_content(opened: CodexAppServerSession) -> None:
    request = _elicitation(opened, "mcp-url please")
    assert (request["mode"], request["url_host"], request["supported"]) == ("url", "auth.example.com", True)
    opened.respond_elicitation(request["elicitation_id"], "accept")
    assert _final_reply(opened)[0] == 'elicitation={"action": "accept"}'


def test_mcp_form_the_workbench_cannot_draw_can_only_be_declined(opened: CodexAppServerSession) -> None:
    request = _elicitation(opened, "mcp-custom please")
    assert (request["mode"], request["supported"], request["fields"]) == ("openai/form", False, [])
    with pytest.raises(CodexAppServerError):
        opened.respond_elicitation(request["elicitation_id"], "accept", {})
    with pytest.raises(CodexAppServerError):
        opened.respond_elicitation(request["elicitation_id"], "approve")
    opened.respond_elicitation(request["elicitation_id"], "decline")
    assert _final_reply(opened)[0] == 'elicitation={"action": "decline"}'


def test_non_web_urls_are_never_offered_to_open() -> None:
    parsed = app_server._parse_elicitation(
        {"serverName": "x", "mode": "url", "message": "m", "elicitationId": "e", "url": "file:///C:/secret.txt"}
    )
    assert parsed["supported"] is False and parsed["url"] is None


def _permissions(opened: CodexAppServerSession) -> dict:
    opened.send_message("perm please")
    events = _wait_for(opened, lambda items: "permissions.requested" in _types(items))
    return next(e for e in events if e["type"] == "permissions.requested")


def test_permission_request_shows_where_protection_would_widen(opened: CodexAppServerSession) -> None:
    request = _permissions(opened)
    assert "requested" not in request and "request_id" not in request
    assert request["network"] is True
    assert request["reason"] == "needs the network and a sibling folder"
    scopes = [(entry["access"], entry["scope"]) for entry in request["filesystem"]]
    assert scopes == [("write", "outside"), ("read", "inside"), ("write", "outside")]
    assert request["filesystem"][2]["target"] == "컴퓨터 전체"
    assert opened.snapshot()["pending_permissions"][0]["permissions_id"] == request["permissions_id"]


@pytest.mark.parametrize("decision", ["turn", "session"])
def test_granting_permissions_echoes_the_request_with_its_scope(opened: CodexAppServerSession, decision: str) -> None:
    request = _permissions(opened)
    result = opened.respond_permissions(request["permissions_id"], decision)
    assert result["network"] is True and len(result["filesystem"]) == 3
    reply, events = _final_reply(opened)
    granted = json.loads(reply.removeprefix("permissions="))
    assert granted["scope"] == decision
    assert granted["permissions"]["network"] == {"enabled": True}
    assert len(granted["permissions"]["fileSystem"]["entries"]) == 3
    assert next(e for e in events if e["type"] == "permissions.resolved")["decision"] == decision


def test_declining_permissions_grants_nothing(opened: CodexAppServerSession) -> None:
    request = _permissions(opened)
    with pytest.raises(CodexAppServerError):
        opened.respond_permissions(request["permissions_id"], "always")
    opened.respond_permissions(request["permissions_id"], "decline")
    assert _final_reply(opened)[0] == 'permissions={"permissions": {}}'
    assert opened.snapshot()["pending_permissions"] == []


def test_permission_grant_is_recorded_before_codex_receives_it(opened, monkeypatch) -> None:
    request = _permissions(opened)
    order = []
    respond = opened._respond

    def send(request_id, result):
        assert order == ["recorded"]
        order.append("sent")
        respond(request_id, result)

    monkeypatch.setattr(opened, "_respond", send)
    opened.respond_permissions(request["permissions_id"], "turn", before_grant=lambda result: order.append("recorded"))
    assert order == ["recorded", "sent"]
    assert json.loads(_final_reply(opened)[0].removeprefix("permissions="))["scope"] == "turn"


def test_permission_record_failure_keeps_the_request_open_without_granting(opened) -> None:
    request = _permissions(opened)

    def fail(result):
        raise CodexAppServerError("record failed")

    with pytest.raises(CodexAppServerError, match="record failed"):
        opened.respond_permissions(request["permissions_id"], "session", before_grant=fail)
    assert opened.snapshot()["pending_permissions"][0]["permissions_id"] == request["permissions_id"]
    assert "permissions.resolved" not in _types(opened.read_events())
    opened.respond_permissions(request["permissions_id"], "decline", before_grant=fail)
    assert _final_reply(opened)[0] == 'permissions={"permissions": {}}'


def test_usage_limits_are_read_after_open_and_follow_codex_updates(opened: CodexAppServerSession) -> None:
    events = _wait_for(opened, lambda items: "usage.limits" in _types(items))
    limits = next(e for e in events if e["type"] == "usage.limits")["limits"]
    assert [(w["used_percent"], w["window_minutes"]) for w in limits["windows"]] == [(42, 300), (15, 10080)]
    assert limits["windows"][0]["resets_at"].startswith("2026-10-")
    assert opened.snapshot()["usage"]["limits"] == limits

    opened.send_message("usage please")
    _wait_for(opened, lambda items: "turn.completed" in _types(items))
    usage = opened.snapshot()["usage"]
    assert usage["tokens"] == {"total_tokens": 12345, "context_window": 200000}
    assert [w["used_percent"] for w in usage["limits"]["windows"]] == [60]


def test_usage_is_hidden_when_codex_has_no_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_APP_SERVER_NO_USAGE", "1")
    session = CodexAppServerSession(
        [sys.executable, "-u", str(FAKE_SERVER)], cwd=tmp_path, env=dict(os.environ), client_version="test"
    )
    session.start()
    try:
        session.open()
        session.send_message("hello there")
        _wait_for(session, lambda items: "turn.completed" in _types(items))
        assert session.snapshot()["usage"] == {"limits": None, "tokens": None}
        assert "usage.limits" not in _types(session.read_events())
    finally:
        session.close(force=True)


def test_usage_limits_accept_milliseconds_and_ignore_empty_snapshots() -> None:
    limits = app_server.usage_limits({"primary": {"usedPercent": 130, "resetsAt": 1791370000000}})
    assert limits["windows"][0]["used_percent"] == 100
    assert limits["windows"][0]["resets_at"].startswith("2026-10-")
    assert app_server.usage_limits({"primary": None}) is None
    assert app_server.usage_limits(None) is None


def test_model_list_comes_from_an_unopened_session_and_hides_hidden_models(tmp_path: Path) -> None:
    session = CodexAppServerSession(
        [sys.executable, "-u", str(FAKE_SERVER)], cwd=tmp_path, env=dict(os.environ), client_version="test"
    )
    session.start()
    try:
        models = session.list_models()
    finally:
        session.close(force=True)
    assert [model["model"] for model in models] == ["gpt-fast"]
    assert models[0]["is_default"] is True and models[0]["default_effort"] == "medium"
    assert [option["effort"] for option in models[0]["efforts"]] == ["low", "medium"]


def test_turn_settings_reach_turn_start_and_nothing_else_does(opened: CodexAppServerSession) -> None:
    opened.send_message("settings default")
    assert _final_reply(opened)[0] == "settings {}"
    with pytest.raises(CodexAppServerError):
        opened.set_turn_settings("gpt fast; rm -rf", None)
    with pytest.raises(CodexAppServerError):
        opened.set_turn_settings(None, "MAX")
    opened.set_turn_settings("gpt-fast", "low")
    assert opened.snapshot()["turn_settings"] == {"model": "gpt-fast", "effort": "low"}
    assert any(e["type"] == "settings.changed" for e in opened.read_events())
    opened.send_message("settings chosen")
    events = _wait_for(opened, lambda items: [e["type"] for e in items].count("turn.completed") >= 2)
    replies = [e["text"] for e in events if e["type"] == "message.completed"]
    assert replies[-1] == 'settings {"effort": "low", "model": "gpt-fast"}'


def test_permission_mode_goes_with_the_next_request_only(opened: CodexAppServerSession) -> None:
    with pytest.raises(CodexAppServerError):
        opened.set_permission_mode("yolo")
    opened.set_permission_mode("full_access")
    assert any(e["type"] == "permission.changed" and e["mode"] == "full_access" for e in opened.read_events())
    opened.send_message("settings yolo")
    _wait_for(opened, lambda items: [e["type"] for e in items].count("turn.completed") >= 1)
    opened.send_message("settings later")
    events = _wait_for(opened, lambda items: [e["type"] for e in items].count("turn.completed") >= 2)
    replies = [e["text"] for e in events if e["type"] == "message.completed"]
    # Codex keeps the override for later turns, so AIA sends it once.
    assert replies[-2:] == [
        'settings {"approvalPolicy": "never", "approvalsReviewer": "user", "sandboxPolicy": {"type": "dangerFullAccess"}}',
        "settings {}",
    ]


def test_permission_profiles_come_from_codex(tmp_path) -> None:
    session = CodexAppServerSession([sys.executable, "-u", str(FAKE_SERVER)], cwd=tmp_path, env=dict(os.environ))
    session.start()
    try:
        session.handshake()
        assert session.list_permission_profiles() == [
            {"id": ":read-only", "allowed": True},
            {"id": ":workspace", "allowed": True},
            {"id": ":danger-full-access", "allowed": False},
        ]
    finally:
        session.close(force=True)


def test_auto_review_outcome_is_kept_without_its_unstable_details() -> None:
    from aia_app.codex_app_server import normalize_notification

    assert normalize_notification("item/autoApprovalReview/completed", {
        "review": {"status": "denied", "riskLevel": "high", "rationale": "deletes files"}, "action": {"command": "rm -rf ."},
    }) == {"type": "auto_review.completed", "status": "denied", "risk": "high"}
    assert normalize_notification("item/autoApprovalReview/completed", {"review": {"status": "inProgress"}}) is None


def test_full_access_opens_only_as_the_complete_pair(tmp_path) -> None:
    session = CodexAppServerSession([sys.executable, "-u", str(FAKE_SERVER)], cwd=tmp_path, env=dict(os.environ))
    with pytest.raises(CodexAppServerError):
        session.open(sandbox="danger-full-access", approval_policy="on-request")
    with pytest.raises(CodexAppServerError):
        session.open(sandbox="workspace-write", approval_policy="never")
    with pytest.raises(CodexAppServerError):
        session.open(approvals_reviewer="guardian_subagent")


def test_plan_updates_keep_the_latest_steps(opened: CodexAppServerSession) -> None:
    opened.send_message("plan please")
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    plans = [e for e in events if e["type"] == "plan.updated"]
    assert len(plans) == 2 and plans[-1]["explanation"] == "Small fix"
    assert [(step["step"], step["status"]) for step in plans[-1]["steps"]] == [
        ("Read the code", "completed"), ("Fix the bug", "inProgress"), ("Run the tests", "pending")]
    assert opened.snapshot()["plan"]["steps"] == plans[-1]["steps"]


def test_diff_events_carry_a_summary_and_the_text_is_read_on_demand(opened: CodexAppServerSession) -> None:
    opened.send_message("diff please")
    events = _wait_for(opened, lambda items: "turn.completed" in _types(items))
    updates = [e for e in events if e["type"] == "diff.updated"]
    assert len(updates) == 2
    last = updates[-1]
    assert (last["files"], last["file_count"], last["added"], last["removed"]) == (["app.py", "notes.md"], 2, 2, 1)
    assert all("print(" not in json.dumps(e) for e in events if e["type"] == "diff.updated")
    diff = opened.read_diff(last["turn_id"])
    assert "+print('new')" in diff["diff"] and "+hello" in diff["diff"] and diff["truncated"] is False
    assert "notes.md" in opened.read_diff()["diff"]
    with pytest.raises(CodexAppServerError):
        opened.read_diff("turn-unknown")


def test_diff_summary_ignores_headers_and_dev_null() -> None:
    summary = app_server.diff_summary("--- a/x\n+++ b/x\n-a\n+b\n+c\n--- a/gone\n+++ /dev/null\n-z\n")
    assert summary == {"files": ["x"], "file_count": 1, "added": 2, "removed": 2}


def test_slash_commands_reach_codex_and_show_their_results(opened: CodexAppServerSession) -> None:
    opened.compact()
    events = _wait_for(opened, lambda items: "compaction.completed" in _types(items))
    assert "compaction.completed" in _types(events)

    opened.start_review()
    events = _wait_for(opened, lambda items: "review.completed" in _types(items))
    assert next(e for e in events if e["type"] == "review.completed")["text"] == "Looks good. One nit."
    _wait_for(opened, lambda _: opened.snapshot()["status"] == "READY")

    opened.set_goal("Ship the login fix")
    assert any(e["type"] == "goal.set" and e["text"] == "Ship the login fix" for e in opened.read_events())
    for bad in ("", "   ", "x" * 2001, 3):
        with pytest.raises(CodexAppServerError):
            opened.set_goal(bad)


def test_a_review_waits_for_the_current_request(opened: CodexAppServerSession) -> None:
    opened.send_message("slow work")
    _wait_for(opened, lambda _: opened.snapshot()["active_turn_id"] is not None)
    with pytest.raises(CodexAppServerError):
        opened.start_review()
    opened.interrupt()


def test_resuming_keeps_protection_and_shows_earlier_messages(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        effective = session.open(resume_thread_id="thr-old")
        assert effective["sandbox"] == "workspaceWrite" and effective["approval_policy"] == "on-request"
        assert session.snapshot()["thread_id"] == "thr-old"
        events = session.read_events()
        assert [e["text"] for e in events if e["type"] == "user_message"] == ["earlier question"]
        assert [e["text"] for e in events if e["type"] == "message.completed"] == ["earlier answer"]
        assert next(e for e in events if e["type"] == "history.restored")["count"] == 2
    finally:
        session.close(force=True)


def test_a_missing_conversation_starts_a_new_one_and_says_so(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        session.open(resume_thread_id="missing")
        assert session.snapshot()["thread_id"] == "thr-1"
        assert any(e["type"] == "warning" and "새 대화" in e["message"] for e in session.read_events())
    finally:
        session.close(force=True)


def test_thread_names_are_read_live_without_opening_a_conversation(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        session.handshake()
        info = session.read_thread("thr-old")
        assert (info["name"], info["preview"]) == ("Fix login", "earlier question")
        assert info["updated_at"].startswith("2026-10-")
        with pytest.raises(CodexAppServerError):
            session.read_thread("missing")
        assert session.snapshot()["thread_id"] is None
    finally:
        session.close(force=True)


def test_connectors_are_listed_read_only_while_a_conversation_is_open(opened: CodexAppServerSession) -> None:
    connectors = opened.list_connectors()
    assert [(c["name"], c["status"], c["auth"], c["tool_count"]) for c in connectors] == [
        ("github", "connected", "oAuth", 2), ("tracker", "authenticationRequired", "notLoggedIn", 0)]
    assert connectors[0]["tools"] == ["create_issue", "search_code"]
    assert connectors[1]["error"] == "login required"


def test_connectors_need_an_open_conversation(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        with pytest.raises(CodexAppServerError):
            session.list_connectors()
    finally:
        session.close(force=True)


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
