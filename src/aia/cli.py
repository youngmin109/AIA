"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Sequence

from aia import (
    CodexAdapter,
    CodexHookInstallationError,
    CodexHookInstaller,
    PolicyProfile,
    POLICY_PROFILE_DISPLAY_NAMES,
    ResolvedPolicy,
    load_policy,
    policy_content_sha256,
    resolve_profile,
)
from aia.hook_verification import HookVerificationStore
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia_app import ApplicationValidationError, RunApplicationService
from aia_app.readers import ResultBundleReader


def _json_text(value: object, *, default: object | None = None) -> str:
    options: dict[str, object] = {"ensure_ascii": True, "indent": 2}
    if default is not None:
        options["default"] = default
    return json.dumps(value, **options)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aia")
    parser.add_argument("--version", action="version", version="AIA 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor",
        help="check the local Codex/AIA protected-run setup",
    )
    doctor.add_argument("--json", action="store_true", help="print machine-readable output")
    doctor.add_argument("--hook-path", type=Path, help="hooks.json path")
    doctor.add_argument("--control-root", type=Path, help="AIA control root")
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
        default="BASIC_DEVELOPMENT",
        choices=(
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

    setup = commands.add_parser(
        "setup",
        help="install the AIA Hook and print the remaining trust steps",
    )
    setup.add_argument("--path", type=Path, help="hooks.json path")
    setup.add_argument("--json", action="store_true", help="print machine-readable output")

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

    protect = commands.add_parser(
        "protect",
        help="run Codex inside an AIA Protected Run",
    )
    protect.add_argument("workspace", type=Path)
    protect.add_argument(
        "--task",
        help="initial Codex task prompt; omit it to open an interactive protected session",
    )
    protect.add_argument("--policy", type=Path, help="custom policy JSON path")
    protect.add_argument(
        "--profile",
        default="BASIC_DEVELOPMENT",
        help="policy profile name",
    )
    protect.add_argument("--model")
    protect.add_argument("--mode", default="ENFORCE", choices=("ENFORCE", "AUDIT"))
    protect.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root outside the protected Workspace",
    )
    protect.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="maximum wait in seconds",
    )
    protect.add_argument(
        "--_allow-unverified-hook",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _control_root(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve(strict=False)
    configured = os.environ.get("AIA_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".aia" / "control").resolve(strict=False)


def _recent_run_diagnostic(control_root: Path) -> dict[str, object] | None:
    """Return safe metadata from the most recent committed Protected Run."""

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
            "뒤 aia hook verify를 다시 실행하세요."
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
        checks.append(
            {
                "name": "codex_executable",
                "ok": True,
                "value": str(executable),
                "detail": "Codex executable discovered",
            }
        )
    except Exception as error:
        checks.append(
            {
                "name": "codex_executable",
                "ok": False,
                "value": None,
                "detail": f"Codex executable unavailable: {type(error).__name__}",
            }
        )

    installer = CodexHookInstaller(args.hook_path)
    hook_installed = installer.is_installed()
    posttool_installed = installer.is_posttool_installed()
    checks.append(
        {
            "name": "codex_hook",
            "ok": hook_installed,
            "value": str(installer.path),
            "detail": (
                "Hook definition installed; review/trust it in Codex"
                if hook_installed
                else "Run 'aia hook install', then review/trust the Hook in Codex"
            ),
        }
    )

    codex_hook_trust: dict[str, object] = {
        "available": False,
        "reason": "CODEX_EXECUTABLE_OR_HOOK_UNAVAILABLE",
        "hooks": [],
    }
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
                        "Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 'aia hook verify'를 실행하세요"
                        if any(
                            isinstance(item, dict)
                            and item.get("event") == "preToolUse"
                            and item.get("trust_status") not in {"TRUSTED", "MANAGED"}
                            for item in (codex_hook_trust.get("hooks") or [])
                        )
                        else "Run 'aia hook verify' after reviewing the Hook in Codex"
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
    try:
        control_root.mkdir(parents=True, exist_ok=True)
        probe = control_root / ".aia-doctor-write-test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
        detail = "Control Root is writable"
    except OSError as error:
        writable = False
        detail = f"Control Root is not writable: {type(error).__name__}"
    checks.append(
        {
            "name": "control_root",
            "ok": writable,
            "value": str(control_root),
            "detail": detail,
        }
    )

    payload = {
        "product": "AIA",
        "checks": checks,
        "ready": all(bool(item["ok"]) for item in checks),
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
        print(f"결과: {'READY' if payload['ready'] else 'NOT_READY'}")
    return 0 if payload["ready"] else 1


def _setup(args: argparse.Namespace) -> int:
    """Install the stable Hook and make the manual trust boundary explicit."""

    installer = CodexHookInstaller(args.path)
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
    payload = {
        "configured": True,
        "hook_path": str(path),
        "pretool_installed": installer.is_installed(),
        "posttool_installed": installer.is_posttool_installed(),
        "trust_status": "MANUAL_REVIEW_REQUIRED",
        "next_steps": [
            "Codex에서 /hooks를 열고 AIA Hook을 검토합니다.",
            "AIA Hook을 신뢰한 뒤 aia doctor를 실행합니다.",
            "aia hook verify로 실제 Session-bound Hook Event를 확인합니다.",
            "검증 결과가 VERIFIED이면 aia protect <workspace>를 실행합니다.",
        ],
    }
    if args.json:
        print(_json_text(payload))
    else:
        print(f"AIA Hook 설정 완료: {path}")
        print("[필수] Codex에서 /hooks를 열고 AIA Hook을 검토·신뢰하세요.")
        print("[다음] uv run aia doctor")
        print("[검증] uv run aia hook verify")
        print("[실행] uv run aia protect C:\\workspace\\my-project")
    return 0


def _run_console(args: argparse.Namespace) -> int:
    """Start the local console through the same product CLI as other commands."""

    from aia_web.__main__ import run, validate_local_bind

    try:
        validate_local_bind(args.host, args.port)
    except ValueError as error:
        raise ApplicationValidationError(str(error)) from error

    print(f"AIA 로컬 보안 콘솔: http://{args.host}:{args.port}")
    print("종료하려면 Ctrl+C를 누르세요.")
    run(host=args.host, port=args.port)
    return 0


def _hook_status(args: argparse.Namespace) -> int:
    """Show the difference between an installed Hook and an observed Hook."""

    installer = CodexHookInstaller(args.path)
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
    verification_current = bool(
        installer.is_installed()
        and executable is not None
        and verification_store.is_current(installer, executable)
    )
    if verification_current:
        activation_status = "CURRENTLY_VERIFIED"
    elif last_verified:
        activation_status = "OBSERVED_IN_PAST"
    else:
        activation_status = "NOT_OBSERVED"
    codex_trust = (
        inspect_codex_hook_trust(
            executable,
            hook_path=installer.path,
            cwd=Path.cwd(),
        ).to_mapping()
        if executable is not None
        else {"available": False, "reason": "CODEX_EXECUTABLE_UNAVAILABLE", "hooks": []}
    )
    payload = {
        "hook_path": str(installer.path),
        "pretool_installed": installer.is_installed(),
        "posttool_installed": installer.is_posttool_installed(),
        "verification_status": "CURRENT" if verification_current else "MISSING_OR_STALE",
        "verification_path": str(verification_store.path),
        "ready": verification_current,
        "trust_status": "MANUAL_REVIEW_REQUIRED",
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
        print("Codex 신뢰: MANUAL_REVIEW_REQUIRED (/hooks에서 검토·신뢰 필요)")
        print(f"Hook 관찰 상태: {payload['activation_status']}")
        trust_entries = codex_trust.get("hooks") or []
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
        if last_verified:
            print(f"최근 검증 실행: {last_verified.get('session_id')}")
            print(f"Hook Events: {last_verified.get('hook_event_count', 0)}")
        else:
            print("최근에 Session에 연결된 Hook Event가 없습니다.")
        if payload["activation_status"] == "OBSERVED_IN_PAST":
            print("주의: 과거 관찰 기록만 있으며 현재 검증 증명은 없습니다.")
        print("주의: CURRENT가 아니면 aia protect는 보호 실행을 시작하지 않습니다.")
    return 0 if payload["ready"] else 1


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
        payload = {
            "verified": False,
            "reason": "PRETOOL_HOOK_NOT_INSTALLED",
            "hook_path": str(installer.path),
        }
        if args.json:
            print(_json_text(payload))
        else:
            print("Hook 검증 실패: PreToolUse Hook이 설치되지 않았습니다.")
            print("[다음] uv run aia setup")
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

    control_root = _control_root(args.control_root)
    probe_workspace = Path(tempfile.mkdtemp(prefix="aia-hook-verify-"))
    marker = probe_workspace / "AIA_HOOK_PROBE_MARKER.txt"
    task = (
        "Use the Bash tool to run exactly: "
        "python -c \"from pathlib import Path; "
        "Path('AIA_HOOK_PROBE_MARKER.txt').write_text('ok', encoding='utf-8')\". "
        "Do not use another tool."
    )
    command = [
        sys.executable,
        "-m",
        "aia.cli",
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
        "--_allow-unverified-hook",
    ]
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
    }
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout + 60.0,
            check=False,
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
    allow_unverified_hook: bool = False,
) -> tuple[bool, list[str]]:
    """Return actionable local checks before creating a Protected Run."""

    failures: list[str] = []
    try:
        CodexAdapter().discover()
    except Exception:
        failures.append("Codex executable을 찾을 수 없습니다. Codex 설치를 확인하세요.")
    installer = CodexHookInstaller()
    if not installer.is_installed():
        failures.append(
            "AIA PreToolUse Hook이 설치되지 않았습니다. 먼저 'uv run aia setup'을 실행하세요."
        )
    elif not allow_unverified_hook:
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
                    f"Codex PreToolUse Hook Trust={trust_status}. Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 'uv run aia hook verify'를 실행하세요."
                )
            else:
                failures.append(
                    "실제 Codex Hook 검증이 없습니다. 먼저 'uv run aia hook verify'를 실행하세요."
                )
    return not failures, failures


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
            PolicyProfile.BASIC_DEVELOPMENT,
            PolicyProfile.CONSERVATIVE_SECURITY,
            PolicyProfile.FREE_DEVELOPMENT,
            PolicyProfile.CUSTOM,
        )
    ]
    if args.json:
        print(_json_text({"profiles": profiles}))
        return 0
    print("AIA 정책 프로필")
    for item in profiles:
        edit_hint = "복사 후 수정 가능" if item["editable"] else "직접 JSON 필요"
        print(f"- {item['value']} / {item['label']}: {item['description']} ({edit_hint})")
    print("기본 정책 파일 생성: uv run aia policy init C:\\workspace\\policies\\my-policy.json")
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
    print(f"다음 단계: uv run aia policy validate \"{target}\"")
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


