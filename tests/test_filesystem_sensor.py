from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)
from watchdog.observers import Observer

from aia import (
    CheckpointValidity,
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    PolicyProfile,
    ProtectedRunSession,
    RawEvidenceStore,
    SessionMode,
    SessionStatus,
    SensorAlreadyRunningError,
    SensorStartError,
    SensorStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)
from aia.sensors.filesystem import FilesystemSensor


class FakeProcessIdentity:
    def __init__(self) -> None:
        self.values = {101: 10.5}

    def __call__(self, pid: int) -> float:
        if pid not in self.values:
            raise ProcessLookupError(pid)
        return self.values[pid]


class FakeObserver:
    instances: list["FakeObserver"] = []

    def __init__(self) -> None:
        self.handler = None
        self.path = None
        self.recursive = False
        self.started = False
        self.stopped = False
        self.joined = False
        self.alive = False
        type(self).instances.append(self)

    def schedule(self, handler, path: str, recursive: bool) -> None:
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self) -> None:
        self.started = True
        self.alive = True

    def stop(self) -> None:
        self.stopped = True
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        self.joined = True

    def is_alive(self) -> bool:
        return self.alive


class FailingEvidenceStore(RawEvidenceStore):
    def append(self, record):
        raise EvidenceStoreError("test store failure")


def prepared_sensor_inputs(
    tmp_path: Path,
) -> tuple[Path, ProtectedRunSession, object, WorkspaceLeaseManager, object]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    session.transition(
        SessionStatus.PREPARING,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    lease_manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=FakeProcessIdentity(),
    )
    context = prepare_protection(
        session,
        resolved,
        tmp_path / "control",
        lease_manager=lease_manager,
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )
    return workspace, session, context, lease_manager, checkpoint


def make_sensor(
    tmp_path: Path,
    *,
    store: RawEvidenceStore | None = None,
) -> tuple[FilesystemSensor, Path, ProtectedRunSession, object, WorkspaceLeaseManager]:
    workspace, session, context, lease_manager, checkpoint = prepared_sensor_inputs(
        tmp_path
    )
    sensor = FilesystemSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
        evidence_store=store,
        observer_factory=FakeObserver,
    )
    return sensor, workspace, session, context, lease_manager


def release_lease(context, lease_manager: WorkspaceLeaseManager) -> None:
    try:
        lease_manager.release(context.workspace_lease)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clear_fake_observers() -> None:
    FakeObserver.instances.clear()


def test_sensor_start_requires_preparing_valid_checkpoint_and_owned_lease(
    tmp_path: Path,
) -> None:
    sensor, _, session, context, lease_manager = make_sensor(tmp_path)
    session.transition(SessionStatus.READY)

    with pytest.raises(SensorStartError):
        sensor.start()

    assert sensor.status is SensorStatus.FAILED
    assert not FakeObserver.instances
    release_lease(context, lease_manager)


def test_sensor_rejects_invalid_checkpoint(tmp_path: Path) -> None:
    workspace, session, context, lease_manager, checkpoint = prepared_sensor_inputs(
        tmp_path
    )
    sensor = FilesystemSensor(
        session,
        context,
        replace(checkpoint, validity=CheckpointValidity.INVALID),
        lease_manager=lease_manager,
        observer_factory=FakeObserver,
    )

    with pytest.raises(SensorStartError):
        sensor.start()

    assert sensor.health.reason == "SENSOR_START_FAILED"
    assert sensor.status is SensorStatus.FAILED
    assert workspace.is_dir()
    release_lease(context, lease_manager)


def test_sensor_start_is_recursive_and_session_remains_preparing(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)

    result = sensor.start()

    observer = FakeObserver.instances[0]
    assert result.status is SensorStatus.HEALTHY
    assert result.session_id == session.session_id
    assert result.evidence_path == sensor.evidence_store.path
    assert observer.path == str(workspace)
    assert observer.recursive is True
    assert session.status is SessionStatus.PREPARING
    assert result.started_at.tzinfo is not None
    health_records = [
        record
        for record in sensor.evidence_store.records()
        if record.record_type is EvidenceRecordType.SENSOR_HEALTH
    ]
    assert [record.payload["status"] for record in health_records] == [
        "STARTING",
        "HEALTHY",
    ]
    assert all("checked_at" in record.payload for record in health_records)
    sensor.stop()
    release_lease(context, lease_manager)


def test_duplicate_start_does_not_create_two_observers_and_stop_is_idempotent(
    tmp_path: Path,
) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()

    with pytest.raises(SensorAlreadyRunningError) as error:
        sensor.start()

    assert error.value.code == "ALREADY_RUNNING"
    assert len(FakeObserver.instances) == 1
    first_stop = sensor.stop()
    second_stop = sensor.stop()
    assert first_stop.status is SensorStatus.STOPPED
    assert second_stop.status is SensorStatus.STOPPED
    assert FakeObserver.instances[0].joined is True
    release_lease(context, lease_manager)


