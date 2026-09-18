"""Install and inspect the stable AIA Codex command Hook definition."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
from typing import Any


class CodexHookInstallationError(ValueError):
    """Raised when the stable Codex Hook definition cannot be managed safely."""


AIA_CODEX_SUPPORTED_MATCHERS = (
    "Bash",
    "apply_patch",
)
# Codex accepts these names as matcher aliases for the canonical
# ``apply_patch`` tool. The Hook payload still reports ``tool_name`` as
# ``apply_patch``; keep the aliases separate from semantic tool names so the
# runtime never treats an alias as a different input schema.
AIA_CODEX_TOOL_ALIASES = {
    "apply_patch": ("Edit", "Write"),
}
# Receive every tool that Codex routes through the local PreToolUse/PostToolUse
# hook path. Semantic support remains explicit in
# ``AIA_CODEX_SUPPORTED_MATCHERS``; an unknown tool is denied by the bound
# Protected Run instead of silently bypassing the AIA boundary.
AIA_CODEX_HOOK_MATCHER = "*"


def _is_ephemeral_uv_python(path: Path) -> bool:
    """Return whether *path* belongs to uv's short-lived isolated environment."""

    parts = tuple(part.casefold() for part in path.resolve(strict=False).parts)
    return any(part.startswith("builds-v") for part in parts) and any(
        part.startswith(".tmp") for part in parts
    )


