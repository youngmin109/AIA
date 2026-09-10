"""Codex CLI adapter based on the locally verified command contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any

from ..codex_installation import AIA_CODEX_HOOK_MATCHER
from ..launcher import (
    AdapterError,
    AdapterUnavailableError,
    AgentLaunchSpec,
    AgentRuntimeMetadata,
    ProtectedLaunchRequest,
)


@dataclass(frozen=True, slots=True)
class CodexExecutionObservation:
    """Bounded, non-sensitive classification of one Codex output stream."""

    output_sha256: str
    output_bytes: int
    block_message_count: int
    no_run_message_count: int
    block_confirmation_available: bool
    reason: str
    effective_approval_policy: str | None = None
    effective_sandbox: str | None = None

    def to_mapping(self) -> dict[str, object]:
        """Return only safe metadata suitable for a Result Bundle."""

        return {
            "block_confirmation_available": self.block_confirmation_available,
            "effective_approval_policy": self.effective_approval_policy,
            "effective_sandbox": self.effective_sandbox,
            "block_message_count": self.block_message_count,
            "no_run_message_count": self.no_run_message_count,
            "output_bytes": self.output_bytes,
            "output_sha256": self.output_sha256,
            "reason": self.reason,
        }


class CodexAdapter:
    """Translate a protected launch request into a Codex ``exec`` argv."""

    _ALLOWED_OPTIONS = frozenset(
        {
            "add_dir",
            "approve_for_me",
            "approval_policy",
            "color",
            "ignore_rules",
            "ignore_user_config",
            "json",
            "interactive",
            "mcp_server",
            "profile",
            "sandbox",
            "skip_git_repo_check",
        }
    )
    _FORBIDDEN_OPTIONS = frozenset(
        {
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
        enable_hooks: bool = False,
    ) -> None:
        if not isinstance(executable_name, str) or not executable_name.strip():
            raise AdapterError("executable_name must be non-empty")
        self.executable_name = executable_name
        if hook_command is not None and (not isinstance(hook_command, str) or not hook_command.strip()):
            raise AdapterError("hook_command must be non-empty when provided")
        self.hook_command = hook_command
        self.allow_hook_trust_bypass = allow_hook_trust_bypass
        if not isinstance(enable_hooks, bool):
            raise AdapterError("enable_hooks must be a boolean")
        self.enable_hooks = enable_hooks

    @property
    def name(self) -> str:
        return "codex"

    def discover(self) -> Path:
        configured = os.environ.get("CODEX_CLI_PATH")
        if configured:
            configured_path = Path(configured).expanduser().resolve(strict=False)
            if self._is_executable_candidate(configured_path):
                return configured_path

        # PATH is the user's active Codex selection. Prefer it over another
        # side-by-side installation so the executable used for Hook trust is
        # the same one the user starts from their terminal/Codex setup.
        for candidate in self._path_candidates():
            if self._is_executable_candidate(candidate):
                return candidate

        candidates: list[Path] = []
        candidates.extend(self._windows_install_candidates())
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = Path(path).expanduser().resolve(strict=False)
            if not resolved.is_file() or resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        if unique:
            return max(unique, key=self._discovery_sort_key)
        raise AdapterUnavailableError("Codex executable is unavailable")

    def _path_candidates(self) -> tuple[Path, ...]:
        if self.executable_name.lower().endswith(".exe"):
            lookup_names = (self.executable_name,)
        else:
            lookup_names = (f"{self.executable_name}.exe", self.executable_name)
        candidates: list[Path] = []
        for candidate in lookup_names:
            resolved = shutil.which(candidate)
            if resolved is not None:
                candidates.append(Path(resolved).expanduser().resolve(strict=False))
        return tuple(candidates)

    @staticmethod
    def _is_executable_candidate(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() not in {".cmd", ".bat", ".ps1"}

    @classmethod
    def _discovery_sort_key(cls, path: Path) -> float:
        """Prefer the most recently installed Codex CLI when several exist."""

        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

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
        if self.enable_hooks and self.hook_command is None:
            # Product launches use the installed user-level Hook definition.
            # Enable the Codex Hook feature explicitly without changing the
            # user's Hook entries or bypassing Codex trust.
            argv.extend(("-c", "features.hooks=true"))
        if self.hook_command is not None:
            argv.extend(
                (
                    "-c",
                    "features.hooks=true",
                )
            )
            for hook_config in self._hook_configs(self.hook_command):
                argv.extend(("-c", hook_config))
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
            f"hooks.PreToolUse=[{{matcher=\"{AIA_CODEX_HOOK_MATCHER}\","
            f"hooks=[{{type=\"command\",command={encoded},commandWindows={encoded}}}]}}]"
        )

    @classmethod
    def _hook_configs(cls, command: str) -> tuple[str, ...]:
        """Build the enforcement and post-tool observation overrides."""

        import json

        encoded = json.dumps(command, ensure_ascii=False)
        handler = (
            f"[{{matcher=\"{AIA_CODEX_HOOK_MATCHER}\","
            f"hooks=[{{type=\"command\",command={encoded},commandWindows={encoded}}}]}}]"
        )
        return (
            f"hooks.PreToolUse={handler}",
            f"hooks.PostToolUse={handler}",
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
        if "approval_policy" in options:
            value = options["approval_policy"]
            if value not in {"on-request", "on-failure", "untrusted"}:
                raise AdapterError("Codex approval policy is not allowed for protected launches")
            import json

            argv.extend(("-c", f"approval_policy={json.dumps(value)}"))
        if "approve_for_me" in options:
            value = options["approve_for_me"]
            if not isinstance(value, bool):
                raise AdapterError("Codex approve_for_me option is invalid")
            if value:
                if "sandbox" in options:
                    raise AdapterError(
                        "Codex approve_for_me cannot be combined with explicit approval or sandbox"
                    )
                # Current Codex CLI exposes the safe workspace-write +
                # on-request execution contract through this flag.  Keep the
                # dangerous full-access bypass options rejected above.
                argv.append("--approve-for-me")
        if "mcp_server" in options:
            CodexAdapter._append_mcp_server(argv, options["mcp_server"])
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
    def _append_mcp_server(argv: list[str], value: Any) -> None:
        """Add one narrow stdio MCP server without exposing arbitrary -c overrides."""

        import json

        if not isinstance(value, Mapping):
            raise AdapterError("mcp_server must be an object")
        name = value.get("name")
        command = value.get("command")
        args = value.get("args", ())
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", name)
            or not isinstance(command, str)
            or not command.strip()
            or not isinstance(args, (tuple, list))
            or any(not isinstance(item, str) for item in args)
        ):
            raise AdapterError("mcp_server must contain a safe name, command, and string args")
        prefix = f"mcp_servers.{name}"
        argv.extend(("-c", f"{prefix}.command={json.dumps(command)}"))
        if args:
            # Codex's Windows TOML override parser treats backslash-heavy
            # array literals as a scalar string.  Forward slashes are valid
            # Windows paths and keep the value a real TOML sequence.
            normalized_args = [
                item.replace("\\", "/")
                if os.name == "nt" and re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", item)
                else item
                for item in args
            ]
            argv.extend(("-c", f"{prefix}.args={json.dumps(normalized_args)}"))

    @staticmethod
    def parse_runtime_metadata(line: str) -> AgentRuntimeMetadata | None:
        """Keep native-session parsing disabled until a verified schema exists."""

        return None

    @staticmethod
    def classify_execution_output(
        stdout: bytes,
        stderr: bytes,
        *,
        posttool_observed: bool,
    ) -> CodexExecutionObservation:
        """Classify native Codex block output without retaining its raw text.

        The confirmation contract is deliberately narrow: Codex must report a
        PreToolUse block and that the command did not run, the matching
        PostToolUse event must be absent, and the caller must separately verify
        the agent process exited normally.  This helper only supplies the
        bounded output evidence; it never emits an enforcement result itself.
        """

        combined = bytes(stdout) + b"\0" + bytes(stderr)
        digest = hashlib.sha256(combined).hexdigest()
        # Keep classification bounded even if an Agent prints a very large
        # response.  Both ends cover Codex's header and final result message.
        sample_limit = 262_144
        sample = (
            combined
            if len(combined) <= sample_limit * 2
            else combined[:sample_limit] + combined[-sample_limit:]
        )
        text = sample.decode("utf-8", errors="replace").casefold()
        approval_match = re.search(r"\bapproval:\s*([^\r\n]+)", text)
        sandbox_match = re.search(r"\bsandbox:\s*([^\r\n]+)", text)
        effective_approval_policy = approval_match.group(1).strip() if approval_match else None
        effective_sandbox = sandbox_match.group(1).strip() if sandbox_match else None
        block_markers = (
            "command was blocked by the pretooluse hook",
            "command blocked by the pretooluse hook",
            "tool call was blocked by the pretooluse hook",
            "hook: pretooluse blocked",
        )
        no_run_markers = ("it did not run", "did not run")
        block_count = sum(text.count(marker) for marker in block_markers)
        no_run_count = sum(text.count(marker) for marker in no_run_markers)
        if posttool_observed:
            reason = "POSTTOOL_OBSERVED"
        elif block_count == 0:
            reason = "CODEX_BLOCK_MESSAGE_MISSING"
        elif no_run_count == 0 and "hook: pretooluse blocked" in text:
            reason = "CODEX_HOOK_BLOCKED_EVENT"
        elif no_run_count == 0:
            reason = "CODEX_NO_RUN_MESSAGE_MISSING"
        else:
            reason = "CODEX_BLOCK_AND_NO_RUN_MESSAGE"
        return CodexExecutionObservation(
            output_sha256=digest,
            output_bytes=len(combined),
            block_message_count=block_count,
            no_run_message_count=no_run_count,
            block_confirmation_available=(
                block_count > 0
                and (no_run_count > 0 or "hook: pretooluse blocked" in text)
                and not posttool_observed
            ),
            reason=reason,
            effective_approval_policy=effective_approval_policy,
            effective_sandbox=effective_sandbox,
        )


__all__ = ["CodexAdapter", "CodexExecutionObservation"]
