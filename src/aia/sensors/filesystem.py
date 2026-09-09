"""Watchdog-backed filesystem Raw Evidence sensor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..checkpoint import (
    CheckpointValidity,
    SafeCheckpoint,
    validate_checkpoint,
)
from ..evidence import (
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
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


@dataclass(frozen=True, slots=True)
class FilesystemSensorContext:
    session_id: str
    workspace: Path
    sensor: EvidenceSource
    status: SensorStatus
    started_at: datetime
    evidence_path: Path
    health: SensorHealth


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


def _validate_context(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
    checkpoint: SafeCheckpoint,
) -> None:
    if not isinstance(session, ProtectedRunSession):
        raise SensorStartError("session must be a ProtectedRunSession")
    if not isinstance(context, ProtectionPreparationContext):
        raise SensorStartError(
            "context must be a ProtectionPreparationContext"
        )
    if not isinstance(checkpoint, SafeCheckpoint):
        raise SensorStartError("checkpoint must be a SafeCheckpoint")
    if session.status is not SessionStatus.PREPARING:
        raise SensorStartError("Filesystem Sensor requires PREPARING Session")
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
        raise SensorStartError("Filesystem Sensor requires a VALID Checkpoint")
    validation = validate_checkpoint(checkpoint)
    if validation.validity is not CheckpointValidity.VALID:
        raise SensorStartError("Checkpoint validation failed")


class _FilesystemEventHandler(FileSystemEventHandler):
    def __init__(self, sensor: "FilesystemSensor") -> None:
        super().__init__()
        self.sensor = sensor

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.sensor.handle_event(event)


class FilesystemSensor:
    """Observe Workspace file events and append only Raw Evidence."""

    _SUPPORTED_EVENT_TYPES = frozenset({"created", "modified", "deleted", "moved"})

    def __init__(
        self,
        session: ProtectedRunSession,
        context: ProtectionPreparationContext,
        checkpoint: SafeCheckpoint,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        evidence_store: RawEvidenceStore | None = None,
        observer_factory: Callable[[], Any] = Observer,
    ) -> None:
        self.session = session
        self.preparation_context = context
        self.checkpoint = checkpoint
        self.lease_manager = lease_manager
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
        self.observer_factory = observer_factory
        self._observer: Any | None = None
        self._handler = _FilesystemEventHandler(self)
        self._lock = RLock()
        self._status = SensorStatus.STOPPED
        self._started_at: datetime | None = None
        self._health = SensorHealth(
            EvidenceSource.FILESYSTEM_WATCHER,
            SensorStatus.STOPPED,
            _now_utc(),
            reason="NOT_STARTED",
        )

    @property
    def status(self) -> SensorStatus:
        return self.check_health().status

    @property
    def health(self) -> SensorHealth:
        return self.check_health()

    @property
    def observer(self) -> Any | None:
        return self._observer

    def start(self) -> FilesystemSensorContext:
        with self._lock:
            if self._status in {SensorStatus.STARTING, SensorStatus.HEALTHY}:
                raise SensorAlreadyRunningError(
                    "Filesystem Sensor is already running"
                )
            self._status = SensorStatus.STARTING
            self._health = SensorHealth(
                EvidenceSource.FILESYSTEM_WATCHER,
                SensorStatus.STARTING,
                _now_utc(),
                reason="STARTING",
            )
            observer: Any | None = None
            try:
                self._set_health(SensorStatus.STARTING, "STARTING", append=True)
                if self._status is not SensorStatus.STARTING:
                    raise SensorStartError(
                        "Filesystem Sensor starting health could not be persisted"
                    )
                _validate_context(self.session, self.preparation_context, self.checkpoint)
                self._control_root = _control_root_for_context(
                    self.session,
                    self.preparation_context,
                )
                manager = self.lease_manager or WorkspaceLeaseManager(
                    self._control_root
                )
                manager.validate_ownership(self.preparation_context.workspace_lease)
                observer = self.observer_factory()
                observer.schedule(
                    self._handler,
                    str(self.session.workspace),
                    recursive=True,
                )
                observer.start()
                if hasattr(observer, "is_alive") and not observer.is_alive():
                    raise SensorStartError("Filesystem Observer stopped during start")
                self._observer = observer
                self._started_at = _now_utc()
                self._set_health(SensorStatus.HEALTHY, "STARTED", append=True)
                if self._status is not SensorStatus.HEALTHY:
                    raise SensorStartError(
                        "Filesystem Sensor health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                if observer is not None:
                    self._stop_observer(observer)
                self._observer = None
                if self._health.reason != "EVIDENCE_STORE_FAILURE":
                    self._set_health(
                        SensorStatus.FAILED,
                        self._failure_reason(error, "START_FAILED"),
                        append=True,
                    )
                if isinstance(error, SensorStartError):
                    raise
                raise SensorStartError("Filesystem Sensor failed to start") from error

    def stop(self) -> FilesystemSensorContext:
        with self._lock:
            if self._status is SensorStatus.STOPPED:
                return self._context()
            if self._status is SensorStatus.FAILED and self._observer is None:
                return self._context()
            observer = self._observer
            self._observer = None
            try:
                if observer is not None:
                    self._stop_observer(observer)
                self._set_health(SensorStatus.STOPPED, "STOPPED", append=True)
                if self._status is not SensorStatus.STOPPED:
                    raise SensorStopError(
                        "Filesystem Sensor stop health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                self._set_health(
                    SensorStatus.FAILED,
                    self._failure_reason(error, "STOP_FAILED"),
                    append=True,
                )
                if isinstance(error, SensorStopError):
                    raise
                raise SensorStopError("Filesystem Sensor failed to stop") from error

    def check_health(self) -> SensorHealth:
        with self._lock:
            if self._status is SensorStatus.HEALTHY:
                observer = self._observer
                alive = True
                if observer is None:
                    alive = False
                elif hasattr(observer, "is_alive"):
                    alive = bool(observer.is_alive())
                if not alive:
                    self._set_health(
                        SensorStatus.FAILED,
                        "OBSERVER_STOPPED_UNEXPECTEDLY",
                        append=True,
                    )
            return self._health

    def handle_event(self, event: FileSystemEvent) -> None:
        with self._lock:
            if self._status is not SensorStatus.HEALTHY:
                return
            event_type = getattr(event, "event_type", None)
            if event_type not in self._SUPPORTED_EVENT_TYPES:
                # opened/closed/access-like events are deliberately not READ evidence.
                return
            payload: dict[str, Any] = {
                "event_type": event_type,
                "src_path": getattr(event, "src_path", None),
                "dest_path": (
                    getattr(event, "dest_path", None)
                    if event_type == "moved"
                    else None
                ),
                "is_directory": bool(getattr(event, "is_directory", False)),
            }
            if not isinstance(payload["src_path"], str):
                self._set_failed("INVALID_EVENT_PATH", append=True)
                return
            record = RawEvidenceRecord(
                session_id=self.session.session_id,
                source=EvidenceSource.FILESYSTEM_WATCHER,
                record_type=EvidenceRecordType.FILESYSTEM_EVENT,
                captured_at=_now_utc(),
                observation_stage=ObservationStage.POST_ACTION,
                payload=payload,
            )
            try:
                self.evidence_store.append(record)
            except EvidenceStoreError:
                self._set_failed("EVIDENCE_STORE_FAILURE", append=True)

    def _set_failed(self, reason: str, *, append: bool) -> None:
        self._set_health(SensorStatus.FAILED, reason, append=append)

    def _context(self) -> FilesystemSensorContext:
        started_at = self._started_at or self._health.checked_at
        return FilesystemSensorContext(
            session_id=self.session.session_id,
            workspace=self.session.workspace,
            sensor=EvidenceSource.FILESYSTEM_WATCHER,
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
            EvidenceSource.FILESYSTEM_WATCHER,
            status,
            _now_utc(),
            reason=reason,
        )
        if not append:
            return
        record = RawEvidenceRecord(
            session_id=self.session.session_id,
            source=EvidenceSource.FILESYSTEM_WATCHER,
            record_type=EvidenceRecordType.SENSOR_HEALTH,
            captured_at=self._health.checked_at,
            observation_stage=ObservationStage.POST_ACTION,
            payload=self._health.to_mapping() | {"reason": reason},
        )
        try:
            self.evidence_store.append(record)
        except EvidenceStoreError:
            # The in-memory health has already become FAILED. A failed Store
            # cannot reliably record its own failure evidence.
            if status is not SensorStatus.FAILED:
                self._status = SensorStatus.FAILED
                self._health = SensorHealth(
                    EvidenceSource.FILESYSTEM_WATCHER,
                    SensorStatus.FAILED,
                    _now_utc(),
                    reason="EVIDENCE_STORE_FAILURE",
                )
        if status is SensorStatus.FAILED and self._observer is not None:
            try:
                self._observer.stop()
            except Exception:
                pass

    def _failure_reason(self, error: Exception, fallback: str) -> str:
        if isinstance(error, SensorError):
            return getattr(error, "code", fallback)
        return fallback

    @staticmethod
    def _stop_observer(observer: Any) -> None:
        try:
            observer.stop()
            observer.join(timeout=5)
        except Exception as error:
            raise SensorStopError("Filesystem Observer could not stop") from error
        if hasattr(observer, "is_alive") and observer.is_alive():
            raise SensorStopError("Filesystem Observer did not stop in time")


__all__ = [
    "FilesystemSensor",
    "FilesystemSensorContext",
    "SensorError",
    "SensorAlreadyRunningError",
    "SensorHealth",
    "SensorStartError",
    "SensorStopError",
    "SensorStatus",
]
