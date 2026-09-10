"""Install and inspect the stable AIA Codex command Hook definition."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile
from typing import Any


class CodexHookInstallationError(ValueError):
    """Raised when the stable Codex Hook definition cannot be managed safely."""


class CodexHookInstaller:
    """Manage one explicit user-level Hook entry without changing other hooks."""

    # Keep the matcher explicit. These are the Codex tool names for which
    # AIA has an explicit semantic contract. Unknown MCP tools are not treated
    # as file operations by name alone.
    _MATCHER = (
        "Bash|apply_patch|Edit|Write|"
        "mcp__filesystem__read_file|mcp__fs__read"
    )
    _EVENTS = ("PreToolUse", "PostToolUse")

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        python_executable: str | Path | None = None,
    ) -> None:
        self.path = (
            Path(path).expanduser().resolve(strict=False)
            if path is not None
            else (Path.home() / ".codex" / "hooks.json").resolve(strict=False)
        )
        self.python_executable = str(
            Path(python_executable or sys.executable).expanduser().resolve(strict=False)
        )

    @property
    def command(self) -> str:
        return subprocess.list2cmdline(
            [self.python_executable, "-m", "aia.codex_hook_runtime"]
        )

    def hook_entry(self, event: str = "PreToolUse") -> dict[str, Any]:
        if event not in self._EVENTS:
            raise CodexHookInstallationError(f"unsupported AIA Hook event: {event}")
        return {
            "matcher": self._MATCHER,
            "hooks": [
                {
                    "type": "command",
                    "command": self.command,
                    "commandWindows": self.command,
                    "timeout": 30,
                }
            ],
        }

    def is_installed(self) -> bool:
        try:
            document = self._read()
        except (OSError, ValueError, TypeError):
            return False
        hooks = document.get("hooks")
        if not isinstance(hooks, Mapping):
            return False
        return self._is_event_installed(hooks, "PreToolUse")

    def is_posttool_installed(self) -> bool:
        """Return whether optional post-tool observation is configured."""

        try:
            document = self._read()
        except (OSError, ValueError, TypeError):
            return False
        hooks = document.get("hooks")
        return isinstance(hooks, Mapping) and self._is_event_installed(
            hooks, "PostToolUse"
        )

    def is_fully_installed(self) -> bool:
        """Return whether both pre-tool enforcement and post-tool evidence exist."""

        return self.is_installed() and self.is_posttool_installed()

    def install(self) -> Path:
        document = self._read()
        hooks = document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise CodexHookInstallationError("hooks must be a JSON object")
        for event in self._EVENTS:
            entries = hooks.setdefault(event, [])
            if not isinstance(entries, list):
                raise CodexHookInstallationError(f"hooks.{event} must be a JSON array")
            command = self.command
            installed = any(
                isinstance(entry, Mapping)
                and any(
                    isinstance(handler, Mapping)
                    and handler.get("type") == "command"
                    and handler.get("command") == command
                    and handler.get("commandWindows", command) == command
                    for handler in (entry.get("hooks") or ())
                )
                for entry in entries
            )
            if not installed:
                entries.append(self.hook_entry(event))
            else:
                # Migrate only an existing AIA entry. User hooks and unrelated
                # matcher groups are left untouched.
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if any(
                        isinstance(handler, Mapping)
                        and handler.get("type") == "command"
                        and handler.get("command") == command
                        and handler.get("commandWindows", command) == command
                        for handler in (entry.get("hooks") or ())
                    ):
                        entry["matcher"] = self._MATCHER
        self._write(document)
        return self.path

    def uninstall(self) -> Path:
        """Remove only AIA's Hook handlers and preserve all user Hooks."""

        if not self.path.exists():
            return self.path
        document = self._read()
        hooks = document.get("hooks")
        if not isinstance(hooks, dict):
            return self.path

        changed = False
        for event in self._EVENTS:
            entries = hooks.get(event)
            if not isinstance(entries, list):
                continue
            retained_entries: list[Any] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    retained_entries.append(entry)
                    continue
                handlers = entry.get("hooks")
                if not isinstance(handlers, list):
                    retained_entries.append(entry)
                    continue
                retained_handlers = [
                    handler for handler in handlers if not self._is_aia_handler(handler)
                ]
                if len(retained_handlers) != len(handlers):
                    changed = True
                if retained_handlers:
                    entry["hooks"] = retained_handlers
                    retained_entries.append(entry)
                elif handlers:
                    changed = True
                else:
                    retained_entries.append(entry)
            if len(retained_entries) != len(entries):
                changed = True
            hooks[event] = retained_entries

        if changed:
            self._write(document)
        return self.path

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
        except OSError as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise CodexHookInstallationError(
                f"could not update Codex Hook at {self.path}"
            ) from error

    def _is_aia_handler(self, handler: object) -> bool:
        return (
            isinstance(handler, Mapping)
            and handler.get("type") == "command"
            and handler.get("command") == self.command
            and handler.get("commandWindows", self.command) == self.command
        )

    def _is_event_installed(self, hooks: Mapping[str, Any], event: str) -> bool:
        entries = hooks.get(event)
        if not isinstance(entries, list):
            return False
        command = self.command
        return any(
            isinstance(entry, Mapping)
            and any(
                isinstance(handler, Mapping)
                and handler.get("type") == "command"
                and handler.get("command") == command
                and handler.get("commandWindows", command) == command
                for handler in (entry.get("hooks") or ())
            )
            for entry in entries
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodexHookInstallationError(
                f"Codex Hook configuration is not valid JSON: {self.path}"
            ) from error
        if not isinstance(value, dict):
            raise CodexHookInstallationError("Codex Hook configuration must be a JSON object")
        return value


__all__ = ["CodexHookInstallationError", "CodexHookInstaller"]
