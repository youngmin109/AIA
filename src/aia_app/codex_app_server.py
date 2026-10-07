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
import re
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
# The only per-turn values the Workbench may override: everything else (sandbox,
# approval policy, cwd, reviewer) stays fixed by the protected thread.
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_EFFORT_PATTERN = re.compile(r"^[a-z]{1,20}$")


def validate_turn_settings(model: Any, effort: Any) -> tuple[str | None, str | None]:
    """Model and reasoning effort for the next turns; ``None`` keeps Codex's default."""

    if model is not None and (not isinstance(model, str) or not _MODEL_PATTERN.match(model)):
        raise CodexAppServerError("모델 이름 형식이 올바르지 않아요.")
    if effort is not None and (not isinstance(effort, str) or not _EFFORT_PATTERN.match(effort)):
        raise CodexAppServerError("생각 깊이 값이 올바르지 않아요.")
    return model, effort


def _model_view(model: Any) -> dict[str, Any] | None:
    if not isinstance(model, Mapping) or model.get("hidden") or not isinstance(model.get("model"), str):
        return None
    efforts = [
        {"effort": option["reasoningEffort"], "description": _text_of(option.get("description"))}
        for option in model.get("supportedReasoningEfforts") or []
        if isinstance(option, Mapping) and isinstance(option.get("reasoningEffort"), str)
    ]
    return {
        "model": model["model"],
        "display_name": _text_of(model.get("displayName")) or model["model"],
        "description": _text_of(model.get("description")),
        "is_default": bool(model.get("isDefault")),
        "default_effort": _text_of(model.get("defaultReasoningEffort")) or None,
        "efforts": efforts,
    }


# Codex asking to widen its sandbox (file system or network); the user decides.
_PERMISSIONS_REQUEST = "item/permissions/requestApproval"
PERMISSION_DECISIONS = frozenset({"turn", "session", "decline"})
_SPECIAL_PATH_LABELS = {
    "root": ("컴퓨터 전체", "outside"),
    "minimal": ("기본 시스템 경로", "outside"),
    "tmpdir": ("임시 폴더", "outside"),
    "slash_tmp": ("/tmp", "outside"),
}
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
            raise CodexAppServerError("입력값이 요청 형식과 맞지 않아요.")
        return int(value) if kind == "integer" else value
    if kind == "select" and isinstance(value, str) and value in allowed:
        return value
    if kind == "multi" and isinstance(value, list) and all(isinstance(item, str) and item in allowed for item in value):
        return list(value)
    raise CodexAppServerError("입력값이 요청 형식과 맞지 않아요.")


def _permission_target(path: Any, workspace: Path) -> tuple[str, str] | None:
    """Readable target and whether it lies inside the protected workspace."""

    if not isinstance(path, Mapping):
        return None
    kind = path.get("type")
    if kind == "path" and isinstance(path.get("path"), str):
        target = Path(path["path"]).expanduser()
        resolved = (target if target.is_absolute() else workspace / target).resolve(strict=False)
        inside = resolved == workspace or workspace in resolved.parents
        return str(resolved), "inside" if inside else "outside"
    if kind == "glob_pattern" and isinstance(path.get("pattern"), str):
        return path["pattern"], "unknown"
    value = path.get("value")
    if kind == "special" and isinstance(value, Mapping):
        special = value.get("kind")
        if special == "project_roots":
            subpath = _text_of(value.get("subpath"))
            return f"작업 폴더{f' / {subpath}' if subpath else ''}", "inside"
        if special in _SPECIAL_PATH_LABELS:
            return _SPECIAL_PATH_LABELS[special]
        return _text_of(value.get("path")) or "알 수 없는 경로", "unknown"
    return None


def _parse_permissions(params: Mapping[str, Any], workspace: Path) -> dict[str, Any] | None:
    """What Codex asks to widen, in display form; ``None`` when the shape is unknown."""

    requested = params.get("permissions")
    if not isinstance(requested, Mapping):
        return None
    filesystem: list[dict[str, str]] = []
    file_system = requested.get("fileSystem")
    if file_system is not None:
        if not isinstance(file_system, Mapping):
            return None
        for entry in file_system.get("entries") or []:
            target = _permission_target(entry.get("path"), workspace) if isinstance(entry, Mapping) else None
            access = entry.get("access") if isinstance(entry, Mapping) else None
            if target is None or access not in {"read", "write", "deny"}:
                return None
            filesystem.append({"access": access, "target": target[0], "scope": target[1]})
        for access in ("read", "write"):
            for legacy in file_system.get(access) or []:
                target = _permission_target({"type": "path", "path": legacy}, workspace)
                if target is None:
                    return None
                filesystem.append({"access": access, "target": target[0], "scope": target[1]})
    network = requested.get("network")
    if network is not None and not isinstance(network, Mapping):
        return None
    return {
        "reason": _text_of(params.get("reason")),
        "network": bool(network and network.get("enabled")),
        "filesystem": filesystem,
        "requested": dict(requested),
    }


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


