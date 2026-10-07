"""Codex app-server transport for the AIA Workbench.

The Workbench talks to Codex through the documented ``codex app-server`` stdio
JSON-RPC protocol instead of scraping the interactive TUI through a pseudo
terminal.  Codex reports turns, streamed messages, command execution, Hook
runs and approval requests as structured events, so the Workbench never has
to guess Codex state from screen text.

Like the terminal transport it replaces, this module only transports the
conversation.  It does not make policy, attribution, or enforcement
decisions: the protected launcher owns the process identity and the
Hook/File/Process Sensors remain the authoritative observation path.
Conversation content is held in a bounded in-memory buffer and is never
persisted into the Evidence Bundle or the Result Bundle.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Condition, Event, Lock, Thread, current_thread
import time
from typing import Any, Mapping, Sequence


class CodexAppServerError(RuntimeError):
    """Raised when the Codex app-server session cannot be started or used."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- Windows console encoding --------------------------------------------------
#
# Codex runs model commands through pipes and guesses the encoding of output
# that is not UTF-8.  With no console (CREATE_NO_WINDOW) Windows PowerShell and
# cmd write the legacy code page (cp949 on Korean Windows), and short or mixed
# output such as a Korean file name is guessed wrong, so both the Workbench and
# the model see broken text.  The app-server therefore gets a hidden console
# whose code page is switched to UTF-8; the commands Codex starts inherit it.

_UTF8_CODE_PAGE = 65001
_ERROR_ACCESS_DENIED = 5
_CONSOLE_ATTACH_LOCK = Lock()
# The child's console appears a moment after spawn, later on a busy machine.
# Waiting longer costs nothing when it attaches quickly.
_CONSOLE_ATTACH_SECONDS = 5.0
_UTF8_CONSOLE_HELPER = (
    "import ctypes, sys, time\n"
    "k = ctypes.WinDLL('kernel32')\n"
    f"deadline = time.monotonic() + {_CONSOLE_ATTACH_SECONDS}\n"
    "while not k.AttachConsole(int(sys.argv[1])):\n"
    "    if time.monotonic() >= deadline:\n"
    "        sys.exit(2)\n"
    "    time.sleep(0.05)\n"
    "ok = k.SetConsoleOutputCP(65001) and k.SetConsoleCP(65001)\n"
    "sys.exit(0 if ok else 3)\n"
)
_HELPER_EXIT_REASONS = {2: "HELPER_ATTACH_TIMEOUT", 3: "HELPER_SET_CODE_PAGE_FAILED"}


def _hidden_console_kwargs() -> dict[str, Any]:
    startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    startupinfo.wShowWindow = 0  # SW_HIDE
    return {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startupinfo}  # type: ignore[attr-defined]


def _python_helper_executable() -> str | None:
    for candidate in (getattr(sys, "_base_executable", None), sys.executable):
        if candidate and Path(candidate).name.casefold() in {"python.exe", "pythonw.exe"}:
            return str(candidate)
    return None


def _switch_console_to_utf8(pid: int) -> bool:
    """Set the UTF-8 code page on the console owned by process *pid*."""

    return _switch_console_to_utf8_with_reason(pid)[0]


