"""Standard-library-only forwarder for the Codex command Hook.

Codex starts ``aia-cli.exe hook runtime`` before and after every tool call.
That process only forwards the native payload to the per-run AIA broker,
which makes the policy decision.  Importing the ``aia`` package for this
forward cost about 0.4 s per call, so this module imports nothing from AIA
and talks to the loopback broker over a plain socket.

The observable behavior matches ``aia.codex_hook_runtime.main`` run through
``aia.cli``:

- unbound Hook (no endpoint): neutral exit 0 without output;
- bound Hook: any failure takes Codex's blocking path (exit 2 + stderr);
- a non-empty broker object is printed to stdout as one JSON line.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, BinaryIO, Mapping, TextIO


ENDPOINT_ENV = "AIA_CODEX_HOOK_ENDPOINT"
CAPABILITY_ENV = "AIA_CODEX_HOOK_CAPABILITY"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024


class HookForwardError(RuntimeError):
    """Raised when a bound Hook cannot get a usable broker answer."""


def _split_endpoint(endpoint: str) -> tuple[str, int, str]:
    """Return host, port and path of the broker's ``http://host:port/path``."""

    prefix = "http://"
    if not endpoint.startswith(prefix):
        raise HookForwardError(f"AIA Hook Broker endpoint must be http: {endpoint}")
    netloc, _, path = endpoint[len(prefix):].partition("/")
    host, separator, port = netloc.rpartition(":")
    if not separator or not host or not port.isdigit():
        raise HookForwardError(f"AIA Hook Broker endpoint has no host and port: {endpoint}")
    return host.strip("[]"), int(port), "/" + path


def _read_response(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise HookForwardError("AIA Hook Broker response is too large")
        chunks.append(chunk)


def _parse_response(raw: bytes) -> dict[str, Any]:
    head, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise HookForwardError("AIA Hook Broker response is not HTTP")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0].split(" ", 2)
    if len(status) < 2 or not status[0].startswith("HTTP/"):
        raise HookForwardError("AIA Hook Broker response is not HTTP")
    if status[1] != "200":
        # urllib raised HTTPError for these, which the Hook treated as an
        # unavailable broker.  Keep that fail-closed outcome.
        raise HookForwardError(f"AIA Hook Broker unavailable: HTTP {status[1]}")
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
            if len(body) < length:
                raise HookForwardError("AIA Hook Broker response was truncated")
            body = body[:length]
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HookForwardError(f"AIA Hook Broker unavailable: {error}") from error
    if not isinstance(value, dict):
        raise HookForwardError("AIA Hook Broker response must be an object")
    return value


def forward(payload: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Send one Hook payload to the bound broker and return its JSON object."""

    endpoint = environ.get(ENDPOINT_ENV)
    capability = environ.get(CAPABILITY_ENV)
    if not endpoint:
        return {}
    if not capability:
        # An endpoint without its per-run capability is a partially bound
        # Protected Run.  An empty exit-0 response would let Codex continue.
        raise HookForwardError("AIA Hook Broker capability is missing")
    host, port, path = _split_endpoint(endpoint)
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    head = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Content-Type: application/json\r\n"
        f"X-AIA-Capability: {capability}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("latin-1")
    try:
        # Connect directly: the broker is a loopback endpoint, so the payload
        # and capability never go through an HTTP proxy from the environment.
        with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as connection:
            connection.sendall(head + body)
            raw = _read_response(connection)
    except OSError as error:
        raise HookForwardError(f"AIA Hook Broker unavailable: {error}") from error
    return _parse_response(raw)


def run(stdin: BinaryIO, stdout: TextIO, stderr: TextIO, environ: Mapping[str, str]) -> int:
    """Run one Hook invocation with explicit streams and environment."""

    try:
        payload = json.loads(stdin.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Codex Hook stdin must be a JSON object")
        result = forward(payload, environ)
        if result:
            stdout.write(json.dumps(result, ensure_ascii=False))
            stdout.write("\n")
        return 0
    except Exception as error:
        # Exit code 2 is Codex's documented blocking path for a PreToolUse
        # command hook.  It is used only when this Hook is attached to an AIA
        # Protected Run; an unbound Hook stays neutral.
        if environ.get(ENDPOINT_ENV):
            stderr.write(f"AIA protection unavailable: {error}\n")
            return 2
        return 0


def _configure_console_encoding() -> None:
    """Match ``aia.cli._configure_console_encoding`` for the Hook streams."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def main() -> int:
    _configure_console_encoding()
    return run(sys.stdin.buffer, sys.stdout, sys.stderr, os.environ)


__all__ = ["HookForwardError", "forward", "main", "run"]
