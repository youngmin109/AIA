"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Sequence
import webbrowser
from uuid import uuid4

from aia import (
    CodexAdapter,
    CodexHookInstallationError,
    CodexHookInstaller,
    CheckpointValidity,
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    Operation,
    PolicyProfile,
    ProtectedRunSession,
    RawEvidenceRecord,
    RawEvidenceStore,
    POLICY_PROFILE_DISPLAY_NAMES,
    ResolvedPolicy,
    SafeCheckpointManager,
    SessionEndReason,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    load_policy,
    prepare_protection,
    policy_content_sha256,
    resolve_profile,
)
from aia.hook_verification import HookVerificationStore
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.capabilities import product_capabilities
from aia.diagnostics import build_support_bundle, write_support_bundle
from aia._version import __version__
from aia_app import ApplicationValidationError, RunApplicationService
from aia_app.readers import ResultBundleReader
from aia_app.presenters import action_summary


_HOOK_VERIFICATION_PROBE_TOKEN_ENV = "AIA_HOOK_VERIFICATION_PROBE_TOKEN"


def _module_cli_prefix() -> str:
    """Return a launcher that does not depend on a generated ``aia.exe``."""

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve(strict=False)
        if executable.name.casefold() in {"aia-cli.exe", "aia-cli"}:
            return subprocess.list2cmdline([str(executable)])
        candidates = (
            executable.parent / "aia-cli" / "aia-cli.exe",
            executable.parent.parent / "aia-cli" / "aia-cli.exe",
            executable.parent / "aia-cli.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return subprocess.list2cmdline([str(candidate)])
        if executable.name.casefold() in {"aia.exe", "aia"}:
            return subprocess.list2cmdline([str(executable)])

    source = Path(__file__).resolve()
    project_root = next(
        (
            candidate
            for candidate in (source.parent, *source.parents)
            if (candidate / "pyproject.toml").is_file()
        ),
        None,
    )
    if project_root is not None:
        return subprocess.list2cmdline(
            [
                "uv",
                "run",
                "--isolated",
                "--project",
                str(project_root),
                "python",
                "-m",
                "aia.cli",
            ]
        )
    return subprocess.list2cmdline([sys.executable, "-m", "aia.cli"])


def _configure_console_encoding() -> None:
    """Keep CLI diagnostics usable on Windows consoles with a legacy code page."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Embedded callers and redirected streams may reject reconfiguration.
            # Their existing stream configuration remains usable in that case.
            continue


def _cli_prefix(installer: CodexHookInstaller) -> str:
    """Return a user-facing launcher that avoids a blocked console-script EXE."""

    # Keep the argument for callers that already pass the installer.  The
    # generated Windows console-script executable can be blocked by local
    # application-control policy even when the Python interpreter is allowed.
    # Always show the direct module path so setup/doctor guidance remains
    # executable in that environment as well.
    del installer
    return _module_cli_prefix()


def _json_text(value: object, *, default: object | None = None) -> str:
    options: dict[str, object] = {"ensure_ascii": True, "indent": 2}
    if default is not None:
        options["default"] = default
    return json.dumps(value, **options)


def _hidden_process_kwargs() -> dict[str, int]:
    """Prevent non-interactive diagnostic runs from opening Windows consoles."""

    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _self_cli_command(*arguments: str) -> list[str]:
    """Build a command that re-enters the current CLI in source or frozen mode."""

    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-m", "aia.cli", *arguments]


def _add_protected_run_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared interactive/one-shot Protected Run arguments."""

    parser.add_argument(
        "workspace",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Workspace directory; defaults to the current directory",
    )
    parser.add_argument(
        "--task",
        help="initial Codex task prompt; omit it to open an interactive protected session",
    )
    parser.add_argument("--policy", type=Path, help="custom policy JSON path")
    parser.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        help="policy profile name",
    )
    parser.add_argument("--model")
    parser.add_argument("--mode", default="ENFORCE", choices=("ENFORCE", "AUDIT"))
    parser.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root outside the protected Workspace",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="maximum wait in seconds",
    )
    parser.add_argument(
        "--_hook-verification-probe",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aia")
    parser.add_argument("--version", action="version", version=f"AIA {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    capabilities = commands.add_parser(
        "capabilities",
        help="show the bounded AIA support and claim contract",
    )
    capabilities.add_argument("--json", action="store_true", help="print machine-readable output")
    doctor = commands.add_parser(
        "doctor",
        help="check the local Codex/AIA protected-run setup",
    )
    doctor.add_argument("--json", action="store_true", help="print machine-readable output")
    doctor.add_argument("--hook-path", type=Path, help="hooks.json path")
    doctor.add_argument("--control-root", type=Path, help="AIA control root")
    self_test = commands.add_parser(
        "self-test",
        help="run a disposable AIA Core self-test without starting Codex",
    )
    self_test.add_argument("--json", action="store_true", help="print machine-readable output")
    demo = commands.add_parser(
        "demo",
        help="show the safe AIA product demo using a disposable Workspace",
    )
    demo.add_argument(
        "--live",
        action="store_true",
        help="after the Core demo, run the opt-in real Codex proof",
    )
    demo.add_argument(
        "--scenario",
        choices=(
            "normal",
            "block-canary",
            "block-apply-patch",
            "block-env",
            "block-windows-delete",
            "process-kill",
            "hook-block",
            "file-rollback",
        ),
        default="block-canary",
        help="live proof scenario or deterministic presentation scenario",
    )
    demo.add_argument(
        "--workspace",
        type=Path,
        help="dedicated Workspace for a deterministic presentation scenario",
    )
    demo.add_argument(
        "--control-root",
        type=Path,
        help="dedicated Control Root for a deterministic presentation scenario",
    )
    demo.add_argument(
        "--open",
        action="store_true",
        help="open the local Workbench console after a deterministic demo",
    )
    demo.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "product-e2e",
        help="directory for live proof artifacts",
    )
    demo.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait for the live proof in seconds",
    )
    runs = commands.add_parser(
        "runs",
        help="list protected-run history from the local Control Root",
    )
    runs.add_argument("--json", action="store_true", help="print machine-readable output")
    runs.add_argument("--limit", type=int, default=20, help="maximum number of runs to show")
    runs.add_argument("--control-root", type=Path, help="AIA control root")
    status = commands.add_parser(
        "status",
        help="inspect one protected run, including completed runs",
    )
    status.add_argument("session_id")
    status.add_argument("--json", action="store_true", help="print machine-readable output")
    status.add_argument("--control-root", type=Path, help="AIA control root")
    stop = commands.add_parser(
        "stop",
        help="request a safe user abort for one running Protected Run",
    )
    stop.add_argument("session_id")
    stop.add_argument("--json", action="store_true", help="print machine-readable output")
    stop.add_argument("--control-root", type=Path, help="AIA control root")
    reconcile = commands.add_parser(
        "reconcile",
        help="acknowledge a crashed Protected Run after its Agent root is gone",
    )
    reconcile.add_argument("session_id")
    reconcile.add_argument("--json", action="store_true", help="print machine-readable output")
    reconcile.add_argument("--control-root", type=Path, help="AIA control root")
    policy = commands.add_parser("policy", help="validate and inspect a policy")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    profiles = policy_commands.add_parser(
        "profiles",
        help="list the built-in Korean policy profiles",
    )
    profiles.add_argument("--json", action="store_true", help="print machine-readable output")
    init_policy = policy_commands.add_parser(
        "init",
        help="create a copy of a built-in policy profile for editing",
    )
    init_policy.add_argument("path", type=Path)
    init_policy.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        choices=(
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
        ),
        help="built-in profile to copy",
    )
    init_policy.add_argument("--force", action="store_true", help="replace an existing file")
    validate = policy_commands.add_parser(
        "validate",
        help="strictly validate a Korean or canonical policy JSON",
    )
    validate.add_argument("path", type=Path)
    validate.add_argument("--json", action="store_true", help="print machine-readable output")
    policy_evaluate = policy_commands.add_parser(
        "evaluate",
        help="preview a policy decision without starting an Agent",
    )
    policy_evaluate.add_argument(
        "--policy",
        type=Path,
        help="custom Korean or canonical policy JSON path",
    )
    policy_evaluate.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        choices=(
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
        ),
        help="built-in profile used when --policy is omitted",
    )
    policy_evaluate.add_argument(
        "--operation",
        required=True,
        choices=tuple(operation.value for operation in Operation),
        help="mechanical operation to preview",
    )
    policy_evaluate.add_argument(
        "--path",
        dest="target_path",
        help="canonical path target for file operations",
    )
    policy_evaluate.add_argument(
        "--command",
        dest="raw_command",
        help="raw command target for EXECUTE; the command is not run",
    )
    policy_evaluate.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable output",
    )
    hook = commands.add_parser("hook", help="manage the stable Codex Hook Adapter")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    install = hook_commands.add_parser("install", help="install the AIA Hook definition")
    install.add_argument("--path", type=Path, help="hooks.json path")
    uninstall = hook_commands.add_parser(
        "uninstall",
        help="remove only the AIA Hook definition",
    )
    uninstall.add_argument("--path", type=Path, help="hooks.json path")
    hook_status = hook_commands.add_parser(
        "status",
        help="show Hook installation and last observed protected-run activation",
    )
    hook_status.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_status.add_argument("--path", type=Path, help="hooks.json path")
    hook_status.add_argument("--control-root", type=Path, help="AIA control root")
    hook_explain = hook_commands.add_parser(
        "explain",
        help="explain the installed Hook review, trust, and verification steps",
    )
    hook_explain.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_explain.add_argument("--path", type=Path, help="hooks.json path")
    hook_explain.add_argument("--control-root", type=Path, help="AIA control root")
    hook_verify = hook_commands.add_parser(
        "verify",
        help="verify the installed Hook with one disposable live Codex run",
    )
    hook_verify.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_verify.add_argument("--path", type=Path, help="hooks.json path")
    hook_verify.add_argument("--control-root", type=Path, help="AIA control root")
    hook_verify.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait in seconds",
    )
    hook_runtime = hook_commands.add_parser(
        "runtime",
        help=argparse.SUPPRESS,
    )

    setup = commands.add_parser(
        "setup",
        help="install the AIA Hook and print the remaining trust steps",
    )
    setup.add_argument("--path", type=Path, help="hooks.json path")
    setup.add_argument("--json", action="store_true", help="print machine-readable output")

    support_bundle = commands.add_parser(
        "support-bundle",
        help="create redacted diagnostics for troubleshooting",
    )
    support_bundle.add_argument(
        "--output",
        type=Path,
        help="write the redacted diagnostics JSON to this path",
    )
    support_bundle.add_argument("--hook-path", type=Path, help="hooks.json path")
    support_bundle.add_argument("--control-root", type=Path, help="AIA control root")
    support_bundle.add_argument("--json", action="store_true", help="print machine-readable output")

    console = commands.add_parser(
        "console",
        help="start the local AIA Security Console",
    )
    console.add_argument(
        "--host",
        default=os.environ.get("AIA_WEB_HOST", "127.0.0.1"),
        help="bind address; localhost is the safe default",
    )
    console.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AIA_WEB_PORT", "8787")),
        help="local HTTP port",
    )
    console.add_argument(
        "--open",
        action="store_true",
        help="open the local console in the default browser",
    )
    console.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root to display in the local console",
    )
    console.add_argument(
        "--open-path",
        default="/",
        help="local console path to open when --open is used",
    )

    protect = commands.add_parser(
        "protect",
        help="run Codex inside an AIA Protected Run",
    )
    _add_protected_run_arguments(protect)
    start = commands.add_parser(
        "start",
        help="start an interactive AIA Protected Run; enter tasks after Codex opens",
    )
    _add_protected_run_arguments(start)
    proof = commands.add_parser(
        "proof",
        help="run an opt-in real Codex pretool proof in a disposable Workspace",
    )
    proof.add_argument(
        "--scenario",
        choices=(
            "normal",
            "block-canary",
            "block-apply-patch",
            "block-env",
            "block-windows-delete",
        ),
        default="block-canary",
        help="proof scenario; block-canary is the default safety demonstration",
    )
    proof.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "product-e2e",
        help="directory where the disposable proof artifact is written",
    )
    proof.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait in seconds",
    )
    proof.add_argument(
        "--json",
        action="store_true",
        help="print the complete machine-readable proof report",
    )
    return parser


