"""Guard the Codex app-server contract the Workbench depends on.

The app-server protocol is marked experimental and Codex updates often.  This
test asks the installed Codex for its protocol JSON Schema and fails with a
precise list when a method, field, or enum value used by
``aia_app.codex_app_server`` disappears.  It is skipped only when no Codex
executable is installed (for example on a CI runner), because the contract
can only be read from the Codex release that the Workbench will launch.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from aia.adapters.codex import AdapterUnavailableError, CodexAdapter


REQUIRED_METHODS = {
    "ClientRequest": {
        "initialize", "thread/start", "thread/resume", "turn/start", "turn/steer", "turn/interrupt",
        "thread/compact/start", "review/start", "thread/goal/set", "thread/goal/clear",
        "account/rateLimits/read", "model/list", "mcpServerStatus/list", "thread/read",
    },
    "ClientNotification": {"initialized"},
    "ServerRequest": {
        "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
        "item/tool/requestUserInput", "mcpServer/elicitation/request", "item/permissions/requestApproval",
    },
    "ServerNotification": {
        "turn/started",
        "turn/completed",
        "item/started",
        "item/completed",
        "item/agentMessage/delta",
        "item/commandExecution/outputDelta",
        "item/reasoning/summaryTextDelta",
        "hook/started",
        "hook/completed",
        "error",
        "serverRequest/resolved",
        "turn/plan/updated",
        "turn/diff/updated",
        "account/rateLimits/updated",
        "thread/tokenUsage/updated",
    },
}

REQUIRED_PROPERTIES = {
    "v2/ThreadStartParams.json": {"cwd", "sandbox", "approvalPolicy", "model"},
    "v2/ThreadStartResponse.json": {"thread", "sandbox", "approvalPolicy", "model"},
    "v2/TurnStartParams.json": {"threadId", "input"},
    "v2/TurnStartResponse.json": {"turn"},
    "v2/TurnSteerParams.json": {"threadId", "expectedTurnId", "input"},
    "v2/TurnInterruptParams.json": {"threadId", "turnId"},
    "v2/AgentMessageDeltaNotification.json": {"itemId", "delta"},
    "v2/CommandExecutionOutputDeltaNotification.json": {"itemId", "delta"},
    "v2/HookStartedNotification.json": {"run", "turnId"},
    "v2/HookCompletedNotification.json": {"run", "turnId"},
    "v2/TurnCompletedNotification.json": {"turn"},
    "v2/ErrorNotification.json": {"error", "willRetry"},
    "v2/ServerRequestResolvedNotification.json": {"requestId"},
    "CommandExecutionRequestApprovalParams.json": {"itemId", "turnId", "command", "cwd", "reason"},
    "FileChangeRequestApprovalParams.json": {"itemId", "turnId", "reason"},
    "ToolRequestUserInputParams.json": {"questions", "autoResolutionMs"},
    "ToolRequestUserInputResponse.json": {"answers"},
    "McpServerElicitationRequestParams.json": {"serverName"},
    "McpServerElicitationRequestResponse.json": {"action", "content"},
    "PermissionsRequestApprovalParams.json": {"permissions", "reason"},
    "PermissionsRequestApprovalResponse.json": {"permissions", "scope"},
    "v2/ThreadResumeParams.json": {"threadId", "cwd", "sandbox", "approvalPolicy"},
    "v2/ThreadResumeResponse.json": {"thread", "sandbox", "approvalPolicy", "model"},
    "v2/TurnPlanUpdatedNotification.json": {"plan", "turnId"},
    "v2/TurnDiffUpdatedNotification.json": {"diff", "turnId"},
    "v2/ThreadTokenUsageUpdatedNotification.json": {"tokenUsage"},
    "v2/ThreadCompactStartParams.json": {"threadId"},
    "v2/ReviewStartParams.json": {"threadId", "target", "delivery"},
    "v2/ThreadGoalSetParams.json": {"threadId", "objective"},
    "v2/ModelListResponse.json": {"data"},
    "v2/GetAccountRateLimitsResponse.json": {"rateLimits", "rateLimitsByLimitId"},
    "v2/ListMcpServerStatusResponse.json": {"data"},
}

REQUIRED_DEFINITION_PROPERTIES = {
    ("v2/HookStartedNotification.json", "HookRunSummary"): {"id", "eventName", "status", "durationMs"},
    ("v2/TurnCompletedNotification.json", "Turn"): {"id", "status", "error", "durationMs"},
    ("v2/ThreadStartResponse.json", "Thread"): {"id"},
    ("ToolRequestUserInputParams.json", "ToolRequestUserInputQuestion"): {"id", "question", "options", "isSecret"},
    ("ToolRequestUserInputResponse.json", "ToolRequestUserInputAnswer"): {"answers"},
}

REQUIRED_ENUM_VALUES = {
    ("PermissionsRequestApprovalResponse.json", "PermissionGrantScope"): {"turn", "session"},
    ("v2/HookStartedNotification.json", "HookRunStatus"): {"running", "completed", "failed", "blocked", "stopped"},
    ("v2/HookStartedNotification.json", "HookEventName"): {"preToolUse", "postToolUse"},
    ("v2/TurnCompletedNotification.json", "TurnStatus"): {"completed", "interrupted", "failed"},
    ("v2/ThreadStartParams.json", "SandboxMode"): {"read-only", "workspace-write"},
    ("CommandExecutionRequestApprovalResponse.json", "CommandExecutionApprovalDecision"): {
        "accept", "acceptForSession", "decline", "cancel",
    },
    ("FileChangeRequestApprovalResponse.json", "FileChangeApprovalDecision"): {
        "accept", "acceptForSession", "decline", "cancel",
    },
}

REQUIRED_ITEM_FIELDS = {
    "userMessage": {"id", "content"},
    "agentMessage": {"id", "text"},
    "reasoning": {"id"},
    "commandExecution": {"id", "command", "cwd", "status", "exitCode", "durationMs"},
    "fileChange": {"id", "changes", "status"},
}


@pytest.fixture(scope="module")
def schema_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    try:
        executable = CodexAdapter().discover()
    except AdapterUnavailableError:
        pytest.skip("Codex is not installed; the app-server contract can only be read from an installed release")
    output = tmp_path_factory.mktemp("codex-app-server-schema")
    completed = subprocess.run(
        [str(executable), "app-server", "generate-json-schema", "--out", str(output)],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-2000:]
    return output


def _load(schema_dir: Path, name: str) -> dict[str, Any]:
    path = schema_dir / name
    assert path.is_file(), f"Codex no longer publishes {name}"
    return json.loads(path.read_text(encoding="utf-8"))


def _methods(document: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            method = (node.get("properties") or {}).get("method") or {}
            found.update(method.get("enum") or ())
            if "const" in method:
                found.add(method["const"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return found


def _enum_values(definition: dict[str, Any]) -> set[str]:
    values = set(definition.get("enum") or ())
    for option in definition.get("oneOf") or definition.get("anyOf") or ():
        values.update(option.get("enum") or ())
    return values


def test_codex_still_publishes_the_methods_the_workbench_uses(schema_dir: Path) -> None:
    missing = {
        kind: sorted(required - _methods(_load(schema_dir, f"{kind}.json")))
        for kind, required in REQUIRED_METHODS.items()
    }
    assert not any(missing.values()), f"Codex app-server methods removed: {missing}"


def test_codex_still_publishes_the_fields_the_workbench_reads(schema_dir: Path) -> None:
    missing = {}
    for name, required in REQUIRED_PROPERTIES.items():
        absent = required - set(_load(schema_dir, name).get("properties", {}))
        if absent:
            missing[name] = sorted(absent)
    for (name, definition), required in REQUIRED_DEFINITION_PROPERTIES.items():
        schema = _load(schema_dir, name).get("definitions", {}).get(definition, {})
        absent = required - set(schema.get("properties", {}))
        if absent:
            missing[f"{name}#{definition}"] = sorted(absent)
    assert not missing, f"Codex app-server fields removed: {missing}"


def test_codex_still_accepts_the_enum_values_the_workbench_sends_and_reads(schema_dir: Path) -> None:
    missing = {}
    for (name, definition), required in REQUIRED_ENUM_VALUES.items():
        schema = _load(schema_dir, name).get("definitions", {}).get(definition, {})
        absent = required - _enum_values(schema)
        if absent:
            missing[f"{name}#{definition}"] = sorted(absent)
    assert not missing, f"Codex app-server enum values removed: {missing}"


def test_codex_thread_items_keep_the_fields_the_workbench_renders(schema_dir: Path) -> None:
    variants = {}
    for option in _load(schema_dir, "v2/ItemStartedNotification.json")["definitions"]["ThreadItem"]["oneOf"]:
        item_type = ((option.get("properties") or {}).get("type") or {}).get("enum") or [None]
        variants[item_type[0]] = set(option.get("properties", {}))
    missing = {
        item_type: sorted(required - variants.get(item_type, set()))
        for item_type, required in REQUIRED_ITEM_FIELDS.items()
        if required - variants.get(item_type, set())
    }
    assert not missing, f"Codex thread item fields removed: {missing}"
