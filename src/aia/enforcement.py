"""Pure Enforcement Gate decisions.

The gate combines already-produced policy and attribution facts with the
currently verifiable runtime boundary.  It never emits a hook response,
terminates a process, mutates a Session, or changes evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Callable

import psutil

from .action import NormalizedAction
from .attribution import AttributionGrade, AttributionResult
from .evidence import EvidenceSource, ObservationStage
from .process_identity import ProcessIdentity, ProcessIdentityStatus, inspect_process_identity
from .policy import PolicyDecision
from .protection import (
    ActivePolicySnapshot,
    LeaseOwnerStatus,
    ProtectionError,
    WorkspaceLease,
    WorkspaceLeaseManager,
)
from .runtime_policy import RuntimePolicyEvaluation
from .session import ProtectedRunSession, SessionMode, SessionStatus, canonicalize_workspace
from .sensors.base import SensorHealth, SensorStatus

if TYPE_CHECKING:
    from .launcher import ProtectedLaunchContext


class EnforcementDecision(StrEnum):
    CONTINUE = "CONTINUE"
    CONTAIN = "CONTAIN"
    REFUSE = "REFUSE"


class EnforcementAction(StrEnum):
    NONE = "NONE"
    BLOCKED = "BLOCKED"
    TERMINATED = "TERMINATED"


class EnforcementExecutionResult(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EnforcementRoute(StrEnum):
    NONE = "NONE"
    PRETOOL_BLOCK = "PRETOOL_BLOCK"
    PROCESS_TERMINATION = "PROCESS_TERMINATION"


class HookTrustStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    MISMATCHED = "MISMATCHED"
    UNAVAILABLE = "UNAVAILABLE"


class EnforcementReason(StrEnum):
    ACTION_CORRELATION_MISMATCH = "ACTION_CORRELATION_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    ACTIVE_POLICY_MISMATCH = "ACTIVE_POLICY_MISMATCH"
    STAGE_MISMATCH = "STAGE_MISMATCH"
    SESSION_NOT_RUNNING = "SESSION_NOT_RUNNING"
    AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT = "AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT"
    POLICY_INDETERMINATE = "POLICY_INDETERMINATE"
    ATTRIBUTION_NOT_EXACT = "ATTRIBUTION_NOT_EXACT"
    HOOK_TRUST_UNAVAILABLE = "HOOK_TRUST_UNAVAILABLE"
    ROOT_PROCESS_IDENTITY_INVALID = "ROOT_PROCESS_IDENTITY_INVALID"
    ROOT_REGISTRATION_MISMATCH = "ROOT_REGISTRATION_MISMATCH"
    LAUNCH_PROVENANCE_INVALID = "LAUNCH_PROVENANCE_INVALID"
    PROCESS_IDENTITY_MISMATCH = "PROCESS_IDENTITY_MISMATCH"
    SENSOR_UNHEALTHY = "SENSOR_UNHEALTHY"
    WORKSPACE_LEASE_INVALID = "WORKSPACE_LEASE_INVALID"
    WORKSPACE_LEASE_UNVERIFIABLE = "WORKSPACE_LEASE_UNVERIFIABLE"
    UNSUPPORTED_STAGE = "UNSUPPORTED_STAGE"
    NATIVE_SESSION_MISMATCH = "HOOK_NATIVE_SESSION_MISMATCH"
    BLOCK_CONFIRMATION_UNAVAILABLE = "BLOCK_CONFIRMATION_UNAVAILABLE"
    HOOK_ENFORCEMENT_FAILURE = "HOOK_ENFORCEMENT_FAILURE"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One independently preserved gate check."""

    name: str
    passed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("GateCheck.name must be non-empty")
        if not isinstance(self.passed, bool):
            raise ValueError("GateCheck.passed must be bool")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("GateCheck.reason must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class EnforcementGateInput:
    """Immutable facts supplied to one pure Enforcement Gate evaluation."""

    action: NormalizedAction
    policy_evaluation: RuntimePolicyEvaluation
    attribution: AttributionResult
    session: ProtectedRunSession
    active_policy: ActivePolicySnapshot
    launch_context: ProtectedLaunchContext | None
    workspace_lease: WorkspaceLease | None
    sensor_health: tuple[SensorHealth, ...] | Mapping[EvidenceSource, SensorHealth]
    hook_trust_status: HookTrustStatus | str
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, NormalizedAction):
            raise TypeError("action must be a NormalizedAction")
        if not isinstance(self.policy_evaluation, RuntimePolicyEvaluation):
            raise TypeError("policy_evaluation must be a RuntimePolicyEvaluation")
        if not isinstance(self.attribution, AttributionResult):
            raise TypeError("attribution must be an AttributionResult")
        if not isinstance(self.session, ProtectedRunSession):
            raise TypeError("session must be a ProtectedRunSession")
        if not isinstance(self.active_policy, ActivePolicySnapshot):
            raise TypeError("active_policy must be an ActivePolicySnapshot")
        object.__setattr__(self, "hook_trust_status", HookTrustStatus(self.hook_trust_status))
        if self.checked_at is not None:
            object.__setattr__(self, "checked_at", _aware_utc(self.checked_at, field_name="checked_at"))
        values: tuple[SensorHealth, ...]
        if isinstance(self.sensor_health, Mapping):
            values = tuple(self.sensor_health.values())
        else:
            values = tuple(self.sensor_health)
        if any(not isinstance(value, SensorHealth) for value in values):
            raise TypeError("sensor_health must contain SensorHealth values")
        object.__setattr__(self, "sensor_health", values)


