from datetime import datetime, timezone
import json
import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aia import ProcessIdentityStatus, RawEvidenceRecord, RawEvidenceStore, SessionFinalizer
from aia_app.activity import ActivityIndex
from aia_app.readers import ResultBundleReader
from aia_app.service import RunApplicationService
from aia_web.app import create_app
from tests.test_finalization import _session
from tests.test_checkpoint import _prepared_workspace


def test_activity_counts_unique_paths_and_never_exposes_commands(tmp_path, monkeypatch):
    index = ActivityIndex()
    path = tmp_path / 'main.py'
    for n in range(3):
        index.observe('FILESYSTEM_WATCHER', 'FILESYSTEM_EVENT', {'event_type': 'modified', 'src_path': str(path), 'is_directory': False}, str(n), str(n))
    index.observe('FILESYSTEM_WATCHER', 'FILESYSTEM_EVENT', {'event_type': 'modified', 'src_path': str(tmp_path.parent / 'outside'), 'is_directory': False}, '4', '4')
    index.observe('PROCESS_RUNTIME', 'PROCESS_OBSERVED', {'pid': 123, 'create_time': 2.0, 'name': 'python.exe', 'raw_command': 'SECRET-COMMAND', 'executable': 'SECRET-PATH'}, '5', '5')
    monkeypatch.setattr('aia_app.activity.inspect_process_identity', lambda identity: (ProcessIdentityStatus.LIVE_MATCH, None))
    view = index.view(tmp_path, live=True)
    assert view['unique_file_count'] == 1
    assert view['files'][0]['event_count'] == 3
    assert view['current_alive_count'] == 1
    assert 'SECRET' not in json.dumps(view)
    assert 'outside' not in json.dumps(view)
    assert index.view(tmp_path, live=False)['current_alive_count'] is None


def test_activity_process_pid_reuse_has_distinct_identities(tmp_path, monkeypatch):
    index = ActivityIndex()
    for created in [1.0, 2.0]:
        index.observe('PROCESS_RUNTIME', 'PROCESS_OBSERVED', {'pid': 123, 'create_time': created}, 'now', str(created))
    index.observe('PROCESS_RUNTIME', 'PROCESS_EXIT_OBSERVED', {'pid': 123, 'create_time': 1.0}, 'later', 'exit')
    monkeypatch.setattr('aia_app.activity.inspect_process_identity', lambda identity: (ProcessIdentityStatus.OWNER_UNVERIFIABLE, None))
    view = index.view(tmp_path, live=True)
    assert view['process_identity_count'] == 2
    assert view['current_alive_count'] is None
    assert view['processes'][0]['state'] == 'EXIT_OBSERVED'


