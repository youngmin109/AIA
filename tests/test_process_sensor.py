from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from aia import (
    CheckpointValidity,
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    PolicyProfile,
    ProcessEvidenceStoreError,
    ProcessIdentity,
    ProcessIdentityStatus,
    ProcessMetadataStatus,
    ProcessRole,
    ProcessRuntimeSensor,
    ProcessRuntimeSensorContext,
    ProtectedRunSession,
    RawEvidenceStore,
    RootProcessRegistration,
    RootProcessGoneError,
    RootProcessReusedError,
    RootProcessUnverifiableError,
    SensorAlreadyRunningError,
    SensorStartError,
    SensorStatus,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
    verify_process_identity,
)


class FakeProcessIdentity:
    def __call__(self, pid: int) -> float:
        if pid != 101:
            raise ProcessLookupError(pid)
        return 10.5


class FakeProcess:
    def __init__(
        self,
        pid: int,
        create_time: float,
        ppid: int,
        *,
        children: list["FakeProcess"] | None = None,
        name: str = "python.exe",
        executable: str = r"C:\Python\python.exe",
        name_error: bool = False,
        executable_error: bool = False,
        cmdline: list[str] | None = None,
        children_error: bool = False,
    ) -> None:
        self.pid = pid
        self._create_time = create_time
        self._ppid = ppid
        self.children_list = children or []
        self._name = name
        self._executable = executable
        self.name_error = name_error
        self.executable_error = executable_error
        self._cmdline = cmdline if cmdline is not None else [executable, "--fixture"]
        self.children_error = children_error

    def create_time(self) -> float:
        return self._create_time

    def ppid(self) -> int:
        return self._ppid

    def name(self) -> str:
        if self.name_error:
            raise psutil.AccessDenied(self.pid)
        return self._name

    def exe(self) -> str:
        if self.executable_error:
            raise psutil.AccessDenied(self.pid)
        return self._executable

    def children(self, recursive: bool = False) -> list["FakeProcess"]:
        assert recursive is False
        if self.children_error:
            raise psutil.AccessDenied(self.pid)
        return list(self.children_list)

    def cmdline(self) -> list[str]:
        return list(self._cmdline)


class FakeProcessTable:
    def __init__(self, processes: list[FakeProcess]) -> None:
        self.processes = {process.pid: process for process in processes}

    def __call__(self, pid: int) -> FakeProcess:
        if pid not in self.processes:
            raise psutil.NoSuchProcess(pid)
        return self.processes[pid]


class FailingProcessStore(RawEvidenceStore):
    def append(self, record):
        if record.record_type is EvidenceRecordType.PROCESS_OBSERVED:
            raise EvidenceStoreError("process observation store failure")
        return super().append(record)


class FailingExitStore(RawEvidenceStore):
    def append(self, record):
        if record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED:
            raise EvidenceStoreError("process exit store failure")
        return super().append(record)


def make_tree() -> tuple[FakeProcess, FakeProcess, FakeProcess, FakeProcess, FakeProcessTable]:
    grandchild = FakeProcess(30, 3.0, 20, name="grandchild.exe")
    child = FakeProcess(20, 2.0, 10, children=[grandchild], name="child.exe")
    root = FakeProcess(10, 1.0, 999, children=[child], name="root.exe")
    unrelated = FakeProcess(40, 4.0, 999, name="unrelated.exe")
    table = FakeProcessTable([root, child, grandchild, unrelated])
    return root, child, grandchild, unrelated, table


def prepared_process_inputs(
    tmp_path: Path,
    *,
    registration: RootProcessRegistration | None = None,
) -> tuple[
    Path,
    ProtectedRunSession,
    object,
    WorkspaceLeaseManager,
    object,
    RootProcessRegistration,
]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
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
    if registration is None:
        registration = RootProcessRegistration(
            aia_session_id=session.session_id,
            workspace=workspace,
            root_process_identity=ProcessIdentity(10, 1.0),
            registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            registration_source="EXTERNAL_TEST",
        )
    return workspace, session, context, lease_manager, checkpoint, registration