def _project_root() -> Path | None:
    """Find the source project root when AIA is running from a checkout."""

    source = Path(__file__).resolve()
    for candidate in (source.parent, *source.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


class CodexHookInstaller:
    """Manage one explicit user-level Hook entry without changing other hooks."""

    # Keep the matcher explicit. These are the Codex tool names for which
    # the current product has an explicit semantic contract. MCP is outside
    # the current product boundary and is therefore handled as unsupported.
    _MATCHER = AIA_CODEX_HOOK_MATCHER
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
            else self._default_hook_path()
        )
        self.python_executable = str(
            Path(python_executable or sys.executable).expanduser().resolve(strict=False)
        )
        self._command_tokens = self._resolve_command_tokens(
            explicit_python=python_executable is not None
        )

    def _resolve_command_tokens(self, *, explicit_python: bool) -> tuple[str, ...]:
        """Use a stable uv command when the caller runs from uv's temp env.

        ``uv run --isolated`` gives each invocation a different temporary
        interpreter. Persisting that interpreter in Codex's Hook config makes
        the next AIA command report the Hook as missing. The project and uv
        executable paths are stable across those invocations, so use them as
        the Hook launcher in that specific case. Explicit test/runtime paths
        retain the historical direct-Python behavior.
        """

        python_path = Path(self.python_executable)
        if not explicit_python and getattr(sys, "frozen", False):
            executable_name = python_path.name.casefold()
            if executable_name in {"aia.exe", "aia"}:
                return (self.python_executable, "hook", "runtime")
            if executable_name in {"aia-cli.exe", "aia-cli"}:
                return (self.python_executable, "hook", "runtime")

            candidates = (
                python_path.parent / "aia-cli" / "aia-cli.exe",
                python_path.parent.parent / "aia-cli" / "aia-cli.exe",
                python_path.parent / "aia-cli.exe",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return (str(candidate), "hook", "runtime")
            raise CodexHookInstallationError(
                "aia-cli.exe is not installed next to the AIA desktop application"
            )

        if explicit_python or not _is_ephemeral_uv_python(python_path):
            return (self.python_executable, "-m", "aia.codex_hook_runtime")

        project = _project_root()
        uv = shutil.which("uv")
        if project is None or uv is None:
            return (self.python_executable, "-m", "aia.codex_hook_runtime")
        return (
            str(Path(uv).expanduser().resolve(strict=False)),
            "run",
            "--quiet",
            "--project",
            str(project),
            "--isolated",
            "python",
            "-m",
            "aia.codex_hook_runtime",
        )

    @staticmethod
    def _default_hook_path() -> Path:
        """Resolve the same Codex home that the CLI uses for its config."""

        configured = os.environ.get("CODEX_HOME")
        root = (
            Path(configured).expanduser().resolve(strict=False)
            if configured
            else (Path.home() / ".codex").resolve(strict=False)
        )
        return root / "hooks.json"

    @property
    def command(self) -> str:
        return subprocess.list2cmdline(list(self._command_tokens))

    @property
    def uses_uv_launcher(self) -> bool:
        """Whether the Hook is launched through uv's stable project command."""

        return len(self._command_tokens) > 1 and Path(
            self._command_tokens[0]
        ).name.casefold() in {"uv", "uv.exe"}

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

    def has_aia_runtime(self, event: str = "PreToolUse") -> bool:
        """Return whether an AIA runtime handler exists for *event*.

        This deliberately does not mean that the handler is usable.  A stale
        isolated-Python path or another checkout can leave an AIA handler in
        ``hooks.json`` whose exact command differs from this installer.  The
        distinction lets the CLI explain that situation without accepting the
        stale handler as current.
        """

        if event not in self._EVENTS:
            raise CodexHookInstallationError(f"unsupported AIA Hook event: {event}")
        try:
            document = self._read()
        except (OSError, ValueError, TypeError):
            return False
        hooks = document.get("hooks")
        entries = hooks.get(event) if isinstance(hooks, Mapping) else None
        if not isinstance(entries, list):
            return False
        return any(
            isinstance(entry, Mapping)
            and any(
                self._is_aia_runtime_handler(handler)
                for handler in (entry.get("hooks") or ())
            )
            for entry in entries
        )

    def install(self) -> Path:
        document = self._read()
        hooks = document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise CodexHookInstallationError("hooks must be a JSON object")
        for event in self._EVENTS:
            entries = hooks.setdefault(event, [])
            if not isinstance(entries, list):
                raise CodexHookInstallationError(f"hooks.{event} must be a JSON array")
            entries[:] = self._migrate_event_entries(entries, event)
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
                    handler
                    for handler in handlers
                    if not self._is_aia_runtime_handler(handler)
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

    def _migrate_event_entries(
        self,
        entries: list[Any],
        event: str,
    ) -> list[Any]:
        """Replace stale AIA handlers while preserving unrelated handlers.

        The command contains the installed Python executable, so upgrading
        AIA can otherwise leave an old handler beside the new one.  Matching
        the stable module name lets us migrate only AIA-owned handlers.  A
        changed command still requires the user's normal Codex Hook review.
        """

        migrated: list[Any] = []
        current_found = False
        for entry in entries:
            if not isinstance(entry, dict):
                migrated.append(entry)
                continue
            handlers = entry.get("hooks")
            if not isinstance(handlers, list):
                migrated.append(entry)
                continue

            retained: list[Any] = []
            contains_current = False
            for handler in handlers:
                if not self._is_aia_runtime_handler(handler):
                    retained.append(handler)
                    continue
                if self._is_aia_handler(handler) and not current_found:
                    retained.append(handler)
                    current_found = True
                    contains_current = True
                # Stale AIA handlers and duplicate current handlers are
                # intentionally omitted.

            if contains_current:
                entry["matcher"] = self._MATCHER
            if retained:
                entry["hooks"] = retained
                migrated.append(entry)
            elif handlers:
                # The entry contained only AIA handlers.  Remove the empty
                # group without touching neighboring user Hook groups.
                continue
            else:
                migrated.append(entry)

        if not current_found:
            migrated.append(self.hook_entry(event))
        return migrated

    @staticmethod
    def _is_aia_runtime_command(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            tokens = shlex.split(value, posix=False)
        except ValueError:
            return False
        normalized = [token.strip('"').casefold() for token in tokens]
        if any(
            token == "-m"
            and index + 1 < len(normalized)
            and normalized[index + 1] == "aia.codex_hook_runtime"
            for index, token in enumerate(normalized)
        ):
            return True
        return any(
            token.replace("\\", "/").rsplit("/", 1)[-1]
            in {"aia.exe", "aia", "aia-cli.exe", "aia-cli"}
            and index + 2 < len(normalized)
            and normalized[index + 1 : index + 3] == ["hook", "runtime"]
            for index, token in enumerate(normalized)
        )

    def _is_aia_runtime_handler(self, handler: object) -> bool:
        return (
            isinstance(handler, Mapping)
            and handler.get("type") == "command"
            and (
                self._is_aia_runtime_command(handler.get("command"))
                or self._is_aia_runtime_command(handler.get("commandWindows"))
            )
        )

    def _is_aia_handler(self, handler: object) -> bool:
        return (
            self._is_aia_runtime_handler(handler)
            and isinstance(handler, Mapping)
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
            and entry.get("matcher") == self._MATCHER
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


__all__ = [
    "AIA_CODEX_SUPPORTED_MATCHERS",
    "AIA_CODEX_TOOL_ALIASES",
    "AIA_CODEX_HOOK_MATCHER",
    "CodexHookInstallationError",
    "CodexHookInstaller",
]
