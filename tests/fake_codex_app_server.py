"""Deterministic stand-in for ``codex app-server`` used by the Workbench tests.

It speaks the same newline-delimited JSON-RPC shapes the real app-server uses
for the methods AIA depends on.  The first word of a turn's text selects the
scenario (``hello``, ``run``, ``patch``, ``slow``, ``ask``, ``question``,
``question-auto``, ``mcp-form``, ``mcp-url``, ``mcp-custom``, ``race``, ``crash``).  Setting ``FAKE_APP_SERVER_SANDBOX`` overrides the sandbox the
fake reports as applied.
"""

from __future__ import annotations

import json
import os
import sys

state = {"turn": 0, "active": None, "pending": None}


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def notify(method: str, **params) -> None:
    send({"method": method, "params": {"threadId": "thr-1", **params}})


def start_turn() -> str:
    state["turn"] += 1
    turn_id = f"turn-{state['turn']}"
    state["active"] = turn_id
    return turn_id


def complete_turn(turn_id: str, status: str = "completed") -> None:
    notify("turn/completed", turn={"id": turn_id, "status": status, "items": [], "durationMs": 5})
    state["active"] = None


def user_item(turn_id: str, text: str) -> None:
    notify(
        "item/started",
        turnId=turn_id,
        item={"type": "userMessage", "id": f"u-{turn_id}-{len(text)}", "content": [{"type": "text", "text": text}]},
    )


def agent_reply(turn_id: str, text: str) -> None:
    item_id = f"a-{turn_id}"
    notify("item/started", turnId=turn_id, item={"type": "agentMessage", "id": item_id, "text": ""})
    for part in (text[: len(text) // 2], text[len(text) // 2 :]):
        notify("item/agentMessage/delta", turnId=turn_id, itemId=item_id, delta=part)
    notify("item/completed", turnId=turn_id, item={"type": "agentMessage", "id": item_id, "text": text})


def handle_turn_start(request_id, text: str) -> None:
    scenario = text.split()[0] if text.split() else "hello"
    if scenario == "crash":
        sys.exit(3)
    turn_id = start_turn()
    if scenario == "race":
        notify("turn/started", turn={"id": turn_id, "status": "inProgress", "items": []})
        user_item(turn_id, text)
        complete_turn(turn_id)
        send({"id": request_id, "result": {"turn": {"id": turn_id, "status": "inProgress", "items": []}}})
        return
    send({"id": request_id, "result": {"turn": {"id": turn_id, "status": "inProgress", "items": []}}})
    notify("turn/started", turn={"id": turn_id, "status": "inProgress", "items": []})
    user_item(turn_id, text)
    if scenario == "hello":
        agent_reply(turn_id, "Hello there")
        complete_turn(turn_id)
    elif scenario == "run":
        notify(
            "item/started",
            turnId=turn_id,
            item={"type": "commandExecution", "id": "cmd-1", "command": "echo hi", "cwd": "C:/ws",
                  "commandActions": [], "status": "inProgress"},
        )
        notify("hook/started", turnId=turn_id, run={"id": "hook-1", "eventName": "preToolUse", "status": "running"})
        notify("hook/completed", turnId=turn_id,
               run={"id": "hook-1", "eventName": "preToolUse", "status": "completed", "durationMs": 3})
        state["pending"] = ("run", turn_id)
        send({"id": "srv-1", "method": "item/commandExecution/requestApproval",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "cmd-1", "command": "echo hi",
                         "cwd": "C:/ws", "reason": "needs approval", "startedAtMs": 1}})
    elif scenario == "patch":
        notify(
            "item/started",
            turnId=turn_id,
            item={"type": "fileChange", "id": "fc-1", "status": "inProgress",
                  "changes": [{"path": "notes.txt", "kind": {"type": "add"}, "diff": "+hi"}]},
        )
        state["pending"] = ("patch", turn_id)
        send({"id": "srv-2", "method": "item/fileChange/requestApproval",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "fc-1", "reason": "write file",
                         "startedAtMs": 1}})
    elif scenario == "ask":
        state["pending"] = ("ask", turn_id)
        send({"id": "srv-3", "method": "item/tool/requestUserInput",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "q-1", "questions": []}})
    elif scenario == "question":
        state["pending"] = ("question", turn_id)
        send({"id": "srv-4", "method": "item/tool/requestUserInput",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "q-2", "isBlocking": True,
                         "questions": [
                             {"id": "scope", "header": "Scope", "question": "Which files?", "isOther": True,
                              "options": [{"label": "All", "description": "every file"},
                                          {"label": "Some", "description": "only tests"}]},
                             {"id": "token", "header": "Token", "question": "Paste the token", "isSecret": True,
                              "options": None},
                         ]}})
    elif scenario == "question-auto":
        send({"id": "srv-5", "method": "item/tool/requestUserInput",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "q-3", "isBlocking": False,
                         "autoResolutionMs": 50,
                         "questions": [{"id": "go", "header": "Go", "question": "Continue?", "options": []}]}})
        notify("serverRequest/resolved", requestId="srv-5")
        agent_reply(turn_id, "auto-resolved")
        complete_turn(turn_id)
    elif scenario in {"mcp-form", "mcp-url", "mcp-custom"}:
        state["pending"] = ("elicitation", turn_id)
        request = {"threadId": "thr-1", "turnId": turn_id, "serverName": "tracker", "message": "Need input"}
        if scenario == "mcp-form":
            request.update(mode="form", requestedSchema={
                "type": "object", "required": ["project"],
                "properties": {"project": {"type": "string", "title": "Project", "enum": ["web", "api"]},
                               "count": {"type": "integer", "minimum": 1},
                               "notify": {"type": "boolean"}}})
        elif scenario == "mcp-url":
            request.update(mode="url", elicitationId="el-1", url="https://auth.example.com/login?state=1")
        else:
            request.update(mode="openai/form", requestedSchema={"anything": True})
        send({"id": "srv-6", "method": "mcpServer/elicitation/request", "params": request})
    elif scenario == "slow":
        pass  # stays in progress until turn/interrupt