def make_sensor(
    tmp_path: Path,
    *,
    table: FakeProcessTable | None = None,
    store: RawEvidenceStore | None = None,
    registration: RootProcessRegistration | None = None,
    poll_interval: float = 0.02,
    capture_command_line: bool = False,
    ppid_snapshot=None,
) -> tuple[
    ProcessRuntimeSensor,
    FakeProcessTable,
    FakeProcess,
    FakeProcess,
    FakeProcess,
    Path,
    ProtectedRunSession,
    object,
    WorkspaceLeaseManager,
]:
    root, child, grandchild, _, default_table = make_tree()
    table = table or default_table
    workspace, session, context, lease_manager, checkpoint, registration = (
        prepared_process_inputs(tmp_path, registration=registration)
    )
    sensor = ProcessRuntimeSensor(
        session,
        context,
        checkpoint,
        registration,
        lease_manager=lease_manager,
        evidence_store=store,
        poll_interval=poll_interval,
        process_factory=table,
        capture_command_line=capture_command_line,
        ppid_snapshot=ppid_snapshot,
    )
    return (
        sensor,
        table,
        root,
        child,
        grandchild,
        workspace,
        session,
        context,
        lease_manager,
    )


def release_lease(context, lease_manager: WorkspaceLeaseManager) -> None:
    try:
        lease_manager.release(context.workspace_lease)
    except Exception:
        pass


def stop_sensor_and_release(sensor, context, lease_manager) -> None:
    try:
        sensor.stop()
    except Exception:
        pass
    release_lease(context, lease_manager)


def test_process_identity_requires_pid_and_create_time() -> None:
    first = ProcessIdentity(123, 10.0)
    same = ProcessIdentity(123, 10.0)
    reused = ProcessIdentity(123, 11.0)

    assert first == same
    assert first != reused


def test_identity_status_distinguishes_live_gone_reused_and_unverifiable() -> None:
    live = FakeProcess(123, 10.0, 1)
    table = FakeProcessTable([live])

    assert verify_process_identity(
        ProcessIdentity(123, 10.0), process_factory=table
    ) is ProcessIdentityStatus.LIVE_MATCH
    assert verify_process_identity(
        ProcessIdentity(123, 11.0), process_factory=table
    ) is ProcessIdentityStatus.PID_REUSED

    gone = FakeProcessTable([])
    assert verify_process_identity(
        ProcessIdentity(123, 10.0), process_factory=gone
    ) is ProcessIdentityStatus.PROCESS_GONE

    def denied(pid: int):
        raise psutil.AccessDenied(pid)

    assert verify_process_identity(
        ProcessIdentity(123, 10.0), process_factory=denied
    ) is ProcessIdentityStatus.OWNER_UNVERIFIABLE