@dataclass(frozen=True, slots=True)
class EnforcementGateResult:
    """Immutable gate outcome; actual action remains NONE until confirmed."""

    action_id: str
    aia_session_id: str
    policy_decision: PolicyDecision
    attribution_grade: AttributionGrade
    decision: EnforcementDecision
    route: EnforcementRoute
    action: EnforcementAction
    execution_result: EnforcementExecutionResult
    stage: ObservationStage
    checked_at: datetime
    gate_checks: tuple[GateCheck, ...]
    failure_reasons: tuple[str, ...]
    policy_fingerprint: str
    root_process_identity: ProcessIdentity | None
    hook_trust_status: HookTrustStatus
    sensor_statuses: tuple[SensorHealth, ...]
    lease_status: str
    latency_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.aia_session_id.strip():
            raise ValueError("gate identifiers must be non-empty")
        object.__setattr__(self, "policy_decision", PolicyDecision(self.policy_decision))
        object.__setattr__(self, "attribution_grade", AttributionGrade(self.attribution_grade))
        object.__setattr__(self, "decision", EnforcementDecision(self.decision))
        object.__setattr__(self, "route", EnforcementRoute(self.route))
        object.__setattr__(self, "action", EnforcementAction(self.action))
        object.__setattr__(self, "execution_result", EnforcementExecutionResult(self.execution_result))
        object.__setattr__(self, "stage", ObservationStage(self.stage))
        object.__setattr__(self, "checked_at", _aware_utc(self.checked_at, field_name="checked_at"))
        object.__setattr__(self, "gate_checks", tuple(self.gate_checks))
        object.__setattr__(self, "failure_reasons", tuple(self.failure_reasons))
        object.__setattr__(self, "sensor_statuses", tuple(self.sensor_statuses))
        object.__setattr__(self, "hook_trust_status", HookTrustStatus(self.hook_trust_status))
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")

    @property
    def containment_approved(self) -> bool:
        return self.decision is EnforcementDecision.CONTAIN