def _control_root(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve(strict=False)
    configured = os.environ.get("AIA_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".aia" / "control").resolve(strict=False)


def _control_root_write_check(control_root: Path) -> tuple[bool, str]:
    """Check that AIA can create and remove a small control-root marker."""

    try:
        control_root.mkdir(parents=True, exist_ok=True)
        probe = control_root / ".aia-write-check"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as error:
        return False, f"Control Root is not writable: {type(error).__name__}"
    return True, "Control Root is writable"


def _recent_run_diagnostic(control_root: Path) -> dict[str, object] | None:
    """Return safe metadata from the most recent committed Protected Run."""

    cli_prefix = _cli_prefix(CodexHookInstaller())
    reader = ResultBundleReader(control_root)
    try:
        runs = reader.list_completed()
    except (OSError, ValueError, KeyError):
        return None
    if not runs:
        return None

    latest = runs[0]
    session_id = latest.get("session_id")
    if not isinstance(session_id, str):
        return None
    try:
        result = reader.read_result(session_id)
    except (OSError, ValueError, KeyError):
        return None

    limitations = tuple(
        str(item)
        for item in (result.get("limitations") or ())
        if isinstance(item, str) and item
    )
    execution = result.get("agent_execution")
    observation = execution.get("output_observation") if isinstance(execution, dict) else None
    effective_sandbox = None
    effective_approval_policy = None
    if isinstance(observation, dict):
        sandbox = observation.get("effective_sandbox")
        approval = observation.get("effective_approval_policy")
        effective_sandbox = str(sandbox) if isinstance(sandbox, str) and sandbox else None
        effective_approval_policy = (
            str(approval) if isinstance(approval, str) and approval else None
        )

    if {
        "CODEX_SANDBOX_DOWNGRADED",
        "CODEX_APPROVAL_POLICY_DOWNGRADED",
    }.intersection(limitations):
        next_step = (
            "Codex가 AIA가 요청한 실행 정책보다 약한 설정을 적용했습니다. "
            "sandbox/approval 설정을 확인한 뒤 다시 Hook 검증을 실행하세요."
        )
    elif not latest.get("hook_event_count"):
        next_step = (
            "Session에 연결된 Codex Hook Event가 없습니다. Codex에서 Hook을 검토·신뢰한 "
            f"뒤 {cli_prefix} hook verify를 다시 실행하세요."
        )
    elif str(latest.get("protection_state", "")).endswith("DEGRADED"):
        next_step = "보호 경계가 완전히 검증되지 않았습니다. Result Bundle의 제한사항을 확인하세요."
    else:
        next_step = "최근 실행의 Hook 계보와 Result Bundle이 확인되었습니다."

    return {
        "session_id": session_id,
        "ended_at": latest.get("ended_at"),
        "protection_state": latest.get("protection_state"),
        "bundle_status": latest.get("bundle_status"),
        "hook_event_count": latest.get("hook_event_count", 0),
        "limitations": list(limitations),
        "effective_sandbox": effective_sandbox,
        "effective_approval_policy": effective_approval_policy,
        "next_step": next_step,
    }


def _doctor(args: argparse.Namespace) -> int:
    """Check prerequisites without starting a Protected Run."""

    checks: list[dict[str, object]] = []

    supported_python = sys.version_info[:2] == (3, 13)
    checks.append(
        {
            "name": "python",
            "ok": supported_python,
            "value": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "detail": "Python 3.13 is required",
        }
    )

    adapter = CodexAdapter()
    executable: Path | None = None
    try:
        executable = adapter.discover()
        executable_version = adapter.executable_version(executable)
        checks.append(
            {
                "name": "codex_executable",
                "ok": True,
                "value": str(executable),
                "version": executable_version,
                "detail": f"Codex executable discovered (version {executable_version})",
            }
        )
    except Exception as error:
        executable_version = "unknown"
        checks.append(
            {
                "name": "codex_executable",
                "ok": False,
                "value": None,
                "version": executable_version,
                "detail": f"Codex executable unavailable: {type(error).__name__}",
            }
        )

    installer = CodexHookInstaller(args.hook_path)
    cli_prefix = _cli_prefix(installer)
    hook_installed = installer.is_installed()
    stale_hook_detected = not hook_installed and installer.has_aia_runtime("PreToolUse")
    posttool_installed = installer.is_posttool_installed()
    checks.append(
        {
            "name": "codex_hook",
            "ok": hook_installed,
            "stale": stale_hook_detected,
            "value": str(installer.path),
            "detail": (
                "Hook definition installed; review/trust it in Codex"
                if hook_installed
                else (
                    f"기존 AIA Hook 경로가 남아 있습니다. '{cli_prefix} setup'으로 현재 경로를 갱신하세요."
                    if stale_hook_detected
                    else f"Run '{cli_prefix} setup', then review/trust the Hook in Codex"
                )
            ),
        }
    )

    codex_hook_trust: dict[str, object] = {
        "available": False,
        "reason": "CODEX_EXECUTABLE_OR_HOOK_UNAVAILABLE",
        "hooks": [],
    }
    pretool_status: str | None = None
    posttool_status: str | None = None
    if executable is not None and hook_installed:
        codex_hook_trust = inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
            timeout=8.0,
        ).to_mapping()
        trust_entries = codex_hook_trust.get("hooks") or []
        pretool_status = next(
            (
                item.get("trust_status")
                for item in trust_entries
                if isinstance(item, dict) and item.get("event") == "preToolUse"
            ),
            None,
        )
        posttool_status = next(
            (
                item.get("trust_status")
                for item in trust_entries
                if isinstance(item, dict) and item.get("event") == "postToolUse"
            ),
            None,
        )
        trust_ok = pretool_status in {"TRUSTED", "MANAGED"}
        if pretool_status is None:
            trust_detail = "Codex 실제 PreToolUse Trust 상태를 확인할 수 없음"
        elif trust_ok:
            trust_detail = f"Codex PreToolUse Trust={pretool_status}"
        else:
            trust_detail = (
                f"Codex PreToolUse Trust={pretool_status}; Codex /hooks에서 AIA Hook을 검토·신뢰하세요."
            )
        checks.append(
            {
                "name": "codex_hook_trust",
                "ok": trust_ok,
                "value": (
                    f"PreToolUse={pretool_status or 'UNKNOWN'}, "
                    f"PostToolUse={posttool_status or 'UNKNOWN'}"
                ),
                "detail": trust_detail,
            }
        )

    control_root = _control_root(args.control_root)
    recent_run = _recent_run_diagnostic(control_root)
    hook_verified = bool(
        hook_installed
        and executable is not None
        and HookVerificationStore(control_root).is_current(installer, executable)
    )
    checks.append(
        {
            "name": "hook_verification",
            "ok": hook_verified,
            "value": str(HookVerificationStore(control_root).path),
            "detail": (
                "Live Codex Hook Event verification is current"
                if hook_verified
                else (
                    (
                        f"Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 '{cli_prefix} hook verify'를 실행하세요"
                        if any(
                            isinstance(item, dict)
                            and item.get("event") == "preToolUse"
                            and item.get("trust_status") not in {"TRUSTED", "MANAGED"}
                            for item in (codex_hook_trust.get("hooks") or [])
                        )
                        else f"Run '{cli_prefix} hook verify' after reviewing the Hook in Codex"
                    )
                    + (
                        f"; recent run: {recent_run['next_step']}"
                        if recent_run is not None
                        else ""
                    )
                )
            ),
        }
    )
    writable, detail = _control_root_write_check(control_root)
    checks.append(
        {
            "name": "control_root",
            "ok": writable,
            "value": str(control_root),
            "detail": detail,
        }
    )

    if not supported_python:
        readiness_code = "PYTHON_VERSION_UNSUPPORTED"
        next_step = "Python 3.13 환경에서 AIA를 다시 실행하세요."
    elif executable is None:
        readiness_code = "CODEX_EXECUTABLE_UNAVAILABLE"
        next_step = f"Codex CLI 설치와 PATH를 확인한 뒤 '{cli_prefix} doctor'를 다시 실행하세요."
    elif not hook_installed:
        readiness_code = "CODEX_HOOK_NOT_INSTALLED"
        next_step = (
            f"기존 AIA Hook 경로를 현재 환경으로 갱신하려면 '{cli_prefix} setup'을 실행하세요."
            if stale_hook_detected
            else f"'{cli_prefix} setup'을 실행한 뒤 Codex /hooks에서 AIA Hook을 검토하세요."
        )
    elif pretool_status not in {"TRUSTED", "MANAGED"}:
        readiness_code = "CODEX_HOOK_TRUST_REQUIRED"
        next_step = (
            "Codex /hooks에서 AIA PreToolUse Hook을 검토·신뢰한 뒤 "
            f"'{cli_prefix} hook verify'와 '{cli_prefix} doctor'를 순서대로 실행하세요."
        )
    elif not hook_verified:
        readiness_code = "HOOK_VERIFICATION_REQUIRED"
        next_step = f"'{cli_prefix} hook verify'를 실행한 뒤 '{cli_prefix} doctor'를 다시 실행하세요."
    elif not writable:
        readiness_code = "CONTROL_ROOT_NOT_WRITABLE"
        next_step = f"AIA Control Root 권한을 확인한 뒤 '{cli_prefix} doctor'를 다시 실행하세요."
    else:
        readiness_code = "READY"
        next_step = f"'{cli_prefix} protect <workspace>'로 보호 실행을 시작할 수 있습니다."

    payload = {
        "product": "AIA",
        "checks": checks,
        "ready": all(bool(item["ok"]) for item in checks),
        "readiness_code": readiness_code,
        "next_step": next_step,
        "codex_executable": str(executable) if executable is not None else None,
        "codex_version": executable_version,
        "optional_capabilities": {
            "posttool_observation": {
                "installed": posttool_installed,
                "detail": (
                    "PostToolUse evidence is enabled"
                    if posttool_installed
                    else "Run 'aia hook install' to add PostToolUse evidence"
                ),
            }
        },
        "codex_hook_trust": codex_hook_trust,
        "recent_protected_run": recent_run,
        "limitations": [
            "Hook trust is reviewed in Codex and cannot be proven by this local preflight command.",
            "The protected scope is Windows 11 + Codex CLI + supported PreToolUse matchers.",
        ],
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("AIA 환경 점검")
        for item in checks:
            mark = "PASS" if item["ok"] else "FAIL"
            print(f"[{mark}] {item['name']}: {item['detail']}")
            if item["value"]:
                print(f"      {item['value']}")
        print("[INFO] Codex에서 Hook을 직접 검토하고 신뢰해야 합니다.")
        print(
            "[INFO] PostToolUse 관찰: "
            f"{'설치됨' if posttool_installed else '선택 기능 미설치'}"
        )
        trust_entries = codex_hook_trust.get("hooks") or []
        if trust_entries:
            trust_summary = ", ".join(
                f"{item.get('event')}={item.get('trust_status')}"
                for item in trust_entries
                if isinstance(item, dict)
            )
            print(f"[INFO] Codex 실제 Hook Trust: {trust_summary}")
        print("[INFO] AIA는 지원 범위 밖의 실행을 보호 실행으로 주장하지 않습니다.")
        if recent_run is not None:
            print(
                "최근 Protected Run: "
                f"{recent_run['protection_state']} / Bundle {recent_run['bundle_status']}"
            )
            if recent_run["effective_sandbox"] or recent_run["effective_approval_policy"]:
                print(
                    "최근 Codex 실행 정책: "
                    f"sandbox={recent_run['effective_sandbox'] or 'unknown'}, "
                    f"approval={recent_run['effective_approval_policy'] or 'unknown'}"
                )
            print(f"[다음] {recent_run['next_step']}")
        print(f"[필수 조치] {next_step}")
        if not payload["ready"]:
            print(f"[도움말] 검토 순서가 헷갈리면 '{cli_prefix} hook explain'을 실행하세요.")
        print(f"결과: {'READY' if payload['ready'] else 'NOT_READY'}")
    return 0 if payload["ready"] else 1


def _capabilities(args: argparse.Namespace) -> int:
    """Print the support contract without touching a protected Workspace."""

    payload = product_capabilities()
    if args.json:
        print(_json_text(payload))
        return 0

    support = payload["support"]
    print("AIA 지원 범위")
    print(f"제품: {payload['product']} {payload['version']}")
    print(
        "환경: "
        f"{', '.join(support['operating_system'])} / "
        f"Python {', '.join(support['python'])} / "
        f"{', '.join(support['agent'])}"
    )
    print(f"실행 경계: {support['launch_boundary']}")
    print(f"보호 모드: {', '.join(support['modes'])}")
    print(f"Hook matcher: {support['pretool_matcher']}")
    print("지원 PreToolUse: " + ", ".join(support["pretool_matchers"]))
    aliases = support.get("pretool_aliases") or {}
    if aliases:
        print(
            "Codex matcher 별칭: "
            + ", ".join(
                f"{alias} → {canonical}"
                for canonical, values in aliases.items()
                for alias in values
            )
        )
    print(f"미지원 도구 처리: {support['unsupported_tool_behavior']}")
    print("실제 확인된 동작:")
    for item in payload["verified_behaviors"]:
        print(f"  - {item}")
    print("사용 전 필수 단계:")
    for item in payload["requires_user_action"]:
        print(f"  - {item}")
    print("지원하지 않거나 주장하지 않는 범위:")
    for item in payload["unsupported_or_unclaimed"]:
        print(f"  - {item}")
    print(f"보호 성공 판정: {payload['claim_rule']}")
    return 0


def _self_test(args: argparse.Namespace) -> int:
    """Exercise the disposable Core contracts without claiming live Codex proof."""

    cli_prefix = _cli_prefix(CodexHookInstaller())
    checks: list[dict[str, object]] = []
    workspace_root = Path(tempfile.mkdtemp(prefix="aia-self-test-workspace-"))
    control_root = Path(tempfile.mkdtemp(prefix="aia-self-test-control-"))
    session: ProtectedRunSession | None = None
    lease_manager = WorkspaceLeaseManager(control_root)
    lease = None

    def passed(name: str, detail: str) -> None:
        checks.append({"name": name, "status": "PASS", "detail": detail})

    try:
        (workspace_root / "README.md").write_text(
            "AIA disposable self-test\n",
            encoding="utf-8",
            newline="\n",
        )
        resolved = resolve_profile(PolicyProfile.PROTECTED_DEVELOPMENT)
        passed(
            "policy_profile_resolution",
            f"{resolved.policy_id} v{resolved.policy_version} / {len(resolved.policy.rules)} rules",
        )
        protected_preview = resolved.evaluate_target(
            operation=Operation.READ,
            path=".env",
        )
        if (
            protected_preview.policy_decision.value != "VIOLATION"
            or protected_preview.operation_effect is None
            or protected_preview.operation_effect.value != "DENY"
            or protected_preview.asset_type is None
            or protected_preview.asset_type.value != "SECRET"
        ):
            raise RuntimeError("protected profile did not deny .env READ")
        passed("protected_default_policy", ".env READ -> VIOLATION / DENY / SECRET")

        session = ProtectedRunSession(
            workspace=workspace_root,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
        )
        session.transition(SessionStatus.PREPARING)
        passed("workspace_validation", str(session.workspace))

        context = prepare_protection(
            session,
            resolved,
            control_root,
            lease_manager=lease_manager,
        )
        lease = context.workspace_lease
        passed("active_policy_freeze", str(context.active_policy.artifact_path))
        passed("workspace_lease", f"LIVE_MATCH / {lease.artifact_path}")

        checkpoint = SafeCheckpointManager().create(
            session,
            context,
            lease_manager=lease_manager,
        )
        validation = SafeCheckpointManager().validate(checkpoint)
        if validation.validity is not CheckpointValidity.VALID:
            raise RuntimeError(f"checkpoint validation returned {validation.validity}")
        passed("safe_checkpoint", f"VALID / {checkpoint.checkpoint_id}")

        evidence = RawEvidenceStore.for_session(control_root, session.session_id)
        evidence.append(
            RawEvidenceRecord(
                session_id=session.session_id,
                source=EvidenceSource.FILESYSTEM_WATCHER,
                record_type=EvidenceRecordType.FILESYSTEM_EVENT,
                captured_at=datetime.now(timezone.utc),
                observation_stage=ObservationStage.POST_ACTION,
                payload={"event_type": "self_test", "path": "README.md"},
                evidence_id="self-test-evidence",
            )
        )
        seal = evidence.seal()
        index = evidence.build_index()
        if seal.line_count != 1 or "self-test-evidence" not in index.entries:
            raise RuntimeError("Raw Evidence seal/index verification failed")
        passed("raw_evidence_seal", f"SEALED / {seal.sha256}")

        session.transition(
            SessionStatus.ABORTED,
            end_reason=SessionEndReason.USER_ABORT,
        )
        lease_manager.release(lease)
        lease = None
        passed("lifecycle_cleanup", f"{session.status.value} / lease released")
        payload: dict[str, object] = {
            "self_test": "AIA_CORE",
            "passed": True,
            "codex_live_proof": "NOT_RUN",
            "workspace": str(workspace_root),
            "control_root": str(control_root),
            "checks": checks,
            "next_step": (
                f"실제 Codex 보호는 {cli_prefix} hook verify 후 "
                f"{cli_prefix} protect로 별도 검증하세요."
            ),
        }
        exit_code = 0
    except Exception as error:
        checks.append(
            {
                "name": "core_self_test",
                "status": "FAIL",
                "detail": f"{type(error).__name__}: {error}",
            }
        )
        payload = {
            "self_test": "AIA_CORE",
            "passed": False,
            "codex_live_proof": "NOT_RUN",
            "checks": checks,
            "error": f"{type(error).__name__}: {error}",
            "next_step": "실패한 Core 점검의 detail을 확인하세요.",
        }
        exit_code = 1
    finally:
        if lease is not None:
            try:
                lease_manager.release(lease)
            except (OSError, ValueError):
                pass
        shutil.rmtree(workspace_root, ignore_errors=True)
        shutil.rmtree(control_root, ignore_errors=True)

    if args.json:
        print(_json_text(payload))
    else:
        print("AIA Core Self-Test")
        for item in payload["checks"]:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")
        print(f"결과: {'PASS' if payload['passed'] else 'FAIL'}")
        print("실제 Codex Hook 증명: 별도 실행 필요")
        print(f"[다음] {payload['next_step']}")
    return exit_code


def _demo(args: argparse.Namespace) -> int:
    """Give a first-time user one safe entry point into the product.

    The default demo only exercises disposable AIA Core state.  A real Codex
    run is opt-in because it consumes a Codex invocation and depends on the
    user's reviewed Hook trust state.
    """

    from aia.demo import (
        DEFAULT_DEMO_CONTROL_ROOT,
        DEFAULT_DEMO_WORKSPACE,
        DEMO_SCENARIOS,
        run_demo,
    )

    if args.scenario in DEMO_SCENARIOS:
        if args.live:
            raise ApplicationValidationError(
                "deterministic presentation scenarios cannot be combined with --live"
            )
        result = run_demo(
            args.scenario,
            workspace=args.workspace or DEFAULT_DEMO_WORKSPACE,
            control_root=args.control_root or DEFAULT_DEMO_CONTROL_ROOT,
        )
        print("AIA 시연용 Result Bundle 생성")
        print(f"시나리오: {result['title']} ({result['scenario']})")
        print(f"Session: {result['session_id']}")
        print(f"Workspace: {result['workspace']}")
        print(f"Control Root: {result['control_root']}")
        print(f"Bundle: {result['bundle_status']}")
        print("주의: DEMO_FIXTURE 결과이며 Actual Codex 실행 증명이 아닙니다.")
        if args.open:
            _run_console(
                argparse.Namespace(
                    host=os.environ.get("AIA_WEB_HOST", "127.0.0.1"),
                    port=int(os.environ.get("AIA_WEB_PORT", "8787")),
                    open=True,
                    control_root=Path(result["control_root"]),
                    open_path=f"/runs/{result['session_id']}/workbench",
                )
            )
        else:
            print(f"[다음] {result['next_step']}")
        return 0

    print("AIA 제품 데모")
    print("실제 프로젝트를 건드리지 않는 임시 Workspace에서 보호 흐름을 확인합니다.")
    print()
    total_steps = 2 if args.live else 1
    print(f"[1/{total_steps}] AIA Core 보호 흐름 확인")
    core_exit = _self_test(argparse.Namespace(json=False))
    if core_exit != 0:
        print("[중단] Core 데모가 실패했습니다. 실제 Codex를 시작하지 않습니다.")
        return core_exit

    if not args.live:
        print()
        print("[완료] Core 데모가 끝났습니다.")
        print("실제 Codex Hook 차단까지 확인하려면 먼저 Codex에서 Hook을 검토·신뢰한 뒤")
        cli_prefix = _cli_prefix(CodexHookInstaller())
        print(f"      {cli_prefix} hook verify")
        print(f"      {cli_prefix} demo --live")
        print("를 실행하세요.")
        return 0

    if args.timeout <= 0:
        raise ApplicationValidationError("timeout must be positive")

    print()
    print("[2/2] 실제 Codex PreToolUse 증명 시작")
    print("Hook Trust가 확인되지 않으면 Codex 도구를 실행하지 않고 원인만 기록합니다.")
    from aia.product_e2e import main as product_e2e_main

    return product_e2e_main(
        [
            "--scenario",
            args.scenario,
            "--output",
            str(args.output),
            "--timeout",
            str(args.timeout),
        ]
    )


def _support_bundle(args: argparse.Namespace) -> int:
    """Create or print diagnostics without exposing protected content."""

    bundle = build_support_bundle(
        control_root=_control_root(args.control_root),
        hook_path=args.hook_path,
    )
    written: Path | None = None
    if args.output is not None:
        written = write_support_bundle(args.output, bundle)

    if args.json:
        output: dict[str, object] = dict(bundle)
        if written is not None:
            output["output_path"] = str(written)
        print(_json_text(output))
        return 0

    print("AIA 지원 진단 번들")
    print(f"Version: {bundle['product']['version']}")
    runtime = bundle["runtime"]
    print(
        "환경: "
        f"Python {runtime['python']} / {runtime['platform']} {runtime['platform_release']}"
    )
    codex = bundle["codex"]
    print(
        "Codex: "
        f"{'확인됨' if codex['available'] else '없음'}"
        f" / {codex['version']}"
    )
    hook = bundle["hook"]
    trust_events = hook["trust"].get("events", [])
    trust_summary = ", ".join(
        f"{item.get('event')}={item.get('trust_status')}"
        for item in trust_events
        if isinstance(item, dict)
    ) or "확인할 수 없음"
    print(
        "Hook: "
        f"PreToolUse={'설치됨' if hook['pretool_installed'] else '없음'} / "
        f"PostToolUse={'설치됨' if hook['posttool_installed'] else '없음'} / "
        f"Trust={trust_summary}"
    )
    print(f"실시간 검증: {'CURRENT' if hook['verification_current'] else '필요'}")
    control = bundle["control_root"]
    print(f"Control Root 쓰기: {'가능' if control['writable'] else '불가'}")
    print(f"최근 보호 실행: {len(bundle['recent_runs'])}건 요약 포함")
    print("개인정보: 전체 경로·Workspace 내용·raw evidence·명령 출력은 포함하지 않음")
    if written is not None:
        print(f"저장 경로: {written}")
    else:
        print("JSON 파일로 저장하려면 --output <path>를 사용하세요.")
    return 0


def _setup(args: argparse.Namespace) -> int:
    """Install the stable Hook and make the manual trust boundary explicit."""

    installer = CodexHookInstaller(args.path)
    cli_prefix = _cli_prefix(installer)
    try:
        path = installer.install()
    except CodexHookInstallationError as error:
        payload = {
            "configured": False,
            "hook_path": str(installer.path),
            "error": str(error),
        }
        if args.json:
            print(_json_text(payload))
        else:
            print(f"AIA 설정 실패: {error}")
        return 2
    codex_hook_trust: dict[str, object] = {
        "available": False,
        "reason": "CODEX_EXECUTABLE_UNAVAILABLE",
        "hooks": [],
    }
    try:
        executable = CodexAdapter().discover()
        executable_version = CodexAdapter.executable_version(executable)
    except Exception:
        executable = None
        executable_version = "unknown"
    if executable is not None:
        codex_hook_trust = inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
            timeout=8.0,
        ).to_mapping()
    trust_entries = codex_hook_trust.get("hooks") or []
    pretool_trust_status = next(
        (
            item.get("trust_status")
            for item in trust_entries
            if isinstance(item, dict) and item.get("event") == "preToolUse"
        ),
        "NOT_VISIBLE",
    )
    if pretool_trust_status in {"TRUSTED", "MANAGED"}:
        next_steps = [
            "Codex PreToolUse Hook은 신뢰된 상태입니다.",
            f"{cli_prefix} hook verify로 실제 Session-bound Hook Event를 확인합니다.",
            f"검증 결과가 VERIFIED이면 {cli_prefix} protect <workspace>를 실행합니다.",
        ]
    else:
        next_steps = [
            "Codex에서 /hooks를 열고 AIA Hook을 검토·신뢰합니다.",
            f"신뢰한 뒤 {cli_prefix} hook verify로 실제 Session-bound Hook Event를 확인합니다.",
            f"검증 결과가 VERIFIED이면 {cli_prefix} protect <workspace>를 실행합니다.",
        ]
    trust_status = (
        pretool_trust_status
        if pretool_trust_status in {"TRUSTED", "MANAGED"}
        else "MANUAL_REVIEW_REQUIRED"
    )
    control_root = _control_root(None)
    control_root_writable, _control_root_detail = _control_root_write_check(control_root)
    verification_current = bool(
        executable is not None
        and installer.is_installed()
        and HookVerificationStore(control_root).is_current(installer, executable)
    )
    if executable is None:
        readiness_code = "CODEX_EXECUTABLE_UNAVAILABLE"
    elif not installer.is_installed():
        readiness_code = "CODEX_HOOK_NOT_INSTALLED"
    elif pretool_trust_status not in {"TRUSTED", "MANAGED"}:
        readiness_code = "CODEX_HOOK_TRUST_REQUIRED"
    elif not verification_current:
        readiness_code = "HOOK_VERIFICATION_REQUIRED"
    elif not control_root_writable:
        readiness_code = "CONTROL_ROOT_NOT_WRITABLE"
    else:
        readiness_code = "READY"
    payload = {
        "configured": True,
        "hook_path": str(path),
        "codex_executable": str(executable) if executable is not None else None,
        "codex_version": executable_version,
        "pretool_installed": installer.is_installed(),
        "posttool_installed": installer.is_posttool_installed(),
        "trust_status": trust_status,
        "codex_hook_trust": codex_hook_trust,
        "codex_pretool_trust_status": pretool_trust_status,
        "ready": readiness_code == "READY",
        "readiness_code": readiness_code,
        "hook_verification_current": verification_current,
        "control_root": str(control_root),
        "control_root_writable": control_root_writable,
        "next_steps": next_steps,
    }
    if args.json:
        print(_json_text(payload))
    else:
        print(f"AIA Hook 설정 완료: {path}")
        print(f"[안내] 검토 순서가 헷갈리면 '{cli_prefix} hook explain'을 실행하세요.")
        print(f"[확인] Codex PreToolUse Trust: {pretool_trust_status}")
        if pretool_trust_status not in {"TRUSTED", "MANAGED"}:
            print("[필수] Codex에서 /hooks를 열고 AIA Hook을 검토·신뢰하세요.")
        print(
            f"[상태] {'READY' if payload['ready'] else 'NOT_READY'} "
            f"({payload['readiness_code']})"
        )
        if not payload["ready"]:
            print(f"[검증] {cli_prefix} hook verify")
            print(f"[확인] {cli_prefix} doctor")
        else:
            print(f"[실행] {cli_prefix} start C:\\workspace\\my-project")
    return 0


def _run_console(args: argparse.Namespace) -> int:
    """Start the local console through the same product CLI as other commands."""

    if args.control_root is not None:
        os.environ["AIA_CONTROL_ROOT"] = str(
            Path(args.control_root).expanduser().resolve(strict=False)
        )
    from aia_web.__main__ import run, validate_local_bind

    try:
        validate_local_bind(args.host, args.port)
    except ValueError as error:
        raise ApplicationValidationError(str(error)) from error

    open_path = getattr(args, "open_path", "/") or "/"
    if not open_path.startswith("/"):
        open_path = "/" + open_path
    url = f"http://{args.host}:{args.port}{open_path}"
    print(f"AIA 로컬 보안 콘솔: {url}")
    if args.open:
        # Let uvicorn bind the loopback port before asking the browser to load
        # the page; otherwise the first navigation can race server startup.
        browser_timer = threading.Timer(0.5, webbrowser.open, args=(url,), kwargs={"new": 2})
        browser_timer.daemon = True
        browser_timer.start()
        print("서버가 시작되면 기본 브라우저에서 콘솔을 엽니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    run(host=args.host, port=args.port)
    return 0


def _hook_status(args: argparse.Namespace) -> int:
    """Show the difference between an installed Hook and an observed Hook."""

    installer = CodexHookInstaller(args.path)
    cli_prefix = _cli_prefix(installer)
    service = RunApplicationService(_control_root(args.control_root))
    try:
        runs = service.list_runs()
    finally:
        service.shutdown()
    verified = [
        item
        for item in runs
        if item.get("hook_event_count", 0) > 0
        and item.get("protection_state")
        in {"ACTIVE_VERIFIED", "COMPLETED_VERIFIED", "ABORTED_VERIFIED"}
    ]
    verified.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    last_verified = verified[0] if verified else None
    executable: Path | None = None
    try:
        executable = CodexAdapter().discover()
    except Exception:
        pass
    verification_store = HookVerificationStore(_control_root(args.control_root))
    fingerprint_current = bool(
        installer.is_installed()
        and executable is not None
        and verification_store.is_current(installer, executable)
    )
    codex_trust = (
        inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
        ).to_mapping()
        if executable is not None
        else {"available": False, "reason": "CODEX_EXECUTABLE_UNAVAILABLE", "hooks": []}
    )
    trust_entries = codex_trust.get("hooks") or []
    pretool_trust_status = next(
        (
            item.get("trust_status")
            for item in trust_entries
            if isinstance(item, dict) and item.get("event") == "preToolUse"
        ),
        None,
    )
    trust_current = bool(
        codex_trust.get("available")
        and pretool_trust_status in {"TRUSTED", "MANAGED"}
    )
    trust_status = (
        str(pretool_trust_status)
        if trust_current
        else "MANUAL_REVIEW_REQUIRED"
    )
    verification_current = fingerprint_current and trust_current
    if verification_current:
        activation_status = "CURRENTLY_VERIFIED"
    elif last_verified:
        activation_status = "OBSERVED_IN_PAST"
    else:
        activation_status = "NOT_OBSERVED"
    if not fingerprint_current:
        verification_status = "MISSING_OR_STALE"
    elif not trust_current:
        verification_status = "CURRENT_BUT_UNTRUSTED"
    else:
        verification_status = "CURRENT"
    payload = {
        "hook_path": str(installer.path),
        "pretool_installed": installer.is_installed(),
        "posttool_installed": installer.is_posttool_installed(),
        "verification_status": verification_status,
        "verification_path": str(verification_store.path),
        "ready": verification_current,
        "trust_status": trust_status,
        "activation_status": activation_status,
        "codex_hook_trust": codex_trust,
        "last_verified_run": (
            {
                "session_id": last_verified.get("session_id"),
                "created_at": last_verified.get("created_at"),
                "protection_state": last_verified.get("protection_state"),
                "hook_event_count": last_verified.get("hook_event_count", 0),
            }
            if last_verified
            else None
        ),
        "claim_rule": "A Protected Run is verified only after a session-bound Hook Event is observed.",
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("AIA Hook 상태")
        print(f"경로: {payload['hook_path']}")
        print(f"PreToolUse 설치: {'YES' if payload['pretool_installed'] else 'NO'}")
        print(f"PostToolUse 설치: {'YES' if payload['posttool_installed'] else 'NO'}")
        print(f"Codex 신뢰: {payload['trust_status']}")
        if payload["trust_status"] == "MANUAL_REVIEW_REQUIRED":
            print("[필수] /hooks에서 AIA Hook을 검토·신뢰하세요.")
        print(f"Hook 관찰 상태: {payload['activation_status']}")
        if codex_trust.get("available"):
            trust_summary = ", ".join(
                f"{item.get('event')}={item.get('trust_status')}"
                for item in trust_entries
                if isinstance(item, dict)
            ) or "AIA Hook 항목을 찾지 못함"
            print(f"Codex 실제 Trust: {trust_summary}")
        else:
            print(f"Codex 실제 Trust: 확인 불가 ({codex_trust.get('reason')})")
        print(f"현재 검증 증명: {payload['verification_status']}")
        if payload["verification_status"] == "CURRENT_BUT_UNTRUSTED":
            print("주의: 이전 검증 지문은 현재 Codex Trust를 통과하지 못했습니다.")
        if last_verified:
            print(f"최근 검증 실행: {last_verified.get('session_id')}")
            print(f"Hook Events: {last_verified.get('hook_event_count', 0)}")
        else:
            print("최근에 Session에 연결된 Hook Event가 없습니다.")
        if payload["activation_status"] == "OBSERVED_IN_PAST":
            print("주의: 과거 관찰 기록만 있으며 현재 검증 증명은 없습니다.")
        if payload["ready"]:
            print(f"[다음] {cli_prefix} protect <workspace>")
        else:
            print(f"주의: CURRENT가 아니면 {cli_prefix} protect는 보호 실행을 시작하지 않습니다.")
            if any(
                isinstance(item, dict)
                and item.get("event") == "preToolUse"
                and item.get("trust_status") not in {"TRUSTED", "MANAGED"}
                for item in trust_entries
            ):
                print("[다음] Codex에서 /hooks를 열고 AIA PreToolUse Hook을 검토·신뢰하세요.")
            print(f"[다음] {cli_prefix} hook verify")
    return 0 if payload["ready"] else 1


def _hook_explain(args: argparse.Namespace) -> int:
    """Explain the user-controlled Hook boundary without changing it.

    This command deliberately performs no installation, trust, or live probe.
    It gives a first-time user a compact review checklist and the exact AIA
    Hook metadata that should be visible in Codex's ``/hooks`` screen.
    """

    installer = CodexHookInstaller(args.path)
    cli_prefix = _cli_prefix(installer)
    executable: Path | None = None
    try:
        executable = CodexAdapter().discover()
    except Exception:
        pass

    codex_trust: dict[str, object] = {
        "available": False,
        "reason": "CODEX_EXECUTABLE_UNAVAILABLE",
        "hooks": [],
    }
    if executable is not None:
        codex_trust = inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
            timeout=8.0,
        ).to_mapping()

    trust_entries = codex_trust.get("hooks") or []
    trust_by_event = {
        str(item.get("event")): str(item.get("trust_status") or "UNKNOWN")
        for item in trust_entries
        if isinstance(item, dict)
    }
    verification_store = HookVerificationStore(_control_root(args.control_root))
    verification_current = bool(
        executable is not None
        and installer.is_installed()
        and verification_store.is_current(installer, executable)
    )
    pretool_trust = trust_by_event.get("preToolUse", "NOT_VISIBLE")
    trusted = pretool_trust in {"TRUSTED", "MANAGED"}
    payload = {
        "schema_version": "aia-hook-explain-v1",
        "hook_path": str(installer.path),
        "installed": {
            "pretool_use": installer.is_installed(),
            "posttool_use": installer.is_posttool_installed(),
        },
        "review_target": {
            "events": ["PreToolUse", "PostToolUse"],
            "matcher": installer.hook_entry("PreToolUse")["matcher"],
            "command": installer.command,
            "semantic_tools": list(product_capabilities()["support"]["pretool_matchers"]),
            "aliases": product_capabilities()["support"]["pretool_aliases"],
        },
        "codex": {
            "executable": str(executable) if executable is not None else None,
            "trust_available": bool(codex_trust.get("available")),
            "trust": trust_by_event,
        },
        "verification": {
            "current": verification_current and trusted,
            "path": str(verification_store.path),
        },
        "next_steps": [
            "Codex에서 /hooks를 엽니다.",
            "AIA PreToolUse Hook의 matcher(*)와 command를 검토합니다.",
            "내용을 이해한 뒤 Codex 화면에서 직접 Trust합니다.",
            f"{cli_prefix} hook verify를 실행합니다.",
            f"{cli_prefix} doctor에서 READY를 확인한 뒤 {cli_prefix} start <workspace>를 실행합니다.",
        ],
        "security_note": (
            "AIA는 사용자의 Codex Hook Trust를 대신 승인하지 않습니다. "
            "설치됨은 신뢰됨이나 실제 보호 증명과 같지 않습니다."
        ),
    }
    if args.json:
        print(_json_text(payload))
        return 0

    print("AIA Hook 검토 안내")
    print(f"설정 파일: {payload['hook_path']}")
    print(
        "설치 상태: "
        f"PreToolUse={'설치됨' if payload['installed']['pretool_use'] else '없음'} / "
        f"PostToolUse={'설치됨' if payload['installed']['posttool_use'] else '없음'}"
    )
    print(f"검토할 matcher: {payload['review_target']['matcher']}")
    print(f"검토할 command: {payload['review_target']['command']}")
    print(
        "AIA가 의미를 해석하는 도구: "
        + ", ".join(str(item) for item in payload["review_target"]["semantic_tools"])
    )
    print(
        "현재 Codex Trust: "
        + ", ".join(f"{event}={status}" for event, status in trust_by_event.items())
        if trust_by_event
        else "확인 불가"
    )
    print(f"현재 검증 증명: {'CURRENT' if payload['verification']['current'] else '필요'}")
    print("다음 순서:")
    for index, step in enumerate(payload["next_steps"], 1):
        print(f"  {index}. {step}")
    print(f"주의: {payload['security_note']}")
    return 0


def _extract_session_id(output: str) -> str | None:
    for line in output.splitlines():
        prefix = "AIA Protected Run:"
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            if value:
                return value
    return None


def _live_hook_proof_is_valid(
    *,
    hook_event_count: object,
    protection_state: object,
    bundle_status: object,
) -> bool:
    """Require a session-bound event and a committed verified run."""

    return bool(
        isinstance(hook_event_count, int)
        and hook_event_count > 0
        and protection_state in {"COMPLETED_VERIFIED", "ABORTED_VERIFIED"}
        and bundle_status == "VALID"
    )


def _hook_verify(args: argparse.Namespace) -> int:
    """Verify the user-level Hook through the normal product launch path."""

    installer = CodexHookInstaller(args.path)
    if args.timeout <= 0:
        raise ApplicationValidationError("timeout must be positive")
    if not installer.is_installed():
        runtime_detected = installer.has_aia_runtime("PreToolUse")
        reason = (
            "PRETOOL_HOOK_COMMAND_MISMATCH"
            if runtime_detected
            else "PRETOOL_HOOK_NOT_INSTALLED"
        )
        payload = {
            "verified": False,
            "reason": reason,
            "hook_path": str(installer.path),
            "aia_runtime_detected": runtime_detected,
        }
        if args.json:
            print(_json_text(payload))
        else:
            print(f"[확인] 읽은 Hook 설정: {installer.path}")
            if runtime_detected:
                print(
                    "Hook 검증 실패: PreToolUse Hook 설정은 있지만 현재 AIA 실행 경로와 일치하지 않습니다."
                )
                print(
                    "[원인] 이전 uv 격리 환경이나 다른 AIA 프로젝트에서 생성된 Hook일 수 있습니다."
                )
            else:
                print("Hook 검증 실패: PreToolUse Hook이 설치되지 않았습니다.")
            print(f"[예상] 현재 AIA Hook 명령: {installer.command}")
            print(f"[다음] {_cli_prefix(installer)} setup")
        return 2
    try:
        executable = CodexAdapter().discover()
    except Exception as error:
        payload = {
            "verified": False,
            "reason": "CODEX_EXECUTABLE_UNAVAILABLE",
            "error": type(error).__name__,
        }
        if args.json:
            print(_json_text(payload))
        else:
            print("Hook 검증 실패: Codex 실행 파일을 찾을 수 없습니다.")
        return 2

    # Trust is a user-controlled security boundary.  Do not start a disposable
    # Protected Run when Codex already reports that the AIA PreToolUse Hook is
    # untrusted or missing.  The app-server inspection starts only a short-lived
    # diagnostic process; it does not start an Agent run or execute a tool.
    codex_hook_trust = inspect_codex_hook_trust(
        executable,
        hook_path=installer.path,
        cwd=Path.cwd(),
        timeout=min(8.0, args.timeout),
    ).to_mapping()
    trust_entries = codex_hook_trust.get("hooks") or []
    pretool_trust_status = next(
        (
            item.get("trust_status")
            for item in trust_entries
            if isinstance(item, dict) and item.get("event") == "preToolUse"
        ),
        None,
    )
    if codex_hook_trust.get("available") and pretool_trust_status not in {
        "TRUSTED",
        "MANAGED",
    }:
        reason = (
            "CODEX_PRETOOL_HOOK_NOT_VISIBLE"
            if pretool_trust_status is None
            else "CODEX_HOOK_TRUST_REQUIRED"
        )
        payload = {
            "verified": False,
            "protection_claim": "PROTECTION_NOT_PROVEN",
            "reason": reason,
            "trust_status": pretool_trust_status or "NOT_VISIBLE",
            "codex_hook_trust": codex_hook_trust,
            "codex_executable": str(executable),
            "hook_path": str(installer.path),
            "probe_started": False,
            "next_step": "Codex /hooks에서 AIA PreToolUse Hook을 검토·신뢰한 뒤 다시 실행하세요.",
        }
        if args.json:
            print(_json_text(payload))
        else:
            print("AIA Hook 검증을 시작하지 않았습니다.")
            print(f"Codex 실제 PreToolUse Trust: {payload['trust_status']}")
            print(payload["next_step"])
        return 2

    control_root = _control_root(args.control_root)
    probe_workspace = Path(tempfile.mkdtemp(prefix="aia-hook-verify-"))
    marker = probe_workspace / "AIA_HOOK_PROBE_MARKER.txt"
    task = (
        "Use the Bash tool to run exactly: "
        "python -c \"from pathlib import Path; "
        "Path('AIA_HOOK_PROBE_MARKER.txt').write_text('ok', encoding='utf-8')\". "
        "Do not use another tool."
    )
    command = _self_cli_command(
        "protect",
        str(probe_workspace),
        "--task",
        task,
        "--profile",
        "FREE_DEVELOPMENT",
        "--control-root",
        str(control_root),
        "--timeout",
        str(args.timeout),
        "--_hook-verification-probe",
    )
    probe_environment = os.environ.copy()
    probe_environment[_HOOK_VERIFICATION_PROBE_TOKEN_ENV] = uuid4().hex
    payload: dict[str, object] = {
        "verified": False,
        "protection_claim": "PROTECTION_NOT_PROVEN",
        "reason": "HOOK_EVENT_NOT_OBSERVED",
        "codex_executable": str(executable),
        "hook_path": str(installer.path),
        "workspace": str(probe_workspace),
        "control_root": str(control_root),
        "session_id": None,
        "hook_event_count": 0,
        "protection_state": None,
        "bundle_status": None,
        "probe_marker_created": False,
        "probe_started": False,
        "codex_hook_trust": codex_hook_trust,
    }
    try:
        payload["probe_started"] = True
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=probe_environment,
            timeout=args.timeout + 60.0,
            check=False,
            **_hidden_process_kwargs(),
        )
        session_id = _extract_session_id(completed.stdout)
        payload["session_id"] = session_id
        payload["cli_exit_code"] = completed.returncode
        if session_id is None:
            payload["reason"] = "PROTECTED_RUN_SESSION_NOT_CREATED"
        else:
            reader = ResultBundleReader(control_root)
            result = reader.read_result(session_id)
            entries = [
                item
                for item in reader.list_completed()
                if item.get("session_id") == session_id
            ]
            history = entries[0] if entries else {}
            payload["limitations"] = list(result.get("limitations") or ())
            observation = result.get("agent_output_observation")
            if isinstance(observation, dict):
                payload["effective_approval_policy"] = observation.get(
                    "effective_approval_policy"
                )
                payload["effective_sandbox"] = observation.get("effective_sandbox")
            payload["hook_event_count"] = reader.hook_event_count(session_id)
            payload["protection_state"] = history.get("protection_state")
            payload["bundle_status"] = (
                reader.verification(session_id).status.value
                if reader.verification(session_id) is not None
                else None
            )
            payload["probe_marker_created"] = marker.exists()
            if _live_hook_proof_is_valid(
                hook_event_count=payload["hook_event_count"],
                protection_state=payload["protection_state"],
                bundle_status=payload["bundle_status"],
            ):
                payload["verified"] = True
                payload["protection_claim"] = "PROTECTION_PROVEN"
                payload["reason"] = "SESSION_BOUND_HOOK_EVENT_OBSERVED"
                try:
                    HookVerificationStore(control_root).write_verified(
                        installer=installer,
                        executable=executable,
                        session_id=str(session_id),
                        hook_event_count=int(payload["hook_event_count"]),
                    )
                    payload["verification_path"] = str(
                        HookVerificationStore(control_root).path
                    )
                except OSError as error:
                    payload["verified"] = False
                    payload["reason"] = f"HOOK_VERIFICATION_PERSIST_FAILED:{type(error).__name__}"
            elif payload["hook_event_count"] == 0:
                if any(
                    item in payload.get("limitations", ())
                    for item in (
                        "CODEX_SANDBOX_DOWNGRADED",
                        "CODEX_APPROVAL_POLICY_DOWNGRADED",
                    )
                ):
                    payload["reason"] = "CODEX_EXECUTION_POLICY_DOWNGRADED"
                else:
                    payload["reason"] = (
                        "HOOK_NOT_OBSERVED_PROBE_EXECUTED"
                        if payload["probe_marker_created"]
                        else "HOOK_EVENT_NOT_OBSERVED"
                    )
            else:
                payload["reason"] = "PROTECTED_RUN_DEGRADED"
            # Keep the result Bundle in the user's Control Root, but do not
            # retain the disposable probe Workspace.
    except subprocess.TimeoutExpired:
        payload["reason"] = "HOOK_VERIFY_TIMEOUT"
    except (OSError, ValueError, KeyError) as error:
        payload["reason"] = f"HOOK_VERIFY_ERROR:{type(error).__name__}"
    finally:
        shutil.rmtree(probe_workspace, ignore_errors=True)

    if args.json:
        print(_json_text(payload))
    else:
        print("AIA Hook 실시간 검증")
        print(f"결과: {'VERIFIED' if payload['verified'] else 'NOT_VERIFIED'}")
        print(f"보호 주장: {payload['protection_claim']}")
        print(f"이유: {payload['reason']}")
        print(f"Hook Events: {payload['hook_event_count']}")
        print(f"Protection: {payload['protection_state']}")
        if payload.get("effective_sandbox") or payload.get("effective_approval_policy"):
            print(
                "Codex 실행 정책: "
                f"sandbox={payload.get('effective_sandbox') or 'unknown'}, "
                f"approval={payload.get('effective_approval_policy') or 'unknown'}"
            )
        if payload.get("limitations"):
            print(f"제한사항: {', '.join(str(item) for item in payload['limitations'])}")
        print("임시 Probe Workspace: 삭제됨")
        if not payload["verified"]:
            if payload["reason"] == "CODEX_EXECUTION_POLICY_DOWNGRADED":
                print(
                    "[다음] Codex의 sandbox/approval 설정을 확인하고, "
                    "AIA가 요청한 workspace-write/on-request가 적용되는 환경에서 다시 실행하세요."
                )
            elif payload["reason"] == "HOOK_NOT_OBSERVED_PROBE_EXECUTED":
                print(
                    "[위험] Probe 명령은 실행됐지만 AIA Hook이 관찰되지 않았습니다. "
                    "이 실행은 보호·차단 증명이 아닙니다. Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 다시 실행하세요."
                )
            else:
                print("[다음] Codex에서 /hooks를 열어 AIA Hook을 검토·신뢰한 뒤 다시 실행하세요.")
    return 0 if payload["verified"] else 1