def test_process_runtime_observes_root_children_and_grandchild_without_unrelated(
    tmp_path: Path,
) -> None:
    sensor, table, root, child, grandchild, _, session, context, lease_manager = (
        make_sensor(tmp_path)
    )
    sensor.start()
    try:
        observations = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        ]
        by_pid = {record.payload["pid"]: record for record in observations}

        assert set(by_pid) == {root.pid, child.pid, grandchild.pid}
        assert by_pid[root.pid].payload["process_role"] == ProcessRole.ROOT
        assert by_pid[child.pid].payload["process_role"] == ProcessRole.DESCENDANT
        assert by_pid[grandchild.pid].payload["process_role"] == ProcessRole.DESCENDANT
        assert by_pid[grandchild.pid].payload["parent_pid"] == child.pid
        assert by_pid[grandchild.pid].payload["parent_create_time"] == child._create_time
        assert all("cmdline" not in record.payload for record in observations)
        assert all("command_line" not in record.payload for record in observations)
        assert all("raw_command" not in record.payload for record in observations)
        assert all(
            datetime.fromisoformat(record.payload["observed_at"]).tzinfo is not None
            for record in observations
        )
        assert all(
            record.payload["root_pid"] == root.pid
            and record.payload["root_create_time"] == root._create_time
            for record in observations
        )
        assert session.status is SessionStatus.PREPARING
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_unstable_child_parent_relation_is_skipped_without_failing_sensor(
    tmp_path: Path,
) -> None:
    root, child, _, _, table = make_tree()
    child._ppid = 999  # children() saw it, but the relation changed before ppid().
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
    )
    sensor.start()
    try:
        observations = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        ]
        assert {record.payload["pid"] for record in observations} == {root.pid}
        assert sensor.status is SensorStatus.HEALTHY
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_child_enumeration_access_denied_fails_sensor_without_claiming_health(
    tmp_path: Path,
) -> None:
    root, _, _, _, table = make_tree()
    root.children_error = True
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
    )

    with pytest.raises(SensorStartError):
        sensor.start()

    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "OWNER_UNVERIFIABLE"
    assert not any(
        record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        for record in sensor.evidence_store.records()
    )
    release_lease(context, lease_manager)


def test_repeated_polling_does_not_create_duplicate_observation_records(
    tmp_path: Path,
) -> None:
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    try:
        time.sleep(0.1)
        observations = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        ]
        assert len(observations) == 3
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_pid_reuse_creates_new_observation_and_exit_for_old_identity(
    tmp_path: Path,
) -> None:
    sensor, table, root, child, _, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    try:
        replacement = FakeProcess(child.pid, 99.0, root.pid, name="replacement.exe")
        table.processes[child.pid] = replacement
        root.children_list = [replacement]
        sensor._poll_once(initial=False)

        exits = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED
        ]
        observed = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        ]
        assert any(
            record.payload["pid"] == child.pid
            and record.payload["create_time"] == child._create_time
            and record.payload["exit_reason"] == ProcessIdentityStatus.PID_REUSED
            for record in exits
        )
        assert any(
            record.payload["pid"] == child.pid
            and record.payload["create_time"] == 99.0
            for record in observed
        )
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_repeated_polls_reuse_metadata_of_observed_identity_but_not_after_pid_reuse(
    tmp_path: Path,
) -> None:
    sensor, table, root, child, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        capture_command_line=True,
    )
    metadata_reads: list[int] = []
    for process in table.processes.values():
        original_exe = process.exe

        def counting_exe(original_exe=original_exe, pid=process.pid) -> str:
            metadata_reads.append(pid)
            return original_exe()

        process.exe = counting_exe
    sensor.start()
    try:
        first_reads = sorted(metadata_reads)
        assert first_reads == [root.pid, 20, 30]

        sensor._poll_once(initial=False)
        sensor._poll_once(initial=False)
        assert sorted(metadata_reads) == first_reads

        replacement = FakeProcess(
            child.pid,
            99.0,
            root.pid,
            name="replacement.exe",
            executable=r"C:\Replacement\replacement.exe",
        )
        table.processes[child.pid] = replacement
        root.children_list = [replacement]
        sensor._poll_once(initial=False)

        replacement_records = [
            record.payload
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
            and record.payload["pid"] == child.pid
            and record.payload["create_time"] == 99.0
        ]
        assert len(replacement_records) == 1
        assert replacement_records[0]["name"] == "replacement.exe"
        assert replacement_records[0]["executable"] == r"C:\Replacement\replacement.exe"
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def _table_ppid_snapshot(table: FakeProcessTable):
    return lambda: {process.pid: process._ppid for process in table.processes.values()}


def _observation_fields(observations: dict) -> dict:
    return {
        identity: (
            observation.ppid,
            observation.process_role,
            observation.name,
            observation.executable,
            observation.metadata_status,
            observation.parent_identity,
            observation.raw_command,
        )
        for identity, observation in observations.items()
    }


