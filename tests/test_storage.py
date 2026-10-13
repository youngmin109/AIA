import os
import pytest
from pathlib import Path
from types import SimpleNamespace
from threading import RLock, Thread, Event

from aia_app.storage import KEEP_RECENT_RUNS, PRUNED_MARKER, StorageMixin, snapshots_pruned


class FakeService(StorageMixin):
    """Only what StorageMixin reads: the run list, live runs and the session folders."""

    def __init__(self, control_root: Path, runs: list[dict], live: list[str] = ()) -> None:
        self.control_root = control_root
        self._manual_restore_lock = RLock()
        self._runs = runs
        self.registry = SimpleNamespace(snapshots=lambda: [SimpleNamespace(session_id=sid, status='RUNNING') for sid in live])
        self.reader = SimpleNamespace(session_directory=lambda sid: control_root / 'sessions' / sid)

    def list_runs(self):
        return self._runs


def _run_with_snapshot(root: Path, session_id: str, content: bytes = b'x' * 1000) -> Path:
    checkpoint = root / 'sessions' / session_id / 'checkpoints' / 'base'
    (checkpoint / 'workspace').mkdir(parents=True)
    (checkpoint / 'workspace' / 'data.bin').write_bytes(content)
    (checkpoint / 'manifest.json').write_text('{}', encoding='utf-8')
    (checkpoint / 'metadata.json').write_text('{}', encoding='utf-8')
    (root / 'sessions' / session_id / 'result').mkdir(parents=True)
    (root / 'sessions' / session_id / 'result' / 'audit.jsonl').write_text('{}\n', encoding='utf-8')
    return checkpoint


def test_old_finished_runs_lose_only_their_snapshot_copies(tmp_path):
    total = KEEP_RECENT_RUNS + 2
    runs = [{'session_id': f'run-{index:02d}', 'status': 'COMPLETED', 'created_at': f'2026-10-{index + 1:02d}T00:00:00+00:00'}
            for index in range(total)]
    runs.append({'session_id': 'run-live', 'status': 'RUNNING', 'created_at': '2026-09-01T00:00:00+00:00'})
    for run in runs:
        _run_with_snapshot(tmp_path, run['session_id'])
    service = FakeService(tmp_path, runs, live=['run-live'])

    summary = service.storage_summary()
    assert summary['prunable_runs'] == 2 and summary['prunable_bytes'] == 2000
    assert summary['snapshot_bytes'] == total * 1000

    result = service.prune_old_snapshots()
    assert result == {'pruned_runs': 2, 'freed_bytes': 2000, 'keep_recent_runs': KEEP_RECENT_RUNS,
                      'failed_runs': 0, 'failures': []}
    for old in ('run-00', 'run-01'):
        checkpoints = tmp_path / 'sessions' / old / 'checkpoints'
        # The copy is gone; the manifest and metadata the sealed bundle refers to, and the audit, stay.
        assert not (checkpoints / 'base' / 'workspace').exists()
        assert (checkpoints / 'base' / 'manifest.json').is_file() and (checkpoints / 'base' / 'metadata.json').is_file()
        assert (tmp_path / 'sessions' / old / 'result' / 'audit.jsonl').is_file()
        assert snapshots_pruned(checkpoints) and (checkpoints / PRUNED_MARKER).is_file()
    for kept in [f'run-{index:02d}' for index in range(2, total)] + ['run-live']:
        assert (tmp_path / 'sessions' / kept / 'checkpoints' / 'base' / 'workspace' / 'data.bin').is_file()

    assert service.prune_old_snapshots()['pruned_runs'] == 0


def test_hard_linked_snapshot_files_are_counted_once(tmp_path):
    first = _run_with_snapshot(tmp_path, 'run-a')
    second = first.parent / 'point-1' / 'workspace'
    second.mkdir(parents=True)
    os.link(first / 'workspace' / 'data.bin', second / 'data.bin')
    service = FakeService(tmp_path, [{'session_id': 'run-a', 'status': 'COMPLETED', 'created_at': '2026-10-01'}])
    assert service.storage_summary()['snapshot_bytes'] == 1000


def pruning_fixture(tmp_path):
    runs = [{'session_id': f'run-{i:02d}', 'status': 'COMPLETED', 'created_at': f'2026-10-{i+1:02d}'} for i in range(11)]
    for run in runs:
        _run_with_snapshot(tmp_path, run['session_id'])
    return FakeService(tmp_path, runs), tmp_path / 'sessions/run-00/checkpoints'


