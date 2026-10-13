"""Codex CLI adapter based on the locally verified command contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import RLock
from typing import Any

from ..codex_installation import AIA_CODEX_HOOK_MATCHER
from ..launcher import (
    AdapterError,
    AdapterUnavailableError,
    AgentLaunchSpec,
    AgentRuntimeMetadata,
    ProtectedLaunchRequest,
)


# The only extra config a protected app-server accepts: each value turns one
# Codex external tool (MCP server, plugin, or ChatGPT apps) off, nothing else.
_EXTERNAL_TOOL_OFF = re.compile(
    r"(?:mcp_servers\.[A-Za-z0-9_-]{1,100}|plugins\.[A-Za-z0-9_-]{1,100}@[A-Za-z0-9_-]{1,100})\.enabled=false"
    r"|features\.apps=false"
)

_VERSION_CACHE_LOCK = RLock()
_VERSION_CACHE: dict[tuple[str, int], tuple[int, int, int] | None] = {}


def _hidden_process_kwargs() -> dict[str, int]:
    """Prevent version probes from opening a transient Windows console."""

    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


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
            "app_server",
            "approve_for_me",
            "approval_policy",
            "color",
            "disable_external_tools",
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

        # The interactive Windows command may be a PowerShell/npm wrapper while
        # AIA launches the native executable. Compare all discoverable native
        # candidates by their reported Codex version so Hook trust and the
        # protected child use the same installed release. PATH candidates still
        # win ties and remain the default when version output is unavailable.
        candidates: dict[Path, int] = {}
        for path in self._path_candidates():
            resolved = Path(path).expanduser().resolve(strict=False)
            candidates[resolved] = 2
        for path in self._windows_install_candidates():
            resolved = Path(path).expanduser().resolve(strict=False)
            candidates[resolved] = max(candidates.get(resolved, 0), 1)
        valid = [
            (path, source_priority)
            for path, source_priority in candidates.items()
            if self._is_executable_candidate(path)
        ]
        if valid:
            return max(valid, key=self._discovery_sort_key)[0]
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
    def _discovery_sort_key(
        cls,
        candidate: tuple[Path, int],
    ) -> tuple[bool, tuple[int, int, int], int, float]:
        """Prefer the newest verified Codex version, then PATH candidates."""

        path, source_priority = candidate
        version = cls._executable_version(path)

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (
            version is not None,
            version or (0, 0, 0),
            source_priority,
            mtime,
        )

    @staticmethod
    def _executable_version(path: Path) -> tuple[int, int, int] | None:
        """Read a bounded semantic version without retaining command output."""

        try:
            resolved = path.resolve(strict=False)
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            return None
        cache_key = (str(resolved), mtime_ns)
        with _VERSION_CACHE_LOCK:
            if cache_key in _VERSION_CACHE:
                return _VERSION_CACHE[cache_key]
            try:
                completed = subprocess.run(
                    [str(path), "--version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                    **_hidden_process_kwargs(),
                )
            except (OSError, subprocess.TimeoutExpired):
                # A failed launch or a timeout under load is transient; caching
                # it would report Codex as unavailable until the binary changes.
                return None
            else:
                output = completed.stdout.decode("utf-8", errors="replace")
                match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", output)
                version = (
                    tuple(int(group) for group in match.groups())
                    if match is not None
                    else None
                )
            stale_keys = [
                key for key in _VERSION_CACHE if key[0] == cache_key[0] and key != cache_key
            ]
            for key in stale_keys:
                del _VERSION_CACHE[key]
            _VERSION_CACHE[cache_key] = version  # type: ignore[assignment]
            return version  # type: ignore[return-value]

    @classmethod
    def executable_version(cls, path: Path | str) -> str:
        """Return the selected executable version without exposing its output."""

        version = cls._executable_version(Path(path))
        return ".".join(str(part) for part in version) if version else "unknown"

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
        app_server = options.pop("app_server", False)
        if not isinstance(app_server, bool):
            raise AdapterError("app_server must be a boolean")
        if app_server:
            if not interactive:
                raise AdapterError("app_server requires interactive mode")
            return self._build_app_server_launch(request, executable, options)
        if "disable_external_tools" in options:
            raise AdapterError("turning off external tools is only supported by app-server")
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

    def _build_app_server_launch(
        self,
        request: ProtectedLaunchRequest,
        executable: Path,
        options: Mapping[str, Any],
    ) -> AgentLaunchSpec:
        """Launch ``codex app-server`` for the Workbench conversation.

        The app-server has no TUI flags, so the protected sandbox and approval
        policy are applied as inline config overrides.  The Workbench passes
        them again when it starts the thread and records what Codex reports as
        applied.  The workspace and model are thread parameters, not argv.
        External tools that may run outside the Hook are turned off with
        validated ``-c`` overrides that can only disable them.
        """

        unsupported = set(options) - {"approval_policy", "sandbox", "disable_external_tools"}
        if unsupported:
            raise AdapterError("the requested Codex option is not supported by app-server")
        if self.hook_command is not None or not self.enable_hooks:
            # Only the product path (installed, user-trusted Hook definition)
            # is verified with app-server; inline Hook definitions are not.
            raise AdapterError("app-server launches require the installed Codex Hook")
        if request.prompt.strip():
            raise AdapterError("interactive Codex launch cannot receive an initial prompt")
        argv: list[str] = [str(executable), "app-server"]
        approval_policy = options.get("approval_policy", "on-request")
        sandbox = options.get("sandbox", "workspace-write")
        # Full access is a user choice for the Workbench conversation
        # and comes only as the complete pair; the installed, trusted Hook
        # required above still checks every tool call.
        full_access = (sandbox, approval_policy) == ("danger-full-access", "never")
        if not full_access and approval_policy not in {"on-request", "on-failure", "untrusted"}:
            raise AdapterError("Codex approval policy is not allowed for protected launches")
        if not full_access and sandbox not in {"read-only", "workspace-write"}:
            raise AdapterError("Codex sandbox is not allowed for protected launches")
        import json

        argv.extend(("-c", f"approval_policy={json.dumps(approval_policy)}"))
        argv.extend(("-c", f"sandbox_mode={json.dumps(sandbox)}"))
        argv.extend(("-c", "features.hooks=true"))
        external_tools_off = options.get("disable_external_tools", ())
        if not isinstance(external_tools_off, (list, tuple)) or len(external_tools_off) > 200:
            raise AdapterError("disable_external_tools must be a list")
        for item in external_tools_off:
            if not isinstance(item, str) or not _EXTERNAL_TOOL_OFF.fullmatch(item):
                raise AdapterError("only turning off Codex external tools is allowed")
            argv.extend(("-c", item))
        return AgentLaunchSpec(
            adapter=self.name,
            executable=executable,
            argv=tuple(argv),
            stdin_bytes=b"",
            interactive=True,
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
