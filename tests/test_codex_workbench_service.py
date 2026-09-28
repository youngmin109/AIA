from __future__ import annotations

from datetime import datetime, timezone
import threading
import time

import pytest

import aia_app.service as service_module
from aia.codex_runtime import UnsupportedToolReview
from aia_app.codex_app_server import CodexAppServerError
from aia_app.dto import CreateRunRequest, DTOValidationError
from aia_app.registry import RunRecord
from aia_app.service import RunApplicationService


def make_record(tmp_path, launch_mode: str = "codex_app_server") -> RunRecord:
    record = RunRecord(
        session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        model="gpt-test",
        policy_profile="BASIC_DEVELOPMENT",
        policy_id="basic-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="",
        interactive=True,
        launch_mode=launch_mode,
        created_at=datetime.now(timezone.utc),
    )
    record.status = "RUNNING"
    return record


class FakeCodexSession:
    def __init__(self, effective: dict | None = None, open_error: Exception | None = None) -> None:
        self.effective = effective or {"model": "gpt-test", "approval_policy": "on-request", "sandbox": "workspaceWrite"}
        self.open_error = open_error
        self.calls: list[tuple] = []

    def open(self, **kwargs):
        self.calls.append(("open", kwargs))
        if self.open_error is not None:
            raise self.open_error
        return dict(self.effective)

    def close(self, *, force: bool = False) -> None:
        self.calls.append(("close", force))

    def snapshot(self) -> dict:
        return {"mode": "codex_app_server", "status": "READY", "error": None, "last_sequence": 3}

    def send_message(self, text: str) -> dict:
        self.calls.append(("send", text))
        return {"accepted": True, "mode": "start", "turn_id": "turn-1"}

    def interrupt(self) -> dict:
        self.calls.append(("interrupt",))
        return {"accepted": True, "turn_id": "turn-1"}

    def respond_approval(self, approval_id: str, decision: str) -> dict:
        self.calls.append(("approval", approval_id, decision))
        return {"accepted": True, "approval_id": approval_id, "decision": decision}

    def post_event(self, event: dict) -> None:
        self.calls.append(("event", dict(event)))

    def posted(self, event_type: str) -> list[dict]:
        return [call[1] for call in self.calls if call[0] == "event" and call[1]["type"] == event_type]

    def read_events(self, after_sequence: int = 0) -> list[dict]:
        return [{"sequence": 3, "type": "turn.started"}][after_sequence:]

    def wait_events(self, after_sequence: int = 0, timeout: float = 15.0) -> list[dict]:
        return self.read_events(after_sequence)


@pytest.fixture
def service(tmp_path):
    service = RunApplicationService(tmp_path / "control")
    yield service
    service.shutdown()


def test_codex_app_server_launch_mode_requires_interactive() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "interactive": True, "launch_mode": "codex_app_server"}
    )
    assert request.launch_mode == "codex_app_server"
    with pytest.raises(DTOValidationError, match="interactive"):
        CreateRunRequest.from_mapping({"workspace": ".", "task": "inspect", "launch_mode": "codex_app_server"})


def test_open_records_applied_settings_without_flags_when_protected(service, tmp_path) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session

    service._open_codex_conversation(record)

    assert session.calls == [("open", {"sandbox": "workspace-write", "approval_policy": "on-request", "model": "gpt-test"})]
    assert record.runtime["codex_effective_settings"]["sandbox"] == "workspaceWrite"
    assert "codex_sandbox_downgraded" not in record.runtime
    assert "codex_approval_policy_downgraded" not in record.runtime
    assert "protection_failure_reason" not in record.runtime


