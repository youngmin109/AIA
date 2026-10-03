"""Bounded, display-only projections of existing filesystem/process Evidence.

No commands, file contents, executable paths or outside-Workspace paths leave
this projection. It does not attribute a file writer or grant control authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aia.process_identity import ProcessIdentity, ProcessIdentityStatus, inspect_process_identity


@dataclass
class ActivityIndex:
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    processes: dict[tuple[int, float], dict[str, Any]] = field(default_factory=dict)
    truncated: bool = False

    def observe(self, source: str, record_type: str, payload: dict, captured_at: str, evidence_id: str) -> None:
        if source == 'FILESYSTEM_WATCHER' and record_type == 'FILESYSTEM_EVENT':
            if payload.get('is_directory') is not False:
                return
            event = payload.get('event_type')
            if event not in {'created', 'modified', 'deleted', 'moved'}:
                return
            if event == 'modified' and payload.get('content_unchanged') is True:
                return  # permission or metadata change; not a file change
            for key in ('src_path', 'dest_path'):
                path = payload.get(key)
                if not isinstance(path, str) or not path:
                    continue
                if path not in self.files and len(self.files) >= 10_000:
                    self.truncated = True
                    continue
                previous = self.files.get(path, {})
                self.files[path] = {'event_type': event, 'observed_at': captured_at,
                                    'evidence_id': evidence_id, 'event_count': previous.get('event_count', 0) + 1}
        elif source == 'PROCESS_RUNTIME' and record_type in {'PROCESS_OBSERVED', 'PROCESS_EXIT_OBSERVED'}:
            pid, created = payload.get('pid'), payload.get('create_time')
            if type(pid) is not int or not isinstance(created, (int, float)) or isinstance(created, bool):
                return
            identity = (pid, float(created))
            if identity not in self.processes and len(self.processes) >= 5_000:
                self.truncated = True
                return
            previous = self.processes.get(identity, {})
            name = payload.get('name')
            self.processes[identity] = {
                **previous, 'pid': pid, 'create_time': created,
                'parent_pid': payload.get('parent_pid', payload.get('ppid', previous.get('parent_pid'))),
                'parent_create_time': payload.get('parent_create_time', previous.get('parent_create_time')),
                'name': Path(name).name[:120] if isinstance(name, str) else previous.get('name', '프로세스'),
                'role': payload.get('process_role', previous.get('role', 'DESCENDANT')),
                'state': 'EXIT_OBSERVED' if record_type == 'PROCESS_EXIT_OBSERVED' else previous.get('state', 'LAST_OBSERVED'),
                'observed_at': captured_at, 'evidence_id': evidence_id,
            }

    def view(self, workspace: Path, *, live: bool) -> dict[str, Any]:
        files = []
        for path, item in self.files.items():
            try:
                # lexical paths: never resolve a symlink or open a target file.
                relative = Path(path).relative_to(workspace).as_posix()
            except (ValueError, TypeError):
                continue
            if '..' in Path(relative).parts:
                continue
            files.append({'path': relative, **item})
        processes = [dict(item) for item in self.processes.values()]
        alive = 0
        complete = live and not self.truncated and len(processes) <= 200
        for item in processes:
            if not live or item['state'] == 'EXIT_OBSERVED':
                continue
            if len(processes) > 200:
                complete = False
                continue
            try:
                identity_status, _ = inspect_process_identity(ProcessIdentity(item['pid'], item['create_time']))
                if identity_status is ProcessIdentityStatus.LIVE_MATCH:
                    item['state'] = 'LIVE_MATCH'
                    alive += 1
                elif identity_status in {ProcessIdentityStatus.PROCESS_GONE, ProcessIdentityStatus.PID_REUSED}:
                    item['state'] = 'GONE_AT_REFRESH'
                else:
                    item['state'] = 'UNVERIFIABLE'
                    complete = False
            except (ValueError, OSError, TypeError):
                item['state'] = 'UNVERIFIABLE'
                complete = False
        return {'available': True, 'live': live, 'files': sorted(files, key=lambda item: item['observed_at'], reverse=True)[:200],
                'processes': processes[-200:], 'unique_file_count': len(files), 'process_identity_count': len(processes),
                'current_alive_count': alive if complete else None, 'truncated': self.truncated or len(files) > 200 or len(processes) > 200,
                'attribution_note': '세션 중 관찰된 변경입니다. 파일을 바꾼 프로세스를 확정하지 않습니다.'}