def _protected_run_preflight(
    control_root: Path | None = None,
    *,
    hook_verification_probe: bool = False,
) -> tuple[bool, list[str]]:
    """Return actionable local checks before creating a Protected Run."""

    failures: list[str] = []
    try:
        CodexAdapter().discover()
    except Exception:
        failures.append("Codex executable을 찾을 수 없습니다. Codex 설치를 확인하세요.")
    installer = CodexHookInstaller()
    cli_prefix = _cli_prefix(installer)
    if not installer.is_installed():
        failures.append(
            f"AIA PreToolUse Hook이 설치되지 않았습니다. 먼저 '{cli_prefix} setup'을 실행하세요."
        )
    elif not hook_verification_probe:
        resolved_control_root = control_root or _control_root(None)
        try:
            executable = CodexAdapter().discover()
        except Exception:
            executable = None
        trust_status = None
        if executable is not None:
            try:
                inspection = inspect_codex_hook_trust(
                    executable,
                    hook_path=installer.path,
                    cwd=Path.cwd(),
                    timeout=8.0,
                ).to_mapping()
                trust_status = next(
                    (
                        item.get("trust_status")
                        for item in (inspection.get("hooks") or [])
                        if isinstance(item, dict) and item.get("event") == "preToolUse"
                    ),
                    None,
                )
            except (OSError, ValueError):
                trust_status = None
        if executable is None or not HookVerificationStore(resolved_control_root).is_current(
            installer,
            executable,
        ):
            if trust_status not in {None, "TRUSTED", "MANAGED"}:
                failures.append(
                    f"Codex PreToolUse Hook Trust={trust_status}. Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 '{cli_prefix} hook verify'를 실행하세요."
                )
            else:
                failures.append(
                    f"실제 Codex Hook 검증이 없습니다. 먼저 '{cli_prefix} hook verify'를 실행하세요."
                )
    return not failures, failures


