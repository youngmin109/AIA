"""Append-only Raw Evidence domain and Control Root store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class EvidenceError(ValueError):
    """Base error for Raw Evidence operations."""


class EvidenceStoreError(EvidenceError):
    """Raised when a Raw Evidence record cannot be appended."""


class EvidenceSource(StrEnum):
    FILESYSTEM_WATCHER = "FILESYSTEM_WATCHER"
    AGENT_HOOK = "AGENT_HOOK"
    PROCESS_RUNTIME = "PROCESS_RUNTIME"


class EvidenceRecordType(StrEnum):
    FILESYSTEM_EVENT = "FILESYSTEM_EVENT"
    PRETOOL_REQUEST = "PRETOOL_REQUEST"
    COMMAND_OBSERVED = "COMMAND_OBSERVED"
    PROCESS_OBSERVED = "PROCESS_OBSERVED"
    PROCESS_EXIT_OBSERVED = "PROCESS_EXIT_OBSERVED"
    SENSOR_HEALTH = "SENSOR_HEALTH"


class ObservationStage(StrEnum):
    PRE_ACTION = "PRE_ACTION"
    POST_ACTION = "POST_ACTION"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_session_id(session_id: str) -> str:
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or session_id in {".", ".."}
        or any(separator in session_id for separator in ("/", "\\"))
    ):
        raise EvidenceError("session_id is not a safe value")
    return session_id


@dataclass(frozen=True, slots=True)
class RawEvidenceRecord:
    """One immutable observation fact before normalization or attribution."""

    session_id: str
    source: EvidenceSource
    record_type: EvidenceRecordType
    captured_at: datetime
    observation_stage: ObservationStage
    payload: Mapping[str, Any]
    evidence_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _safe_session_id(self.session_id))
        object.__setattr__(self, "source", EvidenceSource(self.source))
        object.__setattr__(self, "record_type", EvidenceRecordType(self.record_type))
        object.__setattr__(
            self,
            "observation_stage",
            ObservationStage(self.observation_stage),
        )
        object.__setattr__(
            self,
            "captured_at",
            _aware_utc(self.captured_at, field_name="captured_at"),
        )
        if not isinstance(self.evidence_id, str) or not self.evidence_id.strip():
            raise EvidenceError("evidence_id must be non-empty")
        if not isinstance(self.payload, Mapping):
            raise EvidenceError("payload must be a mapping")
        payload = dict(self.payload)
        try:
            json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise EvidenceError("payload must be JSON serializable") from error
        object.__setattr__(self, "payload", MappingProxyType(payload))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at.isoformat(),
            "evidence_id": self.evidence_id,
            "observation_stage": self.observation_stage.value,
            "payload": dict(self.payload),
            "record_type": self.record_type.value,
            "session_id": self.session_id,
            "source": self.source.value,
        }


class RawEvidenceStore:
    """Thread-safe append-only JSONL storage for one AIA Session."""

    def __init__(
        self,
        path: str | Path,
        *,
        session_id: str | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.session_id = (
            _safe_session_id(session_id) if session_id is not None else None
        )
        self._lock = Lock()

    @classmethod
    def for_session(
        cls,
        control_root: str | Path,
        session_id: str,
    ) -> "RawEvidenceStore":
        safe_id = _safe_session_id(session_id)
        root = Path(control_root).expanduser().resolve(strict=False)
        evidence_path = root / "sessions" / safe_id / "evidence" / "raw-evidence.jsonl"
        return cls(evidence_path, session_id=safe_id)

    def append(self, record: RawEvidenceRecord) -> RawEvidenceRecord:
        if not isinstance(record, RawEvidenceRecord):
            raise EvidenceStoreError("record must be a RawEvidenceRecord")
        if self.session_id is not None and record.session_id != self.session_id:
            raise EvidenceStoreError("record Session ID does not match Evidence Store")
        line = json.dumps(
            record.to_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
        except OSError as error:
            raise EvidenceStoreError(
                f"Raw Evidence cannot be appended: {self.path}"
            ) from error
        return record

    def records(self) -> tuple[RawEvidenceRecord, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError as error:
                raise EvidenceStoreError(
                    f"Raw Evidence cannot be read: {self.path}"
                ) from error
            records: list[RawEvidenceRecord] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    record = RawEvidenceRecord(
                        session_id=value["session_id"],
                        source=value["source"],
                        record_type=value["record_type"],
                        captured_at=datetime.fromisoformat(value["captured_at"]),
                        observation_stage=value["observation_stage"],
                        payload=value["payload"],
                        evidence_id=value["evidence_id"],
                    )
                    if (
                        self.session_id is not None
                        and record.session_id != self.session_id
                    ):
                        raise EvidenceStoreError(
                            "Raw Evidence record Session ID does not match Store"
                        )
                    records.append(record)
                except EvidenceStoreError:
                    raise
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise EvidenceStoreError(
                        f"Raw Evidence contains an invalid record: {self.path}"
                    ) from error
            return tuple(records)


__all__ = [
    "EvidenceError",
    "EvidenceRecordType",
    "EvidenceSource",
    "EvidenceStoreError",
    "ObservationStage",
    "RawEvidenceRecord",
    "RawEvidenceStore",
]
