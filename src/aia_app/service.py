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
from .run_control import RunControlMixin
from .recovery_points import RecoveryPointsMixin


# The dashboard refreshes active runs every five seconds. Keep the verified
# history snapshot through one refresh interval so repeated UI requests do
# not re-hash every completed bundle while a live terminal is active.
_COMPLETED_RUNS_CACHE_TTL_SECONDS = 6.0
_RUNTIME_STATES_CACHE_LIMIT = 2_048


# Human-in-the-loop review stays inside Codex's 30 s Hook timeout.
_UNSUPPORTED_TOOL_REVIEW_SECONDS = 25.0
_WORKSPACE_SIZE_MAX_FILES = 5_000
_WORKSPACE_SIZE_MAX_SECONDS = 1.5


def _workspace_size_estimate(
    workspace: Path,
    *,
    max_files: int = _WORKSPACE_SIZE_MAX_FILES,
    max_seconds: float = _WORKSPACE_SIZE_MAX_SECONDS,
) -> dict[str, Any]:
    """Count files and bytes so a slow start can be announced before it begins.

    Bounded by a file count and a time budget; ``complete`` is False when the
    count stopped early.  Links are not followed, matching the checkpoint.
    """

    deadline = time.monotonic() + max_seconds
    files = 0
    total = 0
    pending = [workspace]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    if files >= max_files or time.monotonic() > deadline:
                        return {"files": files, "bytes": total, "complete": False}
        except OSError:
            continue
    return {"files": files, "bytes": total, "complete": True}


# app-server reports sandbox modes in camelCase; the Result Bundle and the
# requested-policy comparison use the CLI spelling.
_APP_SERVER_SANDBOX_NAMES = {
    "readOnly": "read-only",
    "workspaceWrite": "workspace-write",
    "dangerFullAccess": "danger-full-access",
}


