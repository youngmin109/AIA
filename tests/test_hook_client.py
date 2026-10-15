"""The stdlib Hook forwarder must behave exactly like the AIA Hook runtime."""

from __future__ import annotations

from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import aia.codex_hook_runtime as codex_hook_runtime
import aia_hook_client
from aia import CodexHookBroker


CAPABILITY = "test-capability"
PROXY_VARIABLES = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")
DENY = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "비밀정보 읽기는 정책으로 금지되어 있어요",
    }
}


class _BinaryStdin(BytesIO):
    @property
    def buffer(self):
        return self


def _payload(command: str = "Get-Content -LiteralPath 'release\\connection-check.json'") -> dict:
    return {
        "session_id": "native-1",
        "turn_id": "turn-1",
        "tool_use_id": "tool-1",
        "cwd": "C:/workspace/demo",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "hook_event_name": "PreToolUse",
    }


class _Broker:
    def __init__(self, tmp_path: Path, handler) -> None:
        self.received: list[dict] = []

        def recording_handler(payload):
            self.received.append(dict(payload))
            return handler(payload)

        self.broker = CodexHookBroker(
            capability_secret=CAPABILITY,
            session_id="session-1",
            launch_id="launch-1",
            control_root=tmp_path / "control",
            handler=recording_handler,
        )
        self.broker.start()

    @property
    def endpoint(self) -> str:
        return self.broker.environment["AIA_CODEX_HOOK_ENDPOINT"]

    def stop(self) -> None:
        self.broker.stop()


@pytest.fixture(autouse=True)
def _no_proxies(monkeypatch) -> None:
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def _environment(endpoint: str | None, capability: str | None) -> dict[str, str]:
    environment = {}
    if endpoint is not None:
        environment["AIA_CODEX_HOOK_ENDPOINT"] = endpoint
    if capability is not None:
        environment["AIA_CODEX_HOOK_CAPABILITY"] = capability
    return environment


def _run_existing(monkeypatch, capsys, stdin: bytes, environment: dict[str, str]):
    monkeypatch.delenv("AIA_CODEX_HOOK_ENDPOINT", raising=False)
    monkeypatch.delenv("AIA_CODEX_HOOK_CAPABILITY", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(stdin))
    code = codex_hook_runtime.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _run_forwarder(stdin: bytes, environment: dict[str, str]):
    stdout, stderr = StringIO(), StringIO()
    code = aia_hook_client.run(BytesIO(stdin), stdout, stderr, environment)
    return code, stdout.getvalue(), stderr.getvalue()


def _raise(payload):
    raise RuntimeError("handler failure")


@pytest.mark.parametrize(
    ("scenario", "handler", "stdin", "binding", "expected_code", "expected_stderr"),
    [
        ("unbound", lambda payload: DENY, json.dumps(_payload()).encode(), "none", 0, ""),
        ("allow-empty", lambda payload: {}, json.dumps(_payload()).encode(), "bound", 0, ""),
        ("deny-korean", lambda payload: DENY, json.dumps(_payload(), ensure_ascii=False).encode(), "bound", 0, ""),
        ("wrong-capability", lambda payload: DENY, json.dumps(_payload()).encode(), "wrong", 2, "AIA protection unavailable"),
        ("handler-error", _raise, json.dumps(_payload()).encode(), "bound", 2, "AIA protection unavailable"),
        ("broker-down", lambda payload: DENY, json.dumps(_payload()).encode(), "down", 2, "AIA protection unavailable"),
        ("partial-binding", lambda payload: DENY, json.dumps(_payload()).encode(), "partial", 2, "capability is missing"),
        ("invalid-json-bound", lambda payload: DENY, b"{not json", "bound", 2, "AIA protection unavailable"),
        ("invalid-json-unbound", lambda payload: DENY, b"{not json", "none", 0, ""),
        ("non-object-bound", lambda payload: DENY, b"[1, 2]", "bound", 2, "must be a JSON object"),
        ("non-object-response", lambda payload: [1], json.dumps(_payload()).encode(), "bound", 2, "AIA protection unavailable"),
    ],
)
def test_forwarder_matches_existing_hook_runtime(
    tmp_path, monkeypatch, capsys, scenario, handler, stdin, binding, expected_code, expected_stderr
) -> None:
    broker = _Broker(tmp_path, handler)
    try:
        endpoint = broker.endpoint
        if binding == "down":
            broker.stop()
        environment = {
            "none": _environment(None, None),
            "bound": _environment(endpoint, CAPABILITY),
            "wrong": _environment(endpoint, "wrong-capability"),
            "down": _environment(endpoint, CAPABILITY),
            "partial": _environment(endpoint, None),
        }[binding]

        existing = _run_existing(monkeypatch, capsys, stdin, environment)
        forwarded = _run_forwarder(stdin, environment)
    finally:
        broker.stop()

    assert forwarded[0] == existing[0] == expected_code, scenario
    assert forwarded[1] == existing[1], scenario
    assert expected_stderr in existing[2]
    assert expected_stderr in forwarded[2]
    if expected_code == 0 and existing[1]:
        assert json.loads(forwarded[1]) == DENY