def handle_server_response(message: dict) -> None:
    pending = state["pending"]
    state["pending"] = None
    if pending is None:
        return
    kind, turn_id = pending
    if kind == "ask":
        agent_reply(turn_id, "got-error" if "error" in message else "got-result")
        complete_turn(turn_id)
        return
    if kind == "elicitation":
        agent_reply(turn_id, "elicitation=" + json.dumps(message.get("result"), sort_keys=True))
        complete_turn(turn_id)
        return
    if kind == "question":
        answers = (message.get("result") or {}).get("answers")
        agent_reply(turn_id, "answers=" + json.dumps(answers, sort_keys=True))
        complete_turn(turn_id)
        return
    decision = (message.get("result") or {}).get("decision")
    if kind == "run":
        if decision in {"accept", "acceptForSession"}:
            notify("item/commandExecution/outputDelta", turnId=turn_id, itemId="cmd-1", delta="hi\r\n")
            status, exit_code = "completed", 0
        else:
            status, exit_code = "declined", None
        notify("item/completed", turnId=turn_id,
               item={"type": "commandExecution", "id": "cmd-1", "command": "echo hi", "cwd": "C:/ws",
                     "commandActions": [], "status": status, "exitCode": exit_code, "durationMs": 7})
    else:
        status = "completed" if decision in {"accept", "acceptForSession"} else "declined"
        notify("item/completed", turnId=turn_id,
               item={"type": "fileChange", "id": "fc-1", "status": status,
                     "changes": [{"path": "notes.txt", "kind": {"type": "add"}, "diff": "+hi"}]})
    agent_reply(turn_id, f"decision={decision}")
    complete_turn(turn_id)


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method is None:
            handle_server_response(message)
        elif method == "initialize":
            code_page = None
            if os.name == "nt":
                import ctypes

                code_page = ctypes.WinDLL("kernel32").GetConsoleOutputCP()
            send({"id": request_id, "result": {
                "userAgent": "fake-app-server/0",
                "consoleOutputCodePage": code_page,
                "pythonUtf8": os.environ.get("PYTHONUTF8"),
            }})
        elif method == "initialized":
            continue
        elif method == "thread/start":
            sandbox = os.environ.get("FAKE_APP_SERVER_SANDBOX", "workspaceWrite")
            send({"id": request_id, "result": {
                "thread": {"id": "thr-1"}, "model": params.get("model") or "fake-model",
                "modelProvider": "fake", "cwd": params.get("cwd"), "approvalsReviewer": "user",
                "approvalPolicy": params.get("approvalPolicy"), "sandbox": {"type": sandbox}}})
            notify("thread/started", thread={"id": "thr-1"})
        elif method == "turn/start":
            text = "".join(part.get("text", "") for part in params.get("input", []))
            handle_turn_start(request_id, text)
        elif method == "turn/steer":
            active = state["active"]
            if active is None:
                send({"id": request_id, "error": {"code": -32600, "message": "no active turn"}})
            else:
                send({"id": request_id, "result": {"turnId": active}})
                user_item(active, "".join(part.get("text", "") for part in params.get("input", [])))
        elif method == "turn/interrupt":
            send({"id": request_id, "result": {}})
            if state["active"] is not None:
                complete_turn(state["active"], "interrupted")
        else:
            send({"id": request_id, "error": {"code": -32601, "message": f"unknown {method}"}})


if __name__ == "__main__":
    main()
