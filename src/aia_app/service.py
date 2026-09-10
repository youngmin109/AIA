"""Application orchestration for the optional Local Security Console."""

from __future__ import annotations

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
    PolicyProfile,
    ProcessIdentityStatus,
    ProcessObserverCapability,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    ProtectedRunSession,
    RawEvidenceStore,
    RuntimePolicyEvaluator,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    resolve_profile,
)
from aia.session import SessionEndReason, WorkspaceValidationError
from aia.readiness import ProtectionReadinessBarrier

from .dto import CreateRunRequest, DTOValidationError
from .presenters import action_view, incident_view, incident_views_for_result, result_view
from .readers import ResultBundleReader
from .registry import RunRecord, RunRegistry


class ApplicationValidationError(ValueError):
    """Raised when a console request cannot enter the Core pipeline."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    ) -> None:
        self.control_root = Path(control_root).expanduser().resolve(strict=False)
        self.registry = registry or RunRegistry()
        self.reader = ResultBundleReader(self.control_root)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="aia-console-run",
        )

    @staticmethod
    def policy_profiles() -> list[dict[str, str]]:
        descriptions = {
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
                PolicyProfile.BASIC_DEVELOPMENT,
                PolicyProfile.CONSERVATIVE_SECURITY,
                PolicyProfile.FREE_DEVELOPMENT,
                PolicyProfile.CUSTOM,
            )
        ]

    def preflight(self) -> dict[str, Any]:
        """Report local prerequisites without starting a Protected Run."""

        checks: list[dict[str, Any]] = []
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

        required = [item for item in checks if not item.get("optional")]
        return {
            "ready": all(bool(item["ok"]) for item in required),
            "checks": checks,
            "hook_trust": {
                "status": "MANUAL_REVIEW_REQUIRED",
                "detail": "Codex에서 /hooks를 열어 AIA Hook을 직접 검토·신뢰해야 합니다.",
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
        workspace = self._validate_workspace(request.workspace)
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
        if live_record is not None:
            self._refresh_protection_state(live_record)
        record = self.registry.snapshot(session_id)
        if record is None:
            try:
                return self._status_from_completed_bundle(session_id)
            except (KeyError, OSError, ValueError):
                runtime_state = self._read_runtime_state(session_id)
                if runtime_state is None:
                    raise
                return self._status_from_runtime_state(runtime_state)
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
        if launcher is None or getattr(getattr(launcher, "status", None), "value", None) != "RUNNING":
            record.protection_state = "STOP_REQUESTED"
            self._persist_runtime_state(record)
            return {
                "accepted": True,
                "session_id": session_id,
                "status": "STOP_REQUESTED",
                "reason": "STOP_WILL_BE_APPLIED_BEFORE_AGENT_LAUNCH",
            }
        try:
            stopped = bool(launcher.request_user_abort())
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
            session = state.get("session") if isinstance(state.get("session"), dict) else {}
            policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
            protection = state.get("protection") if isinstance(state.get("protection"), dict) else {}
            session_id = state.get("session_id")
            if not isinstance(session_id, str):
                continue
            values[session_id] = {
                "session_id": session_id,
                "status": session.get("status", "UNKNOWN"),
                "ended_at": None,
                "created_at": session.get("created_at"),
                "workspace": session.get("workspace"),
                "agent": session.get("agent"),
                "policy": {
                    "id": policy.get("id"),
                    "version": policy.get("version"),
                },
                "run_classification": "PRODUCT_PROTECTED_RUN",
                "bundle_status": "PENDING",
                "incident_count": state.get("incident_count", 0),
                "result_url": f"/runs/{session_id}/result",
                "protection_state": protection.get("state", "UNKNOWN"),
                "hook_event_count": protection.get("hook_events", 0),
            }
        for record in self.registry.snapshots():
            live_record = self.registry.get(record.session_id)
            if live_record is not None:
                self._refresh_protection_state(live_record)
                record = self.registry.snapshot(record.session_id) or record
            values[record.session_id] = {
                "session_id": record.session_id,
                "status": record.status,
                "ended_at": None,
                "created_at": record.created_at.isoformat(),
                "workspace": str(record.workspace),
                "agent": record.agent,
                "policy": {"id": record.policy_id, "version": record.policy_version},
                "run_classification": "PRODUCT_PROTECTED_RUN",
                "bundle_status": record.bundle_status or "PENDING",
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
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _validate_workspace(value: str) -> Path:
        try:
            from aia import canonicalize_workspace

            return canonicalize_workspace(value)
        except (WorkspaceValidationError, OSError, ValueError) as error:
            raise ApplicationValidationError(f"workspace validation failed: {error}") from error

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
                adapter=CodexAdapter(),
                lease_manager=manager,
                hook_bridge=bridge,
                hook_broker_factory=broker_factory,
                popen_factory=capture_popen,
                launch_context_callback=lambda context: launch_holder.update(
                    {"context": context}
                ),
            )
            adapter_options: dict[str, Any] = {"sandbox": "workspace-write"}
            if record.interactive:
                adapter_options["interactive"] = True
            else:
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
            record.runtime.update(
                {"launcher": launcher, "launch": launch, "codex_controller": controller}
            )
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
                if not launcher.request_user_abort():
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
            launcher.stop_hook_broker()
            self._capture_codex_execution_observation(record, codex_output_handles)
            self._confirm_codex_blocks(record)
            self._process_evidence(record)
            raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
            process_identity = launch.context.root_process_identity
            end_reason = (
                SessionEndReason.USER_ABORT
                if record.stop_requested
                else SessionEndReason.AGENT_EXITED
            )
            limitations = (
                ("USER_ABORT_TERMINATION_UNCONFIRMED",)
                if record.stop_error
                else ()
            )
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
                active_policy=preparation.active_policy,
                checkpoint=checkpoint,
                launch_context=launch.context,
                run_classification="PRODUCT_PROTECTED_RUN",
                agent_exit_code=exit_code,
                agent_end_observed_at=_now(),
                agent_end_verification="PROCESS_GONE",
                agent_output_observation=record.runtime.get("codex_output_observation"),
                limitations=limitations,
            )
            finalization_done = True
            result_mapping = final.result.to_mapping()
            verification = final.bundle_verification
            record.runtime["final"] = final
            self.registry.update(
                record.session_id,
                status=final.result.session_status.value,
                phase="COMPLETED" if final.result.session_status is SessionStatus.COMPLETED else final.result.session_status.value,
                lease="RELEASED",
                result_path=final.bundle.result_directory / "result.json",
                result=result_mapping,
                bundle_status=verification.status.value,
                protection_state=(
                    "ABORTED_VERIFIED"
                    if final.result.session_status is SessionStatus.ABORTED
                    and not record.stop_error
                    and controller.events
                    and not controller.errors
                    else "ABORTED_DEGRADED"
                    if final.result.session_status is SessionStatus.ABORTED
                    else "COMPLETED_VERIFIED"
                    if controller.events and not controller.errors
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
                if not self._is_stop_requested(record):
                    continue
                if record.runtime.get("stop_action_attempted"):
                    continue
                record.runtime["stop_action_attempted"] = True
                record.protection_state = "STOP_REQUESTED"
                if not launcher.request_user_abort():
                    record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
                    record.protection_state = "DEGRADED"
                self._persist_runtime_state(record)

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
            action_views.append(
                {
                    "action_id": action.action_id,
                    "attribution_grade": attribution_result.grade.value,
                    "attribution_reason": attribution_result.reason,
                    "enforcement_action": gate_result.action.value,
                    "enforcement_decision": gate_result.decision.value,
                    "execution_result": gate_result.execution_result.value,
                    "operation": action.operation.value,
                    "policy_decision": policy_result.policy_decision.value,
                    "enforcement_route": gate_result.route.value,
                    "evidence_ids": list(action.evidence_ids),
                    "matched_rule_ids": list(getattr(policy_result, "matched_rule_ids", ()) or ()),
                    "matched_asset_types": [
                        getattr(policy_result.asset_type, "value", policy_result.asset_type)
                    ]
                    if getattr(policy_result, "asset_type", None) is not None
                    else [],
                    "target": {
                        "canonical_path": action.canonical_path,
                        "target_kind": action.target_kind.value,
                    },
                }
            )
        record.runtime.update(
            {
                "normalized_actions": normalized.actions,
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
        record.hook_event_count = len(controller.events)
        if controller.errors:
            record.protection_state = "DEGRADED"
        elif controller.events:
            record.protection_state = "ACTIVE_VERIFIED"
        self._persist_runtime_state(record)

    def _phase(self, record: RunRecord, phase: str, status: SessionStatus) -> None:
        record.phase = phase
        record.status = status.value
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
        return {
            "schema_version": 1,
            "session_id": record.session_id,
            "updated_at": _now().isoformat(),
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
            path = self._runtime_state_path(record.session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._runtime_state_mapping(record), ensure_ascii=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except (OSError, ValueError):
            if strict:
                raise
            record.protection_state = "DEGRADED"
            record.error = record.error or "RUNTIME_STATE_PERSIST_FAILED"

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

    @staticmethod
    def _status_from_runtime_state(state: dict[str, Any]) -> dict[str, Any]:
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
            "session": session,
        }

    def _status_from_completed_bundle(self, session_id: str) -> dict[str, Any]:
        result = self.reader.read_result(session_id)
        view = result_view(result, self.reader.verification(session_id).status.value)
        hook_events = self.reader.hook_event_count(session_id)
        sensor_failed = any(
            item.get("runtime_health_before_stop") == "FAILED"
            for item in result.get("sensor_summary", [])
            if isinstance(item, dict)
        )
        aborted = (
            result.get("session_status") == "ABORTED"
            and result.get("session_end_reason") == "USER_ABORT"
        )
        if aborted:
            protection_state = (
                "ABORTED_VERIFIED"
                if hook_events and not sensor_failed
                else "ABORTED_DEGRADED"
            )
        else:
            protection_state = (
                "COMPLETED_VERIFIED"
                if hook_events and not sensor_failed
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