def test_prune_waits_until_restore_releases_its_source(tmp_path):
    service, checkpoints = pruning_fixture(tmp_path)
    started, finished = Event(), Event()
    def prune():
        started.set()
        service.prune_old_snapshots()
        finished.set()
    with service._manual_restore_lock:
        worker = Thread(target=prune)
        worker.start()
        assert started.wait(2)
        assert not finished.wait(0.1)
        assert (checkpoints / 'base/workspace/data.bin').exists()
    worker.join(3)
    assert finished.is_set()
    assert not (checkpoints / 'base/workspace').exists()


def test_delete_failure_is_not_success_and_can_be_retried(tmp_path, monkeypatch):
    import aia_app.storage as storage
    service, checkpoints = pruning_fixture(tmp_path)
    original = storage.shutil.rmtree
    def locked(path):
        raise PermissionError('locked')
    monkeypatch.setattr(storage.shutil, 'rmtree', locked)
    result = service.prune_old_snapshots()
    assert result['pruned_runs'] == 0 and result['freed_bytes'] == 0
    assert result['failed_runs'] == 1
    assert not snapshots_pruned(checkpoints)
    assert (checkpoints / 'base/workspace/data.bin').exists()
    monkeypatch.setattr(storage.shutil, 'rmtree', original)
    assert service.prune_old_snapshots()['pruned_runs'] == 1


def test_pruned_hardlinks_free_their_bytes_only_once(tmp_path):
    service, checkpoints = pruning_fixture(tmp_path)
    second = checkpoints / 'point-1/workspace'
    second.mkdir(parents=True)
    os.link(checkpoints / 'base/workspace/data.bin', second / 'data.bin')
    assert service.prune_old_snapshots()['freed_bytes'] == 1000


def test_a_link_kept_outside_pruned_copies_does_not_free_storage(tmp_path):
    service, checkpoints = pruning_fixture(tmp_path)
    os.link(checkpoints / 'base/workspace/data.bin', tmp_path / 'retained.bin')
    assert service.prune_old_snapshots()['freed_bytes'] == 0
    assert (tmp_path / 'retained.bin').is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Windows open-file deletion semantics')
def test_windows_locked_file_is_not_marked_pruned(tmp_path):
    service, checkpoints = pruning_fixture(tmp_path)
    with (checkpoints / 'base/workspace/data.bin').open('rb'):
        result = service.prune_old_snapshots()
        assert result['failed_runs'] == 1 and result['freed_bytes'] == 0
        assert not snapshots_pruned(checkpoints)
    assert service.prune_old_snapshots()['pruned_runs'] == 1


def test_marker_write_failure_is_reported(tmp_path, monkeypatch):
    service, checkpoints = pruning_fixture(tmp_path)
    original = Path.write_text
    def fail_marker(path, *args, **kwargs):
        if path.name == PRUNED_MARKER:
            raise PermissionError('marker locked')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', fail_marker)
    result = service.prune_old_snapshots()
    assert result['failed_runs'] == 1 and result['pruned_runs'] == 0
    assert result['failures'][0]['reason'] == 'PRUNED_MARKER_WRITE_FAILED'


def test_changing_permissions_invalidates_startup_policy_match():
    from aia_app.presenters import _result_execution_policy
    result = {'agent_execution': {'output_observation': {
        'effective_sandbox': 'workspace-write', 'effective_approval_policy': 'on-request'}},
        'limitations': ['CODEX_PERMISSION_MODE_CHANGED']}
    policy = _result_execution_policy(result, [])
    assert policy['execution_policy_status'] == 'NOT_OBSERVED'
    assert policy['effective_sandbox'] is None


def test_opening_app_never_automatically_deletes_recovery_sources(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from aia_web.app import create_app
    from aia_app.service import RunApplicationService
    cleanup_calls = []
    monkeypatch.setenv('AIA_CONTROL_ROOT', str(tmp_path / 'control'))
    monkeypatch.setattr(RunApplicationService, 'prune_old_snapshots', lambda self: cleanup_calls.append(True))
    with TestClient(create_app(), base_url='http://127.0.0.1') as client:
        assert client.get('/api/storage').status_code == 200
    assert cleanup_calls == []