def test_open_records_downgrades_reported_by_codex(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.runtime["codex_session"] = FakeCodexSession(
        {"model": "m", "approval_policy": "untrusted", "sandbox": "readOnly"}
    )

    service._open_codex_conversation(record)

    assert record.runtime["codex_sandbox_downgraded"] is True
    assert record.runtime["codex_approval_policy_downgraded"] is True
    assert "protection_failure_reason" not in record.runtime


@pytest.mark.parametrize(
    "effective",
    [
        {"model": "m", "approval_policy": "on-request", "sandbox": "dangerFullAccess"},
        {"model": "m", "approval_policy": "never", "sandbox": "workspaceWrite"},
    ],
)
def test_open_ends_run_through_verified_termination_when_codex_applies_unprotected_settings(
    service, tmp_path, effective
) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession(effective)
    record.runtime["codex_session"] = session
    terminations: list[str] = []

    class Launcher:
        @staticmethod
        def request_protection_failure_termination_result(reason: str) -> dict:
            terminations.append(reason)
            return {"status": "SUCCEEDED", "outcome": "TERMINATED", "verified_tree_gone": True}

    record.runtime["launcher"] = Launcher()

    service._open_codex_conversation(record)

    assert terminations == ["CODEX_UNPROTECTED_SETTINGS_APPLIED"]
    assert record.runtime["protection_failure_reason"] == "CODEX_UNPROTECTED_SETTINGS_APPLIED"
    assert record.runtime["protection_failure_termination_result"]["status"] == "SUCCEEDED"
    assert record.protection_state == "DEGRADED"
    assert ("close", True) not in session.calls


def test_open_failure_is_recorded_and_lets_codex_exit(service, tmp_path) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession(open_error=CodexAppServerError("no answer"))
    record.runtime["codex_session"] = session

    service._open_codex_conversation(record)

    assert record.runtime["codex_app_server_error"] == "CODEX_APP_SERVER_OPEN_FAILED: no answer"
    assert session.calls[-1] == ("close", True)
    assert "protection_failure_reason" not in record.runtime


def test_conversation_api_delegates_to_the_attached_session(service, tmp_path) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service.registry.add(record)

    assert service.send_codex_message("session-1", "hello")["mode"] == "start"
    assert service.interrupt_codex_turn("session-1")["accepted"] is True
    assert service.respond_codex_approval("session-1", "approval-1", "decline")["decision"] == "decline"
    assert service.read_codex_events("session-1") == [{"sequence": 3, "type": "turn.started"}]
    assert service.end_codex_session("session-1") == {"accepted": True, "session_id": "session-1", "mode": "closed"}
    assert session.calls == [
        ("send", "hello"),
        ("interrupt",),
        ("approval", "approval-1", "decline"),
        ("close", False),
    ]


def test_codex_status_reports_detached_state_and_open_errors(service, tmp_path) -> None:
    record = make_record(tmp_path)
    service.registry.add(record)
    assert service.get_codex_status("session-1")["status"] == "NOT_ATTACHED"

    record.runtime["codex_session"] = FakeCodexSession()
    record.runtime["codex_app_server_error"] = "CODEX_APP_SERVER_OPEN_FAILED: no answer"
    status = service.get_codex_status("session-1")
    assert status["status"] == "READY"
    assert status["error"] == "CODEX_APP_SERVER_OPEN_FAILED: no answer"


def test_conversation_api_rejects_runs_that_do_not_use_the_conversation(service, tmp_path) -> None:
    record = make_record(tmp_path, launch_mode="inherit")
    record.runtime["codex_session"] = FakeCodexSession()
    service.registry.add(record)
    with pytest.raises(CodexAppServerError):
        service.send_codex_message("session-1", "hello")
    with pytest.raises(KeyError):
        service.send_codex_message("missing", "hello")


REVIEW = UnsupportedToolReview(tool_name="web_search", tool_use_id="tool-1", input_summary='{"query": "한글"}')


def _start_review(service, record) -> tuple[threading.Thread, dict]:
    outcome: dict = {}
    thread = threading.Thread(target=lambda: outcome.update(allowed=service._review_unsupported_tool(record, REVIEW)))
    thread.start()
    return thread, outcome


def _pending_review_id(service, session: FakeCodexSession) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        requested = session.posted("approval.requested")
        if requested:
            return requested[-1]["approval_id"]
        time.sleep(0.01)
    raise AssertionError("no review was requested")


@pytest.fixture
def review_run(service, tmp_path):
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service.registry.add(record)
    return record, session


@pytest.mark.parametrize(("decision", "allowed"), [("accept", True), ("decline", False)])
def test_unsupported_tool_review_waits_for_the_users_decision(service, review_run, decision, allowed) -> None:
    record, session = review_run
    thread, outcome = _start_review(service, record)
    approval_id = _pending_review_id(service, session)

    request = session.posted("approval.requested")[0]
    assert request["kind"] == "aia_tool"
    assert request["tool"] == "web_search"
    assert request["command"] == '{"query": "한글"}'
    assert service.get_codex_status("session-1")["pending_approvals"][-1]["approval_id"] == approval_id

    service.respond_codex_approval("session-1", approval_id, decision)
    thread.join(timeout=5)

    assert outcome["allowed"] is allowed
    assert session.posted("approval.resolved")[-1] == {"type": "approval.resolved", "approval_id": approval_id, "decision": decision}
    assert service.get_codex_status("session-1")["pending_approvals"] == []
    with pytest.raises(CodexAppServerError):
        service.respond_codex_approval("session-1", approval_id, "accept")


def test_unsupported_tool_review_times_out_as_a_refusal(service, review_run, monkeypatch) -> None:
    record, session = review_run
    monkeypatch.setattr(service_module, "_UNSUPPORTED_TOOL_REVIEW_SECONDS", 0.2)

    assert service._review_unsupported_tool(record, REVIEW) is False
    assert session.posted("approval.resolved")[-1]["decision"] == "timeout"
    assert service.get_codex_status("session-1")["pending_approvals"] == []


def test_allow_for_session_is_remembered_per_tool(service, review_run) -> None:
    record, session = review_run
    thread, outcome = _start_review(service, record)
    service.respond_codex_approval("session-1", _pending_review_id(service, session), "acceptForSession")
    thread.join(timeout=5)
    assert outcome["allowed"] is True

    assert service._review_unsupported_tool(record, REVIEW) is True
    assert len(session.posted("approval.requested")) == 1
    assert "이 세션 동안 허용됨" in session.posted("warning")[-1]["message"]


def test_unsupported_tool_review_rejects_codex_only_decisions(service, review_run) -> None:
    record, session = review_run
    thread, outcome = _start_review(service, record)
    approval_id = _pending_review_id(service, session)
    with pytest.raises(CodexAppServerError):
        service.respond_codex_approval("session-1", approval_id, "cancel")
    service.respond_codex_approval("session-1", approval_id, "decline")
    thread.join(timeout=5)
    assert outcome["allowed"] is False


def test_unsupported_tool_review_needs_the_conversation(service, tmp_path) -> None:
    record = make_record(tmp_path)
    assert service._review_unsupported_tool(record, REVIEW) is False


# -- runs coordinated by another AIA process (second desktop window) --------

EXTERNAL_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def external_run(service, tmp_path):
    """A live run whose runtime state names another running process as its coordinator."""

    import json as _json
    import subprocess
    import sys

    from aia import process_create_time

    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        path = service._runtime_state_path(EXTERNAL_ID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _json.dumps({
                "schema_version": 1,
                "session_id": EXTERNAL_ID,
                "coordinator": {"pid": owner.pid, "create_time": process_create_time(owner.pid)},
                "session": {"session_id": EXTERNAL_ID, "status": "RUNNING", "workspace": str(tmp_path), "agent": "codex"},
                "launch_mode": "codex_app_server",
                "phase": "RUNNING",
            }),
            encoding="utf-8",
        )
        yield owner
    finally:
        owner.kill()
        owner.wait()


def test_a_run_owned_by_another_aia_window_is_reported_as_external(service, external_run) -> None:
    status = service.get_codex_status(EXTERNAL_ID)
    assert status["status"] == "EXTERNAL"
    assert status["owner_pid"] == external_run.pid
    assert status["end_requested"] is False
    with pytest.raises(CodexAppServerError, match="다른 AIA 창"):
        service.send_codex_message(EXTERNAL_ID, "hello")


def test_ending_an_external_run_forwards_a_graceful_end_request(service, external_run) -> None:
    result = service.end_codex_session(EXTERNAL_ID)

    assert result == {"accepted": True, "session_id": EXTERNAL_ID, "mode": "requested_owner"}
    assert service._stop_request_reason(EXTERNAL_ID) == "END_SESSION"
    assert service.get_codex_status(EXTERNAL_ID)["end_requested"] is True
    # The request asks for a graceful end; it is not a user abort.
    record = make_record(service.control_root)
    record.session_id = EXTERNAL_ID
    assert service._is_stop_requested(record) is False
    assert record.stop_requested is False


def test_unreadable_stop_request_still_counts_as_a_user_stop(service) -> None:
    service._stop_request_path(EXTERNAL_ID).write_text("{not json", encoding="utf-8")
    assert service._stop_request_reason(EXTERNAL_ID) == "USER_ABORT"
    record = make_record(service.control_root)
    record.session_id = EXTERNAL_ID
    assert service._is_stop_requested(record) is True


def test_a_finished_or_unknown_run_is_not_external(service, external_run) -> None:
    external_run.kill()
    external_run.wait()
    assert service._externally_coordinated_run(EXTERNAL_ID) is None
    assert service._externally_coordinated_run("22222222-2222-4333-8444-555555555555") is None


def test_owner_ends_its_conversation_when_another_window_requests_it(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.session_id = EXTERNAL_ID
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    closed = threading.Event()
    session.close = lambda *, force=False: (session.calls.append(("close", force)), closed.set())

    class Process:
        def wait(self, timeout=None):
            if closed.wait(timeout):
                return 0
            raise service_module.subprocess.TimeoutExpired("codex", timeout)

    service._write_stop_request(EXTERNAL_ID, reason="END_SESSION")
    assert service._wait_for_agent(record, Process(), launcher=None) == 0
    assert ("close", False) in session.calls
    assert record.runtime["end_session_requested"] is True
    assert record.stop_requested is False


def test_live_coordinator_recorded_with_the_product_reader_is_not_misjudged_stale() -> None:
    # process_create_time and psutil disagree in float rounding for most
    # processes; a live coordinator must still be recognized as live.
    import os

    from aia import process_create_time

    state = {
        "session": {"status": "RUNNING"},
        "phase": "RUNNING",
        "coordinator": {"pid": os.getpid(), "create_time": process_create_time(os.getpid())},
    }
    result = service_module._runtime_coordinator_reconciliation(state)
    assert result["status"] == "LIVE_MATCH"
    assert result["orphaned"] is False


def test_dead_coordinator_is_still_reported_gone() -> None:
    import subprocess
    import sys

    from aia import process_create_time

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    create_time = process_create_time(child.pid)
    child.wait()
    state = {"session": {"status": "RUNNING"}, "phase": "RUNNING", "coordinator": {"pid": child.pid, "create_time": create_time}}
    del child
    result = service_module._runtime_coordinator_reconciliation(state)
    assert result["orphaned"] is True
