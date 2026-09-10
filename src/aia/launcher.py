"""Protected Agent launch domain and startup lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import os
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
from .process_manager import (
    ManagedProcess,
    ManagedProcessRegistry,
    ManagedRootConflictError,
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
from .pretool_enforcement import HookEnforcementBridge


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


def _identity_from_process(process: Any) -> ProcessIdentity:
    return ProcessIdentity(int(process.pid), float(process.create_time()))


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
    prompt: str = field(default="", repr=False)
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
        if not isinstance(self.adapter_options, Mapping):
            raise LauncherError("adapter_options must be a mapping")
        object.__setattr__(
            self,
            "adapter_options",
            MappingProxyType(dict(self.adapter_options)),
        )
        if not isinstance(self.prompt, str):
            raise LauncherError("prompt must be a string")
        interactive = self.adapter_options.get("interactive", False)
        if not isinstance(interactive, bool):
            raise LauncherError("interactive must be a boolean")
        if not interactive:
            object.__setattr__(
                self,
                "prompt",
                _required_text(self.prompt, field_name="prompt"),
            )
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
    interactive: bool = False

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
        if not isinstance(self.interactive, bool):
            raise LauncherError("interactive must be a boolean")


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
    hook_enforcement_ready_at: datetime | None = None

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
        if self.hook_enforcement_ready_at is not None:
            if (
                self.hook_enforcement_ready_at.tzinfo is None
                or self.hook_enforcement_ready_at.utcoffset() is None
            ):
                raise LauncherError("hook_enforcement_ready_at must be timezone-aware")
            object.__setattr__(
                self,
                "hook_enforcement_ready_at",
                self.hook_enforcement_ready_at.astimezone(timezone.utc),
            )
        for field_name in (
            "spawn_to_identity_ms",
            "spawn_to_process_sensor_healthy_ms",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise LauncherError(f"{field_name} must be non-negative")

    @property
    def hook_bridge_ready(self) -> bool:
        return self.hook_enforcement_ready_at is not None


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


@dataclass(frozen=True, slots=True)
class UserAbortTerminationResult:
    """Auditable result for an explicit user stop request.

    This remains separate from ``ProcessTerminationResult`` because a user
    stop is session control, not a policy Enforcement action.
    """

    termination_id: str
    status: str
    outcome: str
    root_pid: int
    root_create_time: float
    verified_tree_gone: bool
    requested_at: datetime
    completed_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.termination_id.strip():
            raise LauncherError("termination_id must be non-empty")
        if self.status not in {"SUCCEEDED", "FAILED"}:
            raise LauncherError("status must be SUCCEEDED or FAILED")
        if self.outcome not in {"TERMINATED", "ALREADY_EXITED", "FAILED"}:
            raise LauncherError("unsupported user abort outcome")
        if self.root_pid < 0 or self.root_create_time < 0:
            raise LauncherError("root process identity must be non-negative")
        for field_name in ("requested_at", "completed_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise LauncherError(f"{field_name} must be timezone-aware")
            object.__setattr__(self, field_name, value.astimezone(timezone.utc))
        if self.status == "SUCCEEDED" and not self.verified_tree_gone:
            raise LauncherError("successful user abort requires verified_tree_gone")

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCEEDED" and self.verified_tree_gone

    def to_mapping(self) -> dict[str, Any]:
        return {
            "termination_id": self.termination_id,
            "status": self.status,
            "outcome": self.outcome,
            "root_pid": self.root_pid,
            "root_create_time": self.root_create_time,
            "verified_tree_gone": self.verified_tree_gone,
            "requested_at": self.requested_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "reason": self.reason,
        }


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
        hook_bridge: HookEnforcementBridge | None = None,
        managed_process_registry: ManagedProcessRegistry | None = None,
        process_factory: Callable[[int], Any] = psutil.Process,
        process_sensor_factory: Callable[..., ProcessRuntimeSensor] = ProcessRuntimeSensor,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        hook_broker_factory: Callable[[str, HookEnforcementBridge], Any] | None = None,
        launch_context_callback: Callable[[ProtectedLaunchContext], None] | None = None,
    ) -> None:
        self.session = session
        self.readiness_context = readiness_context
        self.preparation_context = preparation_context
        self.checkpoint = checkpoint
        self.filesystem_sensor = filesystem_sensor
        self.hook_sensor = hook_sensor
        self.adapter = adapter
        self.lease_manager = lease_manager
        self.hook_bridge = hook_bridge or HookEnforcementBridge()
        self.managed_process_registry = (
            managed_process_registry or ManagedProcessRegistry()
        )
        self.process_factory = process_factory
        self.process_sensor_factory = process_sensor_factory
        self.popen_factory = popen_factory
        self.hook_broker_factory = hook_broker_factory
        self.launch_context_callback = launch_context_callback
        self._status = LaunchStatus.NOT_STARTED
        self._process_handle: Any | None = None
        self._process_sensor: ProcessRuntimeSensor | None = None
        self._hook_broker: Any | None = None
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

    @property
    def hook_broker(self) -> Any | None:
        return self._hook_broker

    def stop_hook_broker(self) -> None:
        """Stop the per-launch local Hook transport after the Agent exits."""

        broker, self._hook_broker = self._hook_broker, None
        if broker is not None:
            broker.stop()

    def request_user_abort(self) -> bool:
        """Stop the registered Agent tree for an explicit user abort.

        This is a session-control operation, not a policy enforcement result.
        It therefore does not manufacture a Gate decision or a TERMINATED
        enforcement action.  The caller records ``USER_ABORT`` during session
        finalization.  Every process identity is rechecked before and after
        termination so a reused PID cannot be treated as the managed Agent.
        """

        result = self.request_user_abort_result()
        return result.succeeded if result is not None else False

    def request_user_abort_result(self) -> UserAbortTerminationResult | None:
        """Return the verified result of an explicit user stop request."""

        requested_at = _now_utc()
        launch = self._last_result
        context = launch.context if launch is not None else None
        if context is None or launch.status is not LaunchStatus.RUNNING:
            return None
        identity = context.root_process_identity
        termination_id = str(uuid4())
        root_status, _ = inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )
        if root_status is ProcessIdentityStatus.PROCESS_GONE:
            return UserAbortTerminationResult(
                termination_id=termination_id,
                status="SUCCEEDED",
                outcome="ALREADY_EXITED",
                root_pid=identity.pid,
                root_create_time=identity.create_time,
                verified_tree_gone=True,
                requested_at=requested_at,
                completed_at=_now_utc(),
            )
        if root_status is not ProcessIdentityStatus.LIVE_MATCH:
            return UserAbortTerminationResult(
                termination_id=termination_id,
                status="FAILED",
                outcome="FAILED",
                root_pid=identity.pid,
                root_create_time=identity.create_time,
                verified_tree_gone=False,
                requested_at=requested_at,
                completed_at=_now_utc(),
                reason=f"ROOT_{root_status.value}",
            )
        succeeded = self._terminate_verified_tree(identity)
        return UserAbortTerminationResult(
            termination_id=termination_id,
            status="SUCCEEDED" if succeeded else "FAILED",
            outcome="TERMINATED" if succeeded else "FAILED",
            root_pid=identity.pid,
            root_create_time=identity.create_time,
            verified_tree_gone=succeeded,
            requested_at=requested_at,
            completed_at=_now_utc(),
            reason=None if succeeded else "PROCESS_TREE_TERMINATION_INCOMPLETE",
        )

    def _terminate_verified_tree(
        self,
        root_identity: ProcessIdentity,
        *,
        wait_seconds: float = 2.0,
    ) -> bool:
        root_status, root = inspect_process_identity(
            root_identity,
            process_factory=self.process_factory,
        )
        if root_status is ProcessIdentityStatus.PROCESS_GONE:
            return True
        if root_status is not ProcessIdentityStatus.LIVE_MATCH or root is None:
            return False

        descendants: list[tuple[int, ProcessIdentity]] = []
        try:
            candidates = root.children(recursive=True)
        except psutil.Error:
            return False
        for candidate in candidates:
            try:
                identity = _identity_from_process(candidate)
            except (OSError, psutil.Error, TypeError, ValueError):
                return False
            status, _ = inspect_process_identity(
                identity,
                process_factory=self.process_factory,
            )
            if status is ProcessIdentityStatus.PROCESS_GONE:
                continue
            if status is not ProcessIdentityStatus.LIVE_MATCH:
                return False
            depth = self._verified_descendant_depth(candidate, root_identity)
            if depth is None:
                return False
            descendants.append((depth, identity))

        # Descendants must stop before their parent.  The final identity check
        # is performed even if an earlier termination call reports an error.
        descendants.sort(key=lambda item: (-item[0], item[1].pid, item[1].create_time))
        all_identities = [root_identity, *(identity for _, identity in descendants)]
        success = True
        for _, identity in descendants:
            success = self._terminate_verified_identity(identity, wait_seconds) and success
        success = self._terminate_verified_identity(root_identity, wait_seconds) and success
        for identity in all_identities:
            status, _ = inspect_process_identity(
                identity,
                process_factory=self.process_factory,
            )
            if status is not ProcessIdentityStatus.PROCESS_GONE:
                success = False
        return success

    def _verified_descendant_depth(
        self,
        process: Any,
        root_identity: ProcessIdentity,
    ) -> int | None:
        current = process
        seen: set[int] = set()
        depth = 0
        while True:
            try:
                pid = int(current.pid)
            except (AttributeError, TypeError, ValueError):
                return None
            if pid in seen:
                return None
            seen.add(pid)
            try:
                parent = current.parent()
            except psutil.Error:
                return None
            if parent is None:
                return None
            try:
                parent_identity = _identity_from_process(parent)
            except (OSError, psutil.Error, TypeError, ValueError):
                return None
            depth += 1
            if parent_identity == root_identity:
                return depth
            parent_status, _ = inspect_process_identity(
                parent_identity,
                process_factory=self.process_factory,
            )
            if parent_status is not ProcessIdentityStatus.LIVE_MATCH:
                return None
            current = parent

    def _terminate_verified_identity(
        self,
        identity: ProcessIdentity,
        wait_seconds: float,
    ) -> bool:
        status, process = inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )
        if status is ProcessIdentityStatus.PROCESS_GONE:
            return True
        if status is not ProcessIdentityStatus.LIVE_MATCH or process is None:
            return False
        try:
            process.terminate()
        except psutil.Error:
            return False
        status = self._wait_for_identity(identity, wait_seconds)
        if status is ProcessIdentityStatus.PROCESS_GONE:
            return True
        if status is not ProcessIdentityStatus.LIVE_MATCH:
            return False
        status, process = inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )
        if status is not ProcessIdentityStatus.LIVE_MATCH or process is None:
            return status is ProcessIdentityStatus.PROCESS_GONE
        try:
            process.kill()
        except psutil.Error:
            return False
        return self._wait_for_identity(identity, wait_seconds) is ProcessIdentityStatus.PROCESS_GONE

    def _wait_for_identity(
        self,
        identity: ProcessIdentity,
        timeout_seconds: float,
    ) -> ProcessIdentityStatus:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            status, _ = inspect_process_identity(
                identity,
                process_factory=self.process_factory,
            )
            if status is not ProcessIdentityStatus.LIVE_MATCH:
                return status
            if time.monotonic() >= deadline:
                return status
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

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
            hook_enforcement_ready_at = self.hook_bridge.prepare(
                aia_session_id=self.session.session_id,
                launch_id=launch_id,
                workspace=self.session.workspace,
                control_directory=self.preparation_context.control_directory,
            )
            popen_kwargs: dict[str, Any] = {
                "shell": False,
                "cwd": str(self.session.workspace),
            }
            if not spec.interactive:
                popen_kwargs.update(
                    {
                        "stdin": subprocess.PIPE,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                    }
                )
            if self.hook_broker_factory is not None:
                broker = self.hook_broker_factory(launch_id, self.hook_bridge)
                if broker is None:
                    raise _LaunchStepError("HOOK_BROKER_UNAVAILABLE")
                broker.start()
                self._hook_broker = broker
                popen_kwargs["env"] = self._child_environment(broker.environment)
            spawned_perf = time.perf_counter()
            spawned_at = _now_utc()
            process = self.popen_factory(
                list(spec.argv),
                **popen_kwargs,
            )
            self._process_handle = process

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
            try:
                self.managed_process_registry.register(
                    ManagedProcess(
                        aia_session_id=self.session.session_id,
                        launch_id=launch_id,
                        workspace=self.session.workspace,
                        root_process_identity=identity,
                        launch_provenance="AIA_SPAWNED_ROOT",
                        registered_at=identity_registered_at,
                        executable=spec.executable,
                    )
                )
            except ManagedRootConflictError as error:
                raise _LaunchStepError("MANAGED_ROOT_CONFLICT") from error

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
                hook_enforcement_ready_at=hook_enforcement_ready_at,
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
            if self.launch_context_callback is not None:
                self.launch_context_callback(context)
            # A spawned process is not an activated protected task.  The task
            # prompt is released only after identity, sensors, bridge, and
            # Session RUNNING have all been established.
            if not spec.interactive:
                self._write_stdin(process, spec.stdin_bytes)
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
            self.stop_hook_broker()
            return self._failed_result(launch_id, error.code, cleanup=False)
        except AdapterError:
            self.stop_hook_broker()
            return self._failed_result(launch_id, "ADAPTER_LAUNCH_FAILED", cleanup=False)
        except _LaunchStepError as error:
            cleanup_status = self._startup_cleanup(sensor, identity)
            self.stop_hook_broker()
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
            self.stop_hook_broker()
            if cleanup_status is LaunchCleanupStatus.FAILED:
                self._mark_session_failed()
                return self._failed_result(
                    launch_id,
                    "LAUNCH_CLEANUP_FAILED",
                    cleanup_status=cleanup_status,
                )
            if (
                self.session.status in {SessionStatus.READY, SessionStatus.RUNNING}
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

    @staticmethod
    def _child_environment(broker_environment: Mapping[str, str]) -> dict[str, str]:
        """Build an isolated Codex environment for a Protected Run.

        AIA may itself be started from a Codex terminal.  In that case the
        parent environment can contain the outer Codex session identity and
        permission profile.  Passing those values through would let the
        protected child inherit the wrong session boundary.  ``CODEX_HOME``
        remains available for the user's authentication, Hook configuration,
        and profiles; the transient ``CODEX_*`` control values are removed.
        """

        child_environment = os.environ.copy()
        for key in tuple(child_environment):
            if key.startswith("CODEX_") and key != "CODEX_HOME":
                child_environment.pop(key, None)
        child_environment.update(broker_environment)
        return child_environment

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
        return (
            LaunchCleanupStatus.SUCCEEDED
            if self._terminate_verified_tree(identity)
            else LaunchCleanupStatus.FAILED
        )

    def _mark_session_failed(self) -> None:
        if self.session.status in {SessionStatus.READY, SessionStatus.RUNNING}:
            try:
                self.session.transition_to(SessionStatus.FAILED)
            except Exception:
                pass

    def _should_fail_session(self, failure_code: str) -> bool:
        return self.session.status in {SessionStatus.READY, SessionStatus.RUNNING} and (
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
    "UserAbortTerminationResult",
]
