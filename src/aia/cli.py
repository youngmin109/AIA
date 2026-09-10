"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Sequence

from aia import (
    CodexAdapter,
    CodexHookInstallationError,
    CodexHookInstaller,
    PolicyProfile,
    ResolvedPolicy,
    load_policy,
    policy_content_sha256,
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
        print("[INFO] AIA는 지원 범위 밖의 실행을 보호 실행으로 주장하지 않습니다.")
        print(f"결과: {'READY' if payload['ready'] else 'NOT_READY'}")
    return 0 if payload["ready"] else 1


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
        if args.command == "hook" and args.hook_command == "install":
            path = CodexHookInstaller(args.path).install()
            print(f"Codex Hook installed: {path}")
            print("Review and trust this Hook in Codex before starting a protected run.")
            return 0
        if args.command == "protect":
            return _run_protected(args)
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