def _print_protected_run_summary(
    session_id: str,
    status: dict[str, object],
    result: dict[str, object] | None,
) -> None:
    """Print a human-readable completion summary without raw evidence."""

    protection = status.get("protection")
    protection_view = protection if isinstance(protection, dict) else {}
    protection_state = str(protection_view.get("state") or "UNKNOWN")
    hook_events = protection_view.get("hook_events", 0)
    bundle_status = (
        result.get("bundle_status")
        if isinstance(result, dict)
        else None
    )
    incident_count = (
        len(result.get("incidents", ()))
        if isinstance(result, dict) and isinstance(result.get("incidents"), list)
        else status.get("incident_count", 0)
    )

    print("AIA 보호 실행 결과")
    print(f"Protected Run: {session_id}")
    session = status.get("session")
    session_view = session if isinstance(session, dict) else {}
    print(f"Session: {status.get('status') or session_view.get('status', 'UNKNOWN')}")
    print(f"Protection: {protection_state}")
    print(f"Hook Events: {hook_events}")
    print(f"Incidents: {incident_count}")
    print(f"Result Bundle: {bundle_status or 'NOT_AVAILABLE'}")
    if status.get("result_path"):
        print(f"Result Path: {status['result_path']}")

    if isinstance(result, dict):
        summary = result.get("action_summary")
        if not isinstance(summary, dict):
            summary = action_summary(result)
        print(
            "Actions: "
            f"{summary.get('total', 0)} total / "
            f"{summary.get('compliant', 0)} compliant / "
            f"{summary.get('audit', 0)} audit / "
            f"{summary.get('violation', 0)} violation / "
            f"{summary.get('indeterminate', 0)} indeterminate"
        )
        print(
            "Enforcement: "
            f"{summary.get('contain', 0)} contain / "
            f"{summary.get('blocked', 0)} blocked / "
            f"{summary.get('terminated', 0)} terminated"
        )
        print(
            "Execution: "
            f"{summary.get('execution_succeeded', 0)} succeeded / "
            f"{summary.get('execution_failed', 0)} failed / "
            f"{summary.get('execution_not_attempted', 0)} not attempted"
        )
        observed = result.get("evidence_summary")
        if isinstance(observed, dict):
            print(
                "Evidence 관찰: "
                f"파일 변경 {observed.get('filesystem_events', 0)}건 / "
                f"PreTool {observed.get('pretool_events', 0)}건 / "
                f"PostTool {observed.get('posttool_events', 0)}건"
            )
        recovery_status = result.get("recovery_status") or "NOT_ATTEMPTED"
        integrity_status = result.get("integrity_status") or "NOT_ATTEMPTED"
        print(f"Recovery: {recovery_status}")
        print(f"Integrity: {integrity_status}")
        if recovery_status == "RESTORED" and integrity_status == "VERIFIED":
            print("복구 해석: 검증된 복구 성공(RESTORED + VERIFIED)")
        elif recovery_status != "NOT_ATTEMPTED" or integrity_status != "NOT_ATTEMPTED":
            print(
                "복구 해석: Recovery와 Integrity는 독립 상태입니다. "
                "두 상태가 모두 성공인지 확인하세요."
            )

    if protection_state in {"COMPLETED_VERIFIED", "ABORTED_VERIFIED"} and bundle_status == "VALID":
        print("해석: 실제 Hook과 센서 종료 상태가 확인된 보호 실행입니다.")
    elif protection_state in {"COMPLETED_DEGRADED", "ABORTED_DEGRADED"}:
        print("해석: 실행은 끝났지만 보호 경계가 완전히 검증되지 않았습니다.")
        print("다음: Result Bundle의 limitations와 Hook 상태를 확인한 뒤 다시 실행하세요.")
    elif protection_state == "FAILED_DEGRADED":
        print("해석: 보호 경계가 끊겨 보호 성공으로 해석할 수 없습니다.")
        print("다음: 관리 대상 프로세스 종료 결과와 Result Bundle을 확인하세요.")