def _switch_console_to_utf8_with_reason(pid: int) -> tuple[bool, str | None]:
    """Like _switch_console_to_utf8, plus a short reason when it fails."""

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # The child's console is created asynchronously right after spawn;
    # retry briefly until it can be attached.
    deadline = time.monotonic() + _CONSOLE_ATTACH_SECONDS
    while True:
        with _CONSOLE_ATTACH_LOCK:
            # The packaged desktop app has no console of its own and can
            # attach to the child's console for the few calls needed.
            if kernel32.AttachConsole(pid):
                try:
                    switched = bool(
                        kernel32.SetConsoleOutputCP(_UTF8_CODE_PAGE)
                        and kernel32.SetConsoleCP(_UTF8_CODE_PAGE)
                    )
                    return switched, None if switched else "SET_CODE_PAGE_FAILED"
                finally:
                    kernel32.FreeConsole()
            error = ctypes.get_last_error()
        if error == _ERROR_ACCESS_DENIED or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if error != _ERROR_ACCESS_DENIED:
        return False, f"ATTACH_TIMEOUT:{error}"
    # A source-tree server already owns a console; detaching from it would
    # break its logging, so a console-less helper process does the switch.
    # DETACHED_PROCESS (not CREATE_NO_WINDOW, which still allocates a hidden
    # console) leaves the helper free to attach to the child's console.
    helper = _python_helper_executable()
    if helper is None:
        return False, "HELPER_UNAVAILABLE"
    try:
        completed = subprocess.run(
            [helper, "-c", _UTF8_CONSOLE_HELPER, str(pid)],
            creationflags=subprocess.DETACHED_PROCESS,  # type: ignore[attr-defined]
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_CONSOLE_ATTACH_SECONDS + 10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "HELPER_TIMEOUT"
    except OSError:
        return False, "HELPER_START_FAILED"
    if completed.returncode == 0:
        return True, None
    return False, _HELPER_EXIT_REASONS.get(completed.returncode, f"HELPER_EXIT:{completed.returncode}")


# Server requests that the Workbench answers through the approval dialog.
_APPROVAL_REQUESTS = {
    "item/commandExecution/requestApproval": "command",
    "item/fileChange/requestApproval": "file_change",
}
APPROVAL_DECISIONS = frozenset({"accept", "acceptForSession", "decline", "cancel"})
# Codex asking the user directly (experimental in the app-server protocol).
_QUESTION_REQUEST = "item/tool/requestUserInput"
_MAX_QUESTIONS = 10
_MAX_ANSWER_CHARS = 4_000
# An MCP server asking the user for input through Codex.
_ELICITATION_REQUEST = "mcpServer/elicitation/request"
ELICITATION_ACTIONS = frozenset({"accept", "decline", "cancel"})
_MAX_ELICITATION_FIELDS = 20
# A JSON-RPC "method not found" reply lets Codex continue instead of waiting
# forever on a request the Workbench cannot present.
_UNSUPPORTED_REQUEST_CODE = -32601
_PROTECTED_SANDBOXES = frozenset({"read-only", "workspace-write"})
_PROTECTED_APPROVAL_POLICIES = frozenset({"on-request", "on-failure", "untrusted"})


def _text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _user_message_text(item: Mapping[str, Any]) -> str:
    parts = []
    for entry in item.get("content") or ():
        if isinstance(entry, Mapping) and entry.get("type") == "text":
            parts.append(_text_of(entry.get("text")))
    return "".join(parts)


def _parse_questions(params: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Keep the fields the Workbench renders; ``None`` when the shape is unknown.

    The request is experimental, so anything unexpected falls back to the
    unsupported reply instead of a half-rendered question.
    """

    questions = params.get("questions")
    if not isinstance(questions, list) or not 0 < len(questions) <= _MAX_QUESTIONS:
        return None
    parsed: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, Mapping):
            return None
        question_id, text = question.get("id"), question.get("question")
        if not isinstance(question_id, str) or not question_id or not isinstance(text, str):
            return None
        options = question.get("options") or []
        if not isinstance(options, list) or any(
            not isinstance(option, Mapping) or not isinstance(option.get("label"), str) for option in options
        ):
            return None
        parsed.append(
            {
                "id": question_id,
                "header": _text_of(question.get("header")),
                "question": text,
                "options": [
                    {"label": option["label"], "description": _text_of(option.get("description"))}
                    for option in options
                ],
                "allow_other": bool(question.get("isOther")),
                "secret": bool(question.get("isSecret")),
            }
        )
    return parsed


def _elicitation_options(schema: Mapping[str, Any]) -> list[dict[str, str]] | None:
    """Options of an enum field in any of the MCP enum spellings."""

    items = schema.get("items") if schema.get("type") == "array" else schema
    if not isinstance(items, Mapping):
        return None
    titled = items.get("oneOf") or items.get("anyOf")
    if isinstance(titled, list):
        options = [
            {"value": item["const"], "label": _text_of(item.get("title")) or item["const"]}
            for item in titled
            if isinstance(item, Mapping) and isinstance(item.get("const"), str)
        ]
        return options if len(options) == len(titled) else None
    values = items.get("enum")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return None
    names = schema.get("enumNames")
    labels = names if isinstance(names, list) and len(names) == len(values) else values
    return [{"value": value, "label": _text_of(label) or value} for value, label in zip(values, labels)]


def _elicitation_field(name: str, schema: Any, required: bool) -> dict[str, Any] | None:
    """One simple form field, or ``None`` when the Workbench cannot render it."""

    if not isinstance(schema, Mapping):
        return None
    field: dict[str, Any] = {
        "name": name,
        "title": _text_of(schema.get("title")) or name,
        "description": _text_of(schema.get("description")),
        "required": required,
        "default": schema.get("default"),
    }
    kind = schema.get("type")
    if kind == "array":
        options = _elicitation_options(schema)
        return {**field, "kind": "multi", "options": options} if options else None
    if kind == "string" and ("enum" in schema or "oneOf" in schema or "anyOf" in schema):
        options = _elicitation_options(schema)
        return {**field, "kind": "select", "options": options} if options else None
    if kind == "string":
        return {**field, "kind": "text", "format": schema.get("format")}
    if kind in {"number", "integer"}:
        return {**field, "kind": kind, "minimum": schema.get("minimum"), "maximum": schema.get("maximum")}
    if kind == "boolean":
        return {**field, "kind": "boolean"}
    return None


def _parse_elicitation(params: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize an MCP input request; ``supported`` is False for forms the
    Workbench cannot draw, which can then only be declined or cancelled."""

    server = params.get("serverName")
    mode = params.get("mode")
    message = params.get("message")
    if not isinstance(server, str) or not isinstance(mode, str) or not isinstance(message, str):
        return None
    request: dict[str, Any] = {
        "server": server,
        "mode": mode,
        "message": message,
        "fields": [],
        "url": None,
        "url_host": None,
        "supported": False,
    }
    if mode == "url":
        url = params.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is not None and parsed.scheme in {"http", "https"} and parsed.hostname:
            request.update({"url": url, "url_host": parsed.hostname, "supported": True})
        return request
    schema = params.get("requestedSchema")
    if mode != "form" or not isinstance(schema, Mapping):
        return request
    properties = schema.get("properties")
    required = schema.get("required") or []
    if not isinstance(properties, Mapping) or len(properties) > _MAX_ELICITATION_FIELDS or not isinstance(required, list):
        return request
    fields = [_elicitation_field(str(name), item, name in required) for name, item in properties.items()]
    if all(field is not None for field in fields):
        request.update({"fields": fields, "supported": True})
    return request


def _elicitation_value(field: Mapping[str, Any], value: Any) -> Any:
    """Validate one submitted value against its field; raises on mismatch."""

    kind = field["kind"]
    allowed = {option["value"] for option in field.get("options") or ()}
    if kind == "text" and isinstance(value, str) and len(value) <= _MAX_ANSWER_CHARS:
        return value
    if kind == "boolean" and isinstance(value, bool):
        return value
    if kind in {"number", "integer"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        if kind == "integer" and float(value) != int(value):
            raise CodexAppServerError("answers do not match the request")
        return int(value) if kind == "integer" else value
    if kind == "select" and isinstance(value, str) and value in allowed:
        return value
    if kind == "multi" and isinstance(value, list) and all(isinstance(item, str) and item in allowed for item in value):
        return list(value)
    raise CodexAppServerError("answers do not match the request")


def _command_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return " ".join(str(part) for part in value)
    return ""


def _change_paths(item: Mapping[str, Any]) -> list[str]:
    return [
        str(change.get("path"))
        for change in item.get("changes") or ()
        if isinstance(change, Mapping) and change.get("path")
    ]


def normalize_notification(method: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate one Codex notification into a Workbench event.

    Only the fields the Workbench renders are kept.  Unknown notifications
    return ``None`` so a newer Codex release with additional events keeps
    working without a Workbench change.
    """

    if method == "turn/started":
        turn = params.get("turn") or {}
        return {"type": "turn.started", "turn_id": turn.get("id")}
    if method == "turn/completed":
        turn = params.get("turn") or {}
        error = turn.get("error") or {}
        return {
            "type": "turn.completed",
            "turn_id": turn.get("id"),
            "status": turn.get("status"),
            "error": _text_of(error.get("message")) or None,
            "duration_ms": turn.get("durationMs"),
        }
    if method == "item/agentMessage/delta":
        return {"type": "message.delta", "item_id": params.get("itemId"), "text": _text_of(params.get("delta"))}
    if method == "item/commandExecution/outputDelta":
        return {"type": "command.output", "item_id": params.get("itemId"), "text": _text_of(params.get("delta"))}
    if method == "item/reasoning/summaryTextDelta":
        return {"type": "reasoning.delta", "item_id": params.get("itemId"), "text": _text_of(params.get("delta"))}
    if method in {"item/started", "item/completed"}:
        return _normalize_item(method == "item/started", params.get("item") or {})
    if method in {"hook/started", "hook/completed"}:
        run = params.get("run") or {}
        return {
            "type": "hook",
            "phase": "started" if method == "hook/started" else "completed",
            "turn_id": params.get("turnId"),
            "hook_run_id": run.get("id"),
            "event_name": run.get("eventName"),
            "status": run.get("status"),
            "duration_ms": run.get("durationMs"),
        }
    if method == "error":
        error = params.get("error") or {}
        return {
            "type": "error",
            "message": _text_of(error.get("message")) or "Codex reported an error",
            "will_retry": bool(params.get("willRetry")),
        }
    if method in {"warning", "configWarning", "deprecationNotice", "guardianWarning"}:
        message = params.get("message") or params.get("summary") or params.get("details")
        return {"type": "warning", "message": _text_of(message) or method}
    return None


def _normalize_item(started: bool, item: Mapping[str, Any]) -> dict[str, Any] | None:
    item_type = item.get("type")
    item_id = item.get("id")
    if item_type == "userMessage":
        if not started:
            return None
        return {"type": "user_message", "item_id": item_id, "text": _user_message_text(item)}
    if item_type == "agentMessage":
        if started:
            return {"type": "message.started", "item_id": item_id}
        return {"type": "message.completed", "item_id": item_id, "text": _text_of(item.get("text"))}
    if item_type == "commandExecution":
        if started:
            return {
                "type": "command.started",
                "item_id": item_id,
                "command": _command_text(item.get("command")),
                "cwd": _text_of(item.get("cwd")),
            }
        return {
            "type": "command.completed",
            "item_id": item_id,
            "status": item.get("status"),
            "exit_code": item.get("exitCode"),
            "duration_ms": item.get("durationMs"),
        }
    if item_type == "fileChange":
        return {
            "type": "file_change.started" if started else "file_change.completed",
            "item_id": item_id,
            "status": item.get("status"),
            "paths": _change_paths(item),
        }
    if item_type == "reasoning":
        return {"type": "reasoning.started" if started else "reasoning.completed", "item_id": item_id}
    if item_type in {"mcpToolCall", "dynamicToolCall", "webSearch"}:
        tool = item.get("tool") or item.get("query") or item_type
        return {
            "type": "tool.started" if started else "tool.completed",
            "item_id": item_id,
            "tool": _text_of(tool) or str(item_type),
            "status": item.get("status"),
        }
    return None


class CodexAppServerSession:
    """Run one ``codex app-server`` process for one Workbench conversation."""

    MAX_INPUT_CHARS = 32_000
    MAX_EVENTS = 4_000
    MAX_EVENT_TEXT_CHARS = 1_000_000
    REQUEST_TIMEOUT_SECONDS = 30.0
    CLOSE_TIMEOUT_SECONDS = 5.0
    STDERR_TAIL_LINES = 40

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str,
        env: Mapping[str, str],
        client_version: str = "0",
    ) -> None:
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise CodexAppServerError("app-server argv must contain non-empty strings")
        self.argv = tuple(argv)
        self.cwd = Path(cwd).expanduser().resolve(strict=False)
        self.env = dict(env)
        self.client_version = client_version
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()
        self._write_lock = Lock()
        self._events_changed = Condition(self._lock)
        self._events: deque[dict[str, Any]] = deque()
        self._event_text_chars = 0
        self._next_sequence = 1
        self._next_request_id = 1
        self._pending_requests: dict[int, dict[str, Any]] = {}
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._next_approval = 1
        self._pending_questions: dict[str, dict[str, Any]] = {}
        self._next_question = 1
        self._pending_elicitations: dict[str, dict[str, Any]] = {}
        self._next_elicitation = 1
        self._stderr_tail: deque[str] = deque(maxlen=self.STDERR_TAIL_LINES)
        self._readers: list[Thread] = []
        self._status = "NOT_STARTED"
        self._thread_id: str | None = None
        self._active_turn_id: str | None = None
        self._completed_turns: deque[str] = deque(maxlen=64)
        self._change_paths: dict[str, list[str]] = {}
        self._effective: dict[str, Any] = {}
        self._error: str | None = None
        self._console_utf8: bool | None = None
        self._console_utf8_error: str | None = None
        self._closing = False
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None

    # -- process lifecycle -------------------------------------------------

    @property
    def process_handle(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise CodexAppServerError("app-server process has not started")
        return self._process

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                raise CodexAppServerError("app-server session is already started")
        kwargs: dict[str, Any] = {}
        env = dict(self.env)
        if os.name == "nt":
            kwargs.update(_hidden_console_kwargs())
            # Python tools (and the packaged Hook runtime) write UTF-8 to
            # pipes instead of the legacy code page.  An explicit user value
            # is kept.
            env.setdefault("PYTHONUTF8", "1")
        try:
            process = subprocess.Popen(
                list(self.argv),
                cwd=str(self.cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )
        except OSError as error:
            raise CodexAppServerError(f"Codex app-server start failed: {type(error).__name__}") from error
        console_utf8: bool | None = None
        console_utf8_error: str | None = None
        if os.name == "nt":
            console_utf8, console_utf8_error = _switch_console_to_utf8_with_reason(process.pid)
        with self._lock:
            self._process = process
            self._status = "STARTING"
            self._started_at = _now()
            self._console_utf8 = console_utf8
            self._console_utf8_error = console_utf8_error
        for target, name in ((self._read_stdout, "stdout"), (self._read_stderr, "stderr")):
            reader = Thread(target=target, name=f"aia-codex-app-server-{name}-{process.pid}", daemon=True)
            self._readers.append(reader)
            reader.start()

    def open(
        self,
        *,
        sandbox: str = "workspace-write",
        approval_policy: str = "on-request",
        model: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Initialize the protocol and start the Workbench thread.

        Returns the sandbox and approval policy Codex actually applied so the
        caller can record a downgrade instead of inferring it from output.
        """

        if sandbox not in _PROTECTED_SANDBOXES:
            raise CodexAppServerError("sandbox is not allowed for protected Workbench runs")
        if approval_policy not in _PROTECTED_APPROVAL_POLICIES:
            raise CodexAppServerError("approval policy is not allowed for protected Workbench runs")
        timeout = self.REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
        self._request(
            "initialize",
            {"clientInfo": {"name": "aia-workbench", "title": "AIA Workbench", "version": self.client_version}},
            timeout=timeout,
        )
        self._notify("initialized")
        params: dict[str, Any] = {
            "cwd": str(self.cwd),
            "sandbox": sandbox,
            "approvalPolicy": approval_policy,
        }
        if model:
            params["model"] = model
        result = self._request("thread/start", params, timeout=timeout)
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAppServerError("Codex app-server did not return a thread id")
        sandbox_view = result.get("sandbox")
        effective_sandbox = sandbox_view.get("type") if isinstance(sandbox_view, Mapping) else sandbox_view
        effective = {
            "model": result.get("model"),
            "approval_policy": result.get("approvalPolicy"),
            "sandbox": effective_sandbox,
        }
        with self._lock:
            self._thread_id = thread_id
            self._effective = effective
            if self._status == "STARTING":
                self._status = "READY"
        self._append_event({"type": "session.ready", **effective})
        return dict(effective)

    def close(self, *, force: bool = False) -> None:
        """End the conversation and let the app-server exit.

        A graceful close interrupts an active turn, cancels unanswered
        approvals, and closes stdin so Codex exits on its own; the protected
        run then finalizes through the normal Agent-exited path.
        """

        with self._lock:
            process = self._process
            already_closing = self._closing
            self._closing = True
            if self._status in {"STARTING", "READY", "WORKING"}:
                self._status = "CLOSING"
            thread_id = self._thread_id
            turn_id = self._active_turn_id
            approvals = list(self._pending_approvals.items())
            self._pending_approvals.clear()
            questions = list(self._pending_questions.items())
            self._pending_questions.clear()
            elicitations = list(self._pending_elicitations.items())
            self._pending_elicitations.clear()
        if process is None:
            return
        if not force and not already_closing:
            for approval_id, approval in approvals:
                self._respond(approval["request_id"], {"decision": "cancel"})
                self._append_event({"type": "approval.resolved", "approval_id": approval_id, "decision": "cancel"})
            for question_id, question in questions:
                self._respond(question["request_id"], {"answers": {}})
                self._append_event({"type": "question.resolved", "question_id": question_id, "reason": "cancel"})
            for elicitation_id, elicitation in elicitations:
                self._respond(elicitation["request_id"], {"action": "cancel"})
                self._append_event({"type": "elicitation.resolved", "elicitation_id": elicitation_id, "action": "cancel"})
            if thread_id is not None and turn_id is not None and process.poll() is None:
                try:
                    self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=2.0)
                except CodexAppServerError:
                    pass
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=0.1 if force else self.CLOSE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=self.CLOSE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        for reader in self._readers:
            if reader is not current_thread():
                reader.join(timeout=1.0)

    # -- conversation ------------------------------------------------------

    def send_message(self, text: str) -> dict[str, Any]:
        """Start a turn, or steer the active turn with additional input."""

        if not isinstance(text, str) or not text.strip() or len(text) > self.MAX_INPUT_CHARS:
            raise CodexAppServerError("message is empty or too large")
        thread_id, turn_id = self._require_thread()
        user_input = [{"type": "text", "text": text}]
        if turn_id is not None:
            self._request(
                "turn/steer",
                {"threadId": thread_id, "expectedTurnId": turn_id, "input": user_input},
            )
            return {"accepted": True, "mode": "steer", "turn_id": turn_id}
        result = self._request("turn/start", {"threadId": thread_id, "input": user_input})
        new_turn_id = (result.get("turn") or {}).get("id")
        with self._lock:
            # turn/started and even turn/completed can arrive before this
            # response; never resurrect a turn Codex already finished.
            if (
                isinstance(new_turn_id, str)
                and self._status == "READY"
                and new_turn_id not in self._completed_turns
            ):
                self._active_turn_id = new_turn_id
                self._status = "WORKING"
        return {"accepted": True, "mode": "start", "turn_id": new_turn_id}

    def interrupt(self, *, timeout: float | None = None) -> dict[str, Any]:
        thread_id, turn_id = self._require_thread()
        if turn_id is None:
            return {"accepted": False, "reason": "NO_ACTIVE_TURN"}
        self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=timeout)
        return {"accepted": True, "turn_id": turn_id}

    def respond_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        if decision not in APPROVAL_DECISIONS:
            raise CodexAppServerError("approval decision is not supported")
        with self._lock:
            approval = self._pending_approvals.pop(approval_id, None)
        if approval is None:
            raise CodexAppServerError("approval request is no longer pending")
        self._respond(approval["request_id"], {"decision": decision})
        self._append_event({"type": "approval.resolved", "approval_id": approval_id, "decision": decision})
        return {"accepted": True, "approval_id": approval_id, "decision": decision}

    def respond_question(self, question_id: str, answers: Any) -> dict[str, Any]:
        """Send the user's answers; an empty mapping skips the question.

        Secret answers reach Codex only: the event keeps no copy of them.
        """

        if not isinstance(answers, Mapping):
            raise CodexAppServerError("answers must be an object")
        with self._lock:
            question = self._pending_questions.get(question_id)
            if question is None:
                raise CodexAppServerError("question is no longer pending")
            known = {item["id"]: item for item in question["questions"]}
            cleaned: dict[str, list[str]] = {}
            for key, values in answers.items():
                if key not in known or not isinstance(values, list) or not values or any(
                    not isinstance(value, str) or not value.strip() or len(value) > _MAX_ANSWER_CHARS
                    for value in values
                ):
                    raise CodexAppServerError("answers do not match the question")
                cleaned[key] = list(values)
            del self._pending_questions[question_id]
        self._respond(
            question["request_id"],
            {"answers": {key: {"answers": values} for key, values in cleaned.items()}},
        )
        self._append_event(
            {
                "type": "question.answered",
                "question_id": question_id,
                "skipped": not cleaned,
                "answers": {key: None if known[key]["secret"] else values for key, values in cleaned.items()},
            }
        )
        return {"accepted": True, "question_id": question_id, "skipped": not cleaned}

    def respond_elicitation(self, elicitation_id: str, action: str, content: Any = None) -> dict[str, Any]:
        """Answer an MCP input request.  Submitted values reach Codex only."""

        if action not in ELICITATION_ACTIONS:
            raise CodexAppServerError("elicitation action is not supported")
        with self._lock:
            elicitation = self._pending_elicitations.get(elicitation_id)
            if elicitation is None:
                raise CodexAppServerError("input request is no longer pending")
            result: dict[str, Any] = {"action": action}
            if action == "accept":
                if not elicitation["supported"]:
                    raise CodexAppServerError("this input request can only be declined")
                if elicitation["mode"] == "form":
                    if not isinstance(content, Mapping):
                        raise CodexAppServerError("answers do not match the request")
                    fields = {field["name"]: field for field in elicitation["fields"]}
                    if any(key not in fields for key in content) or any(
                        field["required"] and name not in content for name, field in fields.items()
                    ):
                        raise CodexAppServerError("answers do not match the request")
                    result["content"] = {key: _elicitation_value(fields[key], value) for key, value in content.items()}
            del self._pending_elicitations[elicitation_id]
        self._respond(elicitation["request_id"], result)
        self._append_event({"type": "elicitation.resolved", "elicitation_id": elicitation_id, "action": action})
        return {"accepted": True, "elicitation_id": elicitation_id, "action": action}

    # -- event buffer ------------------------------------------------------

    def read_events(self, after_sequence: int = 0) -> list[dict[str, Any]]:
        """Read buffered events without consuming them (replayable per viewer)."""

        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise CodexAppServerError("after_sequence must be a non-negative integer")
        with self._lock:
            return self._events_after(after_sequence)

    def wait_events(self, after_sequence: int = 0, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Block until events newer than ``after_sequence`` exist or the session ends."""

        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            while True:
                events = self._events_after(after_sequence)
                if events or self._status in {"EXITED", "FAILED"}:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._events_changed.wait(timeout=remaining)

    def _events_after(self, after_sequence: int) -> list[dict[str, Any]]:
        if not self._events or self._events[-1]["sequence"] <= after_sequence:
            return []
        newest_first: list[dict[str, Any]] = []
        for event in reversed(self._events):
            if event["sequence"] <= after_sequence:
                break
            newest_first.append(event)
        return list(reversed(newest_first))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            pending = [
                {key: value for key, value in approval.items() if key != "request_id"}
                for approval in self._pending_approvals.values()
            ]
            questions = [
                {key: value for key, value in question.items() if key != "request_id"}
                for question in self._pending_questions.values()
            ]
            elicitations = [
                {key: value for key, value in elicitation.items() if key != "request_id"}
                for elicitation in self._pending_elicitations.values()
            ]
            snapshot = {
                "mode": "codex_app_server",
                "status": self._status,
                "pid": process.pid if process is not None else None,
                "thread_id": self._thread_id,
                "active_turn_id": self._active_turn_id,
                "pending_approvals": pending,
                "pending_questions": questions,
                "pending_elicitations": elicitations,
                "effective": dict(self._effective),
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "ended_at": self._ended_at.isoformat() if self._ended_at else None,
                "exit_code": process.poll() if process is not None else None,
                "error": self._error,
                "console_utf8": self._console_utf8,
                "console_utf8_error": self._console_utf8_error,
                "last_sequence": self._events[-1]["sequence"] if self._events else 0,
            }
        return snapshot

    def post_event(self, event: Mapping[str, Any]) -> None:
        """Add a Workbench-originated event (for example an AIA review) to
        the conversation stream so every viewer sees it in order."""

        if not isinstance(event.get("type"), str):
            raise CodexAppServerError("event type is required")
        self._append_event(dict(event))

    def _append_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._append_event_locked(event)

    def _append_event_locked(self, event: dict[str, Any]) -> None:
        stored = {"sequence": self._next_sequence, "recorded_at": _now().isoformat(), **event}
        self._next_sequence += 1
        self._events.append(stored)
        self._event_text_chars += len(_text_of(stored.get("text")))
        while len(self._events) > self.MAX_EVENTS or self._event_text_chars > self.MAX_EVENT_TEXT_CHARS:
            removed = self._events.popleft()
            self._event_text_chars -= len(_text_of(removed.get("text")))
        self._events_changed.notify_all()

    # -- JSON-RPC ----------------------------------------------------------

    def _require_thread(self) -> tuple[str, str | None]:
        with self._lock:
            if self._status in {"EXITED", "FAILED", "CLOSING"} or self._thread_id is None:
                raise CodexAppServerError("Codex conversation is not available")
            return self._thread_id, self._active_turn_id

    def _write(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise CodexAppServerError("app-server process has not started")
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                process.stdin.write(line)
                process.stdin.flush()
            except (OSError, ValueError) as error:
                raise CodexAppServerError("Codex app-server input failed") from error

    def _notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        self._write(message)

    def _respond(self, request_id: Any, result: Mapping[str, Any] | None = None, *, error: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"id": request_id}
        if error is not None:
            message["error"] = dict(error)
        else:
            message["result"] = dict(result or {})
        try:
            self._write(message)
        except CodexAppServerError:
            pass

    def _request(self, method: str, params: Mapping[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        if current_thread() in self._readers:
            raise CodexAppServerError("requests cannot be issued from the reader thread")
        done = Event()
        with self._lock:
            if self._status in {"EXITED", "FAILED"}:
                raise CodexAppServerError("Codex app-server is not running")
            request_id = self._next_request_id
            self._next_request_id += 1
            slot: dict[str, Any] = {"done": done}
            self._pending_requests[request_id] = slot
        try:
            self._write({"id": request_id, "method": method, "params": dict(params)})
            if not done.wait(self.REQUEST_TIMEOUT_SECONDS if timeout is None else timeout):
                raise CodexAppServerError(f"Codex app-server did not answer {method}")
        finally:
            with self._lock:
                self._pending_requests.pop(request_id, None)
        if "error" in slot:
            error = slot["error"] if isinstance(slot["error"], Mapping) else {}
            raise CodexAppServerError(_text_of(error.get("message")) or f"Codex app-server rejected {method}")
        result = slot.get("result")
        return dict(result) if isinstance(result, Mapping) else {}

    # -- readers -----------------------------------------------------------

    def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            for raw in process.stdout:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        except (OSError, ValueError):
            pass
        exit_code = process.wait()
        with self._lock:
            unexpected = not self._closing
            self._status = "FAILED" if unexpected and exit_code != 0 else "EXITED"
            if unexpected and self._error is None:
                self._error = "CODEX_APP_SERVER_EXITED"
            self._active_turn_id = None
            self._ended_at = _now()
            for slot in self._pending_requests.values():
                slot["error"] = {"message": "Codex app-server exited"}
                slot["done"].set()
            self._pending_approvals.clear()
            self._pending_questions.clear()
            self._pending_elicitations.clear()
            self._append_event_locked({"type": "session.exited", "exit_code": exit_code, "unexpected": unexpected})

    def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        try:
            for raw in process.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    with self._lock:
                        self._stderr_tail.append(line[:500])
        except (OSError, ValueError):
            pass

    def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if "id" in message and method is None:
            with self._lock:
                slot = self._pending_requests.get(message.get("id"))
                if slot is not None:
                    if "error" in message:
                        slot["error"] = message["error"]
                    else:
                        slot["result"] = message.get("result")
                    slot["done"].set()
            return
        if not isinstance(method, str):
            return
        params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
        if "id" in message:
            self._handle_server_request(message["id"], method, params)
            return
        self._handle_notification(method, params)

    def _handle_server_request(self, request_id: Any, method: str, params: Mapping[str, Any]) -> None:
        if method == _QUESTION_REQUEST:
            questions = _parse_questions(params)
            if questions is not None:
                self._open_question(request_id, params, questions)
                return
        if method == _ELICITATION_REQUEST:
            elicitation = _parse_elicitation(params)
            if elicitation is not None:
                self._open_elicitation(request_id, params, elicitation)
                return
        kind = _APPROVAL_REQUESTS.get(method)
        if kind is None:
            self._respond(
                request_id,
                error={"code": _UNSUPPORTED_REQUEST_CODE, "message": f"AIA Workbench does not support {method}"},
            )
            self._append_event({"type": "warning", "message": f"Codex 요청 {method}은 Workbench에서 지원하지 않아 거절했습니다."})
            return
        with self._lock:
            approval_id = f"approval-{self._next_approval}"
            self._next_approval += 1
            approval = {
                "approval_id": approval_id,
                "request_id": request_id,
                "kind": kind,
                "item_id": params.get("itemId"),
                "turn_id": params.get("turnId"),
                "command": _command_text(params.get("command")),
                "cwd": _text_of(params.get("cwd")),
                "reason": _text_of(params.get("reason")),
                "paths": list(self._change_paths.get(str(params.get("itemId")), ())),
            }
            self._pending_approvals[approval_id] = approval
            self._append_event_locked(
                {"type": "approval.requested", **{key: value for key, value in approval.items() if key != "request_id"}}
            )

    def _open_question(self, request_id: Any, params: Mapping[str, Any], questions: list[dict[str, Any]]) -> None:
        auto_ms = params.get("autoResolutionMs")
        auto_resolve_at = (
            (_now() + timedelta(milliseconds=auto_ms)).isoformat()
            if isinstance(auto_ms, int) and not isinstance(auto_ms, bool) and auto_ms > 0
            else None
        )
        with self._lock:
            question_id = f"question-{self._next_question}"
            self._next_question += 1
            question = {
                "question_id": question_id,
                "request_id": request_id,
                "item_id": params.get("itemId"),
                "turn_id": params.get("turnId"),
                "questions": questions,
                "auto_resolve_at": auto_resolve_at,
            }
            self._pending_questions[question_id] = question
            self._append_event_locked(
                {"type": "question.requested", **{key: value for key, value in question.items() if key != "request_id"}}
            )

    def _open_elicitation(self, request_id: Any, params: Mapping[str, Any], elicitation: dict[str, Any]) -> None:
        with self._lock:
            elicitation_id = f"elicitation-{self._next_elicitation}"
            self._next_elicitation += 1
            pending = {
                "elicitation_id": elicitation_id,
                "request_id": request_id,
                "turn_id": params.get("turnId"),
                **elicitation,
            }
            self._pending_elicitations[elicitation_id] = pending
            self._append_event_locked(
                {"type": "elicitation.requested", **{key: value for key, value in pending.items() if key != "request_id"}}
            )

    def _handle_notification(self, method: str, params: Mapping[str, Any]) -> None:
        if method == "serverRequest/resolved":
            request_id = params.get("requestId")
            with self._lock:
                for approval_id, approval in list(self._pending_approvals.items()):
                    if approval["request_id"] == request_id:
                        del self._pending_approvals[approval_id]
                        self._append_event_locked(
                            {"type": "approval.resolved", "approval_id": approval_id, "decision": "resolved_by_codex"}
                        )
                for question_id, question in list(self._pending_questions.items()):
                    if question["request_id"] == request_id:
                        del self._pending_questions[question_id]
                        self._append_event_locked(
                            {"type": "question.resolved", "question_id": question_id, "reason": "resolved_by_codex"}
                        )
                for elicitation_id, elicitation in list(self._pending_elicitations.items()):
                    if elicitation["request_id"] == request_id:
                        del self._pending_elicitations[elicitation_id]
                        self._append_event_locked(
                            {"type": "elicitation.resolved", "elicitation_id": elicitation_id, "action": "resolved_by_codex"}
                        )
            return
        event = normalize_notification(method, params)
        if event is None:
            return
        with self._lock:
            if event["type"] == "turn.started" and isinstance(event.get("turn_id"), str):
                self._active_turn_id = event["turn_id"]
                if self._status in {"READY", "WORKING"}:
                    self._status = "WORKING"
            elif event["type"] == "turn.completed":
                if isinstance(event.get("turn_id"), str):
                    self._completed_turns.append(event["turn_id"])
                if self._active_turn_id in {None, event.get("turn_id")}:
                    self._active_turn_id = None
                    if self._status == "WORKING":
                        self._status = "READY"
            elif event["type"] == "file_change.started" and isinstance(event.get("item_id"), str):
                self._change_paths[event["item_id"]] = list(event.get("paths") or ())
                if len(self._change_paths) > 256:
                    self._change_paths.pop(next(iter(self._change_paths)))
            self._append_event_locked(event)
