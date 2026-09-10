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

    _MATCHER = "Bash|apply_patch|Edit|Write"

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

    @property
    def hook_entry(self) -> dict[str, Any]:
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
        entries = hooks.get("PreToolUse")
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

    def install(self) -> Path:
        document = self._read()
        hooks = document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise CodexHookInstallationError("hooks must be a JSON object")
        entries = hooks.setdefault("PreToolUse", [])
        if not isinstance(entries, list):
            raise CodexHookInstallationError("hooks.PreToolUse must be a JSON array")
        if not self.is_installed():
            entries.append(self.hook_entry)
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
                f"could not install Codex Hook at {self.path}"
            ) from error
        return self.path

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
