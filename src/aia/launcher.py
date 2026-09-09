"""Protected Agent launch domain and startup lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
from pathlib import Path
import subprocess
import time
from types import MappingProxyType
from typing import Any, Callable, Protocol
from uuid import uuid4

import psutil

from .checkpoint import SafeCheckpoint
from .process_identity import (
    ProcessIdentity,
    ProcessIdentityStatus,
    RootProcessRegistration,
    inspect_process_identity,
)
from .protection import ProtectionPreparationContext, WorkspaceLeaseManager
from .readiness import (
    ProtectionReadinessBarrier,
    ProtectionReadinessContext,
)
from .session import ProtectedRunSession, SessionStatus, canonicalize_workspace
from .sensors.base import SensorStatus
from .sensors.filesystem import FilesystemSensor
from .sensors.hook import HookSensor
from .sensors.process import ProcessRuntimeSensor, ProcessRuntimeSensorContext


class LauncherError(ValueError):
    """Base error for protected launch operations."""


class AdapterError(LauncherError):
    """Raised when an Agent Adapter cannot provide a launch plan."""


class AdapterUnavailableError(AdapterError):
    """Raised when the requested Agent executable cannot be resolved."""

    code = "ADAPTER_UNAVAILABLE"


class LaunchStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


class LaunchCleanupStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LauncherError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ProtectedLaunchRequest:
    """Input to one protected Agent launch attempt."""

    aia_session_id: str
    workspace: Path | str
    agent: str
    prompt: str = field(repr=False)
    model: str | None = None
    resume_native_session_id: str | None = None
    adapter_options: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aia_session_id",
            _required_text(self.aia_session_id, field_name="aia_session_id"),
        )
        object.__setattr__(self, "workspace", canonicalize_workspace(self.workspace))
        object.__setattr__(self, "agent", _required_text(self.agent, field_name="agent"))
        object.__setattr__(self, "prompt", _required_text(self.prompt, field_name="prompt"))
        if self.model is not None:
            object.__setattr__(self, "model", _required_text(self.model, field_name="model"))
        if self.resume_native_session_id is not None:
            object.__setattr__(
                self,
                "resume_native_session_id",
                _required_text(
                    self.resume_native_session_id,
                    field_name="resume_native_session_id",
                ),
            )
        if not isinstance(self.adapter_options, Mapping):
            raise LauncherError("adapter_options must be a mapping")
        object.__setattr__(
            self,
            "adapter_options",
            MappingProxyType(dict(self.adapter_options)),
        )

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class AgentLaunchSpec:
    """Adapter output used by the Launcher to spawn one process."""

    adapter: str
    executable: Path | str
    argv: tuple[str, ...]
    stdin_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _required_text(self.adapter, field_name="adapter"))
        executable = Path(self.executable).expanduser().resolve(strict=False)
        if not executable.is_absolute():
            raise LauncherError("executable must be absolute")
        object.__setattr__(self, "executable", executable)
        argv = tuple(self.argv)
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise LauncherError("argv must contain non-empty strings")
        if argv[0] != str(executable):
            raise LauncherError("argv executable does not match resolved executable")
        object.__setattr__(self, "argv", argv)
        if not isinstance(self.stdin_bytes, bytes):
            raise LauncherError("stdin_bytes must be bytes")


@dataclass(frozen=True, slots=True)
class AgentRuntimeMetadata:
    """Optional metadata parsed from an Agent runtime stream."""

    agent_native_session_id: str | None = None


class AgentAdapter(Protocol):
    """Boundary between the product Launcher and one Agent CLI."""

    @property
    def name(self) -> str: ...

    def discover(self) -> Path: ...

    def build_launch(
        self,
        request: ProtectedLaunchRequest,
        executable: Path,
    ) -> AgentLaunchSpec: ...

    def parse_runtime_metadata(self, line: str) -> AgentRuntimeMetadata | None: ...


@dataclass(frozen=True, slots=True)
class ProtectedLaunchContext:
    launch_id: str
    aia_session_id: str
    workspace: Path
    agent: str
    adapter: str
    executable: Path
    prompt_sha256: str
    root_process_identity: ProcessIdentity
    root_registration: RootProcessRegistration
    process_sensor_context: ProcessRuntimeSensorContext
    spawned_at: datetime
    identity_registered_at: datetime
    process_sensor_healthy_at: datetime
    running_at: datetime
    launch_provenance: str
    agent_native_session_id: str | None = None
    spawn_to_identity_ms: float = 0.0
    spawn_to_process_sensor_healthy_ms: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", canonicalize_workspace(self.workspace))
        for field_name in (
            "spawned_at",
            "identity_registered_at",
            "process_sensor_healthy_at",
            "running_at",
        ):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise LauncherError(f"{field_name} must be timezone-aware")
            object.__setattr__(self, field_name, value.astimezone(timezone.utc))
        for field_name in (
            "spawn_to_identity_ms",
            "spawn_to_process_sensor_healthy_ms",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise LauncherError(f"{field_name} must be non-negative")


@dataclass(frozen=True, slots=True)
class ProtectedLaunchResult:
    launch_id: str
    status: LaunchStatus
    failure_code: str | None
    cleanup_status: LaunchCleanupStatus
    context: ProtectedLaunchContext | None
    checked_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", LaunchStatus(self.status))
        object.__setattr__(self, "cleanup_status", LaunchCleanupStatus(self.cleanup_status))
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise LauncherError("checked_at must be timezone-aware")
        object.__setattr__(self, "checked_at", self.checked_at.astimezone(timezone.utc))


class _LaunchStepError(LauncherError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProtectedLauncher:
    """Spawn an Agent only after protection revalidation and root registration."""

    def __init__(
        self,
        session: ProtectedRunSession,
        readiness_context: ProtectionReadinessContext,
        preparation_context: ProtectionPreparationContext,
        checkpoint: SafeCheckpoint,
        filesystem_sensor: FilesystemSensor,
        hook_sensor: HookSensor,
        *,
        adapter: AgentAdapter | None = None,
        lease_manager: WorkspaceLeaseManager | None = None,
        process_factory: Callable[[int], Any] = psutil.Process,
        process_sensor_factory: Callable[..., ProcessRuntimeSensor] = ProcessRuntimeSensor,
        popen_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.session = session
        self.readiness_context = readiness_context
        self.preparation_context = preparation_context
        self.checkpoint = checkpoint
        self.filesystem_sensor = filesystem_sensor
        self.hook_sensor = hook_sensor
        self.adapter = adapter
        self.lease_manager = lease_manager
        self.process_factory = process_factory
        self.process_sensor_factory = process_sensor_factory
        self.popen_factory = popen_factory
        self._status = LaunchStatus.NOT_STARTED
        self._process_handle: Any | None = None
        self._process_sensor: ProcessRuntimeSensor | None = None
        self._last_result: ProtectedLaunchResult | None = None

    @property
    def status(self) -> LaunchStatus:
        return self._status

    @property
    def process_handle(self) -> Any | None:
        return self._process_handle

    @property
    def process_sensor(self) -> ProcessRuntimeSensor | None:
        return self._process_sensor

    def launch(self, request: ProtectedLaunchRequest) -> ProtectedLaunchResult:
        launch_id = str(uuid4())
        if self.session.status is not SessionStatus.READY:
            return self._failed_result(
                launch_id,
                "SESSION_NOT_READY",
                cleanup_status=LaunchCleanupStatus.NOT_ATTEMPTED,
            )
        self._status = LaunchStatus.STARTING
        self._process_handle = None
        self._process_sensor = None
        identity: ProcessIdentity | None = None
        sensor: ProcessRuntimeSensor | None = None
        spawned_perf: float | None = None
        spawned_at: datetime | None = None
        try:
            self._validate_request(request)
            revalidation = self._readiness_barrier().revalidate_ready_context(
                self.readiness_context
            )
            if not revalidation.passed:
                raise _LaunchStepError("LAUNCH_REFUSED")

            adapter = self.adapter or self._default_adapter()
            executable = adapter.discover()
            spec = adapter.build_launch(request, executable)
            spawned_perf = time.perf_counter()
            spawned_at = _now_utc()
            process = self.popen_factory(
                list(spec.argv),
                shell=False,
                cwd=str(self.session.workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._process_handle = process
            self._write_stdin(process, spec.stdin_bytes)

            identity, identity_registered_at = self._capture_identity(process)
            registration = RootProcessRegistration(
                aia_session_id=self.session.session_id,
                workspace=self.session.workspace,
                root_process_identity=identity,
                registered_at=identity_registered_at,
                registration_source="PROTECTED_LAUNCHER",
            )
            sensor = self.process_sensor_factory(
                self.session,
                self.preparation_context,
                self.checkpoint,
                registration,
                lease_manager=self.lease_manager,
                process_factory=self.process_factory,
                allow_ready=True,
            )
            self._process_sensor = sensor
            sensor.start()
            process_sensor_healthy_at = _now_utc()
            if sensor.check_health().status is not SensorStatus.HEALTHY:
                raise _LaunchStepError("PROCESS_SENSOR_UNHEALTHY")
            self._require_root_evidence(sensor, identity)

            final_revalidation = self._readiness_barrier().revalidate_ready_context(
                self.readiness_context
            )
            if not final_revalidation.passed:
                raise _LaunchStepError("FINAL_VERIFICATION_FAILED")
            final_root_status, _ = inspect_process_identity(
                identity,
                process_factory=self.process_factory,
            )
            if final_root_status is not ProcessIdentityStatus.LIVE_MATCH:
                raise _LaunchStepError("PROCESS_EXITED_DURING_STARTUP")
            if sensor.check_health().status is not SensorStatus.HEALTHY:
                raise _LaunchStepError("PROCESS_SENSOR_UNHEALTHY")
            if self.session.status is not SessionStatus.READY:
                raise _LaunchStepError("SESSION_NOT_READY")

            running_at = _now_utc()
            self.session.transition_to(SessionStatus.RUNNING, at=running_at)
            if self.session.status is not SessionStatus.RUNNING:
                raise _LaunchStepError("RUNNING_TRANSITION_FAILED")
            assert spawned_at is not None
            assert spawned_perf is not None
            context = ProtectedLaunchContext(
                launch_id=launch_id,
                aia_session_id=self.session.session_id,
                workspace=self.session.workspace,
                agent=self.session.agent,
                adapter=adapter.name,
                executable=spec.executable,
                prompt_sha256=request.prompt_sha256,
                root_process_identity=identity,
                root_registration=registration,
                process_sensor_context=sensor.context,
                spawned_at=spawned_at,
                identity_registered_at=identity_registered_at,
                process_sensor_healthy_at=process_sensor_healthy_at,
                running_at=running_at,
                launch_provenance="AIA_SPAWNED_ROOT",
                spawn_to_identity_ms=max(
                    0.0,
                    (identity_registered_at - spawned_at).total_seconds() * 1000,
                ),
                spawn_to_process_sensor_healthy_ms=max(
                    0.0,
                    (process_sensor_healthy_at - spawned_at).total_seconds() * 1000,
                ),
            )
            self._status = LaunchStatus.RUNNING
            result = ProtectedLaunchResult(
                launch_id=launch_id,
                status=LaunchStatus.RUNNING,
                failure_code=None,
                cleanup_status=LaunchCleanupStatus.NOT_ATTEMPTED,
                context=context,
                checked_at=running_at,
            )
            self._last_result = result
            return result
        except AdapterUnavailableError as error:
            return self._failed_result(launch_id, error.code, cleanup=False)
        except AdapterError:
            return self._failed_result(launch_id, "ADAPTER_LAUNCH_FAILED", cleanup=False)
        except _LaunchStepError as error:
            cleanup_status = self._startup_cleanup(sensor, identity)
            if cleanup_status is LaunchCleanupStatus.FAILED:
                self._mark_session_failed()
                return self._failed_result(
                    launch_id,
                    "LAUNCH_CLEANUP_FAILED",
                    cleanup_status=cleanup_status,
                )
            if self._should_fail_session(error.code):
                self._mark_session_failed()
            return self._failed_result(
                launch_id,
                error.code,
                cleanup_status=cleanup_status,
            )
        except Exception:
            cleanup_status = self._startup_cleanup(sensor, identity)
            if cleanup_status is LaunchCleanupStatus.FAILED:
                self._mark_session_failed()
                return self._failed_result(
                    launch_id,
                    "LAUNCH_CLEANUP_FAILED",
                    cleanup_status=cleanup_status,
                )
            if (
                self.session.status is SessionStatus.READY
                and self._process_handle is not None
            ):
                self._mark_session_failed()
            return self._failed_result(
                launch_id,
                "LAUNCH_FAILED",
                cleanup_status=cleanup_status,
            )

    start = launch

    def _default_adapter(self) -> AgentAdapter:
        from .adapters.codex import CodexAdapter

        return CodexAdapter()

    def _readiness_barrier(self) -> ProtectionReadinessBarrier:
        return ProtectionReadinessBarrier(
            self.session,
            self.preparation_context,
            self.checkpoint,
            self.filesystem_sensor,
            self.hook_sensor,
            self.readiness_context.process_observer_capability,
            lease_manager=self.lease_manager,
        )

    def _validate_request(self, request: ProtectedLaunchRequest) -> None:
        if not isinstance(request, ProtectedLaunchRequest):
            raise _LaunchStepError("INVALID_LAUNCH_REQUEST")
        if self.session.status is not SessionStatus.READY:
            raise _LaunchStepError("SESSION_NOT_READY")
        if request.aia_session_id != self.session.session_id:
            raise _LaunchStepError("CONTEXT_MISMATCH")
        if request.agent != self.session.agent:
            raise _LaunchStepError("CONTEXT_MISMATCH")
        if request.workspace != self.session.workspace:
            raise _LaunchStepError("CONTEXT_MISMATCH")
        if not isinstance(self.readiness_context, ProtectionReadinessContext):
            raise _LaunchStepError("READINESS_CONTEXT_INVALID")
        if (
            self.readiness_context.aia_session_id != self.session.session_id
            or self.readiness_context.workspace != self.session.workspace
        ):
            raise _LaunchStepError("CONTEXT_MISMATCH")

    @staticmethod
    def _write_stdin(process: Any, value: bytes) -> None:
        stream = getattr(process, "stdin", None)
        if stream is None:
            raise _LaunchStepError("SPAWN_STDIN_UNAVAILABLE")
        try:
            stream.write(value)
            stream.close()
        except (BrokenPipeError, OSError) as error:
            raise _LaunchStepError("SPAWN_STDIN_FAILED") from error

    def _capture_identity(
        self,
        process: Any,
    ) -> tuple[ProcessIdentity, datetime]:
        try:
            pid = int(process.pid)
            process_object = self.process_factory(pid)
            create_time = float(process_object.create_time())
            identity = ProcessIdentity(pid, create_time)
        except Exception as error:
            raise _LaunchStepError("PROCESS_EXITED_BEFORE_REGISTRATION") from error
        status, _ = inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )
        if status is not ProcessIdentityStatus.LIVE_MATCH:
            if status is ProcessIdentityStatus.PID_REUSED:
                raise _LaunchStepError("PID_REUSED")
            if status is ProcessIdentityStatus.OWNER_UNVERIFIABLE:
                raise _LaunchStepError("OWNER_UNVERIFIABLE")
            raise _LaunchStepError("PROCESS_EXITED_BEFORE_REGISTRATION")
        return identity, _now_utc()

    @staticmethod
    def _require_root_evidence(
        sensor: ProcessRuntimeSensor,
        identity: ProcessIdentity,
    ) -> None:
        try:
            records = sensor.evidence_store.records()
        except Exception as error:
            raise _LaunchStepError("ROOT_EVIDENCE_UNAVAILABLE") from error
        if not any(
            record.record_type.value == "PROCESS_OBSERVED"
            and record.payload.get("process_role") == "ROOT"
            and record.payload.get("pid") == identity.pid
            and record.payload.get("create_time") == identity.create_time
            for record in records
        ):
            raise _LaunchStepError("ROOT_EVIDENCE_MISSING")

    def _startup_cleanup(
        self,
        sensor: ProcessRuntimeSensor | None,
        identity: ProcessIdentity | None,
    ) -> LaunchCleanupStatus:
        if sensor is not None:
            try:
                sensor.stop()
            except Exception:
                pass
        if identity is None:
            process = self._process_handle
            if process is None:
                return LaunchCleanupStatus.NOT_ATTEMPTED
            try:
                if process.poll() is not None:
                    return LaunchCleanupStatus.SUCCEEDED
            except Exception:
                pass
            # A PID-only termination would violate the identity contract.
            return LaunchCleanupStatus.FAILED
        try:
            status, root = inspect_process_identity(
                identity,
                process_factory=self.process_factory,
            )
            if status is ProcessIdentityStatus.PROCESS_GONE:
                return LaunchCleanupStatus.SUCCEEDED
            if status is not ProcessIdentityStatus.LIVE_MATCH or root is None:
                return LaunchCleanupStatus.FAILED
            descendants = list(root.children(recursive=True))
            for child in reversed(descendants):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            try:
                root.terminate()
            except psutil.Error:
                pass
            _, alive = psutil.wait_procs(descendants + [root], timeout=2)
            for process in alive:
                try:
                    process.kill()
                except psutil.Error:
                    pass
            _, still_alive = psutil.wait_procs(alive, timeout=2)
            return (
                LaunchCleanupStatus.SUCCEEDED
                if not still_alive
                else LaunchCleanupStatus.FAILED
            )
        except Exception:
            return LaunchCleanupStatus.FAILED

    def _mark_session_failed(self) -> None:
        if self.session.status is SessionStatus.READY:
            try:
                self.session.transition_to(SessionStatus.FAILED)
            except Exception:
                pass

    def _should_fail_session(self, failure_code: str) -> bool:
        return self.session.status is SessionStatus.READY and (
            self._process_handle is not None
            or failure_code
            in {
                "LAUNCH_REFUSED",
                "CONTEXT_MISMATCH",
                "READINESS_CONTEXT_INVALID",
            }
        )

    def _failed_result(
        self,
        launch_id: str,
        failure_code: str,
        *,
        cleanup: bool | None = None,
        cleanup_status: LaunchCleanupStatus | None = None,
    ) -> ProtectedLaunchResult:
        if cleanup_status is None:
            cleanup_status = (
                LaunchCleanupStatus.SUCCEEDED
                if cleanup
                else LaunchCleanupStatus.NOT_ATTEMPTED
            )
        self._status = LaunchStatus.FAILED
        result = ProtectedLaunchResult(
            launch_id=launch_id,
            status=LaunchStatus.FAILED,
            failure_code=failure_code,
            cleanup_status=cleanup_status,
            context=None,
            checked_at=_now_utc(),
        )
        self._last_result = result
        return result


__all__ = [
    "AdapterError",
    "AdapterUnavailableError",
    "AgentAdapter",
    "AgentLaunchSpec",
    "AgentRuntimeMetadata",
    "LaunchCleanupStatus",
    "LaunchStatus",
    "LauncherError",
    "ProtectedLaunchContext",
    "ProtectedLaunchRequest",
    "ProtectedLaunchResult",
    "ProtectedLauncher",
]
