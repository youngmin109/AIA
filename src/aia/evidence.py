"""Append-only Raw Evidence domain and Control Root store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any
from uuid import uuid4
from weakref import WeakValueDictionary


class EvidenceError(ValueError):
    """Base error for Raw Evidence operations."""


class EvidenceStoreError(EvidenceError):
    """Raised when a Raw Evidence record cannot be appended."""


class EvidenceStoreSealedError(EvidenceStoreError):
    """Raised when Product Logic appends after the Raw Evidence seal."""

    code = "EVIDENCE_STORE_SEALED"


class EvidenceSource(StrEnum):
    FILESYSTEM_WATCHER = "FILESYSTEM_WATCHER"
    AGENT_HOOK = "AGENT_HOOK"
    PROCESS_RUNTIME = "PROCESS_RUNTIME"


class EvidenceRecordType(StrEnum):
    FILESYSTEM_EVENT = "FILESYSTEM_EVENT"
    PRETOOL_REQUEST = "PRETOOL_REQUEST"
    COMMAND_OBSERVED = "COMMAND_OBSERVED"
    POSTTOOL_OBSERVED = "POSTTOOL_OBSERVED"
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


@dataclass(frozen=True, slots=True)
class EvidenceSeal:
    """Integrity-verifiable snapshot metadata for one Raw Evidence JSONL."""

    schema_version: str
    aia_session_id: str
    sealed_at: datetime
    raw_evidence_relative_path: str
    byte_size: int
    line_count: int
    sha256: str
    last_evidence_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sealed_at", _aware_utc(self.sealed_at, field_name="sealed_at"))
        if not self.schema_version.strip() or not self.aia_session_id.strip():
            raise EvidenceError("Evidence Seal identifiers must be non-empty")
        if not self.raw_evidence_relative_path.strip():
            raise EvidenceError("raw_evidence_relative_path must be non-empty")
        if self.byte_size < 0 or self.line_count < 0:
            raise EvidenceError("Evidence Seal counts must be non-negative")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise EvidenceError("Evidence Seal sha256 must be a lowercase SHA-256 digest")

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "aia_session_id": self.aia_session_id,
            "byte_size": self.byte_size,
            "line_count": self.line_count,
            "raw_evidence_relative_path": self.raw_evidence_relative_path,
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at.isoformat(),
            "sha256": self.sha256,
        }
        if self.last_evidence_id is not None:
            result["last_evidence_id"] = self.last_evidence_id
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceSeal":
        try:
            return cls(
                schema_version=value["schema_version"],
                aia_session_id=value["aia_session_id"],
                sealed_at=datetime.fromisoformat(value["sealed_at"]),
                raw_evidence_relative_path=value["raw_evidence_relative_path"],
                byte_size=value["byte_size"],
                line_count=value["line_count"],
                sha256=value["sha256"],
                last_evidence_id=value.get("last_evidence_id"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceStoreError("Raw Evidence Seal is invalid") from error


@dataclass(frozen=True, slots=True)
class EvidenceIndex:
    """Minimal Raw Evidence lookup index without payload duplication."""

    schema_version: str
    aia_session_id: str
    raw_evidence_relative_path: str
    entries: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not self.schema_version.strip() or not self.aia_session_id.strip():
            raise EvidenceError("Evidence Index identifiers must be non-empty")
        entries = {
            str(key): dict(value)
            for key, value in dict(self.entries).items()
        }
        object.__setattr__(self, "entries", MappingProxyType(entries))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "aia_session_id": self.aia_session_id,
            "entries": {key: dict(value) for key, value in sorted(self.entries.items())},
            "raw_evidence_relative_path": self.raw_evidence_relative_path,
            "schema_version": self.schema_version,
        }


_RAW_EVIDENCE_LOCKS_GUARD = Lock()
_RAW_EVIDENCE_LOCKS: WeakValueDictionary[Path, Any] = WeakValueDictionary()


def _raw_evidence_lock(path: Path) -> Any:
    """Share synchronization between stores that append to the same JSONL."""

    with _RAW_EVIDENCE_LOCKS_GUARD:
        lock = _RAW_EVIDENCE_LOCKS.get(path)
        if lock is None:
            lock = Lock()
            _RAW_EVIDENCE_LOCKS[path] = lock
        return lock


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
        self.seal_path = self.path.parent / "raw-evidence.seal.json"
        self.index_path = self.path.parent / "evidence-index.json"
        self._lock = _raw_evidence_lock(self.path)

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
                if self.seal_path.exists():
                    raise EvidenceStoreSealedError(
                        "EVIDENCE_STORE_SEALED: Raw Evidence append is forbidden"
                    )
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

    @property
    def sealed(self) -> bool:
        return self.seal_path.exists()

    def _snapshot(self) -> tuple[bytes, int, str | None]:
        try:
            raw = self.path.read_bytes() if self.path.exists() else b""
        except OSError as error:
            raise EvidenceStoreError(f"Raw Evidence cannot be read: {self.path}") from error
        line_count = 0
        last_evidence_id: str | None = None
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                evidence_id = value["evidence_id"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise EvidenceStoreError("Raw Evidence contains an invalid record") from error
            line_count += 1
            last_evidence_id = evidence_id
        return raw, line_count, last_evidence_id

    def seal(self, *, sealed_at: datetime | None = None) -> EvidenceSeal:
        """Seal the current JSONL and return its integrity metadata."""

        with self._lock:
            raw, line_count, last_evidence_id = self._snapshot()
            digest = hashlib.sha256(raw).hexdigest()
            if self.seal_path.exists():
                try:
                    existing = EvidenceSeal.from_mapping(
                        json.loads(self.seal_path.read_text(encoding="utf-8"))
                    )
                except (OSError, json.JSONDecodeError, EvidenceStoreError) as error:
                    raise EvidenceStoreError("Raw Evidence Seal cannot be read") from error
                if (
                    existing.byte_size != len(raw)
                    or existing.line_count != line_count
                    or existing.sha256 != digest
                ):
                    raise EvidenceStoreError("Raw Evidence changed after sealing")
                return existing
            seal = EvidenceSeal(
                schema_version="aia-evidence-seal-1",
                aia_session_id=self.session_id or "unbound",
                sealed_at=sealed_at or datetime.now(timezone.utc),
                raw_evidence_relative_path="evidence/raw-evidence.jsonl",
                byte_size=len(raw),
                line_count=line_count,
                sha256=digest,
                last_evidence_id=last_evidence_id,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.seal_path.with_name(f".{self.seal_path.name}.{uuid4().hex}.tmp")
            try:
                self.path.touch(exist_ok=True)
                temporary.write_text(
                    json.dumps(seal.to_mapping(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, self.seal_path)
            except OSError as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise EvidenceStoreError("Raw Evidence Seal cannot be written") from error
            return seal

    def build_index(self) -> EvidenceIndex:
        """Write an ID-to-line index without copying Raw Evidence payloads."""

        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
            except OSError as error:
                raise EvidenceStoreError("Raw Evidence cannot be read for indexing") from error
            entries: dict[str, dict[str, Any]] = {}
            line_number = 0
            for line in lines:
                line_number += 1
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    evidence_id = value["evidence_id"]
                    entries[evidence_id] = {
                        "captured_at": value.get("captured_at"),
                        "line_number": line_number,
                        "record_type": value.get("record_type"),
                        "source": value.get("source"),
                    }
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise EvidenceStoreError("Raw Evidence contains an invalid record") from error
            index = EvidenceIndex(
                schema_version="aia-evidence-index-1",
                aia_session_id=self.session_id or "unbound",
                raw_evidence_relative_path="evidence/raw-evidence.jsonl",
                entries=entries,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.index_path.with_name(f".{self.index_path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(index.to_mapping(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(temporary, self.index_path)
            except OSError as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise EvidenceStoreError("Evidence Index cannot be written") from error
            return index

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
    "EvidenceIndex",
    "EvidenceRecordType",
    "EvidenceSeal",
    "EvidenceSource",
    "EvidenceStoreError",
    "EvidenceStoreSealedError",
    "ObservationStage",
    "RawEvidenceRecord",
    "RawEvidenceStore",
]
