"""Managed process registration and identity-safe process termination.

The Process Manager is intentionally downstream of the Enforcement Gate.  It
does not decide whether an action is dangerous and it does not expose a PID
based kill API.  A termination attempt is valid only when the caller presents
the complete, correlated Gate, launch, session, workspace, and lease context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import math
from pathlib import Path
import time
from typing import Any, Callable, TYPE_CHECKING
from uuid import uuid4

import psutil

from .enforcement import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
)
from .process_identity import (
    ProcessIdentity,
    ProcessIdentityStatus,
    inspect_process_identity,
)
from .session import SessionStatus, canonicalize_workspace

if TYPE_CHECKING:
    from .launcher import ProtectedLaunchContext
    from .protection import WorkspaceLease, WorkspaceLeaseManager
    from .session import ProtectedRunSession


class ProcessManagerError(ValueError):
    """Base error for managed-process registration and termination."""


class ManagedRootConflictError(ProcessManagerError):
    """Raised when a session or launch is bound to a different root."""

    code = "MANAGED_ROOT_CONFLICT"


class ProcessTerminationOutcome(StrEnum):
    """Internal result for one managed termination operation."""

    TERMINATED = "TERMINATED"
    ALREADY_EXITED = "ALREADY_EXITED"
    EXITED_DURING_CONTAINMENT = "EXITED_DURING_CONTAINMENT"
    IDENTITY_REUSED = "IDENTITY_REUSED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"


class TerminationAttemptResult(StrEnum):
    """Result of one graceful or force termination API call."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProcessManagerError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProcessManagerError(f"{field_name} must be non-empty")
    return value


def _same_identity(left: ProcessIdentity, right: ProcessIdentity) -> bool:
    return left.pid == right.pid and left.create_time == right.create_time


def _identity_from_process(process: Any) -> ProcessIdentity:
    return ProcessIdentity(int(process.pid), float(process.create_time()))


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    """Immutable binding between an AIA launch and its managed root."""

    aia_session_id: str
    launch_id: str
    workspace: Path | str
    root_process_identity: ProcessIdentity
    launch_provenance: str
    registered_at: datetime
    executable: Path | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aia_session_id",
            _required_text(self.aia_session_id, field_name="aia_session_id"),
        )
        object.__setattr__(
            self,
            "launch_id",
            _required_text(self.launch_id, field_name="launch_id"),
        )
        object.__setattr__(self, "workspace", canonicalize_workspace(self.workspace))
        if not isinstance(self.root_process_identity, ProcessIdentity):
            raise ProcessManagerError(
                "root_process_identity must be a ProcessIdentity"
            )
        if self.launch_provenance != "AIA_SPAWNED_ROOT":
            raise ProcessManagerError(
                "managed processes require AIA_SPAWNED_ROOT provenance"
            )
        object.__setattr__(
            self,
            "registered_at",
            _aware_utc(self.registered_at, field_name="registered_at"),
        )
        if self.executable is not None:
            executable = Path(self.executable).expanduser().resolve(strict=False)
            if not executable.is_absolute():
                raise ProcessManagerError("executable must be absolute")
            object.__setattr__(self, "executable", executable)


@dataclass(frozen=True, slots=True)
class ManagedDescendant:
    """One verified process found below the managed root."""

    process_identity: ProcessIdentity
    parent_process_identity: ProcessIdentity
    depth: int
    discovered_at: datetime
    process_role: str = "DESCENDANT"

    def __post_init__(self) -> None:
        if not isinstance(self.process_identity, ProcessIdentity):
            raise ProcessManagerError("process_identity must be a ProcessIdentity")
        if not isinstance(self.parent_process_identity, ProcessIdentity):
            raise ProcessManagerError(
                "parent_process_identity must be a ProcessIdentity"
            )
        if not isinstance(self.depth, int) or self.depth < 1:
            raise ProcessManagerError("depth must be a positive integer")
        object.__setattr__(
            self,
            "discovered_at",
            _aware_utc(self.discovered_at, field_name="discovered_at"),
        )


