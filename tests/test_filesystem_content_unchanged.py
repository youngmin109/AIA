"""A modified event whose bytes did not change is not a MODIFY action.

The Codex Windows sandbox adds an inheritable ACL to the Workspace root,
and the propagation makes the File Sensor see every file as ``modified``.
Those events stay in Raw Evidence, marked ``content_unchanged``; only real
content changes become MODIFY actions (and can raise policy violations).
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

import pytest
from watchdog.events import DirModifiedEvent, FileModifiedEvent
from watchdog.observers import Observer

from aia import (
    EvidenceRecordType,
    PolicyProfile,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)
from aia.action import Operation
from aia.normalizer import Normalizer
from aia.sensors.filesystem import FilesystemSensor
from aia_app.activity import ActivityIndex
from tests.test_filesystem_sensor import FakeObserver, FakeProcessIdentity, release_lease


def _sensor(tmp_path: Path, files: dict[str, bytes], *, observer_factory=FakeObserver):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name, content in files.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    resolved = resolve_profile(PolicyProfile.PROTECTED_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace, agent="codex", mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id, policy_version=resolved.policy_version,
    )
    session.transition(SessionStatus.PREPARING, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    lease_manager = WorkspaceLeaseManager(tmp_path / "control", process_identity_provider=FakeProcessIdentity())
    context = prepare_protection(
        session, resolved, tmp_path / "control", lease_manager=lease_manager,
        owner_pid=101, owner_process_create_time=10.5,
    )
    checkpoint = create_safe_checkpoint(session, context, lease_manager=lease_manager)
    sensor = FilesystemSensor(
        session, context, checkpoint, lease_manager=lease_manager, observer_factory=observer_factory,
    )
    return sensor, workspace, session, context, lease_manager


def _file_events(sensor: FilesystemSensor):
    return [
        record for record in sensor.evidence_store.records()
        if record.record_type is EvidenceRecordType.FILESYSTEM_EVENT
    ]


def _modify_targets(sensor: FilesystemSensor, session: ProtectedRunSession) -> list[str]:
    result = Normalizer(session.session_id, session.workspace).normalize(sensor.evidence_store.records())
    return [action.canonical_path for action in result.actions if action.operation is Operation.MODIFY]


def test_permission_only_change_is_kept_as_evidence_but_is_not_a_modify(tmp_path) -> None:
    sensor, workspace, session, context, lease_manager = _sensor(tmp_path, {".env": b"API_KEY=one\n"})
    secret = workspace / ".env"
    sensor.start()
    try:
        os.utime(secret, (time.time() + 60, time.time() + 60))
        os.chmod(secret, stat.S_IREAD)
        os.chmod(secret, stat.S_IREAD | stat.S_IWRITE)
        sensor.handle_event(FileModifiedEvent(str(secret)))
        [event] = _file_events(sensor)
        assert event.payload["event_type"] == "modified"
        assert event.payload["content_unchanged"] is True
        assert "API_KEY" not in str(event.payload)
        assert _modify_targets(sensor, session) == []
        result = Normalizer(session.session_id, session.workspace).normalize(sensor.evidence_store.records())
        assert [issue.code for issue in result.issues] == ["CONTENT_UNCHANGED"]
    finally:
        sensor.stop()
        release_lease(context, lease_manager)


def test_real_content_change_stays_a_modify_even_if_later_reverted(tmp_path) -> None:
    sensor, workspace, session, context, lease_manager = _sensor(tmp_path, {".env": b"API_KEY=one\n"})
    secret = workspace / ".env"
    sensor.start()
    try:
        secret.write_bytes(b"API_KEY=two\n")  # same size, different bytes
        sensor.handle_event(FileModifiedEvent(str(secret)))
        secret.write_bytes(b"API_KEY=one\n")  # put back: still treated as a change
        sensor.handle_event(FileModifiedEvent(str(secret)))
        assert all("content_unchanged" not in event.payload for event in _file_events(sensor))
        assert _modify_targets(sensor, session) == [".env", ".env"]
    finally:
        sensor.stop()
        release_lease(context, lease_manager)


def test_files_that_cannot_be_compared_stay_modifications(tmp_path, monkeypatch) -> None:
    sensor, workspace, session, context, lease_manager = _sensor(
        tmp_path, {"big.bin": b"x" * 64, "data/db.sqlite": b"rows"},
    )
    sensor.start()
    try:
        monkeypatch.setattr(FilesystemSensor, "_CONTENT_CHECK_MAX_BYTES", 16)
        new_file = workspace / "new.txt"
        new_file.write_bytes(b"created after the checkpoint")
        sensor.handle_event(FileModifiedEvent(str(new_file)))  # not in the checkpoint
        sensor.handle_event(FileModifiedEvent(str(workspace / "big.bin")))  # above the size limit
        sensor.handle_event(FileModifiedEvent(str(workspace / "gone.txt")))  # unreadable
        sensor.handle_event(DirModifiedEvent(str(workspace / "data")))  # directory
        sensor.handle_event(FileModifiedEvent(str(tmp_path / "outside.txt")))  # outside the Workspace
        assert all("content_unchanged" not in event.payload for event in _file_events(sensor))
        # Directory and outside-Workspace events keep their existing MODIFY handling.
        assert _modify_targets(sensor, session) == ["new.txt", "big.bin", "gone.txt", "data", None]
    finally:
        sensor.stop()
        release_lease(context, lease_manager)


def test_activity_view_does_not_list_permission_only_changes(tmp_path) -> None:
    index = ActivityIndex()
    index.observe("FILESYSTEM_WATCHER", "FILESYSTEM_EVENT", {
        "event_type": "modified", "src_path": str(tmp_path / ".env"), "is_directory": False, "content_unchanged": True,
    }, "t1", "e1")
    index.observe("FILESYSTEM_WATCHER", "FILESYSTEM_EVENT", {
        "event_type": "modified", "src_path": str(tmp_path / "app.py"), "is_directory": False,
    }, "t2", "e2")
    view = index.view(tmp_path, live=False)
    assert [item["path"] for item in view["files"]] == ["app.py"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL propagation")
def test_inheritable_acl_on_the_workspace_root_raises_no_file_modify(tmp_path) -> None:
    files = {".env": b"API_KEY=one", ".env.production": b"API_KEY=prod", "data/customers.db": b"rows"}
    sensor, workspace, session, context, lease_manager = _sensor(tmp_path, files, observer_factory=Observer)
    sensor.start()
    try:
        # What the Codex sandbox does: an inheritable ACE on the Workspace root,
        # which Windows propagates to every file's security descriptor.
        subprocess.run(
            ["icacls", str(workspace), "/grant", "*S-1-5-32-545:(OI)(CI)(R)"],
            check=True, capture_output=True,
        )
        deadline = time.monotonic() + 5
        seen: set[str] = set()
        while time.monotonic() < deadline and len(seen) < len(files):
            seen = {
                Path(event.payload["src_path"]).name
                for event in _file_events(sensor)
                if event.payload["event_type"] == "modified" and not event.payload["is_directory"]
            }
            time.sleep(0.05)
        assert seen == {".env", ".env.production", "customers.db"}, "watchdog did not report the ACL change"
        file_events = [event for event in _file_events(sensor) if not event.payload["is_directory"]]
        assert all(event.payload.get("content_unchanged") is True for event in file_events)
        file_modifies = [path for path in _modify_targets(sensor, session) if path in {".env", ".env.production", "data/customers.db"}]
        assert file_modifies == []
    finally:
        sensor.stop()
        release_lease(context, lease_manager)