def test_ppid_snapshot_tree_matches_per_node_walk_without_per_node_queries(
    tmp_path: Path,
) -> None:
    walk_sensor, _, walk_root, _, _, _, _, walk_context, walk_leases = make_sensor(
        tmp_path / "walk",
        capture_command_line=True,
    )
    expected = _observation_fields(walk_sensor._collect_tree(walk_root))
    release_lease(walk_context, walk_leases)

    root, child, grandchild, unrelated, table = make_tree()
    per_node_queries: list[str] = []
    for process in table.processes.values():
        def children(recursive: bool = False, pid=process.pid):
            per_node_queries.append(f"children:{pid}")
            return []

        def ppid(pid=process.pid):
            per_node_queries.append(f"ppid:{pid}")
            return 0

        process.children = children
        process.ppid = ppid
    snapshot = {process.pid: process._ppid for process in table.processes.values()}
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path / "snapshot",
        table=table,
        capture_command_line=True,
        ppid_snapshot=lambda: snapshot,
    )
    try:
        observed = _observation_fields(sensor._collect_tree(root))
    finally:
        release_lease(context, lease_manager)

    assert observed == expected
    assert set(observed) == {
        ProcessIdentity(root.pid, root._create_time),
        ProcessIdentity(child.pid, child._create_time),
        ProcessIdentity(grandchild.pid, grandchild._create_time),
    }
    assert ProcessIdentity(unrelated.pid, unrelated._create_time) not in observed
    assert per_node_queries == []


def test_unavailable_ppid_snapshot_reuses_observed_identity_ppids(
    tmp_path: Path,
) -> None:
    root, child, grandchild, unrelated, table = make_tree()
    ppid_reads = {pid: 0 for pid in table.processes}
    for process in table.processes.values():
        original_ppid = process.ppid

        def counted_ppid(pid=process.pid, read=original_ppid):
            ppid_reads[pid] += 1
            return read()

        process.ppid = counted_ppid
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
        ppid_snapshot=lambda: None,
    )
    try:
        first = sensor._collect_tree(root)
        sensor._observed.update(first)
        second = sensor._collect_tree(root)
    finally:
        release_lease(context, lease_manager)

    assert _observation_fields(second) == _observation_fields(first)
    assert set(second) == {
        ProcessIdentity(root.pid, root._create_time),
        ProcessIdentity(child.pid, child._create_time),
        ProcessIdentity(grandchild.pid, grandchild._create_time),
    }
    assert ppid_reads == {
        root.pid: 1,
        child.pid: 1,
        grandchild.pid: 1,
        unrelated.pid: 0,
    }


def test_ppid_snapshot_skips_child_older_than_its_parent_as_reused_pid(
    tmp_path: Path,
) -> None:
    root, child, grandchild, _, table = make_tree()
    # A process that claims the root as parent but was created before it is a
    # reused PID, not a real child.
    impostor = FakeProcess(50, 0.5, root.pid, name="impostor.exe")
    table.processes[impostor.pid] = impostor
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
        ppid_snapshot=_table_ppid_snapshot(table),
    )
    try:
        observed = sensor._collect_tree(root)
    finally:
        release_lease(context, lease_manager)

    pids = {identity.pid for identity in observed}
    assert pids == {root.pid, child.pid, grandchild.pid}


def test_failed_ppid_snapshot_falls_back_to_per_node_walk(tmp_path: Path) -> None:
    def failing_snapshot():
        raise OSError("snapshot unavailable")

    sensor, _, root, child, grandchild, _, _, context, lease_manager = make_sensor(
        tmp_path,
        ppid_snapshot=failing_snapshot,
    )
    try:
        observed = sensor._collect_tree(root)
    finally:
        release_lease(context, lease_manager)

    assert {identity.pid for identity in observed} == {root.pid, child.pid, grandchild.pid}


