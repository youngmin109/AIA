"""Protected Run finalization orchestration and canonical result construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from .audit import AuditEventType, AuditRecord, audit_jsonl, order_audit_records
from .attribution import AttributionResult
from .evidence import EvidenceSeal, RawEvidenceStore
from .evidence_bundle import (
    BundleCommitResult,
    BundleVerificationResult,
    EvidenceBundleCommitter,
    EvidenceBundleVerifier,
    ResultAlreadyCommittedConflict,
)
from .enforcement import (
    EnforcementAction,
    EnforcementExecutionResult,
    EnforcementGateResult,
)
from .integrity import IntegrityStatus, IntegrityVerificationResult
from .launcher import UserAbortTerminationResult
from .process_identity import ProcessIdentity, ProcessIdentityStatus, inspect_process_identity
from .process_manager import ProcessTerminationOutcome, ProcessTerminationResult
from .protection import ActivePolicySnapshot, WorkspaceLease, WorkspaceLeaseManager
from .recovery import RecoveryResult, RecoveryVerificationResult
from .report import ReportGenerator, redact_text
from .result import (
    ActionOutcomeRecord,
    RESULT_SCHEMA_VERSION,
    RunClassification,
    SensorSummary,
    SessionResult,
)
from .session import (
    ProtectedRunSession,
    SessionEndReason,
    SessionStatus,
)
from .sensors.base import SensorHealth, SensorStatus


class FinalizationError(ValueError):
    """Base error for finalization contract failures."""


class FinalizationRefused(FinalizationError):
    """Raised when a normal completion cannot safely be claimed."""


@dataclass(frozen=True, slots=True)
class SessionFinalizationResult:
    result: SessionResult
    audit_records: tuple[AuditRecord, ...]
    bundle: BundleCommitResult
    bundle_verification: BundleVerificationResult
    evidence_seal: EvidenceSeal
    report_text: str

    @property
    def session_result(self) -> SessionResult:
        return self.result

    @property
    def result_id(self) -> str:
        return self.result.result_id

    @property
    def bundle_valid(self) -> bool:
        return self.bundle_verification.is_valid


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return None


def _dt_from_text(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _items(value: Any, *attributes: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    for attribute in attributes:
        nested = getattr(value, attribute, None)
        if nested is not None:
            return tuple(nested)
    if isinstance(value, (str, bytes, Mapping)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _identity(value: ProcessIdentity | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"create_time": value.create_time, "pid": value.pid}


def _fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _status(value: Any) -> str | None:
    if value is None:
        return None
    return str(_value(value))


def _safe_reason(value: Any) -> str | None:
    return redact_text(str(value)) if value is not None else None


def _path_relative(session_directory: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(session_directory.resolve(strict=False)).as_posix()
    except ValueError:
        return path.name


class SessionFinalizer:
    """Consume existing authoritative results and publish one terminal bundle."""

    def __init__(
        self,
        session: ProtectedRunSession | None = None,
        *,
        evidence_store: RawEvidenceStore | None = None,
        sensors: Iterable[Any] = (),
        lease_manager: WorkspaceLeaseManager | None = None,
        workspace_lease: WorkspaceLease | None = None,
        control_root: str | Path | None = None,
        bundle_committer: EvidenceBundleCommitter | None = None,
        report_generator: ReportGenerator | None = None,
        process_factory: Callable[[int], Any] | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self.evidence_store = evidence_store
        self.session = session
        self.sensors = tuple(sensors)
        self.lease_manager = lease_manager
        self.workspace_lease = workspace_lease
        self.control_root = Path(control_root).expanduser().resolve(strict=False) if control_root is not None else None
        self.bundle_committer = bundle_committer
        self.report_generator = report_generator or ReportGenerator()
        self.process_factory = process_factory
        self.clock = clock
        self._outcomes: dict[str, SessionFinalizationResult] = {}

    def finalize(
        self,
        session: ProtectedRunSession | None = None,
        *,
        end_reason: SessionEndReason | str | None = None,
        process_identity: ProcessIdentity | None = None,
        process_end_status: ProcessIdentityStatus | str | None = None,
        termination_result: ProcessTerminationResult | None = None,
        user_abort_termination_result: UserAbortTerminationResult | Mapping[str, Any] | None = None,
        protection_failure_termination_result: Mapping[str, Any] | None = None,
        gate_results: Iterable[EnforcementGateResult] | Any = (),
        gate_result: EnforcementGateResult | None = None,
        actions: Iterable[Any] | Any = (),
        policy_evaluations: Iterable[Any] | Any = (),
        attribution_results: Iterable[Any] | Any = (),
        enforcement_results: Iterable[Any] | Any = (),
        recovery_result: RecoveryVerificationResult | RecoveryResult | None = None,
        integrity_result: IntegrityVerificationResult | None = None,
        sensors: Iterable[Any] | None = None,
        evidence_store: RawEvidenceStore | None = None,
        active_policy: ActivePolicySnapshot | Any | None = None,
        checkpoint: Any | None = None,
        launch_context: Any | None = None,
        workspace_lease: WorkspaceLease | None = None,
        lease_manager: WorkspaceLeaseManager | None = None,
        limitations: Iterable[str] = (),
        run_classification: RunClassification | str | None = None,
        prior_session_id: str | None = None,
        agent_exit_code: int | None = None,
        agent_end_observed_at: datetime | None = None,
        agent_end_verification: str | None = None,
        agent_output_observation: Any | None = None,
    ) -> SessionFinalizationResult:
        session = session or self.session
        if not isinstance(session, ProtectedRunSession):
            raise FinalizationError("session must be a ProtectedRunSession")
        if gate_result is not None:
            gate_results = (gate_result, *(_items(gate_results, "results")))
        gates = tuple(item for item in _items(gate_results, "results") if isinstance(item, EnforcementGateResult))
        action_items = tuple(_items(actions, "actions"))
        policy_items = tuple(_items(policy_evaluations, "results"))
        attribution_items = tuple(item for item in _items(attribution_results, "results") if isinstance(item, AttributionResult))
        enforcement_items = tuple(item for item in _items(enforcement_results, "results"))
        if not enforcement_items:
            enforcement_items = gates
        elif not gates:
            # The application service historically passed Gate results through
            # ``enforcement_results``. Keep the action-level correlation
            # authoritative regardless of which equivalent input name a
            # caller used.
            gates = tuple(
                item for item in enforcement_items if isinstance(item, EnforcementGateResult)
            )
        limitations = tuple(limitations)
        store = evidence_store or self.evidence_store
        sensors_to_stop = tuple(self.sensors if sensors is None else sensors)
        lease = workspace_lease or self.workspace_lease
        manager = lease_manager or self.lease_manager

        reason, target_status, additional_limits = self._resolve_terminal_outcome(
            session,
            end_reason=end_reason,
            process_identity=process_identity,
            process_end_status=process_end_status,
            termination_result=termination_result,
        )
        all_limitations = [redact_text(str(item)) for item in limitations] + [redact_text(str(item)) for item in additional_limits]
        if recovery_result is not None:
            all_limitations.append("RECOVERY_CONTROLLED_EVENTS_NOT_REINTERPRETED_AS_AGENT_ACTION")

        session_directory = self._session_directory(session, store, self.bundle_committer, self.control_root)
        committer = self.bundle_committer or EvidenceBundleCommitter(session_directory)
        if not self._has_result_inputs(
            end_reason=end_reason,
            termination_result=termination_result,
            user_abort_termination_result=user_abort_termination_result,
            protection_failure_termination_result=protection_failure_termination_result,
            gate_results=gates,
            actions=action_items,
            policy_evaluations=policy_items,
            attribution_results=attribution_items,
            enforcement_results=enforcement_items,
            recovery_result=recovery_result,
            integrity_result=integrity_result,
            active_policy=active_policy,
            checkpoint=checkpoint,
            limitations=limitations,
            run_classification=run_classification,
            prior_session_id=prior_session_id,
        ):
            existing = self._reuse_committed(session, committer)
            if existing is not None:
                self._outcomes[session.session_id] = existing
                return existing

        sensor_summaries, sensor_limits = self._stop_sensors(sensors_to_stop)
        all_limitations.extend(sensor_limits)
        store = store or RawEvidenceStore(session_directory / "evidence" / "raw-evidence.jsonl", session_id=session.session_id)
        terminal_at = session.ended_at or self.clock()
        try:
            index = store.build_index()
            seal = store.seal(sealed_at=terminal_at)
        except Exception as error:
            all_limitations.append("EVIDENCE_SEAL_FAILED")
            raise FinalizationError("Raw Evidence finalization failed") from error

        if not session.is_terminal:
            try:
                session.transition(target_status, at=terminal_at, end_reason=reason)
            except Exception as error:
                raise FinalizationError("session terminal transition failed") from error
        else:
            if session.end_reason is None:
                session.end_reason = reason
            reason = session.end_reason or reason
            target_status = session.status
            terminal_at = session.ended_at or terminal_at

        lease_limits = self._release_lease(manager, lease, session)
        all_limitations.extend(lease_limits)
        all_limitations = list(dict.fromkeys(str(item) for item in all_limitations if str(item)))

        policy_mappings = tuple(self._policy_mapping(item) for item in policy_items)
        attribution_mappings = tuple(self._attribution_mapping(item) for item in attribution_items)
        enforcement_mappings = tuple(self._enforcement_mapping(item) for item in enforcement_items)
        if termination_result is not None:
            enforcement_mappings += ({
                "action_id": gates[0].action_id if gates else None,
                "enforcement_action": _value(termination_result.action),
                "enforcement_decision": _value(termination_result.decision),
                "execution_result": _value(termination_result.execution_result),
                "route": _value(termination_result.route),
                "termination_id": termination_result.termination_id,
            },)
        action_outcomes, correlation_limits = self._action_outcomes(
            action_items,
            policy_items,
            attribution_items,
            gates,
            termination_result,
            recovery_result,
        )
        all_limitations.extend(correlation_limits)
        all_limitations = list(dict.fromkeys(all_limitations))
        process_mapping = self._termination_mapping(termination_result)
        user_abort_mapping = self._user_abort_mapping(user_abort_termination_result)
        protection_failure_mapping = self._protection_failure_mapping(
            protection_failure_termination_result
        )
        recovery_mapping, integrity_mapping = self._recovery_mappings(recovery_result, integrity_result)
        policy_mapping = self._policy_binding(session, active_policy, gates, policy_items)
        evidence_references, evidence_artifacts = self._evidence_references(
            session_directory,
            store,
            seal,
            index,
            active_policy,
            checkpoint,
        )
        generated_at = terminal_at
        started_finalization = self.clock()
        review_required = self._review_required(
            action_outcomes,
            enforcement_mappings,
            recovery_mapping,
            integrity_mapping,
            sensor_summaries,
            all_limitations,
        )
        result_id = str(uuid5(NAMESPACE_URL, f"{session.session_id}:{RESULT_SCHEMA_VERSION}"))
        agent_execution: dict[str, Any] | None = None
        if any(
            value is not None
            for value in (agent_exit_code, agent_end_observed_at, agent_end_verification, agent_output_observation)
        ):
            agent_execution = {
                "agent_end_observed_at": agent_end_observed_at,
                "agent_end_verification": agent_end_verification,
                "agent_exit_code": agent_exit_code,
            }
            if agent_output_observation is not None:
                if hasattr(agent_output_observation, "to_mapping"):
                    agent_execution["output_observation"] = agent_output_observation.to_mapping()
                elif isinstance(agent_output_observation, Mapping):
                    agent_execution["output_observation"] = dict(agent_output_observation)
        result = SessionResult(
            schema_version=RESULT_SCHEMA_VERSION,
            result_id=result_id,
            aia_session_id=session.session_id,
            agent_native_session_id=session.agent_native_session_id,
            workspace=str(session.workspace),
            agent=session.agent,
            mode=session.mode,
            policy=policy_mapping,
            created_at=session.created_at,
            started_at=session.started_at,
            ended_at=terminal_at,
            session_status=session.status,
            session_end_reason=reason,
            sensor_summary=tuple(item.to_mapping() for item in sensor_summaries),
            action_outcomes=action_outcomes,
            policy_evaluations=policy_mappings,
            attribution_results=attribution_mappings,
            enforcement_results=enforcement_mappings,
            process_termination_result=process_mapping,
            user_abort_termination_result=user_abort_mapping,
            protection_failure_termination_result=protection_failure_mapping,
            recovery_result=recovery_mapping,
            integrity_result=integrity_mapping,
            limitations=tuple(dict.fromkeys(all_limitations)),
            evidence_references=tuple(evidence_references),
            generated_at=generated_at,
            finalization_started_at=started_finalization,
            finalization_completed_at=self.clock(),
            finalization_duration_ms=max(0.0, (self.clock() - started_finalization).total_seconds() * 1000),
            review_required=review_required,
            run_classification=run_classification,
            prior_session_id=prior_session_id,
            agent_execution=agent_execution,
        )
        report_text = self.report_generator.render(result)
        audit_records = self._audit_records(
            session,
            result,
            active_policy=active_policy,
            checkpoint=checkpoint,
            lease=lease,
            launch_context=launch_context,
            actions=action_items,
            policy_evaluations=policy_items,
            attribution_results=attribution_items,
            gates=gates,
            termination_result=termination_result,
            user_abort_termination_result=user_abort_termination_result,
            protection_failure_termination_result=protection_failure_termination_result,
            recovery_result=recovery_result,
            integrity_result=integrity_result or (recovery_result.integrity if isinstance(recovery_result, RecoveryVerificationResult) else None),
            sensor_summaries=sensor_summaries,
        )
        extra_artifacts = self._extra_artifacts(session_directory, active_policy, checkpoint)
        try:
            bundle = committer.commit(
                result,
                audit_bytes=audit_jsonl(audit_records),
                report_bytes=report_text.encode("utf-8"),
                evidence_artifacts=evidence_artifacts,
                extra_artifacts=extra_artifacts,
                committed_at=terminal_at,
            )
        except ResultAlreadyCommittedConflict:
            raise
        except Exception as error:
            raise FinalizationError("Evidence Bundle commit failed") from error
        verification = EvidenceBundleVerifier().verify(bundle.result_directory)
        if bundle.reused:
            existing = self._reuse_committed(session, committer)
            if existing is None:
                raise FinalizationError("reused Evidence Bundle cannot be loaded")
            self._outcomes[session.session_id] = existing
            return existing
        final = SessionFinalizationResult(
            result=result,
            audit_records=order_audit_records(audit_records),
            bundle=bundle,
            bundle_verification=verification,
            evidence_seal=seal,
            report_text=report_text,
        )
        self._outcomes[session.session_id] = final
        return final

    @staticmethod
    def _has_result_inputs(
        *,
        end_reason: SessionEndReason | str | None,
        termination_result: ProcessTerminationResult | None,
        user_abort_termination_result: UserAbortTerminationResult | Mapping[str, Any] | None,
        protection_failure_termination_result: Mapping[str, Any] | None,
        gate_results: tuple[EnforcementGateResult, ...],
        actions: tuple[Any, ...],
        policy_evaluations: tuple[Any, ...],
        attribution_results: tuple[AttributionResult, ...],
        enforcement_results: tuple[Any, ...],
        recovery_result: RecoveryVerificationResult | RecoveryResult | None,
        integrity_result: IntegrityVerificationResult | None,
        active_policy: Any | None,
        checkpoint: Any | None,
        limitations: Iterable[str],
        run_classification: RunClassification | str | None,
        prior_session_id: str | None,
    ) -> bool:
        return any(
            (
                end_reason is not None,
                termination_result is not None,
                user_abort_termination_result is not None,
                protection_failure_termination_result is not None,
                bool(gate_results),
                bool(actions),
                bool(policy_evaluations),
                bool(attribution_results),
                bool(enforcement_results),
                recovery_result is not None,
                integrity_result is not None,
                active_policy is not None,
                checkpoint is not None,
                bool(tuple(limitations)),
                run_classification is not None,
                prior_session_id is not None,
            )
        )

    def _resolve_terminal_outcome(
        self,
        session: ProtectedRunSession,
        *,
        end_reason: SessionEndReason | str | None,
        process_identity: ProcessIdentity | None,
        process_end_status: ProcessIdentityStatus | str | None,
        termination_result: ProcessTerminationResult | None,
    ) -> tuple[SessionEndReason, SessionStatus, tuple[str, ...]]:
        if session.is_terminal and session.end_reason is not None:
            return session.end_reason, session.status, ()
        if session.status is SessionStatus.COMPLETED:
            return SessionEndReason.AGENT_EXITED, SessionStatus.COMPLETED, ()
        if session.status is SessionStatus.ABORTED:
            return SessionEndReason.USER_ABORT, SessionStatus.ABORTED, ()
        if session.status is SessionStatus.FAILED:
            return SessionEndReason.PROTECTION_FAILURE, SessionStatus.FAILED, ()
        requested = SessionEndReason(end_reason) if end_reason is not None else None
        termination_ok = self._termination_succeeded(termination_result)
        if requested is SessionEndReason.SECURITY_CONTAINMENT or termination_ok:
            if not termination_ok:
                return SessionEndReason.PROTECTION_FAILURE, SessionStatus.FAILED, ("CONTAINMENT_NOT_CONFIRMED",)
            return SessionEndReason.SECURITY_CONTAINMENT, SessionStatus.ABORTED, ()
        if requested is SessionEndReason.USER_ABORT:
            return requested, SessionStatus.ABORTED, ()
        if requested is SessionEndReason.PROTECTION_FAILURE:
            return requested, SessionStatus.FAILED, ()
        status = self._process_end_status(process_identity, process_end_status)
        if status is ProcessIdentityStatus.LIVE_MATCH:
            raise FinalizationRefused("LIVE_MATCH: normal completion cannot be claimed")
        if status is ProcessIdentityStatus.OWNER_UNVERIFIABLE:
            return SessionEndReason.PROTECTION_FAILURE, SessionStatus.FAILED, ("OWNER_UNVERIFIABLE",)
        if status not in {ProcessIdentityStatus.PROCESS_GONE, ProcessIdentityStatus.PID_REUSED}:
            raise FinalizationRefused(f"process end cannot be verified: {status.value}")
        return SessionEndReason.AGENT_EXITED, SessionStatus.COMPLETED, ()

    def _process_end_status(
        self,
        process_identity: ProcessIdentity | None,
        process_end_status: ProcessIdentityStatus | str | None,
    ) -> ProcessIdentityStatus:
        if process_end_status is not None:
            return ProcessIdentityStatus(process_end_status)
        if process_identity is None:
            raise FinalizationRefused("PROCESS_END_VERIFICATION_REQUIRED")
        return inspect_process_identity(
            process_identity,
            process_factory=self.process_factory or __import__("psutil").Process,
        )[0]

    @staticmethod
    def _termination_succeeded(result: ProcessTerminationResult | None) -> bool:
        return bool(
            result is not None
            and result.action is EnforcementAction.TERMINATED
            and result.execution_result is EnforcementExecutionResult.SUCCEEDED
            and result.outcome in {
                ProcessTerminationOutcome.TERMINATED,
                ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT,
            }
        )

    @staticmethod
    def _session_directory(
        session: ProtectedRunSession,
        store: RawEvidenceStore | None,
        committer: EvidenceBundleCommitter | None,
        control_root: Path | None,
    ) -> Path:
        if store is not None:
            return store.path.parent.parent
        if committer is not None:
            return committer.session_directory
        if control_root is not None:
            return control_root / "sessions" / session.session_id
        raise FinalizationError("Evidence Store or Bundle Committer is required")

    def _reuse_committed(
        self,
        session: ProtectedRunSession,
        committer: EvidenceBundleCommitter,
    ) -> SessionFinalizationResult | None:
        verification = EvidenceBundleVerifier().verify(committer.result_directory)
        if not verification.is_valid:
            return None
        result_path = committer.result_directory / "result.json"
        try:
            result = SessionResult.from_mapping(__import__("json").loads(result_path.read_text(encoding="utf-8")))
            report_text = (committer.result_directory / "security-report.md").read_text(encoding="utf-8")
            evidence_store = self.evidence_store or RawEvidenceStore(
                committer.session_directory / "evidence" / "raw-evidence.jsonl",
                session_id=session.session_id,
            )
            seal = evidence_store.seal()
        except Exception:
            return None
        return SessionFinalizationResult(
            result=result,
            audit_records=(),
            bundle=BundleCommitResult(
                session.session_id,
                result.result_id,
                committer.result_directory,
                committer.result_directory / "commit.json",
                committer.result_directory / "evidence-manifest.json",
                verification.result_id or "",
                reused=True,
            ),
            bundle_verification=verification,
            evidence_seal=seal,
            report_text=report_text,
        )

    def _stop_sensors(self, sensors: Iterable[Any]) -> tuple[tuple[SensorSummary, ...], tuple[str, ...]]:
        summaries: list[SensorSummary] = []
        limitations: list[str] = []
        for sensor in sensors:
            before = self._sensor_health(sensor)
            try:
                context = sensor.stop()
                after = getattr(context, "health", None) or self._sensor_health(sensor)
                final_state = _status(getattr(context, "status", None) or getattr(after, "status", None)) or "UNKNOWN"
            except Exception as error:
                after = self._sensor_health(sensor)
                final_state = _status(getattr(after, "status", None)) or "FAILED"
                limitations.append(f"SENSOR_STOP_FAILED:{getattr(before, 'sensor', type(sensor).__name__)}")
                if final_state != SensorStatus.FAILED.value:
                    final_state = SensorStatus.FAILED.value
                _ = error
            sensor_name = _status(getattr(before, "sensor", None)) or type(sensor).__name__
            before_status = _status(getattr(before, "status", None)) or "UNKNOWN"
            reason = _safe_reason(getattr(before, "reason", None))
            failed_at = getattr(before, "checked_at", None) if before_status == SensorStatus.FAILED.value else None
            final_checked_at = getattr(after, "checked_at", None)
            summaries.append(SensorSummary(sensor_name, before_status, final_state, reason, failed_at, final_checked_at))
            if before_status == SensorStatus.FAILED.value:
                limitations.append(f"SENSOR_RUNTIME_FAILED:{sensor_name}")
        return tuple(summaries), tuple(limitations)

    @staticmethod
    def _sensor_health(sensor: Any) -> SensorHealth:
        health = getattr(sensor, "runtime_health_before_stop", None)
        if callable(health):
            health = health()
        if not isinstance(health, SensorHealth):
            health = getattr(sensor, "health", None)
            if callable(health):
                health = health()
        if not isinstance(health, SensorHealth):
            status = getattr(sensor, "status", SensorStatus.STOPPED)
            return SensorHealth(getattr(sensor, "source", "FILESYSTEM_WATCHER"), status, _now_utc())
        return health

    @staticmethod
    def _release_lease(
        manager: WorkspaceLeaseManager | None,
        lease: WorkspaceLease | None,
        session: ProtectedRunSession,
    ) -> tuple[str, ...]:
        if manager is None or lease is None:
            return ()
        try:
            if lease.session_id != session.session_id or lease.workspace != session.workspace:
                return ("LEASE_RELEASE_FAILED",)
            if not lease.artifact_path.exists():
                return ()
            manager.release(lease)
            return ()
        except Exception:
            return ("LEASE_RELEASE_FAILED",)

    def _policy_binding(self, session: ProtectedRunSession, active_policy: Any, gates: tuple[Any, ...], evaluations: tuple[Any, ...]) -> dict[str, Any]:
        fingerprint = getattr(active_policy, "sha256", None)
        if fingerprint is None and gates:
            fingerprint = gates[0].policy_fingerprint
        profile = getattr(active_policy, "profile", None)
        if profile is None and evaluations:
            profile = getattr(evaluations[0], "policy_profile", None)
        return {
            "fingerprint": fingerprint,
            "policy_id": getattr(active_policy, "policy_id", session.policy_id),
            "policy_version": getattr(active_policy, "policy_version", session.policy_version),
            "profile": _value(profile) if profile is not None else None,
        }

    @staticmethod
    def _policy_mapping(value: Any) -> dict[str, Any]:
        return {
            "action_id": getattr(value, "action_id", None),
            "asset_type": _value(getattr(value, "asset_type", None)),
            "audit_record": getattr(value, "audit_record", None),
            "evaluated_at": _dt(getattr(value, "evaluated_at", None)),
            "matched_asset_types": [
                _value(getattr(getattr(item, "policy_evaluation", None), "asset_type", None))
                for item in getattr(value, "path_evaluations", ())
                if getattr(getattr(item, "policy_evaluation", None), "asset_type", None) is not None
            ] + ([_value(getattr(value, "asset_type"))] if getattr(value, "asset_type", None) is not None else []),
            "matched_rule_ids": list(getattr(value, "matched_rule_ids", ())),
            "operation": _value(getattr(value, "operation", None)),
            "operation_effect": _value(getattr(value, "operation_effect", None)),
            "path": getattr(value, "path", None),
            "policy_decision": _value(getattr(value, "policy_decision", None)),
            "policy_id": getattr(value, "policy_id", None),
            "policy_profile": _value(getattr(value, "policy_profile", None)),
            "policy_version": getattr(value, "policy_version", None),
            "reason": _safe_reason(getattr(value, "reason", None)),
            "stage": _value(getattr(value, "stage", None)),
        }

    @staticmethod
    def _attribution_mapping(value: AttributionResult) -> dict[str, Any]:
        return {
            "action_id": value.action_id,
            "agent_native_session_id": value.agent_native_session_id,
            "grade": _value(value.grade),
            "limitations": list(value.limitations),
            "reason": _safe_reason(value.reason),
            "reason_code": _value(value.reason_code),
            "supporting_evidence_ids": list(value.supporting_evidence_ids),
            "tool_use_id": value.tool_use_id,
            "turn_id": value.turn_id,
        }

    @staticmethod
    def _enforcement_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, EnforcementGateResult):
            return {
                "action_id": value.action_id,
                "attribution_grade": _value(value.attribution_grade),
                "enforcement_action": _value(value.action),
                "enforcement_decision": _value(value.decision),
                "execution_result": _value(value.execution_result),
                "failure_reasons": [_safe_reason(item) for item in value.failure_reasons],
                "hook_trust_status": _value(value.hook_trust_status),
                "lease_status": value.lease_status,
                "policy_decision": _value(value.policy_decision),
                "policy_fingerprint": value.policy_fingerprint,
                "route": _value(value.route),
                "sensor_statuses": [
                    {"sensor": _value(item.sensor), "status": _value(item.status), "reason": _safe_reason(item.reason)}
                    for item in value.sensor_statuses
                ],
                "stage": _value(value.stage),
                **(
                    {"confirmation_basis": dict(value.confirmation_basis)}
                    if value.confirmation_basis is not None
                    else {}
                ),
            }
        return {"type": type(value).__name__, "reason": _safe_reason(getattr(value, "reason", None))}

    @staticmethod
    def _termination_mapping(value: ProcessTerminationResult | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "action": _value(value.action),
            "aia_session_id": value.aia_session_id,
            "decision": _value(value.decision),
            "execution_result": _value(value.execution_result),
            "launch_id": value.launch_id,
            "outcome": _value(value.outcome),
            "process_results": [
                {
                    "final_identity_status": _value(getattr(item, "final_identity_status", None)),
                    "outcome": _value(getattr(item, "outcome", None)),
                    "process_identity": _identity(getattr(item, "process_identity", None)),
                    "reason": _safe_reason(getattr(item, "reason", None)),
                    "role": getattr(item, "role", None),
                }
                for item in value.process_results
            ],
            "reason": _safe_reason(value.reason),
            "route": _value(value.route),
            "termination_completed_at": value.termination_completed_at,
            "termination_duration_ms": value.termination_duration_ms,
            "termination_id": value.termination_id,
            "termination_requested_at": value.termination_requested_at,
        }

    @staticmethod
    def _user_abort_mapping(
        value: UserAbortTerminationResult | Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, UserAbortTerminationResult):
            return value.to_mapping()
        if isinstance(value, Mapping):
            mapping = {str(key): value[key] for key in value}
            if mapping.get("status") not in {"SUCCEEDED", "FAILED"}:
                raise FinalizationError("user abort status is invalid")
            if mapping.get("outcome") not in {"TERMINATED", "ALREADY_EXITED", "FAILED"}:
                raise FinalizationError("user abort outcome is invalid")
            if mapping.get("status") == "SUCCEEDED" and mapping.get("verified_tree_gone") is not True:
                raise FinalizationError("successful user abort requires verified_tree_gone")
            return mapping
        raise FinalizationError("user_abort_termination_result is invalid")

    @staticmethod
    def _protection_failure_mapping(
        value: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise FinalizationError("protection_failure_termination_result is invalid")
        mapping = {str(key): value[key] for key in value}
        if mapping.get("status") not in {"SUCCEEDED", "FAILED"}:
            raise FinalizationError("protection failure termination status is invalid")
        if mapping.get("outcome") not in {"TERMINATED", "ALREADY_EXITED", "FAILED"}:
            raise FinalizationError("protection failure termination outcome is invalid")
        if mapping.get("status") == "SUCCEEDED" and mapping.get("verified_tree_gone") is not True:
            raise FinalizationError(
                "successful protection failure termination requires verified_tree_gone"
            )
        if mapping.get("control") != "PROTECTION_FAILURE":
            raise FinalizationError("protection failure termination control is invalid")
        return mapping

    @staticmethod
    def _recovery_mappings(
        recovery: RecoveryVerificationResult | RecoveryResult | None,
        integrity: IntegrityVerificationResult | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if isinstance(recovery, RecoveryVerificationResult):
            integrity = recovery.integrity
            recovery = recovery.recovery
        recovery_mapping = None
        if isinstance(recovery, RecoveryResult):
            recovery_mapping = {
                "action_id": recovery.action_id,
                "attempted_operation_count": recovery.attempted_operation_count,
                "checkpoint_id": recovery.checkpoint_id,
                "failed_paths": list(recovery.failed_paths),
                "failed_operation_count": recovery.failed_operation_count,
                "planned_operation_count": recovery.planned_operation_count,
                "reason": _safe_reason(recovery.reason),
                "recovery_id": recovery.recovery_id,
                "recovery_status": _value(recovery.recovery_status),
                "restored_paths": list(recovery.restored_paths),
                "termination_id": recovery.termination_id,
            }
        integrity_mapping = None
        if isinstance(integrity, IntegrityVerificationResult):
            integrity_mapping = {
                "changed_paths": list(integrity.changed_paths),
                "checkpoint_id": integrity.checkpoint_id,
                "integrity_status": _value(integrity.integrity_status),
                "missing_paths": list(integrity.missing_paths),
                "reason": _safe_reason(integrity.reason),
                "unexpected_paths": list(integrity.unexpected_paths),
                "verification_errors": list(integrity.verification_errors),
            }
        return recovery_mapping, integrity_mapping

    @staticmethod
    def _action_outcomes(
        actions: tuple[Any, ...],
        policies: tuple[Any, ...],
        attributions: tuple[AttributionResult, ...],
        gates: tuple[EnforcementGateResult, ...],
        termination: ProcessTerminationResult | None,
        recovery: RecoveryVerificationResult | RecoveryResult | None,
    ) -> tuple[tuple[ActionOutcomeRecord, ...], tuple[str, ...]]:
        policy_by_id: dict[str | None, list[Any]] = {}
        for item in policies:
            policy_by_id.setdefault(getattr(item, "action_id", None), []).append(item)
        attribution_by_id = {item.action_id: item for item in attributions}
        gate_by_id = {item.action_id: item for item in gates}
        recovery_id = getattr(getattr(recovery, "recovery", recovery), "recovery_id", None)
        termination_id = getattr(termination, "termination_id", None)
        records: list[ActionOutcomeRecord] = []
        limitations: list[str] = []
        action_ids = {getattr(item, "action_id", None) for item in actions}
        for collection in (policies, attributions, gates):
            for item in collection:
                action_id = getattr(item, "action_id", None)
                if action_id not in action_ids:
                    limitations.append(f"UNRESOLVED_CORRELATION:{action_id}")
        for action in actions:
            action_id = action.action_id
            policy_values = policy_by_id.get(action_id, [])
            policy = policy_values[0] if policy_values else None
            attribution = attribution_by_id.get(action_id)
            gate = gate_by_id.get(action_id)
            asset_types: list[str] = []
            for policy_value in policy_values:
                for value in getattr(policy_value, "path_evaluations", ()):
                    asset = getattr(getattr(value, "policy_evaluation", None), "asset_type", None)
                    if asset is not None and _value(asset) not in asset_types:
                        asset_types.append(_value(asset))
                asset = getattr(policy_value, "asset_type", None)
                if asset is not None and _value(asset) not in asset_types:
                    asset_types.append(_value(asset))
            effective_action = getattr(gate, "action", None)
            effective_execution = getattr(gate, "execution_result", None)
            effective_route = getattr(gate, "route", None)
            if termination is not None and gate is not None and termination.aia_session_id == action.aia_session_id:
                effective_action = termination.action
                effective_execution = termination.execution_result
                effective_route = termination.route
            target: dict[str, Any] = {
                "canonical_path": action.canonical_path,
                "destination_path": action.destination_path,
                "source_path": action.source_path,
                "target_kind": _value(action.target_kind),
            }
            if action.raw_command is not None:
                target["command_fingerprint"] = _fingerprint(action.raw_command)
            matched_rule_ids: list[str] = []
            for policy_value in policy_values:
                for rule_id in getattr(policy_value, "matched_rule_ids", ()):
                    if rule_id not in matched_rule_ids:
                        matched_rule_ids.append(rule_id)
            records.append(
                ActionOutcomeRecord(
                    action_id=action_id,
                    operation=_value(action.operation),
                    target=target,
                    observation_stage=_value(action.stage),
                    evidence_ids=tuple(action.evidence_ids),
                    policy_decision=_value(getattr(policy, "policy_decision", None)),
                    operation_effect=_value(getattr(policy, "operation_effect", None)),
                    matched_rule_ids=tuple(matched_rule_ids),
                    matched_asset_types=tuple(asset_types),
                    attribution_grade=_value(getattr(attribution, "grade", None)),
                    attribution_reason=_safe_reason(getattr(attribution, "reason", None)),
                    enforcement_decision=_value(getattr(gate, "decision", None)),
                    enforcement_route=_value(effective_route),
                    enforcement_action=_value(effective_action),
                    execution_result=_value(effective_execution),
                    related_termination_id=termination_id if gate is not None else None,
                    related_recovery_id=recovery_id if gate is not None else None,
                    limitations=tuple(action.limitations),
                )
            )
        return tuple(records), tuple(dict.fromkeys(limitations))

    @staticmethod
    def _review_required(
        actions: tuple[ActionOutcomeRecord, ...],
        enforcement: tuple[Mapping[str, Any], ...],
        recovery: Mapping[str, Any] | None,
        integrity: Mapping[str, Any] | None,
        sensors: tuple[SensorSummary, ...],
        limitations: Iterable[str],
    ) -> bool:
        return bool(
            any(item.policy_decision == "INDETERMINATE" or (item.policy_decision == "VIOLATION" and item.enforcement_decision == "REFUSE") for item in actions)
            or any(item.get("execution_result") == "FAILED" for item in enforcement)
            or recovery is not None and recovery.get("recovery_status") in {"FAILED", "REFUSED", "RECOVERY_UNAVAILABLE"}
            or integrity is not None and integrity.get("integrity_status") == "FAILED"
            or any(item.runtime_health_before_stop == "FAILED" for item in sensors)
            or tuple(limitations)
        )

    @staticmethod
    def _evidence_references(
        session_directory: Path,
        store: RawEvidenceStore,
        seal: EvidenceSeal,
        index: Any,
        active_policy: Any,
        checkpoint: Any,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        files: list[tuple[str, str, Path]] = [
            ("RAW_EVIDENCE", seal.raw_evidence_relative_path, store.path),
            ("EVIDENCE_SEAL", _path_relative(session_directory, store.seal_path), store.seal_path),
            ("EVIDENCE_INDEX", _path_relative(session_directory, store.index_path), store.index_path),
        ]
        if active_policy is not None and getattr(active_policy, "artifact_path", None) is not None:
            files.append(("ACTIVE_POLICY", _path_relative(session_directory, active_policy.artifact_path), active_policy.artifact_path))
        if checkpoint is not None:
            for name, path in (("CHECKPOINT_MANIFEST", getattr(checkpoint, "manifest_path", None)), ("CHECKPOINT_METADATA", getattr(checkpoint, "metadata_path", None))):
                if path is not None:
                    files.append((name, _path_relative(session_directory, Path(path)), Path(path)))
        references: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for artifact_type, relative, path in files:
            if not path.is_file():
                continue
            data = path.read_bytes()
            item = {
                "artifact_type": artifact_type,
                "byte_size": len(data),
                "relative_path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            references.append(item)
            artifacts.append({"path": path, "relative_path": relative, "type": artifact_type})
        return tuple(references), tuple(artifacts)

    @staticmethod
    def _extra_artifacts(session_directory: Path, active_policy: Any, checkpoint: Any) -> tuple[dict[str, Any], ...]:
        # Policy/checkpoint artifacts are included by _evidence_references; this
        # method intentionally returns no Workspace snapshot files.
        return ()

    def _audit_records(
        self,
        session: ProtectedRunSession,
        result: SessionResult,
        *,
        active_policy: Any,
        checkpoint: Any,
        lease: WorkspaceLease | None,
        launch_context: Any,
        actions: tuple[Any, ...],
        policy_evaluations: tuple[Any, ...],
        attribution_results: tuple[AttributionResult, ...],
        gates: tuple[EnforcementGateResult, ...],
        termination_result: ProcessTerminationResult | None,
        user_abort_termination_result: UserAbortTerminationResult | Mapping[str, Any] | None,
        protection_failure_termination_result: Mapping[str, Any] | None,
        recovery_result: RecoveryVerificationResult | RecoveryResult | None,
        integrity_result: IntegrityVerificationResult | None,
        sensor_summaries: tuple[SensorSummary, ...],
    ) -> tuple[AuditRecord, ...]:
        records: list[AuditRecord] = []

        def add(event: AuditEventType, occurred_at: datetime | None, entity_type: str, entity_id: str, source: str, *, action_id: str | None = None, reason: str | None = None, summary: str = "") -> None:
            if occurred_at is None:
                return
            audit_id = str(uuid5(NAMESPACE_URL, f"{session.session_id}:{event.value}:{entity_type}:{entity_id}:{occurred_at.isoformat()}"))
            records.append(AuditRecord(audit_id, session.session_id, occurred_at, event, entity_type, entity_id, source, action_id=action_id, reason_code=reason, summary=redact_text(summary)))

        add(AuditEventType.SESSION_CREATED, session.created_at, "SESSION", session.session_id, "session")
        add(AuditEventType.PROTECTION_STARTED, session.started_at, "SESSION", session.session_id, "session")
        add(AuditEventType.POLICY_FROZEN, _dt(getattr(active_policy, "frozen_at", None)), "POLICY", getattr(active_policy, "policy_id", session.policy_id), "active-policy")
        add(AuditEventType.LEASE_ACQUIRED, _dt(getattr(lease, "acquired_at", None)), "LEASE", session.session_id, "lease")
        add(AuditEventType.CHECKPOINT_CREATED, _dt(getattr(checkpoint, "created_at", None)), "CHECKPOINT", getattr(checkpoint, "checkpoint_id", "checkpoint"), "checkpoint")
        add(AuditEventType.AGENT_LAUNCHED, _dt(getattr(launch_context, "spawned_at", None)), "LAUNCH", getattr(launch_context, "launch_id", "launch"), "launcher")
        for action in actions:
            add(AuditEventType.ACTION_OBSERVED, _dt(getattr(action, "observed_at", None)), "ACTION", action.action_id, "canonical-action", action_id=action.action_id, summary=f"{_value(action.operation)} action")
        for evaluation in policy_evaluations:
            add(AuditEventType.POLICY_EVALUATED, _dt(getattr(evaluation, "evaluated_at", None)), "POLICY_EVALUATION", evaluation.action_id, "policy", action_id=evaluation.action_id, reason=_value(getattr(evaluation, "policy_decision", None)))
        for attribution in attribution_results:
            add(AuditEventType.ATTRIBUTION_EVALUATED, _dt(getattr(attribution, "evaluated_at", None)), "ATTRIBUTION", attribution.action_id, "attribution", action_id=attribution.action_id, reason=_value(getattr(attribution, "grade", None)))
        for gate in gates:
            add(AuditEventType.ENFORCEMENT_DECIDED, gate.checked_at, "ENFORCEMENT", gate.action_id, "enforcement", action_id=gate.action_id, reason=_value(gate.decision))
        if termination_result is not None:
            add(AuditEventType.ENFORCEMENT_EXECUTED, termination_result.termination_requested_at, "TERMINATION", termination_result.termination_id, "process-manager")
            add(AuditEventType.PROCESS_TERMINATED, termination_result.termination_completed_at, "TERMINATION", termination_result.termination_id, "process-manager", reason=_value(termination_result.outcome))
        if user_abort_termination_result is not None:
            abort_mapping = self._user_abort_mapping(user_abort_termination_result)
            abort_completed_at = (
                user_abort_termination_result.completed_at
                if isinstance(user_abort_termination_result, UserAbortTerminationResult)
                else _dt_from_text(abort_mapping.get("completed_at"))
            )
            add(
                AuditEventType.USER_ABORT_EXECUTED,
                abort_completed_at,
                "USER_ABORT",
                str(abort_mapping.get("termination_id", "user-abort")),
                "launcher",
                reason=str(abort_mapping.get("status", "UNKNOWN")),
            )
        if protection_failure_termination_result is not None:
            failure_mapping = self._protection_failure_mapping(
                protection_failure_termination_result
            )
            assert failure_mapping is not None
            add(
                AuditEventType.PROTECTION_FAILURE_EXECUTED,
                _dt_from_text(failure_mapping.get("completed_at")),
                "PROTECTION_FAILURE",
                str(failure_mapping.get("termination_id", "protection-failure")),
                "launcher",
                reason=str(failure_mapping.get("reason", "UNKNOWN")),
                summary=f"status={failure_mapping.get('status', 'UNKNOWN')}",
            )
        recovery = getattr(recovery_result, "recovery", recovery_result)
        integrity = integrity_result or getattr(recovery_result, "integrity", None)
        add(AuditEventType.RECOVERY_EXECUTED, _dt(getattr(recovery, "ended_at", None)), "RECOVERY", getattr(recovery, "recovery_id", "recovery"), "recovery", action_id=getattr(recovery, "action_id", None), reason=_value(getattr(recovery, "recovery_status", None)))
        if integrity is not None and _value(getattr(integrity, "integrity_status", None)) != IntegrityStatus.NOT_CHECKED.value:
            add(AuditEventType.INTEGRITY_VERIFIED, _dt(getattr(integrity, "verified_at", None)), "INTEGRITY", getattr(integrity, "checkpoint_id", "integrity"), "integrity", reason=_value(integrity.integrity_status))
        for sensor in sensor_summaries:
            add(AuditEventType.SENSOR_HEALTH, sensor.failed_at, "SENSOR", sensor.sensor, "sensor", reason=sensor.runtime_health_before_stop)
            if sensor.final_sensor_state == SensorStatus.STOPPED.value:
                add(AuditEventType.SENSOR_STOPPED, sensor.final_checked_at, "SENSOR", sensor.sensor, "sensor")
        add(AuditEventType.SESSION_FINALIZED, result.ended_at, "SESSION", session.session_id, "finalizer", reason=result.session_end_reason.value)
        return order_audit_records(records)


def finalize_session(session: ProtectedRunSession, **kwargs: Any) -> SessionFinalizationResult:
    return SessionFinalizer(**{key: kwargs.pop(key) for key in ("evidence_store", "sensors", "lease_manager", "workspace_lease", "bundle_committer", "control_root", "report_generator", "process_factory", "clock") if key in kwargs}).finalize(session, **kwargs)


__all__ = [
    "FinalizationError",
    "FinalizationRefused",
    "SessionFinalizationResult",
    "SessionFinalizer",
    "finalize_session",
]
