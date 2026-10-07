from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aia import create_safe_checkpoint, SessionStatus, SessionFinalizer, RawEvidenceStore, ProcessIdentityStatus
from aia_app.service import RunApplicationService, process_create_time, ApplicationValidationError
from aia_app.registry import RunRecord
from aia_web.app import create_app
from tests.test_checkpoint import _prepared_workspace


def live_run(tmp_path, monkeypatch):
    workspace, session, context, manager = _prepared_workspace(tmp_path, owner_pid=os.getpid(), owner_create_time=process_create_time(os.getpid()))
    (workspace / 'note.txt').write_text('before', encoding='utf-8')
    baseline = create_safe_checkpoint(session, context, lease_manager=manager)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)
    service = RunApplicationService(tmp_path / 'control')
    codex = SimpleNamespace(snapshot=lambda: {'status': 'READY', 'last_sequence': 2, 'pending_approvals': [], 'active_turn_id': None})
    record = RunRecord(session.session_id, workspace, 'codex', None, 'BASIC_DEVELOPMENT', session.policy_id, session.policy_version, 'ENFORCE', '', status='RUNNING', launch_mode='codex_app_server')
    record.runtime.update(session=session, preparation=context, lease_manager=manager, checkpoint=baseline,
                          codex_session=codex, codex_controller=SimpleNamespace(unsupported_tool_names=(), user_approved_unsupported_tools=()),
                          sensors=(SimpleNamespace(health=SimpleNamespace(status=SimpleNamespace(value='HEALTHY'))),))
    service.registry.add(record)
    monkeypatch.setattr('aia_app.recovery_points._hook_broker_runtime_healthy', lambda record: True)
    monkeypatch.setattr(service, '_process_evidence', lambda record: record.runtime.update(policy_evaluations=(SimpleNamespace(policy_decision=SimpleNamespace(value='COMPLIANT')),)))
    return workspace, session, context, manager, baseline, record, service


def finish(session, context, manager, baseline, record, service):
    SessionFinalizer(evidence_store=RawEvidenceStore.for_session(service.control_root, session.session_id)).finalize(
        session, process_end_status=ProcessIdentityStatus.PROCESS_GONE, checkpoint=baseline,
        active_policy=context.active_policy, workspace_lease=context.workspace_lease, lease_manager=manager)
    record.status = 'COMPLETED'


def test_multiple_points_restore_and_repeat_without_changing_original_bundle(tmp_path, monkeypatch):
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        (workspace / 'note.txt').write_text('middle', encoding='utf-8')
        middle = service.save_recovery_point(session.session_id, name='중간 작업')
        (workspace / 'note.txt').write_text('last', encoding='utf-8')
        last = service.save_recovery_point(session.session_id, name='마지막 작업')
        assert len(service.list_recovery_points(session.session_id)['points']) == 3
        with pytest.raises(ApplicationValidationError, match='RUN_IS_ACTIVE'):
            service.restore_run(session.session_id, confirm=True, checkpoint_id=middle['checkpoint_id'], expected_fingerprint='0' * 64)
        finish(session, context, manager, baseline, record, service)
        original = service.reader.read_result_json(session.session_id)
        for checkpoint_id, expected in [(middle['checkpoint_id'], 'middle'), (last['checkpoint_id'], 'last'), (baseline.checkpoint_id, 'before'), (middle['checkpoint_id'], 'middle')]:
            preview = service.get_recovery_status(session.session_id, checkpoint_id)
            result = service.restore_run(session.session_id, confirm=True, checkpoint_id=checkpoint_id, expected_fingerprint=preview['preview_fingerprint'])
            assert result['recovery_result']['recovery_status'] == 'RESTORED'
            assert result['integrity_result']['integrity_status'] == 'VERIFIED'
            assert (workspace / 'note.txt').read_text(encoding='utf-8') == expected
        assert service.reader.read_result_json(session.session_id) == original
        data = service.list_recovery_points(session.session_id)
        assert len(data['history']) == 4
        assert all(item['verification'] == 'VALID' for item in data['history'])
        with pytest.raises(ApplicationValidationError):
            service.restore_run(session.session_id, confirm=True, checkpoint_id='../other', expected_fingerprint='0' * 64)
    finally:
        record.status = 'COMPLETED'
        service.shutdown()


@pytest.mark.parametrize('condition', ['working', 'approval', 'violation', 'sensor', 'unsupported', 'closing'])
def test_points_refuse_uncertain_or_unsafe_capture(tmp_path, monkeypatch, condition):
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        if condition == 'working': record.runtime['codex_session'].snapshot = lambda: {'status': 'WORKING'}
        if condition == 'approval': record.runtime['codex_session'].snapshot = lambda: {'status': 'READY', 'pending_approvals': [{}]}
        if condition == 'sensor': record.runtime['sensors'][0].health.status.value = 'FAILED'
        if condition == 'unsupported': record.runtime['codex_controller'].user_approved_unsupported_tools = ('search',)
        if condition == 'closing': record.runtime['point_closing'] = True
        if condition == 'violation': monkeypatch.setattr(service, '_process_evidence', lambda record: record.runtime.update(policy_evaluations=(SimpleNamespace(policy_decision=SimpleNamespace(value='VIOLATION')),)))
        with pytest.raises(ApplicationValidationError): service.save_recovery_point(session.session_id)
        assert len(service.list_recovery_points(session.session_id)['points']) == 1
    finally:
        record.status = 'COMPLETED'; manager.release(context.workspace_lease); service.shutdown()


