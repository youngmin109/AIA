"""Protected run preparation, launch, observation, and finalization."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile
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
    HookEnforcementBridge,
    HookSensor,
    HookTrustStatus,
    Normalizer,
    ProcessIdentityStatus,
    ProcessManager,
    ProcessObserverCapability,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    ProtectedRunSession,
    RawEvidenceStore,
    SessionFinalizer,
    SessionStatus,
    RuntimePolicyEvaluator,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    __version__,
)
from aia.readiness import ProtectionReadinessBarrier
from aia.session import SessionEndReason
from .codex_app_server import CodexAppServerError, CodexAppServerSession

from .registry import RunRecord
from .run_history import _hook_broker_runtime_healthy, _sensor_summary_is_verified
from .presenters import incident_view, safe_tool_name


class ApplicationValidationError(ValueError):
    """Raised when a console request cannot enter the Core pipeline."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _popen_kwargs_for_launch_mode(launch_mode: str) -> dict[str, Any]:
    """Return Windows-only terminal creation options for an interactive run."""

    if launch_mode != "new_terminal":
        return {}
    if os.name != "nt":
        raise ApplicationValidationError("new_terminal launch mode requires Windows 11")
    return {"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0)}


def _sensor_status(sensor: Any) -> str | None:
    health = getattr(sensor, "health", None)
    if callable(health):
        health = health()
    status = getattr(health, "status", None)
    return getattr(status, "value", status)


def _sensors_runtime_healthy(sensors: Any) -> bool:
    items = tuple(item for item in (sensors or ()) if item is not None)
    return bool(items) and all(_sensor_status(item) == "HEALTHY" for item in items)


def _event_tool_name(event: Any | None) -> str | None:
    """Extract only an allowlisted tool label from Hook Evidence."""

    if event is None:
        return None
    for record in getattr(event, "records", ()):
        payload = getattr(record, "payload", None)
        if isinstance(payload, Mapping):
            tool_name = safe_tool_name(payload.get("tool_name"))
            if tool_name:
                return tool_name
    return None


def _runtime_action_view(
    action: Any,
    policy_result: Any,
    attribution_result: Any,
    gate_result: Any,
    *,
    execution_observed: bool = False,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Build the redacted live/result action view from authoritative facts."""

    observed_at = getattr(action, "observed_at", None)
    return {
        "action_id": action.action_id,
        "attribution_grade": attribution_result.grade.value,
        "attribution_reason": attribution_result.reason,
        "enforcement_action": gate_result.action.value,
        "enforcement_decision": gate_result.decision.value,
        "execution_result": gate_result.execution_result.value,
        "execution_observed": execution_observed,
        "tool_name": safe_tool_name(tool_name),
        "operation": action.operation.value,
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
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


def _containment_errors(containments: Any) -> list[str]:
    """Termination errors of post-action containments, once per containment."""

    return [item.termination_error for item in containments if item.termination_error]


def _posttool_use_ids(control_root: Path, session_id: str) -> set[str]:
    """Return only tool-use identifiers proven by PostToolUse Evidence.

    This is presentation metadata. It does not alter the Core enforcement
    result, which intentionally keeps ``NOT_ATTEMPTED`` when no enforcement
    action was executed.
    """

    try:
        records = RawEvidenceStore.for_session(control_root, session_id).records()
    except (OSError, ValueError):
        return set()
    return {
        str(record.payload["tool_use_id"])
        for record in records
        if record.record_type.value == "POSTTOOL_OBSERVED"
        and isinstance(record.payload.get("tool_use_id"), str)
        and record.payload.get("tool_use_id")
    }


class ProtectedRunMixin:
    def _prepare_protected_run(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        resolved: Any,
        resources: dict[str, Any],
    ) -> tuple[Any, Any, tuple[Any, ...], Any, Any, Any, bool]:
        """Acquire protection resources and verify sensor readiness."""

        manager = WorkspaceLeaseManager(
            self.control_root,
            process_identity_provider=process_create_time,
        )
        resources["manager"] = manager
        preparation = prepare_protection(
            session,
            resolved,
            self.control_root,
            lease_manager=manager,
            owner_pid=os.getpid(),
            owner_process_create_time=process_create_time(os.getpid()),
        )
        lease = preparation.workspace_lease
        resources["lease"] = lease
        record.runtime.update({"preparation": preparation, "lease_manager": manager})
        record.lease = "ACTIVE"
        self._startup_step(record, "checkpoint")
        checkpoint = create_safe_checkpoint(
            session,
            preparation,
            lease_manager=manager,
            progress=lambda stage, done, total: self._startup_progress(record, stage, done, total),
        )
        record.runtime["checkpoint"] = checkpoint
        record.checkpoint = "READY"

        self._startup_step(record, "sensors")
        filesystem = FilesystemSensor(session, preparation, checkpoint, lease_manager=manager)
        hook = HookSensor(session, preparation, checkpoint, lease_manager=manager)
        filesystem.start()
        hook.start()
        sensors = (filesystem, hook)
        resources["sensors"] = sensors
        record.runtime["sensors"] = sensors
        self._refresh_sensors(record, sensors)
        self._startup_step(record, "readiness")
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
                record, session, preparation, checkpoint, sensors, manager, lease
            )
            return manager, lease, sensors, preparation, checkpoint, readiness, False
        self._phase(record, "READY", SessionStatus.READY)
        record.protection_state = "READY_UNVERIFIED"
        return manager, lease, sensors, preparation, checkpoint, readiness, True

    def _observe_protected_run(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        filesystem: FilesystemSensor,
        hook: HookSensor,
        manager: WorkspaceLeaseManager,
        lease: Any,
        sensors: tuple[Any, ...],
        launcher: ProtectedLauncher,
        adapter_options: dict[str, Any],
        codex_output_handles: list[Any],
    ) -> tuple[Any, tuple[Any, ...], int, bool | None, Any] | None:
        """Launch Codex, collect evidence, and verify any recovery."""

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
        # The Process Sensor is created before the launcher can report a
        # startup failure. Preserve it in the run record even when Codex
        # exits during startup so failed runs still show truthful sensor
        # health and evidence in the Workbench.
        process_sensor = launcher.process_sensor
        if process_sensor is not None:
            sensors = (filesystem, hook, process_sensor)
            record.runtime["sensors"] = sensors
            self._refresh_sensors(record, sensors)
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
                return None
            if not self._request_user_abort(record, launcher):
                record.stop_error = "USER_ABORT_TERMINATION_UNCONFIRMED"
        if launch.context is None or launch.status.value != "RUNNING":
            raise RuntimeError(launch.failure_code or "Codex launch failed")
        process_sensor = launcher.process_sensor
        sensors = (filesystem, hook, process_sensor)
        record.runtime["sensors"] = sensors
        # The Process Sensor is created only after Codex has been
        # registered. Refresh the public runtime snapshot at that point
        # so the Workbench shows all three product sensors as active.
        self._refresh_sensors(record, sensors)
        self._phase(record, "RUNNING", SessionStatus.RUNNING)
        record.protection_state = "ACTIVE_UNVERIFIED"
        if record.runtime.get("codex_session") is not None:
            self._startup_step(record, "conversation")
        self._open_codex_conversation(record)
        self._startup_step(record, None)
        process = launcher.process_handle
        exit_code = self._wait_for_agent(record, process, launcher)
        record.runtime['point_closing'] = True
        worker = record.runtime.get('point_worker')
        if worker is not None:
            worker.join()
        # No supplemental capture may race Lease release / final bundle creation.
        with self._point_lock(record):
            pass
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
        return (
            launch,
            sensors,
            exit_code,
            hook_broker_healthy_before_stop,
            recovery_verification,
        )

    def _process_evidence(self, record: RunRecord) -> None:
        session: ProtectedRunSession = record.runtime["session"]
        preparation = record.runtime["preparation"]
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
        posttool_ids = _posttool_use_ids(self.control_root, session.session_id)

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
            *,
            execution_observed: bool = False,
            tool_name: str | None = None,
        ) -> None:
            action_views.append(
                _runtime_action_view(
                    action,
                    policy_result,
                    attribution_result,
                    gate_result,
                    execution_observed=execution_observed,
                    tool_name=tool_name,
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
            append_action_view(
                action,
                policy_result,
                attribution_result,
                gate_result,
                execution_observed=(
                    codex_event is not None
                    and codex_event.tool_use_id in posttool_ids
                ),
                tool_name=_event_tool_name(codex_event),
            )

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
                execution_observed=True,
                tool_name=_event_tool_name(containment.source_event),
            )
        # Evidence is now also processed during a run (recovery-point checks), so
        # rebuild the error list from the containments instead of appending.
        containment_errors = _containment_errors(post_action_containments)
        if containment_errors:
            record.runtime["post_action_containment_errors"] = containment_errors
        else:
            record.runtime.pop("post_action_containment_errors", None)
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

    def _create_protected_launcher(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        filesystem: FilesystemSensor,
        hook: HookSensor,
        manager: WorkspaceLeaseManager,
        readiness: Any,
        codex_output_handles: list[Any],
    ) -> tuple[ProtectedLauncher, Any, dict[str, Any]]:
        """Build the hook controller and protected Codex launcher."""

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
            # Human-in-the-loop for tools AIA cannot interpret: only the
            # structured Workbench conversation can ask the user in time.
            unsupported_tool_reviewer=(
                (lambda review: self._review_unsupported_tool(record, review))
                if record.launch_mode == "codex_app_server"
                else None
            ),
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

            if record.launch_mode == "codex_app_server":
                try:
                    codex_session = CodexAppServerSession(
                        argv,
                        cwd=Path(kwargs["cwd"]),
                        env=kwargs["env"],
                        client_version=__version__,
                    )
                    codex_session.start()
                except (KeyError, CodexAppServerError) as error:
                    raise RuntimeError(f"CODEX_APP_SERVER_START_FAILED: {error}") from error
                record.runtime["codex_session"] = codex_session
                return codex_session.process_handle
            if record.interactive:
                kwargs.update(_popen_kwargs_for_launch_mode(record.launch_mode))
                return subprocess.Popen(argv, **kwargs)
            stdout_stream = tempfile.TemporaryFile(mode="w+b")
            stderr_stream = tempfile.TemporaryFile(mode="w+b")
            codex_output_handles.extend((stdout_stream, stderr_stream))
            kwargs["stdout"] = stdout_stream
            kwargs["stderr"] = stderr_stream
            if os.name == "nt":
                kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
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
            if record.launch_mode == "codex_app_server":
                adapter_options["app_server"] = True
                if record.permission_mode == "full_access":
                    # Full access: the user chose no Codex sandbox and no Codex
                    # approval prompts; the AIA Hook still checks every call.
                    adapter_options.update({"approval_policy": "never", "sandbox": "danger-full-access"})
                # External tools can run outside the Hook; only those the user
                # allowed in Settings stay on for this run.
                overrides, turned_off = self._external_tool_overrides()
                adapter_options["disable_external_tools"] = overrides
                record.runtime["external_tools_off"] = turned_off
        elif record.permission_mode == "full_access":
            # Only the Hook verification probe runs exec with full access.  It
            # proves the Hook path, which fires before any sandboxed execution,
            # so waiting for Codex to prepare its sandbox only delays the proof.
            adapter_options.update(
                {
                    "sandbox": "danger-full-access",
                    "approval_policy": "never",
                    "skip_git_repo_check": True,
                }
            )
        else:
            # Codex CLI's current exec contract applies the supported
            # workspace-write/on-request policy through --approve-for-me.
            # Passing -c approval_policy=on-request alone is silently
            # reported as approval=never on some Windows installations.
            adapter_options["approve_for_me"] = True
            adapter_options["skip_git_repo_check"] = True
        if not record.interactive:
            # Exec commands can also invoke external tools outside the Hook.
            # Apply the same user-aware disable plan as protected app-server runs.
            overrides, turned_off = self._external_tool_overrides()
            adapter_options["disable_external_tools"] = overrides
            record.runtime["external_tools_off"] = turned_off
        return launcher, controller, adapter_options

    def _finalize_completed_protected_run(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        sensors: tuple[Any, ...],
        manager: WorkspaceLeaseManager,
        lease: Any,
        launch: Any,
        exit_code: int,
        controller: Any,
        hook_broker_healthy_before_stop: bool | None,
        recovery_verification: Any,
    ) -> bool:
        """Finalize evidence and publish the terminal run snapshot."""

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
        if getattr(controller, "user_approved_unsupported_tools", ()):
            # The user let a tool AIA cannot interpret run; the Bundle
            # records that decision instead of claiming protection for it.
            limitations.append("UNSUPPORTED_TOOL_USER_APPROVED")
        limitations.extend(record.runtime.get("unsupported_tool_review_decisions", ()))
        if record.permission_grants:
            # The sealed result records the scope exception; detailed user
            # decisions remain in the separate Workbench runtime snapshot.
            limitations.append("CODEX_PERMISSIONS_USER_GRANTED")
        if record.full_access_used:
            # The user chose full access for some or all requests: the Codex
            # sandbox did not limit writes outside the work folder or network
            # use.  AIA's Hook, sensors and recovery still applied.
            limitations.append("CODEX_FULL_ACCESS_USER_SELECTED")
        if any(change.get("status") in {"SUBMITTING", "ACKNOWLEDGED", "UNCONFIRMED"} for change in record.permission_changes):
            limitations.append("CODEX_PERMISSION_MODE_CHANGED")
        if record.auto_review_used:
            # Codex's auto-review, not the user, answered approval requests.
            limitations.append("CODEX_AUTO_REVIEW_USER_SELECTED")
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
                and not record.permission_grants
                and not record.auto_review_used
                else "ABORTED_DEGRADED"
                if final.result.session_status is SessionStatus.ABORTED
                else "COMPLETED_VERIFIED"
                if controller.events and not controller.errors
                and sensor_verified
                and hook_broker_healthy_before_stop is True
                and not record.runtime.get("codex_sandbox_downgraded")
                and not record.runtime.get("codex_approval_policy_downgraded")
                and not record.permission_grants
                and not record.auto_review_used
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

        return True
