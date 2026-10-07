"""Deterministic stand-in for ``codex app-server`` used by the Workbench tests.

It speaks the same newline-delimited JSON-RPC shapes the real app-server uses
for the methods AIA depends on.  The first word of a turn's text selects the
scenario (``hello``, ``run``, ``patch``, ``slow``, ``ask``, ``question``,
``question-auto``, ``mcp-form``, ``mcp-url``, ``mcp-custom``, ``perm``, ``usage``, ``plan``, ``diff``, ``race``, ``crash``).
``FAKE_APP_SERVER_NO_USAGE`` makes the usage read fail like an API-key login.  Setting ``FAKE_APP_SERVER_SANDBOX`` overrides the sandbox the
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
    elif scenario == "settings":
        agent_reply(turn_id, text)
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
    elif scenario == "perm":
        state["pending"] = ("permissions", turn_id)
        send({"id": "srv-7", "method": "item/permissions/requestApproval",
              "params": {"threadId": "thr-1", "turnId": turn_id, "itemId": "p-1", "cwd": "C:/ws",
                         "startedAtMs": 1, "reason": "needs the network and a sibling folder",
                         "permissions": {"network": {"enabled": True}, "fileSystem": {"entries": [
                             {"access": "write", "path": {"type": "path", "path": "../shared"}},
                             {"access": "read", "path": {"type": "special", "value": {"kind": "project_roots", "subpath": "docs"}}},
                             {"access": "write", "path": {"type": "special", "value": {"kind": "root"}}}]}}}})
    elif scenario == "usage":
        notify("thread/tokenUsage/updated", turnId=turn_id, tokenUsage={
            "total": {"totalTokens": 12345, "inputTokens": 10000, "cachedInputTokens": 0, "outputTokens": 2345,
                      "reasoningOutputTokens": 0},
            "last": {"totalTokens": 345, "inputTokens": 300, "cachedInputTokens": 0, "outputTokens": 45,
                     "reasoningOutputTokens": 0},
            "modelContextWindow": 200000})
        notify("account/rateLimits/updated", rateLimits={"primary": {"usedPercent": 60, "windowDurationMins": 300}})
        agent_reply(turn_id, "counted")
        complete_turn(turn_id)
    elif scenario == "diff":
        diff = ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n-print('old')\n+print('new')\n"
                " keep\n"
                "diff --git a/notes.md b/notes.md\n--- /dev/null\n+++ b/notes.md\n@@ -0,0 +1 @@\n+hello\n")
        notify("turn/diff/updated", turnId=turn_id, diff=diff.split("diff --git a/notes.md")[0])
        notify("turn/diff/updated", turnId=turn_id, diff=diff)
        agent_reply(turn_id, "changed")
        complete_turn(turn_id)
    elif scenario == "plan":
        steps = ["Read the code", "Fix the bug", "Run the tests"]
        notify("turn/plan/updated", turnId=turn_id, explanation="Small fix",
               plan=[{"step": step, "status": "inProgress" if index == 0 else "pending"} for index, step in enumerate(steps)])
        notify("turn/plan/updated", turnId=turn_id, explanation="Small fix",
               plan=[{"step": "Read the code", "status": "completed"}, {"step": "Fix the bug", "status": "inProgress"},
                     {"step": "Run the tests", "status": "pending"}, {"step": "ignored", "status": "weird"}])
        agent_reply(turn_id, "planned")
        complete_turn(turn_id)
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
    if kind == "permissions":
        agent_reply(turn_id, "permissions=" + json.dumps(message.get("result"), sort_keys=True))
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
        elif method == "thread/resume":
            if params.get("threadId") == "missing":
                send({"id": request_id, "error": {"code": -32600, "message": "thread not found"}})
                continue
            sandbox = os.environ.get("FAKE_APP_SERVER_SANDBOX", "workspaceWrite")
            send({"id": request_id, "result": {
                "thread": {"id": params["threadId"], "turns": [{"id": "old-1", "items": [
                    {"type": "userMessage", "id": "ou-1", "content": [{"type": "text", "text": "earlier question"}]},
                    {"type": "agentMessage", "id": "oa-1", "text": "earlier answer"}]}]},
                "model": params.get("model") or "fake-model", "modelProvider": "fake", "cwd": params.get("cwd"),
                "approvalsReviewer": "user", "approvalPolicy": params.get("approvalPolicy"), "sandbox": {"type": sandbox}}})
        elif method == "thread/read":
            if params.get("threadId") == "missing":
                send({"id": request_id, "error": {"code": -32600, "message": "thread not found"}})
            else:
                send({"id": request_id, "result": {"thread": {"id": params["threadId"], "name": "Fix login",
                                                              "preview": "earlier question", "updatedAt": 1791370000}}})
        elif method == "turn/start":
            text = "".join(part.get("text", "") for part in params.get("input", []))
            if text.startswith("settings"):
                extra = sorted(key for key in params if key not in {"threadId", "input"})
                text = "settings " + json.dumps({key: params[key] for key in extra}, sort_keys=True)
            handle_turn_start(request_id, text)
        elif method == "thread/compact/start":
            send({"id": request_id, "result": {}})
            notify("item/started", turnId="compact", item={"type": "contextCompaction", "id": "cc-1"})
            notify("item/completed", turnId="compact", item={"type": "contextCompaction", "id": "cc-1"})
        elif method == "review/start":
            turn_id = start_turn()
            send({"id": request_id, "result": {"reviewThreadId": "thr-1", "turn": {"id": turn_id, "status": "inProgress", "items": []}}})
            notify("turn/started", turn={"id": turn_id, "status": "inProgress", "items": []})
            notify("item/started", turnId=turn_id, item={"type": "enteredReviewMode", "id": "rv-1", "review": "current changes"})
            notify("item/completed", turnId=turn_id, item={"type": "exitedReviewMode", "id": "rv-2", "review": "Looks good. One nit."})
            complete_turn(turn_id)
        elif method == "thread/goal/set":
            send({"id": request_id, "result": {"goal": {"objective": params.get("objective")}}})
        elif method == "model/list":
            send({"id": request_id, "result": {"data": [
                {"id": "m1", "model": "gpt-fast", "displayName": "GPT Fast", "description": "quick", "hidden": False,
                 "isDefault": True, "defaultReasoningEffort": "medium",
                 "supportedReasoningEfforts": [{"reasoningEffort": "low", "description": "fast"},
                                               {"reasoningEffort": "medium", "description": "balanced"}]},
                {"id": "m2", "model": "gpt-secret", "displayName": "Hidden", "description": "", "hidden": True,
                 "isDefault": False, "defaultReasoningEffort": "high", "supportedReasoningEfforts": []},
            ], "nextCursor": None}})
        elif method == "account/rateLimits/read":
            if os.environ.get("FAKE_APP_SERVER_NO_USAGE"):
                send({"id": request_id, "error": {"code": -32600, "message": "not available for API keys"}})
            else:
                send({"id": request_id, "result": {"rateLimits": {
                    "primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": 1791370000},
                    "secondary": {"usedPercent": 15, "windowDurationMins": 10080, "resetsAt": None}}}})
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
