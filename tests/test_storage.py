import os
from pathlib import Path
from types import SimpleNamespace

from aia_app.storage import KEEP_RECENT_RUNS, PRUNED_MARKER, StorageMixin, snapshots_pruned


class FakeService(StorageMixin):
    """Only what StorageMixin reads: the run list, live runs and the session folders."""

    def __init__(self, control_root: Path, runs: list[dict], live: list[str] = ()) -> None:
        self.control_root = control_root
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
    assert result == {'pruned_runs': 2, 'freed_bytes': 2000, 'keep_recent_runs': KEEP_RECENT_RUNS}
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
