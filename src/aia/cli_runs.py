"""Handlers for protected runs and run history CLI commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

from aia_app.presenters import action_summary


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

def _list_runs(args: argparse.Namespace) -> int:
    from aia.cli import RunApplicationService, _control_root, _json_text

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
    from aia.cli import (
        CodexHookInstaller,
        RunApplicationService,
        _cli_prefix,
        _control_root,
        _json_text,
    )

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
    from aia.cli import RunApplicationService, _control_root, _json_text

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
    from aia.cli import RunApplicationService, _control_root, _json_text

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
    from aia.cli import (
        ApplicationValidationError,
        CodexHookInstaller,
        RunApplicationService,
        _HOOK_VERIFICATION_PROBE_TOKEN_ENV,
        _cli_prefix,
        _control_root,
        _protected_run_preflight,
    )

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

