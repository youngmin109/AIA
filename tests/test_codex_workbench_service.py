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
        return {"mode": "codex_app_server", "status": "READY", "error": None, "last_sequence": 3, "thread_id": "thr-42"}

    def send_message(self, text: str, *, before_permission_send=None) -> dict:
        mode = getattr(self, 'pending_permission', None)
        if mode and before_permission_send:
            before_permission_send(mode)
        self.pending_permission = None
        self.calls.append(("send", text))
        return {"accepted": True, "mode": "start", "turn_id": "turn-1", **({'permission_submitted': mode} if mode else {})}

    def interrupt(self) -> dict:
        self.calls.append(("interrupt",))
        return {"accepted": True, "turn_id": "turn-1"}

    def respond_approval(self, approval_id: str, decision: str) -> dict:
        self.calls.append(("approval", approval_id, decision))
        return {"accepted": True, "approval_id": approval_id, "decision": decision}

    def set_turn_settings(self, model=None, effort=None) -> dict:
        self.calls.append(("settings", model, effort))
        return {"accepted": True, "model": model, "effort": effort}

    def set_permission_mode(self, mode) -> dict:
        self.pending_permission = mode
        self.calls.append(("permission", mode))
        return {"accepted": True, "mode": mode}

    def respond_permissions(self, permissions_id: str, decision: str, *, before_grant=None) -> dict:
        result = {"accepted": True, "permissions_id": permissions_id, "decision": decision, "network": True,
                  "filesystem": [{"access": "write", "target": "C:\\shared", "scope": "outside"}], "reason": "sync"}
        if decision != "decline" and before_grant is not None:
            before_grant(result)
        self.calls.append(("permissions", permissions_id, decision))
        return result

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

    # The user reviews approvals in this mode, even if the Codex config says otherwise.
    assert session.calls == [("open", {"sandbox": "workspace-write", "approval_policy": "on-request", "approvals_reviewer": "user", "model": "gpt-test"})]
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


def test_permission_mode_is_a_codex_conversation_choice_and_defaults_to_work_folder_only() -> None:
    base = {"workspace": ".", "interactive": True, "launch_mode": "codex_app_server"}
    assert CreateRunRequest.from_mapping(base).permission_mode == "workspace"
    assert CreateRunRequest.from_mapping({**base, "permission_mode": "full_access"}).permission_mode == "full_access"
    assert CreateRunRequest.from_mapping({**base, "permission_mode": "auto_review"}).permission_mode == "auto_review"
    with pytest.raises(DTOValidationError, match="permission_mode"):
        CreateRunRequest.from_mapping({**base, "permission_mode": "yolo"})
    with pytest.raises(DTOValidationError, match="auto_review"):
        CreateRunRequest.from_mapping({"workspace": ".", "interactive": True, "permission_mode": "auto_review"})
    with pytest.raises(DTOValidationError, match="full_access"):
        CreateRunRequest.from_mapping({"workspace": ".", "interactive": True, "permission_mode": "full_access"})