def test_process_gone_creates_exit_evidence_but_does_not_fail_sensor(
    tmp_path: Path,
) -> None:
    sensor, table, root, child, _, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    try:
        root.children_list = []
        del table.processes[child.pid]
        sensor._poll_once(initial=False)

        exits = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED
        ]
        assert any(record.payload["pid"] == child.pid for record in exits)
        assert sensor.status is SensorStatus.HEALTHY
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_missing_from_tree_is_not_exit_when_identity_is_still_live(
    tmp_path: Path,
) -> None:
    sensor, _, root, _, _, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    try:
        root.children_list = []
        sensor._poll_once(initial=False)
        assert not any(
            record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED
            for record in sensor.evidence_store.records()
        )
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_metadata_access_failure_keeps_identity_with_partial_metadata(
    tmp_path: Path,
) -> None:
    root, child, grandchild, _, table = make_tree()
    root.name_error = True
    root.executable_error = True
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
    )
    sensor.start()
    try:
        root_record = next(
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
            and record.payload["process_role"] == ProcessRole.ROOT
        )
        assert root_record.payload["metadata_status"] == ProcessMetadataStatus.PARTIAL
        assert "name" not in root_record.payload
        assert "executable" not in root_record.payload
        assert sensor.status is SensorStatus.HEALTHY
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (ProcessIdentityStatus.PROCESS_GONE, RootProcessGoneError),
        (ProcessIdentityStatus.PID_REUSED, RootProcessReusedError),
        (ProcessIdentityStatus.OWNER_UNVERIFIABLE, RootProcessUnverifiableError),
    ],
)
def test_root_registration_status_is_required_before_sensor_health(
    tmp_path: Path,
    status: ProcessIdentityStatus,
    error_type,
) -> None:
    root, _, _, _, table = make_tree()
    if status is ProcessIdentityStatus.PROCESS_GONE:
        del table.processes[root.pid]
    elif status is ProcessIdentityStatus.PID_REUSED:
        table.processes[root.pid] = FakeProcess(root.pid, 9.0, 999)
    else:
        def denied(pid: int):
            raise psutil.AccessDenied(pid)

        table = denied
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(
        tmp_path,
        table=table,
    )

    try:
        with pytest.raises(error_type):
            sensor.start()
        assert sensor.status is SensorStatus.FAILED
    finally:
        release_lease(context, lease_manager)


def test_sensor_lifecycle_duplicate_start_and_repeated_stop(
    tmp_path: Path,
) -> None:
    sensor, _, _, _, _, _, _, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    try:
        with pytest.raises(SensorAlreadyRunningError):
            sensor.start()
        first_stop = sensor.stop()
        second_stop = sensor.stop()
        assert first_stop.status is SensorStatus.STOPPED
        assert second_stop.status is SensorStatus.STOPPED
    finally:
        release_lease(context, lease_manager)


def test_process_evidence_store_failure_marks_sensor_failed(
    tmp_path: Path,
) -> None:
    _, session, context, lease_manager, checkpoint, registration = (
        prepared_process_inputs(tmp_path)
    )
    store = FailingProcessStore(
        context.control_directory / "evidence" / "raw-evidence.jsonl",
        session_id=session.session_id,
    )
    _, _, _, _, table = make_tree()
    sensor = ProcessRuntimeSensor(
        session,
        context,
        checkpoint,
        registration,
        lease_manager=lease_manager,
        evidence_store=store,
        process_factory=table,
    )

    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "EVIDENCE_STORE_FAILURE"
    release_lease(context, lease_manager)


def test_process_exit_store_failure_marks_sensor_failed(
    tmp_path: Path,
) -> None:
    sensor, table, root, child, _, _, _, context, lease_manager = make_sensor(tmp_path)
    normal_path = sensor.evidence_store.path
    store = FailingExitStore(normal_path, session_id=sensor.session.session_id)
    sensor.evidence_store = store
    sensor.start()
    try:
        # This test drives _poll_once itself. Do not let the background poller
        # consume the failing exit first and make the assertion timing-dependent.
        sensor._stop_event.set()
        sensor._thread.join(timeout=5)
        assert not sensor._thread.is_alive()
        root.children_list = []
        del table.processes[child.pid]
        with pytest.raises(ProcessEvidenceStoreError):
            sensor._poll_once(initial=False)
        assert sensor.status is SensorStatus.FAILED
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)