def test_live_activity_comes_from_same_audit_stream(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    store = RawEvidenceStore.for_session(tmp_path / 'control', 'session-1')
    store.append(RawEvidenceRecord(session_id='session-1', source='FILESYSTEM_WATCHER', record_type='FILESYSTEM_EVENT', observation_stage='POST_ACTION', captured_at=datetime.now(timezone.utc), payload={'event_type': 'created', 'src_path': str(workspace / 'actual.txt'), 'is_directory': False}))
    reader = ResultBundleReader(tmp_path / 'control')
    assert reader.read_activity('session-1', workspace, live=True)['files'][0]['path'] == 'actual.txt'
    assert reader.read_activity('session-1', workspace, live=True)['unique_file_count'] == 1


def test_browser_boundary_rejects_foreign_origin_and_requires_local_capability(tmp_path):
    service = RunApplicationService(tmp_path / 'control')
    with TestClient(create_app(service), base_url='http://127.0.0.1:8791') as client:
        assert client.get('/api/local-session', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/runs', json={}, headers={'Origin': 'http://127.0.0.1:8791'}).status_code == 403
        token = client.get('/api/local-session').json()['token']
        assert client.post('/api/runs', json={}, headers={'Origin': 'http://127.0.0.1:8791', 'X-AIA-Local-Token': token}).status_code == 400
        assert client.get('/api/runs', headers={'Host': 'evil.example'}).status_code == 403
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect('ws://127.0.0.1:8791/api/runs/session-1/codex', headers={'Origin': 'https://evil.example'}):
                pass
        assert failure.value.code == 1008


def test_recovery_preview_detects_drift_and_diff(tmp_path):
    import aia.checkpoint as checkpoint
    from aia import create_safe_checkpoint
    prepared = _prepared_workspace(tmp_path)
    _, session, context, manager = prepared
    baseline = create_safe_checkpoint(session, context, lease_manager=manager)
    (session.workspace / 'new.txt').write_text('new', encoding='utf-8')
    comparison = checkpoint.compare_workspace_to_checkpoint(baseline)
    assert 'new.txt' in comparison.created_paths
    assert not comparison.matches


def test_recovery_record_seal_does_not_override_verified_run_when_corrupted(tmp_path):
    session, store, action = _session(tmp_path)
    SessionFinalizer(evidence_store=store).finalize(session, process_end_status=ProcessIdentityStatus.PROCESS_GONE, actions=(action,))
    service = RunApplicationService(tmp_path / 'control')
    try:
        path = service._manual_recovery_artifact_path(session.session_id)
        path.write_text(json.dumps({'recovery_result': {'recovery_status': 'RESTORED'}}), encoding='utf-8')
        assert service._read_manual_recovery(session.session_id)['record_verification'] == 'UNVERIFIED'
        original = {'recovery_status': 'NOT_ATTEMPTED'}
        assert service._apply_manual_recovery_view(original, session.session_id)['recovery_status'] == 'NOT_ATTEMPTED'
    finally:
        service.shutdown()


def test_manual_restore_requires_current_preview_and_seals_actual_outcome(tmp_path):
    from aia import create_safe_checkpoint, SessionStatus
    from aia_app.service import ApplicationValidationError
    from aia_app.service import process_create_time

    workspace, session, context, manager = _prepared_workspace(
        tmp_path, owner_pid=os.getpid(), owner_create_time=process_create_time(os.getpid())
    )
    (workspace / 'original.txt').write_text('baseline', encoding='utf-8')
    checkpoint = create_safe_checkpoint(session, context, lease_manager=manager)
    store = RawEvidenceStore.for_session(tmp_path / 'control', session.session_id)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)
    SessionFinalizer(evidence_store=store).finalize(
        session, process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        checkpoint=checkpoint, active_policy=context.active_policy,
        workspace_lease=context.workspace_lease, lease_manager=manager,
    )
    (workspace / 'original.txt').unlink()
    (workspace / 'new.txt').write_text('later work', encoding='utf-8')
    unrelated = tmp_path / 'outside.txt'
    unrelated.write_text('do not touch', encoding='utf-8')
    service = RunApplicationService(tmp_path / 'control')
    try:
        before = service.get_recovery_status(session.session_id)
        assert before['change_count'] == 2
        (workspace / 'new.txt').write_text('changed since preview', encoding='utf-8')
        with pytest.raises(ApplicationValidationError, match='미리보기 이후'):
            service.restore_run(session.session_id, confirm=True, expected_fingerprint=before['preview_fingerprint'])
        assert not (workspace / 'original.txt').exists()
        current = service.get_recovery_status(session.session_id)
        outcome = service.restore_run(session.session_id, confirm=True, expected_fingerprint=current['preview_fingerprint'])
        assert outcome['recovery_result']['recovery_status'] == 'RESTORED'
        assert outcome['integrity_result']['integrity_status'] == 'VERIFIED'
        assert (workspace / 'original.txt').read_text(encoding='utf-8') == 'baseline'
        assert not (workspace / 'new.txt').exists()
        assert unrelated.read_text(encoding='utf-8') == 'do not touch'
        assert service._read_manual_recovery(session.session_id)['record_verification'] == 'VALID'
        path = service._manual_recovery_artifact_path(session.session_id)
        assert not path.with_suffix('.sha256').exists()  # the seal lives inside the record
        record = json.loads(path.read_text(encoding='utf-8'))
        record['recovery_result']['recovery_status'] = 'FAILED'
        path.write_text(json.dumps(record), encoding='utf-8')
        assert service._read_manual_recovery(session.session_id)['record_verification'] == 'INVALID'
    finally:
        service.shutdown()


def _finished_run_with_deleted_file(tmp_path):
    from aia import create_safe_checkpoint, SessionStatus
    from aia_app.service import process_create_time

    workspace, session, context, manager = _prepared_workspace(
        tmp_path, owner_pid=os.getpid(), owner_create_time=process_create_time(os.getpid())
    )
    (workspace / 'original.txt').write_text('baseline', encoding='utf-8')
    checkpoint = create_safe_checkpoint(session, context, lease_manager=manager)
    store = RawEvidenceStore.for_session(tmp_path / 'control', session.session_id)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)
    SessionFinalizer(evidence_store=store).finalize(
        session, process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        checkpoint=checkpoint, active_policy=context.active_policy,
        workspace_lease=context.workspace_lease, lease_manager=manager,
    )
    (workspace / 'original.txt').unlink()
    return workspace, session