@dataclass(frozen=True, slots=True)
class ProcessTerminationEntry:
    """Audit-safe result for one root or descendant identity."""

    process_identity: ProcessIdentity
    process_role: str
    depth: int
    initial_verification: ProcessIdentityStatus
    terminate_attempted: bool
    terminate_result: TerminationAttemptResult
    force_kill_attempted: bool
    force_kill_result: TerminationAttemptResult
    final_verification: ProcessIdentityStatus
    outcome: ProcessTerminationOutcome
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "initial_verification",
            ProcessIdentityStatus(self.initial_verification),
        )
        object.__setattr__(
            self,
            "final_verification",
            ProcessIdentityStatus(self.final_verification),
        )
        object.__setattr__(
            self,
            "terminate_result",
            TerminationAttemptResult(self.terminate_result),
        )
        object.__setattr__(
            self,
            "force_kill_result",
            TerminationAttemptResult(self.force_kill_result),
        )
        object.__setattr__(self, "outcome", ProcessTerminationOutcome(self.outcome))

    def to_mapping(self) -> dict[str, Any]:
        """Return the complete, audit-safe per-process result."""

        return {
            "process_identity": {
                "pid": self.process_identity.pid,
                "create_time": self.process_identity.create_time,
            },
            "process_role": self.process_role,
            "depth": self.depth,
            "initial_verification": self.initial_verification.value,
            "terminate_attempted": self.terminate_attempted,
            "terminate_result": self.terminate_result.value,
            "force_kill_attempted": self.force_kill_attempted,
            "force_kill_result": self.force_kill_result.value,
            "final_verification": self.final_verification.value,
            "outcome": self.outcome.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ProcessTerminationResult:
    """Official outcome of one Gate-bound process termination execution."""

    termination_id: str
    aia_session_id: str
    launch_id: str
    decision: EnforcementDecision
    route: EnforcementRoute
    action: EnforcementAction
    execution_result: EnforcementExecutionResult
    termination_attempt_count: int
    outcome: ProcessTerminationOutcome
    process_results: tuple[ProcessTerminationEntry, ...]
    termination_requested_at: datetime
    termination_started_at: datetime | None
    termination_completed_at: datetime
    gate_to_termination_start_ms: float | None
    termination_duration_ms: float | None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", EnforcementDecision(self.decision))
        object.__setattr__(self, "route", EnforcementRoute(self.route))
        object.__setattr__(self, "action", EnforcementAction(self.action))
        object.__setattr__(
            self,
            "execution_result",
            EnforcementExecutionResult(self.execution_result),
        )
        object.__setattr__(self, "outcome", ProcessTerminationOutcome(self.outcome))
        if (
            not isinstance(self.termination_attempt_count, int)
            or isinstance(self.termination_attempt_count, bool)
            or self.termination_attempt_count < 0
        ):
            raise ProcessManagerError(
                "termination_attempt_count must be a non-negative integer"
            )
        object.__setattr__(self, "process_results", tuple(self.process_results))
        for field_name in (
            "termination_requested_at",
            "termination_completed_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _aware_utc(getattr(self, field_name), field_name=field_name),
            )
        if self.termination_started_at is not None:
            object.__setattr__(
                self,
                "termination_started_at",
                _aware_utc(
                    self.termination_started_at,
                    field_name="termination_started_at",
                ),
            )
        for field_name in (
            "gate_to_termination_start_ms",
            "termination_duration_ms",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ProcessManagerError(f"{field_name} must be non-negative")

    @property
    def entries(self) -> tuple[ProcessTerminationEntry, ...]:
        """Alias used by callers that refer to per-process entries."""

        return self.process_results

    def to_mapping(self) -> dict[str, Any]:
        """Return the complete, audit-safe termination execution result.

        Enforcement Gate state and the actual execution result remain separate
        fields.  This mapping is safe for Result Bundle and diagnostic output;
        it contains process identities and bounded status values, never process
        command lines or raw tool payloads.
        """

        return {
            "termination_id": self.termination_id,
            "aia_session_id": self.aia_session_id,
            "launch_id": self.launch_id,
            "decision": self.decision.value,
            "route": self.route.value,
            "action": self.action.value,
            "execution_result": self.execution_result.value,
            "termination_attempt_count": self.termination_attempt_count,
            "outcome": self.outcome.value,
            "process_results": [item.to_mapping() for item in self.process_results],
            "termination_requested_at": self.termination_requested_at.isoformat(),
            "termination_started_at": (
                self.termination_started_at.isoformat()
                if self.termination_started_at is not None
                else None
            ),
            "termination_completed_at": self.termination_completed_at.isoformat(),
            "gate_to_termination_start_ms": self.gate_to_termination_start_ms,
            "termination_duration_ms": self.termination_duration_ms,
            "reason": self.reason,
        }


class ManagedProcessRegistry:
    """Session/launch registry for immutable managed roots and replay results."""

    def __init__(self) -> None:
        self._by_session: dict[str, ManagedProcess] = {}
        self._by_launch: dict[str, ManagedProcess] = {}
        self._termination_results: dict[
            tuple[str, str], ProcessTerminationResult
        ] = {}

    def register(self, managed_process: ManagedProcess) -> ManagedProcess:
        if not isinstance(managed_process, ManagedProcess):
            raise ProcessManagerError("managed_process must be a ManagedProcess")
        existing_session = self._by_session.get(managed_process.aia_session_id)
        existing_launch = self._by_launch.get(managed_process.launch_id)
        for existing in (existing_session, existing_launch):
            if existing is None:
                continue
            if existing != managed_process:
                raise ManagedRootConflictError(
                    "session or launch is already bound to another managed root"
                )
        self._by_session[managed_process.aia_session_id] = managed_process
        self._by_launch[managed_process.launch_id] = managed_process
        return managed_process

    def get_by_session(self, aia_session_id: str) -> ManagedProcess | None:
        return self._by_session.get(aia_session_id)

    def get_by_launch(self, launch_id: str) -> ManagedProcess | None:
        return self._by_launch.get(launch_id)

    def validate_binding(
        self,
        *,
        aia_session_id: str,
        launch_id: str,
        workspace: Path | str,
        root_process_identity: ProcessIdentity,
    ) -> ManagedProcess:
        managed = self.get_by_session(aia_session_id)
        if managed is None or self.get_by_launch(launch_id) != managed:
            raise ManagedRootConflictError("managed session/launch binding is absent")
        if (
            managed.workspace != canonicalize_workspace(workspace)
            or not _same_identity(managed.root_process_identity, root_process_identity)
            or managed.aia_session_id != aia_session_id
            or managed.launch_id != launch_id
        ):
            raise ManagedRootConflictError("managed root binding does not match")
        return managed

    def mark_termination_result(
        self,
        result: ProcessTerminationResult,
    ) -> ProcessTerminationResult:
        key = (result.aia_session_id, result.launch_id)
        existing = self._termination_results.get(key)
        if existing is not None:
            return existing
        self._termination_results[key] = result
        return result

    def get_termination_result(
        self,
        aia_session_id: str,
        launch_id: str,
    ) -> ProcessTerminationResult | None:
        return self._termination_results.get((aia_session_id, launch_id))


@dataclass(slots=True)
class _WorkEntry:
    identity: ProcessIdentity
    role: str
    depth: int
    parent_identity: ProcessIdentity | None
    initial: ProcessIdentityStatus = ProcessIdentityStatus.LIVE_MATCH
    final: ProcessIdentityStatus = ProcessIdentityStatus.LIVE_MATCH
    terminate_attempted: bool = False
    terminate_result: TerminationAttemptResult = TerminationAttemptResult.NOT_ATTEMPTED
    force_kill_attempted: bool = False
    force_kill_result: TerminationAttemptResult = TerminationAttemptResult.NOT_ATTEMPTED
    outcome: ProcessTerminationOutcome = ProcessTerminationOutcome.FAILED
    reason: str | None = None


class ProcessManager:
    """Execute only Gate-authorized, identity-verified process termination."""

    def __init__(
        self,
        registry: ManagedProcessRegistry,
        lease_manager: "WorkspaceLeaseManager",
        *,
        process_factory: Callable[[int], Any] = psutil.Process,
        clock: Callable[[], datetime] = _now_utc,
        sleeper: Callable[[float], None] = time.sleep,
        terminate_wait_seconds: float = 0.5,
        force_kill_wait_seconds: float = 0.5,
        max_refresh_passes: int = 3,
    ) -> None:
        if not isinstance(registry, ManagedProcessRegistry):
            raise ProcessManagerError("registry must be a ManagedProcessRegistry")
        if lease_manager is None or not callable(
            getattr(lease_manager, "validate_ownership", None)
        ):
            raise ProcessManagerError("lease_manager must validate ownership")
        if terminate_wait_seconds < 0 or force_kill_wait_seconds < 0:
            raise ProcessManagerError("termination wait values must be non-negative")
        if max_refresh_passes < 1 or max_refresh_passes > 3:
            raise ProcessManagerError("max_refresh_passes must be between 1 and 3")
        self.registry = registry
        self.lease_manager = lease_manager
        self.process_factory = process_factory
        self.clock = clock
        self.sleeper = sleeper
        self.terminate_wait_seconds = float(terminate_wait_seconds)
        self.force_kill_wait_seconds = float(force_kill_wait_seconds)
        self.max_refresh_passes = max_refresh_passes

    def execute(
        self,
        gate_result: EnforcementGateResult,
        *,
        session: "ProtectedRunSession",
        launch_context: "ProtectedLaunchContext",
        workspace_lease: "WorkspaceLease",
    ) -> ProcessTerminationResult:
        """Execute a Gate-bound termination request.

        All binding and lease checks happen before the first process lookup.
        The method is intentionally the only public Process Manager operation;
        callers cannot provide a bare PID or process tree root.
        """

        requested_at = self.clock()
        if not isinstance(gate_result, EnforcementGateResult):
            return self._refused_result(
                "GATE_RESULT_INVALID",
                requested_at=requested_at,
            )
        launch_id = getattr(launch_context, "launch_id", "")
        session_id = getattr(session, "session_id", gate_result.aia_session_id)
        replay = self.registry.get_termination_result(session_id, launch_id)

        refusal = self._validate_execution_context(
            gate_result,
            session=session,
            launch_context=launch_context,
            workspace_lease=workspace_lease,
        )
        if refusal is not None:
            return self._refused_result(
                refusal,
                requested_at=requested_at,
                aia_session_id=session_id,
                launch_id=launch_id,
            )
        if replay is not None:
            return replay

        assert gate_result.root_process_identity is not None
        assert launch_id
        assert isinstance(launch_context.aia_session_id, str)
        started_at = self.clock()
        root_identity = gate_result.root_process_identity
        entries: dict[tuple[int, float], _WorkEntry] = {}
        root_entry = _WorkEntry(
            identity=root_identity,
            role="ROOT",
            depth=0,
            parent_identity=None,
        )
        entries[(root_identity.pid, root_identity.create_time)] = root_entry
        known_pid_identities: dict[int, ProcessIdentity] = {
            root_identity.pid: root_identity
        }
        fatal_verification_failure = False

        root_status, root_process = self._inspect(root_identity)
        root_entry.initial = root_status
        root_entry.final = root_status
        if root_status is ProcessIdentityStatus.PROCESS_GONE:
            root_entry.outcome = ProcessTerminationOutcome.ALREADY_EXITED
            root_entry.reason = "ROOT_GONE_BEFORE_TERMINATION_API"
            return self._finish(
                gate_result,
                session_id,
                launch_id,
                ProcessTerminationOutcome.ALREADY_EXITED,
                entries,
                requested_at,
                None,
                self.clock(),
                reason="ROOT_GONE_BEFORE_TERMINATION_API",
            )
        if root_status is not ProcessIdentityStatus.LIVE_MATCH or root_process is None:
            root_entry.outcome = (
                ProcessTerminationOutcome.IDENTITY_REUSED
                if root_status is ProcessIdentityStatus.PID_REUSED
                else ProcessTerminationOutcome.REFUSED
            )
            root_entry.reason = f"ROOT_{root_status.value}"
            return self._finish(
                gate_result,
                session_id,
                launch_id,
                root_entry.outcome,
                entries,
                requested_at,
                None,
                self.clock(),
                reason=root_entry.reason,
            )

        for pass_index in range(self.max_refresh_passes):
            status, root_process = self._inspect(root_identity)
            root_entry.final = status
            if status is not ProcessIdentityStatus.LIVE_MATCH or root_process is None:
                termination_attempt_count = self._termination_attempt_count(entries)
                if termination_attempt_count > 0 and status in {
                    ProcessIdentityStatus.PROCESS_GONE,
                    ProcessIdentityStatus.PID_REUSED,
                }:
                    root_entry.outcome = (
                        ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT
                        if status is ProcessIdentityStatus.PROCESS_GONE
                        else ProcessTerminationOutcome.IDENTITY_REUSED
                    )
                    root_entry.reason = (
                        "ROOT_EXITED_DURING_CONTAINMENT"
                        if status is ProcessIdentityStatus.PROCESS_GONE
                        else "ROOT_PID_REUSED_DURING_CONTAINMENT"
                    )
                    break
                if status is ProcessIdentityStatus.PROCESS_GONE:
                    root_entry.outcome = ProcessTerminationOutcome.ALREADY_EXITED
                    root_entry.reason = "ROOT_GONE_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.ALREADY_EXITED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_GONE_BEFORE_TERMINATION_API",
                    )
                if status is ProcessIdentityStatus.PID_REUSED:
                    root_entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                    root_entry.reason = "ROOT_PID_REUSED_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.IDENTITY_REUSED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_PID_REUSED_BEFORE_TERMINATION_API",
                    )
                fatal_verification_failure = True
                root_entry.outcome = (
                    ProcessTerminationOutcome.IDENTITY_REUSED
                    if status is ProcessIdentityStatus.PID_REUSED
                    else ProcessTerminationOutcome.REFUSED
                )
                root_entry.reason = f"ROOT_{status.value}"
                break
            discovered_new, discovery_failure = self._discover_descendants(
                root_process,
                root_identity,
                entries,
                known_pid_identities,
            )
            fatal_verification_failure = fatal_verification_failure or discovery_failure
            for entry in sorted(
                entries.values(),
                key=lambda item: (-item.depth, item.identity.pid, item.identity.create_time),
            ):
                if entry.role != "DESCENDANT":
                    continue
                if entry.final is ProcessIdentityStatus.LIVE_MATCH:
                    self._terminate_entry(entry)

            root_status, root_process = self._inspect(root_identity)
            root_entry.final = root_status
            if root_status is not ProcessIdentityStatus.LIVE_MATCH or root_process is None:
                termination_attempt_count = self._termination_attempt_count(entries)
                if termination_attempt_count > 0 and root_status in {
                    ProcessIdentityStatus.PROCESS_GONE,
                    ProcessIdentityStatus.PID_REUSED,
                }:
                    root_entry.outcome = (
                        ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT
                        if root_status is ProcessIdentityStatus.PROCESS_GONE
                        else ProcessTerminationOutcome.IDENTITY_REUSED
                    )
                    root_entry.reason = (
                        "ROOT_EXITED_DURING_CONTAINMENT"
                        if root_status is ProcessIdentityStatus.PROCESS_GONE
                        else "ROOT_PID_REUSED_DURING_CONTAINMENT"
                    )
                    break
                if root_status is ProcessIdentityStatus.PROCESS_GONE:
                    root_entry.outcome = ProcessTerminationOutcome.ALREADY_EXITED
                    root_entry.reason = "ROOT_GONE_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.ALREADY_EXITED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_GONE_BEFORE_TERMINATION_API",
                    )
                if root_status is ProcessIdentityStatus.PID_REUSED:
                    root_entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                    root_entry.reason = "ROOT_PID_REUSED_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.IDENTITY_REUSED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_PID_REUSED_BEFORE_TERMINATION_API",
                    )
                fatal_verification_failure = True
                root_entry.reason = "ROOT_NOT_LIVE_AFTER_DESCENDANT_TERMINATION"
                break

            live_descendants = any(
                entry.role == "DESCENDANT"
                and entry.final is ProcessIdentityStatus.LIVE_MATCH
                for entry in entries.values()
            )
            if pass_index >= 1 and not discovered_new and not live_descendants:
                break

        if not fatal_verification_failure:
            root_status, root_process = self._inspect(root_identity)
            root_entry.final = root_status
            if root_status is ProcessIdentityStatus.LIVE_MATCH and root_process is not None:
                self._terminate_entry(root_entry)
            elif root_status is ProcessIdentityStatus.PROCESS_GONE:
                if self._termination_attempt_count(entries) > 0:
                    root_entry.outcome = ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT
                    root_entry.reason = "ROOT_EXITED_DURING_CONTAINMENT"
                else:
                    root_entry.outcome = ProcessTerminationOutcome.ALREADY_EXITED
                    root_entry.reason = "ROOT_GONE_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.ALREADY_EXITED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_GONE_BEFORE_TERMINATION_API",
                    )
            elif root_status is ProcessIdentityStatus.PID_REUSED:
                if self._termination_attempt_count(entries) > 0:
                    root_entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                    root_entry.reason = "ROOT_PID_REUSED_DURING_CONTAINMENT"
                else:
                    root_entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                    root_entry.reason = "ROOT_PID_REUSED_BEFORE_TERMINATION_API"
                    return self._finish(
                        gate_result,
                        session_id,
                        launch_id,
                        ProcessTerminationOutcome.IDENTITY_REUSED,
                        entries,
                        requested_at,
                        None,
                        self.clock(),
                        reason="ROOT_PID_REUSED_BEFORE_TERMINATION_API",
                    )
            else:
                root_entry.reason = "ROOT_NOT_LIVE_BEFORE_TERMINATION_API"
                fatal_verification_failure = True

        completed_at = self.clock()
        for entry in entries.values():
            final_status, _ = self._inspect(entry.identity)
            entry.final = final_status
            if final_status is ProcessIdentityStatus.LIVE_MATCH:
                if entry.outcome is ProcessTerminationOutcome.FAILED:
                    entry.reason = entry.reason or "PROCESS_REMAINS_LIVE"
            elif final_status is ProcessIdentityStatus.PROCESS_GONE:
                if (
                    entry.outcome is ProcessTerminationOutcome.FAILED
                    and (entry.terminate_attempted or entry.force_kill_attempted)
                ):
                    entry.outcome = ProcessTerminationOutcome.TERMINATED
            elif final_status is ProcessIdentityStatus.PID_REUSED:
                entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                entry.reason = entry.reason or "PID_REUSED_DURING_FINAL_VERIFICATION"

        termination_attempt_count = self._termination_attempt_count(entries)
        success = (
            not fatal_verification_failure
            and termination_attempt_count > 0
            and root_entry.final is not ProcessIdentityStatus.LIVE_MATCH
            and all(
                entry.final is not ProcessIdentityStatus.LIVE_MATCH
                for entry in entries.values()
            )
            and all(
                entry.outcome
                in {
                    ProcessTerminationOutcome.TERMINATED,
                    ProcessTerminationOutcome.ALREADY_EXITED,
                    ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT,
                    ProcessTerminationOutcome.IDENTITY_REUSED,
                }
                for entry in entries.values()
            )
        )
        if success:
            outcome = ProcessTerminationOutcome.TERMINATED
            action = EnforcementAction.TERMINATED
            execution = EnforcementExecutionResult.SUCCEEDED
            reason = None
        else:
            any_progress = termination_attempt_count > 0
            outcome = (
                ProcessTerminationOutcome.PARTIAL
                if any_progress and any(
                    entry.outcome is not ProcessTerminationOutcome.TERMINATED
                    for entry in entries.values()
                )
                else ProcessTerminationOutcome.FAILED
            )
            action = EnforcementAction.NONE
            execution = EnforcementExecutionResult.FAILED
            reason = "PROCESS_TREE_TERMINATION_INCOMPLETE"
        result = self._finish(
            gate_result,
            session_id,
            launch_id,
            outcome,
            entries,
            requested_at,
            started_at,
            completed_at,
            reason=reason,
            action=action,
            execution_result=execution,
        )
        return self.registry.mark_termination_result(result)

    terminate = execute

    def _validate_execution_context(
        self,
        gate_result: EnforcementGateResult,
        *,
        session: "ProtectedRunSession",
        launch_context: "ProtectedLaunchContext",
        workspace_lease: "WorkspaceLease",
    ) -> str | None:
        if gate_result.decision is not EnforcementDecision.CONTAIN:
            return "GATE_DECISION_NOT_CONTAIN"
        if gate_result.route is not EnforcementRoute.PROCESS_TERMINATION:
            return "GATE_ROUTE_NOT_PROCESS_TERMINATION"
        if gate_result.action is not EnforcementAction.NONE:
            return "GATE_ACTION_ALREADY_EXECUTED"
        if gate_result.execution_result is not EnforcementExecutionResult.NOT_ATTEMPTED:
            return "GATE_EXECUTION_ALREADY_ATTEMPTED"
        if session is None or getattr(session, "status", None) is not SessionStatus.RUNNING:
            return "SESSION_NOT_RUNNING"
        if getattr(session, "session_id", None) != gate_result.aia_session_id:
            return "SESSION_BINDING_MISMATCH"
        if launch_context is None:
            return "LAUNCH_CONTEXT_MISSING"
        if getattr(launch_context, "aia_session_id", None) != session.session_id:
            return "LAUNCH_SESSION_MISMATCH"
        if getattr(launch_context, "workspace", None) != session.workspace:
            return "LAUNCH_WORKSPACE_MISMATCH"
        root_identity = gate_result.root_process_identity
        if root_identity is None:
            return "ROOT_IDENTITY_MISSING"
        launch_root_identity = getattr(launch_context, "root_process_identity", None)
        if not isinstance(launch_root_identity, ProcessIdentity):
            return "LAUNCH_ROOT_IDENTITY_MISSING"
        if not _same_identity(root_identity, launch_root_identity):
            return "ROOT_IDENTITY_MISMATCH"
        if getattr(launch_context, "launch_provenance", None) != "AIA_SPAWNED_ROOT":
            return "LAUNCH_PROVENANCE_INVALID"
        try:
            self.registry.validate_binding(
                aia_session_id=session.session_id,
                launch_id=launch_context.launch_id,
                workspace=session.workspace,
                root_process_identity=root_identity,
            )
        except (ManagedRootConflictError, ProcessManagerError, ValueError):
            return "MANAGED_ROOT_BINDING_MISMATCH"
        if workspace_lease is None:
            return "WORKSPACE_LEASE_MISSING"
        try:
            validated = self.lease_manager.validate_ownership(workspace_lease)
        except Exception:
            return "WORKSPACE_LEASE_INVALID"
        if (
            getattr(validated, "session_id", None) != session.session_id
            or getattr(validated, "workspace", None) != session.workspace
        ):
            return "WORKSPACE_LEASE_BINDING_MISMATCH"
        return None

    def _inspect(
        self,
        identity: ProcessIdentity,
    ) -> tuple[ProcessIdentityStatus, Any | None]:
        return inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )

    def _discover_descendants(
        self,
        root_process: Any,
        root_identity: ProcessIdentity,
        entries: dict[tuple[int, float], _WorkEntry],
        known_pid_identities: dict[int, ProcessIdentity],
    ) -> tuple[bool, bool]:
        try:
            candidates = list(root_process.children(recursive=True))
        except Exception:
            return False, True
        discovered_new = False
        fatal_failure = False
        for candidate in candidates:
            try:
                identity = _identity_from_process(candidate)
            except Exception:
                fatal_failure = True
                continue
            previous_identity = known_pid_identities.get(identity.pid)
            if previous_identity is not None and not _same_identity(
                previous_identity,
                identity,
            ):
                key = (previous_identity.pid, previous_identity.create_time)
                previous = entries.get(key)
                if previous is not None:
                    previous.final = ProcessIdentityStatus.PID_REUSED
                    previous.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
                    previous.reason = "PID_REUSED_DURING_REFRESH"
                fatal_failure = True
                continue
            known_pid_identities[identity.pid] = identity
            key = (identity.pid, identity.create_time)
            if key in entries:
                continue
            status, process = self._inspect(identity)
            if status is ProcessIdentityStatus.PROCESS_GONE:
                entry = _WorkEntry(
                    identity=identity,
                    role="DESCENDANT",
                    depth=1,
                    parent_identity=root_identity,
                    initial=status,
                    final=status,
                    outcome=ProcessTerminationOutcome.ALREADY_EXITED,
                    reason="DESCENDANT_GONE_BEFORE_TERMINATION_API",
                )
                entries[key] = entry
                discovered_new = True
                continue
            if status is not ProcessIdentityStatus.LIVE_MATCH or process is None:
                entries[key] = _WorkEntry(
                    identity=identity,
                    role="DESCENDANT",
                    depth=1,
                    parent_identity=root_identity,
                    initial=status,
                    final=status,
                    outcome=(
                        ProcessTerminationOutcome.IDENTITY_REUSED
                        if status is ProcessIdentityStatus.PID_REUSED
                        else ProcessTerminationOutcome.REFUSED
                    ),
                    reason=f"DESCENDANT_{status.value}",
                )
                fatal_failure = True
                discovered_new = True
                continue
            chain = self._verified_parent_chain(process, root_identity)
            if chain is None:
                # An observed process without a current verified root chain is
                # unrelated or has raced out of the managed tree.  It is never
                # passed to a termination API.
                continue
            parent_identity, depth = chain
            entries[key] = _WorkEntry(
                identity=identity,
                role="DESCENDANT",
                depth=depth,
                parent_identity=parent_identity,
            )
            discovered_new = True
        return discovered_new, fatal_failure

    def _verified_parent_chain(
        self,
        process: Any,
        root_identity: ProcessIdentity,
    ) -> tuple[ProcessIdentity, int] | None:
        current = process
        seen: set[int] = set()
        direct_parent: ProcessIdentity | None = None
        depth = 0
        for _ in range(128):
            try:
                current_pid = int(current.pid)
            except Exception:
                return None
            if current_pid in seen:
                return None
            seen.add(current_pid)
            try:
                parent = current.parent()
            except Exception:
                return None
            if parent is None:
                return None
            try:
                parent_identity = _identity_from_process(parent)
            except Exception:
                return None
            if direct_parent is None:
                direct_parent = parent_identity
            depth += 1
            if _same_identity(parent_identity, root_identity):
                return parent_identity, depth
            status, verified_parent = self._inspect(parent_identity)
            if status is not ProcessIdentityStatus.LIVE_MATCH or verified_parent is None:
                return None
            current = verified_parent
        return None

    def _terminate_entry(self, entry: _WorkEntry) -> None:
        status, process = self._inspect(entry.identity)
        if entry.initial is ProcessIdentityStatus.LIVE_MATCH:
            entry.initial = status
        if status is ProcessIdentityStatus.PROCESS_GONE:
            entry.final = status
            entry.outcome = ProcessTerminationOutcome.ALREADY_EXITED
            entry.reason = "PROCESS_GONE_BEFORE_TERMINATION_API"
            return
        if status is ProcessIdentityStatus.PID_REUSED:
            entry.final = status
            entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
            entry.reason = "PID_REUSED_BEFORE_TERMINATION_API"
            return
        if status is not ProcessIdentityStatus.LIVE_MATCH or process is None:
            entry.final = status
            entry.outcome = ProcessTerminationOutcome.REFUSED
            entry.reason = "OWNER_UNVERIFIABLE_BEFORE_TERMINATION_API"
            return

        entry.terminate_attempted = True
        try:
            process.terminate()
            entry.terminate_result = TerminationAttemptResult.SUCCEEDED
        except Exception:
            entry.terminate_result = TerminationAttemptResult.FAILED
            entry.reason = "GRACEFUL_TERMINATION_FAILED"
        status = self._wait_for_identity(entry.identity, self.terminate_wait_seconds)
        entry.final = status
        if status is ProcessIdentityStatus.LIVE_MATCH:
            status, process = self._inspect(entry.identity)
            entry.final = status
            if status is ProcessIdentityStatus.LIVE_MATCH and process is not None:
                entry.force_kill_attempted = True
                try:
                    process.kill()
                    entry.force_kill_result = TerminationAttemptResult.SUCCEEDED
                except Exception:
                    entry.force_kill_result = TerminationAttemptResult.FAILED
                    entry.reason = entry.reason or "FORCE_TERMINATION_FAILED"
                entry.final = self._wait_for_identity(
                    entry.identity,
                    self.force_kill_wait_seconds,
                )

        if entry.final is ProcessIdentityStatus.PROCESS_GONE:
            entry.outcome = ProcessTerminationOutcome.TERMINATED
            entry.reason = entry.reason or "PROCESS_TERMINATED"
        elif entry.final is ProcessIdentityStatus.PID_REUSED:
            entry.outcome = ProcessTerminationOutcome.IDENTITY_REUSED
            entry.reason = entry.reason or "PID_REUSED_AFTER_TERMINATION"
        elif entry.final is ProcessIdentityStatus.OWNER_UNVERIFIABLE:
            entry.outcome = ProcessTerminationOutcome.REFUSED
            entry.reason = entry.reason or "OWNER_UNVERIFIABLE_AFTER_TERMINATION"
        else:
            entry.outcome = ProcessTerminationOutcome.FAILED
            entry.reason = entry.reason or "PROCESS_REMAINS_LIVE"

    def _wait_for_identity(
        self,
        identity: ProcessIdentity,
        timeout_seconds: float,
    ) -> ProcessIdentityStatus:
        deadline = time.monotonic() + timeout_seconds
        while True:
            status, _ = self._inspect(identity)
            if status is not ProcessIdentityStatus.LIVE_MATCH:
                return status
            if timeout_seconds <= 0 or time.monotonic() >= deadline:
                return status
            self.sleeper(min(0.02, max(0.0, deadline - time.monotonic())))

    @staticmethod
    def _termination_attempt_count(
        entries: dict[tuple[int, float], _WorkEntry],
    ) -> int:
        """Count real termination API interventions on verified identities."""

        return sum(
            int(entry.terminate_attempted) + int(entry.force_kill_attempted)
            for entry in entries.values()
        )

    def _refused_result(
        self,
        reason: str,
        *,
        requested_at: datetime,
        aia_session_id: str = "unknown",
        launch_id: str = "unknown",
    ) -> ProcessTerminationResult:
        result = ProcessTerminationResult(
            termination_id=str(uuid4()),
            aia_session_id=aia_session_id,
            launch_id=launch_id,
            decision=EnforcementDecision.REFUSE,
            route=EnforcementRoute.NONE,
            action=EnforcementAction.NONE,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            termination_attempt_count=0,
            outcome=ProcessTerminationOutcome.REFUSED,
            process_results=(),
            termination_requested_at=requested_at,
            termination_started_at=None,
            termination_completed_at=self.clock(),
            gate_to_termination_start_ms=None,
            termination_duration_ms=None,
            reason=reason,
        )
        return result

    def _finish(
        self,
        gate_result: EnforcementGateResult,
        aia_session_id: str,
        launch_id: str,
        outcome: ProcessTerminationOutcome,
        entries: dict[tuple[int, float], _WorkEntry],
        requested_at: datetime,
        started_at: datetime | None,
        completed_at: datetime,
        *,
        reason: str | None,
        action: EnforcementAction = EnforcementAction.NONE,
        execution_result: EnforcementExecutionResult = EnforcementExecutionResult.NOT_ATTEMPTED,
    ) -> ProcessTerminationResult:
        process_results = tuple(
            ProcessTerminationEntry(
                process_identity=entry.identity,
                process_role=entry.role,
                depth=entry.depth,
                initial_verification=entry.initial,
                terminate_attempted=entry.terminate_attempted,
                terminate_result=entry.terminate_result,
                force_kill_attempted=entry.force_kill_attempted,
                force_kill_result=entry.force_kill_result,
                final_verification=entry.final,
                outcome=entry.outcome,
                reason=entry.reason,
            )
            for entry in sorted(
                entries.values(),
                key=lambda item: (item.depth, item.identity.pid, item.identity.create_time),
            )
        )
        result = ProcessTerminationResult(
            termination_id=str(uuid4()),
            aia_session_id=aia_session_id,
            launch_id=launch_id,
            decision=(
                EnforcementDecision.CONTAIN
                if gate_result.decision is EnforcementDecision.CONTAIN
                else EnforcementDecision.REFUSE
            ),
            route=(
                EnforcementRoute.PROCESS_TERMINATION
                if gate_result.route is EnforcementRoute.PROCESS_TERMINATION
                else EnforcementRoute.NONE
            ),
            action=action,
            execution_result=execution_result,
            termination_attempt_count=self._termination_attempt_count(entries),
            outcome=outcome,
            process_results=process_results,
            termination_requested_at=requested_at,
            termination_started_at=started_at,
            termination_completed_at=completed_at,
            gate_to_termination_start_ms=(
                max(0.0, (started_at - gate_result.checked_at).total_seconds() * 1000)
                if started_at is not None
                else None
            ),
            termination_duration_ms=(
                max(0.0, (completed_at - started_at).total_seconds() * 1000)
                if started_at is not None
                else None
            ),
            reason=reason,
        )
        return self.registry.mark_termination_result(result)


__all__ = [
    "ManagedDescendant",
    "ManagedProcess",
    "ManagedProcessRegistry",
    "ManagedRootConflictError",
    "ProcessManager",
    "ProcessManagerError",
    "ProcessTerminationEntry",
    "ProcessTerminationOutcome",
    "ProcessTerminationResult",
    "TerminationAttemptResult",
]
