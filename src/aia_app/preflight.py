"""Preflight and Hook readiness reporting for the application service."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

from aia import CodexAdapter, CodexHookInstaller
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.hook_verification import HookVerificationStore


def _aia_cli_prefix(installer: CodexHookInstaller) -> str:
    """Return a usable local CLI command for messages shown by the web app."""

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
        return subprocess.list2cmdline([str(executable)])

    module_path = Path(__file__).resolve()
    project_root = next(
        (
            candidate
            for candidate in (module_path.parent, *module_path.parents)
            if (candidate / "pyproject.toml").is_file()
        ),
        None,
    )
    if project_root is None:
        return subprocess.list2cmdline([sys.executable, "-m", "aia.cli"])
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



class PreflightMixin:
    def preflight(
        self,
        *,
        runs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Report local prerequisites without starting a Protected Run."""

        checks: list[dict[str, Any]] = []
        hook_state = self._preflight_hook_state(checks)
        self._append_control_root_check(checks)
        activation = self._preflight_hook_activation(
            runs,
            hook_state["hook_verified"],
            hook_state["cli_prefix"],
        )
        readiness = self._preflight_readiness(checks, hook_state)
        return self._preflight_result(checks, hook_state, activation, readiness)

    def _preflight_hook_state(
        self,
        checks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        executable: Path | None = None
        try:
            executable = CodexAdapter().discover()
            checks.append(
                {
                    "name": "codex_executable",
                    "label": "Codex 실행 파일",
                    "ok": True,
                    "detail": str(executable),
                }
            )
        except Exception as error:
            checks.append(
                {
                    "name": "codex_executable",
                    "label": "Codex 실행 파일",
                    "ok": False,
                    "detail": f"찾을 수 없음 ({type(error).__name__})",
                }
            )

        installer = CodexHookInstaller()
        cli_prefix = _aia_cli_prefix(installer)
        pretool_installed = installer.is_installed()
        stale_hook_detected = not pretool_installed and installer.has_aia_runtime("PreToolUse")
        pretool_check: dict[str, Any] = {
            "name": "pretool_hook",
            "label": "PreToolUse Hook",
            "ok": pretool_installed,
            "stale": stale_hook_detected,
            "detail": (
                "설치됨 · Trust 상태 확인 중"
                if pretool_installed
                else (
                    f"기존 AIA Hook 경로가 남아 있음 · {cli_prefix} setup으로 현재 경로 갱신 필요"
                    if stale_hook_detected
                    else f"설치되지 않음 · {cli_prefix} setup 필요"
                )
            ),
        }
        checks.append(pretool_check)
        posttool_installed = installer.is_posttool_installed()
        checks.append(
            {
                "name": "posttool_hook",
                "label": "PostToolUse 관찰",
                "ok": posttool_installed,
                "optional": True,
                "detail": (
                    "설치됨 · 실행 결과 확인 가능"
                    if posttool_installed
                    else "선택 기능 미설치 · 차단 결과 확인 범위가 줄어듦"
                ),
            }
        )

        codex_hook_trust: dict[str, object] = {
            "available": False,
            "reason": "CODEX_EXECUTABLE_UNAVAILABLE",
            "hooks": [],
        }
        pretool_status: str | None = None
        if executable is not None and pretool_installed:
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
            trust_ok = pretool_status in {"TRUSTED", "MANAGED"}
            pretool_check["detail"] = (
                "설치됨 · Trust 확인됨"
                if trust_ok
                else "설치됨 · Codex /hooks 검토 필요"
            )
            checks.append(
                {
                    "name": "codex_hook_trust",
                    "label": "Codex Hook Trust",
                    "ok": trust_ok,
                    "optional": True,
                    "detail": (
                        f"PreToolUse={pretool_status}"
                        if pretool_status is not None
                        else "Codex에서 AIA PreToolUse Trust 상태를 확인할 수 없음"
                    ),
                }
            )

        hook_verified = False
        if self.require_hook_verification:
            try:
                executable = CodexAdapter().discover()
                hook_verified = HookVerificationStore(self.control_root).is_current(
                    installer,
                    executable,
                )
            except Exception:
                hook_verified = False
            checks.append(
                {
                    "name": "hook_verification",
                    "label": "실제 Hook 연결 증명",
                    "ok": hook_verified,
                    "detail": (
                        "최근 실제 Codex Probe에서 Session-bound Hook Event 확인"
                        if hook_verified
                        else f"{cli_prefix} hook verify 필요"
                    ),
                }
            )

        return {
            "executable": executable,
            "installer": installer,
            "cli_prefix": cli_prefix,
            "pretool_installed": pretool_installed,
            "stale_hook_detected": stale_hook_detected,
            "pretool_status": pretool_status,
            "codex_hook_trust": codex_hook_trust,
            "hook_verified": hook_verified,
        }

    def _append_control_root_check(self, checks: list[dict[str, Any]]) -> None:
        try:
            self.control_root.mkdir(parents=True, exist_ok=True)
            probe = self.control_root / ".aia-preflight-write-test"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks.append(
                {
                    "name": "control_root",
                    "label": "AIA Control Root",
                    "ok": True,
                    "detail": str(self.control_root),
                }
            )
        except OSError as error:
            checks.append(
                {
                    "name": "control_root",
                    "label": "AIA Control Root",
                    "ok": False,
                    "detail": f"쓰기 불가 ({type(error).__name__})",
                }
            )

    def _preflight_hook_activation(
        self,
        runs: list[dict[str, Any]] | None,
        hook_verified: bool,
        cli_prefix: str,
    ) -> dict[str, Any]:
        recent_runs = runs if runs is not None else self.list_runs()
        recent_verified = [
            item
            for item in recent_runs
            if item.get("hook_event_count", 0) > 0
            and item.get("protection_state")
            in {"ACTIVE_VERIFIED", "COMPLETED_VERIFIED", "ABORTED_VERIFIED"}
        ]
        recent_verified.sort(
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )
        last_verified = recent_verified[0] if recent_verified else None
        if hook_verified:
            hook_activation_status = "CURRENTLY_VERIFIED"
            hook_activation_detail = (
                "현재 Hook 설정과 Codex 실행 파일에 대한 실제 Session-bound Hook Event가 검증되었습니다."
            )
        elif last_verified:
            hook_activation_status = "OBSERVED_IN_PAST"
            hook_activation_detail = (
                "과거 실행에서 Hook Event가 관찰되었지만 현재 검증 증명이 만료되었거나 없습니다. "
                f"{cli_prefix} hook verify를 다시 실행하세요."
            )
        else:
            hook_activation_status = "NOT_OBSERVED"
            hook_activation_detail = "현재 환경에서 실제 보호 실행 Hook Event가 아직 관찰되지 않았습니다."

        return {
            "status": hook_activation_status,
            "detail": hook_activation_detail,
            "last_verified": last_verified,
        }

    def _preflight_readiness(
        self,
        checks: list[dict[str, Any]],
        hook_state: dict[str, Any],
    ) -> dict[str, Any]:
        executable = hook_state["executable"]
        cli_prefix = hook_state["cli_prefix"]
        stale_hook_detected = hook_state["stale_hook_detected"]
        pretool_installed = hook_state["pretool_installed"]
        pretool_status = hook_state["pretool_status"]
        hook_verified = hook_state["hook_verified"]
        control_root_check = next(
            (item for item in checks if item.get("name") == "control_root"),
            None,
        )
        if not self.require_hook_verification:
            required_checks_ok = all(
                bool(item["ok"])
                for item in checks
                if not item.get("optional")
            )
            readiness_code = "READY" if required_checks_ok else "NOT_READY"
            next_step = (
                "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다."
                if readiness_code == "READY"
                else (
                    f"기존 AIA Hook 경로를 현재 환경으로 갱신하려면 '{cli_prefix} setup'을 실행하세요."
                    if stale_hook_detected
                    else "위의 필수 확인 항목을 해결한 뒤 다시 검사하세요."
                )
            )
        elif executable is None:
            readiness_code = "CODEX_EXECUTABLE_UNAVAILABLE"
            next_step = "Codex CLI 설치와 PATH를 확인한 뒤 다시 검사하세요."
        elif not pretool_installed:
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
                f"'{cli_prefix} hook verify'를 실행하세요."
            )
        elif not hook_verified:
            readiness_code = "HOOK_VERIFICATION_REQUIRED"
            next_step = f"'{cli_prefix} hook verify'를 실행한 뒤 다시 검사하세요."
        elif not (control_root_check and control_root_check.get("ok")):
            readiness_code = "CONTROL_ROOT_NOT_WRITABLE"
            next_step = "AIA Control Root 권한을 확인한 뒤 다시 검사하세요."
        else:
            readiness_code = "READY"
            next_step = "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다."

        return {
            "ready": readiness_code == "READY",
            "readiness_code": readiness_code,
            "next_step": next_step,
        }

    def _preflight_result(
        self,
        checks: list[dict[str, Any]],
        hook_state: dict[str, Any],
        activation: dict[str, Any],
        readiness: dict[str, Any],
    ) -> dict[str, Any]:
        cli_prefix = hook_state["cli_prefix"]
        codex_hook_trust = hook_state["codex_hook_trust"]
        pretool_status = hook_state["pretool_status"]
        last_verified = activation["last_verified"]
        hook_trust_status = (
            pretool_status
            if pretool_status in {"TRUSTED", "MANAGED"}
            else "MANUAL_REVIEW_REQUIRED"
        )

        return {
            # The machine-readable readiness result must include effective
            # gates such as Codex Hook Trust, even when that check is marked
            # optional for telemetry purposes.
            "ready": readiness["ready"],
            "readiness_code": readiness["readiness_code"],
            "next_step": readiness["next_step"],
            "checks": checks,
            "hook_trust": {
                "status": hook_trust_status,
                "detail": (
                    "Codex PreToolUse Hook이 신뢰된 상태입니다."
                    if hook_trust_status in {"TRUSTED", "MANAGED"}
                    else (
                        "Codex에서 /hooks를 열어 AIA Hook을 직접 검토·신뢰해야 합니다."
                        if not codex_hook_trust.get("available")
                        else "Codex의 실제 Hook Trust 상태를 확인했습니다. TRUSTED가 아니면 /hooks에서 다시 검토·신뢰하세요."
                    )
                ),
            },
            "codex_hook_trust": codex_hook_trust,
            "hook_activation": {
                "status": activation["status"],
                "detail": activation["detail"],
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
            },
            "protection_claim": {
                "status": "CLAIM_ALLOWED_AFTER_SESSION_EVENT",
                "detail": (
                    "사전 조건 READY만으로 보호 성공을 주장하지 않습니다. "
                    "각 Protected Run에서 Hook Event가 확인된 뒤에만 보호 상태를 검증합니다."
                ),
            },
            "next_steps": [
                f"PreToolUse Hook이 없으면 '{cli_prefix} setup'을 실행합니다.",
                "Codex에서 /hooks를 열어 AIA Hook을 검토·신뢰합니다.",
                "Workspace와 정책을 선택해 보호 실행을 시작합니다.",
            ],
        }

