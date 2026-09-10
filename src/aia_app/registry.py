"""In-memory execution tracking for the local console."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class RunRecord:
    session_id: str
    workspace: Path
    agent: str
    model: str | None
    policy_profile: str
    policy_id: str
    policy_version: str
    mode: str
    task: str
    interactive: bool = False
    created_at: datetime = field(default_factory=_now)
    status: str = "CREATED"
    phase: str = "CREATED"
    protection_state: str = "STARTING"
    stop_requested: bool = False
    stop_error: str | None = None
    hook_event_count: int = 0
    error: str | None = None
    result_path: Path | None = None
    checkpoint: str = "NOT_READY"
    lease: str = "NOT_READY"
    sensor_health: dict[str, str] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    bundle_status: str | None = None
    runtime: dict[str, Any] = field(default_factory=dict, repr=False)


class RunRegistry:
    """Track execution state only; Core artifacts remain authoritative."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self._lock = RLock()

    def add(self, record: RunRecord) -> RunRecord:
        with self._lock:
            if record.session_id in self._records:
                raise ValueError(f"run already exists: {record.session_id}")
            self._records[record.session_id] = record
            return record

    def get(self, session_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(session_id)

    def require(self, session_id: str) -> RunRecord:
        record = self.get(session_id)
        if record is None:
            raise KeyError(session_id)
        return record

    def snapshot(self, session_id: str) -> RunRecord | None:
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                return None
            return self._snapshot_record(record)

    def snapshots(self) -> tuple[RunRecord, ...]:
        with self._lock:
            return tuple(self._snapshot_record(record) for record in self._records.values())

    @staticmethod
    def _snapshot_record(record: RunRecord) -> RunRecord:
        return RunRecord(
            session_id=record.session_id,
            workspace=record.workspace,
            agent=record.agent,
            model=record.model,
            policy_profile=record.policy_profile,
            policy_id=record.policy_id,
            policy_version=record.policy_version,
            mode=record.mode,
            task=record.task,
            interactive=record.interactive,
            created_at=record.created_at,
            status=record.status,
            phase=record.phase,
            protection_state=record.protection_state,
            stop_requested=record.stop_requested,
            stop_error=record.stop_error,
            hook_event_count=record.hook_event_count,
            error=record.error,
            result_path=record.result_path,
            checkpoint=record.checkpoint,
            lease=record.lease,
            sensor_health=dict(record.sensor_health),
            actions=[dict(item) for item in record.actions],
            incidents=[dict(item) for item in record.incidents],
            result=dict(record.result) if record.result is not None else None,
            bundle_status=record.bundle_status,
        )

    def update(self, session_id: str, **changes: Any) -> RunRecord:
        with self._lock:
            record = self.require(session_id)
            for key, value in changes.items():
                if not hasattr(record, key):
                    raise AttributeError(key)
                setattr(record, key, value)
            return record