def _usage_window(window: Any) -> dict[str, Any] | None:
    if not isinstance(window, Mapping) or not isinstance(window.get("usedPercent"), int):
        return None
    resets_at = window.get("resetsAt")
    if isinstance(resets_at, int) and not isinstance(resets_at, bool) and resets_at > 0:
        # Codex reports epoch seconds; tolerate milliseconds as well.
        seconds = resets_at / 1000 if resets_at > 10**12 else resets_at
        resets = datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    else:
        resets = None
    minutes = window.get("windowDurationMins")
    return {
        "used_percent": max(0, min(100, window["usedPercent"])),
        "window_minutes": minutes if isinstance(minutes, int) else None,
        "resets_at": resets,
    }


def usage_limits(snapshot: Any) -> dict[str, Any] | None:
    """Rate-limit windows in display form; ``None`` when Codex reports none."""

    if not isinstance(snapshot, Mapping):
        return None
    windows = [window for window in (_usage_window(snapshot.get("primary")), _usage_window(snapshot.get("secondary"))) if window]
    if not windows:
        return None
    return {"windows": windows, "reached": _text_of(snapshot.get("rateLimitReachedType")) or None}


def _token_usage(params: Mapping[str, Any]) -> dict[str, Any] | None:
    usage = params.get("tokenUsage")
    if not isinstance(usage, Mapping):
        return None
    total = usage.get("total") if isinstance(usage.get("total"), Mapping) else {}
    total_tokens = total.get("totalTokens")
    if not isinstance(total_tokens, int) or isinstance(total_tokens, bool):
        return None
    window = usage.get("modelContextWindow")
    return {"total_tokens": total_tokens, "context_window": window if isinstance(window, int) else None}


_MAX_DIFF_CHARS = 500_000
_MAX_DIFF_TURNS = 30
_MAX_DIFF_FILES = 50