def test_forwarder_sends_the_same_payload_as_existing_hook_runtime(tmp_path, monkeypatch, capsys) -> None:
    broker = _Broker(tmp_path, lambda payload: DENY)
    payload = json.dumps(_payload("python scripts/sync_backup.py"), ensure_ascii=False).encode()
    environment = _environment(broker.endpoint, CAPABILITY)
    try:
        _run_existing(monkeypatch, capsys, payload, environment)
        _run_forwarder(payload, environment)
    finally:
        broker.stop()

    assert len(broker.received) == 2
    assert broker.received[0] == broker.received[1] == json.loads(payload)


def test_forwarder_reaches_loopback_broker_even_when_a_proxy_is_configured(tmp_path) -> None:
    broker = _Broker(tmp_path, lambda payload: DENY)
    environment = {
        **_environment(broker.endpoint, CAPABILITY),
        "HTTP_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
    }
    try:
        code, out, err = _run_forwarder(json.dumps(_payload()).encode(), environment)
    finally:
        broker.stop()

    assert (code, err) == (0, "")
    assert json.loads(out) == DENY


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"garbage", "not HTTP"),
        (b"SMTP 200 OK\r\n\r\n{}", "not HTTP"),
        (b"HTTP/1.0 403 Forbidden\r\nContent-Length: 2\r\n\r\n{}", "HTTP 403"),
        (b"HTTP/1.0 200 OK\r\nContent-Length: 10\r\n\r\n{}", "truncated"),
        (b"HTTP/1.0 200 OK\r\n\r\nnot-json", "unavailable"),
        (b"HTTP/1.0 200 OK\r\n\r\n[]", "must be an object"),
    ],
)
def test_forwarder_rejects_unusable_broker_responses(raw, message) -> None:
    with pytest.raises(aia_hook_client.HookForwardError, match=message):
        aia_hook_client._parse_response(raw)


def test_forwarder_rejects_endpoint_without_host_and_port() -> None:
    with pytest.raises(aia_hook_client.HookForwardError):
        aia_hook_client.forward(_payload(), _environment("http://127.0.0.1/pretool", CAPABILITY))
    with pytest.raises(aia_hook_client.HookForwardError):
        aia_hook_client.forward(_payload(), _environment("https://127.0.0.1:1/pretool", CAPABILITY))


def test_packaged_cli_entry_forwards_without_importing_aia(tmp_path) -> None:
    """`aia-cli.exe hook runtime` runs cli.py as __main__; it must skip AIA imports."""

    broker = _Broker(tmp_path, lambda payload: DENY)
    cli_path = Path(__file__).resolve().parents[1] / "src" / "aia" / "cli.py"
    probe = (
        "import runpy, sys\n"
        "sys.argv = ['aia-cli', 'hook', 'runtime']\n"
        "code = 0\n"
        "try:\n"
        f"    runpy.run_path({str(cli_path)!r}, run_name='__main__')\n"
        "except SystemExit as exit:\n"
        "    code = exit.code\n"
        "sys.stderr.write('AIA_IMPORTED=' + str('aia' in sys.modules or 'aia_app' in sys.modules))\n"
        "sys.exit(code)\n"
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("AIA_") and key not in PROXY_VARIABLES
    }
    environment.update(broker.broker.environment)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            input=json.dumps(_payload()).encode("utf-8"),
            capture_output=True,
            env=environment,
            timeout=60,
        )
    finally:
        broker.stop()

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.decode("utf-8")) == DENY
    assert completed.stderr.decode("utf-8").endswith("AIA_IMPORTED=False")
    assert len(broker.received) == 1