def test_preparation_requires_preparing_valid_checkpoint_and_matching_registration(
    tmp_path: Path,
) -> None:
    sensor, _, _, _, _, _, session, context, lease_manager = make_sensor(tmp_path)
    session.transition(SessionStatus.READY)
    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED
    release_lease(context, lease_manager)

    _, session, context, lease_manager, checkpoint, registration = (
        prepared_process_inputs(tmp_path / "second")
    )
    invalid_registration = replace(
        registration,
        aia_session_id="different-session",
    )
    invalid_checkpoint = replace(checkpoint, validity=CheckpointValidity.INVALID)
    invalid_sensor = ProcessRuntimeSensor(
        session,
        context,
        invalid_checkpoint,
        invalid_registration,
        lease_manager=lease_manager,
        process_factory=make_tree()[-1],
    )
    with pytest.raises(SensorStartError):
        invalid_sensor.start()
    assert invalid_sensor.status is SensorStatus.FAILED
    release_lease(context, lease_manager)


def terminate_tree(process: subprocess.Popen) -> None:
    try:
        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
        for child in descendants:
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            root.terminate()
        except psutil.Error:
            pass
        _, alive = psutil.wait_procs(descendants + [root], timeout=2)
        for item in alive:
            try:
                item.kill()
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def test_actual_python_root_child_grandchild_process_integration(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    grandchild_code = "import time; time.sleep(4)"
    child_code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable, '-c', {grandchild_code!r}]);"
        "time.sleep(4)"
    )
    root_code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]);"
        "time.sleep(4)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", root_code],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        root_process = psutil.Process(process.pid)
        registration = RootProcessRegistration(
            aia_session_id="pending",
            workspace=workspace,
            root_process_identity=ProcessIdentity(
                process.pid,
                root_process.create_time(),
            ),
            registered_at=datetime.now(timezone.utc),
            registration_source="EXTERNAL_TEST",
        )
        sensor, _, session, context, lease_manager, _ = (None,) * 6
        resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
        )
        session.transition(SessionStatus.PREPARING)
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
        )
        registration = replace(registration, aia_session_id=session.session_id)
        sensor = ProcessRuntimeSensor(
            session,
            context,
            checkpoint,
            registration,
            lease_manager=lease_manager,
            poll_interval=0.05,
        )
        sensor.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            observations = [
                record
                for record in sensor.evidence_store.records()
                if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
            ]
            if len({record.payload["pid"] for record in observations}) >= 3:
                break
            time.sleep(0.05)
        assert len({record.payload["pid"] for record in observations}) >= 3
        assert any(
            record.payload["process_role"] == ProcessRole.ROOT
            for record in observations
        )
        assert sum(
            record.payload["process_role"] == ProcessRole.DESCENDANT
            for record in observations
        ) >= 2
        assert session.status is SessionStatus.PREPARING
        sensor.stop()
        release_lease(context, lease_manager)
    finally:
        terminate_tree(process)


def test_process_runtime_can_capture_command_line_as_lexical_evidence(
    tmp_path: Path,
) -> None:
    sensor, _, root, child, grandchild, _, _, context, lease_manager = make_sensor(
        tmp_path,
        capture_command_line=True,
    )
    try:
        sensor.start()
        observations = [
            record
            for record in sensor.evidence_store.records()
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED
        ]
        by_pid = {record.payload["pid"]: record for record in observations}
        assert by_pid[root.pid].payload["raw_command"]
        assert by_pid[child.pid].payload["raw_command"]
        assert by_pid[grandchild.pid].payload["raw_command"]
    finally:
        stop_sensor_and_release(sensor, context, lease_manager)
