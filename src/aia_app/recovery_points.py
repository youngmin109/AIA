"""Supplemental recovery points; never replace the launch checkpoint."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from threading import RLock, Thread
import time
from uuid import uuid4

from aia.checkpoint import SafeCheckpointManager, _validate_artifact, _checkpoint_from_artifact
from .protected_run import ApplicationValidationError, _sensors_runtime_healthy
from .run_history import _hook_broker_runtime_healthy


# Automatic points keep the newest few.  Unchanged files are shared with the
# run's earlier checkpoints (hard links), so space grows with what changed,
# but every point still reads each file to verify it.  Small workspaces get a
# point after every finished request, large ones at most every
# LARGE_AUTO_INTERVAL_SECONDS, and beyond the upper limit automatic points
# stop.  Manual points are the user's explicit choice and keep the existing
# per-session limit of 50.
AUTO_POINTS_KEPT = 5
AUTO_MAX_FILES = 1_000
AUTO_MAX_BYTES = 50 * 1024 * 1024
LARGE_AUTO_MAX_FILES = 20_000
LARGE_AUTO_MAX_BYTES = 2 * 1024 * 1024 * 1024
LARGE_AUTO_INTERVAL_SECONDS = 600


def _auto_size_class(workspace: Path) -> str:
    """'small', 'large' or 'too_large'; the walk stops at the upper limit."""

    files = 0
    total = 0
    pending = [Path(workspace)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    if files >= LARGE_AUTO_MAX_FILES or total >= LARGE_AUTO_MAX_BYTES:
                        return 'too_large'
        except OSError:
            continue
    return 'small' if files < AUTO_MAX_FILES and total < AUTO_MAX_BYTES else 'large'


def seal(body):
    return hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != 'record_sha256'},
                                    ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class RecoveryPointsMixin:
    def _point_directory(self, session_id):
        return self.reader.session_directory(session_id) / 'checkpoint-notes'

    def _point_lock(self, record):
        # This map is accessed under the application's existing state lock.
        with self._runtime_state_lock:
            return record.runtime.setdefault('point_lock', RLock())

    def _read_point_note(self, session_id, checkpoint):
        path = self._point_directory(session_id) / f'{checkpoint.checkpoint_id}.json'
        try:
            note = json.loads(path.read_text(encoding='utf-8'))
            if (note.get('record_sha256') == seal(note) and note.get('session_id') == session_id
                    and note.get('manifest_sha256') == checkpoint.manifest_sha256):
                return note
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _recovery_checkpoints(self, session_id, workspace):
        root = self.reader.session_directory(session_id) / 'checkpoints'
        record = self.registry.get(session_id)
        baseline = record.runtime.get('checkpoint') if record is not None else None
        if record is None or record.status in {'COMPLETED', 'ABORTED', 'FAILED'}:
            result = self.reader.read_result(session_id)
            baseline_refs = [item for item in result.get('evidence_references', ())
                             if item.get('artifact_type') == 'CHECKPOINT_METADATA']
        else:
            baseline_refs = []
        points = []
        for path in root.iterdir() if root.is_dir() else ():
            if not path.is_dir() or path.name.startswith('.'):
                continue
            try:
                metadata, manifest = _validate_artifact(path)
                point = _checkpoint_from_artifact(path, metadata, manifest)
                if point.session_id != session_id or point.workspace != workspace:
                    continue
                # Failed/interrupted supplemental captures are never eligible.
                if point.checkpoint_id.startswith('point-') and not self._read_point_note(session_id, point):
                    continue
                if not point.checkpoint_id.startswith('point-'):
                    if baseline_refs:
                        relative = point.metadata_path.relative_to(self.reader.session_directory(session_id)).as_posix()
                        digest = hashlib.sha256(point.metadata_path.read_bytes()).hexdigest()
                        if not any(item.get('relative_path') == relative and item.get('sha256') == digest for item in baseline_refs):
                            continue
                    elif baseline is None or point.checkpoint_id != baseline.checkpoint_id:
                        continue
                points.append(point)
            except (OSError, ValueError):
                continue
        return sorted(points, key=lambda point: point.created_at)

    def list_recovery_points(self, session_id):
        record = self.registry.get(session_id)
        workspace = record.workspace if record else self._validate_workspace(self.reader.read_result(session_id).get('workspace'))
        ended = record is None or record.status in {'COMPLETED', 'ABORTED', 'FAILED'}
        points = []
        for point in self._recovery_checkpoints(session_id, workspace):
            note = self._read_point_note(session_id, point)
            points.append({
                'checkpoint_id': point.checkpoint_id, 'created_at': point.created_at.isoformat(),
                'kind': note['kind'] if note else 'BASELINE', 'name': note['name'] if note else '실행 전 기준점',
                'reason': note['reason'] if note else '보호 실행 시작 전 저장',
                'validity': point.validity.value, 'entry_count': len(point.manifest), 'can_restore': ended,
            })
        history = []
        root = self.reader.session_directory(session_id) / 'recovery-history'
        for path in sorted(root.glob('*.json')) if root.is_dir() else ():
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                valid = (item.get('record_sha256') == seal(item)
                         and item.get('session_id') == session_id
                         and item.get('original_result_sha256') == hashlib.sha256(self.reader.read_result_json(session_id)).hexdigest())
                history.append({'saved_at': item.get('saved_at'), 'checkpoint_id': item.get('checkpoint_id'),
                                'recovery_status': (item.get('recovery_result') or {}).get('recovery_status'),
                                'integrity_status': (item.get('integrity_result') or {}).get('integrity_status'),
                                'verification': 'VALID' if valid else 'INVALID'})
            except (OSError, ValueError, AttributeError):
                history.append({'verification': 'INVALID'})
        return {'points': points, 'history': history, 'run_ended': ended,
                'last_save_error': record.runtime.get('point_error') if record else None,
                'limitation': '저장 일관성 검증은 코드의 안전성 보증이 아닙니다. 외부 프로그램의 쓰기는 완전히 잠그지 못합니다.'}

    def _point_eligibility(self, record):
        codex = record.runtime.get('codex_session')
        if record.status != 'RUNNING' or record.stop_requested or record.runtime.get('end_session_requested') or record.runtime.get('point_closing') or codex is None:
            raise ApplicationValidationError('작업창의 실행 중인 세션에서만 저장할 수 있어요.')
        state = codex.snapshot()
        if (state.get('status') != 'READY' or state.get('active_turn_id')
                or any(state.get(key) for key in ('pending_approvals', 'pending_questions', 'pending_elicitations', 'pending_permissions'))):
            raise ApplicationValidationError('작업과 사용자 확인이 끝난 뒤 저장해 주세요.')
        if record.permission_grants:
            raise ApplicationValidationError('Codex 추가 권한을 허용한 세션은 추가 지점을 저장하지 않아요.')
        if not _sensors_runtime_healthy(record.runtime.get('sensors')) or not _hook_broker_runtime_healthy(record):
            raise ApplicationValidationError('센서 또는 Hook 상태를 확인할 수 없어 저장하지 않았어요.')
        for sensor in record.runtime.get('sensors', ()):
            observer = getattr(sensor, '_observer', None)
            queue = getattr(observer, 'event_queue', None)
            if queue is not None and queue.unfinished_tasks:
                raise ApplicationValidationError('파일 변화 증거를 처리 중이에요. 잠시 뒤 저장해 주세요.')
        if record.runtime.get('protection_failure_reason') or record.runtime.get('codex_sandbox_downgraded') or record.runtime.get('codex_approval_policy_downgraded'):
            raise ApplicationValidationError('보호 조건이 손실되어 저장하지 않았어요.')
        controller = record.runtime.get('codex_controller')
        if controller is None:
            raise ApplicationValidationError('정책 판정을 확인할 수 없어 저장하지 않았어요.')
        if getattr(controller, 'errors', ()):
            raise ApplicationValidationError('Hook 처리 오류가 남아 있어 저장하지 않았어요.')
        if getattr(controller, 'user_approved_unsupported_tools', ()) or getattr(controller, 'unsupported_tool_names', ()):
            raise ApplicationValidationError('보호 범위 밖 도구가 사용된 세션은 추가 지점을 저장하지 않아요.')
        if any(not item['event'].is_set() for item in record.runtime.get('unsupported_tool_reviews', {}).values()):
            raise ApplicationValidationError('사용자 확인 요청을 먼저 처리해 주세요.')
        self._process_evidence(record)
        if any(getattr(item.policy_decision, 'value', None) != 'COMPLIANT' for item in record.runtime.get('policy_evaluations', ())):
            raise ApplicationValidationError('위반 또는 미확정 판정이 남아 있어 저장하지 않았어요.')
        return state

    def save_recovery_point(self, session_id, *, name='수동 복구 지점', kind='MANUAL', turn_id=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ApplicationValidationError('복구 지점 이름은 1~80자로 입력해 주세요.')
        record = self.registry.require(session_id)
        size_class = _auto_size_class(record.workspace) if kind == 'AUTO' else None
        if size_class == 'too_large':
            raise ApplicationValidationError('작업 폴더가 너무 커서(파일 2만 개 또는 2GB 이상) 자동 저장을 하지 않았어요. 필요하면 직접 저장해 주세요.')
        if size_class == 'large':
            last = record.runtime.get('last_large_auto_point')
            if last is not None and time.monotonic() - last < LARGE_AUTO_INTERVAL_SECONDS:
                return {'saved': False, 'reason': 'LARGE_WORKSPACE_INTERVAL'}
        lock = self._point_lock(record)
        if not lock.acquire(blocking=False):
            raise ApplicationValidationError('복구 지점을 저장 중이에요. 잠시 뒤 다시 시도해 주세요.')
        try:
            before = self._point_eligibility(record)
            points = self._recovery_checkpoints(session_id, record.workspace)
            if len(points) >= 50:
                raise ApplicationValidationError('세션당 복구 지점 보관 한도 50개에 도달했어요. 새 세션을 시작해 주세요.')
            if kind == 'AUTO' and points:
                from aia.checkpoint import compare_workspace_to_checkpoint
                if compare_workspace_to_checkpoint(points[-1], record.workspace).matches:
                    return {'saved': False, 'reason': 'UNCHANGED_WORKSPACE'}
            if turn_id and record.runtime.get('latest_completed_turn') != turn_id:
                raise ApplicationValidationError('다음 작업이 시작되어 자동 저장을 보류했어요.')
            point = SafeCheckpointManager().create(
                record.runtime['session'], record.runtime['preparation'],
                lease_manager=record.runtime['lease_manager'], checkpoint_id=f'point-{uuid4().hex}', runtime_snapshot=True,
            )
            after = self._point_eligibility(record)
            if before['last_sequence'] != after['last_sequence']:
                raise ApplicationValidationError('저장 중 실행 상태가 바뀌어 지점을 등록하지 않았어요.')
            note = {'session_id': session_id, 'checkpoint_id': point.checkpoint_id, 'manifest_sha256': point.manifest_sha256,
                    'kind': kind, 'name': name.strip(), 'reason': '작업 완료 후 자동 저장' if kind == 'AUTO' else '사용자가 직접 저장',
                    'created_at': point.created_at.isoformat(), 'turn_id': turn_id}
            note['record_sha256'] = seal(note)
            root = self._point_directory(session_id)
            root.mkdir(parents=True, exist_ok=True)
            path = root / f'{point.checkpoint_id}.json'
            with path.open('x', encoding='utf-8') as stream:
                json.dump(note, stream, ensure_ascii=False, indent=2)
            if kind == 'AUTO':
                self._prune_auto_points(session_id)
            if size_class == 'large':
                record.runtime['last_large_auto_point'] = time.monotonic()
            record.runtime.pop('point_error', None)
            return {'saved': True, 'checkpoint_id': point.checkpoint_id, 'created_at': point.created_at.isoformat()}
        finally:
            lock.release()

    def _prune_auto_points(self, session_id):
        """Keep the newest AUTO_POINTS_KEPT automatic points; others are removed.

        The note goes first, so an interrupted removal leaves a point without a
        note, which is never offered for restore.
        """

        notes = []
        for path in self._point_directory(session_id).glob('point-*.json'):
            try:
                note = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if note.get('kind') == 'AUTO' and note.get('record_sha256') == seal(note):
                notes.append((str(note.get('created_at') or ''), path, note))
        checkpoints = self.reader.session_directory(session_id) / 'checkpoints'
        for _, path, note in sorted(notes, key=lambda item: item[0])[:-AUTO_POINTS_KEPT]:
            checkpoint_id = str(note.get('checkpoint_id') or '')
            if not checkpoint_id.startswith('point-') or path.stem != checkpoint_id:
                continue
            try:
                path.unlink()
                shutil.rmtree(checkpoints / checkpoint_id, ignore_errors=True)
            except OSError:
                continue

    def _maybe_auto_checkpoint(self, record):
        codex = record.runtime.get('codex_session')
        if codex is None or not hasattr(codex, 'read_events'):
            return
        events = codex.read_events(record.runtime.get('point_event_sequence', 0))
        for event in events:
            record.runtime['point_event_sequence'] = event['sequence']
            if event.get('type') == 'turn.completed' and event.get('status') == 'completed' and event.get('turn_id'):
                record.runtime['latest_completed_turn'] = event['turn_id']
                record.runtime['point_due_at'] = time.monotonic() + 1.0
            elif event.get('type') == 'turn.started':
                record.runtime.pop('point_due_at', None)
        due = record.runtime.get('point_due_at')
        worker = record.runtime.get('point_worker')
        if not due or time.monotonic() < due or (worker and worker.is_alive()):
            return
        record.runtime.pop('point_due_at', None)
        turn_id = record.runtime.get('latest_completed_turn')

        def capture():
            try:
                self.save_recovery_point(record.session_id, name='작업 완료', kind='AUTO', turn_id=turn_id)
            except Exception as error:
                # The failure stays explicit; it does not interrupt protection.
                record.runtime['point_error'] = (str(error) if isinstance(error, ApplicationValidationError)
                                                 else f'복구 지점을 저장하지 못했어요 ({type(error).__name__}).')

        worker = Thread(target=capture, name=f'aia-point-{record.session_id[:8]}', daemon=True)
        record.runtime['point_worker'] = worker
        worker.start()