def diff_summary(diff: str) -> dict[str, Any]:
    """Files and line counts of a unified diff; the text itself is not included."""

    files: list[str] = []
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path != "/dev/null":
                path = path[2:] if path.startswith(("a/", "b/")) else path
                if path not in files:
                    files.append(path)
        elif line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"files": files[:_MAX_DIFF_FILES], "file_count": len(files), "added": added, "removed": removed}


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
    if method == "turn/plan/updated":
        steps = [
            {"step": _text_of(item.get("step"))[:500], "status": item.get("status")}
            for item in (params.get("plan") or [])[:50]
            if isinstance(item, Mapping) and item.get("status") in {"pending", "inProgress", "completed"}
        ]
        return {
            "type": "plan.updated",
            "turn_id": params.get("turnId"),
            "explanation": _text_of(params.get("explanation"))[:1000] or None,
            "steps": steps,
        }
    if method == "account/rateLimits/updated":
        limits = usage_limits(params.get("rateLimits"))
        return {"type": "usage.limits", "limits": limits} if limits else None
    if method == "thread/tokenUsage/updated":
        tokens = _token_usage(params)
        return {"type": "usage.tokens", "tokens": tokens} if tokens else None
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
    if item_type == "exitedReviewMode" and not started:
        return {"type": "review.completed", "item_id": item_id, "text": _text_of(item.get("review"))}
    if item_type == "enteredReviewMode" and started:
        return {"type": "review.started", "item_id": item_id}
    if item_type == "contextCompaction" and not started:
        return {"type": "compaction.completed", "item_id": item_id}
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
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._next_permissions = 1
        self._usage_limits: dict[str, Any] | None = None
        self._token_usage: dict[str, Any] | None = None
        self._turn_settings: dict[str, str | None] = {"model": None, "effort": None}
        self._plan: dict[str, Any] | None = None
        # Latest unified diff per turn, in memory only and fetched on demand.
        self._diffs: dict[str, str] = {}
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
        resume_thread_id: str | None = None,
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
        result: dict[str, Any] | None = None
        if resume_thread_id:
            # Resuming keeps AIA's protected cwd, sandbox and approval policy.
            try:
                result = self._request("thread/resume", {**params, "threadId": resume_thread_id}, timeout=timeout)
            except CodexAppServerError:
                self._append_event(
                    {"type": "warning", "message": "이전 대화를 찾지 못해 새 대화로 시작했어요."}
                )
        if result is None:
            result = self._request("thread/start", params, timeout=timeout)
        elif isinstance(result.get("thread"), Mapping):
            self._replay_history(result["thread"])
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
        # Usage is informational; read it without delaying the conversation.
        Thread(target=self._read_usage_limits, name="codex-usage", daemon=True).start()
        return dict(effective)

    def _read_usage_limits(self) -> None:
        try:
            result = self._request("account/rateLimits/read", {"excludeResetCreditDetails": True}, timeout=10.0)
        except CodexAppServerError:
            return  # API-key logins and older Codex releases have no usage limits
        limits = usage_limits(result.get("rateLimits"))
        if limits is not None:
            with self._lock:
                self._usage_limits = limits
                self._append_event_locked({"type": "usage.limits", "limits": limits})

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
            permission_requests = list(self._pending_permissions.items())
            self._pending_permissions.clear()
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
            for permissions_id, request in permission_requests:
                self._respond(request["request_id"], {"permissions": {}})
                self._append_event({"type": "permissions.resolved", "permissions_id": permissions_id, "decision": "cancel"})
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
        params: dict[str, Any] = {"threadId": thread_id, "input": user_input}
        with self._lock:
            settings = dict(self._turn_settings)
        # Built from the two allowed keys only; nothing else can reach turn/start.
        if settings["model"]:
            params["model"] = settings["model"]
        if settings["effort"]:
            params["effort"] = settings["effort"]
        result = self._request("turn/start", params)
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
            raise CodexAppServerError("답이 질문 형식과 맞지 않아요.")
        with self._lock:
            question = self._pending_questions.get(question_id)
            if question is None:
                raise CodexAppServerError("이미 끝난 질문이에요.")
            known = {item["id"]: item for item in question["questions"]}
            cleaned: dict[str, list[str]] = {}
            for key, values in answers.items():
                if key not in known or not isinstance(values, list) or not values or any(
                    not isinstance(value, str) or not value.strip() or len(value) > _MAX_ANSWER_CHARS
                    for value in values
                ):
                    raise CodexAppServerError("답이 질문 형식과 맞지 않아요.")
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
            raise CodexAppServerError("지원하지 않는 응답이에요.")
        with self._lock:
            elicitation = self._pending_elicitations.get(elicitation_id)
            if elicitation is None:
                raise CodexAppServerError("이미 끝난 입력 요청이에요.")
            result: dict[str, Any] = {"action": action}
            if action == "accept":
                if not elicitation["supported"]:
                    raise CodexAppServerError("이 입력 요청은 거절이나 취소만 할 수 있어요.")
                if elicitation["mode"] == "form":
                    if not isinstance(content, Mapping):
                        raise CodexAppServerError("입력값이 요청 형식과 맞지 않아요.")
                    fields = {field["name"]: field for field in elicitation["fields"]}
                    if any(key not in fields for key in content) or any(
                        field["required"] and name not in content for name, field in fields.items()
                    ):
                        raise CodexAppServerError("입력값이 요청 형식과 맞지 않아요.")
                    result["content"] = {key: _elicitation_value(fields[key], value) for key, value in content.items()}
            del self._pending_elicitations[elicitation_id]
        self._respond(elicitation["request_id"], result)
        self._append_event({"type": "elicitation.resolved", "elicitation_id": elicitation_id, "action": action})
        return {"accepted": True, "elicitation_id": elicitation_id, "action": action}

    def read_diff(self, turn_id: str | None = None) -> dict[str, Any]:
        """One turn's diff, or every kept turn in order when ``turn_id`` is None."""

        with self._lock:
            if turn_id is None:
                text = "\n".join(self._diffs.values())
            elif turn_id in self._diffs:
                text = self._diffs[turn_id]
            else:
                raise CodexAppServerError("이 요청에서 기록된 바뀐 내용이 없어요.")
        truncated = len(text) > _MAX_DIFF_CHARS
        return {"turn_id": turn_id, "diff": text[:_MAX_DIFF_CHARS], "truncated": truncated}

    def compact(self) -> dict[str, Any]:
        """Ask Codex to summarize the conversation so far (``/compact``)."""

        thread_id, _ = self._require_thread()
        self._request("thread/compact/start", {"threadId": thread_id})
        return {"accepted": True}

    def start_review(self) -> dict[str, Any]:
        """Ask Codex to review the uncommitted changes in the workspace (``/review``)."""

        thread_id, turn_id = self._require_thread()
        if turn_id is not None:
            raise CodexAppServerError("진행 중인 요청이 끝난 뒤에 코드 검토를 시작할 수 있어요.")
        result = self._request(
            "review/start",
            {"threadId": thread_id, "target": {"type": "uncommittedChanges"}, "delivery": "inline"},
        )
        new_turn_id = (result.get("turn") or {}).get("id")
        with self._lock:
            if isinstance(new_turn_id, str) and self._status == "READY" and new_turn_id not in self._completed_turns:
                self._active_turn_id = new_turn_id
                self._status = "WORKING"
        return {"accepted": True, "turn_id": new_turn_id}

    def set_goal(self, objective: Any) -> dict[str, Any]:
        """Set the conversation goal (``/goal``)."""

        if not isinstance(objective, str) or not objective.strip() or len(objective) > 2_000:
            raise CodexAppServerError("목표는 2,000자 이내의 문장으로 적어 주세요.")
        thread_id, _ = self._require_thread()
        self._request("thread/goal/set", {"threadId": thread_id, "objective": objective.strip()})
        self._append_event({"type": "goal.set", "text": objective.strip()})
        return {"accepted": True}

    def set_turn_settings(self, model: Any = None, effort: Any = None) -> dict[str, Any]:
        """Choose the model and reasoning effort for the next turns."""

        model, effort = validate_turn_settings(model, effort)
        with self._lock:
            self._turn_settings = {"model": model, "effort": effort}
            self._append_event_locked({"type": "settings.changed", "model": model, "effort": effort})
        return {"accepted": True, "model": model, "effort": effort}

    def handshake(self, *, timeout: float = 15.0) -> None:
        """Initialize a not-yet-opened app-server for read-only questions (no thread is started)."""

        self._request(
            "initialize",
            {"clientInfo": {"name": "aia-workbench", "title": "AIA Workbench", "version": self.client_version}},
            timeout=timeout,
        )
        self._notify("initialized")

    def list_models(self, *, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Visible models; the session must not be opened (see ``handshake``)."""

        self.handshake(timeout=timeout)
        result = self._request("model/list", {"includeHidden": False, "limit": 50}, timeout=timeout)
        return [view for view in (_model_view(item) for item in result.get("data") or []) if view]

    def list_connectors(self, *, timeout: float = 15.0) -> list[dict[str, Any]]:
        """MCP servers Codex has for this conversation; read-only, outside AIA's protection."""

        self._require_thread()
        result = self._request("mcpServerStatus/list", {"limit": 100}, timeout=timeout)
        connectors: list[dict[str, Any]] = []
        for server in result.get("data") or []:
            if not isinstance(server, Mapping) or not isinstance(server.get("name"), str):
                continue
            tools = server.get("tools") if isinstance(server.get("tools"), Mapping) else {}
            connectors.append(
                {
                    "name": server["name"],
                    "status": _text_of(server.get("runtimeStatus")) or "unknown",
                    "auth": _text_of(server.get("authStatus")) or "unknown",
                    "tool_count": len(tools),
                    "tools": sorted(str(name) for name in tools)[:30],
                    "error": _text_of(server.get("toolsError")) or None,
                }
            )
        return connectors

    def read_thread(self, thread_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        """Name and preview of a conversation, read live from Codex (after ``handshake``)."""

        result = self._request("thread/read", {"threadId": thread_id, "includeTurns": False}, timeout=timeout)
        thread = result.get("thread") if isinstance(result.get("thread"), Mapping) else {}
        updated = thread.get("updatedAt")
        return {
            "name": _text_of(thread.get("name")) or None,
            "preview": _text_of(thread.get("preview"))[:200],
            "updated_at": (
                datetime.fromtimestamp(updated / 1000 if updated > 10**12 else updated, tz=timezone.utc).isoformat()
                if isinstance(updated, int) and not isinstance(updated, bool) and updated > 0
                else None
            ),
        }

    def _replay_history(self, thread: Mapping[str, Any], limit: int = 60) -> None:
        """Show the resumed conversation's earlier messages (text only, newest ``limit``)."""

        messages: list[dict[str, Any]] = []
        for turn in thread.get("turns") or []:
            for item in (turn.get("items") if isinstance(turn, Mapping) else None) or []:
                if not isinstance(item, Mapping):
                    continue
                item_id = f"history-{_text_of(item.get('id'))}"
                if item.get("type") == "userMessage":
                    messages.append({"type": "user_message", "item_id": item_id, "text": _user_message_text(item)[:20_000]})
                elif item.get("type") == "agentMessage":
                    messages.append({"type": "message.completed", "item_id": item_id, "text": _text_of(item.get("text"))[:20_000]})
        kept = messages[-limit:]
        with self._lock:
            for message in kept:
                self._append_event_locked(message)
            self._append_event_locked({"type": "history.restored", "count": len(kept)})

    def respond_permissions(self, permissions_id: str, decision: str) -> dict[str, Any]:
        """Grant what Codex asked for (this turn or the whole session) or decline.

        A grant widens the sandbox exactly as requested; the caller records it
        so the run shows that protection reached less than before.
        """

        if decision not in PERMISSION_DECISIONS:
            raise CodexAppServerError("지원하지 않는 권한 결정이에요.")
        with self._lock:
            request = self._pending_permissions.pop(permissions_id, None)
        if request is None:
            raise CodexAppServerError("이미 끝난 권한 요청이에요.")
        if decision == "decline":
            self._respond(request["request_id"], {"permissions": {}})
        else:
            self._respond(request["request_id"], {"permissions": request["requested"], "scope": decision})
        self._append_event({"type": "permissions.resolved", "permissions_id": permissions_id, "decision": decision})
        return {
            "accepted": True,
            "permissions_id": permissions_id,
            "decision": decision,
            "network": request["network"],
            "filesystem": request["filesystem"],
            "reason": request["reason"],
        }

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
            permission_requests = [
                {key: value for key, value in request.items() if key not in {"request_id", "requested"}}
                for request in self._pending_permissions.values()
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
                "pending_permissions": permission_requests,
                "usage": {"limits": self._usage_limits, "tokens": self._token_usage},
                "turn_settings": dict(self._turn_settings),
                "plan": self._plan,
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
            self._pending_permissions.clear()
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
        if method == _PERMISSIONS_REQUEST:
            permissions = _parse_permissions(params, self.cwd)
            if permissions is not None:
                self._open_permissions(request_id, params, permissions)
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

    def _open_permissions(self, request_id: Any, params: Mapping[str, Any], permissions: dict[str, Any]) -> None:
        with self._lock:
            permissions_id = f"permissions-{self._next_permissions}"
            self._next_permissions += 1
            pending = {
                "permissions_id": permissions_id,
                "request_id": request_id,
                "item_id": params.get("itemId"),
                "turn_id": params.get("turnId"),
                **permissions,
            }
            self._pending_permissions[permissions_id] = pending
            self._append_event_locked(
                {
                    "type": "permissions.requested",
                    **{key: value for key, value in pending.items() if key not in {"request_id", "requested"}},
                }
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
                for permissions_id, request in list(self._pending_permissions.items()):
                    if request["request_id"] == request_id:
                        del self._pending_permissions[permissions_id]
                        self._append_event_locked(
                            {"type": "permissions.resolved", "permissions_id": permissions_id, "decision": "resolved_by_codex"}
                        )
            return
        if method == "turn/diff/updated":
            turn_id, diff = params.get("turnId"), params.get("diff")
            if isinstance(turn_id, str) and isinstance(diff, str):
                with self._lock:
                    self._diffs.pop(turn_id, None)
                    self._diffs[turn_id] = diff[: _MAX_DIFF_CHARS + 1]
                    while len(self._diffs) > _MAX_DIFF_TURNS:
                        self._diffs.pop(next(iter(self._diffs)))
                    self._append_event_locked({"type": "diff.updated", "turn_id": turn_id, **diff_summary(diff)})
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
            elif event["type"] == "plan.updated":
                self._plan = {key: event[key] for key in ("turn_id", "explanation", "steps")}
            elif event["type"] == "usage.limits":
                self._usage_limits = event["limits"]
            elif event["type"] == "usage.tokens":
                self._token_usage = event["tokens"]
            elif event["type"] == "file_change.started" and isinstance(event.get("item_id"), str):
                self._change_paths[event["item_id"]] = list(event.get("paths") or ())
                if len(self._change_paths) > 256:
                    self._change_paths.pop(next(iter(self._change_paths)))
            self._append_event_locked(event)