def _run_protected(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise ApplicationValidationError("timeout must be positive")
    interactive = args.task is None
    if interactive and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        print(
            "AIA error: interactive protected runs require a terminal; "
            "provide --task for non-interactive execution"
        )
        return 2
    ready, failures = _protected_run_preflight(
        _control_root(args.control_root),
        allow_unverified_hook=args._allow_unverified_hook,
    )
    if not ready:
        print("AIA 보호 실행을 시작하지 않았습니다.")
        for failure in failures:
            print(f"[FAIL] {failure}")
        if any("hook verify" in failure for failure in failures):
            print("[다음] uv run aia hook verify")
        else:
            print("[다음] uv run aia setup")
        return 2
    service = RunApplicationService(
        _control_root(args.control_root),
        require_hook_verification=not args._allow_unverified_hook,
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
        print(f"Control Root: {_control_root(args.control_root)}")
        if interactive:
            print(
                "Interactive protected session: Codex will open after readiness; "
                "enter tasks in the Codex screen and exit Codex to finish."
            )
        deadline = time.monotonic() + args.timeout
        last_phase: str | None = None
        interactive_started = False
        while True:
            status = service.get_run_status(session_id)
            phase = str(status.get("phase"))
            if phase != last_phase and (not interactive or phase != "RUNNING"):
                print(f"Phase: {phase}")
                last_phase = phase
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
        if status.get("result_available"):
            result = service.get_result(session_id)
            print(
                _json_text(
                    {
                        "bundle_status": result.get("bundle_status"),
                        "incident_count": len(result.get("incidents", [])),
                        "result_path": status.get("result_path"),
                        "session_status": result.get("session_status"),
                        "protection_state": (status.get("protection") or {}).get("state"),
                    }
                )
            )
        protection_state = (status.get("protection") or {}).get("state")
        protection = status.get("protection") or {}
        if protection_state == "COMPLETED_DEGRADED":
            hook_events = protection.get("hook_events", 0)
            if hook_events == 0:
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
    finally:
        service.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "runs":
            return _list_runs(args)
        if args.command == "status":
            return _show_status(args)
        if args.command == "stop":
            return _stop_run(args)
        if args.command == "policy" and args.policy_command == "validate":
            return _validate_policy(args)
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
        if args.command == "setup":
            return _setup(args)
        if args.command == "console":
            return _run_console(args)
        if args.command == "hook" and args.hook_command == "status":
            return _hook_status(args)
        if args.command == "hook" and args.hook_command == "verify":
            return _hook_verify(args)
        if args.command == "protect":
            return _run_protected(args)
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
