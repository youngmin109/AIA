"""Codex Workbench conversation operations for the application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone, timedelta
import os
import time
from threading import Event
from typing import Any
from uuid import uuid4

from aia.codex_runtime import UnsupportedToolReview

from .codex_app_server import TURN_PERMISSIONS, CodexAppServerError, CodexAppServerSession
from .registry import RunRecord


_AIA_REVIEW_PREFIX = "aia-review-"
# Cross-process request asking the AIA process that owns a conversation to
# end it gracefully rather than abort it.
_END_SESSION_REQUEST = "END_SESSION"


class CodexWorkbench:
    """Serve conversation requests using the owning RunApplicationService."""

    def __init__(
        self,
        service: Any,
        reconcile_runtime: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> None:
        self._service = service
        self._reconcile_runtime = reconcile_runtime

    def _codex_session(self, session_id: str) -> CodexAppServerSession:
        service = self._service
        record = service.registry.get(session_id)
        if record is None:
            external = self._externally_coordinated_run(session_id)
            if external is not None:
                owner = (external.get("coordinator") or {}).get("pid")
                raise CodexAppServerError(
                    f"이 보호 실행은 다른 AIA 창(PID {owner})에서 진행 중입니다. 그 창에서 계속하세요."
                )
            raise KeyError(session_id)
        if record.launch_mode != "codex_app_server":
            raise CodexAppServerError("this run is not using the Codex conversation")
        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            raise CodexAppServerError("Codex conversation is not attached")
        return codex_session

    def get_codex_status(self, session_id: str) -> dict[str, Any]:
        """Return the Workbench conversation state without exposing its content."""

        service = self._service
        detached = {
            "mode": "codex_app_server",
            "status": "NOT_ATTACHED",
            "pid": None,
            "thread_id": None,
            "active_turn_id": None,
            "pending_approvals": [],
            "effective": {},
            "started_at": None,
            "ended_at": None,
            "exit_code": None,
            "error": None,
            "last_sequence": 0,
        }
        record = service.registry.get(session_id)
        if record is None:
            external = self._externally_coordinated_run(session_id)
            if external is not None:
                # The conversation lives in the other AIA process; this one
                # can only show that and forward an end request.
                return {
                    **detached,
                    "mode": external.get("launch_mode", "inherit"),
                    "status": "EXTERNAL",
                    "owner_pid": (external.get("coordinator") or {}).get("pid"),
                    "end_requested": service._stop_request_reason(session_id) == _END_SESSION_REQUEST,
                }
            status = service.get_run_status(session_id)
            ended = status.get("session", {}).get("status") in {"COMPLETED", "ABORTED", "FAILED"}
            return {
                **detached,
                "mode": status.get("launch_mode", "inherit"),
                "status": "EXITED" if ended else "NOT_ATTACHED",
            }
        error = record.runtime.get("codex_app_server_error")
        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            return {**detached, "mode": record.launch_mode, "error": error}
        snapshot = codex_session.snapshot()
        if error:
            snapshot["error"] = error
        with service._tool_review_lock:
            reviews = [
                dict(item["request"])
                for item in record.runtime.get("unsupported_tool_reviews", {}).values()
                if not item["event"].is_set()
            ]
        snapshot["pending_approvals"] = [*snapshot.get("pending_approvals", []), *reviews]
        snapshot["permission_mode"] = record.permission_mode
        return snapshot

    def read_codex_events(self, session_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        service = self._service
        record = service.registry.get(session_id)
        if record is None:
            service.get_run_status(session_id)
            return []
        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            return []
        return codex_session.read_events(after_sequence)

    def wait_codex_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Block until new conversation events exist (used off the event loop)."""

        service = self._service
        record = service.registry.get(session_id)
        if record is None:
            service.get_run_status(session_id)
            # Nothing can arrive here (the run is finished or coordinated by
            # another AIA process); pace the caller's long-poll loop.
            time.sleep(min(timeout, 1.0))
            return []
        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            time.sleep(min(timeout, 0.25))
            return []
        return codex_session.wait_events(after_sequence, timeout=timeout)

    def send_codex_message(self, session_id: str, text: str) -> dict[str, Any]:
        return {**self._codex_session(session_id).send_message(text), "session_id": session_id}

    def interrupt_codex_turn(self, session_id: str) -> dict[str, Any]:
        return {**self._codex_session(session_id).interrupt(), "session_id": session_id}

    def respond_codex_approval(self, session_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        codex_session = self._codex_session(session_id)
        if approval_id.startswith(_AIA_REVIEW_PREFIX):
            return {
                **self._resolve_unsupported_tool_review(session_id, approval_id, decision),
                "session_id": session_id,
            }
        return {**codex_session.respond_approval(approval_id, decision), "session_id": session_id}

    def respond_codex_question(self, session_id: str, question_id: str, answers: Any) -> dict[str, Any]:
        codex_session = self._codex_session(session_id)
        return {**codex_session.respond_question(question_id, answers), "session_id": session_id}

    def respond_codex_elicitation(self, session_id: str, elicitation_id: str, action: str, content: Any) -> dict[str, Any]:
        codex_session = self._codex_session(session_id)
        return {**codex_session.respond_elicitation(elicitation_id, action, content), "session_id": session_id}

    def run_codex_command(self, session_id: str, command: str, argument: Any = None) -> dict[str, Any]:
        """Slash commands that reach Codex: compact, review, goal."""

        codex_session = self._codex_session(session_id)
        if command == "compact":
            result = codex_session.compact()
        elif command == "review":
            result = codex_session.start_review()
        elif command == "goal":
            result = codex_session.set_goal(argument)
        else:
            raise CodexAppServerError("지원하지 않는 명령이에요.")
        return {**result, "command": command, "session_id": session_id}

    def list_codex_connectors(self, session_id: str) -> dict[str, Any]:
        connectors = self._codex_session(session_id).list_connectors()
        record = self._service.registry.get(session_id)
        turned_off = list(record.runtime.get("external_tools_off") or ()) if record is not None else []
        for connector in connectors:
            connector["turned_off_by_aia"] = connector["name"] in turned_off
        # Turned-off plugins and ChatGPT apps leave Codex's list; keep them visible as off.
        listed = {connector["name"] for connector in connectors}
        connectors.extend(
            {"name": name, "status": "disabled", "auth": "unknown", "tool_count": 0, "tools": [], "error": None,
             "turned_off_by_aia": True}
            for name in turned_off if name not in listed
        )
        return {"connectors": connectors, "session_id": session_id}

    def read_codex_diff(self, session_id: str, turn_id: str | None) -> dict[str, Any]:
        return {**self._codex_session(session_id).read_diff(turn_id), "session_id": session_id}

    def set_codex_turn_settings(self, session_id: str, model: Any, effort: Any) -> dict[str, Any]:
        return {**self._codex_session(session_id).set_turn_settings(model, effort), "session_id": session_id}

    def set_codex_permission_mode(self, session_id: str, mode: Any) -> dict[str, Any]:
        """Switch full access (YOLO) or work-folder-only for the next requests.

        Like a permission grant, the run records the choice before Codex hears
        of it, so a full-access request never runs unrecorded.
        """

        if mode not in TURN_PERMISSIONS:
            raise CodexAppServerError("permission mode must be full_access or workspace")
        codex_session = self._codex_session(session_id)
        service = self._service
        record = service.registry.require(session_id)
        previous = (record.permission_mode, record.full_access_used)
        record.permission_mode = mode
        record.full_access_used = record.full_access_used or mode == "full_access"
        try:
            service._persist_runtime_state(record, strict=True)
        except (OSError, ValueError) as error:
            record.permission_mode, record.full_access_used = previous
            raise CodexAppServerError("권한 변경을 기록하지 못해 바꾸지 않았어요. 다시 시도해 주세요.") from error
        return {**codex_session.set_permission_mode(mode), "session_id": session_id}

    def respond_codex_permissions(self, session_id: str, permissions_id: str, decision: str) -> dict[str, Any]:
        """Answer a sandbox-widening request and record a grant on the run."""

        codex_session = self._codex_session(session_id)
        service = self._service
        record = service.registry.require(session_id)

        def record_grant(result: dict[str, Any]) -> None:
            previous = record.permission_grants
            record.permission_grants = [
                *previous,
                {
                    "granted_at": datetime.now(timezone.utc).isoformat(),
                    "scope": decision,
                    "network": result["network"],
                    "filesystem": result["filesystem"],
                    "reason": result["reason"],
                },
            ]
            record.protection_state = "DEGRADED"
            try:
                service._persist_runtime_state(record, strict=True)
            except (OSError, ValueError) as error:
                record.permission_grants = previous
                raise CodexAppServerError("권한 허용 결정을 기록하지 못해 허용하지 않았어요. 다시 시도해 주세요.") from error

        result = codex_session.respond_permissions(permissions_id, decision, before_grant=record_grant)
        return {**result, "session_id": session_id}

    def _resolve_unsupported_tool_review(self, session_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"accept", "acceptForSession", "decline"}:
            raise CodexAppServerError("approval decision is not supported")
        service = self._service
        record = service.registry.get(session_id)
        reviews = record.runtime.get("unsupported_tool_reviews", {}) if record is not None else {}
        with service._tool_review_lock:
            review = reviews.get(approval_id)
            if review is None or review["event"].is_set():
                raise CodexAppServerError("approval request is no longer pending")
            review["decision"] = decision
            review["event"].set()
        return {"accepted": True, "approval_id": approval_id, "decision": decision}

    def review_unsupported_tool(
        self,
        record: RunRecord,
        review: UnsupportedToolReview,
        timeout_seconds: float = 25.0,
    ) -> bool:
        """Ask the Workbench user whether Codex may use an unsupported tool."""

        service = self._service
        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            return False
        with service._tool_review_lock:
            session_allowed = record.runtime.setdefault("unsupported_tools_allowed_for_session", set())
            if review.tool_name in session_allowed:
                allowed_for_session = True
            else:
                allowed_for_session = False
                approval_id = f"{_AIA_REVIEW_PREFIX}{uuid4().hex[:12]}"
                pending = {
                    "event": Event(),
                    "decision": None,
                    "request": {
                        "approval_id": approval_id,
                        "kind": "aia_tool",
                        "tool": review.tool_name,
                        "command": review.input_summary,
                        "cwd": "",
                        "reason": "AIA가 의미를 해석하지 못하는 도구라서 정책으로 판정할 수 없습니다.",
                        "paths": [],
                        "timeout_seconds": timeout_seconds,
                        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)).isoformat(),
                    },
                }
                record.runtime.setdefault("unsupported_tool_reviews", {})[approval_id] = pending
        if allowed_for_session:
            codex_session.post_event(
                {"type": "warning", "message": f"보호 범위 밖 도구 {review.tool_name} · 이 세션 동안 허용됨"}
            )
            return True
        codex_session.post_event({"type": "approval.requested", **pending["request"]})
        decided = pending["event"].wait(timeout_seconds)
        with service._tool_review_lock:
            record.runtime["unsupported_tool_reviews"].pop(approval_id, None)
            decision = pending["decision"] if decided else "timeout"
            if decision == "acceptForSession":
                session_allowed.add(review.tool_name)
            decision_code = {
                "accept": "UNSUPPORTED_TOOL_REVIEW_APPROVED",
                "acceptForSession": "UNSUPPORTED_TOOL_REVIEW_APPROVED",
                "decline": "UNSUPPORTED_TOOL_REVIEW_DECLINED",
                "timeout": "UNSUPPORTED_TOOL_REVIEW_TIMED_OUT",
            }[decision]
            decisions = record.runtime.setdefault("unsupported_tool_review_decisions", [])
            if decision_code not in decisions:
                decisions.append(decision_code)
        codex_session.post_event({"type": "approval.resolved", "approval_id": approval_id, "decision": decision})
        return decision in {"accept", "acceptForSession"}

    def end_codex_session(self, session_id: str) -> dict[str, Any]:
        """Let Codex exit so the run finalizes through the Agent-exited path."""

        service = self._service
        if service.registry.get(session_id) is None and self._externally_coordinated_run(session_id) is not None:
            service._write_stop_request(session_id, reason=_END_SESSION_REQUEST)
            return {"accepted": True, "session_id": session_id, "mode": "requested_owner"}
        self._codex_session(session_id).close(force=False)
        return {"accepted": True, "session_id": session_id, "mode": "closed"}

    def _externally_coordinated_run(self, session_id: str) -> dict[str, Any] | None:
        """Return the runtime state of a run another live AIA process owns."""

        service = self._service
        state = service._read_runtime_state(session_id)
        if state is None:
            return None
        coordinator = state.get("coordinator")
        if not isinstance(coordinator, Mapping) or coordinator.get("pid") == os.getpid():
            return None
        if self._reconcile_runtime(state).get("status") != "LIVE_MATCH":
            return None
        return state