def test_filesystem_events_are_raw_post_action_evidence_and_open_events_are_ignored(
    tmp_path: Path,
) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    source = r"C:\workspace\raw-file.txt"
    destination = r"C:\workspace\renamed-file.txt"

    sensor.handle_event(FileCreatedEvent(source))
    sensor.handle_event(FileModifiedEvent(source))
    sensor.handle_event(FileDeletedEvent(source))
    sensor.handle_event(FileMovedEvent(source, destination))
    sensor.handle_event(SimpleNamespace(event_type="opened", src_path=source))
    sensor.handle_event(SimpleNamespace(event_type="closed", src_path=source))

    records = sensor.evidence_store.records()
    events = [
        record for record in records
        if record.record_type is EvidenceRecordType.FILESYSTEM_EVENT
    ]
    assert [record.payload["event_type"] for record in events] == [
        "created",
        "modified",
        "deleted",
        "moved",
    ]
    assert all(record.source is EvidenceSource.FILESYSTEM_WATCHER for record in events)
    assert all(record.observation_stage is ObservationStage.POST_ACTION for record in events)
    assert events[0].payload["src_path"] == source
    assert events[-1].payload["src_path"] == source
    assert events[-1].payload["dest_path"] == destination
    assert all("operation" not in record.payload for record in events)
    assert all("content" not in record.payload for record in events)
    sensor.stop()
    release_lease(context, lease_manager)


def test_events_after_stop_are_not_appended(tmp_path: Path) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    sensor.stop()
    before = len(sensor.evidence_store.records())

    sensor.handle_event(FileCreatedEvent(r"C:\workspace\after-stop.txt"))

    assert len(sensor.evidence_store.records()) == before
    release_lease(context, lease_manager)


def test_unexpected_observer_death_transitions_to_failed_with_health_evidence(
    tmp_path: Path,
) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    FakeObserver.instances[0].alive = False

    health = sensor.check_health()

    assert health.status is SensorStatus.FAILED
    assert health.reason == "OBSERVER_STOPPED_UNEXPECTEDLY"
    assert FakeObserver.instances[0].stopped is True
    assert any(
        record.record_type is EvidenceRecordType.SENSOR_HEALTH
        and record.payload["status"] == "FAILED"
        for record in sensor.evidence_store.records()
    )
    release_lease(context, lease_manager)


def test_evidence_store_failure_fails_start_and_stops_observer(tmp_path: Path) -> None:
    _, session, context, lease_manager, checkpoint = prepared_sensor_inputs(tmp_path)
    store = FailingEvidenceStore(
        context.control_directory / "evidence" / "raw-evidence.jsonl",
        session_id=None,
    )
    sensor = FilesystemSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
        evidence_store=store,
        observer_factory=FakeObserver,
    )

    with pytest.raises(SensorStartError):
        sensor.start()

    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "EVIDENCE_STORE_FAILURE"
    assert not FakeObserver.instances
    release_lease(context, lease_manager)


def test_evidence_store_failure_during_event_fails_sensor_and_stops_observer(
    tmp_path: Path,
) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    failing_store = FailingEvidenceStore(
        sensor.evidence_store.path,
        session_id=sensor.session.session_id,
    )
    sensor.evidence_store = failing_store

    sensor.handle_event(FileModifiedEvent(r"C:\workspace\failure.txt"))

    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "EVIDENCE_STORE_FAILURE"
    assert FakeObserver.instances[0].stopped is True
    release_lease(context, lease_manager)


def test_sensor_revalidates_current_lease_before_observing(tmp_path: Path) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    lease_manager.release(context.workspace_lease)

    with pytest.raises(SensorStartError):
        sensor.start()

    assert sensor.status is SensorStatus.FAILED


def test_sensor_evidence_store_must_stay_under_session_control_root(
    tmp_path: Path,
) -> None:
    _, session, context, lease_manager, checkpoint = prepared_sensor_inputs(tmp_path)
    outside_store = RawEvidenceStore(
        tmp_path / "outside-control" / "raw-evidence.jsonl",
        session_id=session.session_id,
    )

    with pytest.raises(SensorStartError):
        FilesystemSensor(
            session,
            context,
            checkpoint,
            lease_manager=lease_manager,
            evidence_store=outside_store,
            observer_factory=FakeObserver,
        )

    release_lease(context, lease_manager)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows watchdog integration test")
def test_windows_filesystem_sensor_observes_create_modify_delete_with_bounded_polling(
    tmp_path: Path,
) -> None:
    sensor, workspace, _, context, lease_manager = make_sensor(tmp_path)
    target = workspace / "observed.txt"
    try:
        sensor = FilesystemSensor(
            sensor.session,
            sensor.preparation_context,
            sensor.checkpoint,
            lease_manager=lease_manager,
            observer_factory=Observer,
        )
        sensor.start()
        target.write_text("one", encoding="utf-8")
        target.write_text("two", encoding="utf-8")
        target.unlink()

        deadline = time.monotonic() + 5
        seen: set[str] = set()
        while time.monotonic() < deadline:
            seen.update(
                record.payload["event_type"]
                for record in sensor.evidence_store.records()
                if record.record_type is EvidenceRecordType.FILESYSTEM_EVENT
            )
            if {"created", "modified", "deleted"}.issubset(seen):
                break
            time.sleep(0.05)

        assert {"created", "modified", "deleted"}.issubset(seen)
    finally:
        if sensor.status in {SensorStatus.HEALTHY, SensorStatus.FAILED}:
            sensor.stop()
        release_lease(context, lease_manager)
