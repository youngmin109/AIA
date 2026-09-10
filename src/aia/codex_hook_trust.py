"""Optional Codex app-server inspection for installed Hook trust state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any


@dataclass(frozen=True, slots=True)
class CodexHookTrustInspection:
    """Safe metadata returned by Codex's ``hooks/list`` request."""

    available: bool
    reason: str | None = None
    hooks: tuple[dict[str, object], ...] = ()

    def to_mapping(self) -> dict[str, object]:
        return {
            "available": self.available,
            "reason": self.reason,
            "hooks": [dict(item) for item in self.hooks],
        }


def summarize_aia_hooks(
    data: object,
    *,
    hook_path: str | Path,
) -> CodexHookTrustInspection:
    """Extract only AIA Hook trust metadata from an app-server response."""

    if not isinstance(data, Mapping):
        return CodexHookTrustInspection(False, "INVALID_APP_SERVER_RESPONSE")
    result = data.get("result")
    if not isinstance(result, Mapping):
        error = data.get("error")
        return CodexHookTrustInspection(
            False,
            "APP_SERVER_REQUEST_FAILED" if error is not None else "APP_SERVER_RESPONSE_MISSING",
        )
    rows = result.get("data")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return CodexHookTrustInspection(False, "APP_SERVER_HOOK_DATA_MISSING")
    expected = _normalize_path(hook_path)
    selected: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        entries = row.get("hooks")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            source_path = entry.get("sourcePath")
            command = entry.get("command")
            if _normalize_path(source_path) != expected:
                continue
            if not isinstance(command, str) or not command.strip():
                continue
            selected.append(
                {
                    "event": str(entry.get("eventName") or "UNKNOWN"),
                    "enabled": bool(entry.get("enabled")),
                    "trust_status": str(entry.get("trustStatus") or "UNKNOWN").upper(),
                    "matcher": str(entry.get("matcher") or ""),
                    "command_sha256": _sha256_text(command),
                    "key": str(entry.get("key") or ""),
                }
            )
    return CodexHookTrustInspection(True, hooks=tuple(selected))


def inspect_codex_hook_trust(
    executable: str | Path,
    *,
    hook_path: str | Path,
    cwd: str | Path | None = None,
    timeout: float = 8.0,
) -> CodexHookTrustInspection:
    """Ask the discovered Codex executable for the current AIA Hook trust state.

    This is diagnostic only. It never writes Codex configuration and never trusts
    a Hook. Unsupported Codex versions return an unavailable inspection.
    """

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    command = [str(Path(executable).expanduser().resolve(strict=False)), "app-server", "--stdio"]
    process: subprocess.Popen[str] | None = None
    lines: queue.Queue[str] = queue.Queue()
    reader: threading.Thread | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=str(Path(cwd).expanduser().resolve(strict=False)) if cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_safe_environment(),
        )
        if process.stdin is None or process.stdout is None:
            return CodexHookTrustInspection(False, "APP_SERVER_STREAM_UNAVAILABLE")

        def read_lines() -> None:
            assert process is not None and process.stdout is not None
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        _send(process, {"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "aia", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}})
        if _read_response(lines, 1, timeout) is None:
            return CodexHookTrustInspection(False, "APP_SERVER_INITIALIZE_TIMEOUT")
        _send(process, {"method": "initialized", "params": {}})
        _send(process, {"method": "hooks/list", "id": 2, "params": {"cwds": [str(Path(cwd or Path.cwd()).resolve(strict=False))]}})
        response = _read_response(lines, 2, timeout)
        if response is None:
            return CodexHookTrustInspection(False, "APP_SERVER_HOOK_LIST_TIMEOUT")
        return summarize_aia_hooks(response, hook_path=hook_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return CodexHookTrustInspection(False, "APP_SERVER_UNAVAILABLE")
    finally:
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if reader is not None:
            reader.join(timeout=0.5)


def _send(process: subprocess.Popen[str], payload: Mapping[str, object]) -> None:
    if process.stdin is None:
        raise OSError("app-server stdin is unavailable")
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _read_response(
    lines: queue.Queue[str],
    request_id: int,
    timeout: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            return None
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("id") == request_id:
            return value
    return None


def _normalize_path(value: object) -> str:
    if not isinstance(value, (str, Path)):
        return ""
    return os.path.normcase(os.path.normpath(str(value)))


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            environment.pop(key, None)
    return environment


__all__ = [
    "CodexHookTrustInspection",
    "inspect_codex_hook_trust",
    "summarize_aia_hooks",
]
