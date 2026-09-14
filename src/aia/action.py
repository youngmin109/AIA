"""Immutable Canonical Action values derived from Raw Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .evidence import EvidenceRecordType, EvidenceSource, ObservationStage
from .policy import Operation
from .process_identity import ProcessIdentity


class ActionTargetKind(StrEnum):
    """The mechanical target shape carried by a Canonical Action."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    COMMAND = "COMMAND"
    PROCESS = "PROCESS"


class NormalizationCompleteness(StrEnum):
    """Structural completeness of one normalized observation."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNUSABLE = "UNUSABLE"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class NormalizedAction:
    """One immutable, deterministic action representation.

    This model deliberately contains observation facts and structural
    limitations only. It has no attribution grade, policy decision, risk
    classification, or enforcement authority.
    """

    action_id: str
    aia_session_id: str
    operation: Operation
    stage: ObservationStage
    target_kind: ActionTargetKind
    observed_at: datetime
    evidence_ids: tuple[str, ...]
    evidence_sources: tuple[EvidenceSource, ...]
    completeness: NormalizationCompleteness
    normalizer_version: str
    limitations: tuple[str, ...] = ()
    canonical_path: str | None = None
    source_path: str | None = None
    destination_path: str | None = None
    target_is_directory: bool | None = None
    raw_command: str | None = None
    normalized_command: str | None = None
    process_identity: ProcessIdentity | None = None
    root_process_identity: ProcessIdentity | None = None
    parent_process_identity: ProcessIdentity | None = None
    process_role: str | None = None
    process_name: str | None = None
    process_executable: str | None = None
    agent_native_session_id: str | None = None
    turn_id: str | None = None
    tool_use_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be non-empty")
        if not isinstance(self.aia_session_id, str) or not self.aia_session_id.strip():
            raise ValueError("aia_session_id must be non-empty")
        object.__setattr__(self, "operation", Operation(self.operation))
        object.__setattr__(self, "stage", ObservationStage(self.stage))
        object.__setattr__(self, "target_kind", ActionTargetKind(self.target_kind))
        object.__setattr__(self, "completeness", NormalizationCompleteness(self.completeness))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, field_name="observed_at"))
        if not self.evidence_ids or any(
            not isinstance(value, str) or not value.strip() for value in self.evidence_ids
        ):
            raise ValueError("evidence_ids must contain at least one non-empty ID")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(
            self,
            "evidence_sources",
            tuple(EvidenceSource(value) for value in self.evidence_sources),
        )
        if not self.evidence_sources:
            raise ValueError("evidence_sources must not be empty")
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if not isinstance(self.normalizer_version, str) or not self.normalizer_version.strip():
            raise ValueError("normalizer_version must be non-empty")
        if self.target_is_directory is not None and not isinstance(
            self.target_is_directory, bool
        ):
            raise ValueError("target_is_directory must be a bool or None")


@dataclass(frozen=True, slots=True)
class NormalizationIssue:
    """A record-level normalization problem retained in a batch result."""

    code: str
    message: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("NormalizationIssue code and message must be non-empty")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class NonActionEvidence:
    """Raw Evidence intentionally retained without creating an action."""

    evidence_id: str
    session_id: str
    record_type: EvidenceRecordType
    source: EvidenceSource
    captured_at: datetime
    reason: str

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.session_id.strip():
            raise ValueError("NonActionEvidence identifiers must be non-empty")
        object.__setattr__(self, "record_type", EvidenceRecordType(self.record_type))
        object.__setattr__(self, "source", EvidenceSource(self.source))
        object.__setattr__(self, "captured_at", _aware_utc(self.captured_at, field_name="captured_at"))
        if not self.reason.strip():
            raise ValueError("NonActionEvidence reason must be non-empty")


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Deterministic batch output with per-record issues preserved."""

    aia_session_id: str
    normalized_at: datetime
    actions: tuple[NormalizedAction, ...]
    issues: tuple[NormalizationIssue, ...]
    non_action_evidence: tuple[NonActionEvidence, ...]
    total_input_records: int
    normalized_action_count: int
    partial_count: int
    unusable_count: int
    non_action_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_at", _aware_utc(self.normalized_at, field_name="normalized_at"))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "non_action_evidence", tuple(self.non_action_evidence))
        for name in (
            "total_input_records",
            "normalized_action_count",
            "partial_count",
            "unusable_count",
            "non_action_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "ActionTargetKind",
    "NonActionEvidence",
    "NormalizationCompleteness",
    "NormalizationIssue",
    "NormalizationResult",
    "NormalizedAction",
]
