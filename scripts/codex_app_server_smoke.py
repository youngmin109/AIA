"""Verify the Workbench app-server transport against the installed Codex CLI.

This is a developer validation tool, not the normal product runtime.  It runs
``codex app-server`` through the same adapter and ``CodexAppServerSession``
the Workbench uses, inside a disposable workspace, and checks:

- protocol handshake and the sandbox/approval policy Codex reports as applied
- a plain reply turn (streamed message events)
- a harmless shell command turn (command events and Codex Hook runs)
- interrupting an active turn
- a graceful close that lets Codex exit on its own

Only event types, counts, statuses and timings are retained.  Conversation
text is reduced to booleans, and the workspace is removed afterwards.  Each
turn makes a small real model request on the signed-in Codex account.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

from aia import CodexAdapter, ProtectedLaunchRequest, __version__
from aia_app.codex_app_server import CodexAppServerSession


def _run_turn(session: CodexAppServerSession, text: str, timeout: float, *, interrupt_after_first_event: bool = False) -> dict[str, Any]:
    start_sequence = session.snapshot()["last_sequence"]
    started = time.monotonic()
    ack = session.send_message(text)
    ack_seconds = time.monotonic() - started
    first_event_at: float | None = None
    interrupted = False
    cursor = start_sequence
    events: list[dict[str, Any]] = []
    deadline = started + timeout
    while time.monotonic() < deadline:
        batch = session.wait_events(cursor, timeout=1.0)
        if batch:
            cursor = batch[-1]["sequence"]
            events.extend(batch)
            if first_event_at is None:
                first_event_at = time.monotonic() - started
        if interrupt_after_first_event and not interrupted and any(e["type"] == "turn.started" for e in events):
            session.interrupt()
            interrupted = True
        if any(e["type"] in {"turn.completed", "session.exited"} for e in events):
            break
    completed = next((e for e in events if e["type"] == "turn.completed"), None)
    agent_text = "".join(e.get("text", "") for e in events if e["type"] == "message.completed")
    command_output = "".join(e.get("text", "") for e in events if e["type"] == "command.output")
    return {
        "mode": ack.get("mode"),
        "ack_seconds": round(ack_seconds, 3),
        "first_event_seconds": round(first_event_at, 3) if first_event_at is not None else None,
        "completed": completed is not None,
        "turn_status": completed.get("status") if completed else None,
        "event_counts": dict(Counter(e["type"] for e in events)),
        "hook_runs": sorted(
            {(e.get("event_name"), e.get("status")) for e in events if e["type"] == "hook" and e.get("phase") == "completed"}
        ),
        "command_statuses": [e.get("status") for e in events if e["type"] == "command.completed"],
        "agent_text_chars": len(agent_text),
        "_agent_text": agent_text,
        "_command_output": command_output,
        "interrupted": interrupted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--model")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args(argv)

    workspace = Path(tempfile.mkdtemp(prefix="aia-app-server-smoke-"))
    adapter = CodexAdapter(enable_hooks=True)
    executable = adapter.discover()
    spec = adapter.build_launch(
        ProtectedLaunchRequest(
            aia_session_id=f"smoke-{uuid4()}",
            workspace=workspace,
            agent="codex",
            adapter_options={"interactive": True, "app_server": True, "sandbox": "workspace-write"},
        ),
        executable,
    )
    result: dict[str, Any] = {
        "codex_version": CodexAdapter.executable_version(executable),
        "argv_flags": [part for part in spec.argv[1:]],
    }
    session = CodexAppServerSession(spec.argv, cwd=workspace, env=dict(os.environ), client_version=__version__)
    checks: dict[str, bool] = {}
    try:
        started = time.monotonic()
        session.start()
        result["effective"] = session.open(model=args.model)
        result["open_seconds"] = round(time.monotonic() - started, 3)
        checks["sandbox_applied"] = result["effective"].get("sandbox") == "workspaceWrite"
        checks["approval_policy_applied"] = result["effective"].get("approval_policy") == "on-request"

        plain = _run_turn(session, "Reply with exactly the single word: pong", args.timeout)
        checks["plain_turn_completed"] = plain["turn_status"] == "completed"
        checks["plain_reply_streamed"] = plain["event_counts"].get("message.delta", 0) >= 1
        checks["plain_reply_text"] = "pong" in plain.pop("_agent_text").lower()
        plain.pop("_command_output")
        result["plain_turn"] = plain

        command = _run_turn(
            session,
            "Run the shell command `echo aia-smoke` in the current folder, then reply with its output only.",
            args.timeout,
        )
        checks["command_turn_completed"] = command["turn_status"] == "completed"
        checks["command_executed"] = "completed" in command["command_statuses"]
        checks["command_output_streamed"] = "aia-smoke" in command.pop("_command_output")
        command.pop("_agent_text")
        hook_events = {name for name, _ in command["hook_runs"]}
        checks["pretool_hook_ran"] = "preToolUse" in hook_events
        checks["posttool_hook_ran"] = "postToolUse" in hook_events
        result["command_turn"] = command

        # Korean output must reach Codex intact from both PowerShell and
        # Python (UTF-8 console + PYTHONUTF8 for the app-server tree).
        (workspace / "한글파일.txt").write_text("x", encoding="utf-8")
        korean = _run_turn(
            session,
            "Run these two shell commands exactly, one after the other, then reply with done: "
            "`Get-ChildItem -Name` and `python -c \"print('한글 출력 확인')\"`",
            args.timeout,
        )
        korean_output = korean.pop("_command_output")
        korean.pop("_agent_text")
        checks["korean_file_name_intact"] = "한글파일.txt" in korean_output
        checks["korean_python_output_intact"] = "한글 출력 확인" in korean_output
        checks["no_replacement_characters"] = "�" not in korean_output
        result["korean_turn"] = korean
        result["console_utf8"] = session.snapshot().get("console_utf8")

        interrupted = _run_turn(
            session,
            "Write a very long, detailed essay (at least 3000 words) about the history of the Korean alphabet.",
            args.timeout,
            interrupt_after_first_event=True,
        )
        interrupted.pop("_agent_text")
        interrupted.pop("_command_output")
        checks["interrupt_ended_turn"] = interrupted["turn_status"] == "interrupted"
        result["interrupt_turn"] = interrupted
        checks["ready_after_interrupt"] = session.snapshot()["status"] == "READY"
    except Exception as error:  # noqa: BLE001 - report every failure shape
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        close_started = time.monotonic()
        session.close()
        result["close_seconds"] = round(time.monotonic() - close_started, 3)
        snapshot = session.snapshot()
        exited = [e for e in session.read_events() if e["type"] == "session.exited"]
        checks["graceful_exit"] = bool(exited) and exited[-1]["unexpected"] is False and snapshot["status"] == "EXITED"
        result["final_status"] = snapshot["status"]
        if not args.keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
    result["checks"] = checks
    result["passed"] = bool(checks) and all(checks.values()) and "error" not in result
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=list))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
