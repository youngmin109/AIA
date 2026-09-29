"""Application orchestration for the optional Local Security Console."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import os
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import RLock, Thread
from typing import Any
from uuid import UUID, uuid4

from aia import (
    CodexAdapter,
    CodexExecutionObservation,
    CodexHookBroker,
    CodexHookInstaller,
    CodexPreToolController,
    FilesystemSensor,
    HookSensor,
    HookEnforcementBridge,
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
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    load_policy_document,
    prepare_protection,
    process_create_time,
    resolve_profile,
    verify_process_identity,
    __version__,
)
from aia.codex_runtime import UnsupportedToolReview
from aia.session import SessionEndReason, WorkspaceValidationError
from aia.readiness import ProtectionReadinessBarrier
from aia.hook_verification import HookVerificationStore
from aia.codex_hook_trust import inspect_codex_hook_trust

from .dto import CreateRunRequest, DTOValidationError, PolicyPreviewRequest
from .presenters import (
    action_view,
    evidence_chain_views,
    evidence_summary,
    evidence_timeline_views,
    incident_view,
    incident_views_for_result,
    result_action_chain_views,
    result_view,
    safe_event_views,
    safe_tool_name,
)
from .readers import ResultBundleReader
from .registry import RunRecord, RunRegistry
from .codex_app_server import CodexAppServerError, CodexAppServerSession
from .codex_workbench import CodexWorkbench, _END_SESSION_REQUEST
from .run_history import (
    RunHistoryMixin,
    _runtime_coordinator_reconciliation,
    _workspace_key,
    _PRODUCT_SENSOR_NAMES,
    _annotate_execution_observations,
    _execution_observation_metadata,
    _hook_broker_runtime_healthy,
    _sensor_summary_is_verified,
)
from .preflight import PreflightMixin, _aia_cli_prefix
from .protected_run import (
    ApplicationValidationError,
    ProtectedRunMixin,
    _event_tool_name,
    _now,
    _posttool_use_ids,
    _popen_kwargs_for_launch_mode,
    _runtime_action_view,
    _sensor_status,
    _sensors_runtime_healthy,
)


# The dashboard refreshes active runs every five seconds. Keep the verified
# history snapshot through one refresh interval so repeated UI requests do
# not re-hash every completed bundle while a live terminal is active.
_COMPLETED_RUNS_CACHE_TTL_SECONDS = 6.0
_RUNTIME_STATES_CACHE_LIMIT = 2_048


# Human-in-the-loop review stays inside Codex's 30 s Hook timeout.
_UNSUPPORTED_TOOL_REVIEW_SECONDS = 25.0


# app-server reports sandbox modes in camelCase; the Result Bundle and the
# requested-policy comparison use the CLI spelling.
_APP_SERVER_SANDBOX_NAMES = {
    "readOnly": "read-only",
    "workspaceWrite": "workspace-write",
    "dangerFullAccess": "danger-full-access",
}


def _product_sensor_set_present(sensors: Any) -> bool:
    names: set[str] = set()
    for sensor in tuple(item for item in (sensors or ()) if item is not None):
        health = getattr(sensor, "health", None)
        if callable(health):
            health = health()
        source = getattr(health, "sensor", None)
        name = getattr(source, "value", source)
        if isinstance(name, str):
            names.add(name)
    return _PRODUCT_SENSOR_NAMES.issubset(names)


class RunApplicationService(ProtectedRunMixin, RunHistoryMixin, PreflightMixin):
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
        self._runtime_state_lock = RLock()
        self._runtime_states_cache_lock = RLock()
        self._runtime_states_cache: dict[
            Path,
            tuple[int, int, int, int, dict[str, Any]],
        ] = {}
        self._completed_runs_cache_lock = RLock()
        self._tool_review_lock = RLock()
        self._codex_workbench = CodexWorkbench(self, _runtime_coordinator_reconciliation)
        self._completed_runs_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="aia-console-run",
        )

    def _list_completed_runs(self) -> list[dict[str, Any]]:
        """Read verified history once per short UI polling window.

        History is display data.  Re-verifying every completed Result Bundle
        on every dashboard poll can contend with the live Workbench terminal,
        especially when several console views refresh at the same time.  The
        cache does not participate in policy, enforcement, recovery, or
        integrity decisions; those paths continue to read and verify their
        artifacts directly.  A six-second window is short enough for the
        history UI while preventing duplicate scans in one refresh burst.
        """

        now = time.monotonic()
        with self._completed_runs_cache_lock:
            cached = self._completed_runs_cache
            if cached is not None and now - cached[0] < _COMPLETED_RUNS_CACHE_TTL_SECONDS:
                return deepcopy(cached[1])

            completed = self.reader.list_completed()
            self._completed_runs_cache = (time.monotonic(), completed)
            return deepcopy(completed)

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

    @staticmethod
    def validate_policy_document(document: Mapping[str, Any]) -> dict[str, Any]:
        """Strictly validate a console-authored policy without saving it."""

        if not isinstance(document, Mapping):
            raise ApplicationValidationError("policy document must be a JSON object")
        try:
            policy = load_policy_document(document, source="<console-editor>")
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error
        return {
            "valid": True,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "rule_count": len(policy.rules),
            "default_effect": policy.default_effect.value,
        }

    @staticmethod
    def save_policy_document(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate then save one user policy JSON for later CUSTOM runs."""

        if not isinstance(payload, Mapping):
            raise ApplicationValidationError("policy save request must be a JSON object")
        document = payload.get("document")
        if not isinstance(document, Mapping):
            raise ApplicationValidationError("document must be a JSON object")
        RunApplicationService.validate_policy_document(document)
        requested_path = payload.get("path")
        if requested_path is None or not str(requested_path).strip():
            policy_id = str(document.get("정책ID") or document.get("policy_id") or "custom-policy")
            safe_name = "".join(
                character if character.isalnum() or character in {"-", "_"} else "-"
                for character in policy_id
            ).strip("-") or "custom-policy"
            path = Path.home() / ".aia" / "policies" / f"{safe_name}.json"
        else:
            if not isinstance(requested_path, str):
                raise ApplicationValidationError("path must be a string")
            path = Path(requested_path).expanduser()
            if path.suffix.casefold() != ".json":
                raise ApplicationValidationError("policy path must end with .json")
        path = path.resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(document), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        summary = RunApplicationService.validate_policy_document(document)
        return {**summary, "path": str(path)}

    @staticmethod
    def _workspace_policy_path(
        workspace: Path,
        profile_name: str,
        protected_paths: tuple[str, ...],
        policy_source: str | Path | Mapping[str, Any] | None = None,
    ) -> Path | None:
        """Create a validated custom policy for paths selected in the UI."""

        if not protected_paths:
            return None
        try:
            resolved = resolve_profile(profile_name, policy_source=policy_source)
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error

        normalized: list[tuple[str, bool]] = []
        for raw_path in protected_paths:
            candidate = Path(raw_path).expanduser().resolve(strict=False)
            try:
                relative = candidate.relative_to(workspace).as_posix()
            except ValueError as error:
                raise ApplicationValidationError(
                    "보호할 파일·폴더는 선택한 Workspace 안에 있어야 합니다."
                ) from error
            if not relative or relative == ".":
                raise ApplicationValidationError("Workspace 자체는 보호 목록에 추가할 수 없습니다.")
            normalized.append((relative, candidate.is_dir()))

        rules: list[dict[str, Any]] = []
        for rule in resolved.policy.rules:
            rule_mapping: dict[str, Any] = {
                "rule_id": rule.rule_id,
                "priority": rule.priority,
                "asset_type": rule.asset_type.value,
                "operation_effects": {
                    operation.value: effect.value
                    for operation, effect in rule.operation_effects.items()
                },
            }
            if rule.path_patterns:
                rule_mapping["path_patterns"] = list(rule.path_patterns)
            else:
                rule_mapping["command_patterns"] = list(rule.command_patterns)
            rules.append(rule_mapping)

        for index, (relative, is_directory) in enumerate(normalized, start=1):
            patterns = [relative]
            if is_directory:
                patterns.append(f"{relative}/**")
            rules.append(
                {
                    "rule_id": f"aia-user-protected-path-{index}",
                    "priority": 2000 + index,
                    "asset_type": "WORKSPACE",
                    "path_patterns": patterns,
                    "operation_effects": {
                        "CREATE": "DENY",
                        "MODIFY": "DENY",
                        "DELETE": "DENY",
                        "MOVE": "DENY",
                        "RENAME": "DENY",
                    },
                }
            )

        policy_document = {
            "profile": PolicyProfile.CUSTOM.value,
            "policy_name": "AIA Workspace Protected Paths",
            "policy_id": "aia-workspace-protected",
            "policy_version": "1.0",
            "schema_version": "1",
            "default_effect": resolved.policy.default_effect.value,
            "rules": rules,
        }
        digest = hashlib.sha256(
            json.dumps(
                {"workspace": str(workspace), "paths": normalized},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        path = Path.home() / ".aia" / "policies" / f"workspace-{digest}.json"
        RunApplicationService.save_policy_document(
            {"document": policy_document, "path": str(path)}
        )
        return path

    def create_protected_run(self, request: CreateRunRequest | dict[str, Any]) -> dict[str, Any]:
        if isinstance(request, dict):
            try:
                request = CreateRunRequest.from_mapping(request)
            except DTOValidationError as error:
                raise ApplicationValidationError(str(error)) from error
        if not isinstance(request, CreateRunRequest):
            raise ApplicationValidationError("request is invalid")
        installer = CodexHookInstaller()
        cli_prefix = _aia_cli_prefix(installer)
        if self.require_hook_verification:
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
                    f"실제 Codex Hook 검증이 없습니다. 먼저 '{cli_prefix} hook verify'를 실행하세요."
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
                f"확인한 뒤 '{cli_prefix} reconcile {session_id}'를 실행하세요."
            )
        if not request.interactive and not request.task.strip():
            raise ApplicationValidationError(
                "task is required for a non-interactive protected run"
            )
        if request.agent.lower() != "codex":
            raise ApplicationValidationError("only Codex is supported in this console")
        if request.launch_mode == "new_terminal" and os.name != "nt":
            raise ApplicationValidationError(
                f"{request.launch_mode} launch mode requires Windows 11"
            )
        try:
            mode = SessionMode(request.mode.upper())
        except ValueError as error:
            raise ApplicationValidationError("mode must be ENFORCE or AUDIT") from error
        workspace_policy_path = self._workspace_policy_path(
            workspace,
            request.policy_profile,
            request.protected_paths,
            Path(request.custom_policy_path)
            if request.custom_policy_path is not None
            else None,
        )
        selected_policy_profile = (
            PolicyProfile.CUSTOM
            if workspace_policy_path is not None
            else PolicyProfile.from_value(request.policy_profile)
        )
        selected_policy_source = (
            workspace_policy_path
            if workspace_policy_path is not None
            else (
                Path(request.custom_policy_path)
                if request.custom_policy_path is not None
                else None
            )
        )
        try:
            resolved = resolve_profile(
                selected_policy_profile,
                policy_source=selected_policy_source,
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
            policy_profile=selected_policy_profile.value,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            mode=mode.value,
            task=request.task,
            interactive=request.interactive,
            launch_mode=request.launch_mode,
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
            "redirect_url": (
                f"/runs/{session.session_id}/workbench"
                if request.launch_mode == "codex_app_server"
                else f"/runs/{session.session_id}"
            ),
            "session_id": session.session_id,
            "status": session.status.value,
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
            "NOT_STARTED",
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
            "reason": (
                "AGENT_ROOT_NOT_STARTED"
                if reconciliation.get("agent_process_status") == "NOT_STARTED"
                else "RECORDED_AGENT_ROOT_NOT_LIVE"
            ),
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

    def _codex_session(self, session_id: str) -> CodexAppServerSession:
        return self._codex_workbench._codex_session(session_id)

    def get_codex_status(self, session_id: str) -> dict[str, Any]:
        return self._codex_workbench.get_codex_status(session_id)

    def read_codex_events(self, session_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self._codex_workbench.read_codex_events(session_id, after_sequence=after_sequence)

    def wait_codex_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        return self._codex_workbench.wait_codex_events(
            session_id,
            after_sequence=after_sequence,
            timeout=timeout,
        )

    def send_codex_message(self, session_id: str, text: str) -> dict[str, Any]:
        return self._codex_workbench.send_codex_message(session_id, text)

    def interrupt_codex_turn(self, session_id: str) -> dict[str, Any]:
        return self._codex_workbench.interrupt_codex_turn(session_id)

    def respond_codex_approval(self, session_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        return self._codex_workbench.respond_codex_approval(session_id, approval_id, decision)

    def _resolve_unsupported_tool_review(self, session_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        return self._codex_workbench._resolve_unsupported_tool_review(session_id, approval_id, decision)

    def _review_unsupported_tool(self, record: RunRecord, review: UnsupportedToolReview) -> bool:
        return self._codex_workbench.review_unsupported_tool(
            record,
            review,
            timeout_seconds=_UNSUPPORTED_TOOL_REVIEW_SECONDS,
        )

    def end_codex_session(self, session_id: str) -> dict[str, Any]:
        return self._codex_workbench.end_codex_session(session_id)

    def _externally_coordinated_run(self, session_id: str) -> dict[str, Any] | None:
        return self._codex_workbench._externally_coordinated_run(session_id)

    def _open_codex_conversation(self, record: RunRecord) -> None:
        """Start the Workbench thread once Codex is registered and protected.

        Opening waits until the launcher has registered the app-server root and
        started the Process Sensor, because starting a thread can launch
        configured MCP servers as Codex children.  The applied sandbox and
        approval policy come from Codex's own response instead of being
        inferred from output.
        """

        codex_session = record.runtime.get("codex_session")
        if codex_session is None:
            return
        try:
            effective = codex_session.open(
                sandbox="workspace-write",
                approval_policy="on-request",
                model=record.model,
            )
        except CodexAppServerError as error:
            record.runtime["codex_app_server_error"] = f"CODEX_APP_SERVER_OPEN_FAILED: {error}"
            codex_session.close(force=True)
            return
        record.runtime["codex_effective_settings"] = effective
        sandbox = str(effective.get("sandbox") or "")
        approval_policy = str(effective.get("approval_policy") or "")
        # Codex reports the applied settings itself in the thread/start
        # response.  Record them as the run's execution observation so the
        # Result Bundle states what was applied instead of NOT_OBSERVED.  No
        # output stream is retained, so text-based block confirmation stays
        # unavailable and blocks are confirmed through Hook evidence only.
        record.runtime["codex_output_observation"] = CodexExecutionObservation(
            output_sha256=hashlib.sha256(b"").hexdigest(),
            output_bytes=0,
            block_message_count=0,
            no_run_message_count=0,
            block_confirmation_available=False,
            reason="APP_SERVER_THREAD_SETTINGS",
            effective_approval_policy=approval_policy or None,
            effective_sandbox=_APP_SERVER_SANDBOX_NAMES.get(sandbox, sandbox) or None,
        )
        if sandbox == "dangerFullAccess" or approval_policy == "never":
            # Codex applied a less protected mode than AIA requested (for
            # example from a managed config).  No task has been sent yet; end
            # the run through the same verified termination as a lost Hook
            # broker instead of trusting a plain process close.
            reason = "CODEX_UNPROTECTED_SETTINGS_APPLIED"
            record.runtime["codex_app_server_error"] = reason
            record.runtime["protection_failure_termination_attempted"] = True
            record.runtime["protection_failure_reason"] = reason
            record.protection_state = "DEGRADED"
            launcher = record.runtime.get("launcher")
            result: dict[str, Any] | None = None
            try:
                if launcher is not None:
                    result = launcher.request_protection_failure_termination_result(reason)
            except Exception as error:
                result = {
                    "status": "FAILED",
                    "outcome": "FAILED",
                    "verified_tree_gone": False,
                    "reason": f"{type(error).__name__}",
                    "control": "PROTECTION_FAILURE",
                }
            record.runtime["protection_failure_termination_result"] = result or {
                "status": "FAILED",
                "outcome": "FAILED",
                "verified_tree_gone": False,
                "reason": "PROTECTION_FAILURE_TERMINATION_UNAVAILABLE",
                "control": "PROTECTION_FAILURE",
            }
            self._persist_runtime_state(record)
            return
        if sandbox == "readOnly":
            record.runtime["codex_sandbox_downgraded"] = True
        if approval_policy != "on-request":
            record.runtime["codex_approval_policy_downgraded"] = True

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

    def _apply_manual_recovery_view(
        self,
        view: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        manual = self._read_manual_recovery(session_id)
        if not manual:
            return view
        recovery = manual.get("recovery_result") or {}
        integrity = manual.get("integrity_result") or {}
        view["recovery"] = recovery
        view["integrity"] = integrity
        view["recovery_status"] = recovery.get("recovery_status", "NOT_ATTEMPTED")
        view["integrity_status"] = integrity.get("integrity_status", "NOT_CHECKED")
        view["recovery_summary"] = {
            "status": view["recovery_status"],
            "reason": recovery.get("reason"),
            "planned_operations": int(recovery.get("planned_operation_count") or 0),
            "attempted_operations": int(recovery.get("attempted_operation_count") or 0),
            "succeeded_operations": int(recovery.get("succeeded_operation_count") or 0),
            "failed_operations": int(recovery.get("failed_operation_count") or 0),
            "restored_paths": len(recovery.get("restored_paths") or []),
            "removed_paths": len(recovery.get("removed_paths") or []),
            "failed_paths": len(recovery.get("failed_paths") or []),
        }
        view["integrity_summary"] = {
            "status": view["integrity_status"],
            "reason": integrity.get("reason"),
            "expected_entries": int(integrity.get("expected_entry_count") or 0),
            "actual_entries": int(integrity.get("actual_entry_count") or 0),
            "missing_paths": len(integrity.get("missing_paths") or []),
            "unexpected_paths": len(integrity.get("unexpected_paths") or []),
            "changed_paths": len(integrity.get("changed_paths") or []),
            "verification_errors": len(integrity.get("verification_errors") or []),
        }
        return view

    def get_result(self, session_id: str) -> dict[str, Any]:
        record = self.registry.snapshot(session_id)
        if record is not None and record.result is not None and record.bundle_status is not None:
            view = result_view(record.result, record.bundle_status)
            evidence_metadata = self._evidence_metadata(
                session_id,
                require_valid=False,
            )
            _annotate_execution_observations(
                view,
                control_root=self.control_root,
                session_id=session_id,
                evidence_metadata=evidence_metadata,
            )
            view["launch_mode"] = record.launch_mode
            view["protection_state"] = record.protection_state
            view["posttool_event_count"] = sum(
                1
                for item in evidence_metadata
                if item.get("source") == "AGENT_HOOK"
                and item.get("record_type") == "POSTTOOL_OBSERVED"
            )
            view["evidence_summary"] = self._evidence_summary(
                session_id,
                metadata=evidence_metadata,
            )
            return self._apply_manual_recovery_view(view, session_id)
        result = self.reader.read_result(session_id)
        verification = self.reader.verification(session_id)
        view = result_view(result, verification.status.value if verification else "NOT_FOUND")
        evidence_metadata = self._evidence_metadata(
            session_id,
            require_valid=False,
        )
        _annotate_execution_observations(
            view,
            control_root=self.control_root,
            session_id=session_id,
            evidence_metadata=evidence_metadata,
        )
        runtime_state = self._read_runtime_state(session_id)
        if isinstance(runtime_state, Mapping):
            view["launch_mode"] = runtime_state.get("launch_mode", "inherit")
        completed_metadata = next(
            (item for item in self._list_completed_runs() if item.get("session_id") == session_id),
            None,
        )
        view["protection_state"] = (
            completed_metadata.get("protection_state")
            if completed_metadata
            else {
                "FAILED": "FAILED_DEGRADED",
                "ABORTED": "ABORTED_DEGRADED",
                "COMPLETED": "COMPLETED_DEGRADED",
            }.get(result.get("session_status"), "UNKNOWN")
        )
        view["posttool_event_count"] = sum(
            1
            for item in evidence_metadata
            if item.get("source") == "AGENT_HOOK"
            and item.get("record_type") == "POSTTOOL_OBSERVED"
        )
        view["evidence_summary"] = self._evidence_summary(
            session_id,
            metadata=evidence_metadata,
        )
        return self._apply_manual_recovery_view(view, session_id)

    def _manual_recovery_artifact_path(self, session_id: str) -> Path:
        if (
            not isinstance(session_id, str)
            or not session_id
            or any(not (character.isalnum() or character == "-") for character in session_id)
        ):
            raise ValueError("invalid session_id")
        return self.control_root / "sessions" / session_id / "manual-recovery.json"

    def _read_manual_recovery(self, session_id: str) -> dict[str, Any] | None:
        try:
            path = self._manual_recovery_artifact_path(session_id)
            if not path.is_file():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _recovery_mapping(value: Any) -> dict[str, Any]:
        return {
            "recovery_id": value.recovery_id,
            "aia_session_id": value.aia_session_id,
            "action_id": value.action_id,
            "termination_id": value.termination_id,
            "checkpoint_id": value.checkpoint_id,
            "recovery_status": value.recovery_status.value,
            "started_at": value.started_at.isoformat() if value.started_at else None,
            "ended_at": value.ended_at.isoformat(),
            "duration_ms": value.duration_ms,
            "planned_operation_count": value.planned_operation_count,
            "attempted_operation_count": value.attempted_operation_count,
            "succeeded_operation_count": value.succeeded_operation_count,
            "failed_operation_count": value.failed_operation_count,
            "restored_paths": list(value.restored_paths),
            "removed_paths": list(value.removed_paths),
            "failed_paths": list(value.failed_paths),
            "reason": value.reason,
            "limitations": list(value.limitations),
            "operation_results": [
                {
                    "operation": item.operation.value,
                    "relative_path": item.relative_path,
                    "expected_entry_type": item.expected_entry_type.value
                    if item.expected_entry_type
                    else None,
                    "attempted": item.attempted,
                    "succeeded": item.succeeded,
                    "reason": item.reason,
                    "expected_sha256": item.expected_sha256,
                    "final_sha256": item.final_sha256,
                }
                for item in value.operation_results
            ],
        }

    @staticmethod
    def _integrity_mapping(value: Any) -> dict[str, Any]:
        return {
            "aia_session_id": value.aia_session_id,
            "checkpoint_id": value.checkpoint_id,
            "integrity_status": value.integrity_status.value,
            "integrity_started_at": value.integrity_started_at.isoformat()
            if value.integrity_started_at
            else None,
            "integrity_ended_at": value.integrity_ended_at.isoformat()
            if value.integrity_ended_at
            else None,
            "integrity_duration_ms": value.integrity_duration_ms,
            "verified_at": value.verified_at.isoformat() if value.verified_at else None,
            "checkpoint_fingerprint": value.checkpoint_fingerprint,
            "expected_entry_count": value.expected_entry_count,
            "actual_entry_count": value.actual_entry_count,
            "missing_paths": list(value.missing_paths),
            "unexpected_paths": list(value.unexpected_paths),
            "type_mismatches": list(value.type_mismatches),
            "changed_paths": list(value.changed_paths),
            "verification_errors": list(value.verification_errors),
            "limitations": list(value.limitations),
            "reason": value.reason,
        }

    def _manual_recovery_context(self, session_id: str) -> dict[str, Any]:
        """Load a completed run and its immutable checkpoint without mutation."""

        record = self.registry.get(session_id)
        if record is not None and record.status not in {"COMPLETED", "ABORTED", "FAILED"}:
            return {"available": False, "reason": "RUN_IS_ACTIVE"}
        try:
            raw_result = self.reader.read_result(session_id)
        except (KeyError, OSError, ValueError) as error:
            raise KeyError(session_id) from error
        workspace = self._validate_workspace(raw_result.get("workspace"))
        checkpoints_root = self.control_root / "sessions" / session_id / "checkpoints"
        candidates = sorted(
            (path for path in checkpoints_root.iterdir() if path.is_dir())
            if checkpoints_root.is_dir()
            else (),
            key=lambda path: path.name,
        )
        import aia.checkpoint as checkpoint_module

        checkpoint = None
        for candidate in candidates:
            try:
                metadata, manifest = checkpoint_module._validate_artifact(candidate)
                checkpoint = checkpoint_module._checkpoint_from_artifact(
                    candidate,
                    metadata,
                    manifest,
                )
                break
            except Exception:
                continue
        if checkpoint is None:
            return {"available": False, "reason": "CHECKPOINT_UNAVAILABLE"}
        from aia.checkpoint import compare_workspace_to_checkpoint

        comparison = compare_workspace_to_checkpoint(checkpoint, workspace)
        return {
            "available": True,
            "reason": None,
            "workspace": workspace,
            "raw_result": raw_result,
            "checkpoint": checkpoint,
            "workspace_matches": comparison.matches,
            "checkpoint_validity": checkpoint.validity.value,
        }

    def get_recovery_status(self, session_id: str) -> dict[str, Any]:
        context = self._manual_recovery_context(session_id)
        manual = self._read_manual_recovery(session_id)
        if manual is not None:
            context = {
                **context,
                "available": False,
                "status": (manual.get("recovery_result") or {}).get("recovery_status"),
                "integrity_status": (manual.get("integrity_result") or {}).get("integrity_status"),
                "recovery_result": manual.get("recovery_result"),
                "integrity_result": manual.get("integrity_result"),
                "manual_recovery": True,
            }
        else:
            raw_result = context.get("raw_result") or {}
            recovery_result = raw_result.get("recovery_result")
            integrity_result = raw_result.get("integrity_result")
            context = {
                **context,
                "status": (
                    recovery_result.get("recovery_status") or recovery_result.get("status")
                    if isinstance(recovery_result, Mapping)
                    else None
                ) or ("NOT_REQUIRED" if context.get("workspace_matches") else "NOT_ATTEMPTED"),
                "integrity_status": (
                    integrity_result.get("integrity_status") or integrity_result.get("status")
                    if isinstance(integrity_result, Mapping)
                    else None
                ) or ("VERIFIED" if context.get("workspace_matches") else "NOT_CHECKED"),
                "recovery_result": recovery_result,
                "integrity_result": integrity_result,
                "manual_recovery": False,
            }
        return {
            key: value
            for key, value in context.items()
            if key not in {"workspace", "raw_result", "checkpoint"}
        }

    def restore_run(self, session_id: str, *, confirm: bool) -> dict[str, Any]:
        if confirm is not True:
            raise ApplicationValidationError("전체 Workspace 복구 확인이 필요합니다.")
        existing = self._read_manual_recovery(session_id)
        if existing is not None:
            return existing
        context = self._manual_recovery_context(session_id)
        if not context.get("available"):
            raise ApplicationValidationError(str(context.get("reason") or "RECOVERY_UNAVAILABLE"))
        workspace: Path = context["workspace"]
        raw_result = context["raw_result"]
        checkpoint = context["checkpoint"]
        policy = raw_result.get("policy") if isinstance(raw_result.get("policy"), Mapping) else {}
        session = ProtectedRunSession(
            workspace=workspace,
            agent=str(raw_result.get("agent") or "codex"),
            mode=str(raw_result.get("mode") or "ENFORCE"),
            policy_id=str(policy.get("policy_id") or "manual-recovery"),
            policy_version=str(policy.get("policy_version") or "1"),
            created_at=datetime.fromisoformat(raw_result["created_at"]),
        )
        session.session_id = session_id
        manager = WorkspaceLeaseManager(
            self.control_root,
            process_identity_provider=process_create_time,
        )
        lease = manager.acquire(
            workspace,
            session_id,
            owner_pid=os.getpid(),
            owner_process_create_time=process_create_time(os.getpid()),
        )
        try:
            verification = RecoveryCoordinator(manager).restore_manual(
                session=session,
                checkpoint=checkpoint,
                workspace_lease=lease,
                workspace=workspace,
            )
        finally:
            try:
                manager.release(lease)
            except Exception:
                pass
        payload = {
            "schema_version": "aia-manual-recovery-1",
            "session_id": session_id,
            "workspace": str(workspace),
            "recovery_result": self._recovery_mapping(verification.recovery),
            "integrity_result": self._integrity_mapping(verification.integrity),
            "saved_at": _now().isoformat(),
        }
        path = self._manual_recovery_artifact_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return payload

    def _evidence_summary(
        self,
        session_id: str,
        *,
        require_valid: bool = True,
        metadata: list[dict[str, Any]] | None = None,
    ) -> dict[str, int | bool]:
        """Return safe counts from the Evidence metadata index.

        Completed result views require a valid bundle.  Live status may count
        the append-only metadata file before finalization so the console can
        show observation progress without exposing raw payload values.
        """

        return evidence_summary(
            metadata
            if metadata is not None
            else self._evidence_metadata(session_id, require_valid=require_valid)
        )

    def _evidence_metadata(
        self,
        session_id: str,
        *,
        require_valid: bool = True,
    ) -> list[dict[str, Any]]:
        """Return metadata-only evidence for display joins.

        A transient or older run may not have an evidence file yet.  The UI
        should show an unlinked/unknown chain in that case, rather than turn a
        status refresh into an application error.
        """

        try:
            return self.reader.read_evidence_metadata(
                session_id,
                require_valid=require_valid,
            )
        except (OSError, ValueError, KeyError):
            return []

    def get_report(self, session_id: str) -> str:
        return self.reader.read_report(session_id)

    def get_result_json(self, session_id: str) -> bytes:
        return self.reader.read_result_json(session_id)

    def get_raw_evidence(self, session_id: str) -> list[dict[str, Any]]:
        return self.reader.read_evidence_metadata(session_id)

    def validate_workspace(self, value: str) -> dict[str, Any]:
        workspace = self._validate_workspace(value)
        orphan = self._unresolved_orphan_for_workspace(workspace)
        recovery = None
        if orphan is not None:
            reconciliation = orphan.get("runtime_reconciliation") or {}
            recovery = {
                "required": True,
                "session_id": orphan.get("session_id"),
                "status": reconciliation.get("status", "UNKNOWN"),
                "action": reconciliation.get("action"),
                "agent_process_status": reconciliation.get("agent_process_status"),
            }
        return {
            "valid": True,
            "exists": workspace.exists(),
            "is_directory": workspace.is_dir(),
            "canonical_path": str(workspace),
            "recovery": recovery,
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
        """Coordinate the protected run and its resource cleanup."""

        self._run_protected_lifecycle(record)

    def _run_protected_lifecycle(self, record: RunRecord) -> None:
        """Execute preparation, launch, observation, and finalization in order."""

        session: ProtectedRunSession = record.runtime["session"]
        resolved = record.runtime["resolved_policy"]
        manager: WorkspaceLeaseManager | None = None
        lease = None
        sensors: tuple[Any, ...] = ()
        finalization_done = False
        codex_output_handles: list[Any] = []
        resources: dict[str, Any] = {}
        try:
            self._phase(record, "PREPARING", SessionStatus.PREPARING)
            record.protection_state = "PREPARING"
            session.transition(SessionStatus.PREPARING, at=_now())
            (
                manager,
                lease,
                sensors,
                preparation,
                checkpoint,
                readiness,
                continue_run,
            ) = self._prepare_protected_run(record, session, resolved, resources)
            if not continue_run:
                finalization_done = True
                return
            filesystem, hook = sensors

            (
                launcher,
                controller,
                adapter_options,
            ) = self._create_protected_launcher(
                record,
                session,
                preparation,
                checkpoint,
                filesystem,
                hook,
                manager,
                readiness,
                codex_output_handles,
            )
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
            observation = self._observe_protected_run(
                record,
                session,
                preparation,
                checkpoint,
                filesystem,
                hook,
                manager,
                lease,
                sensors,
                launcher,
                adapter_options,
                codex_output_handles,
            )
            if observation is None:
                finalization_done = True
                return
            (
                launch,
                sensors,
                exit_code,
                hook_broker_healthy_before_stop,
                recovery_verification,
            ) = observation
            finalization_done = self._finalize_completed_protected_run(
                record,
                session,
                preparation,
                checkpoint,
                sensors,
                manager,
                lease,
                launch,
                exit_code,
                controller,
                hook_broker_healthy_before_stop,
                recovery_verification,
            )
        except Exception as error:
            self._fail_record(record, error)
        finally:
            self._cleanup_run_lifecycle(
                record,
                codex_output_handles,
                sensors or resources.get("sensors", ()),
                manager or resources.get("manager"),
                lease or resources.get("lease"),
                finalization_done,
            )

    @staticmethod
    def _cleanup_run_lifecycle(
        record: RunRecord,
        codex_output_handles: list[Any],
        sensors: tuple[Any, ...],
        manager: WorkspaceLeaseManager | None,
        lease: Any,
        finalization_done: bool,
    ) -> None:
        """Release run resources that were not already released by finalization."""

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
        codex_session = record.runtime.get("codex_session")
        if codex_session is not None:
            try:
                codex_session.close(force=False)
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
                if (
                    not record.runtime.get("end_session_requested")
                    and self._stop_request_reason(record.session_id) == _END_SESSION_REQUEST
                ):
                    # Another AIA window asked to end this conversation.  Close
                    # it the same way this window's own "end session" does so
                    # the run finalizes as Agent-exited, not as an abort.
                    record.runtime["end_session_requested"] = True
                    codex_session = record.runtime.get("codex_session")
                    if codex_session is not None:
                        Thread(
                            target=codex_session.close,
                            kwargs={"force": False},
                            name=f"aia-end-session-{record.session_id[:8]}",
                            daemon=True,
                        ).start()
                    else:
                        record.stop_requested = True
                    continue
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
        # A graceful end request is handled separately in _wait_for_agent and
        # must not turn the run into a user abort.
        requested = self._stop_request_reason(record.session_id) not in {None, _END_SESSION_REQUEST}
        if requested:
            record.stop_requested = True
        return requested

    def _stop_request_reason(self, session_id: str) -> str | None:
        """Return the pending cross-process request reason, if any.

        An unreadable request file still counts as a user stop, as before.
        """

        try:
            path = self._stop_request_path(session_id)
            if not path.is_file():
                return None
        except (OSError, ValueError):
            return None
        try:
            reason = json.loads(path.read_text(encoding="utf-8")).get("reason")
        except (OSError, ValueError, AttributeError):
            return "USER_ABORT"
        return reason if reason == _END_SESSION_REQUEST else "USER_ABORT"

    def _write_stop_request(self, session_id: str, *, reason: str = "USER_ABORT") -> Path:
        path = self._stop_request_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "requested_at": _now().isoformat(),
                    "reason": reason,
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
                tool_name=_event_tool_name(event),
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
                    execution_observed=True,
                    tool_name=_event_tool_name(containment.source_event),
                )
            )
        display_view = {"actions": action_views}
        _annotate_execution_observations(
            display_view,
            control_root=self.control_root,
            session_id=record.session_id,
        )
        record.actions = display_view["actions"]
        record.incidents = [
            item
            for item in (incident_view(action) for action in action_views)
            if item
        ]
        record.hook_event_count = len(events)
        runtime_sensors = record.runtime.get("sensors", ())
        sensors_healthy = _sensors_runtime_healthy(runtime_sensors)
        if record.phase == "RUNNING" and not _product_sensor_set_present(runtime_sensors):
            sensors_healthy = False
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
        root = (self.control_root / "run-status").resolve(strict=False)
        return self._runtime_state_path_under_root(session_id, root)

    def _runtime_state_path_under_root(self, session_id: str, root: Path) -> Path:
        if (
            not isinstance(session_id, str)
            or not session_id
            or any(not (character.isalnum() or character == "-") for character in session_id)
        ):
            raise ValueError("invalid session_id")
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
            "launch_mode": record.launch_mode,
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
            "bundle_status": record.bundle_status or (
                "PENDING" if record.result_path is None else "UNVERIFIED"
            ),
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
        with self._runtime_state_lock:
            path = self._runtime_state_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Multiple request threads persist the same live run while the
            # background launcher updates it. A shared ``.tmp`` name lets one
            # writer replace or remove another writer's temporary file, which
            # falsely degrades an otherwise healthy run. Each write gets its
            # own temporary path and the final replace remains atomic.
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(dict(payload), ensure_ascii=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, path)
            finally:
                try:
                    temporary.unlink()
                except OSError:
                    pass
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
            with self._runtime_states_cache_lock:
                self._runtime_states_cache.clear()
            return []
        states: list[dict[str, Any]] = []
        seen_paths: set[Path] = set()
        for path in root.glob("*.json"):
            session_id = path.stem
            try:
                if self._runtime_state_path_under_root(session_id, root) != path:
                    continue
            except ValueError:
                continue
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns, stat.st_ino)
            except OSError:
                continue
            seen_paths.add(path)
            with self._runtime_states_cache_lock:
                cached = self._runtime_states_cache.get(path)
                payload = cached[4] if cached is not None and cached[:4] == signature else None
            if payload is None:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict) or payload.get("session_id") != session_id:
                    continue
                with self._runtime_states_cache_lock:
                    self._runtime_states_cache[path] = (*signature, payload)
                    if len(self._runtime_states_cache) > _RUNTIME_STATES_CACHE_LIMIT:
                        self._runtime_states_cache.pop(next(iter(self._runtime_states_cache)))
            if not isinstance(payload, dict) or payload.get("session_id") != session_id:
                continue
            states.append(deepcopy(payload))
        with self._runtime_states_cache_lock:
            for cached_path in self._runtime_states_cache.keys() - seen_paths:
                self._runtime_states_cache.pop(cached_path, None)
        return states

    def result_directory_for(self, session_id: str) -> Path:
        return self.reader.result_directory(session_id) / "result.json"
