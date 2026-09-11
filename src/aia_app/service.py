"""Application orchestration for the optional Local Security Console."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import os
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from aia import (
    AttributionEngine,
    CodexAdapter,
    CodexHookBroker,
    CodexHookInstaller,
    CodexPreToolController,
    EnforcementGate,
    EnforcementGateInput,
    FilesystemSensor,
    HookSensor,
    HookTrustStatus,
    HookEnforcementBridge,
    Normalizer,
    Operation,
    PolicyProfile,
    ProcessIdentityStatus,
    ProcessManager,
    ProcessObserverCapability,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    ProtectedRunSession,
    ProcessIdentity,
    RawEvidenceStore,
    RecoveryCoordinator,
    RuntimePolicyEvaluator,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    resolve_profile,
    verify_process_identity,
)
from aia.session import SessionEndReason, WorkspaceValidationError
from aia.readiness import ProtectionReadinessBarrier
from aia.hook_verification import HookVerificationStore
from aia.codex_hook_trust import inspect_codex_hook_trust

from .dto import CreateRunRequest, DTOValidationError, PolicyPreviewRequest
from .presenters import action_view, incident_view, incident_views_for_result, result_view
from .readers import ResultBundleReader
from .registry import RunRecord, RunRegistry


class ApplicationValidationError(ValueError):
    """Raised when a console request cannot enter the Core pipeline."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _runtime_coordinator_reconciliation(state: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether a persisted non-terminal run still has a coordinator.

    Runtime state is a recovery hint, not a termination authority.  A stale
    state is therefore reported explicitly and never converted into a
    successful or terminal Session result here.
    """

    session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
    session_status = session.get("status")
    if session_status in {"COMPLETED", "ABORTED", "FAILED"}:
        return {
            "status": "TERMINAL",
            "orphaned": False,
            "action": "NONE",
            "detail": "Session is already terminal; the Result Bundle is authoritative.",
        }

    coordinator = state.get("coordinator")
    if not isinstance(coordinator, Mapping):
        return {
            "status": "UNKNOWN",
            "orphaned": False,
            "action": "NO_AUTOMATIC_CONCLUSION",
            "detail": "This runtime snapshot has no coordinator identity; live state cannot be proven.",
        }
    pid = coordinator.get("pid")
    create_time = coordinator.get("create_time")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(create_time, (int, float))
        or isinstance(create_time, bool)
    ):
        return {
            "status": "OWNER_UNVERIFIABLE",
            "orphaned": False,
            "action": "DO_NOT_TAKE_OVER",
            "detail": "The persisted AIA coordinator identity is malformed; takeover is refused.",
        }

    try:
        process_status = verify_process_identity(
            ProcessIdentity(pid=pid, create_time=float(create_time))
        )
    except (OSError, ValueError, TypeError):
        process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE

    managed_process = state.get("managed_process")
    agent_process_status = "NOT_RECORDED"
    if isinstance(managed_process, Mapping):
        root = managed_process.get("root_process_identity")
        root_pid = root.get("pid") if isinstance(root, Mapping) else None
        root_create_time = root.get("create_time") if isinstance(root, Mapping) else None
        if (
            isinstance(root_pid, int)
            and not isinstance(root_pid, bool)
            and root_pid > 0
            and isinstance(root_create_time, (int, float))
            and not isinstance(root_create_time, bool)
        ):
            try:
                agent_process_status = verify_process_identity(
                    ProcessIdentity(
                        pid=root_pid,
                        create_time=float(root_create_time),
                    )
                ).value
            except (OSError, TypeError, ValueError):
                agent_process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE.value
        else:
            agent_process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE.value

    if process_status is ProcessIdentityStatus.LIVE_MATCH:
        return {
            "status": "LIVE_MATCH",
            "orphaned": False,
            "action": "NONE",
            "agent_process_status": agent_process_status,
            "acknowledged": False,
            "detail": "The AIA coordinator process identity is still live.",
        }
    if process_status in {
        ProcessIdentityStatus.PROCESS_GONE,
        ProcessIdentityStatus.PID_REUSED,
    }:
        acknowledged = (
            isinstance(state.get("orphan_reconciliation"), Mapping)
            and state["orphan_reconciliation"].get("status") == "ACKNOWLEDGED"
        )
        return {
            "status": (
                "STALE_PROCESS_GONE"
                if process_status is ProcessIdentityStatus.PROCESS_GONE
                else "STALE_PID_REUSED"
            ),
            "orphaned": True,
            "action": "RECONCILED" if acknowledged else "REVIEW_AND_RESTART",
            "agent_process_status": agent_process_status,
            "acknowledged": acknowledged,
            "detail": (
                "The stale run was acknowledged after its recorded Agent root was verified gone."
                if acknowledged
                else "The AIA coordinator is no longer live. Protection cannot be assumed; "
                "review the run and restart only after the old Agent is closed."
            ),
        }
    return {
        "status": "OWNER_UNVERIFIABLE",
        "orphaned": False,
        "action": "DO_NOT_TAKE_OVER",
        "agent_process_status": agent_process_status,
        "acknowledged": False,
        "detail": "The AIA coordinator identity could not be verified; takeover is refused.",
    }


def _workspace_key(value: str | Path) -> str | None:
    """Return a case-insensitive key for comparing persisted workspaces."""

    try:
        return str(Path(value).expanduser().resolve(strict=False)).casefold()
    except (OSError, TypeError, ValueError):
        return None


def _sensor_status(sensor: Any) -> str | None:
    health = getattr(sensor, "health", None)
    if callable(health):
        health = health()
    status = getattr(health, "status", None)
    return getattr(status, "value", status)


def _sensors_runtime_healthy(sensors: Any) -> bool:
    items = tuple(item for item in (sensors or ()) if item is not None)
    return bool(items) and all(_sensor_status(item) == "HEALTHY" for item in items)


def _sensor_summary_is_verified(sensor_summary: Any) -> bool:
    summaries = tuple(
        item for item in (sensor_summary or ()) if isinstance(item, Mapping)
    )
    return bool(summaries) and all(
        item.get("runtime_health_before_stop") == "HEALTHY"
        and item.get("final_sensor_state") == "STOPPED"
        for item in summaries
    )


def _hook_broker_runtime_healthy(record: RunRecord) -> bool | None:
    """Return per-run Hook transport health when a launcher is available."""

    launcher = record.runtime.get("launcher")
    if launcher is None:
        return None
    broker = getattr(launcher, "hook_broker", None)
    if broker is None:
        return False
    status = getattr(broker, "is_running", None)
    if callable(status):
        status = status()
    return bool(status)


def _runtime_action_view(
    action: Any,
    policy_result: Any,
    attribution_result: Any,
    gate_result: Any,
) -> dict[str, Any]:
    """Build the redacted live/result action view from authoritative facts."""

    return {
        "action_id": action.action_id,
        "attribution_grade": attribution_result.grade.value,
        "attribution_reason": attribution_result.reason,
        "enforcement_action": gate_result.action.value,
        "enforcement_decision": gate_result.decision.value,
        "execution_result": gate_result.execution_result.value,
        "operation": action.operation.value,
        "policy_decision": policy_result.policy_decision.value,
        "operation_effect": (
            getattr(policy_result.operation_effect, "value", policy_result.operation_effect)
            if getattr(policy_result, "operation_effect", None) is not None
            else None
        ),
        "enforcement_route": gate_result.route.value,
        "evidence_ids": list(action.evidence_ids),
        "matched_rule_ids": list(
            getattr(policy_result, "matched_rule_ids", ()) or ()
        ),
        "matched_asset_types": [
            getattr(
                policy_result.asset_type,
                "value",
                policy_result.asset_type,
            )
        ]
        if getattr(policy_result, "asset_type", None) is not None
        else [],
        "target": {
            "canonical_path": action.canonical_path,
            "target_kind": action.target_kind.value,
        },
    }


class RunApplicationService:
    """Connect UI requests to existing AIA Core APIs.

    This class is an orchestrator and presentation boundary. It never creates
    policy, attribution, or enforcement decisions itself.
    """

    def __init__(
        self,
        control_root: str | Path,
        *,
        registry: RunRegistry | None = None,
        max_workers: int = 4,
        require_hook_verification: bool = False,
    ) -> None:
        self.control_root = Path(control_root).expanduser().resolve(strict=False)
        self.registry = registry or RunRegistry()
        self.reader = ResultBundleReader(self.control_root)
        self.require_hook_verification = require_hook_verification
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="aia-console-run",
        )

    @staticmethod
    def policy_profiles() -> list[dict[str, str]]:
        descriptions = {
            PolicyProfile.PROTECTED_DEVELOPMENT: (
                "민감정보 읽기와 대표적인 파괴 명령을 기본 차단하고, 그 밖의 개발 행위는 기록합니다."
            ),
            PolicyProfile.BASIC_DEVELOPMENT: (
                "일반 개발 작업을 허용하면서 .env 삭제와 위험한 데이터베이스·Git 명령을 통제합니다."
            ),
            PolicyProfile.CONSERVATIVE_SECURITY: (
                "비밀정보와 핵심 변경을 더 엄격하게 기록·차단하는 보호 우선 프로필입니다."
            ),
            PolicyProfile.FREE_DEVELOPMENT: (
                "개발 흐름을 가장 넓게 허용하고 위험 행위를 주로 기록하는 프로필입니다."
            ),
            PolicyProfile.CUSTOM: (
                "사용자가 작성한 Strict Validation 통과 정책 JSON을 고정해 사용합니다."
            ),
        }
        return [
            {
                "value": profile.value,
                "label": profile.display_name,
                "description": descriptions[profile],
            }
            for profile in (
                PolicyProfile.PROTECTED_DEVELOPMENT,
                PolicyProfile.BASIC_DEVELOPMENT,
                PolicyProfile.CONSERVATIVE_SECURITY,
                PolicyProfile.FREE_DEVELOPMENT,
                PolicyProfile.CUSTOM,
            )
        ]

    def preview_policy(
        self,
        request: PolicyPreviewRequest | dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate one target without starting an agent or touching a workspace."""

        if isinstance(request, dict):
            try:
                request = PolicyPreviewRequest.from_mapping(request)
            except DTOValidationError as error:
                raise ApplicationValidationError(str(error)) from error
        if not isinstance(request, PolicyPreviewRequest):
            raise ApplicationValidationError("policy preview request is invalid")

        try:
            profile = PolicyProfile.from_value(request.policy_profile)
            resolved = resolve_profile(
                profile,
                policy_source=(
                    Path(request.custom_policy_path)
                    if request.custom_policy_path is not None
                    else None
                ),
            )
            operation = Operation(request.operation)
            if operation is Operation.EXECUTE:
                evaluation = resolved.evaluate_target(
                    operation=operation,
                    raw_command=request.command,
                )
                target_kind = "COMMAND"
            else:
                evaluation = resolved.evaluate_target(
                    operation=operation,
                    path=request.path,
                )
                target_kind = "PATH"
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy preview failed: {error}") from error

        return {
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

    def preflight(self) -> dict[str, Any]:
        """Report local prerequisites without starting a Protected Run."""

        checks: list[dict[str, Any]] = []
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
        pretool_installed = installer.is_installed()
        checks.append(
            {
                "name": "pretool_hook",
                "label": "PreToolUse Hook",
                "ok": pretool_installed,
                "detail": (
                    "설치됨 · Codex에서 /hooks 검토 필요"
                    if pretool_installed
                    else "설치되지 않음 · aia setup 필요"
                ),
            }
        )
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
                    "label": "실시간 Hook 검증",
                    "ok": hook_verified,
                    "detail": (
                        "최근 실제 Codex Probe에서 Session-bound Hook Event 확인"
                        if hook_verified
                        else "uv run aia hook verify 필요"
                    ),
                }
            )

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

        control_root_check = next(
            (item for item in checks if item.get("name") == "control_root"),
            None,
        )
        recent_verified = [
            item
            for item in self.list_runs()
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
                "aia hook verify를 다시 실행하세요."
            )
        else:
            hook_activation_status = "NOT_OBSERVED"
            hook_activation_detail = "현재 환경에서 실제 보호 실행 Hook Event가 아직 관찰되지 않았습니다."

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
                else "위의 필수 확인 항목을 해결한 뒤 다시 검사하세요."
            )
        elif executable is None:
            readiness_code = "CODEX_EXECUTABLE_UNAVAILABLE"
            next_step = "Codex CLI 설치와 PATH를 확인한 뒤 다시 검사하세요."
        elif not pretool_installed:
            readiness_code = "CODEX_HOOK_NOT_INSTALLED"
            next_step = "'aia setup'을 실행한 뒤 Codex /hooks에서 AIA Hook을 검토하세요."
        elif pretool_status not in {"TRUSTED", "MANAGED"}:
            readiness_code = "CODEX_HOOK_TRUST_REQUIRED"
            next_step = (
                "Codex /hooks에서 AIA PreToolUse Hook을 검토·신뢰한 뒤 "
                "'aia hook verify'를 실행하세요."
            )
        elif not hook_verified:
            readiness_code = "HOOK_VERIFICATION_REQUIRED"
            next_step = "'aia hook verify'를 실행한 뒤 다시 검사하세요."
        elif not (control_root_check and control_root_check.get("ok")):
            readiness_code = "CONTROL_ROOT_NOT_WRITABLE"
            next_step = "AIA Control Root 권한을 확인한 뒤 다시 검사하세요."
        else:
            readiness_code = "READY"
            next_step = "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다."

        ready = readiness_code == "READY"

        hook_trust_status = (
            pretool_status
            if pretool_status in {"TRUSTED", "MANAGED"}
            else "MANUAL_REVIEW_REQUIRED"
        )

        return {
            # The machine-readable readiness result must include effective
            # gates such as Codex Hook Trust, even when that check is marked
            # optional for telemetry purposes.
            "ready": ready,
            "readiness_code": readiness_code,
            "next_step": next_step,
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
                "status": hook_activation_status,
                "detail": hook_activation_detail,
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
                "PreToolUse Hook이 없으면 'uv run aia setup'을 실행합니다.",
                "Codex에서 /hooks를 열어 AIA Hook을 검토·신뢰합니다.",
                "Workspace와 정책을 선택해 보호 실행을 시작합니다.",
            ],
        }

    def create_protected_run(self, request: CreateRunRequest | dict[str, Any]) -> dict[str, Any]:
        if isinstance(request, dict):
            try:
                request = CreateRunRequest.from_mapping(request)
            except DTOValidationError as error:
                raise ApplicationValidationError(str(error)) from error
        if not isinstance(request, CreateRunRequest):
            raise ApplicationValidationError("request is invalid")
        if self.require_hook_verification:
            installer = CodexHookInstaller()
            try:
                executable = CodexAdapter().discover()
            except Exception as error:
                raise ApplicationValidationError(
                    "Codex 실행 파일을 찾을 수 없습니다"
                ) from error
            if not HookVerificationStore(self.control_root).is_current(
                installer,
                executable,
            ):
                raise ApplicationValidationError(
                    "실제 Codex Hook 검증이 없습니다. 먼저 'uv run aia hook verify'를 실행하세요."
                )
            inspection = inspect_codex_hook_trust(
                executable,
                hook_path=installer.path,
                cwd=Path.cwd(),
                timeout=8.0,
            ).to_mapping()
            pretool_status = next(
                (
                    item.get("trust_status")
                    for item in (inspection.get("hooks") or [])
                    if isinstance(item, dict) and item.get("event") == "preToolUse"
                ),
                None,
            )
            if pretool_status not in {"TRUSTED", "MANAGED"}:
                raise ApplicationValidationError(
                    "Codex PreToolUse Hook Trust가 확인되지 않았습니다. "
                    "Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 다시 시도하세요."
                )
        workspace = self._validate_workspace(request.workspace)
        orphan = self._unresolved_orphan_for_workspace(workspace)
        if orphan is not None:
            session_id = orphan["session_id"]
            reconciliation = orphan["runtime_reconciliation"]
            raise ApplicationValidationError(
                "이 Workspace에는 정리되지 않은 이전 Protected Run이 있습니다 "
                f"({session_id}, {reconciliation.get('status', 'UNKNOWN')}). "
                "이전 Codex가 실행 중이면 먼저 종료하고, Agent Root가 사라진 것을 "
                f"확인한 뒤 'uv run aia reconcile {session_id}'를 실행하세요."
            )
        if not request.interactive and not request.task.strip():
            raise ApplicationValidationError(
                "task is required for a non-interactive protected run"
            )
        if request.agent.lower() != "codex":
            raise ApplicationValidationError("only Codex is supported in this console")
        try:
            mode = SessionMode(request.mode.upper())
        except ValueError as error:
            raise ApplicationValidationError("mode must be ENFORCE or AUDIT") from error
        try:
            profile = PolicyProfile.from_value(request.policy_profile)
            resolved = resolve_profile(
                profile,
                policy_source=(
                    Path(request.custom_policy_path)
                    if request.custom_policy_path is not None
                    else None
                ),
            )
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=mode,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            created_at=_now(),
        )
        record = RunRecord(
            session_id=session.session_id,
            workspace=workspace,
            agent=session.agent,
            model=request.model,
            policy_profile=profile.value,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            mode=mode.value,
            task=request.task,
            interactive=request.interactive,
            created_at=session.created_at,
            protection_state="STARTING",
            coordinator_pid=os.getpid(),
            coordinator_process_create_time=process_create_time(os.getpid()),
        )
        record.runtime.update({"request": request, "resolved_policy": resolved, "session": session})
        self._persist_runtime_state(record, strict=True)
        self.registry.add(record)
        self._executor.submit(self._run, record)
        return {
            "redirect_url": f"/runs/{session.session_id}",
            "session_id": session.session_id,
            "status": session.status.value,
        }

    def get_run_status(self, session_id: str) -> dict[str, Any]:
        live_record = self.registry.get(session_id)
        live_hook_broker_healthy: bool | None = None
        if live_record is not None:
            self._refresh_protection_state(live_record)
            live_hook_broker_healthy = _hook_broker_runtime_healthy(live_record)
        record = self.registry.snapshot(session_id)
        if record is None:
            try:
                return self._status_from_completed_bundle(session_id)
            except (KeyError, OSError, ValueError):
                runtime_state = self._read_runtime_state(session_id)
                if runtime_state is None:
                    raise
                return self._status_from_runtime_state(runtime_state)
        hook_broker_healthy = (
            live_hook_broker_healthy
            if live_record is not None
            else _hook_broker_runtime_healthy(record)
        )
        incidents = list(record.incidents)
        return {
            "checkpoint": record.checkpoint,
            "error": record.error,
            "incident_count": len(incidents),
            "latest_actions": record.actions[-20:],
            "lease": record.lease,
            "mode": record.mode,
            "interactive": record.interactive,
            "phase": record.phase,
            "result_path": str(record.result_path) if record.result_path is not None else None,
            "protection": {
                "state": record.protection_state,
                "hook_events": record.hook_event_count,
                "hook_broker": (
                    "HEALTHY"
                    if hook_broker_healthy is True
                    else "FAILED"
                    if hook_broker_healthy is False
                    else "NOT_STARTED"
                ),
            },
            "stop": {
                "requested": record.stop_requested,
                "error": record.stop_error,
            },
            "policy": {
                "id": record.policy_id,
                "profile": record.policy_profile,
                "version": record.policy_version,
            },
            "result_available": bool(record.result_path),
            "sensor_health": dict(record.sensor_health),
            "session": {
                "agent": record.agent,
                "created_at": record.created_at.isoformat(),
                "model": record.model,
                "session_id": record.session_id,
                "status": record.status,
                "workspace": str(record.workspace),
            },
        }

    def request_stop(self, session_id: str) -> dict[str, Any]:
        """Request a user-initiated stop for one live Protected Run.

        The launcher performs identity-safe tree termination.  This method
        records the request and never turns a failed stop into a success claim.
        """

        record = self.registry.get(session_id)
        if record is None:
            try:
                result = self.reader.read_result(session_id)
            except (KeyError, OSError, ValueError):
                try:
                    self._write_stop_request(session_id)
                except (OSError, ValueError):
                    raise KeyError(session_id) from None
                return {
                    "accepted": True,
                    "session_id": session_id,
                    "status": "STOP_REQUESTED",
                    "reason": "STOP_REQUEST_STORED",
                }
            return {
                "accepted": False,
                "session_id": session_id,
                "status": result.get("session_status", "UNKNOWN"),
                "reason": "RUN_ALREADY_TERMINAL",
            }
        if record.status in {"COMPLETED", "ABORTED", "FAILED"}:
            return {
                "accepted": False,
                "session_id": session_id,
                "status": record.status,
                "reason": "RUN_ALREADY_TERMINAL",
            }
        record.stop_requested = True
        try:
            self._write_stop_request(session_id)
        except (OSError, ValueError) as error:
            record.stop_error = f"STOP_REQUEST_PERSIST_FAILED: {type(error).__name__}"
        self._persist_runtime_state(record)
        launcher = record.runtime.get("launcher")
        launcher_status = getattr(getattr(launcher, "status", None), "value", None)
        if launcher is not None and launcher_status == "STARTING":
            try:
                stopped = self._request_user_abort(record, launcher)
            except Exception as error:
                stopped = False
                record.stop_error = f"{type(error).__name__}: {error}"
            if stopped:
                record.protection_state = "STOP_REQUESTED"
                self._persist_runtime_state(record)
                return {
                    "accepted": True,
                    "session_id": session_id,
                    "status": "STOP_REQUESTED",
                    "reason": "USER_ABORT_DURING_LAUNCH",
                }
            if record.runtime.get("user_abort_termination_result"):
                record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
                record.protection_state = "DEGRADED"
            else:
                record.protection_state = "STOP_REQUESTED"
            self._persist_runtime_state(record)
            return {
                "accepted": True,
                "session_id": session_id,
                "status": "STOP_REQUESTED",
                "reason": "STOP_WILL_BE_APPLIED_BEFORE_AGENT_LAUNCH",
            }
        if launcher is None or launcher_status != "RUNNING":
            record.protection_state = "STOP_REQUESTED"
            self._persist_runtime_state(record)
            return {
                "accepted": True,
                "session_id": session_id,
                "status": "STOP_REQUESTED",
                "reason": "STOP_WILL_BE_APPLIED_BEFORE_AGENT_LAUNCH",
            }
        try:
            stopped = self._request_user_abort(record, launcher)
        except Exception as error:
            stopped = False
            record.stop_error = f"{type(error).__name__}: {error}"
        if not stopped:
            record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
            record.protection_state = "DEGRADED"
            self._persist_runtime_state(record)
            return {
                "accepted": False,
                "session_id": session_id,
                "status": record.status,
                "reason": record.stop_error,
            }
        record.protection_state = "STOP_REQUESTED"
        self._persist_runtime_state(record)
        return {
            "accepted": True,
            "session_id": session_id,
            "status": "STOP_REQUESTED",
            "reason": "USER_ABORT_REQUESTED",
        }

    def reconcile_orphaned_run(self, session_id: str) -> dict[str, Any]:
        """Acknowledge a crashed coordinator only after the Agent root is gone.

        This operation preserves the stale runtime snapshot and all evidence.
        It only records an operational acknowledgement that permits a later
        protected run to reuse the Workspace after identity-safe checks.
        """

        if self.registry.get(session_id) is not None:
            return {
                "reconciled": False,
                "session_id": session_id,
                "reason": "RUN_IS_CONTROLLED_BY_THIS_AIA_PROCESS",
            }
        state = self._read_runtime_state(session_id)
        if state is None:
            raise KeyError(session_id)
        reconciliation = _runtime_coordinator_reconciliation(state)
        if not reconciliation.get("orphaned"):
            return {
                "reconciled": False,
                "session_id": session_id,
                "reason": "ORPHANED_COORDINATOR_NOT_PROVEN",
                "runtime_reconciliation": reconciliation,
            }
        if reconciliation.get("acknowledged"):
            return {
                "reconciled": True,
                "session_id": session_id,
                "reason": "ORPHAN_ALREADY_ACKNOWLEDGED",
                "runtime_reconciliation": reconciliation,
            }
        if reconciliation.get("agent_process_status") not in {
            ProcessIdentityStatus.PROCESS_GONE.value,
            ProcessIdentityStatus.PID_REUSED.value,
        }:
            return {
                "reconciled": False,
                "session_id": session_id,
                "reason": "RECORDED_AGENT_ROOT_NOT_PROVEN_GONE",
                "runtime_reconciliation": reconciliation,
            }

        acknowledged_at = _now().isoformat()
        updated = dict(state)
        updated["orphan_reconciliation"] = {
            "status": "ACKNOWLEDGED",
            "acknowledged_at": acknowledged_at,
            "reason": "RECORDED_AGENT_ROOT_NOT_LIVE",
        }
        self._write_runtime_state_payload(session_id, updated)
        result = _runtime_coordinator_reconciliation(updated)
        return {
            "reconciled": True,
            "session_id": session_id,
            "reason": "ORPHAN_RECONCILED_AFTER_ROOT_CHECK",
            "runtime_reconciliation": result,
        }

    def get_run_actions(self, session_id: str) -> list[dict[str, Any]]:
        record = self.registry.snapshot(session_id)
        if record is not None:
            return record.actions
        result = self.reader.read_result(session_id)
        return [action_view(item) for item in result.get("action_outcomes", [])]

    def list_runs(self) -> list[dict[str, Any]]:
        """Return live runs plus valid persisted Bundles for the local console."""

        values: dict[str, dict[str, Any]] = {}
        for state in self._list_runtime_states():
            state = self._runtime_state_for_display(state)
            session = state.get("session") if isinstance(state.get("session"), dict) else {}
            policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
            protection = state.get("protection") if isinstance(state.get("protection"), dict) else {}
            session_id = state.get("session_id")
            if not isinstance(session_id, str):
                continue
            session_status = session.get("status", "UNKNOWN")
            result_available = bool(state.get("result_available"))
            # A runtime snapshot is only a recovery hint. It must not look
            # like a committed product result when its Result Bundle cannot
            # be verified (for example after an interrupted probe or an old
            # incompatible artifact).
            verification = self.reader.verification(session_id) if result_available else None
            if verification is not None and verification.is_valid:
                run_classification = "PRODUCT_PROTECTED_RUN"
                bundle_status = verification.status.value
            elif session_status in {"COMPLETED", "ABORTED", "FAILED"}:
                run_classification = "UNVERIFIED_RUNTIME_STATE"
                bundle_status = "UNVERIFIED"
            else:
                run_classification = "LIVE_PROTECTED_RUN"
                bundle_status = "PENDING"
            values[session_id] = {
                "session_id": session_id,
                "status": session_status,
                "ended_at": None,
                "created_at": session.get("created_at"),
                "workspace": session.get("workspace"),
                "agent": session.get("agent"),
                "policy": {
                    "id": policy.get("id"),
                    "version": policy.get("version"),
                },
                "run_classification": run_classification,
                "bundle_status": bundle_status,
                "incident_count": state.get("incident_count", 0),
                "result_url": f"/runs/{session_id}/result",
                "protection_state": protection.get("state", "UNKNOWN"),
                "hook_event_count": protection.get("hook_events", 0),
                "runtime_reconciliation": state.get("runtime_reconciliation"),
            }
        for record in self.registry.snapshots():
            live_record = self.registry.get(record.session_id)
            if live_record is not None:
                self._refresh_protection_state(live_record)
                record = self.registry.snapshot(record.session_id) or record
            if record.status in {"COMPLETED", "ABORTED", "FAILED"} and record.bundle_status != "VALID":
                run_classification = "UNVERIFIED_RUNTIME_STATE"
                bundle_status = "UNVERIFIED"
            else:
                run_classification = "PRODUCT_PROTECTED_RUN"
                bundle_status = record.bundle_status or "PENDING"
            values[record.session_id] = {
                "session_id": record.session_id,
                "status": record.status,
                "ended_at": None,
                "created_at": record.created_at.isoformat(),
                "workspace": str(record.workspace),
                "agent": record.agent,
                "policy": {"id": record.policy_id, "version": record.policy_version},
                "run_classification": run_classification,
                "bundle_status": bundle_status,
                "incident_count": len(record.incidents),
                "result_url": f"/runs/{record.session_id}/result",
                "protection_state": record.protection_state,
                "hook_event_count": record.hook_event_count,
            }
        for item in self.reader.list_completed():
            values[item["session_id"]] = item
        return sorted(
            values.values(),
            key=lambda item: str(item.get("ended_at") or item.get("created_at") or ""),
            reverse=True,
        )

    def get_incidents(self, session_id: str) -> list[dict[str, Any]]:
        record = self.registry.snapshot(session_id)
        if record is not None:
            if record.result is not None:
                return result_view(record.result, record.bundle_status or "UNKNOWN")["incidents"]
            return record.incidents
        result = self.reader.read_result(session_id)
        return incident_views_for_result(result)

    def get_incident(self, session_id: str, action_id: str) -> dict[str, Any]:
        incident = next(
            (item for item in self.get_incidents(session_id) if item.get("action_id") == action_id),
            None,
        )
        if incident is None:
            raise KeyError(action_id)
        return incident

    def get_result(self, session_id: str) -> dict[str, Any]:
        record = self.registry.snapshot(session_id)
        if record is not None and record.result is not None and record.bundle_status is not None:
            view = result_view(record.result, record.bundle_status)
            view["posttool_event_count"] = self.reader.posttool_event_count(session_id)
            return view
        result = self.reader.read_result(session_id)
        verification = self.reader.verification(session_id)
        view = result_view(result, verification.status.value if verification else "NOT_FOUND")
        view["posttool_event_count"] = self.reader.posttool_event_count(session_id)
        return view

    def get_report(self, session_id: str) -> str:
        return self.reader.read_report(session_id)

    def get_result_json(self, session_id: str) -> bytes:
        return self.reader.read_result_json(session_id)

    def get_raw_evidence(self, session_id: str) -> list[dict[str, Any]]:
        return self.reader.read_evidence_metadata(session_id)

    def validate_workspace(self, value: str) -> dict[str, Any]:
        workspace = self._validate_workspace(value)
        return {
            "valid": True,
            "exists": workspace.exists(),
            "is_directory": workspace.is_dir(),
            "canonical_path": str(workspace),
        }

    def shutdown(self, wait: bool = True) -> None:
        """Stop live Protected Runs before closing the application service.

        A console process can be interrupted while a Codex child is still
        running.  Leaving the executor to shut down by itself would close the
        AIA coordinator while the managed Agent remains alive.  Requesting a
        user abort first lets the existing identity-safe launcher cleanup path
        terminate the registered tree and finalize the run honestly.
        """

        for record in self.registry.snapshots():
            if record.status in {"COMPLETED", "ABORTED", "FAILED"}:
                continue
            try:
                self.request_stop(record.session_id)
            except (KeyError, OSError, ValueError):
                # The worker may have finalized between the snapshot and the
                # stop request.  Its own finalization remains authoritative.
                continue
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _validate_workspace(value: str) -> Path:
        try:
            from aia import canonicalize_workspace

            return canonicalize_workspace(value)
        except (WorkspaceValidationError, OSError, ValueError) as error:
            raise ApplicationValidationError(f"workspace validation failed: {error}") from error

    def _unresolved_orphan_for_workspace(self, workspace: Path) -> dict[str, Any] | None:
        """Refuse reuse until a stale run's recorded Agent root is reconciled.

        Workspace lease takeover is identity-safe for the AIA owner, but it
        cannot by itself prove that a crashed coordinator's Agent child has
        stopped.  The persisted run must therefore be acknowledged after the
        Agent root is gone before another protected run can use the workspace.
        """

        workspace_key = _workspace_key(workspace)
        if workspace_key is None:
            return None
        for state in self._list_runtime_states():
            session = state.get("session")
            if not isinstance(session, Mapping):
                continue
            state_workspace = session.get("workspace")
            if _workspace_key(state_workspace) != workspace_key:
                continue
            reconciliation = _runtime_coordinator_reconciliation(state)
            if not reconciliation.get("orphaned"):
                continue
            if reconciliation.get("action") == "RECONCILED":
                continue
            session_id = state.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            return {
                "session_id": session_id,
                "phase": state.get("phase"),
                "runtime_reconciliation": reconciliation,
            }
        return None

    def _run(self, record: RunRecord) -> None:
        session: ProtectedRunSession = record.runtime["session"]
        resolved = record.runtime["resolved_policy"]
        manager: WorkspaceLeaseManager | None = None
        lease = None
        sensors: tuple[Any, ...] = ()
        finalization_done = False
        codex_output_handles: list[Any] = []
        try:
            self._phase(record, "PREPARING", SessionStatus.PREPARING)
            record.protection_state = "PREPARING"
            session.transition(SessionStatus.PREPARING, at=_now())
            manager = WorkspaceLeaseManager(
                self.control_root,
                process_identity_provider=process_create_time,
            )
            preparation = prepare_protection(
                session,
                resolved,
                self.control_root,
                lease_manager=manager,
                owner_pid=os.getpid(),
                owner_process_create_time=process_create_time(os.getpid()),
            )
            lease = preparation.workspace_lease
            record.runtime.update({"preparation": preparation, "lease_manager": manager})
            record.lease = "ACTIVE"
            checkpoint = create_safe_checkpoint(session, preparation, lease_manager=manager)
            record.runtime["checkpoint"] = checkpoint
            record.checkpoint = "READY"

            filesystem = FilesystemSensor(session, preparation, checkpoint, lease_manager=manager)
            hook = HookSensor(session, preparation, checkpoint, lease_manager=manager)
            filesystem.start()
            hook.start()
            sensors = (filesystem, hook)
            record.runtime["sensors"] = sensors
            self._refresh_sensors(record, sensors)
            readiness = ProtectionReadinessBarrier(
                session,
                preparation,
                checkpoint,
                filesystem,
                hook,
                ProcessObserverCapability(
                    aia_session_id=session.session_id,
                    workspace=session.workspace,
                ),
                lease_manager=manager,
            ).evaluate()
            if readiness.readiness_context is None:
                raise RuntimeError("readiness barrier failed")
            if record.stop_requested:
                self._finalize_user_abort_before_launch(
                    record,
                    session,
                    preparation,
                    checkpoint,
                    sensors,
                    manager,
                    lease,
                )
                finalization_done = True
                return
            self._phase(record, "READY", SessionStatus.READY)
            record.protection_state = "READY_UNVERIFIED"

            launch_holder: dict[str, Any] = {}
            bridge = HookEnforcementBridge()
            launcher: ProtectedLauncher

            def execute_post_action_containment(containment: Any) -> Any:
                """Execute only a verified compensating containment request."""

                process_manager = record.runtime.get("process_manager")
                launch_context = launch_holder.get("context")
                if process_manager is None or launch_context is None:
                    raise RuntimeError("PROCESS_CONTAINMENT_CONTEXT_UNAVAILABLE")
                result = process_manager.execute(
                    containment.gate_result,
                    session=session,
                    launch_context=launch_context,
                    workspace_lease=preparation.workspace_lease,
                )
                record.runtime["process_termination_result"] = result
                record.runtime.setdefault("post_action_gate_results", []).append(
                    containment.gate_result
                )
                self._persist_runtime_state(record)
                return result

            controller = CodexPreToolController(
                session,
                preparation,
                filesystem,
                hook,
                checkpoint=checkpoint,
                lease_manager=manager,
                bridge=bridge,
                launch_context_provider=lambda: launch_holder.get("context"),
                process_sensor_provider=lambda: launcher.process_sensor,
                post_action_containment_callback=execute_post_action_containment,
            )

            def broker_factory(launch_id: str, prepared_bridge: HookEnforcementBridge) -> CodexHookBroker:
                if prepared_bridge is not bridge:
                    raise RuntimeError("Hook bridge identity changed")
                return CodexHookBroker(
                    capability_secret=prepared_bridge.capability_secret or "",
                    session_id=session.session_id,
                    launch_id=launch_id,
                    control_root=preparation.control_directory,
                    handler=controller.handle,
                )

            def capture_popen(argv: list[str], **kwargs: Any) -> Any:
                """Capture non-interactive Codex output in temporary handles only."""

                if record.interactive:
                    return subprocess.Popen(argv, **kwargs)
                stdout_stream = tempfile.TemporaryFile(mode="w+b")
                stderr_stream = tempfile.TemporaryFile(mode="w+b")
                codex_output_handles.extend((stdout_stream, stderr_stream))
                kwargs["stdout"] = stdout_stream
                kwargs["stderr"] = stderr_stream
                try:
                    return subprocess.Popen(argv, **kwargs)
                except Exception:
                    stdout_stream.close()
                    stderr_stream.close()
                    raise

            if not CodexHookInstaller().is_installed():
                raise RuntimeError(
                    "CODEX_HOOK_NOT_INSTALLED: run 'aia hook install' and review/trust the Hook"
                )
            launcher = ProtectedLauncher(
                session,
                readiness.readiness_context,
                preparation,
                checkpoint,
                filesystem,
                hook,
                adapter=CodexAdapter(enable_hooks=True),
                lease_manager=manager,
                hook_bridge=bridge,
                hook_broker_factory=broker_factory,
                popen_factory=capture_popen,
                capture_process_command_line=True,
                launch_context_callback=lambda context: self._record_launch_context(
                    record,
                    launch_holder,
                    context,
                ),
            )
            record.runtime["process_manager"] = ProcessManager(
                launcher.managed_process_registry,
                manager,
            )
            adapter_options: dict[str, Any] = {}
            if record.interactive:
                adapter_options.update(
                    {
                        "approval_policy": "on-request",
                        "sandbox": "workspace-write",
                    }
                )
                adapter_options["interactive"] = True
            else:
                # Codex CLI's current exec contract applies the supported
                # workspace-write/on-request policy through --approve-for-me.
                # Passing -c approval_policy=on-request alone is silently
                # reported as approval=never on some Windows installations.
                adapter_options["approve_for_me"] = True
                adapter_options["skip_git_repo_check"] = True
            if record.stop_requested:
                self._finalize_user_abort_before_launch(
                    record,
                    session,
                    preparation,
                    checkpoint,
                    sensors,
                    manager,
                    lease,
                )
                finalization_done = True
                return
            # Keep launch work visible. The Session remains READY until the
            # launcher has registered the Codex root and process sensor, but
            # the product phase must show that Codex creation is in progress.
            record.protection_state = "LAUNCHING"
            self._phase(record, "LAUNCHING", SessionStatus.READY)
            record.runtime.update(
                {"launcher": launcher, "codex_controller": controller}
            )
            launch = launcher.launch(
                ProtectedLaunchRequest(
                    aia_session_id=session.session_id,
                    workspace=session.workspace,
                    agent="codex",
                    model=record.model,
                    prompt=record.task,
                    adapter_options=adapter_options,
                )
            )
            record.runtime["launch"] = launch
            if record.stop_requested:
                if launch.context is None:
                    self._finalize_user_abort_before_launch(
                        record,
                        session,
                        preparation,
                        checkpoint,
                        sensors,
                        manager,
                        lease,
                    )
                    finalization_done = True
                    return
                if not self._request_user_abort(record, launcher):
                    record.stop_error = "USER_ABORT_TERMINATION_UNCONFIRMED"
            if launch.context is None or launch.status.value != "RUNNING":
                raise RuntimeError(launch.failure_code or "Codex launch failed")
            process_sensor = launcher.process_sensor
            sensors = (filesystem, hook, process_sensor)
            record.runtime["sensors"] = sensors
            self._phase(record, "RUNNING", SessionStatus.RUNNING)
            record.protection_state = "ACTIVE_UNVERIFIED"
            process = launcher.process_handle
            exit_code = self._wait_for_agent(record, process, launcher)
            record.runtime["exit_code"] = exit_code
            hook_broker_healthy_before_stop = _hook_broker_runtime_healthy(record)
            record.runtime["hook_broker_runtime_healthy_before_stop"] = (
                hook_broker_healthy_before_stop
            )
            launcher.stop_hook_broker()
            self._capture_codex_execution_observation(record, codex_output_handles)
            self._confirm_codex_blocks(record)
            self._process_evidence(record)
            recovery_verification = self._recover_after_containment(
                record,
                session=session,
                preparation=preparation,
                checkpoint=checkpoint,
                lease=lease,
                launch_context=launch.context,
            )
            raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
            process_identity = launch.context.root_process_identity
            protection_failure_reason = record.runtime.get("protection_failure_reason")
            end_reason = (
                SessionEndReason.PROTECTION_FAILURE
                if protection_failure_reason
                else SessionEndReason.USER_ABORT
                if record.stop_requested
                else SessionEndReason.AGENT_EXITED
            )
            limitations = list(
                ("USER_ABORT_TERMINATION_UNCONFIRMED",)
                if record.stop_error
                else ()
            )
            if protection_failure_reason:
                limitations.append("PROTECTION_BOUNDARY_LOST")
                protection_failure_result = (
                    record.runtime.get("protection_failure_termination_result") or {}
                )
                if protection_failure_result.get("status") != "SUCCEEDED":
                    limitations.append("PROTECTION_FAILURE_TERMINATION_UNCONFIRMED")
            if record.runtime.get("post_action_containment_errors"):
                limitations.append("POST_ACTION_CONTAINMENT_DEGRADED")
            if getattr(controller, "unsupported_tool_names", ()):
                limitations.append("UNSUPPORTED_TOOL_PATH")
            if record.runtime.get("codex_sandbox_downgraded"):
                limitations.append("CODEX_SANDBOX_DOWNGRADED")
            if record.runtime.get("codex_approval_policy_downgraded"):
                limitations.append("CODEX_APPROVAL_POLICY_DOWNGRADED")
            if recovery_verification is not None and not recovery_verification.verified_recovery_success:
                limitations.append("RECOVERY_NOT_VERIFIED")
            if not _sensors_runtime_healthy(sensors):
                limitations.append("SENSOR_RUNTIME_NOT_VERIFIED")
            if hook_broker_healthy_before_stop is not True:
                limitations.append("HOOK_BROKER_RUNTIME_NOT_VERIFIED")
            final = SessionFinalizer(
                evidence_store=raw_store,
                sensors=sensors,
                lease_manager=manager,
                workspace_lease=lease,
            ).finalize(
                session,
                end_reason=end_reason,
                process_identity=process_identity,
                process_end_status=ProcessIdentityStatus.PROCESS_GONE,
                actions=record.runtime.get("normalized_actions", ()),
                policy_evaluations=record.runtime.get("policy_evaluations", ()),
                attribution_results=record.runtime.get("attribution_results", ()),
                enforcement_results=record.runtime.get("gate_results", ()),
                termination_result=record.runtime.get("process_termination_result"),
                recovery_result=recovery_verification,
                integrity_result=(
                    recovery_verification.integrity_result
                    if recovery_verification is not None
                    else None
                ),
                active_policy=preparation.active_policy,
                checkpoint=checkpoint,
                launch_context=launch.context,
                run_classification="PRODUCT_PROTECTED_RUN",
                agent_exit_code=exit_code,
                agent_end_observed_at=_now(),
                agent_end_verification="PROCESS_GONE",
                agent_output_observation=record.runtime.get("codex_output_observation"),
                user_abort_termination_result=record.runtime.get("user_abort_termination_result"),
                protection_failure_termination_result=record.runtime.get(
                    "protection_failure_termination_result"
                ),
                limitations=tuple(limitations),
            )
            finalization_done = True
            result_mapping = final.result.to_mapping()
            verification = final.bundle_verification
            record.runtime["final"] = final
            sensor_verified = _sensor_summary_is_verified(final.result.sensor_summary)
            self.registry.update(
                record.session_id,
                status=final.result.session_status.value,
                phase="COMPLETED" if final.result.session_status is SessionStatus.COMPLETED else final.result.session_status.value,
                lease="RELEASED",
                result_path=final.bundle.result_directory / "result.json",
                result=result_mapping,
                bundle_status=verification.status.value,
                protection_state=(
                    "FAILED_DEGRADED"
                    if final.result.session_status is SessionStatus.FAILED
                    else
                    "ABORTED_VERIFIED"
                    if final.result.session_status is SessionStatus.ABORTED
                    and not record.stop_error
                    and controller.events
                    and not controller.errors
                    and sensor_verified
                    and hook_broker_healthy_before_stop is True
                    and not record.runtime.get("codex_sandbox_downgraded")
                    and not record.runtime.get("codex_approval_policy_downgraded")
                    else "ABORTED_DEGRADED"
                    if final.result.session_status is SessionStatus.ABORTED
                    else "COMPLETED_VERIFIED"
                    if controller.events and not controller.errors
                    and sensor_verified
                    and hook_broker_healthy_before_stop is True
                    and not record.runtime.get("codex_sandbox_downgraded")
                    and not record.runtime.get("codex_approval_policy_downgraded")
                    else "COMPLETED_DEGRADED"
                ),
                hook_event_count=len(controller.events),
                sensor_health={
                    item.get("sensor"): item.get("runtime_health_before_stop")
                    for item in final.result.sensor_summary
                    if hasattr(item, "get")
                },
            )
            self._persist_runtime_state(record)
        except Exception as error:
            self._fail_record(record, error)
        finally:
            launcher = record.runtime.get("launcher")
            if launcher is not None:
                try:
                    launcher.stop_hook_broker()
                except Exception:
                    pass
            for handle in codex_output_handles:
                try:
                    handle.close()
                except Exception:
                    pass
            if not finalization_done:
                for sensor in sensors:
                    try:
                        if getattr(sensor, "status", None) and sensor.status.value != "STOPPED":
                            sensor.stop()
                    except Exception:
                        pass
                if manager is not None and lease is not None:
                    try:
                        manager.release(lease)
                    except Exception:
                        pass

    def _finalize_user_abort_before_launch(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        sensors: tuple[Any, ...],
        manager: WorkspaceLeaseManager,
        lease: Any,
    ) -> None:
        raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
        final = SessionFinalizer(
            evidence_store=raw_store,
            sensors=sensors,
            lease_manager=manager,
            workspace_lease=lease,
        ).finalize(
            session,
            end_reason=SessionEndReason.USER_ABORT,
            active_policy=preparation.active_policy,
            checkpoint=checkpoint,
            run_classification="PRODUCT_PROTECTED_RUN",
            limitations=("AGENT_NOT_LAUNCHED",),
        )
        verification = final.bundle_verification
        self.registry.update(
            record.session_id,
            status=final.result.session_status.value,
            phase=final.result.session_status.value,
            lease="RELEASED",
            result_path=final.bundle.result_directory / "result.json",
            result=final.result.to_mapping(),
            bundle_status=verification.status.value,
            protection_state="ABORTED_BEFORE_LAUNCH",
        )
        self._persist_runtime_state(record)

    def _wait_for_agent(
        self,
        record: RunRecord,
        process: Any,
        launcher: ProtectedLauncher,
    ) -> int:
        while True:
            try:
                return int(process.wait(timeout=0.5))
            except subprocess.TimeoutExpired:
                if self._is_stop_requested(record):
                    if record.runtime.get("stop_action_attempted"):
                        continue
                    record.runtime["stop_action_attempted"] = True
                    record.protection_state = "STOP_REQUESTED"
                    if not self._request_user_abort(record, launcher):
                        record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
                        record.protection_state = "DEGRADED"
                    self._persist_runtime_state(record)
                    continue
                broker = getattr(launcher, "hook_broker", None)
                broker_running = (
                    broker is not None and bool(getattr(broker, "is_running", False))
                )
                if not broker_running:
                    reason = "HOOK_BROKER_LOST"
                    if not record.runtime.get("protection_failure_termination_attempted"):
                        record.runtime["protection_failure_termination_attempted"] = True
                        record.runtime["protection_failure_reason"] = reason
                        record.protection_state = "DEGRADED"
                        try:
                            result = launcher.request_protection_failure_termination_result(
                                reason
                            )
                        except Exception as error:
                            result = {
                                "status": "FAILED",
                                "outcome": "FAILED",
                                "verified_tree_gone": False,
                                "reason": f"{type(error).__name__}",
                                "control": "PROTECTION_FAILURE",
                            }
                        if result is None:
                            result = {
                                "status": "FAILED",
                                "outcome": "FAILED",
                                "verified_tree_gone": False,
                                "reason": "PROTECTION_FAILURE_TERMINATION_UNAVAILABLE",
                                "control": "PROTECTION_FAILURE",
                            }
                        record.runtime["protection_failure_termination_result"] = result
                        self._persist_runtime_state(record)
                    continue
                continue

    @staticmethod
    def _request_user_abort(record: RunRecord, launcher: ProtectedLauncher) -> bool:
        """Request a user stop and retain its verified result separately."""

        detailed = getattr(launcher, "request_user_abort_result", None)
        try:
            if callable(detailed):
                result = detailed()
                if result is None:
                    return False
                mapping = result.to_mapping() if hasattr(result, "to_mapping") else dict(result)
                record.runtime["user_abort_termination_result"] = mapping
                if hasattr(result, "succeeded"):
                    return bool(result.succeeded)
                return bool(
                    mapping.get("status") == "SUCCEEDED"
                    and mapping.get("verified_tree_gone") is True
                )
            return bool(launcher.request_user_abort())
        except Exception as error:
            record.stop_error = f"{type(error).__name__}: {error}"
            return False

    def _is_stop_requested(self, record: RunRecord) -> bool:
        if record.stop_requested:
            return True
        try:
            requested = self._stop_request_path(record.session_id).is_file()
        except (OSError, ValueError):
            requested = False
        if requested:
            record.stop_requested = True
        return requested

    def _write_stop_request(self, session_id: str) -> Path:
        path = self._stop_request_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "requested_at": _now().isoformat(),
                    "reason": "USER_ABORT",
                },
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def _stop_request_path(self, session_id: str) -> Path:
        try:
            UUID(session_id)
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("invalid session_id") from error
        requests = (self.control_root / "stop-requests").resolve(strict=False)
        requests.mkdir(parents=True, exist_ok=True)
        candidate = (requests / f"{session_id}.json").resolve(strict=False)
        if not candidate.is_relative_to(requests):
            raise ValueError("stop request path escaped control root")
        return candidate

    def _recover_after_containment(
        self,
        record: RunRecord,
        *,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        lease: Any,
        launch_context: Any,
    ) -> Any | None:
        """Run Recovery only after a post-action termination attempt.

        A pre-tool deny does not mutate the Workspace and therefore does not
        trigger Recovery.  Recovery is eligible only for the derived
        POST_ACTION gate that authorized process termination.  The coordinator
        independently verifies the termination result, session, lease, and
        checkpoint before it mutates anything.
        """

        termination_result = record.runtime.get("process_termination_result")
        gate_results = tuple(record.runtime.get("post_action_gate_results", ()))
        if termination_result is None or not gate_results:
            return None
        gate_result = next(
            (
                item
                for item in reversed(gate_results)
                if getattr(getattr(item, "route", None), "value", None)
                == "PROCESS_TERMINATION"
            ),
            None,
        )
        if gate_result is None:
            return None
        launch_id = getattr(launch_context, "launch_id", None)
        verification = RecoveryCoordinator(
            record.runtime["lease_manager"]
        ).recover(
            gate_result,
            termination_result,
            session=session,
            checkpoint=checkpoint,
            workspace_lease=lease,
            launch_context=launch_context,
            expected_launch_id=launch_id,
            workspace=session.workspace,
        )
        record.runtime["recovery_verification"] = verification
        self._persist_runtime_state(record)
        return verification

    def _process_evidence(self, record: RunRecord) -> None:
        session: ProtectedRunSession = record.runtime["session"]
        preparation = record.runtime["preparation"]
        launcher = record.runtime["launcher"]
        raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
        records = raw_store.records()
        normalized = Normalizer(session.session_id, session.workspace).normalize(records)
        evaluator = RuntimePolicyEvaluator(preparation.active_policy)
        launch_context = record.runtime["launch"].context
        attribution_engine = AttributionEngine(session.session_id, records, launch_context=launch_context)
        gate = EnforcementGate(lease_manager=record.runtime["lease_manager"])
        policy_results = []
        attribution_results = []
        gate_results = []
        action_views = []
        codex_controller = record.runtime.get("codex_controller")
        codex_events = tuple(codex_controller.events) if codex_controller is not None else ()

        def matching_codex_event(action: Any) -> Any | None:
            action_evidence_ids = set(action.evidence_ids)
            for event in codex_events:
                if action_evidence_ids == set(event.action.evidence_ids):
                    return event
            return None

        def append_action_view(
            action: Any,
            policy_result: Any,
            attribution_result: Any,
            gate_result: Any,
        ) -> None:
            action_views.append(
                _runtime_action_view(
                    action,
                    policy_result,
                    attribution_result,
                    gate_result,
                )
            )

        for action in normalized.actions:
            policy_result = evaluator.evaluate(action)
            attribution_result = attribution_engine.attribute(action)
            sensors = record.runtime.get("sensors", ())
            sensor_health = tuple(sensor.health for sensor in sensors if sensor is not None)
            codex_event = matching_codex_event(action)
            if codex_event is not None:
                policy_result = codex_event.policy_evaluation
                attribution_result = codex_event.attribution
                gate_result = codex_event.gate_result
            else:
                gate_result = gate.evaluate(
                    EnforcementGateInput(
                        action=action,
                        policy_evaluation=policy_result,
                        attribution=attribution_result,
                        session=session,
                        active_policy=preparation.active_policy,
                        launch_context=launch_context,
                        workspace_lease=preparation.workspace_lease,
                        sensor_health=sensor_health,
                        hook_trust_status=HookTrustStatus.UNVERIFIED,
                        checked_at=_now(),
                    )
                )
            policy_results.append(policy_result)
            attribution_results.append(attribution_result)
            gate_results.append(gate_result)
            append_action_view(action, policy_result, attribution_result, gate_result)

        post_action_containments = (
            tuple(codex_controller.post_action_containments)
            if codex_controller is not None
            else ()
        )
        for containment in post_action_containments:
            policy_results.append(containment.policy_evaluation)
            attribution_results.append(containment.attribution)
            gate_results.append(containment.gate_result)
            append_action_view(
                containment.action,
                containment.policy_evaluation,
                containment.attribution,
                containment.gate_result,
            )
            if containment.termination_error:
                record.runtime.setdefault("post_action_containment_errors", []).append(
                    containment.termination_error
                )
        all_actions = tuple(
            (*normalized.actions, *(item.action for item in post_action_containments))
        )
        record.runtime.update(
            {
                "normalized_actions": all_actions,
                "policy_evaluations": tuple(policy_results),
                "attribution_results": tuple(attribution_results),
                "gate_results": tuple(gate_results),
            }
        )
        incidents = [item for item in (incident_view(item) for item in action_views) if item]
        self.registry.update(record.session_id, actions=action_views, incidents=incidents)

    def _capture_codex_execution_observation(
        self,
        record: RunRecord,
        handles: list[Any],
    ) -> None:
        """Classify bounded Codex output without persisting the raw stream."""

        if len(handles) != 2:
            return
        streams: list[bytes] = []
        for handle in handles:
            try:
                handle.flush()
                handle.seek(0)
                streams.append(handle.read(8 * 1024 * 1024))
            except (OSError, ValueError):
                streams.append(b"")
        raw_store = RawEvidenceStore.for_session(
            self.control_root,
            record.session_id,
        )
        posttool_observed = any(
            item.record_type.value == "POSTTOOL_OBSERVED"
            for item in raw_store.records()
        )
        observation = CodexAdapter.classify_execution_output(
            streams[0],
            streams[1],
            posttool_observed=posttool_observed,
        )
        record.runtime["codex_output_observation"] = observation
        if (
            observation.effective_sandbox is not None
            and observation.effective_sandbox.casefold().startswith("read-only")
        ):
            record.runtime["codex_sandbox_downgraded"] = True
        if (
            observation.effective_approval_policy is not None
            and observation.effective_approval_policy.casefold() != "on-request"
        ):
            record.runtime["codex_approval_policy_downgraded"] = True

    def _confirm_codex_blocks(self, record: RunRecord) -> None:
        """Attach a BLOCKED result only to a native, unambiguous Codex block."""

        observation = record.runtime.get("codex_output_observation")
        if observation is None or not observation.block_confirmation_available:
            return
        if record.runtime.get("exit_code") != 0:
            return
        controller = record.runtime.get("codex_controller")
        if controller is None:
            return
        raw_store = RawEvidenceStore.for_session(
            self.control_root,
            record.session_id,
        )
        posttool_ids = {
            item.payload.get("tool_use_id")
            for item in raw_store.records()
            if item.record_type.value == "POSTTOOL_OBSERVED"
            and isinstance(item.payload.get("tool_use_id"), str)
        }
        candidates = [
            event
            for event in controller.events
            if event.confirmed_block is None
            and event.tool_use_id not in posttool_ids
            and event.gate_result.decision.value == "CONTAIN"
            and event.gate_result.route.value == "PRETOOL_BLOCK"
        ]
        if not candidates or observation.block_message_count < len(candidates):
            return
        for event in candidates:
            controller.confirm_block(event.tool_use_id, True)

    def _refresh_protection_state(self, record: RunRecord) -> None:
        if record.status in {"COMPLETED", "FAILED", "ABORTED"}:
            return
        controller = record.runtime.get("codex_controller")
        if controller is None:
            return
        events = tuple(controller.events)
        action_views = [
            _runtime_action_view(
                event.action,
                event.policy_evaluation,
                event.attribution,
                event.gate_result,
            )
            for event in events
        ]
        for containment in getattr(controller, "post_action_containments", ()):
            action_views.append(
                _runtime_action_view(
                    containment.action,
                    containment.policy_evaluation,
                    containment.attribution,
                    containment.gate_result,
                )
            )
        record.actions = action_views
        record.incidents = [
            item
            for item in (incident_view(action) for action in action_views)
            if item
        ]
        record.hook_event_count = len(events)
        sensors_healthy = _sensors_runtime_healthy(record.runtime.get("sensors", ()))
        hook_broker_healthy = _hook_broker_runtime_healthy(record)
        if controller.errors or hook_broker_healthy is False:
            record.protection_state = "DEGRADED"
        elif events and sensors_healthy and hook_broker_healthy is not False:
            record.protection_state = "ACTIVE_VERIFIED"
        elif events:
            record.protection_state = "ACTIVE_DEGRADED"
        self._persist_runtime_state(record)

    def _phase(self, record: RunRecord, phase: str, status: SessionStatus) -> None:
        record.phase = phase
        record.status = status.value
        self._persist_runtime_state(record)

    def _record_launch_context(
        self,
        record: RunRecord,
        launch_holder: dict[str, Any],
        context: Any,
    ) -> None:
        """Persist the verified Agent root before releasing the task prompt."""

        launch_holder["context"] = context
        record.runtime["launch_context"] = context
        self._persist_runtime_state(record)

    def _refresh_sensors(self, record: RunRecord, sensors: tuple[Any, ...]) -> None:
        record.sensor_health = {
            sensor.health.sensor.value: sensor.health.status.value
            for sensor in sensors
            if sensor is not None
        }
        self._persist_runtime_state(record)

    def _fail_record(self, record: RunRecord, error: Exception) -> None:
        record.status = "FAILED"
        record.phase = "FAILED"
        record.protection_state = "FAILED"
        record.error = f"{type(error).__name__}: {error}"
        record.lease = "FAILED" if record.lease == "ACTIVE" else record.lease
        self._persist_runtime_state(record)

    def _runtime_state_path(self, session_id: str) -> Path:
        if (
            not isinstance(session_id, str)
            or not session_id
            or any(not (character.isalnum() or character == "-") for character in session_id)
        ):
            raise ValueError("invalid session_id")
        root = (self.control_root / "run-status").resolve(strict=False)
        candidate = (root / f"{session_id}.json").resolve(strict=False)
        if not candidate.is_relative_to(root):
            raise ValueError("runtime state path escaped control root")
        return candidate

    @staticmethod
    def _runtime_state_mapping(record: RunRecord) -> dict[str, Any]:
        launch_context = record.runtime.get("launch_context")
        managed_process = None
        coordinator = None
        if (
            isinstance(record.coordinator_pid, int)
            and not isinstance(record.coordinator_pid, bool)
            and record.coordinator_pid > 0
            and isinstance(record.coordinator_process_create_time, (int, float))
            and not isinstance(record.coordinator_process_create_time, bool)
        ):
            coordinator = {
                "pid": record.coordinator_pid,
                "create_time": record.coordinator_process_create_time,
            }
        if launch_context is not None:
            root_identity = getattr(launch_context, "root_process_identity", None)
            launch_id = getattr(launch_context, "launch_id", None)
            if (
                isinstance(root_identity, ProcessIdentity)
                and isinstance(launch_id, str)
                and launch_id
            ):
                managed_process = {
                    "launch_id": launch_id,
                    "launch_provenance": getattr(
                        launch_context,
                        "launch_provenance",
                        None,
                    ),
                    "root_process_identity": {
                        "pid": root_identity.pid,
                        "create_time": root_identity.create_time,
                    },
                }
        return {
            "schema_version": 1,
            "session_id": record.session_id,
            "updated_at": _now().isoformat(),
            "coordinator": coordinator,
            "managed_process": managed_process,
            "session": {
                "agent": record.agent,
                "created_at": record.created_at.isoformat(),
                "model": record.model,
                "session_id": record.session_id,
                "status": record.status,
                "workspace": str(record.workspace),
            },
            "phase": record.phase,
            "protection": {
                "state": record.protection_state,
                "hook_events": record.hook_event_count,
            },
            "checkpoint": record.checkpoint,
            "lease": record.lease,
            "mode": record.mode,
            "policy": {
                "id": record.policy_id,
                "profile": record.policy_profile,
                "version": record.policy_version,
            },
            "incident_count": len(record.incidents),
            "latest_actions": record.actions[-20:],
            "sensor_health": dict(record.sensor_health),
            "stop": {
                "requested": record.stop_requested,
                "error": record.stop_error,
            },
            "error": record.error,
            "result_path": str(record.result_path) if record.result_path is not None else None,
            "result_available": record.result_path is not None,
        }

    def _persist_runtime_state(self, record: RunRecord, *, strict: bool = False) -> None:
        try:
            self._write_runtime_state_payload(
                record.session_id,
                self._runtime_state_mapping(record),
            )
        except (OSError, ValueError):
            if strict:
                raise
            record.protection_state = "DEGRADED"
            record.error = record.error or "RUNTIME_STATE_PERSIST_FAILED"

    def _write_runtime_state_payload(
        self,
        session_id: str,
        payload: Mapping[str, Any],
    ) -> Path:
        path = self._runtime_state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def _read_runtime_state(self, session_id: str) -> dict[str, Any] | None:
        try:
            path = self._runtime_state_path(session_id)
            if not path.is_file():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("session_id") != session_id:
            return None
        return payload

    def _list_runtime_states(self) -> list[dict[str, Any]]:
        root = (self.control_root / "run-status").resolve(strict=False)
        if not root.is_dir():
            return []
        states: list[dict[str, Any]] = []
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            session_id = payload.get("session_id")
            if not isinstance(session_id, str):
                continue
            try:
                if self._runtime_state_path(session_id) != path.resolve(strict=False):
                    continue
            except ValueError:
                continue
            states.append(payload)
        return states

    def _runtime_state_for_display(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Add crash reconciliation metadata to a persisted runtime view."""

        displayed = dict(state)
        reconciliation = _runtime_coordinator_reconciliation(state)
        displayed["runtime_reconciliation"] = reconciliation
        protection = state.get("protection")
        if isinstance(protection, Mapping):
            protection_view = dict(protection)
            if reconciliation.get("orphaned"):
                protection_view["state"] = "ORPHANED_DEGRADED"
            displayed["protection"] = protection_view
        return displayed

    def _status_from_runtime_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state = self._runtime_state_for_display(state)
        session = state.get("session") if isinstance(state.get("session"), dict) else {}
        protection = state.get("protection") if isinstance(state.get("protection"), dict) else {}
        policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
        stop = state.get("stop") if isinstance(state.get("stop"), dict) else {}
        return {
            "checkpoint": state.get("checkpoint", "UNKNOWN"),
            "error": state.get("error"),
            "incident_count": state.get("incident_count", 0),
            "latest_actions": state.get("latest_actions", []),
            "lease": state.get("lease", "UNKNOWN"),
            "mode": state.get("mode"),
            "phase": state.get("phase", session.get("status", "UNKNOWN")),
            "result_path": state.get("result_path"),
            "protection": protection,
            "stop": stop,
            "policy": policy,
            "result_available": bool(state.get("result_available")),
            "sensor_health": state.get("sensor_health", {}),
            "runtime_reconciliation": state.get("runtime_reconciliation"),
            "session": session,
        }

    def _status_from_completed_bundle(self, session_id: str) -> dict[str, Any]:
        result = self.reader.read_result(session_id)
        view = result_view(result, self.reader.verification(session_id).status.value)
        hook_events = self.reader.hook_event_count(session_id)
        sensor_failed = any(
            item.get("runtime_health_before_stop") == "FAILED"
            for item in result.get("sensor_summary", [])
            if isinstance(item, Mapping)
        )
        sensor_verified = _sensor_summary_is_verified(result.get("sensor_summary", []))
        protection_downgraded = any(
            item in {
                "CODEX_SANDBOX_DOWNGRADED",
                "CODEX_APPROVAL_POLICY_DOWNGRADED",
                "HOOK_BROKER_RUNTIME_NOT_VERIFIED",
                "PROTECTION_BOUNDARY_LOST",
            }
            for item in result.get("limitations", [])
        )
        aborted = (
            result.get("session_status") == "ABORTED"
            and result.get("session_end_reason") == "USER_ABORT"
        )
        if result.get("session_status") == "FAILED" or result.get("session_end_reason") == "PROTECTION_FAILURE":
            protection_state = "FAILED_DEGRADED"
        elif aborted:
            protection_state = (
                "ABORTED_VERIFIED"
                if hook_events and sensor_verified and not sensor_failed and not protection_downgraded
                else "ABORTED_DEGRADED"
            )
        else:
            protection_state = (
                "COMPLETED_VERIFIED"
                if hook_events and sensor_verified and not sensor_failed and not protection_downgraded
                else "COMPLETED_DEGRADED"
            )
        return {
            "checkpoint": "UNKNOWN",
            "error": None,
            "incident_count": len(view["incidents"]),
            "latest_actions": view["actions"][-20:],
            "lease": "RELEASED",
            "mode": view["mode"],
            "phase": view["session_status"],
            "result_path": str(self.result_directory_for(session_id)),
            "protection": {
                "state": protection_state,
                "hook_events": hook_events,
            },
            "stop": {"requested": aborted, "error": None},
            "policy": view["policy"],
            "result_available": True,
            "sensor_health": {
                item.get("sensor"): item.get("runtime_health_before_stop")
                for item in result.get("sensor_summary", [])
            },
            "session": {
                "agent": result.get("agent"),
                "created_at": result.get("created_at"),
                "model": None,
                "session_id": session_id,
                "status": result.get("session_status"),
                "workspace": result.get("workspace"),
            },
        }

    def result_directory_for(self, session_id: str) -> Path:
        return self.reader.result_directory(session_id) / "result.json"