def _manual_recovery_digest(body: Mapping[str, Any]) -> str:
    """SHA-256 of a manual-recovery record without its own seal field."""

    content = {key: value for key, value in body.items() if key != "record_sha256"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


_POINT_SEND_WAIT_SECONDS = 30.0


class RunApplicationService(
    RunControlMixin, ProtectedRunMixin, RunHistoryMixin, PreflightMixin, RecoveryPointsMixin
):
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
        self._manual_restore_lock = RLock()
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
        display = {
            PolicyProfile.PROTECTED_DEVELOPMENT: (
                "표준 보호",
                "Standard Protection",
                "모든 .env 계열 읽기와 대표적인 파괴 명령을 차단하고, 그 밖의 개발 행위는 기록합니다.",
            ),
            PolicyProfile.BASIC_DEVELOPMENT: (
                "협업 개발",
                "Development Collaboration",
                "일반 개발 작업을 허용하면서 .env 삭제와 위험한 데이터베이스·Git 명령을 통제합니다.",
            ),
            PolicyProfile.CONSERVATIVE_SECURITY: (
                "변경 통제 강화",
                "Change Control",
                "루트 .env 읽기는 기록하고, 의존성·인프라 파일의 삭제와 위험한 데이터베이스·Git 명령을 차단합니다.",
            ),
            PolicyProfile.FREE_DEVELOPMENT: (
                "관찰 전용",
                "Observation Only",
                "개발 흐름을 가장 넓게 허용하고 위험 행위를 주로 기록하는 프로필입니다.",
            ),
            PolicyProfile.CUSTOM: (
                "사용자 지정",
                "Custom Policy",
                "파일 경로·명령·행동별 규칙을 직접 설정하고 검증해 저장합니다. 저장한 규칙은 다음 보호 실행부터 적용됩니다.",
            ),
        }
        return [
            {
                "value": profile.value,
                "display_name": display[profile][0],
                "english_name": display[profile][1],
                "description": display[profile][2],
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
        record = self.registry.get(session_id)
        if record is None:
            return self._codex_workbench.send_codex_message(session_id, text)
        lock = self._point_lock(record)
        # A recovery-point capture is short for the workspaces it runs on; wait
        # for it rather than rejecting the user's message outright.
        if not lock.acquire(timeout=_POINT_SEND_WAIT_SECONDS):
            raise CodexAppServerError('복구 지점을 저장 중이에요. 잠시 뒤 명령을 다시 보내 주세요.')
        try:
            return self._codex_workbench.send_codex_message(session_id, text)
        finally:
            lock.release()

    def interrupt_codex_turn(self, session_id: str) -> dict[str, Any]:
        return self._codex_workbench.interrupt_codex_turn(session_id)

    def respond_codex_approval(self, session_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        return self._codex_workbench.respond_codex_approval(session_id, approval_id, decision)

    def respond_codex_question(self, session_id: str, question_id: str, answers: Any) -> dict[str, Any]:
        return self._codex_workbench.respond_codex_question(session_id, question_id, answers)

    def respond_codex_elicitation(self, session_id: str, elicitation_id: str, action: str, content: Any) -> dict[str, Any]:
        return self._codex_workbench.respond_codex_elicitation(session_id, elicitation_id, action, content)

    def respond_codex_permissions(self, session_id: str, permissions_id: str, decision: str) -> dict[str, Any]:
        return self._codex_workbench.respond_codex_permissions(session_id, permissions_id, decision)

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
        view['manual_recovery'] = manual
        if manual.get('record_verification') != 'VALID':
            # Do not overlay unaudited recovery onto the original verified run.
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
        if not isinstance(payload, dict):
            return None
        verification = 'UNVERIFIED'
        try:
            recorded = payload.get('record_sha256')
            if isinstance(recorded, str):
                body = {key: value for key, value in payload.items() if key != 'record_sha256'}
                sealed = recorded == _manual_recovery_digest(body)
            else:
                # Records sealed by a sidecar file (earlier format of this change).
                seal = path.with_suffix('.sha256').read_text(encoding='ascii').strip()
                sealed = seal == hashlib.sha256(path.read_bytes()).hexdigest()
            if sealed:
                current_result_hash = hashlib.sha256(self.reader.read_result_json(session_id)).hexdigest()
                verification = 'VALID' if payload.get('original_result_sha256') == current_result_hash else 'INVALID'
            else:
                verification = 'INVALID'
        except (OSError, ValueError, KeyError):
            pass
        return {**payload, 'record_verification': verification}

    def _archive_unverified_manual_recovery(self, session_id: str) -> None:
        """Keep an unverifiable record for audit, but stop it blocking a new restore."""

        path = self._manual_recovery_artifact_path(session_id)
        stamp = _now().strftime('%Y%m%dT%H%M%S%fZ')
        for current in (path, path.with_suffix('.sha256')):
            if current.exists():
                os.replace(current, current.with_name(f'{current.stem}.superseded-{stamp}{current.suffix}'))

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

    def _manual_recovery_context(self, session_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        """Load a completed run and its immutable checkpoint without mutation."""

        record = self.registry.get(session_id)
        if record is not None and record.status not in {"COMPLETED", "ABORTED", "FAILED"}:
            return {"available": False, "reason": "RUN_IS_ACTIVE"}
        try:
            raw_result = self.reader.read_result(session_id)
        except (KeyError, OSError, ValueError) as error:
            raise KeyError(session_id) from error
        workspace = self._validate_workspace(raw_result.get("workspace"))
        points = self._recovery_checkpoints(session_id, workspace)
        # Supplemental points never become the implicit launch baseline.
        checkpoint = next((point for point in points if
                           (point.checkpoint_id == checkpoint_id if checkpoint_id is not None
                            else not point.checkpoint_id.startswith('point-'))), None)
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
            "checkpoint_id": checkpoint.checkpoint_id,
            "workspace_matches": comparison.matches,
            "checkpoint_validity": checkpoint.validity.value,
            "checkpoint_created_at": checkpoint.created_at.isoformat(),
            "preview_fingerprint": comparison.current_workspace_content_sha256,
            "change_count": len(comparison.created_paths) + len(comparison.changed_paths) + len(comparison.deleted_paths),
            "change_preview": ([{'path': path, 'operation': 'REMOVE_CURRENT'} for path in comparison.created_paths]
                               + [{'path': path, 'operation': 'RESTORE_CONTENT'} for path in comparison.changed_paths]
                               + [{'path': path, 'operation': 'RESTORE_MISSING'} for path in comparison.deleted_paths])[:200],
            "preview_truncated": len(comparison.created_paths) + len(comparison.changed_paths) + len(comparison.deleted_paths) > 200,
        }

    def get_recovery_status(self, session_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        context = self._manual_recovery_context(session_id, checkpoint_id)
        manual = self._read_manual_recovery(session_id)
        if checkpoint_id is not None:
            # A selected point previews CURRENT bytes, not an old restore's result.
            context.update(status='NOT_REQUIRED' if context.get('workspace_matches') else 'NOT_ATTEMPTED',
                           integrity_status='VERIFIED' if context.get('workspace_matches') else 'NOT_CHECKED')
        elif manual is not None and manual.get('record_verification') == 'VALID':
            context = {
                **context,
                "available": False,
                "status": (manual.get("recovery_result") or {}).get("recovery_status"),
                "integrity_status": (manual.get("integrity_result") or {}).get("integrity_status"),
                "recovery_result": manual.get("recovery_result"),
                "integrity_result": manual.get("integrity_result"),
                "manual_recovery": True,
                "record_verification": manual.get('record_verification'),
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
                "record_verification": manual.get('record_verification') if manual else None,
            }
        return {
            key: value
            for key, value in context.items()
            if key not in {"workspace", "raw_result", "checkpoint"}
        }

    def restore_run(self, session_id: str, *, confirm: bool, expected_fingerprint: str | None = None, checkpoint_id: str | None = None) -> dict[str, Any]:
        with self._manual_restore_lock:
            return self._restore_run_locked(session_id, confirm=confirm, expected_fingerprint=expected_fingerprint, checkpoint_id=checkpoint_id)

    def _restore_run_locked(self, session_id: str, *, confirm: bool, expected_fingerprint: str | None = None, checkpoint_id: str | None = None) -> dict[str, Any]:
        if confirm is not True:
            raise ApplicationValidationError("전체 Workspace 복구 확인이 필요합니다.")
        existing = self._read_manual_recovery(session_id)
        if checkpoint_id is None and existing is not None and existing.get('record_verification') == 'VALID':
            return existing
        if checkpoint_id is not None and expected_fingerprint is None:
            raise ApplicationValidationError('선택한 복구 지점의 미리보기를 먼저 확인해 주세요.')
        context = self._manual_recovery_context(session_id, checkpoint_id)
        if not context.get("available"):
            raise ApplicationValidationError(str(context.get("reason") or "RECOVERY_UNAVAILABLE"))
        if expected_fingerprint is not None and expected_fingerprint != context.get('preview_fingerprint'):
            raise ApplicationValidationError('미리보기 이후 작업공간이 변경됐습니다. 복구 목록을 다시 확인해주세요.')
        if existing is not None and existing.get('record_verification') != 'VALID':
            # An older unsealed (or damaged) record is never overwritten: it is
            # kept beside the new one so the restore is not blocked forever.
            self._archive_unverified_manual_recovery(session_id)
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
            # Recheck under Lease. External writers remain a documented limit.
            if expected_fingerprint is not None:
                from aia.checkpoint import compare_workspace_to_checkpoint
                if compare_workspace_to_checkpoint(checkpoint, workspace).current_workspace_content_sha256 != expected_fingerprint:
                    raise ApplicationValidationError('미리보기 이후 작업공간이 변경됐습니다. 다시 확인해주세요.')
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
            "original_result_sha256": hashlib.sha256(self.reader.read_result_json(session_id)).hexdigest(),
            "checkpoint_manifest_sha256": checkpoint.manifest_sha256,
            "session_id": session_id,
            "checkpoint_id": checkpoint.checkpoint_id,
            "workspace": str(workspace),
            "recovery_result": self._recovery_mapping(verification.recovery),
            "integrity_result": self._integrity_mapping(verification.integrity),
            "saved_at": _now().isoformat(),
        }
        # The checksum lives in the same file, so one atomic replace commits
        # the record and its seal together.
        payload["record_sha256"] = _manual_recovery_digest(payload)
        path = self._manual_recovery_artifact_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        history = path.parent / 'recovery-history'
        history.mkdir(exist_ok=True)
        # Preserve every outcome independently; the old file remains a latest
        # compatibility view. No finalized result bundle is modified.
        if existing is not None and existing.get('record_verification') == 'VALID':
            previous = {key: value for key, value in existing.items() if key != 'record_verification'}
            previous_id = (previous.get('recovery_result') or {}).get('recovery_id')
            previous_path = history / f'{hashlib.sha256(str(previous_id).encode()).hexdigest()}.json'
            if not previous_path.exists():
                with previous_path.open('x', encoding='utf-8') as stream:
                    json.dump(previous, stream, ensure_ascii=False, indent=2)
        history_path = history / f'{hashlib.sha256(str(payload["recovery_result"]["recovery_id"]).encode()).hexdigest()}.json'
        with history_path.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
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

    def get_run_activity(self, session_id: str, status: dict[str, Any]) -> dict[str, Any]:
        session = status.get('session') or {}
        live = session.get('status') in {'RUNNING', 'STARTING', 'PROTECTING', 'CREATED', 'PREPARING', 'READY'}
        live = live and not (status.get('runtime_reconciliation') or {}).get('orphaned')
        try:
            return self.reader.read_activity(session_id, Path(session['workspace']), live=live)
        except (KeyError, OSError, ValueError, TypeError):
            return {'available': False, 'reason': 'EVIDENCE_NOT_VERIFIED'}

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
            "size_estimate": _workspace_size_estimate(workspace) if workspace.is_dir() else None,
        }

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
            self._startup_step(record, "launch")
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

        # Exceptional exits must wait for captures too, before releasing ownership.
        record.runtime['point_closing'] = True
        point_worker = record.runtime.get('point_worker')
        if point_worker is not None:
            point_worker.join()
        point_lock = record.runtime.get('point_lock')
        if point_lock is not None:
            with point_lock:
                pass
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
        (
            evidence_metadata,
            observed_evidence_ids,
            capture_times,
        ) = self._read_live_evidence_snapshot(record.session_id)
        _annotate_execution_observations(
            display_view,
            control_root=self.control_root,
            session_id=record.session_id,
            evidence_metadata=evidence_metadata,
            execution_observations=(observed_evidence_ids, capture_times),
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

    def _startup_step(self, record: RunRecord, step: str | None) -> None:
        """Mark the preparation step now running; ``None`` ends the startup.

        Display only: the steps name work that already happens, and never
        stand in for the checkpoint, sensor or readiness results themselves.
        """

        now = _now().isoformat()
        steps = [dict(item) for item in record.startup.get("steps", [])]
        if steps and steps[-1].get("ended_at") is None:
            steps[-1]["ended_at"] = now
        if step is not None:
            steps.append({"step": step, "started_at": now, "ended_at": None})
        record.startup = {"current": step, "steps": steps}

    def _startup_progress(self, record: RunRecord, stage: str, done: int, total: int | None) -> None:
        record.startup = {**record.startup, "progress": {"stage": stage, "done": done, "total": total}}

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
        if record.startup.get("current"):
            self._startup_step(record, None)
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
            "startup": record.startup,
            "permission_grants": record.permission_grants,
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
