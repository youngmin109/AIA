"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
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
from aia_app import ApplicationValidationError, RunApplicationService


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

    setup = commands.add_parser(
        "setup",
        help="install the AIA Hook and print the remaining trust steps",
    )
    setup.add_argument("--path", type=Path, help="hooks.json path")
    setup.add_argument("--json", action="store_true", help="print machine-readable output")

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
    return parser


def _control_root(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve(strict=False)
    configured = os.environ.get("AIA_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".aia" / "control").resolve(strict=False)


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

    control_root = _control_root(args.control_root)
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
        print("[INFO] AIA는 지원 범위 밖의 실행을 보호 실행으로 주장하지 않습니다.")
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
            "검사 결과가 READY이면 aia protect <workspace>를 실행합니다.",
        ],
    }
    if args.json:
        print(_json_text(payload))
    else:
        print(f"AIA Hook 설정 완료: {path}")
        print("[필수] Codex에서 /hooks를 열고 AIA Hook을 검토·신뢰하세요.")
        print("[다음] uv run aia doctor")
        print("[실행] uv run aia protect C:\\workspace\\my-project")
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
    payload = {
        "hook_path": str(installer.path),
        "pretool_installed": installer.is_installed(),
        "posttool_installed": installer.is_posttool_installed(),
        "trust_status": "MANUAL_REVIEW_REQUIRED",
        "activation_status": "OBSERVED_FROM_RUN" if last_verified else "NOT_OBSERVED",
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
        print(f"실제 Hook 관찰: {payload['activation_status']}")
        if last_verified:
            print(f"최근 검증 실행: {last_verified.get('session_id')}")
            print(f"Hook Events: {last_verified.get('hook_event_count', 0)}")
        else:
            print("최근에 Session에 연결된 Hook Event가 없습니다.")
        print("주의: 설치됨은 실제 보호 활성화를 의미하지 않습니다.")
    return 0 if payload["pretool_installed"] else 1


def _protected_run_preflight() -> tuple[bool, list[str]]:
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
    ready, failures = _protected_run_preflight()
    if not ready:
        print("AIA 보호 실행을 시작하지 않았습니다.")
        for failure in failures:
            print(f"[FAIL] {failure}")
        print("[다음] uv run aia setup")
        return 2
    service = RunApplicationService(_control_root(args.control_root))
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
        if args.command == "hook" and args.hook_command == "status":
            return _hook_status(args)
        if args.command == "protect":
            return _run_protected(args)
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
