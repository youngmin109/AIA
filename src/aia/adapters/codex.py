"""Codex CLI adapter based on the locally verified command contract."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import shutil
from typing import Any

from ..launcher import (
    AdapterError,
    AdapterUnavailableError,
    AgentLaunchSpec,
    AgentRuntimeMetadata,
    ProtectedLaunchRequest,
)


class CodexAdapter:
    """Translate a protected launch request into a Codex ``exec`` argv."""

    _ALLOWED_OPTIONS = frozenset(
        {
            "add_dir",
            "color",
            "ignore_rules",
            "ignore_user_config",
            "json",
            "interactive",
            "profile",
            "sandbox",
            "skip_git_repo_check",
        }
    )
    _FORBIDDEN_OPTIONS = frozenset(
        {
            "approve_for_me",
            "dangerously_bypass_approvals_and_sandbox",
            "dangerously_bypass_hook_trust",
            "full_access",
            "yolo",
        }
    )

    def __init__(
        self,
        *,
        executable_name: str = "codex",
        hook_command: str | None = None,
        allow_hook_trust_bypass: bool = False,
    ) -> None:
        if not isinstance(executable_name, str) or not executable_name.strip():
            raise AdapterError("executable_name must be non-empty")
        self.executable_name = executable_name
        if hook_command is not None and (not isinstance(hook_command, str) or not hook_command.strip()):
            raise AdapterError("hook_command must be non-empty when provided")
        self.hook_command = hook_command
        self.allow_hook_trust_bypass = allow_hook_trust_bypass

    @property
    def name(self) -> str:
        return "codex"

    def discover(self) -> Path:
        candidates = []
        if self.executable_name.lower().endswith(".exe"):
            candidates.append(self.executable_name)
        else:
            candidates.extend((f"{self.executable_name}.exe", self.executable_name))
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved is None:
                continue
            path = Path(resolved).expanduser().resolve(strict=False)
            if path.is_file() and path.suffix.lower() == ".exe":
                return path
            if path.is_file() and path.suffix.lower() not in {".cmd", ".bat", ".ps1"}:
                return path
        for path in self._windows_install_candidates():
            if path.is_file():
                return path
        raise AdapterUnavailableError("Codex executable is unavailable")

    def _windows_install_candidates(self) -> tuple[Path, ...]:
        """Find the per-user Windows Codex install when it is outside PATH."""

        if os.name != "nt" or self.executable_name.lower() not in {"codex", "codex.exe"}:
            return ()
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            local_app_data = str(Path.home() / "AppData" / "Local")
        roots = [Path(local_app_data) / "OpenAI" / "Codex" / "bin"]
        app_data = os.environ.get("APPDATA")
        if app_data:
            roots.append(
                Path(app_data)
                / "npm"
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-win32-x64"
                / "vendor"
                / "x86_64-pc-windows-msvc"
                / "bin"
            )
        candidates: list[Path] = []
        for root in roots:
            if root.name == "bin" and root.parent.name == "Codex":
                candidates.extend(root.glob("*/codex.exe"))
            else:
                candidates.append(root / "codex.exe")
        return tuple(
            sorted(
                (path.resolve(strict=False) for path in candidates),
                key=lambda path: path.stat().st_mtime if path.is_file() else 0,
                reverse=True,
            )
        )

    def build_launch(
        self,
        request: ProtectedLaunchRequest,
        executable: Path,
    ) -> AgentLaunchSpec:
        if request.agent.lower() != "codex":
            raise AdapterError("Codex Adapter received a non-Codex request")
        if request.resume_native_session_id is not None:
            # The local help output does not establish a safe stdin contract for
            # resume. Do not invent one from an unverified schema.
            raise AdapterError("Codex resume contract is not enabled")
        options = dict(request.adapter_options)
        unknown = set(options) - self._ALLOWED_OPTIONS
        if unknown:
            forbidden = unknown & self._FORBIDDEN_OPTIONS
            if forbidden:
                raise AdapterError("protected Codex permission option is not allowed")
            raise AdapterError("unsupported Codex adapter option")

        interactive = options.pop("interactive", False)
        if not isinstance(interactive, bool):
            raise AdapterError("interactive must be a boolean")
        if interactive and any(
            key in options for key in ("ignore_rules", "json", "skip_git_repo_check")
        ):
            raise AdapterError(
                "the requested Codex option is only supported in exec mode"
            )

        if interactive:
            # Interactive mode inherits the user's terminal.  AIA owns the
            # process and its Hook environment, while Codex owns the prompt
            # loop shown to the user.
            argv: list[str] = [
                str(executable),
                "-C",
                str(request.workspace),
                "--color",
                "never",
            ]
        else:
            argv = [
                str(executable),
                "exec",
                "-C",
                str(request.workspace),
                "--ephemeral",
                "--color",
                "never",
            ]
        if request.model is not None:
            argv.extend(("--model", request.model))
        self._append_options(argv, options)
        if self.hook_command is not None:
            argv.extend(
                (
                    "-c",
                    "features.hooks=true",
                    "-c",
                    self._hook_config(self.hook_command),
                )
            )
            if self.allow_hook_trust_bypass:
                argv.append("--dangerously-bypass-hook-trust")
        stdin_bytes = b""
        if interactive:
            if request.prompt.strip():
                raise AdapterError(
                    "interactive Codex launch cannot receive an initial prompt"
                )
        else:
            # ``-`` is the documented exec prompt form; the prompt is kept on
            # stdin instead of being exposed in the process command line.
            argv.append("-")
            stdin_bytes = request.prompt.encode("utf-8")
        return AgentLaunchSpec(
            adapter=self.name,
            executable=executable,
            argv=tuple(argv),
            stdin_bytes=stdin_bytes,
            interactive=interactive,
        )

    @staticmethod
    def _hook_config(command: str) -> str:
        """Build the smallest inline TOML override for the AIA Hook."""

        import json

        encoded = json.dumps(command, ensure_ascii=False)
        return (
            "hooks.PreToolUse=[{matcher=\"Bash|apply_patch|Edit|Write\","
            f"hooks=[{{type=\"command\",command={encoded},commandWindows={encoded}}}]}}]"
        )

    @staticmethod
    def _append_options(argv: list[str], options: Mapping[str, Any]) -> None:
        scalar_flags = {
            "profile": "--profile",
            "sandbox": "--sandbox",
            "color": "--color",
        }
        for key, flag in scalar_flags.items():
            if key in options:
                value = options[key]
                if not isinstance(value, str) or not value:
                    raise AdapterError("Codex option value is invalid")
                argv.extend((flag, value))
        if options.get("add_dir") is not None:
            values = options["add_dir"]
            if isinstance(values, str):
                values = (values,)
            if not isinstance(values, (tuple, list)) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise AdapterError("add_dir must contain path strings")
            for value in values:
                argv.extend(("--add-dir", value))
        bool_flags = {
            "ignore_user_config": "--ignore-user-config",
            "ignore_rules": "--ignore-rules",
            "json": "--json",
            "skip_git_repo_check": "--skip-git-repo-check",
        }
        for key, flag in bool_flags.items():
            if key in options:
                value = options[key]
                if not isinstance(value, bool):
                    raise AdapterError("Codex boolean option is invalid")
                if value:
                    argv.append(flag)

    @staticmethod
    def parse_runtime_metadata(line: str) -> AgentRuntimeMetadata | None:
        """Keep native-session parsing disabled until a verified schema exists."""

        return None


__all__ = ["CodexAdapter"]