def _validate_policy(args: argparse.Namespace) -> int:
    """Validate a policy before a Protected Run freezes it."""

    try:
        policy = load_policy(args.path)
        resolved = ResolvedPolicy(
            profile=policy.profile or PolicyProfile.CUSTOM,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            source=str(args.path),
            policy=policy,
        )
    except (OSError, ValueError) as error:
        if args.json:
            print(
                    _json_text({"valid": False, "path": str(args.path), "error": str(error)})
            )
        else:
            print(f"정책 검증 실패: {error}")
        return 2

    payload = {
        "valid": True,
        "path": str(args.path.expanduser().resolve(strict=False)),
        "policy_id": resolved.policy_id,
        "policy_version": resolved.policy_version,
        "profile": resolved.profile.value,
        "rule_count": len(resolved.policy.rules),
        "sha256": policy_content_sha256(resolved),
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("정책 검증 성공")
        print(f"정책 ID: {payload['policy_id']}")
        print(f"버전: {payload['policy_version']}")
        print(f"Rule 수: {payload['rule_count']}")
        print(f"SHA-256: {payload['sha256']}")
    return 0


def _policy_profiles(args: argparse.Namespace) -> int:
    descriptions = {
        PolicyProfile.PROTECTED_DEVELOPMENT: "민감정보와 대표적인 파괴 명령을 기본 차단하는 보호 우선 정책",
        PolicyProfile.BASIC_DEVELOPMENT: "일반적인 개발 작업과 기본적인 보호를 함께 제공",
        PolicyProfile.CONSERVATIVE_SECURITY: "중요 자산 변경을 더 보수적으로 제한",
        PolicyProfile.FREE_DEVELOPMENT: "개발 자유도를 우선하고 관찰 중심으로 운용",
        PolicyProfile.CUSTOM: "사용자가 직접 작성하고 Strict Validation을 통과한 정책",
    }
    profiles = [
        {
            "value": profile.value,
            "label": POLICY_PROFILE_DISPLAY_NAMES[profile],
            "description": descriptions[profile],
            "editable": profile is not PolicyProfile.CUSTOM,
        }
        for profile in (
            PolicyProfile.PROTECTED_DEVELOPMENT,
            PolicyProfile.BASIC_DEVELOPMENT,
            PolicyProfile.CONSERVATIVE_SECURITY,
            PolicyProfile.FREE_DEVELOPMENT,
            PolicyProfile.CUSTOM,
        )
    ]
    if args.json:
        print(_json_text({"profiles": profiles}))
        return 0
    cli_prefix = _cli_prefix(CodexHookInstaller())
    print("AIA 정책 프로필")
    for item in profiles:
        edit_hint = "복사 후 수정 가능" if item["editable"] else "직접 JSON 필요"
        print(f"- {item['value']} / {item['label']}: {item['description']} ({edit_hint})")
    print(f"기본 정책 파일 생성: {cli_prefix} policy init C:\\workspace\\policies\\my-policy.json")
    return 0


def _init_policy(args: argparse.Namespace) -> int:
    target = args.path.expanduser().resolve(strict=False)
    profile = PolicyProfile.from_value(args.profile)
    try:
        resolved = resolve_profile(profile)
        source = Path(resolved.source)
        if target.exists() and not args.force:
            print(f"정책 생성 실패: 파일이 이미 존재합니다: {target}")
            print("덮어쓰려면 --force를 사용하세요.")
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except (OSError, ValueError) as error:
        print(f"정책 생성 실패: {error}")
        return 2
    print("정책 파일을 생성했습니다.")
    print(f"프로필: {profile.value} ({profile.display_name})")
    print(f"경로: {target}")
    print(f"다음 단계: {_cli_prefix(CodexHookInstaller())} policy validate \"{target}\"")
    return 0


def _policy_evaluate(args: argparse.Namespace) -> int:
    """Preview one target against an already resolved policy object."""

    try:
        if args.policy is not None:
            resolved = resolve_profile(PolicyProfile.CUSTOM, args.policy)
        else:
            resolved = resolve_profile(PolicyProfile.from_value(args.profile))
        operation = Operation(args.operation)
        if operation is Operation.EXECUTE:
            if args.target_path is not None:
                raise ValueError("EXECUTE preview accepts --command, not --path")
            if not isinstance(args.raw_command, str) or not args.raw_command.strip():
                raise ValueError("EXECUTE preview requires --command")
            evaluation = resolved.evaluate_target(
                operation=operation,
                raw_command=args.raw_command,
            )
            target_kind = "COMMAND"
        else:
            if args.raw_command is not None:
                raise ValueError("file operation preview accepts --path, not --command")
            if not isinstance(args.target_path, str) or not args.target_path.strip():
                raise ValueError("file operation preview requires --path")
            evaluation = resolved.evaluate_target(
                operation=operation,
                path=args.target_path,
            )
            target_kind = "PATH"
    except (OSError, ValueError) as error:
        print(f"정책 미리보기 실패: {error}")
        return 2

    payload = {
        "policy_id": resolved.policy_id,
        "policy_version": resolved.policy_version,
        "profile": resolved.profile.value,
        "operation": operation.value,
        "target_kind": target_kind,
        "policy_decision": evaluation.policy_decision.value,
        "operation_effect": (
            evaluation.operation_effect.value
            if evaluation.operation_effect is not None
            else None
        ),
        "asset_type": (
            evaluation.asset_type.value if evaluation.asset_type is not None else None
        ),
        "matched_rule_ids": list(evaluation.matched_rule_ids),
        "audit_record": evaluation.audit_record,
        "reason": evaluation.reason,
        "limitation": evaluation.limitation,
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("AIA 정책 미리보기")
        print(f"Policy: {resolved.policy_id} v{resolved.policy_version}")
        print(f"Profile: {resolved.profile.value}")
        print(f"Operation: {operation.value}")
        print(f"Decision: {evaluation.policy_decision.value}")
        print(f"Effect: {payload['operation_effect'] or 'DEFAULT'}")
        print(f"Asset Type: {payload['asset_type'] or 'NONE'}")
        print(
            "Matched Rules: "
            + (", ".join(evaluation.matched_rule_ids) or "NONE")
        )
        if evaluation.reason:
            print(f"Reason: {evaluation.reason}")
        if evaluation.limitation:
            print(f"Limitation: {evaluation.limitation}")
        print("실제 Agent나 명령은 실행하지 않았습니다.")
    return 0


def _list_runs(args: argparse.Namespace) -> int:
    if args.limit < 0:
        print("AIA error: limit must be zero or greater")
        return 2
    service = RunApplicationService(_control_root(args.control_root))
    try:
        runs = service.list_runs()[: args.limit]
    finally:
        service.shutdown()
    if args.json:
        print(_json_text({"runs": runs}))
        return 0
    print("AIA 보호 실행 기록")
    if not runs:
        print("기록된 보호 실행이 없습니다.")
        return 0
    for item in runs:
        policy = item.get("policy") or {}
        policy_id = policy.get("id") or policy.get("policy_id") or "—"
        policy_version = policy.get("version") or policy.get("policy_version") or ""
        print(f"- {item.get('session_id')}")
        print(
            "  상태: "
            f"{item.get('status', 'UNKNOWN')} / "
            f"보호: {item.get('protection_state', 'UNKNOWN')} / "
            f"Bundle: {item.get('bundle_status', 'UNKNOWN')}"
        )
        classification = item.get("run_classification")
        if classification and classification != "PRODUCT_PROTECTED_RUN":
            print(f"  기록 분류: {classification}")
            if classification == "UNVERIFIED_RUNTIME_STATE":
                print("  주의: 검증된 Result Bundle이 없어 보호 성공으로 해석하지 마세요.")
        print(f"  Workspace: {item.get('workspace', '-')}")
        print(
            f"  Policy: {policy_id} "
            f"{policy_version} / "
            f"사건: {item.get('incident_count', 0)} / "
            f"Hook: {item.get('hook_event_count', 0)}"
        )
    return 0


def _show_status(args: argparse.Namespace) -> int:
    service = RunApplicationService(_control_root(args.control_root))
    try:
        try:
            status = service.get_run_status(args.session_id)
        except (KeyError, ValueError) as error:
            if args.json:
                print(
                    _json_text({"session_id": args.session_id, "error": str(error)})
                )
            else:
                print(f"AIA error: {error}")
            return 2
    finally:
        service.shutdown()
    if args.json:
        print(_json_text(status, default=str))
        return 0
    session = status.get("session") or {}
    protection = status.get("protection") or {}
    policy = status.get("policy") or {}
    policy_id = policy.get("id") or policy.get("policy_id") or "-"
    policy_version = policy.get("version") or policy.get("policy_version") or ""
    cli_prefix = _cli_prefix(CodexHookInstaller())
    print("AIA 보호 실행 상태")
    print(f"Session: {session.get('session_id', args.session_id)}")
    print(f"상태: {session.get('status', 'UNKNOWN')} / 단계: {status.get('phase', 'UNKNOWN')}")
    print(
        f"보호: {protection.get('state', 'UNKNOWN')} "
        f"(Hook Events: {protection.get('hook_events', 0)})"
    )
    print(f"Workspace: {session.get('workspace', '-')}")
    print(f"Policy: {policy_id} {policy_version}")
    print(
        f"Checkpoint: {status.get('checkpoint', '-')} / "
        f"Lease: {status.get('lease', '-')} / "
        f"사건: {status.get('incident_count', 0)}"
    )
    if status.get("result_path"):
        print(f"Result: {status['result_path']}")
    if status.get("error"):
        print(f"오류: {status['error']}")
    reconciliation = status.get("runtime_reconciliation")
    if isinstance(reconciliation, dict):
        print(
            "AIA 조정 프로세스: "
            f"{reconciliation.get('status', 'UNKNOWN')} / "
            f"Agent Root: {reconciliation.get('agent_process_status', 'NOT_RECORDED')}"
        )
        if reconciliation.get("orphaned"):
            print(f"주의: {reconciliation.get('detail', '보호 상태를 확인할 수 없습니다.')}")
            print(f"[다음] {cli_prefix} reconcile {args.session_id}")
    return 0


def _stop_run(args: argparse.Namespace) -> int:
    service = RunApplicationService(_control_root(args.control_root))
    try:
        try:
            result = service.request_stop(args.session_id)
        except KeyError:
            result = {
                "accepted": False,
                "session_id": args.session_id,
                "status": "NOT_FOUND",
                "reason": "RUN_NOT_FOUND",
            }
    finally:
        service.shutdown()
    if args.json:
        print(_json_text(result))
    else:
        state = "접수됨" if result.get("accepted") else "실패"
        print(f"보호 실행 중지 요청: {state}")
        print(f"Session: {result.get('session_id', args.session_id)}")
        print(f"상태: {result.get('status', 'UNKNOWN')}")
        print(f"사유: {result.get('reason', '-')}")
    return 0 if result.get("accepted") else 1


def _reconcile_run(args: argparse.Namespace) -> int:
    service = RunApplicationService(_control_root(args.control_root))
    try:
        try:
            result = service.reconcile_orphaned_run(args.session_id)
        except KeyError:
            result = {
                "reconciled": False,
                "session_id": args.session_id,
                "reason": "RUN_NOT_FOUND",
            }
    finally:
        service.shutdown()
    if args.json:
        print(_json_text(result, default=str))
    else:
        state = "완료" if result.get("reconciled") else "실패"
        print(f"고아 보호 실행 정리 확인: {state}")
        print(f"Session: {result.get('session_id', args.session_id)}")
        print(f"사유: {result.get('reason', '-')}")
        reconciliation = result.get("runtime_reconciliation")
        if isinstance(reconciliation, dict):
            print(
                "AIA 조정 프로세스: "
                f"{reconciliation.get('status', 'UNKNOWN')} / "
                f"Agent Root: {reconciliation.get('agent_process_status', 'NOT_RECORDED')}"
            )
        if not result.get("reconciled"):
            print(
                "다음: 기존 Codex가 실행 중이면 먼저 종료한 뒤, "
                "기록된 Agent Root가 사라졌는지 확인하세요."
            )
    return 0 if result.get("reconciled") else 1


def _run_protected(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise ApplicationValidationError("timeout must be positive")
    if args._hook_verification_probe:
        probe_token = os.environ.pop(_HOOK_VERIFICATION_PROBE_TOKEN_ENV, None)
        if not isinstance(probe_token, str) or not probe_token:
            print("AIA error: Hook verification probe authorization is missing")
            return 2
    interactive = args.task is None
    if interactive and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        print(
            "AIA error: interactive protected runs require a terminal; "
            "provide --task for non-interactive execution"
        )
        return 2
    ready, failures = _protected_run_preflight(
        _control_root(args.control_root),
        hook_verification_probe=args._hook_verification_probe,
    )
    if not ready:
        print("AIA 보호 실행을 시작하지 않았습니다.")
        for failure in failures:
            print(f"[FAIL] {failure}")
        cli_prefix = _cli_prefix(CodexHookInstaller())
        if any("hook verify" in failure for failure in failures):
            print(f"[다음] {cli_prefix} hook verify")
        else:
            print(f"[다음] {cli_prefix} setup")
        return 2
    service = RunApplicationService(
        _control_root(args.control_root),
        require_hook_verification=not args._hook_verification_probe,
    )
    try:
        created = service.create_protected_run(
            {
                "workspace": str(args.workspace),
                "agent": "codex",
                "model": args.model,
                "policy_profile": "CUSTOM" if args.policy else args.profile,
                "custom_policy_path": str(args.policy) if args.policy else None,
                "mode": args.mode,
                "task": args.task or "",
                "interactive": interactive,
            }
        )
        session_id = created["session_id"]
        print(f"AIA Protected Run: {session_id}")
        print(f"Workspace: {Path(args.workspace).expanduser().resolve(strict=False)}")
        print(f"Control Root: {_control_root(args.control_root)}")
        if interactive:
            print(
                "Interactive protected session: Codex will open after readiness; "
                "enter tasks in the Codex screen and exit Codex to finish."
            )
        deadline = time.monotonic() + args.timeout
        last_phase: str | None = None
        interactive_started = False
        phase_started_at = time.monotonic()
        ready_delay_reported = False
        while True:
            status = service.get_run_status(session_id)
            phase = str(status.get("phase"))
            now = time.monotonic()
            if phase != last_phase:
                phase_started_at = now
                ready_delay_reported = False
            if phase != last_phase and (not interactive or phase != "RUNNING"):
                print(f"Phase: {phase}")
                if phase == "READY":
                    print(
                        "AIA: 보호 준비가 끝났습니다. Codex를 시작하는 중입니다. "
                        "Codex 화면이 열리면 그 안에서 작업을 입력하세요."
                    )
                elif phase == "LAUNCHING":
                    print(
                        "AIA: Codex 실행을 등록하고 보호 센서를 연결하는 중입니다. "
                        "잠시 후 Codex 화면이 열립니다."
                    )
                last_phase = phase
            if (
                phase == "READY"
                and not ready_delay_reported
                and now - phase_started_at >= 30
            ):
                print(
                    "AIA: Codex 시작이 30초 이상 지연되고 있습니다. "
                    "별도 PowerShell에서 'aia status "
                    f"{session_id}'를 확인할 수 있습니다. 중지하려면 Ctrl+C를 누르세요."
                )
                ready_delay_reported = True
            protection = status.get("protection") or {}
            if protection.get("state") in {"DEGRADED", "COMPLETED_DEGRADED"}:
                print(f"Protection: {protection['state']}")
            if interactive and phase == "RUNNING" and not interactive_started:
                print("Protected Codex session is active.")
                interactive_started = True
                last_phase = phase
            if status.get("result_available") or status.get("status") in {
                "COMPLETED",
                "FAILED",
                "ABORTED",
            }:
                break
            if time.monotonic() >= deadline:
                print("Result: TIMEOUT")
                return 2
            time.sleep(0.5)
        status = service.get_run_status(session_id)
        final_status = status.get("status") or status.get("session", {}).get("status")
        print(f"Status: {final_status}")
        if status.get("error"):
            print(f"Error: {status['error']}")
        result: dict[str, object] | None = None
        if status.get("result_available"):
            result = service.get_result(session_id)
        _print_protected_run_summary(session_id, status, result)
        protection_state = (status.get("protection") or {}).get("state")
        protection = status.get("protection") or {}
        if protection_state in {"COMPLETED_DEGRADED", "FAILED_DEGRADED"}:
            hook_events = protection.get("hook_events", 0)
            if protection_state == "FAILED_DEGRADED":
                print(
                    "주의: 보호 경계가 실행 중 끊겨 관리 트리 중지를 시도했습니다. "
                    "이 실행은 보호 성공으로 해석하지 마세요."
                )
            elif hook_events == 0:
                print(
                    "주의: 검증된 Codex Hook 이벤트가 없습니다. "
                    "Codex에서 /hooks를 열고 AIA Hook을 검토·신뢰한 뒤 다시 실행하세요."
                )
            else:
                print(
                    "주의: 보호 센서 또는 실행 경계에 오류가 있어 결과를 "
                    "완전한 보호 성공으로 해석하지 마세요."
                )
        return 0 if final_status == "COMPLETED" and protection_state != "COMPLETED_DEGRADED" else 1
    except KeyboardInterrupt:
        print("\nAIA 보호 실행 중지를 요청했습니다. 관리 중인 Codex를 정리하는 중입니다.")
        return 130
    finally:
        service.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    args = _parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            return _capabilities(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "self-test":
            return _self_test(args)
        if args.command == "demo":
            return _demo(args)
        if args.command == "runs":
            return _list_runs(args)
        if args.command == "status":
            return _show_status(args)
        if args.command == "stop":
            return _stop_run(args)
        if args.command == "reconcile":
            return _reconcile_run(args)
        if args.command == "policy" and args.policy_command == "validate":
            return _validate_policy(args)
        if args.command == "policy" and args.policy_command == "evaluate":
            return _policy_evaluate(args)
        if args.command == "policy" and args.policy_command == "profiles":
            return _policy_profiles(args)
        if args.command == "policy" and args.policy_command == "init":
            return _init_policy(args)
        if args.command == "hook" and args.hook_command == "install":
            path = CodexHookInstaller(args.path).install()
            print(f"Codex Hook installed: {path}")
            print("Review and trust this Hook in Codex before starting a protected run.")
            return 0
        if args.command == "hook" and args.hook_command == "uninstall":
            path = CodexHookInstaller(args.path).uninstall()
            print(f"AIA Codex Hook removed (other Hooks preserved): {path}")
            return 0
        if args.command == "hook" and args.hook_command == "runtime":
            from aia.codex_hook_runtime import main as hook_runtime_main

            return hook_runtime_main()
        if args.command == "setup":
            return _setup(args)
        if args.command == "support-bundle":
            return _support_bundle(args)
        if args.command == "console":
            return _run_console(args)
        if args.command == "hook" and args.hook_command == "status":
            return _hook_status(args)
        if args.command == "hook" and args.hook_command == "explain":
            return _hook_explain(args)
        if args.command == "hook" and args.hook_command == "verify":
            return _hook_verify(args)
        if args.command in {"protect", "start"}:
            return _run_protected(args)
        if args.command == "proof":
            if args.timeout <= 0:
                raise ApplicationValidationError("timeout must be positive")
            from aia.product_e2e import main as product_e2e_main

            return product_e2e_main(
                [
                    "--scenario",
                    args.scenario,
                    "--output",
                    str(args.output),
                    "--timeout",
                    str(args.timeout),
                ]
                + (["--json"] if args.json else [])
            )
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