def test_unsealed_earlier_recovery_record_is_kept_but_does_not_block_restore(tmp_path):
    workspace, session = _finished_run_with_deleted_file(tmp_path)
    service = RunApplicationService(tmp_path / 'control')
    try:
        path = service._manual_recovery_artifact_path(session.session_id)
        path.write_text(json.dumps({'recovery_result': {'recovery_status': 'RESTORED'}}), encoding='utf-8')
        status = service.get_recovery_status(session.session_id)
        assert status['record_verification'] == 'UNVERIFIED'
        outcome = service.restore_run(session.session_id, confirm=True, expected_fingerprint=status['preview_fingerprint'])
        assert outcome['recovery_result']['recovery_status'] == 'RESTORED'
        assert (workspace / 'original.txt').read_text(encoding='utf-8') == 'baseline'
        assert service._read_manual_recovery(session.session_id)['record_verification'] == 'VALID'
        superseded = list(path.parent.glob('manual-recovery.superseded-*.json'))
        assert len(superseded) == 1
        assert json.loads(superseded[0].read_text(encoding='utf-8'))['recovery_result']['recovery_status'] == 'RESTORED'
    finally:
        service.shutdown()


def test_completed_activity_is_not_reverified_on_every_poll(tmp_path, monkeypatch):
    workspace, session = _finished_run_with_deleted_file(tmp_path)
    reader = ResultBundleReader(tmp_path / 'control')
    calls = []
    original = reader._read_verified_result
    monkeypatch.setattr(reader, '_read_verified_result', lambda session_id: calls.append(session_id) or original(session_id))
    first = reader.read_activity(session.session_id, workspace, live=False)
    second = reader.read_activity(session.session_id, workspace, live=False)
    assert first['available'] and second == first
    assert len(calls) == 1


def test_live_activity_is_rebuilt_at_most_once_per_refresh_window(tmp_path, monkeypatch):
    reader = ResultBundleReader(tmp_path / 'control')
    builds = []
    monkeypatch.setattr(reader, '_build_activity', lambda session_id, workspace, live: builds.append(1) or {'available': True, 'n': len(builds)})
    monkeypatch.setattr('aia_app.readers.time.monotonic', lambda: 100.0)
    assert reader.read_activity('session-1', tmp_path, live=True)['n'] == 1
    assert reader.read_activity('session-1', tmp_path, live=True)['n'] == 1
    monkeypatch.setattr('aia_app.readers.time.monotonic', lambda: 100.0 + reader.ACTIVITY_LIVE_REFRESH_SECONDS)
    assert reader.read_activity('session-1', tmp_path, live=True)['n'] == 2
