"""Handlers for Hook setup and inspection CLI commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from aia import CodexAdapter, CodexHookInstallationError, CodexHookInstaller
from aia.capabilities import product_capabilities
from aia.cli import (
    _cli_prefix,
    _control_root,
    _control_root_write_check,
    _json_text,
)
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.hook_verification import HookVerificationStore
from aia_app import RunApplicationService


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


