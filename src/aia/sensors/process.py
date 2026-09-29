"""psutil-backed Process Runtime Raw Evidence sensor."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from pathlib import Path
import subprocess
from threading import Event, RLock, Thread, current_thread
from typing import Any

import psutil

from ..checkpoint import CheckpointValidity, SafeCheckpoint, validate_checkpoint
from ..evidence import (
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)
from ..process_identity import (
    ProcessIdentity,
    ProcessIdentityStatus,
    ProcessFactory,
    RootProcessRegistration,
    inspect_process_identity,
)
from ..protection import (
    ControlRoot,
    ProtectionPreparationContext,
    WorkspaceLeaseManager,
)
from ..session import ProtectedRunSession, SessionStatus
from .base import (
    SensorAlreadyRunningError,
    SensorError,
    SensorHealth,
    SensorStartError,
    SensorStatus,
    SensorStopError,
)


class ProcessRuntimeError(SensorError):
    """Base error for Process Runtime observation."""


class RootProcessGoneError(SensorStartError):
    code = "ROOT_PROCESS_GONE"


class RootProcessReusedError(SensorStartError):
    code = "ROOT_PID_REUSED"


class RootProcessUnverifiableError(SensorStartError):
    code = "OWNER_UNVERIFIABLE"


class ProcessEvidenceStoreError(ProcessRuntimeError):
    code = "EVIDENCE_STORE_FAILURE"


class ProcessTreeEnumerationError(ProcessRuntimeError):
    """Raised when a managed process tree cannot be safely enumerated."""

    code = "OWNER_UNVERIFIABLE"


class ProcessRole(StrEnum):
    ROOT = "ROOT"
    DESCENDANT = "DESCENDANT"


class ProcessMetadataStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ProcessObserverCapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ProcessObserverCapability:
    """Validated Process Runtime configuration without starting a process."""

    sensor_source: EvidenceSource = EvidenceSource.PROCESS_RUNTIME
    polling_interval: float = 0.25
    configured: bool = True
    process_factory: ProcessFactory = psutil.Process
    aia_session_id: str | None = None
    workspace: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensor_source", EvidenceSource(self.sensor_source))
        if self.sensor_source is not EvidenceSource.PROCESS_RUNTIME:
            raise ProcessRuntimeError(
                "Process Observer Capability must use PROCESS_RUNTIME"
            )
        if not isinstance(self.polling_interval, (int, float)) or isinstance(
            self.polling_interval, bool
        ) or not math.isfinite(float(self.polling_interval)) or self.polling_interval <= 0:
            raise ProcessRuntimeError(
                "polling_interval must be a positive finite number"
            )
        object.__setattr__(self, "polling_interval", float(self.polling_interval))
        if not isinstance(self.configured, bool):
            raise ProcessRuntimeError("configured must be a bool")
        if not callable(self.process_factory):
            raise ProcessRuntimeError("process_factory must be callable")
        if self.aia_session_id is not None and (
            not isinstance(self.aia_session_id, str) or not self.aia_session_id
        ):
            raise ProcessRuntimeError("aia_session_id must be non-empty when provided")
        if self.workspace is not None:
            try:
                object.__setattr__(
                    self,
                    "workspace",
                    Path(self.workspace).expanduser().resolve(strict=False),
                )
            except (TypeError, ValueError, OSError) as error:
                raise ProcessRuntimeError("workspace is invalid") from error

    @property
    def status(self) -> ProcessObserverCapabilityStatus:
        return (
            ProcessObserverCapabilityStatus.AVAILABLE
            if self.configured
            else ProcessObserverCapabilityStatus.UNAVAILABLE
        )

    @property
    def available(self) -> bool:
        return self.status is ProcessObserverCapabilityStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    identity: ProcessIdentity
    ppid: int | None
    process_role: ProcessRole
    root_identity: ProcessIdentity
    observed_at: datetime
    name: str | None = None
    executable: str | None = None
    metadata_status: ProcessMetadataStatus = ProcessMetadataStatus.COMPLETE
    parent_identity: ProcessIdentity | None = None
    raw_command: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProcessIdentity):
            raise ProcessRuntimeError("identity must be a ProcessIdentity")
        if not isinstance(self.root_identity, ProcessIdentity):
            raise ProcessRuntimeError("root_identity must be a ProcessIdentity")
        if not isinstance(self.process_role, ProcessRole):
            object.__setattr__(self, "process_role", ProcessRole(self.process_role))
        if self.ppid is not None and (
            not isinstance(self.ppid, int)
            or isinstance(self.ppid, bool)
            or self.ppid < 0
        ):
            raise ProcessRuntimeError("ppid must be a non-negative integer")
        object.__setattr__(
            self,
            "metadata_status",
            ProcessMetadataStatus(self.metadata_status),
        )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ProcessRuntimeError("observed_at must be timezone-aware")
        object.__setattr__(
            self,
            "observed_at",
            self.observed_at.astimezone(timezone.utc),
        )
        if self.parent_identity is not None and (
            self.process_role is ProcessRole.ROOT
            or self.ppid != self.parent_identity.pid
        ):
            raise ProcessRuntimeError("parent_identity does not match process parent")
        if self.raw_command is not None and (
            not isinstance(self.raw_command, str) or not self.raw_command.strip()
        ):
            raise ProcessRuntimeError("raw_command must be non-empty when provided")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "create_time": self.identity.create_time,
            "metadata_status": self.metadata_status.value,
            "pid": self.identity.pid,
            "process_role": self.process_role.value,
            "root_create_time": self.root_identity.create_time,
            "root_pid": self.root_identity.pid,
            "observed_at": self.observed_at.isoformat(),
        }
        if self.ppid is not None:
            payload["ppid"] = self.ppid
        if self.name is not None:
            payload["name"] = self.name
        if self.executable is not None:
            payload["executable"] = self.executable
        if self.parent_identity is not None:
            payload["parent_pid"] = self.parent_identity.pid
            payload["parent_create_time"] = self.parent_identity.create_time
        if self.raw_command is not None:
            payload["raw_command"] = self.raw_command
        return payload


@dataclass(frozen=True, slots=True)
class ProcessRuntimeSensorContext:
    aia_session_id: str
    workspace: Path
    root_process_identity: ProcessIdentity
    status: SensorStatus
    started_at: datetime
    evidence_path: Path
    health: SensorHealth

    @property
    def session_id(self) -> str:
        return self.aia_session_id


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _control_root_for_context(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
) -> ControlRoot:
    try:
        control_directory = context.control_directory.resolve(strict=True)
    except OSError as error:
        raise SensorStartError("Protection control directory is unavailable") from error
    root = ControlRoot.for_workspace(
        session.workspace,
        control_directory.parent.parent,
    )
    if root.session_directory(session.session_id) != control_directory:
        raise SensorStartError("Protection context control directory is invalid")
    return root


def _validate_preparation(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
    checkpoint: SafeCheckpoint,
    registration: RootProcessRegistration,
    *,
    allow_ready: bool = False,
) -> None:
    if not isinstance(session, ProtectedRunSession):
        raise SensorStartError("session must be a ProtectedRunSession")
    if not isinstance(context, ProtectionPreparationContext):
        raise SensorStartError(
            "context must be a ProtectionPreparationContext"
        )
    if not isinstance(checkpoint, SafeCheckpoint):
        raise SensorStartError("checkpoint must be a SafeCheckpoint")
    if not isinstance(registration, RootProcessRegistration):
        raise SensorStartError("registration must be a RootProcessRegistration")
    allowed_statuses = {SessionStatus.PREPARING}
    if allow_ready:
        allowed_statuses.add(SessionStatus.READY)
    if session.status not in allowed_statuses:
        raise SensorStartError(
            "Process Runtime Sensor requires PREPARING or launch-authorized READY Session"
        )
    if context.session_id != session.session_id:
        raise SensorStartError("Protection context Session ID does not match")
    if context.workspace != session.workspace:
        raise SensorStartError("Protection context Workspace does not match")
    if context.active_policy.session_id != session.session_id:
        raise SensorStartError("Active Policy does not belong to Session")
    if context.workspace_lease.session_id != session.session_id:
        raise SensorStartError("Workspace Lease does not belong to Session")
    if context.workspace_lease.workspace != session.workspace:
        raise SensorStartError("Workspace Lease Workspace does not match")
    if checkpoint.session_id != session.session_id:
        raise SensorStartError("Checkpoint does not belong to Session")
    if checkpoint.workspace != session.workspace:
        raise SensorStartError("Checkpoint Workspace does not match")
    if checkpoint.validity is not CheckpointValidity.VALID:
        raise SensorStartError("Process Runtime Sensor requires a VALID Checkpoint")
    if registration.aia_session_id != session.session_id:
        raise SensorStartError("Root registration Session ID does not match")
    if registration.workspace != session.workspace:
        raise SensorStartError("Root registration Workspace does not match")
    validation = validate_checkpoint(checkpoint)
    if validation.validity is not CheckpointValidity.VALID:
        raise SensorStartError("Checkpoint validation failed")


PpidSnapshot = Callable[[], Mapping[int, int] | None]


def _psutil_ppid_snapshot() -> Mapping[int, int] | None:
    """Return one system-wide pid -> ppid map.

    psutil takes this snapshot inside every children() call and every Windows
    ppid() call. The sensor takes it once per poll instead of twice per tracked
    process. It is a psutil internal, so when it is missing this returns None
    and the sensor keeps the per-node children() walk.
    """

    snapshot = getattr(getattr(psutil, "_psplatform", None), "ppid_map", None)
    return snapshot() if snapshot is not None else None


class ProcessRuntimeSensor:
    """Observe an explicitly registered process tree and append Raw Evidence."""

    def __init__(
        self,
        session: ProtectedRunSession,
        context: ProtectionPreparationContext,
        checkpoint: SafeCheckpoint,
        registration: RootProcessRegistration,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        evidence_store: RawEvidenceStore | None = None,
        poll_interval: float = 0.25,
        process_factory: ProcessFactory = psutil.Process,
        allow_ready: bool = False,
        capture_command_line: bool = False,
        ppid_snapshot: PpidSnapshot | None = None,
    ) -> None:
        if not isinstance(poll_interval, (int, float)) or isinstance(
            poll_interval,
            bool,
        ) or not math.isfinite(float(poll_interval)) or poll_interval <= 0:
            raise ProcessRuntimeError("poll_interval must be a positive finite number")
        if not isinstance(allow_ready, bool):
            raise ProcessRuntimeError("allow_ready must be a bool")
        if not isinstance(capture_command_line, bool):
            raise ProcessRuntimeError("capture_command_line must be a bool")
        self.session = session
        self.preparation_context = context
        self.checkpoint = checkpoint
        self.registration = registration
        self.lease_manager = lease_manager
        self.poll_interval = float(poll_interval)
        self.process_factory = process_factory
        # Only the real psutil backend gets the per-poll snapshot by default.
        # An injected process factory keeps the per-node children() walk
        # unless it also supplies a snapshot of the same process table.
        if ppid_snapshot is None and process_factory is psutil.Process:
            ppid_snapshot = _psutil_ppid_snapshot
        self.ppid_snapshot = ppid_snapshot
        self.allow_ready = allow_ready
        self.capture_command_line = capture_command_line
        self._control_root: ControlRoot | None = None
        if evidence_store is None:
            try:
                control_directory = context.control_directory.resolve(strict=False)
                evidence_store = RawEvidenceStore(
                    control_directory / "evidence" / "raw-evidence.jsonl",
                    session_id=session.session_id,
                )
            except (OSError, ValueError, TypeError) as error:
                raise SensorStartError("Evidence Store path cannot be prepared") from error
        if evidence_store.session_id not in {None, session.session_id}:
            raise SensorStartError("Evidence Store Session ID does not match")
        if evidence_store.path.is_relative_to(session.workspace):
            raise SensorStartError("Evidence Store must be outside Workspace")
        evidence_root = (
            context.control_directory.resolve(strict=False) / "evidence"
        ).resolve(strict=False)
        if not evidence_store.path.is_relative_to(evidence_root):
            raise SensorStartError(
                "Evidence Store must be under the Session Control Root"
            )
        self.evidence_store = evidence_store
        self._lock = RLock()
        self._status = SensorStatus.STOPPED
        self._health = SensorHealth(
            EvidenceSource.PROCESS_RUNTIME,
            SensorStatus.STOPPED,
            _now_utc(),
            reason="NOT_STARTED",
        )
        self._started_at: datetime | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._observed: dict[ProcessIdentity, ProcessObservation] = {}
        self._exit_recorded: set[ProcessIdentity] = set()
        self._root_exit_observed = False

    @property
    def status(self) -> SensorStatus:
        return self.check_health().status

    @property
    def health(self) -> SensorHealth:
        return self.check_health()

    @property
    def observer_thread(self) -> Thread | None:
        return self._thread

    @property
    def context(self) -> ProcessRuntimeSensorContext:
        return self._context()

    @property
    def capability(self) -> ProcessObserverCapability:
        """Return validated configuration without starting Runtime observation."""

        return ProcessObserverCapability(
            polling_interval=self.poll_interval,
            process_factory=self.process_factory,
            aia_session_id=self.session.session_id,
            workspace=self.session.workspace,
        )

    def start(self) -> ProcessRuntimeSensorContext:
        with self._lock:
            if self._status in {SensorStatus.STARTING, SensorStatus.HEALTHY}:
                raise SensorAlreadyRunningError(
                    "Process Runtime Sensor is already running"
                )
            self._status = SensorStatus.STARTING
            self._health = SensorHealth(
                EvidenceSource.PROCESS_RUNTIME,
                SensorStatus.STARTING,
                _now_utc(),
                reason="STARTING",
            )
            self._stop_event.clear()
            self._root_exit_observed = False
            try:
                self._set_health(SensorStatus.STARTING, "STARTING", append=True)
                if self._status is not SensorStatus.STARTING:
                    raise SensorStartError(
                        "Process Runtime starting health could not be persisted"
                    )
                _validate_preparation(
                    self.session,
                    self.preparation_context,
                    self.checkpoint,
                    self.registration,
                    allow_ready=self.allow_ready,
                )
                self._control_root = _control_root_for_context(
                    self.session,
                    self.preparation_context,
                )
                manager = self.lease_manager or WorkspaceLeaseManager(
                    self._control_root
                )
                manager.validate_ownership(self.preparation_context.workspace_lease)
                root_status, _ = inspect_process_identity(
                    self.registration.root_process_identity,
                    process_factory=self.process_factory,
                )
                self._raise_for_root_status(root_status)
                self._poll_once(initial=True)
                self._started_at = _now_utc()
                thread = Thread(
                    target=self._run,
                    name=f"aia-process-runtime-{self.session.session_id}",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
                if not thread.is_alive() and not self._root_exit_observed:
                    raise SensorStartError(
                        "Process Runtime observer thread stopped during start"
                    )
                if self._status is SensorStatus.FAILED:
                    raise SensorStartError(
                        "Process Runtime observer failed during start"
                    )
                self._set_health(SensorStatus.HEALTHY, "STARTED", append=True)
                if self._status is not SensorStatus.HEALTHY:
                    raise SensorStartError(
                        "Process Runtime health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                self._stop_event.set()
                thread = self._thread
                self._thread = None
                if thread is not None and thread is not current_thread():
                    thread.join(timeout=5)
                if self._health.reason != "EVIDENCE_STORE_FAILURE":
                    self._set_health(
                        SensorStatus.FAILED,
                        self._failure_reason(error, "START_FAILED"),
                        append=True,
                    )
                if isinstance(error, SensorStartError):
                    raise
                raise SensorStartError(
                    "Process Runtime Sensor failed to start"
                ) from error

    def stop(self) -> ProcessRuntimeSensorContext:
        with self._lock:
            if self._status is SensorStatus.STOPPED:
                return self._context()
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=5)
        with self._lock:
            self._thread = None
            if thread is not None and thread.is_alive():
                self._set_health(SensorStatus.FAILED, "OBSERVER_FAILURE", append=True)
                raise SensorStopError(
                    "Process Runtime observer did not stop in time"
                )
            if self._status is SensorStatus.FAILED:
                return self._context()
            try:
                self._set_health(SensorStatus.STOPPED, "STOPPED", append=True)
                if self._status is not SensorStatus.STOPPED:
                    raise SensorStopError(
                        "Process Runtime stop health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                if self._health.reason != "EVIDENCE_STORE_FAILURE":
                    self._set_health(
                        SensorStatus.FAILED,
                        self._failure_reason(error, "STOP_FAILED"),
                        append=True,
                    )
                if isinstance(error, SensorStopError):
                    raise
                raise SensorStopError(
                    "Process Runtime Sensor failed to stop"
                ) from error

    def check_health(self) -> SensorHealth:
        with self._lock:
            if (
                self._status is SensorStatus.HEALTHY
                and self._thread is not None
                and not self._thread.is_alive()
                and not self._root_exit_observed
                and not self._stop_event.is_set()
            ):
                self._set_health(SensorStatus.FAILED, "OBSERVER_FAILURE", append=True)
            return self._health

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            try:
                self._poll_once(initial=False)
            except ProcessEvidenceStoreError:
                return
            except Exception as error:
                with self._lock:
                    if self._status is not SensorStatus.FAILED:
                        self._set_health(
                            SensorStatus.FAILED,
                            self._failure_reason(error, "OBSERVER_FAILURE"),
                            append=True,
                        )
                return

    def _poll_once(self, *, initial: bool) -> None:
        with self._lock:
            if self._status not in {SensorStatus.STARTING, SensorStatus.HEALTHY}:
                return
            root_status, root_process = inspect_process_identity(
                self.registration.root_process_identity,
                process_factory=self.process_factory,
            )
            if root_status is not ProcessIdentityStatus.LIVE_MATCH:
                if initial:
                    self._raise_for_root_status(root_status)
                if root_status in {
                    ProcessIdentityStatus.PROCESS_GONE,
                    ProcessIdentityStatus.PID_REUSED,
                }:
                    self._root_exit_observed = True
                    self._stop_event.set()
                    current: dict[ProcessIdentity, ProcessObservation] = {}
                    self._record_missing_observations(current, root_status)
                    return
                self._set_failed("OWNER_UNVERIFIABLE", append=True)
                raise ProcessRuntimeError(
                    "Root Process identity became unverifiable"
                )
            if root_process is None:
                raise ProcessRuntimeError("Root Process handle is unavailable")
            current = self._collect_tree(root_process)
            for identity, observation in current.items():
                if identity not in self._observed:
                    self._append_observation(observation)
            self._record_missing_observations(current, None)
            self._observed.update(current)

    def _collect_tree(self, root_process: Any) -> dict[ProcessIdentity, ProcessObservation]:
        children_by_parent, ppids = self._take_ppid_snapshot()
        current: dict[ProcessIdentity, ProcessObservation] = {}
        root_identity = self.registration.root_process_identity
        root_observation = self._build_observation(
            root_process,
            root_identity,
            ProcessRole.ROOT,
            root_identity,
            parent_identity=None,
            ppid=ppids.get(root_identity.pid) if ppids is not None else None,
        )
        current[root_identity] = root_observation
        stack: list[tuple[Any, ProcessIdentity]] = [(root_process, root_identity)]
        while stack:
            parent_process, parent_identity = stack.pop()
            children = (
                self._snapshot_children(parent_process, children_by_parent)
                if children_by_parent is not None
                else self._children(parent_process)
            )
            for child_process in children:
                child_identity, live_child = self._child_identity(child_process)
                if child_identity is None or live_child is None:
                    continue
                if child_identity in current:
                    continue
                try:
                    observation = self._build_observation(
                        live_child,
                        child_identity,
                        ProcessRole.DESCENDANT,
                        root_identity,
                        parent_identity=parent_identity,
                        ppid=(
                            ppids.get(child_identity.pid)
                            if ppids is not None
                            else None
                        ),
                    )
                except ProcessRuntimeError:
                    # Windows process trees can change between the children()
                    # enumeration and the ppid() read.  A race here must not
                    # turn the whole sensor unhealthy or create an unverified
                    # parent relation.  Omit only this descendant and observe
                    # it on a later poll if the relation becomes stable.
                    continue
                current[child_identity] = observation
                stack.append((live_child, child_identity))
        return current

    def _take_ppid_snapshot(
        self,
    ) -> tuple[dict[int, list[int]] | None, dict[int, int] | None]:
        """Take this poll's pid -> ppid snapshot, or None to walk per node."""

        if self.ppid_snapshot is None:
            return None, None
        try:
            snapshot = self.ppid_snapshot()
        except Exception:
            return None, None
        if snapshot is None:
            return None, None
        ppids = {
            pid: ppid
            for pid, ppid in snapshot.items()
            if type(pid) is int and type(ppid) is int and pid >= 0 and ppid >= 0
        }
        children_by_parent: dict[int, list[int]] = {}
        for pid, ppid in ppids.items():
            if pid != ppid:
                children_by_parent.setdefault(ppid, []).append(pid)
        return children_by_parent, ppids

    def _snapshot_children(
        self,
        parent_process: Any,
        children_by_parent: dict[int, list[int]],
    ) -> list[Any]:
        """Return a parent's children from the poll snapshot, as children() would."""

        child_pids = children_by_parent.get(int(parent_process.pid), ())
        if not child_pids:
            return []
        try:
            parent_created = parent_process.create_time()
        except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
            return []
        except (psutil.AccessDenied, PermissionError, OSError) as error:
            raise ProcessTreeEnumerationError(
                "managed process children could not be enumerated"
            ) from error
        children: list[Any] = []
        for pid in child_pids:
            try:
                child = self.process_factory(pid)
                # A child cannot be older than its parent. An older one means
                # the PID was reused; psutil children() applies the same guard.
                if parent_created <= child.create_time():
                    children.append(child)
            except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
                continue
            except (psutil.AccessDenied, PermissionError, OSError) as error:
                raise ProcessTreeEnumerationError(
                    "managed process children could not be enumerated"
                ) from error
        return children

    @staticmethod
    def _children(process: Any) -> Iterable[Any]:
        try:
            return process.children(recursive=False)
        except (
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
            ProcessLookupError,
        ):
            return ()
        except (psutil.AccessDenied, PermissionError, OSError) as error:
            raise ProcessTreeEnumerationError(
                "managed process children could not be enumerated"
            ) from error
        except Exception:
            raise ProcessTreeEnumerationError(
                "managed process children query failed"
            )

    def _child_identity(
        self,
        process: Any,
    ) -> tuple[ProcessIdentity | None, Any | None]:
        try:
            identity = ProcessIdentity(
                pid=int(process.pid),
                create_time=float(process.create_time()),
            )
        except (
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
            psutil.AccessDenied,
            ProcessLookupError,
            PermissionError,
            OSError,
            ValueError,
            TypeError,
        ):
            return None, None
        status, live_process = inspect_process_identity(
            identity,
            process_factory=self.process_factory,
        )
        if status is not ProcessIdentityStatus.LIVE_MATCH:
            return None, None
        return identity, live_process

    def _build_observation(
        self,
        process: Any,
        identity: ProcessIdentity,
        role: ProcessRole,
        root_identity: ProcessIdentity,
        *,
        parent_identity: ProcessIdentity | None,
        ppid: int | None = None,
    ) -> ProcessObservation:
        if ppid is None:
            ppid = self._read_ppid(process)
        previous = self._observed.get(identity)
        if previous is not None:
            # Only the first observation of a verified identity (PID + create
            # time) is recorded, so re-reading name, executable and command line
            # on every poll is wasted work. Reuse what was captured first.
            name = previous.name
            executable = previous.executable
            metadata_status = previous.metadata_status
            raw_command = previous.raw_command
        else:
            name, executable, metadata_status = self._read_metadata(process)
            raw_command = (
                self._read_command_line(process)
                if self.capture_command_line
                else None
            )
        return ProcessObservation(
            identity=identity,
            ppid=ppid,
            process_role=role,
            root_identity=root_identity,
            observed_at=_now_utc(),
            name=name,
            executable=executable,
            metadata_status=metadata_status,
            parent_identity=parent_identity,
            raw_command=raw_command,
        )

    @staticmethod
    def _read_ppid(process: Any) -> int | None:
        try:
            value = process.ppid()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        except Exception:
            pass
        return None

    @staticmethod
    def _read_metadata(
        process: Any,
    ) -> tuple[str | None, str | None, ProcessMetadataStatus]:
        name: str | None = None
        executable: str | None = None
        try:
            value = process.name()
            if isinstance(value, str) and value:
                name = value
        except Exception:
            pass
        try:
            value = process.exe()
            if isinstance(value, str) and value:
                executable = value
        except Exception:
            pass
        status = (
            ProcessMetadataStatus.COMPLETE
            if name is not None and executable is not None
            else ProcessMetadataStatus.PARTIAL
        )
        return name, executable, status

    @staticmethod
    def _read_command_line(process: Any) -> str | None:
        """Capture only the observed lexical command line.

        This is evidence for command-pattern evaluation.  It does not claim
        what a script will do internally, and it is intentionally opt-in
        because process command lines can contain secrets.
        """

        try:
            values = process.cmdline()
        except Exception:
            return None
        if not isinstance(values, (tuple, list)) or not values:
            return None
        if any(not isinstance(value, str) or not value for value in values):
            return None
        try:
            command = subprocess.list2cmdline(values)
        except (TypeError, ValueError):
            return None
        return command if command.strip() else None

    def _append_observation(self, observation: ProcessObservation) -> None:
        record = RawEvidenceRecord(
            session_id=self.session.session_id,
            source=EvidenceSource.PROCESS_RUNTIME,
            record_type=EvidenceRecordType.PROCESS_OBSERVED,
            captured_at=observation.observed_at,
            observation_stage=ObservationStage.POST_ACTION,
            payload=observation.to_payload(),
        )
        self._append_process_record(record)

    def _record_missing_observations(
        self,
        current: dict[ProcessIdentity, ProcessObservation],
        root_status: ProcessIdentityStatus | None,
    ) -> None:
        for identity, observation in tuple(self._observed.items()):
            if identity in current or identity in self._exit_recorded:
                continue
            status = root_status if identity == self.registration.root_process_identity else None
            if status is None:
                status = inspect_process_identity(
                    identity,
                    process_factory=self.process_factory,
                )[0]
            if status not in {
                ProcessIdentityStatus.PROCESS_GONE,
                ProcessIdentityStatus.PID_REUSED,
            }:
                continue
            payload: dict[str, Any] = {
                "create_time": identity.create_time,
                "exit_reason": status.value,
                "observed_at": _now_utc().isoformat(),
                "pid": identity.pid,
                "process_role": observation.process_role.value,
                "root_create_time": observation.root_identity.create_time,
                "root_pid": observation.root_identity.pid,
            }
            record = RawEvidenceRecord(
                session_id=self.session.session_id,
                source=EvidenceSource.PROCESS_RUNTIME,
                record_type=EvidenceRecordType.PROCESS_EXIT_OBSERVED,
                captured_at=_now_utc(),
                observation_stage=ObservationStage.POST_ACTION,
                payload=payload,
            )
            self._append_process_record(record)
            self._exit_recorded.add(identity)

    def _append_process_record(self, record: RawEvidenceRecord) -> None:
        try:
            self.evidence_store.append(record)
        except EvidenceStoreError as error:
            self._set_failed("EVIDENCE_STORE_FAILURE", append=True)
            raise ProcessEvidenceStoreError(
                "Process Runtime Evidence could not be appended"
            ) from error

    def _set_failed(self, reason: str, *, append: bool) -> None:
        self._set_health(SensorStatus.FAILED, reason, append=append)

    @staticmethod
    def _raise_for_root_status(status: ProcessIdentityStatus) -> None:
        if status is ProcessIdentityStatus.PROCESS_GONE:
            raise RootProcessGoneError("registered Root Process is gone")
        if status is ProcessIdentityStatus.PID_REUSED:
            raise RootProcessReusedError("registered Root PID was reused")
        if status is ProcessIdentityStatus.OWNER_UNVERIFIABLE:
            raise RootProcessUnverifiableError(
                "registered Root Process identity is unverifiable"
            )
        if status is not ProcessIdentityStatus.LIVE_MATCH:
            raise SensorStartError("registered Root Process is not live")

    def _context(self) -> ProcessRuntimeSensorContext:
        started_at = self._started_at or self._health.checked_at
        return ProcessRuntimeSensorContext(
            aia_session_id=self.session.session_id,
            workspace=self.session.workspace,
            root_process_identity=self.registration.root_process_identity,
            status=self._status,
            started_at=started_at,
            evidence_path=self.evidence_store.path,
            health=self._health,
        )

    def _set_health(
        self,
        status: SensorStatus,
        reason: str,
        *,
        append: bool,
    ) -> None:
        self._status = status
        self._health = SensorHealth(
            EvidenceSource.PROCESS_RUNTIME,
            status,
            _now_utc(),
            reason=reason,
        )
        if not append:
            return
        record = RawEvidenceRecord(
            session_id=self.session.session_id,
            source=EvidenceSource.PROCESS_RUNTIME,
            record_type=EvidenceRecordType.SENSOR_HEALTH,
            captured_at=self._health.checked_at,
            observation_stage=ObservationStage.POST_ACTION,
            payload=self._health.to_mapping() | {"reason": reason},
        )
        try:
            self.evidence_store.append(record)
        except EvidenceStoreError:
            if status is not SensorStatus.FAILED:
                self._status = SensorStatus.FAILED
                self._health = SensorHealth(
                    EvidenceSource.PROCESS_RUNTIME,
                    SensorStatus.FAILED,
                    _now_utc(),
                    reason="EVIDENCE_STORE_FAILURE",
                )

    def _failure_reason(self, error: Exception, fallback: str) -> str:
        if isinstance(error, SensorError):
            return getattr(error, "code", fallback)
        return f"{fallback}:{type(error).__name__}"


__all__ = [
    "ProcessEvidenceStoreError",
    "ProcessMetadataStatus",
    "ProcessObserverCapability",
    "ProcessObserverCapabilityStatus",
    "ProcessObservation",
    "ProcessRole",
    "ProcessRuntimeError",
    "ProcessTreeEnumerationError",
    "ProcessRuntimeSensor",
    "ProcessRuntimeSensorContext",
    "RootProcessGoneError",
    "RootProcessReusedError",
    "RootProcessUnverifiableError",
    "SensorAlreadyRunningError",
    "SensorError",
    "SensorHealth",
    "SensorStartError",
    "SensorStatus",
    "SensorStopError",
]