class EnforcementGate:
    """Fail-safe, side-effect-free authority boundary."""

    _REQUIRED_SENSORS = (
        EvidenceSource.AGENT_HOOK,
        EvidenceSource.FILESYSTEM_WATCHER,
        EvidenceSource.PROCESS_RUNTIME,
    )

    def __init__(
        self,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        process_factory: Callable[[int], Any] | None = None,
    ) -> None:
        self.lease_manager = lease_manager
        self.process_factory = process_factory

    def evaluate(self, gate_input: EnforcementGateInput) -> EnforcementGateResult:
        checked_at = gate_input.checked_at or _now_utc()
        checks: list[GateCheck] = []
        failures: list[str] = []

        def add(name: str, passed: bool, reason: str | None = None) -> None:
            check = GateCheck(name, passed, reason)
            checks.append(check)
            if not passed and reason is not None and reason not in failures:
                failures.append(reason)

        action = gate_input.action
        policy = gate_input.policy_evaluation
        attribution = gate_input.attribution
        session = gate_input.session
        snapshot = gate_input.active_policy

        action_ids = {action.action_id, policy.action_id, attribution.action_id}
        correlation_ok = len(action_ids) == 1
        add(
            "action_correlation",
            correlation_ok,
            None if correlation_ok else EnforcementReason.ACTION_CORRELATION_MISMATCH.value,
        )
        session_ids = {
            action.aia_session_id,
            policy.aia_session_id,
            attribution.aia_session_id,
            session.session_id,
            snapshot.session_id,
        }
        session_ok = len(session_ids) == 1
        add(
            "session_binding",
            session_ok,
            None if session_ok else EnforcementReason.SESSION_MISMATCH.value,
        )

        policy_ok = (
            policy.policy_id == snapshot.policy_id
            and policy.policy_version == snapshot.policy_version
            and policy.policy_profile.value == snapshot.profile.value
            and policy.active_policy_fingerprint == snapshot.sha256
        )
        add(
            "active_policy_binding",
            policy_ok,
            None if policy_ok else EnforcementReason.ACTIVE_POLICY_MISMATCH.value,
        )
        stage_ok = action.stage is policy.stage
        add(
            "stage_correlation",
            stage_ok,
            None if stage_ok else EnforcementReason.STAGE_MISMATCH.value,
        )

        # Identity and lease are still checked for every non-correlated input,
        # but a correlation failure always dominates the result.
        if not correlation_ok or not session_ok:
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
            )
        if not policy_ok:
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
            )
        if not stage_ok:
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
            )

        if policy.policy_decision is PolicyDecision.COMPLIANT:
            add("policy_decision", True)
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.CONTINUE,
                EnforcementRoute.NONE,
            )
        if policy.policy_decision is PolicyDecision.INDETERMINATE:
            add("policy_decision", False, EnforcementReason.POLICY_INDETERMINATE.value)
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
            )
        add("policy_decision", True)

        if attribution.grade is not AttributionGrade.EXACT:
            add("attribution_exact", False, EnforcementReason.ATTRIBUTION_NOT_EXACT.value)
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
            )
        add("attribution_exact", True)

        if session.status is not SessionStatus.RUNNING:
            add("session_running", False, EnforcementReason.SESSION_NOT_RUNNING.value)
            return self._result(gate_input, checked_at, checks, failures, EnforcementDecision.REFUSE, EnforcementRoute.NONE)
        add("session_running", True)
        if session.mode is not SessionMode.ENFORCE:
            add("session_mode", False, EnforcementReason.AUDIT_MODE_NO_AUTOMATIC_ENFORCEMENT.value)
            return self._result(gate_input, checked_at, checks, failures, EnforcementDecision.REFUSE, EnforcementRoute.NONE)
        add("session_mode", True)

        hook_ok = gate_input.hook_trust_status is HookTrustStatus.VERIFIED
        add("hook_trust", hook_ok, None if hook_ok else EnforcementReason.HOOK_TRUST_UNAVAILABLE.value)
        root_ok, root_reason = self._verify_root(gate_input.launch_context, session)
        add("root_process_identity", root_ok, root_reason)
        attribution_identity_ok, attribution_identity_reason = self._verify_attribution_identity(
            attribution,
            gate_input.launch_context,
        )
        add(
            "attribution_process_identity",
            attribution_identity_ok,
            attribution_identity_reason,
        )
        launch_ok = bool(
            gate_input.launch_context is not None
            and gate_input.launch_context.launch_provenance == "AIA_SPAWNED_ROOT"
            and gate_input.launch_context.aia_session_id == session.session_id
            and gate_input.launch_context.workspace == session.workspace
            and gate_input.launch_context.hook_bridge_ready
        )
        add("launch_provenance", launch_ok, None if launch_ok else EnforcementReason.LAUNCH_PROVENANCE_INVALID.value)
        lease_ok, lease_status = self._verify_lease(gate_input.workspace_lease, session)
        add("workspace_lease", lease_ok, None if lease_ok else EnforcementReason.WORKSPACE_LEASE_INVALID.value)
        sensor_ok = self._verify_sensors(gate_input.sensor_health, add)

        all_ok = (
            hook_ok
            and root_ok
            and attribution_identity_ok
            and launch_ok
            and lease_ok
            and sensor_ok
        )
        if not all_ok:
            return self._result(
                gate_input,
                checked_at,
                checks,
                failures,
                EnforcementDecision.REFUSE,
                EnforcementRoute.NONE,
                lease_status=lease_status,
            )
        route = (
            EnforcementRoute.PRETOOL_BLOCK
            if action.stage is ObservationStage.PRE_ACTION
            else EnforcementRoute.PROCESS_TERMINATION
            if action.stage is ObservationStage.POST_ACTION
            else EnforcementRoute.NONE
        )
        if route is EnforcementRoute.NONE:
            add("stage_supported", False, EnforcementReason.UNSUPPORTED_STAGE.value)
            return self._result(gate_input, checked_at, checks, failures, EnforcementDecision.REFUSE, route, lease_status=lease_status)
        add("stage_supported", True)
        return self._result(
            gate_input,
            checked_at,
            checks,
            failures,
            EnforcementDecision.CONTAIN,
            route,
            lease_status=lease_status,
        )

    def _verify_root(
        self,
        context: ProtectedLaunchContext | None,
        session: ProtectedRunSession,
    ) -> tuple[bool, str | None]:
        if context is None:
            return False, EnforcementReason.ROOT_PROCESS_IDENTITY_INVALID.value
        registration = context.root_registration
        if (
            registration.aia_session_id != session.session_id
            or registration.workspace != session.workspace
            or registration.root_process_identity != context.root_process_identity
        ):
            return False, EnforcementReason.ROOT_REGISTRATION_MISMATCH.value
        status, _ = inspect_process_identity(
            context.root_process_identity,
            process_factory=self.process_factory or psutil.Process,
        )
        if status is not ProcessIdentityStatus.LIVE_MATCH:
            return False, EnforcementReason.ROOT_PROCESS_IDENTITY_INVALID.value
        return True, None

    def _verify_attribution_identity(
        self,
        attribution: AttributionResult,
        context: ProtectedLaunchContext | None,
    ) -> tuple[bool, str | None]:
        if context is None:
            return False, EnforcementReason.ROOT_PROCESS_IDENTITY_INVALID.value
        if (
            attribution.root_process_identity is not None
            and attribution.root_process_identity != context.root_process_identity
        ):
            return False, EnforcementReason.PROCESS_IDENTITY_MISMATCH.value
        if attribution.process_identity is not None:
            if attribution.process_identity == context.root_process_identity:
                return True, None
            status, _ = inspect_process_identity(
                attribution.process_identity,
                process_factory=self.process_factory or psutil.Process,
            )
            if status is not ProcessIdentityStatus.LIVE_MATCH:
                return False, EnforcementReason.PROCESS_IDENTITY_MISMATCH.value
        return True, None

    def _verify_lease(
        self,
        lease: WorkspaceLease | None,
        session: ProtectedRunSession,
    ) -> tuple[bool, str]:
        if lease is None or lease.session_id != session.session_id:
            return False, "MISSING"
        try:
            if canonicalize_workspace(lease.workspace) != session.workspace:
                return False, "WORKSPACE_MISMATCH"
        except (OSError, ValueError):
            return False, "WORKSPACE_MISMATCH"
        if self.lease_manager is None:
            return False, "UNVERIFIABLE"
        try:
            current = self.lease_manager.validate_ownership(lease)
        except (ProtectionError, OSError, ValueError):
            return False, "UNVERIFIABLE"
        if current.session_id != session.session_id or current.workspace != session.workspace:
            return False, "MISMATCH"
        return True, LeaseOwnerStatus.LIVE_MATCH.value

    def _verify_sensors(
        self,
        health: tuple[SensorHealth, ...],
        add: Callable[[str, bool, str | None], None],
    ) -> bool:
        by_source = {item.sensor: item for item in health}
        result = True
        for source in self._REQUIRED_SENSORS:
            item = by_source.get(source)
            passed = item is not None and item.status is SensorStatus.HEALTHY
            add(
                f"sensor:{source.value}",
                passed,
                None if passed else EnforcementReason.SENSOR_UNHEALTHY.value,
            )
            result = result and passed
        return result

    @staticmethod
    def _result(
        gate_input: EnforcementGateInput,
        checked_at: datetime,
        checks: list[GateCheck],
        failures: list[str],
        decision: EnforcementDecision,
        route: EnforcementRoute,
        *,
        lease_status: str = "UNVERIFIED",
    ) -> EnforcementGateResult:
        context = gate_input.launch_context
        return EnforcementGateResult(
            action_id=gate_input.action.action_id,
            aia_session_id=gate_input.session.session_id,
            policy_decision=gate_input.policy_evaluation.policy_decision,
            attribution_grade=gate_input.attribution.grade,
            decision=decision,
            route=route,
            action=EnforcementAction.NONE,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            stage=gate_input.action.stage,
            checked_at=checked_at,
            gate_checks=tuple(checks),
            failure_reasons=tuple(failures),
            policy_fingerprint=gate_input.active_policy.sha256,
            root_process_identity=context.root_process_identity if context is not None else None,
            hook_trust_status=gate_input.hook_trust_status,
            sensor_statuses=gate_input.sensor_health,
            lease_status=lease_status,
        )


__all__ = [
    "EnforcementAction",
    "EnforcementDecision",
    "EnforcementExecutionResult",
    "EnforcementGate",
    "EnforcementGateInput",
    "EnforcementGateResult",
    "EnforcementReason",
    "EnforcementRoute",
    "GateCheck",
    "HookTrustStatus",
]
