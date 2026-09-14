"""Deterministic canonical Audit Trail records for finalized Protected Runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from typing import Any, Iterable


class AuditError(ValueError):
    """Raised when an Audit Record is invalid."""


class AuditEventType(StrEnum):
    SESSION_CREATED = "SESSION_CREATED"
    PROTECTION_STARTED = "PROTECTION_STARTED"
    POLICY_FROZEN = "POLICY_FROZEN"
    LEASE_ACQUIRED = "LEASE_ACQUIRED"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    SENSOR_HEALTH = "SENSOR_HEALTH"
    AGENT_LAUNCHED = "AGENT_LAUNCHED"
    ACTION_OBSERVED = "ACTION_OBSERVED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    ATTRIBUTION_EVALUATED = "ATTRIBUTION_EVALUATED"
    ENFORCEMENT_DECIDED = "ENFORCEMENT_DECIDED"
    ENFORCEMENT_EXECUTED = "ENFORCEMENT_EXECUTED"
    PROCESS_TERMINATED = "PROCESS_TERMINATED"
    USER_ABORT_EXECUTED = "USER_ABORT_EXECUTED"
    PROTECTION_FAILURE_EXECUTED = "PROTECTION_FAILURE_EXECUTED"
    RECOVERY_EXECUTED = "RECOVERY_EXECUTED"
    INTEGRITY_VERIFIED = "INTEGRITY_VERIFIED"
    SENSOR_STOPPED = "SENSOR_STOPPED"
    SESSION_FINALIZED = "SESSION_FINALIZED"


_PHASE_ORDER = {event.value: index for index, event in enumerate(AuditEventType)}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuditError("occurred_at must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """An authoritative result reference, not a Raw Sensor Evidence record."""

    audit_id: str
    aia_session_id: str
    occurred_at: datetime
    event_type: AuditEventType | str
    entity_type: str
    entity_id: str
    source_reference: str
    action_id: str | None = None
    reason_code: str | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        for field_name in ("audit_id", "aia_session_id", "entity_type", "entity_id", "source_reference"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise AuditError(f"{field_name} must be non-empty")
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at))
        object.__setattr__(self, "event_type", AuditEventType(self.event_type))

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "audit_id": self.audit_id,
            "aia_session_id": self.aia_session_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "source_reference": self.source_reference,
            "summary": self.summary,
        }
        if self.action_id is not None:
            result["action_id"] = self.action_id
        if self.reason_code is not None:
            result["reason_code"] = self.reason_code
        return result

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.occurred_at,
            _PHASE_ORDER.get(self.event_type.value, len(_PHASE_ORDER)),
            self.entity_id,
            self.audit_id,
        )


def order_audit_records(records: Iterable[AuditRecord]) -> tuple[AuditRecord, ...]:
    return tuple(sorted(records, key=AuditRecord.sort_key))


def audit_jsonl(records: Iterable[AuditRecord]) -> bytes:
    ordered = order_audit_records(records)
    return b"".join(
        (json.dumps(record.to_mapping(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for record in ordered
    )


__all__ = [
    "AuditError",
    "AuditEventType",
    "AuditRecord",
    "audit_jsonl",
    "order_audit_records",
]