def test_full_access_run_opens_without_codex_sandbox_and_is_not_a_protection_failure(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.permission_mode = "full_access"
    session = FakeCodexSession({"model": "m", "approval_policy": "never", "sandbox": "dangerFullAccess"})
    record.runtime["codex_session"] = session

    service._open_codex_conversation(record)

    assert session.calls == [("open", {"sandbox": "danger-full-access", "approval_policy": "never", "approvals_reviewer": "user", "model": "gpt-test"})]
    assert record.full_access_used is True
    # Full access is the user's choice of Codex sandbox, recorded as the
    # CODEX_FULL_ACCESS_USER_SELECTED limitation.  It does not degrade AIA's
    # own Hook, sensors and recovery, so opening leaves the state untouched.
    assert record.protection_state == 'STARTING'
    assert "protection_failure_reason" not in record.runtime
    assert "codex_sandbox_downgraded" not in record.runtime
    assert "codex_approval_policy_downgraded" not in record.runtime


def _exec_record(tmp_path, permission_mode: str) -> RunRecord:
    record = make_record(tmp_path, launch_mode="inherit")
    record.interactive = False
    record.permission_mode = permission_mode
    return record


def test_exec_observation_treats_requested_full_access_as_the_contract(service, tmp_path) -> None:
    from io import BytesIO

    record = _exec_record(tmp_path, "full_access")

    service._capture_codex_execution_observation(
        record, [BytesIO(b""), BytesIO(b"approval: never\nsandbox: danger-full-access\n")]
    )

    assert record.full_access_used is True
    assert "codex_approval_policy_downgraded" not in record.runtime
    assert "codex_sandbox_downgraded" not in record.runtime


def test_exec_observation_still_flags_never_when_the_sandbox_was_requested(service, tmp_path) -> None:
    from io import BytesIO

    record = _exec_record(tmp_path, "workspace")

    service._capture_codex_execution_observation(
        record, [BytesIO(b""), BytesIO(b"approval: never\nsandbox: workspace-write\n")]
    )

    assert record.runtime["codex_approval_policy_downgraded"] is True
    assert record.full_access_used is False


def test_auto_review_run_lets_codex_review_approvals_inside_the_sandbox(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.permission_mode = "auto_review"
    session = FakeCodexSession({"model": "m", "approval_policy": "on-request", "approvals_reviewer": "auto_review", "sandbox": "workspaceWrite"})
    record.runtime["codex_session"] = session

    service._open_codex_conversation(record)

    assert session.calls == [("open", {"sandbox": "workspace-write", "approval_policy": "on-request", "approvals_reviewer": "auto_review", "model": "gpt-test"})]
    assert record.auto_review_used is True and record.full_access_used is False
    assert record.protection_state == 'DEGRADED'
    assert "protection_failure_reason" not in record.runtime


def test_full_access_request_that_codex_applies_more_strictly_is_not_marked_used(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.permission_mode = "full_access"
    record.runtime["codex_session"] = FakeCodexSession({"model": "m", "approval_policy": "on-request", "sandbox": "workspaceWrite"})

    service._open_codex_conversation(record)

    assert record.full_access_used is False
    assert "protection_failure_reason" not in record.runtime


def test_switching_permission_mode_is_recorded_before_codex_hears_of_it(service, tmp_path, monkeypatch) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service.registry.add(record)

    assert service.set_codex_permission_mode("session-1", "full_access")["mode"] == "full_access"
    assert record.permission_mode == "full_access" and record.full_access_used is False
    assert service.get_codex_status("session-1")["permission_mode"] == "full_access"
    # Superseding a choice before a new turn does not claim it was used.
    service.set_codex_permission_mode("session-1", "workspace")
    assert record.permission_mode == "workspace" and record.full_access_used is False
    service.set_codex_permission_mode("session-1", "auto_review")
    assert record.auto_review_used is False
    service.set_codex_permission_mode("session-1", "workspace")
    assert session.calls == [("permission", "full_access"), ("permission", "workspace"), ("permission", "auto_review"), ("permission", "workspace")]
    with pytest.raises(CodexAppServerError):
        service.set_codex_permission_mode("session-1", "yolo")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service, "_persist_runtime_state", fail)
    with pytest.raises(CodexAppServerError, match="기록하지 못해"):
        service.set_codex_permission_mode("session-1", "full_access")
    assert record.permission_mode == "workspace"
    assert session.calls[-1] == ("permission", "workspace")


def test_open_failure_is_recorded_and_lets_codex_exit(service, tmp_path) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession(open_error=CodexAppServerError("no answer"))
    record.runtime["codex_session"] = session

    service._open_codex_conversation(record)

    assert record.runtime["codex_app_server_error"] == "CODEX_APP_SERVER_OPEN_FAILED: no answer"
    assert session.calls[-1] == ("close", True)


def test_mode_exception_is_durable_before_dispatch_and_remains_after_restriction(service, tmp_path):
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime['codex_session'] = session
    record.protection_state = 'ACTIVE_VERIFIED'
    service.registry.add(record)
    service.set_codex_permission_mode(record.session_id, 'full_access')
    assert not record.full_access_used and not record.permission_grants
    original_send = session.send_message
    def inspected_send(text, *, before_permission_send):
        def before(mode):
            before_permission_send(mode)
            saved = service._read_runtime_state(record.session_id)
            assert saved['permission_changes'][-1]['status'] == 'SUBMITTING'
            assert saved['permission_grants'] and saved['protection']['state'] == 'DEGRADED'
        return original_send(text, before_permission_send=before)
    session.send_message = inspected_send
    service.send_codex_message(record.session_id, 'hello')
    assert record.full_access_used
    assert record.permission_changes[-1]['status'] == 'ACKNOWLEDGED'
    assert record.protection_state == 'DEGRADED'
    service.set_codex_permission_mode(record.session_id, 'workspace')
    service.send_codex_message(record.session_id, 'restricted')
    assert record.full_access_used and record.permission_grants
    assert record.protection_state == 'DEGRADED'


def test_mode_submission_write_failure_prevents_dispatch(service, tmp_path, monkeypatch):
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime['codex_session'] = session
    service.registry.add(record)
    service.set_codex_permission_mode(record.session_id, 'full_access')
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(service, '_persist_runtime_state', fail)
    with pytest.raises(CodexAppServerError, match='기록하지 못해'):
        service.send_codex_message(record.session_id, 'never dispatched')
    assert not any(call[0] == 'send' for call in session.calls)
    assert record.permission_changes[-1]['status'] == 'PENDING'
    assert not record.full_access_used and not record.permission_grants


def test_mode_rpc_timeout_remains_unconfirmed_and_degraded(service, tmp_path):
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime['codex_session'] = session
    service.registry.add(record)
    service.set_codex_permission_mode(record.session_id, 'auto_review')
    def timeout(text, *, before_permission_send):
        before_permission_send('auto_review')
        raise CodexAppServerError('timeout')
    session.send_message = timeout
    with pytest.raises(CodexAppServerError, match='timeout'):
        service.send_codex_message(record.session_id, 'unknown result')
    assert record.permission_changes[-1]['status'] == 'UNCONFIRMED'
    assert not record.auto_review_used
    assert record.permission_grants and record.protection_state == 'DEGRADED'
    assert record.permission_changes[-1]['attempts'][0]['status'] == 'UNCONFIRMED'
    service.set_codex_permission_mode(record.session_id, 'workspace')
    assert record.permission_changes[-2]['status'] == 'UNCONFIRMED'


def test_mode_queue_failure_restores_previous_pending_choice(service, tmp_path):
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime['codex_session'] = session
    service.registry.add(record)
    service.set_codex_permission_mode(record.session_id, 'workspace')
    previous = record.permission_changes
    def fail(mode):
        raise CodexAppServerError('not attached')
    session.set_permission_mode = fail
    with pytest.raises(CodexAppServerError):
        service.set_codex_permission_mode(record.session_id, 'full_access')
    assert record.permission_mode == 'workspace'
    assert record.permission_changes == previous
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


def test_granted_permissions_are_recorded_on_the_run_and_declines_are_not(service, tmp_path) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service.registry.add(record)

    service.respond_codex_permissions(record.session_id, "permissions-1", "decline")
    assert record.permission_grants == []
    service.respond_codex_permissions(record.session_id, "permissions-2", "session")

    assert session.calls[-1] == ("permissions", "permissions-2", "session")
    [grant] = record.permission_grants
    assert (grant["scope"], grant["network"], grant["reason"]) == ("session", True, "sync")
    assert grant["filesystem"][0]["scope"] == "outside"
    assert service.get_run_status(record.session_id)["permission_grants"] == [grant]
    assert record.protection_state == "DEGRADED"
    assert service._read_runtime_state(record.session_id)["permission_grants"] == [grant]


def test_failed_permission_persistence_does_not_send_a_grant(service, tmp_path, monkeypatch) -> None:
    record = make_record(tmp_path)
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service.registry.add(record)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service, "_write_runtime_state_payload", fail)
    with pytest.raises(CodexAppServerError, match="기록하지 못해"):
        service.respond_codex_permissions(record.session_id, "permissions-1", "turn")
    assert session.calls == []
    assert record.permission_grants == []
    assert record.protection_state == "DEGRADED"


def test_the_codex_conversation_id_is_kept_for_resuming_but_no_text(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.runtime["codex_session"] = FakeCodexSession()
    service.registry.add(record)
    service._open_codex_conversation(record)
    assert record.codex_thread_id == "thr-42"
    state = service._read_runtime_state(record.session_id)
    assert state["codex_thread_id"] == "thr-42"
    assert service.get_run_status(record.session_id)["codex_thread_id"] == "thr-42"


def test_only_conversations_aia_opened_in_the_same_folder_can_be_resumed(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.codex_thread_id = "thr-42"
    service.registry.add(record)
    service._persist_runtime_state(record)
    assert service._resumable_threads() == [], "a conversation still open in a live run is not offered"
    record.status = "COMPLETED"
    threads = service._resumable_threads()
    assert [(item["thread_id"], item["session_id"]) for item in threads] == [("thr-42", record.session_id)]

    other = tmp_path / "other"
    other.mkdir()
    base = {"interactive": True, "launch_mode": "codex_app_server"}
    monkey_service = service
    monkey_service.require_hook_verification = False
    with pytest.raises(service_module.ApplicationValidationError, match="같은 작업 폴더"):
        service.create_protected_run({**base, "workspace": str(other), "resume_thread_id": "thr-42"})
    with pytest.raises(service_module.ApplicationValidationError, match="같은 작업 폴더"):
        service.create_protected_run({**base, "workspace": str(tmp_path), "resume_thread_id": "thr-unknown"})


def test_resume_thread_id_must_look_like_a_conversation_id() -> None:
    for bad in ("../x", "a b", "", "x" * 101, 5):
        with pytest.raises(DTOValidationError):
            CreateRunRequest.from_mapping({"workspace": ".", "resume_thread_id": bad})


def test_chosen_reasoning_effort_is_applied_once_the_conversation_opens(service, tmp_path) -> None:
    record = make_record(tmp_path)
    record.reasoning_effort = "high"
    session = FakeCodexSession()
    record.runtime["codex_session"] = session
    service._open_codex_conversation(record)
    assert ("settings", "gpt-test", "high") in session.calls


def test_reasoning_effort_in_a_new_run_request_is_a_lowercase_word() -> None:
    request = CreateRunRequest.from_mapping({"workspace": ".", "interactive": True, "launch_mode": "codex_app_server",
                                             "reasoning_effort": "xhigh"})
    assert request.reasoning_effort == "xhigh"
    for bad in ("High", "very high", "x" * 21, 3):
        with pytest.raises(DTOValidationError):
            CreateRunRequest.from_mapping({"workspace": ".", "reasoning_effort": bad})


def test_model_list_is_cached_and_a_failure_hides_the_picker(service, monkeypatch) -> None:
    created = []

    class FakeModelSession:
        def __init__(self, argv, **kwargs):
            created.append(argv)

        def start(self):
            pass

        def list_models(self):
            return [{"model": "gpt-fast", "display_name": "GPT Fast", "efforts": []}]

        def list_permission_profiles(self):
            return [{"id": ":workspace", "allowed": True}, {"id": ":danger-full-access", "allowed": False}]

        def close(self, force=False):
            pass

    monkeypatch.setattr(service_module.CodexAdapter, "discover", lambda self: "codex.exe")
    monkeypatch.setattr(service_module, "CodexAppServerSession", FakeModelSession)
    assert service.list_codex_models()["models"][0]["model"] == "gpt-fast"
    # The Codex app's permission menu comes from Codex's own profiles.
    assert service.list_codex_models()["permission_profiles"][1] == {"id": ":danger-full-access", "allowed": False}
    assert created == [["codex.exe", "app-server"]]

    service._models_cache = None
    monkeypatch.setattr(service_module.CodexAdapter, "discover", lambda self: (_ for _ in ()).throw(RuntimeError("no codex")))
    failed = service.list_codex_models()
    assert failed["models"] == [] and "no codex" in failed["error"]


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


@pytest.mark.parametrize(
    ("decision", "allowed", "recorded"),
    [
        ("accept", True, "UNSUPPORTED_TOOL_REVIEW_APPROVED"),
        ("decline", False, "UNSUPPORTED_TOOL_REVIEW_DECLINED"),
    ],
)
def test_unsupported_tool_review_waits_for_the_users_decision(
    service, review_run, decision, allowed, recorded
) -> None:
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
    assert record.runtime["unsupported_tool_review_decisions"] == [recorded]
    assert session.posted("approval.resolved")[-1] == {"type": "approval.resolved", "approval_id": approval_id, "decision": decision}
    assert service.get_codex_status("session-1")["pending_approvals"] == []
    with pytest.raises(CodexAppServerError):
        service.respond_codex_approval("session-1", approval_id, "accept")


def test_unsupported_tool_review_times_out_as_a_refusal(service, review_run, monkeypatch) -> None:
    record, session = review_run
    monkeypatch.setattr(service_module, "_UNSUPPORTED_TOOL_REVIEW_SECONDS", 0.2)

    assert service._review_unsupported_tool(record, REVIEW) is False
    assert session.posted("approval.resolved")[-1]["decision"] == "timeout"
    assert record.runtime["unsupported_tool_review_decisions"] == ["UNSUPPORTED_TOOL_REVIEW_TIMED_OUT"]
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
