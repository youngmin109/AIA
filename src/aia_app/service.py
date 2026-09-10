"""Application orchestration for the optional Local Security Console."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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
        return [
            {"value": profile.value, "label": profile.display_name}
            for profile in (
                PolicyProfile.BASIC_DEVELOPMENT,
                PolicyProfile.CONSERVATIVE_SECURITY,
                PolicyProfile.FREE_DEVELOPMENT,
                PolicyProfile.CUSTOM,
            )
        ]

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
            return self._status_from_completed_bundle(session_id)
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

    def get_run_actions(self, session_id: str) -> list[dict[str, Any]]:
        record = self.registry.snapshot(session_id)
        if record is not None:
            return record.actions
        result = self.reader.read_result(session_id)
        return [action_view(item) for item in result.get("action_outcomes", [])]

    def list_runs(self) -> list[dict[str, Any]]:
        """Return live runs plus valid persisted Bundles for the local console."""

        values: dict[str, dict[str, Any]] = {}
        for record in self.registry.snapshots():
            self._refresh_protection_state(record)
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
            }
        for item in self.reader.list_completed():
            values.setdefault(item["session_id"], item)
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
            return result_view(record.result, record.bundle_status)
        result = self.reader.read_result(session_id)
        verification = self.reader.verification(session_id)
        return result_view(result, verification.status.value if verification else "NOT_FOUND")

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
                    handler=controller.evaluate,
                )

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
                launch_context_callback=lambda context: launch_holder.update(
                    {"context": context}
                ),
            )
            adapter_options: dict[str, Any] = {"sandbox": "workspace-write"}
            if record.interactive:
                adapter_options["interactive"] = True
            else:
                adapter_options["skip_git_repo_check"] = True
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
            if launch.context is None or launch.status.value != "RUNNING":
                raise RuntimeError(launch.failure_code or "Codex launch failed")
            process_sensor = launcher.process_sensor
            sensors = (filesystem, hook, process_sensor)
            record.runtime["sensors"] = sensors
            self._phase(record, "RUNNING", SessionStatus.RUNNING)
            record.protection_state = "ACTIVE_UNVERIFIED"
            process = launcher.process_handle
            exit_code = process.wait(timeout=3600)
            record.runtime["exit_code"] = exit_code
            launcher.stop_hook_broker()
            self._process_evidence(record)
            raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
            process_identity = launch.context.root_process_identity
            final = SessionFinalizer(
                evidence_store=raw_store,
                sensors=sensors,
                lease_manager=manager,
                workspace_lease=lease,
            ).finalize(
                session,
                end_reason=SessionEndReason.AGENT_EXITED,
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
                    "COMPLETED_VERIFIED" if not controller.errors else "COMPLETED_DEGRADED"
                ),
                hook_event_count=len(controller.events),
                sensor_health={
                    item.get("sensor"): item.get("runtime_health_before_stop")
                    for item in final.result.sensor_summary
                    if hasattr(item, "get")
                },
            )
        except Exception as error:
            self._fail_record(record, error)
        finally:
            launcher = record.runtime.get("launcher")
            if launcher is not None:
                try:
                    launcher.stop_hook_broker()
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

    @staticmethod
    def _refresh_protection_state(record: RunRecord) -> None:
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

    @staticmethod
    def _phase(record: RunRecord, phase: str, status: SessionStatus) -> None:
        record.phase = phase
        record.status = status.value

    @staticmethod
    def _refresh_sensors(record: RunRecord, sensors: tuple[Any, ...]) -> None:
        record.sensor_health = {
            sensor.health.sensor.value: sensor.health.status.value
            for sensor in sensors
            if sensor is not None
        }

    def _fail_record(self, record: RunRecord, error: Exception) -> None:
        record.status = "FAILED"
        record.phase = "FAILED"
        record.protection_state = "FAILED"
        record.error = f"{type(error).__name__}: {error}"
        record.lease = "FAILED" if record.lease == "ACTIVE" else record.lease

    def _status_from_completed_bundle(self, session_id: str) -> dict[str, Any]:
        result = self.reader.read_result(session_id)
        view = result_view(result, self.reader.verification(session_id).status.value)
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
                "state": "COMPLETED_DEGRADED"
                if any(
                    item.get("runtime_health_before_stop") == "FAILED"
                    for item in result.get("sensor_summary", [])
                    if isinstance(item, dict)
                )
                else "COMPLETED_VERIFIED",
                "hook_events": sum(
                    1
                    for item in result.get("evidence_references", [])
                    if item.get("source") == "CODEX_HOOK"
                ),
            },
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
