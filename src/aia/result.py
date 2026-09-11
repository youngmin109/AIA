"""Immutable, secret-safe canonical result contracts for one Protected Run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .session import SessionEndReason, SessionMode, SessionStatus


RESULT_SCHEMA_VERSION = "aia-result-1"


class ResultError(ValueError):
    """Base error for canonical Result values."""


class RunClassification(StrEnum):
    FIRST_ATTEMPT = "FIRST_ATTEMPT"
    REVIEWER_APPROVED_RERUN = "REVIEWER_APPROVED_RERUN"
    EXPLORATORY = "EXPLORATORY"
    ENGINEERING_FIXTURE = "ENGINEERING_FIXTURE"
    PRODUCT_PROTECTED_RUN = "PRODUCT_PROTECTED_RUN"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResultError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _copy_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _copy_mappings(values: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | Any) -> tuple[Mapping[str, Any], ...]:
    return tuple(MappingProxyType(dict(value)) for value in values)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if hasattr(value, "to_mapping") and callable(value.to_mapping):
        return _json_safe(value.to_mapping())
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class SensorSummary:
    sensor: str
    runtime_health_before_stop: str
    final_sensor_state: str
    reason: str | None = None
    failed_at: datetime | None = None
    final_checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.sensor.strip():
            raise ResultError("sensor must be non-empty")
        if self.failed_at is not None:
            object.__setattr__(self, "failed_at", _aware(self.failed_at, field_name="failed_at"))
        if self.final_checked_at is not None:
            object.__setattr__(self, "final_checked_at", _aware(self.final_checked_at, field_name="final_checked_at"))

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "final_sensor_state": self.final_sensor_state,
            "runtime_health_before_stop": self.runtime_health_before_stop,
            "sensor": self.sensor,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        if self.failed_at is not None:
            result["failed_at"] = self.failed_at.isoformat()
        if self.final_checked_at is not None:
            result["final_checked_at"] = self.final_checked_at.isoformat()
        return result


@dataclass(frozen=True, slots=True)
class ActionOutcomeRecord:
    """One action-level chain from Canonical Action to final controls."""

    action_id: str
    operation: str
    target: Mapping[str, Any]
    observation_stage: str
    evidence_ids: tuple[str, ...]
    policy_decision: str | None = None
    matched_rule_ids: tuple[str, ...] = ()
    matched_asset_types: tuple[str, ...] = ()
    attribution_grade: str | None = None
    attribution_reason: str | None = None
    enforcement_decision: str | None = None
    enforcement_route: str | None = None
    enforcement_action: str | None = None
    execution_result: str | None = None
    related_termination_id: str | None = None
    related_recovery_id: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ResultError("action_id must be non-empty")
        object.__setattr__(self, "target", _copy_mapping(self.target))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "matched_rule_ids", tuple(self.matched_rule_ids))
        object.__setattr__(self, "matched_asset_types", tuple(self.matched_asset_types))
        object.__setattr__(self, "limitations", tuple(self.limitations))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "attribution_grade": self.attribution_grade,
            "attribution_reason": self.attribution_reason,
            "evidence_ids": list(self.evidence_ids),
            "execution_result": self.execution_result,
            "enforcement_action": self.enforcement_action,
            "enforcement_decision": self.enforcement_decision,
            "enforcement_route": self.enforcement_route,
            "limitations": list(self.limitations),
            "matched_asset_types": list(self.matched_asset_types),
            "matched_rule_ids": list(self.matched_rule_ids),
            "operation": self.operation,
            "observation_stage": self.observation_stage,
            "policy_decision": self.policy_decision,
            "related_recovery_id": self.related_recovery_id,
            "related_termination_id": self.related_termination_id,
            "target": _json_safe(self.target),
        }


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Canonical immutable-by-contract Result published by finalization."""

    schema_version: str
    result_id: str
    aia_session_id: str
    workspace: str
    agent: str
    mode: SessionMode | str
    policy: Mapping[str, Any]
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime
    session_status: SessionStatus | str
    session_end_reason: SessionEndReason | str
    sensor_summary: tuple[Mapping[str, Any], ...]
    action_outcomes: tuple[ActionOutcomeRecord, ...]
    policy_evaluations: tuple[Mapping[str, Any], ...]
    attribution_results: tuple[Mapping[str, Any], ...]
    enforcement_results: tuple[Mapping[str, Any], ...]
    process_termination_result: Mapping[str, Any] | None
    user_abort_termination_result: Mapping[str, Any] | None
    protection_failure_termination_result: Mapping[str, Any] | None
    recovery_result: Mapping[str, Any] | None
    integrity_result: Mapping[str, Any] | None
    limitations: tuple[str, ...]
    evidence_references: tuple[Mapping[str, Any], ...]
    generated_at: datetime
    finalization_started_at: datetime
    finalization_completed_at: datetime
    finalization_duration_ms: float
    review_required: bool = False
    run_classification: RunClassification | str | None = None
    prior_session_id: str | None = None
    agent_native_session_id: str | None = None
    agent_execution: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for field_name in ("created_at", "ended_at", "generated_at", "finalization_started_at", "finalization_completed_at"):
            object.__setattr__(self, field_name, _aware(getattr(self, field_name), field_name=field_name))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", _aware(self.started_at, field_name="started_at"))
        object.__setattr__(self, "mode", SessionMode(self.mode))
        object.__setattr__(self, "session_status", SessionStatus(self.session_status))
        object.__setattr__(self, "session_end_reason", SessionEndReason(self.session_end_reason))
        if self.run_classification is not None:
            object.__setattr__(self, "run_classification", RunClassification(self.run_classification))
        object.__setattr__(self, "policy", _copy_mapping(self.policy))
        if self.agent_execution is not None:
            object.__setattr__(self, "agent_execution", _copy_mapping(self.agent_execution))
        object.__setattr__(self, "sensor_summary", _copy_mappings(self.sensor_summary))
        object.__setattr__(self, "policy_evaluations", _copy_mappings(self.policy_evaluations))
        object.__setattr__(self, "attribution_results", _copy_mappings(self.attribution_results))
        object.__setattr__(self, "enforcement_results", _copy_mappings(self.enforcement_results))
        object.__setattr__(self, "evidence_references", _copy_mappings(self.evidence_references))
        object.__setattr__(self, "action_outcomes", tuple(self.action_outcomes))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if self.finalization_duration_ms < 0:
            raise ResultError("finalization_duration_ms must be non-negative")

    @property
    def actions(self) -> tuple[ActionOutcomeRecord, ...]:
        return self.action_outcomes

    @property
    def session_id(self) -> str:
        return self.aia_session_id

    def to_mapping(self) -> dict[str, Any]:
        mapping = {
            "action_outcomes": [item.to_mapping() for item in self.action_outcomes],
            "agent": self.agent,
            "agent_native_session_id": self.agent_native_session_id,
            "agent_execution": _json_safe(self.agent_execution) if self.agent_execution is not None else None,
            "aia_session_id": self.aia_session_id,
            "attribution_results": [_json_safe(item) for item in self.attribution_results],
            "created_at": self.created_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "enforcement_results": [_json_safe(item) for item in self.enforcement_results],
            "evidence_references": [_json_safe(item) for item in self.evidence_references],
            "finalization_completed_at": self.finalization_completed_at.isoformat(),
            "finalization_duration_ms": self.finalization_duration_ms,
            "finalization_started_at": self.finalization_started_at.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "integrity_result": _json_safe(self.integrity_result) if self.integrity_result is not None else None,
            "limitations": list(self.limitations),
            "mode": self.mode.value,
            "policy": _json_safe(self.policy),
            "policy_evaluations": [_json_safe(item) for item in self.policy_evaluations],
            "prior_session_id": self.prior_session_id,
            "process_termination_result": _json_safe(self.process_termination_result) if self.process_termination_result is not None else None,
            "recovery_result": _json_safe(self.recovery_result) if self.recovery_result is not None else None,
            "result_id": self.result_id,
            "review_required": self.review_required,
            "run_classification": self.run_classification.value if self.run_classification is not None else None,
            "schema_version": self.schema_version,
            "sensor_summary": [_json_safe(item) for item in self.sensor_summary],
            "session_end_reason": self.session_end_reason.value,
            "session_status": self.session_status.value,
            "started_at": self.started_at.isoformat() if self.started_at is not None else None,
            "workspace": self.workspace,
        }
        # Keep the canonical bytes of pre-user-abort Result Bundles stable.
        # The field is present only when a user stop actually occurred.
        if self.user_abort_termination_result is not None:
            mapping["user_abort_termination_result"] = _json_safe(self.user_abort_termination_result)
        if self.protection_failure_termination_result is not None:
            mapping["protection_failure_termination_result"] = _json_safe(
                self.protection_failure_termination_result
            )
        return mapping

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.to_mapping(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SessionResult":
        action_outcomes = tuple(
            ActionOutcomeRecord(
                action_id=item["action_id"],
                operation=item["operation"],
                target=item.get("target", {}),
                observation_stage=item.get("observation_stage", "POST_ACTION"),
                evidence_ids=tuple(item.get("evidence_ids", ())),
                policy_decision=item.get("policy_decision"),
                matched_rule_ids=tuple(item.get("matched_rule_ids", ())),
                matched_asset_types=tuple(item.get("matched_asset_types", ())),
                attribution_grade=item.get("attribution_grade"),
                attribution_reason=item.get("attribution_reason"),
                enforcement_decision=item.get("enforcement_decision"),
                enforcement_route=item.get("enforcement_route"),
                enforcement_action=item.get("enforcement_action"),
                execution_result=item.get("execution_result"),
                related_termination_id=item.get("related_termination_id"),
                related_recovery_id=item.get("related_recovery_id"),
                limitations=tuple(item.get("limitations", ())),
            )
            for item in value.get("action_outcomes", ())
        )
        return cls(
            schema_version=value["schema_version"],
            result_id=value["result_id"],
            aia_session_id=value["aia_session_id"],
            workspace=value["workspace"],
            agent=value["agent"],
            mode=value["mode"],
            policy=value.get("policy", {}),
            created_at=datetime.fromisoformat(value["created_at"]),
            started_at=datetime.fromisoformat(value["started_at"]) if value.get("started_at") else None,
            ended_at=datetime.fromisoformat(value["ended_at"]),
            session_status=value["session_status"],
            session_end_reason=value["session_end_reason"],
            sensor_summary=tuple(value.get("sensor_summary", ())),
            action_outcomes=action_outcomes,
            policy_evaluations=tuple(value.get("policy_evaluations", ())),
            attribution_results=tuple(value.get("attribution_results", ())),
            enforcement_results=tuple(value.get("enforcement_results", ())),
            process_termination_result=value.get("process_termination_result"),
            user_abort_termination_result=value.get("user_abort_termination_result"),
            protection_failure_termination_result=value.get(
                "protection_failure_termination_result"
            ),
            recovery_result=value.get("recovery_result"),
            integrity_result=value.get("integrity_result"),
            limitations=tuple(value.get("limitations", ())),
            evidence_references=tuple(value.get("evidence_references", ())),
            generated_at=datetime.fromisoformat(value["generated_at"]),
            finalization_started_at=datetime.fromisoformat(value["finalization_started_at"]),
            finalization_completed_at=datetime.fromisoformat(value["finalization_completed_at"]),
            finalization_duration_ms=float(value.get("finalization_duration_ms", 0.0)),
            review_required=bool(value.get("review_required", False)),
            run_classification=value.get("run_classification"),
            prior_session_id=value.get("prior_session_id"),
            agent_native_session_id=value.get("agent_native_session_id"),
            agent_execution=value.get("agent_execution"),
        )


__all__ = [
    "ActionOutcomeRecord",
    "RESULT_SCHEMA_VERSION",
    "ResultError",
    "RunClassification",
    "SensorSummary",
    "SessionResult",
]
