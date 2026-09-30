"""Handlers for CLI diagnostics and doctor readiness checks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile

from aia import (
    CheckpointValidity,
    CodexAdapter,
    CodexHookInstaller,
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    Operation,
    PolicyProfile,
    ProtectedRunSession,
    RawEvidenceRecord,
    RawEvidenceStore,
    SafeCheckpointManager,
    SessionEndReason,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    prepare_protection,
    resolve_profile,
)
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.hook_verification import HookVerificationStore
from aia_app import ApplicationValidationError
from aia_app.readers import ResultBundleReader


def _recent_run_diagnostic(control_root: Path) -> dict[str, object] | None:
    """Return safe metadata from the most recent committed Protected Run."""

    from aia.cli import _cli_prefix

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


@dataclass
class _DoctorPrerequisites:
    checks: list[dict[str, object]]
    supported_python: bool
    executable: Path | None
    executable_version: str
    cli_prefix: str
    hook_installed: bool
    stale_hook_detected: bool
    posttool_installed: bool
    codex_hook_trust: dict[str, object]
    pretool_status: str | None
    recent_run: dict[str, object] | None
    hook_verified: bool
    writable: bool


def _doctor_python_check(checks: list[dict[str, object]]) -> bool:
    supported_python = sys.version_info[:2] == (3, 13)
    checks.append(
        {
            "name": "python",
            "ok": supported_python,
            "value": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "detail": "Python 3.13 is required",
        }
    )
    return supported_python


def _doctor_codex_executable_check(
    checks: list[dict[str, object]],
) -> tuple[Path | None, str]:
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
    return executable, executable_version


def _doctor_hook_installation_check(
    args: argparse.Namespace, checks: list[dict[str, object]]
) -> tuple[CodexHookInstaller, str, bool, bool, bool]:
    from aia.cli import _cli_prefix

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
    return installer, cli_prefix, hook_installed, stale_hook_detected, posttool_installed


def _doctor_hook_trust_check(
    checks: list[dict[str, object]],
    executable: Path | None,
    installer: CodexHookInstaller,
    hook_installed: bool,
) -> tuple[dict[str, object], str | None, str | None]:
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
    return codex_hook_trust, pretool_status, posttool_status


def _doctor_final_checks(
    args: argparse.Namespace,
    checks: list[dict[str, object]],
    installer: CodexHookInstaller,
    cli_prefix: str,
    executable: Path | None,
    hook_installed: bool,
    codex_hook_trust: dict[str, object],
) -> tuple[dict[str, object] | None, bool, bool]:
    from aia.cli import _control_root, _control_root_write_check

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
    return recent_run, hook_verified, writable


def _doctor_prerequisite_checks(args: argparse.Namespace) -> _DoctorPrerequisites:
    checks: list[dict[str, object]] = []
    supported_python = _doctor_python_check(checks)
    executable, executable_version = _doctor_codex_executable_check(checks)
    (
        installer,
        cli_prefix,
        hook_installed,
        stale_hook_detected,
        posttool_installed,
    ) = _doctor_hook_installation_check(args, checks)
    codex_hook_trust, pretool_status, posttool_status = _doctor_hook_trust_check(
        checks, executable, installer, hook_installed
    )
    recent_run, hook_verified, writable = _doctor_final_checks(
        args,
        checks,
        installer,
        cli_prefix,
        executable,
        hook_installed,
        codex_hook_trust,
    )
    return _DoctorPrerequisites(
        checks=checks,
        supported_python=supported_python,
        executable=executable,
        executable_version=executable_version,
        cli_prefix=cli_prefix,
        hook_installed=hook_installed,
        stale_hook_detected=stale_hook_detected,
        posttool_installed=posttool_installed,
        codex_hook_trust=codex_hook_trust,
        pretool_status=pretool_status,
        recent_run=recent_run,
        hook_verified=hook_verified,
        writable=writable,
    )


def _doctor_readiness_summary(prerequisites: _DoctorPrerequisites) -> dict[str, object]:
    if not prerequisites.supported_python:
        readiness_code = "PYTHON_VERSION_UNSUPPORTED"
        next_step = "Python 3.13 환경에서 AIA를 다시 실행하세요."
    elif prerequisites.executable is None:
        readiness_code = "CODEX_EXECUTABLE_UNAVAILABLE"
        next_step = (
            "Codex CLI 설치와 PATH를 확인한 뒤 "
            f"'{prerequisites.cli_prefix} doctor'를 다시 실행하세요."
        )
    elif not prerequisites.hook_installed:
        readiness_code = "CODEX_HOOK_NOT_INSTALLED"
        next_step = (
            f"기존 AIA Hook 경로를 현재 환경으로 갱신하려면 '{prerequisites.cli_prefix} setup'을 실행하세요."
            if prerequisites.stale_hook_detected
            else f"'{prerequisites.cli_prefix} setup'을 실행한 뒤 Codex /hooks에서 AIA Hook을 검토하세요."
        )
    elif prerequisites.pretool_status not in {"TRUSTED", "MANAGED"}:
        readiness_code = "CODEX_HOOK_TRUST_REQUIRED"
        next_step = (
            "Codex /hooks에서 AIA PreToolUse Hook을 검토·신뢰한 뒤 "
            f"'{prerequisites.cli_prefix} hook verify'와 "
            f"'{prerequisites.cli_prefix} doctor'를 순서대로 실행하세요."
        )
    elif not prerequisites.hook_verified:
        readiness_code = "HOOK_VERIFICATION_REQUIRED"
        next_step = (
            f"'{prerequisites.cli_prefix} hook verify'를 실행한 뒤 "
            f"'{prerequisites.cli_prefix} doctor'를 다시 실행하세요."
        )
    elif not prerequisites.writable:
        readiness_code = "CONTROL_ROOT_NOT_WRITABLE"
        next_step = (
            "AIA Control Root 권한을 확인한 뒤 "
            f"'{prerequisites.cli_prefix} doctor'를 다시 실행하세요."
        )
    else:
        readiness_code = "READY"
        next_step = (
            f"'{prerequisites.cli_prefix} protect <workspace>'로 "
            "보호 실행을 시작할 수 있습니다."
        )

    return {
        "product": "AIA",
        "checks": prerequisites.checks,
        "ready": all(bool(item["ok"]) for item in prerequisites.checks),
        "readiness_code": readiness_code,
        "next_step": next_step,
        "codex_executable": (
            str(prerequisites.executable) if prerequisites.executable is not None else None
        ),
        "codex_version": prerequisites.executable_version,
        "optional_capabilities": {
            "posttool_observation": {
                "installed": prerequisites.posttool_installed,
                "detail": (
                    "PostToolUse evidence is enabled"
                    if prerequisites.posttool_installed
                    else "Run 'aia hook install' to add PostToolUse evidence"
                ),
            }
        },
        "codex_hook_trust": prerequisites.codex_hook_trust,
        "recent_protected_run": prerequisites.recent_run,
        "limitations": [
            "Hook trust is reviewed in Codex and cannot be proven by this local preflight command.",
            "The protected scope is Windows 11 + Codex CLI + supported PreToolUse matchers.",
        ],
    }


def _doctor(args: argparse.Namespace) -> int:
    """Check prerequisites without starting a Protected Run."""

    from aia.cli import _json_text

    prerequisites = _doctor_prerequisite_checks(args)
    payload = _doctor_readiness_summary(prerequisites)
    checks = prerequisites.checks
    cli_prefix = prerequisites.cli_prefix
    posttool_installed = prerequisites.posttool_installed
    codex_hook_trust = prerequisites.codex_hook_trust
    recent_run = prerequisites.recent_run
    next_step = payload["next_step"]
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


def _self_test(args: argparse.Namespace) -> int:
    """Exercise the disposable Core contracts without claiming live Codex proof."""
    from aia.cli import _cli_prefix, _json_text

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

    from aia.cli import _cli_prefix
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
            from aia.cli import _run_console

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

