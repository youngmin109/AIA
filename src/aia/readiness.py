"""Fail-closed protection readiness checks before an Agent may be launched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from .checkpoint import (
    CheckpointValidity,
    SafeCheckpoint,
    UnsupportedFilesystemEntryError,
    compare_workspace_to_checkpoint,
    validate_checkpoint,
)
from .evidence import EvidenceSource
from .policy import ResolvedPolicy
from .protection import (
    ActivePolicySnapshot,
    ProtectionPreparationContext,
    WorkspaceLease,
    WorkspaceLeaseManager,
    policy_content_mapping,
    policy_content_sha256,
)
from .session import ProtectedRunSession, SessionStatus
from .sensors.base import SensorStatus
from .sensors.filesystem import FilesystemSensor, FilesystemSensorContext
from .sensors.hook import HookSensor, HookSensorContext
from .sensors.process import (
    ProcessObserverCapability,
    ProcessObserverCapabilityStatus,
)


class ReadinessError(ValueError):
    """Raised when a Readiness domain value is invalid."""


class ReadinessStatus(StrEnum):
    """Result status for the Protection Readiness Barrier."""

    READY = "READY"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    check_name: str
    passed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.check_name, str) or not self.check_name.strip():
            raise ReadinessError("check_name must be non-empty")
        if not isinstance(self.passed, bool):
            raise ReadinessError("passed must be a bool")


@dataclass(frozen=True, slots=True)
class ProtectionReadinessResult:
    aia_session_id: str
    workspace: Path
    status: str
    checked_at: datetime
    checks: tuple[ReadinessCheck, ...]
    active_policy_fingerprint: str | None
    checkpoint_id: str | None
    checkpoint_content_sha256: str | None
    current_workspace_content_sha256: str | None
    filesystem_sensor_status: SensorStatus | None
    hook_sensor_status: SensorStatus | None
    hook_ingress_verified: bool | None
    process_observer_capability_status: str
    readiness_context: ProtectionReadinessContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.aia_session_id, str) or not self.aia_session_id:
            raise ReadinessError("aia_session_id must be non-empty")
        object.__setattr__(self, "workspace", Path(self.workspace))
        try:
            object.__setattr__(self, "status", ReadinessStatus(self.status))
        except ValueError as error:
            raise ReadinessError("invalid Readiness status") from error
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ReadinessError("checked_at must be timezone-aware")
        object.__setattr__(
            self,
            "checked_at",
            self.checked_at.astimezone(timezone.utc),
        )
        object.__setattr__(self, "checks", tuple(self.checks))
        if self.filesystem_sensor_status is not None:
            object.__setattr__(
                self,
                "filesystem_sensor_status",
                SensorStatus(self.filesystem_sensor_status),
            )
        if self.hook_sensor_status is not None:
            object.__setattr__(
                self,
                "hook_sensor_status",
                SensorStatus(self.hook_sensor_status),
            )

    @property
    def is_ready(self) -> bool:
        return self.status == ReadinessStatus.READY

    @property
    def context(self) -> ProtectionReadinessContext | None:
        return self.readiness_context


_READINESS_CONTEXT_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ProtectionReadinessContext:
    """Immutable input contract for a future Protected Launcher.

    The constructor requires an internal token. Normal callers obtain this
    object only from a successful ProtectionReadinessBarrier evaluation.
    """

    aia_session_id: str
    workspace: Path
    ready_at: datetime
    active_policy_fingerprint: str
    checkpoint_id: str
    checkpoint_content_sha256: str
    current_workspace_content_sha256: str
    workspace_lease_identity: WorkspaceLease
    filesystem_sensor_status: SensorStatus
    hook_sensor_status: SensorStatus
    hook_ingress_verified: bool
    process_observer_capability: ProcessObserverCapability
    readiness_checks: tuple[ReadinessCheck, ...]

    def __init__(
        self,
        *,
        _token: object,
        aia_session_id: str,
        workspace: Path,
        ready_at: datetime,
        active_policy_fingerprint: str,
        checkpoint_id: str,
        checkpoint_content_sha256: str,
        current_workspace_content_sha256: str,
        workspace_lease_identity: WorkspaceLease,
        filesystem_sensor_status: SensorStatus,
        hook_sensor_status: SensorStatus,
        hook_ingress_verified: bool,
        process_observer_capability: ProcessObserverCapability,
        readiness_checks: tuple[ReadinessCheck, ...],
    ) -> None:
        if _token is not _READINESS_CONTEXT_TOKEN:
            raise ReadinessError(
                "ProtectionReadinessContext is created by Readiness Barrier only"
            )
        if ready_at.tzinfo is None or ready_at.utcoffset() is None:
            raise ReadinessError("ready_at must be timezone-aware")
        values = {
            "aia_session_id": aia_session_id,
            "workspace": Path(workspace),
            "ready_at": ready_at.astimezone(timezone.utc),
            "active_policy_fingerprint": active_policy_fingerprint,
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_sha256": checkpoint_content_sha256,
            "current_workspace_content_sha256": current_workspace_content_sha256,
            "workspace_lease_identity": workspace_lease_identity,
            "filesystem_sensor_status": SensorStatus(filesystem_sensor_status),
            "hook_sensor_status": SensorStatus(hook_sensor_status),
            "hook_ingress_verified": hook_ingress_verified,
            "process_observer_capability": process_observer_capability,
            "readiness_checks": tuple(readiness_checks),
        }
        for field_name, value in values.items():
            object.__setattr__(self, field_name, value)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _same_workspace(left: Path | str, right: Path | str) -> bool:
    try:
        return Path(left).expanduser().resolve(strict=False) == Path(
            right
        ).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _check(
    name: str,
    passed: bool,
    reason: str | None = None,
) -> ReadinessCheck:
    return ReadinessCheck(name, passed, None if passed else reason)


class ProtectionReadinessBarrier:
    """Validate protection prerequisites and perform the READY transition."""

    def __init__(
        self,
        session: ProtectedRunSession,
        preparation_context: ProtectionPreparationContext,
        checkpoint: SafeCheckpoint,
        filesystem_sensor: FilesystemSensor,
        hook_sensor: HookSensor,
        process_observer_capability: ProcessObserverCapability | None = None,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        process_capability: ProcessObserverCapability | None = None,
    ) -> None:
        self.session = session
        self.preparation_context = preparation_context
        self.checkpoint = checkpoint
        self.filesystem_sensor = filesystem_sensor
        self.hook_sensor = hook_sensor
        self.lease_manager = lease_manager
        self.process_observer_capability = (
            process_observer_capability or process_capability
        )
        self._last_result: ProtectionReadinessResult | None = None

    def evaluate(self) -> ProtectionReadinessResult:
        """Return a derived Readiness result and transition only on success."""

        if (
            self.session.status is SessionStatus.READY
            and self._last_result is not None
            and self._last_result.is_ready
            and self._last_result.readiness_context is not None
        ):
            return self._last_result

        checked_at = _now_utc()
        checks: list[ReadinessCheck] = []
        checks.append(
            _check(
                "SESSION_STATUS",
                self.session.status is SessionStatus.PREPARING,
                "SESSION_NOT_PREPARING",
            )
        )

        binding_ok = self._check_bindings()
        checks.append(_check("SESSION_WORKSPACE_BINDING", binding_ok, "CONTEXT_MISMATCH"))

        active_policy = getattr(self.preparation_context, "active_policy", None)
        policy_ok = self._validate_active_policy(active_policy)
        checks.append(_check("ACTIVE_POLICY", policy_ok, "ACTIVE_POLICY_INVALID"))

        lease_ok, current_lease = self._validate_lease()
        checks.append(_check("WORKSPACE_LEASE", lease_ok, "WORKSPACE_LEASE_INVALID"))

        checkpoint_ok, _checkpoint_result = self._validate_checkpoint()
        checks.append(_check("SAFE_CHECKPOINT", checkpoint_ok, "CHECKPOINT_INVALID"))
        checkpoint_binding_ok = self._checkpoint_binding_ok()
        checks.append(
            _check("CHECKPOINT_BINDING", checkpoint_binding_ok, "CONTEXT_MISMATCH")
        )

        filesystem_status, filesystem_context, filesystem_ok = self._validate_filesystem_sensor()
        checks.append(
            _check("FILESYSTEM_SENSOR", filesystem_ok, "FILESYSTEM_SENSOR_UNHEALTHY")
        )

        hook_status, hook_context, hook_ok = self._validate_hook_sensor()
        checks.append(_check("HOOK_SENSOR", hook_ok, "HOOK_SENSOR_UNHEALTHY"))
        hook_ingress_verified = (
            hook_context.ingress_verified
            if isinstance(hook_context, HookSensorContext)
            else None
        )
        checks.append(
            _check(
                "HOOK_INGRESS_TRUST",
                isinstance(hook_ingress_verified, bool),
                "HOOK_TRUST_STATUS_UNAVAILABLE",
            )
        )

        capability = self.process_observer_capability
        capability_ok = self._validate_process_capability(capability)
        checks.append(
            _check(
                "PROCESS_OBSERVER_CAPABILITY",
                capability_ok,
                "PROCESS_CAPABILITY_UNAVAILABLE",
            )
        )

        current_workspace_fingerprint: str | None = None
        baseline_ok = False
        stability_ok = False
        if checkpoint_ok and checkpoint_binding_ok and filesystem_ok:
            sequence_before = self._filesystem_sequence(filesystem_context)
            try:
                comparison = compare_workspace_to_checkpoint(
                    self.checkpoint,
                    self.session.workspace,
                )
                current_workspace_fingerprint = (
                    comparison.current_workspace_content_sha256
                )
                baseline_ok = comparison.matches
                baseline_reason = comparison.reason
            except UnsupportedFilesystemEntryError as error:
                baseline_reason = getattr(
                    error,
                    "code",
                    "UNSUPPORTED_FILESYSTEM_ENTRY",
                )
            except Exception:
                baseline_reason = "WORKSPACE_DRIFTED_AFTER_CHECKPOINT"
            sequence_after = self._filesystem_sequence(filesystem_context)
            checks.append(
                _check(
                    "WORKSPACE_BASELINE",
                    baseline_ok,
                    baseline_reason if not baseline_ok else None,
                )
            )
            stability_ok = (
                isinstance(sequence_before, int)
                and isinstance(sequence_after, int)
                and sequence_before == sequence_after
            )
            checks.append(
                _check(
                    "WORKSPACE_STABILITY",
                    stability_ok,
                    "WORKSPACE_CHANGED_DURING_READINESS"
                    if not stability_ok
                    else None,
                )
            )
        else:
            checks.append(
                _check("WORKSPACE_BASELINE", False, "DEPENDENCY_NOT_READY")
            )
            checks.append(
                _check("WORKSPACE_STABILITY", False, "DEPENDENCY_NOT_READY")
            )

        if all(item.passed for item in checks):
            try:
                self.session.transition_to(SessionStatus.READY, at=checked_at)
            except Exception:
                checks.append(
                    _check("SESSION_TRANSITION", False, "SESSION_TRANSITION_FAILED")
                )
                return self._result(
                    checked_at=checked_at,
                    checks=checks,
                    active_policy=active_policy,
                    current_workspace_fingerprint=current_workspace_fingerprint,
                    filesystem_status=filesystem_status,
                    hook_status=hook_status,
                    hook_ingress_verified=hook_ingress_verified,
                    capability=capability,
                )
            if self.session.status is not SessionStatus.READY:
                checks.append(
                    _check("SESSION_TRANSITION", False, "SESSION_TRANSITION_FAILED")
                )
                return self._result(
                    checked_at=checked_at,
                    checks=checks,
                    active_policy=active_policy,
                    current_workspace_fingerprint=current_workspace_fingerprint,
                    filesystem_status=filesystem_status,
                    hook_status=hook_status,
                    hook_ingress_verified=hook_ingress_verified,
                    capability=capability,
                )
            checks.append(_check("SESSION_TRANSITION", True))
            result = self._result(
                checked_at=checked_at,
                checks=checks,
                active_policy=active_policy,
                current_workspace_fingerprint=current_workspace_fingerprint,
                filesystem_status=filesystem_status,
                hook_status=hook_status,
                hook_ingress_verified=hook_ingress_verified,
                capability=capability,
                current_lease=current_lease,
            )
            self._last_result = result
            return result

        return self._result(
            checked_at=checked_at,
            checks=checks,
            active_policy=active_policy,
            current_workspace_fingerprint=current_workspace_fingerprint,
            filesystem_status=filesystem_status,
            hook_status=hook_status,
            hook_ingress_verified=hook_ingress_verified,
            capability=capability,
        )

    assess = evaluate
    check = evaluate
    run = evaluate

    def _result(
        self,
        *,
        checked_at: datetime,
        checks: list[ReadinessCheck],
        active_policy: Any,
        current_workspace_fingerprint: str | None,
        filesystem_status: SensorStatus | None,
        hook_status: SensorStatus | None,
        hook_ingress_verified: bool | None,
        capability: ProcessObserverCapability | None,
        current_lease: WorkspaceLease | None = None,
    ) -> ProtectionReadinessResult:
        ready = all(item.passed for item in checks) and self.session.status is SessionStatus.READY
        context: ProtectionReadinessContext | None = None
        if ready and isinstance(active_policy, ActivePolicySnapshot):
            checkpoint = self.checkpoint
            lease = current_lease or self.preparation_context.workspace_lease
            if (
                isinstance(capability, ProcessObserverCapability)
                and isinstance(filesystem_status, SensorStatus)
                and isinstance(hook_status, SensorStatus)
                and isinstance(hook_ingress_verified, bool)
                and current_workspace_fingerprint is not None
            ):
                context = ProtectionReadinessContext(
                    _token=_READINESS_CONTEXT_TOKEN,
                    aia_session_id=self.session.session_id,
                    workspace=self.session.workspace,
                    ready_at=checked_at,
                    active_policy_fingerprint=active_policy.sha256,
                    checkpoint_id=checkpoint.checkpoint_id,
                    checkpoint_content_sha256=checkpoint.checkpoint_content_sha256,
                    current_workspace_content_sha256=current_workspace_fingerprint,
                    workspace_lease_identity=lease,
                    filesystem_sensor_status=filesystem_status,
                    hook_sensor_status=hook_status,
                    hook_ingress_verified=hook_ingress_verified,
                    process_observer_capability=capability,
                    readiness_checks=tuple(checks),
                )
            else:
                ready = False
        result = ProtectionReadinessResult(
            aia_session_id=self.session.session_id,
            workspace=self.session.workspace,
            status=ReadinessStatus.READY if ready else ReadinessStatus.NOT_READY,
            checked_at=checked_at,
            checks=tuple(checks),
            active_policy_fingerprint=(
                active_policy.sha256
                if isinstance(active_policy, ActivePolicySnapshot)
                else None
            ),
            checkpoint_id=(
                self.checkpoint.checkpoint_id
                if isinstance(self.checkpoint, SafeCheckpoint)
                else None
            ),
            checkpoint_content_sha256=(
                self.checkpoint.checkpoint_content_sha256
                if isinstance(self.checkpoint, SafeCheckpoint)
                else None
            ),
            current_workspace_content_sha256=current_workspace_fingerprint,
            filesystem_sensor_status=filesystem_status,
            hook_sensor_status=hook_status,
            hook_ingress_verified=hook_ingress_verified,
            process_observer_capability_status=(
                capability.status.value
                if isinstance(capability, ProcessObserverCapability)
                else ProcessObserverCapabilityStatus.UNAVAILABLE.value
            ),
            readiness_context=context,
        )
        if result.is_ready and context is None:
            return ProtectionReadinessResult(
                aia_session_id=result.aia_session_id,
                workspace=result.workspace,
                status=ReadinessStatus.NOT_READY,
                checked_at=result.checked_at,
                checks=result.checks,
                active_policy_fingerprint=result.active_policy_fingerprint,
                checkpoint_id=result.checkpoint_id,
                checkpoint_content_sha256=result.checkpoint_content_sha256,
                current_workspace_content_sha256=result.current_workspace_content_sha256,
                filesystem_sensor_status=result.filesystem_sensor_status,
                hook_sensor_status=result.hook_sensor_status,
                hook_ingress_verified=result.hook_ingress_verified,
                process_observer_capability_status=result.process_observer_capability_status,
                readiness_context=None,
            )
        return result

    def _check_bindings(self) -> bool:
        context = self.preparation_context
        if not isinstance(context, ProtectionPreparationContext):
            return False
        if context.session_id != self.session.session_id or not _same_workspace(
            context.workspace, self.session.workspace
        ):
            return False
        policy = context.active_policy
        if not isinstance(policy, ActivePolicySnapshot):
            return False
        if (
            policy.session_id != self.session.session_id
            or policy.policy_id != self.session.policy_id
            or policy.policy_version != self.session.policy_version
        ):
            return False
        lease = context.workspace_lease
        if not isinstance(lease, WorkspaceLease) or (
            lease.session_id != self.session.session_id
            or not _same_workspace(lease.workspace, self.session.workspace)
        ):
            return False
        checkpoint = self.checkpoint
        if not isinstance(checkpoint, SafeCheckpoint) or (
            checkpoint.session_id != self.session.session_id
            or not _same_workspace(checkpoint.workspace, self.session.workspace)
        ):
            return False
        for sensor in (self.filesystem_sensor, self.hook_sensor):
            sensor_session = getattr(sensor, "session", None)
            if sensor_session is not None and (
                sensor_session.session_id != self.session.session_id
                or not _same_workspace(sensor_session.workspace, self.session.workspace)
            ):
                return False
            sensor_context = getattr(sensor, "preparation_context", None)
            if not isinstance(sensor_context, ProtectionPreparationContext):
                return False
            if (
                sensor_context.session_id != self.session.session_id
                or not _same_workspace(
                    sensor_context.workspace,
                    self.session.workspace,
                )
            ):
                return False
            sensor_checkpoint = getattr(sensor, "checkpoint", None)
            if not isinstance(sensor_checkpoint, SafeCheckpoint):
                return False
            if (
                sensor_checkpoint.session_id != self.session.session_id
                or not _same_workspace(
                    sensor_checkpoint.workspace,
                    self.session.workspace,
                )
            ):
                return False
        capability = self.process_observer_capability
        if isinstance(capability, ProcessObserverCapability):
            if capability.aia_session_id != self.session.session_id:
                return False
            if capability.workspace is None or not _same_workspace(
                capability.workspace, self.session.workspace
            ):
                return False
        return True

    def _validate_active_policy(self, snapshot: Any) -> bool:
        if not isinstance(snapshot, ActivePolicySnapshot):
            return False
        if (
            snapshot.session_id != self.session.session_id
            or snapshot.policy_id != self.session.policy_id
            or snapshot.policy_version != self.session.policy_version
        ):
            return False
        if (
            snapshot.policy.policy_id != snapshot.policy_id
            or snapshot.policy.policy_version != snapshot.policy_version
        ):
            return False
        try:
            artifact_path = snapshot.artifact_path.resolve(strict=True)
            if not artifact_path.is_file():
                return False
            expected_artifact_path = (
                self.preparation_context.control_directory.resolve(strict=False)
                / "active-policy.json"
            ).resolve(strict=False)
            if artifact_path != expected_artifact_path:
                return False
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            if not isinstance(artifact, dict):
                return False
            resolved = ResolvedPolicy(
                profile=snapshot.profile,
                policy_id=snapshot.policy_id,
                policy_version=snapshot.policy_version,
                source="active-policy-artifact",
                policy=snapshot.policy,
            )
            expected_content = policy_content_mapping(resolved)
            expected_hash = policy_content_sha256(resolved)
            if snapshot.sha256 != expected_hash:
                return False
            if artifact.get("session_id") != self.session.session_id:
                return False
            if artifact.get("policy_content_sha256") != expected_hash:
                return False
            if any(artifact.get(key) != value for key, value in expected_content.items()):
                return False
            frozen_at = artifact.get("frozen_at")
            if not isinstance(frozen_at, str):
                return False
            parsed = datetime.fromisoformat(frozen_at)
            return parsed.tzinfo is not None and parsed.utcoffset() is not None
        except Exception:
            return False

    def _validate_lease(self) -> tuple[bool, WorkspaceLease | None]:
        lease = getattr(self.preparation_context, "workspace_lease", None)
        if not isinstance(lease, WorkspaceLease):
            return False, None
        try:
            manager = self.lease_manager
            if manager is None:
                control_directory = self.preparation_context.control_directory.resolve(
                    strict=True
                )
                manager = WorkspaceLeaseManager(control_directory.parent.parent)
            current = manager.validate_ownership(lease)
            return (
                current.session_id == self.session.session_id
                and _same_workspace(current.workspace, self.session.workspace),
                current,
            )
        except Exception:
            return False, None

    def _validate_checkpoint(self) -> tuple[bool, CheckpointValidity | None]:
        if not isinstance(self.checkpoint, SafeCheckpoint):
            return False, None
        try:
            if self.checkpoint.validity is not CheckpointValidity.VALID:
                return False, self.checkpoint.validity
            result = validate_checkpoint(self.checkpoint)
            if not result.is_valid:
                return False, result.validity
            metadata = json.loads(
                self.checkpoint.metadata_path.read_text(encoding="utf-8")
            )
            if not isinstance(metadata, dict):
                return False, CheckpointValidity.INVALID
            if (
                metadata.get("checkpoint_id") != self.checkpoint.checkpoint_id
                or metadata.get("session_id") != self.session.session_id
                or not _same_workspace(
                    metadata.get("workspace", ""),
                    self.session.workspace,
                )
                or metadata.get("checkpoint_content_sha256")
                != self.checkpoint.checkpoint_content_sha256
                or metadata.get("manifest_sha256") != self.checkpoint.manifest_sha256
            ):
                return False, CheckpointValidity.INVALID
            return result.is_valid, result.validity
        except Exception:
            return False, CheckpointValidity.INVALID

    def _checkpoint_binding_ok(self) -> bool:
        return isinstance(self.checkpoint, SafeCheckpoint) and (
            self.checkpoint.session_id == self.session.session_id
            and _same_workspace(self.checkpoint.workspace, self.session.workspace)
        )

    def _validate_filesystem_sensor(
        self,
    ) -> tuple[SensorStatus | None, FilesystemSensorContext | None, bool]:
        if not isinstance(self.filesystem_sensor, FilesystemSensor):
            return None, None, False
        try:
            status = self.filesystem_sensor.check_health().status
            context = self.filesystem_sensor.context
            observer = self.filesystem_sensor.observer
            observer_alive = observer is not None and (
                not hasattr(observer, "is_alive") or bool(observer.is_alive())
            )
            evidence_store = self.filesystem_sensor.evidence_store
            evidence_bound = (
                evidence_store.session_id in {None, self.session.session_id}
                and self._evidence_path_bound(context.evidence_path)
            )
            passed = (
                status is SensorStatus.HEALTHY
                and isinstance(context, FilesystemSensorContext)
                and context.status is SensorStatus.HEALTHY
                and context.session_id == self.session.session_id
                and _same_workspace(context.workspace, self.session.workspace)
                and observer_alive
                and evidence_bound
            )
            return status, context, passed
        except Exception:
            return getattr(self.filesystem_sensor, "status", None), None, False

    def _validate_hook_sensor(
        self,
    ) -> tuple[SensorStatus | None, HookSensorContext | None, bool]:
        if not isinstance(self.hook_sensor, HookSensor):
            return None, None, False
        try:
            status = self.hook_sensor.check_health().status
            context = self.hook_sensor.context
            evidence_store = self.hook_sensor.evidence_store
            evidence_bound = (
                evidence_store.session_id in {None, self.session.session_id}
                and self._evidence_path_bound(context.evidence_path)
            )
            passed = (
                status is SensorStatus.HEALTHY
                and isinstance(context, HookSensorContext)
                and context.status is SensorStatus.HEALTHY
                and context.aia_session_id == self.session.session_id
                and _same_workspace(context.workspace, self.session.workspace)
                and evidence_bound
            )
            return status, context, passed
        except Exception:
            return getattr(self.hook_sensor, "status", None), None, False

    def _evidence_path_bound(self, evidence_path: Path) -> bool:
        try:
            expected_root = (
                self.preparation_context.control_directory.resolve(strict=False)
                / "evidence"
            ).resolve(strict=False)
            return Path(evidence_path).resolve(strict=False).is_relative_to(expected_root)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _filesystem_sequence(
        self,
        context: FilesystemSensorContext | None,
    ) -> int | None:
        if context is None:
            return None
        live_value = getattr(self.filesystem_sensor, "observation_sequence", None)
        if isinstance(live_value, int):
            return live_value
        value = getattr(context, "observation_sequence", None)
        if isinstance(value, int):
            return value
        return None

    def _validate_process_capability(
        self,
        capability: ProcessObserverCapability | None,
    ) -> bool:
        return (
            isinstance(capability, ProcessObserverCapability)
            and capability.sensor_source is EvidenceSource.PROCESS_RUNTIME
            and capability.available
            and capability.aia_session_id == self.session.session_id
            and capability.workspace is not None
            and _same_workspace(capability.workspace, self.session.workspace)
            and capability.polling_interval > 0
            and callable(capability.process_factory)
        )


ReadinessBarrier = ProtectionReadinessBarrier


def evaluate_readiness(
    session: ProtectedRunSession,
    preparation_context: ProtectionPreparationContext,
    checkpoint: SafeCheckpoint,
    filesystem_sensor: FilesystemSensor,
    hook_sensor: HookSensor,
    process_observer_capability: ProcessObserverCapability | None = None,
    *,
    lease_manager: WorkspaceLeaseManager | None = None,
) -> ProtectionReadinessResult:
    """Evaluate one Readiness attempt through a new Barrier instance."""

    return ProtectionReadinessBarrier(
        session,
        preparation_context,
        checkpoint,
        filesystem_sensor,
        hook_sensor,
        process_observer_capability,
        lease_manager=lease_manager,
    ).evaluate()


check_readiness = evaluate_readiness


__all__ = [
    "ProtectionReadinessContext",
    "ProtectionReadinessBarrier",
    "ProtectionReadinessResult",
    "ReadinessBarrier",
    "ReadinessCheck",
    "ReadinessError",
    "ReadinessStatus",
    "check_readiness",
    "evaluate_readiness",
]