def test_supplemental_capture_does_not_relax_preparing_checkpoint_contract(tmp_path, monkeypatch):
    from aia.checkpoint import CheckpointRefusedError
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        with pytest.raises(CheckpointRefusedError, match='PREPARING'):
            create_safe_checkpoint(session, context, lease_manager=manager)
    finally:
        record.status = 'COMPLETED'; manager.release(context.workspace_lease); service.shutdown()


def test_tampered_point_note_not_eligible_and_new_input_refused_during_save(tmp_path, monkeypatch):
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        point = service.save_recovery_point(session.session_id)
        path = service._point_directory(session.session_id) / f'{point["checkpoint_id"]}.json'
        note = json.loads(path.read_text(encoding='utf-8')); note['name'] = 'changed'
        path.write_text(json.dumps(note), encoding='utf-8')
        assert len(service.list_recovery_points(session.session_id)['points']) == 1
        # Test from a different thread: an RLock intentionally permits the owner.
        from threading import Thread
        failures = []
        lock = service._point_lock(record)
        def send():
            try: service.send_codex_message(session.session_id, 'hello')
            except Exception as error: failures.append(str(error))
        with lock:
            worker = Thread(target=send); worker.start(); worker.join()
        assert '저장 중' in failures[0]
    finally:
        record.status = 'COMPLETED'; manager.release(context.workspace_lease); service.shutdown()


def test_auto_only_after_successful_completed_turn_and_no_duplicate_without_changes(tmp_path, monkeypatch):
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        (workspace / 'note.txt').write_text('after', encoding='utf-8')
        record.runtime['codex_session'].read_events = lambda after: [{'sequence': 2, 'type': 'turn.completed', 'status': 'completed', 'turn_id': 'turn-1'}] if after < 2 else []
        service._maybe_auto_checkpoint(record)
        record.runtime['point_due_at'] = 0.01
        service._maybe_auto_checkpoint(record)
        record.runtime['point_worker'].join()
        points = service.list_recovery_points(session.session_id)['points']
        assert len(points) == 2 and points[-1]['kind'] == 'AUTO'
        assert service.save_recovery_point(session.session_id, kind='AUTO')['reason'] == 'UNCHANGED_WORKSPACE'
    finally:
        record.status = 'COMPLETED'; manager.release(context.workspace_lease); service.shutdown()


def test_template_endpoint_reads_real_policy_and_custom_still_requires_validation(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    service = RunApplicationService(tmp_path / 'control')
    with TestClient(create_app(service), base_url='http://127.0.0.1') as client:
        template = client.get('/api/policy/templates/CONSERVATIVE_SECURITY').json()['document']
        env = next(rule for rule in template['rules'] if '.env' in rule.get('path_patterns', []))
        assert env['operation_effects']['READ'] == 'AUDIT'
        assert client.get('/api/policy/templates/CUSTOM').status_code == 400
        assert client.post('/api/policy/save', headers={'Origin': 'http://127.0.0.1'}, json={'document': template}).status_code == 403
        token = client.get('/api/local-session').json()['token']
        assert client.post('/api/policy/validate', headers={'X-AIA-Local-Token': token}, json={'document': {}}).status_code == 400
        template.update(profile='CUSTOM', policy_id='aia-custom-test')
        response = client.post('/api/policy/save', headers={'Origin': 'http://127.0.0.1', 'X-AIA-Local-Token': token}, json={'document': template})
        assert response.status_code == 200
        path = response.json()['path']
        decision = service.preview_policy({'policy_profile': 'CUSTOM', 'custom_policy_path': path, 'operation': 'READ', 'path': '.env'})
        assert decision['operation_effect'] == 'AUDIT'


def test_unreferenced_checkpoint_cannot_be_mistaken_for_launch_baseline(tmp_path, monkeypatch):
    from aia.checkpoint import SafeCheckpointManager
    workspace, session, context, manager, baseline, record, service = live_run(tmp_path, monkeypatch)
    try:
        SafeCheckpointManager().create(session, context, lease_manager=manager,
                                       checkpoint_id='unregistered-copy', runtime_snapshot=True)
        assert [point['checkpoint_id'] for point in service.list_recovery_points(session.session_id)['points']] == [baseline.checkpoint_id]
        finish(session, context, manager, baseline, record, service)
        service.registry._records.pop(session.session_id)
        assert [point['checkpoint_id'] for point in service.list_recovery_points(session.session_id)['points']] == [baseline.checkpoint_id]
    finally:
        record.status = 'COMPLETED'
        service.shutdown()


def test_exception_cleanup_waits_for_snapshot_before_releasing_lease():
    from threading import Event, Thread
    started, proceed, released = Event(), Event(), Event()
    record = SimpleNamespace(runtime={})
    worker = Thread(target=lambda: (started.set(), proceed.wait(timeout=3)))
    record.runtime['point_worker'] = worker
    worker.start(); assert started.wait(timeout=1)
    cleanup = Thread(target=RunApplicationService._cleanup_run_lifecycle,
                     args=(record, [], (), SimpleNamespace(release=lambda lease: released.set()), object(), False))
    cleanup.start()
    try:
        assert not released.wait(timeout=0.05)
        proceed.set(); cleanup.join(timeout=2)
        assert released.is_set() and record.runtime['point_closing']
    finally:
        proceed.set(); worker.join(); cleanup.join()
