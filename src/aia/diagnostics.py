"""Redacted diagnostics for AIA installation and protected-run support."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from tempfile import NamedTemporaryFile
from typing import Any

from ._version import __version__
from .codex_hook_trust import inspect_codex_hook_trust
from .codex_installation import CodexHookInstaller
from .adapters.codex import CodexAdapter
from .hook_verification import HookVerificationStore


def _path_fingerprint(path: Path) -> str:
    """Return a stable fingerprint without exposing the local path."""

    return hashlib.sha256(
        str(path.expanduser().resolve(strict=False)).casefold().encode("utf-8")
    ).hexdigest()


def _control_root_writable(control_root: Path) -> bool:
    try:
        control_root.mkdir(parents=True, exist_ok=True)
        probe = control_root / ".aia-support-write-test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _trust_summary(inspection: dict[str, object]) -> dict[str, object]:
    hooks = inspection.get("hooks")
    if not isinstance(hooks, list):
        hooks = []
    return {
        "available": bool(inspection.get("available")),
        "reason": inspection.get("reason"),
        "events": [
            {
                "event": item.get("event"),
                "enabled": item.get("enabled"),
                "trust_status": item.get("trust_status"),
                "matcher_sha256": (
                    hashlib.sha256(str(item.get("matcher", "")).encode("utf-8")).hexdigest()
                    if item.get("matcher") is not None
                    else None
                ),
            }
            for item in hooks
            if isinstance(item, dict)
        ],
    }


def build_support_bundle(
    *,
    control_root: str | Path | None = None,
    hook_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a safe, shareable diagnostics document.

    The document deliberately excludes full local paths, Workspace contents,
    raw evidence, tool input, command output, and Result Bundle payloads.
    """

    root = (
        Path(control_root).expanduser().resolve(strict=False)
        if control_root is not None
        else (Path.home() / ".aia" / "control").resolve(strict=False)
    )
    installer = CodexHookInstaller(hook_path)
    executable: Path | None = None
    executable_version = "unknown"
    executable_error: str | None = None
    try:
        executable = CodexAdapter().discover()
        executable_version = CodexAdapter().executable_version(executable)
    except Exception as error:  # diagnostics must remain available when Codex is absent
        executable_error = type(error).__name__

    inspection = {"available": False, "reason": "CODEX_UNAVAILABLE", "hooks": []}
    if executable is not None and installer.is_installed():
        inspection = inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
            timeout=8.0,
        ).to_mapping()

    verification = HookVerificationStore(root)
    verification_current = False
    if executable is not None:
        try:
            verification_current = verification.is_current(installer, executable)
        except (OSError, ValueError):
            verification_current = False

    recent_runs: list[dict[str, object]] = []
    try:
        from aia_app.readers import ResultBundleReader

        completed = ResultBundleReader(root).list_completed()
        for item in completed[:5]:
            recent_runs.append(
                {
                    "ended_at": item.get("ended_at"),
                    "status": item.get("status"),
                    "protection_state": item.get("protection_state"),
                    "bundle_status": item.get("bundle_status"),
                    "hook_event_count": item.get("hook_event_count", 0),
                    "posttool_event_count": item.get("posttool_event_count", 0),
                    "incident_count": item.get("incident_count", 0),
                }
            )
    except (OSError, ValueError, KeyError):
        recent_runs = []

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "product": {"name": "AIA", "version": __version__},
        "runtime": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
        },
        "codex": {
            "available": executable is not None,
            "version": executable_version,
            "executable_name": executable.name if executable is not None else None,
            "error_type": executable_error,
        },
        "hook": {
            "pretool_installed": installer.is_installed(),
            "posttool_installed": installer.is_posttool_installed(),
            "path_sha256": _path_fingerprint(installer.path),
            "trust": _trust_summary(inspection),
            "verification_current": verification_current,
        },
        "control_root": {
            "writable": _control_root_writable(root),
            "path_sha256": _path_fingerprint(root),
        },
        "recent_runs": recent_runs,
        "supported_scope": {
            "os": "Windows 11",
            "agent": "Codex CLI",
            "pretool_matchers": [
                "Bash",
                "apply_patch",
                "Edit",
                "Write",
                "mcp__filesystem__read_file",
                "mcp__fs__read",
            ],
        },
        "privacy": {
            "full_paths_included": False,
            "workspace_contents_included": False,
            "raw_evidence_included": False,
            "tool_input_included": False,
            "command_output_included": False,
        },
    }


def write_support_bundle(path: str | Path, bundle: dict[str, Any]) -> Path:
    """Write diagnostics atomically as UTF-8 JSON."""

    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(bundle, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, target)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = ["build_support_bundle", "write_support_bundle"]
