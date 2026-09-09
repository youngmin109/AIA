"""Conservative, deterministic attribution of Canonical Actions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from types import MappingProxyType
from typing import Any

from .action import ActionTargetKind, NormalizedAction
from .evidence import EvidenceRecordType, EvidenceSource, RawEvidenceRecord
from .process_identity import ProcessIdentity, RootProcessRegistration


class AttributionError(ValueError):
    """Raised when Attribution Engine configuration is invalid."""


class AttributionGrade(StrEnum):
    EXACT = "EXACT"
    PROCESS = "PROCESS"
    TEMPORAL = "TEMPORAL"
    UNKNOWN = "UNKNOWN"


class AttributionReason(StrEnum):
    DIRECT_TRUSTED_HOOK = "DIRECT_TRUSTED_HOOK"
    VERIFIED_AGENT_PROCESS = "VERIFIED_AGENT_PROCESS"
    PROCESS_WINDOW_ASSOCIATION = "PROCESS_WINDOW_ASSOCIATION"
    TURN_WINDOW_ASSOCIATION = "TURN_WINDOW_ASSOCIATION"
    HOOK_INGRESS_UNVERIFIED = "HOOK_INGRESS_UNVERIFIED"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    NATIVE_SESSION_MISMATCH = "NATIVE_SESSION_MISMATCH"
    TOOL_IDENTIFIER_MISSING = "TOOL_IDENTIFIER_MISSING"
    CONFLICTING_TOOL_IDENTIFIER = "CONFLICTING_TOOL_IDENTIFIER"
    PROCESS_IDENTITY_MISMATCH = "PROCESS_IDENTITY_MISMATCH"
    COMPETING_CANDIDATE = "COMPETING_CANDIDATE"
    AMBIGUOUS_TURN_WINDOW = "AMBIGUOUS_TURN_WINDOW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED_PROVENANCE = "UNSUPPORTED_PROVENANCE"
    MALFORMED_LINEAGE = "MALFORMED_LINEAGE"
    TURN_IDENTIFIER_MISMATCH = "TURN_IDENTIFIER_MISMATCH"


# Friendly alias for callers that prefer the explicit Code naming.
AttributionReasonCode = AttributionReason


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AttributionError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _identity(
    payload: Mapping[str, Any],
    *,
    pid_key: str,
    create_time_key: str,
) -> ProcessIdentity | None:
    if pid_key not in payload or create_time_key not in payload:
        return None
    try:
        return ProcessIdentity(
            pid=payload[pid_key],
            create_time=payload[create_time_key],
        )
    except (TypeError, ValueError):
        return None


def _process_identity(payload: Mapping[str, Any]) -> ProcessIdentity | None:
    return _identity(payload, pid_key="pid", create_time_key="create_time")


def _root_identity(payload: Mapping[str, Any]) -> ProcessIdentity | None:
    return _identity(
        payload,
        pid_key="root_pid",
        create_time_key="root_create_time",
    )


def _parent_identity(payload: Mapping[str, Any]) -> ProcessIdentity | None:
    return _identity(
        payload,
        pid_key="parent_pid",
        create_time_key="parent_create_time",
    )


@dataclass(frozen=True, slots=True)
class TurnWindow:
    """An explicit Agent turn interval supplied by a trusted boundary."""

    turn_id: str
    aia_session_id: str
    started_at: datetime
    ended_at: datetime
    agent_native_session_id: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.turn_id, str) or not self.turn_id.strip():
            raise AttributionError("turn_id must be non-empty")
        if not isinstance(self.aia_session_id, str) or not self.aia_session_id.strip():
            raise AttributionError("aia_session_id must be non-empty")
        object.__setattr__(self, "started_at", _aware_utc(self.started_at, field_name="started_at"))
        object.__setattr__(self, "ended_at", _aware_utc(self.ended_at, field_name="ended_at"))
        if self.ended_at < self.started_at:
            raise AttributionError("ended_at must not precede started_at")
        if self.agent_native_session_id == "":
            raise AttributionError("agent_native_session_id must be non-empty when provided")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

    def contains(self, observed_at: datetime) -> bool:
        value = _aware_utc(observed_at, field_name="observed_at")
        return self.started_at <= value <= self.ended_at


@dataclass(frozen=True, slots=True)
class CompetingCandidate:
    """A known candidate that can make an Action attribution ambiguous."""

    candidate_id: str
    candidate_kind: str
    active_from: datetime
    active_until: datetime | None
    reason: str
    process_identity: ProcessIdentity | None = None
    session_id: str | None = None
    canonical_path: str | None = None
    action_id: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.candidate_kind.strip():
            raise AttributionError("candidate identifiers must be non-empty")
        object.__setattr__(self, "active_from", _aware_utc(self.active_from, field_name="active_from"))
        if self.active_until is not None:
            object.__setattr__(self, "active_until", _aware_utc(self.active_until, field_name="active_until"))
            if self.active_until < self.active_from:
                raise AttributionError("active_until must not precede active_from")
        if not self.reason.strip():
            raise AttributionError("candidate reason must be non-empty")
        if self.canonical_path is not None:
            object.__setattr__(self, "canonical_path", self.canonical_path.casefold())

    def applies_to(self, action: NormalizedAction) -> bool:
        if self.session_id is not None and self.session_id != action.aia_session_id:
            return False
        if self.action_id is not None and self.action_id != action.action_id:
            return False
        target_paths = {
            value
            for value in (
                action.canonical_path,
                action.source_path,
                action.destination_path,
            )
            if value is not None
        }
        if self.canonical_path is not None and self.canonical_path not in target_paths:
            return False
        if action.observed_at < self.active_from:
            return False
        if self.active_until is not None and action.observed_at >= self.active_until:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ProcessTreeLifetime:
    """Observed lifetime interval for one PID plus create-time identity."""

    process_identity: ProcessIdentity
    root_process_identity: ProcessIdentity
    first_observed_at: datetime
    process_role: str
    exit_observed_at: datetime | None = None
    parent_process_identity: ProcessIdentity | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "first_observed_at", _aware_utc(self.first_observed_at, field_name="first_observed_at"))
        if self.exit_observed_at is not None:
            object.__setattr__(self, "exit_observed_at", _aware_utc(self.exit_observed_at, field_name="exit_observed_at"))
            if self.exit_observed_at < self.first_observed_at:
                raise AttributionError("exit_observed_at must not precede first_observed_at")
        if not self.process_role.strip():
            raise AttributionError("process_role must be non-empty")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

    def contains(self, observed_at: datetime) -> bool:
        value = _aware_utc(observed_at, field_name="observed_at")
        return self.first_observed_at <= value and (
            self.exit_observed_at is None or value < self.exit_observed_at
        )


@dataclass(frozen=True, slots=True)
class RawEvidenceIndex:
    """Session-scoped lookup for the Raw Evidence referenced by an Action."""

    records: Mapping[str, RawEvidenceRecord]

    def __post_init__(self) -> None:
        values = dict(self.records)
        if any(not isinstance(value, RawEvidenceRecord) for value in values.values()):
            raise AttributionError("RawEvidenceIndex values must be RawEvidenceRecord instances")
        object.__setattr__(self, "records", MappingProxyType(values))

    @classmethod
    def from_records(
        cls,
        records: Mapping[str, RawEvidenceRecord] | Iterable[RawEvidenceRecord],
    ) -> "RawEvidenceIndex":
        if isinstance(records, Mapping):
            values = dict(records)
        else:
            values = {record.evidence_id: record for record in records}
        return cls(values)

    def get(self, evidence_id: str) -> RawEvidenceRecord | None:
        return self.records.get(evidence_id)


@dataclass(frozen=True, slots=True)
class AttributionResult:
    """Immutable attribution result kept separate from NormalizedAction."""

    action_id: str
    aia_session_id: str
    grade: AttributionGrade
    reason_code: AttributionReason
    reason: str
    supporting_evidence_ids: tuple[str, ...] = ()
    tool_use_id: str | None = None
    turn_id: str | None = None
    agent_native_session_id: str | None = None
    process_identity: ProcessIdentity | None = None
    root_process_identity: ProcessIdentity | None = None
    competing_candidates: tuple[CompetingCandidate, ...] = ()
    limitations: tuple[str, ...] = ()
    duplicate_evidence_count: int = 0

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.aia_session_id.strip():
            raise AttributionError("AttributionResult identifiers must be non-empty")
        object.__setattr__(self, "grade", AttributionGrade(self.grade))
        object.__setattr__(self, "reason_code", AttributionReason(self.reason_code))
        if not self.reason.strip():
            raise AttributionError("reason must be non-empty")
        object.__setattr__(self, "supporting_evidence_ids", tuple(self.supporting_evidence_ids))
        object.__setattr__(self, "competing_candidates", tuple(self.competing_candidates))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if self.duplicate_evidence_count < 0:
            raise AttributionError("duplicate_evidence_count must be non-negative")


@dataclass(frozen=True, slots=True)
class AttributedAction:
    """Optional immutable wrapper that does not mutate NormalizedAction."""

    action: NormalizedAction
    attribution: AttributionResult


@dataclass(frozen=True, slots=True)
class AttributionBatchResult:
    """Deterministically ordered batch attribution output."""

    aia_session_id: str
    results: tuple[AttributionResult, ...]
    exact_count: int
    process_count: int
    temporal_count: int
    unknown_count: int
    conflicts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(self, "limitations", tuple(self.limitations))


class AttributionEngine:
    """Conservatively attribute Normalized Actions without policy authority."""

    _VALID_PROVENANCE = frozenset(
        {"AIA_SPAWNED_ROOT", "PROTECTED_LAUNCHER", "EXPLICIT_VERIFIED_ROOT"}
    )

    def __init__(
        self,
        aia_session_id: str,
        raw_evidence: Mapping[str, RawEvidenceRecord] | Iterable[RawEvidenceRecord] = (),
        *,
        launch_context: Any | None = None,
        root_process_registration: RootProcessRegistration | None = None,
        root_process_identity: ProcessIdentity | None = None,
        root_process_provenance: str | None = None,
        turn_windows: Iterable[TurnWindow] = (),
        competing_candidates: Iterable[CompetingCandidate] = (),
        expected_agent_native_session_id: str | None = None,
    ) -> None:
        if not isinstance(aia_session_id, str) or not aia_session_id.strip():
            raise AttributionError("aia_session_id must be non-empty")
        self.aia_session_id = aia_session_id
        self.raw_evidence = RawEvidenceIndex.from_records(raw_evidence)
        self.turn_windows = tuple(turn_windows)
        self.competing_candidates = tuple(competing_candidates)
        self._root_context_error: AttributionReason | None = None
        self.root_process_identity, provenance, context_native = self._resolve_root_context(
            launch_context,
            root_process_registration,
            root_process_identity,
            root_process_provenance,
        )
        if provenance is not None and provenance not in self._VALID_PROVENANCE:
            self._root_context_error = AttributionReason.UNSUPPORTED_PROVENANCE
        self.expected_agent_native_session_id = (
            expected_agent_native_session_id
            if expected_agent_native_session_id is not None
            else context_native
        )
        if self.expected_agent_native_session_id == "":
            raise AttributionError(
                "expected_agent_native_session_id must be non-empty when provided"
            )
        self._lifetimes = self._build_lifetimes()

    def _resolve_root_context(
        self,
        launch_context: Any | None,
        root_process_registration: RootProcessRegistration | None,
        root_process_identity: ProcessIdentity | None,
        root_process_provenance: str | None,
    ) -> tuple[ProcessIdentity | None, str | None, str | None]:
        context_native: str | None = None
        provenance = root_process_provenance
        resolved_root = root_process_identity
        if launch_context is not None:
            registration = getattr(launch_context, "root_registration", None)
            resolved_root = getattr(launch_context, "root_process_identity", resolved_root)
            if registration is not None:
                resolved_root = registration.root_process_identity
            provenance = getattr(launch_context, "launch_provenance", provenance)
            context_native = getattr(launch_context, "agent_native_session_id", None)
            context_session = getattr(launch_context, "aia_session_id", self.aia_session_id)
            if context_session != self.aia_session_id:
                self._root_context_error = AttributionReason.SESSION_MISMATCH
        if root_process_registration is not None:
            if root_process_registration.aia_session_id != self.aia_session_id:
                self._root_context_error = AttributionReason.SESSION_MISMATCH
            if resolved_root is not None and resolved_root != root_process_registration.root_process_identity:
                self._root_context_error = AttributionReason.PROCESS_IDENTITY_MISMATCH
            resolved_root = root_process_registration.root_process_identity
            provenance = provenance or root_process_registration.registration_source
        return resolved_root, provenance, context_native

    def _build_lifetimes(self) -> tuple[ProcessTreeLifetime, ...]:
        observations: dict[ProcessIdentity, dict[str, Any]] = {}
        exits: dict[ProcessIdentity, datetime] = {}
        for record in self.raw_evidence.records.values():
            if record.session_id != self.aia_session_id:
                continue
            if record.record_type is EvidenceRecordType.PROCESS_OBSERVED:
                process_identity = _process_identity(record.payload)
                root_identity = _root_identity(record.payload)
                role = record.payload.get("process_role")
                if process_identity is None or root_identity is None or not isinstance(role, str):
                    continue
                parent = _parent_identity(record.payload)
                current = observations.get(process_identity)
                if current is None:
                    observations[process_identity] = {
                        "root": root_identity,
                        "first": record.captured_at,
                        "role": role,
                        "parent": parent,
                        "evidence_ids": [record.evidence_id],
                    }
                else:
                    current["first"] = min(current["first"], record.captured_at)
                    current["evidence_ids"].append(record.evidence_id)
                    if current["parent"] is None and parent is not None:
                        current["parent"] = parent
            elif record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED:
                process_identity = _process_identity(record.payload)
                if process_identity is not None:
                    previous = exits.get(process_identity)
                    exits[process_identity] = (
                        record.captured_at
                        if previous is None
                        else min(previous, record.captured_at)
                    )
        lifetimes = [
            ProcessTreeLifetime(
                process_identity=process_identity,
                root_process_identity=values["root"],
                first_observed_at=values["first"],
                exit_observed_at=(
                    exits.get(process_identity)
                    if exits.get(process_identity) is None
                    or exits[process_identity] >= values["first"]
                    else values["first"]
                ),
                process_role=values["role"],
                parent_process_identity=values["parent"],
                evidence_ids=tuple(dict.fromkeys(values["evidence_ids"])),
            )
            for process_identity, values in observations.items()
        ]
        return tuple(
            sorted(
                lifetimes,
                key=lambda item: (
                    item.first_observed_at,
                    item.process_identity.pid,
                    item.process_identity.create_time,
                ),
            )
        )

    def attribute(self, action: NormalizedAction) -> AttributionResult:
        if not isinstance(action, NormalizedAction):
            raise AttributionError("action must be a NormalizedAction")
        if action.aia_session_id != self.aia_session_id:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.SESSION_MISMATCH,
                "Action Session does not match the Attribution Session",
            )

        direct_candidate = (
            action.target_kind in {ActionTargetKind.FILE, ActionTargetKind.DIRECTORY, ActionTargetKind.COMMAND}
            and EvidenceSource.AGENT_HOOK in action.evidence_sources
        )
        if direct_candidate:
            direct = self._attribute_direct_hook(action)
            if direct is not None:
                return direct

        competing = self._active_competitors(action)
        if competing:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.COMPETING_CANDIDATE,
                "A known competing candidate overlaps this Action",
                competing_candidates=competing,
                limitations=("PROCESS_OR_TURN_ASSOCIATION_BLOCKED_BY_COMPETITOR",),
            )

        process_result = self._attribute_process(action)
        if process_result is not None:
            return process_result

        temporal_result = self._attribute_temporal(action)
        if temporal_result is not None:
            return temporal_result

        return self._result(
            action,
            AttributionGrade.UNKNOWN,
            AttributionReason.INSUFFICIENT_EVIDENCE,
            "No trusted direct Hook, verified Process Tree, or explicit Turn Window supports this Action",
        )

    def attribute_batch(self, actions: Iterable[NormalizedAction]) -> AttributionBatchResult:
        ordered = tuple(
            sorted(
                actions,
                key=lambda action: (action.observed_at, action.evidence_ids, action.action_id),
            )
        )
        results = tuple(self.attribute(action) for action in ordered)
        conflicts = tuple(
            result.reason_code.value
            for result in results
            if result.reason_code
            in {
                AttributionReason.CONFLICTING_TOOL_IDENTIFIER,
                AttributionReason.COMPETING_CANDIDATE,
                AttributionReason.AMBIGUOUS_TURN_WINDOW,
            }
        )
        limitations = tuple(
            sorted(
                {
                    limitation
                    for result in results
                    for limitation in result.limitations
                }
            )
        )
        return AttributionBatchResult(
            aia_session_id=self.aia_session_id,
            results=results,
            exact_count=sum(result.grade is AttributionGrade.EXACT for result in results),
            process_count=sum(result.grade is AttributionGrade.PROCESS for result in results),
            temporal_count=sum(result.grade is AttributionGrade.TEMPORAL for result in results),
            unknown_count=sum(result.grade is AttributionGrade.UNKNOWN for result in results),
            conflicts=conflicts,
            limitations=limitations,
        )

    def _attribute_direct_hook(self, action: NormalizedAction) -> AttributionResult | None:
        records = [self.raw_evidence.get(evidence_id) for evidence_id in action.evidence_ids]
        records = [record for record in records if record is not None]
        if not records:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.INSUFFICIENT_EVIDENCE,
                "Direct Hook Action has no referenced Raw Evidence",
            )
        if not any(record.source is EvidenceSource.AGENT_HOOK for record in records):
            return None

        pretools = [
            record for record in records if record.record_type is EvidenceRecordType.PRETOOL_REQUEST
        ]
        commands = [
            record for record in records if record.record_type is EvidenceRecordType.COMMAND_OBSERVED
        ]
        if len(pretools) != 1 or (
            action.target_kind is ActionTargetKind.COMMAND and len(commands) != 1
        ) or (
            action.target_kind is not ActionTargetKind.COMMAND and commands
        ):
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.MALFORMED_LINEAGE,
                "Direct Hook Action lineage does not contain the expected parent/child records",
            )
        parent = pretools[0]
        parent_payload = parent.payload
        if parent.session_id != self.aia_session_id:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.SESSION_MISMATCH,
                "Hook parent Session does not match the Attribution Session",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
            )
        tool_use_id = parent_payload.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not tool_use_id:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.TOOL_IDENTIFIER_MISSING,
                "Trusted direct Hook requires a non-empty tool_use_id",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
            )
        if action.tool_use_id != tool_use_id:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.CONFLICTING_TOOL_IDENTIFIER,
                "Normalized Action tool_use_id does not match Raw Hook Evidence",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
            )

        parent_trusted, trust_reason = self._hook_trust(parent_payload)
        if not parent_trusted:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                trust_reason,
                "Hook ingress is not trusted for EXACT attribution",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
                tool_use_id=tool_use_id,
                turn_id=_text(parent_payload.get("turn_id")),
                agent_native_session_id=_text(parent_payload.get("agent_native_session_id")),
            )

        command = commands[0] if commands else None
        if command is not None:
            command_payload = command.payload
            if command_payload.get("parent_evidence_id") != parent.evidence_id:
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.MALFORMED_LINEAGE,
                    "COMMAND_OBSERVED does not reference the direct PRETOOL_REQUEST parent",
                    supporting_evidence_ids=tuple(record.evidence_id for record in records),
                    tool_use_id=tool_use_id,
                )
            if command.session_id != parent.session_id:
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.SESSION_MISMATCH,
                    "Command and Hook parent belong to different Sessions",
                    supporting_evidence_ids=tuple(record.evidence_id for record in records),
                    tool_use_id=tool_use_id,
                )
            if command_payload.get("tool_use_id") != tool_use_id:
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.CONFLICTING_TOOL_IDENTIFIER,
                    "Command and Hook parent have different tool_use_id values",
                    supporting_evidence_ids=tuple(record.evidence_id for record in records),
                    tool_use_id=tool_use_id,
                )
            child_trusted, child_reason = self._hook_trust(command_payload)
            if not child_trusted:
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    child_reason,
                    "Command Hook ingress is not trusted for EXACT attribution",
                    supporting_evidence_ids=tuple(record.evidence_id for record in records),
                    tool_use_id=tool_use_id,
                )

        native_id, turn_id, identity_reason = self._compare_hook_context(
            action,
            parent_payload,
            command.payload if command is not None else None,
        )
        if identity_reason is not None:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                identity_reason,
                "Hook context identifiers are inconsistent",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
                tool_use_id=tool_use_id,
                turn_id=turn_id,
                agent_native_session_id=native_id,
            )

        duplicate_ids, conflicting, duplicate_unverified = self._hook_identifier_duplicates(tool_use_id)
        if conflicting:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.CONFLICTING_TOOL_IDENTIFIER,
                "The same tool_use_id has conflicting Hook semantics",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
                tool_use_id=tool_use_id,
                turn_id=turn_id,
                agent_native_session_id=native_id,
                duplicate_evidence_count=len(duplicate_ids),
            )
        if duplicate_unverified:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.HOOK_INGRESS_UNVERIFIED,
                "A duplicate Hook identifier includes unverified ingress evidence",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
                tool_use_id=tool_use_id,
                turn_id=turn_id,
                agent_native_session_id=native_id,
                duplicate_evidence_count=len(duplicate_ids),
            )
        if self.expected_agent_native_session_id is not None and native_id != self.expected_agent_native_session_id:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.NATIVE_SESSION_MISMATCH,
                "Hook Native Session ID does not match the expected Agent Native Session",
                supporting_evidence_ids=tuple(record.evidence_id for record in records),
                tool_use_id=tool_use_id,
                turn_id=turn_id,
                agent_native_session_id=native_id,
                duplicate_evidence_count=len(duplicate_ids),
            )
        return self._result(
            action,
            AttributionGrade.EXACT,
            AttributionReason.DIRECT_TRUSTED_HOOK,
            "Trusted direct Hook Evidence identifies the Agent Tool Use",
            supporting_evidence_ids=tuple(record.evidence_id for record in records),
            tool_use_id=tool_use_id,
            turn_id=turn_id,
            agent_native_session_id=native_id,
            duplicate_evidence_count=len(duplicate_ids),
        )

    def _hook_trust(self, payload: Mapping[str, Any]) -> tuple[bool, AttributionReason]:
        if payload.get("ingress_verified") is not True:
            return False, AttributionReason.HOOK_INGRESS_UNVERIFIED
        if "ingress_status" in payload and payload.get("ingress_status") != "VERIFIED":
            return False, AttributionReason.HOOK_INGRESS_UNVERIFIED
        return True, AttributionReason.DIRECT_TRUSTED_HOOK

    def _compare_hook_context(
        self,
        action: NormalizedAction,
        parent_payload: Mapping[str, Any],
        command_payload: Mapping[str, Any] | None,
    ) -> tuple[str | None, str | None, AttributionReason | None]:
        values = [parent_payload]
        if command_payload is not None:
            values.append(command_payload)
        native_values = {
            value
            for payload in values
            for value in (_text(payload.get("agent_native_session_id")),)
            if value is not None
        }
        turn_values = {
            value
            for payload in values
            for value in (_text(payload.get("turn_id")),)
            if value is not None
        }
        if len(native_values) > 1:
            return None, None, AttributionReason.NATIVE_SESSION_MISMATCH
        if len(turn_values) > 1:
            return None, None, AttributionReason.TURN_IDENTIFIER_MISMATCH
        native_id = next(iter(native_values), None)
        turn_id = next(iter(turn_values), None)
        if action.agent_native_session_id is not None and action.agent_native_session_id != native_id:
            return native_id, turn_id, AttributionReason.NATIVE_SESSION_MISMATCH
        if action.turn_id is not None and action.turn_id != turn_id:
            return native_id, turn_id, AttributionReason.TURN_IDENTIFIER_MISMATCH
        return native_id, turn_id, None

    def _hook_identifier_duplicates(
        self,
        tool_use_id: str,
    ) -> tuple[tuple[str, ...], bool, bool]:
        related: list[tuple[str, str]] = []
        unverified = False
        for record in self.raw_evidence.records.values():
            if record.session_id != self.aia_session_id:
                continue
            if record.record_type is not EvidenceRecordType.PRETOOL_REQUEST:
                continue
            if record.payload.get("tool_use_id") != tool_use_id:
                continue
            if record.payload.get("ingress_verified") is not True:
                unverified = True
            command = next(
                (
                    child
                    for child in self.raw_evidence.records.values()
                    if child.record_type is EvidenceRecordType.COMMAND_OBSERVED
                    and child.session_id == record.session_id
                    and child.payload.get("parent_evidence_id") == record.evidence_id
                ),
                None,
            )
            signature_payload = {
                "tool_name": record.payload.get("tool_name"),
                "tool_input": record.payload.get("tool_input"),
                "command": command.payload.get("raw_command") if command else None,
                "native": record.payload.get("agent_native_session_id"),
                "turn": record.payload.get("turn_id"),
            }
            related.append(
                (
                    record.evidence_id,
                    json.dumps(signature_payload, ensure_ascii=False, sort_keys=True, default=str),
                )
            )
            if command is not None:
                related.append((command.evidence_id, related[-1][1]))
                if command.payload.get("ingress_verified") is not True:
                    unverified = True
        signatures = {signature for _, signature in related}
        return (
            tuple(sorted(identifier for identifier, _ in related)),
            len(signatures) > 1,
            unverified,
        )

    def _attribute_process(self, action: NormalizedAction) -> AttributionResult | None:
        if action.target_kind is ActionTargetKind.PROCESS:
            referenced = [
                self.raw_evidence.get(evidence_id)
                for evidence_id in action.evidence_ids
            ]
            if not any(
                record is not None
                and record.session_id == self.aia_session_id
                and record.record_type is EvidenceRecordType.PROCESS_OBSERVED
                for record in referenced
            ):
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.INSUFFICIENT_EVIDENCE,
                    "Process Action does not reference PROCESS_OBSERVED Raw Evidence",
                )
            lifetime = next(
                (
                    item
                    for item in self._lifetimes
                    if item.process_identity == action.process_identity
                    and item.contains(action.observed_at)
                ),
                None,
            )
            if lifetime is None:
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.PROCESS_IDENTITY_MISMATCH,
                    "Process Action has no valid observed lifetime",
                )
            if not self._is_verified_agent_lifetime(lifetime):
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    self._root_context_error or AttributionReason.PROCESS_IDENTITY_MISMATCH,
                    "Process identity cannot be verified against the protected Agent Root",
                    supporting_evidence_ids=lifetime.evidence_ids,
                    process_identity=lifetime.process_identity,
                    root_process_identity=lifetime.root_process_identity,
                )
            return self._result(
                action,
                AttributionGrade.PROCESS,
                AttributionReason.VERIFIED_AGENT_PROCESS,
                "Process was observed in the verified Agent Process Tree",
                supporting_evidence_ids=lifetime.evidence_ids,
                process_identity=lifetime.process_identity,
                root_process_identity=lifetime.root_process_identity,
            )

        if action.target_kind not in {ActionTargetKind.FILE, ActionTargetKind.DIRECTORY}:
            return None
        active = [
            item
            for item in self._lifetimes
            if item.contains(action.observed_at) and self._is_verified_agent_lifetime(item)
        ]
        if not active:
            return None
        selected = active[0]
        supporting = tuple(dict.fromkeys(action.evidence_ids + selected.evidence_ids))
        return self._result(
            action,
            AttributionGrade.PROCESS,
            AttributionReason.PROCESS_WINDOW_ASSOCIATION,
            "Filesystem Action overlaps a verified Agent Process Tree observation window",
            supporting_evidence_ids=supporting,
            process_identity=selected.process_identity,
            root_process_identity=selected.root_process_identity,
            limitations=("PROCESS_TREE_ASSOCIATION_ONLY",),
        )

    def _is_verified_agent_lifetime(self, lifetime: ProcessTreeLifetime) -> bool:
        if self._root_context_error is not None:
            return False
        if self.root_process_identity is None:
            return False
        if lifetime.root_process_identity != self.root_process_identity:
            return False
        if lifetime.process_role == "ROOT":
            return lifetime.process_identity == lifetime.root_process_identity
        if lifetime.process_role != "DESCENDANT":
            return False
        by_identity = {item.process_identity: item for item in self._lifetimes}
        current = lifetime
        visited: set[ProcessIdentity] = set()
        while current.parent_process_identity is not None:
            if current.process_identity in visited:
                return False
            visited.add(current.process_identity)
            parent = by_identity.get(current.parent_process_identity)
            if parent is None or parent.root_process_identity != self.root_process_identity:
                return False
            if parent.process_identity == self.root_process_identity:
                return True
            current = parent
        return False

    def _attribute_temporal(self, action: NormalizedAction) -> AttributionResult | None:
        if action.target_kind not in {ActionTargetKind.FILE, ActionTargetKind.DIRECTORY}:
            return None
        overlapping = [
            window
            for window in self.turn_windows
            if window.contains(action.observed_at)
        ]
        if overlapping and not any(
            window.aia_session_id == self.aia_session_id for window in overlapping
        ):
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.SESSION_MISMATCH,
                "Overlapping Turn Window belongs to another AIA Session",
            )
        matching = [
            window
            for window in overlapping
            if window.aia_session_id == self.aia_session_id
            and self._turn_window_matches_native(window, action)
        ]
        if not matching:
            if overlapping and (
                self.expected_agent_native_session_id is not None
                or action.agent_native_session_id is not None
            ):
                return self._result(
                    action,
                    AttributionGrade.UNKNOWN,
                    AttributionReason.NATIVE_SESSION_MISMATCH,
                    "Overlapping Turn Window has a different Native Session ID",
                )
            return None
        distinct = {window.turn_id for window in matching}
        if len(distinct) > 1:
            return self._result(
                action,
                AttributionGrade.UNKNOWN,
                AttributionReason.AMBIGUOUS_TURN_WINDOW,
                "More than one distinct Agent Turn Window overlaps this Action",
                supporting_evidence_ids=tuple(
                    evidence_id
                    for window in matching
                    for evidence_id in window.evidence_ids
                ),
                limitations=("TEMPORAL_ASSOCIATION_AMBIGUOUS",),
            )
        window = sorted(matching, key=lambda item: (item.started_at, item.turn_id))[0]
        return self._result(
            action,
            AttributionGrade.TEMPORAL,
            AttributionReason.TURN_WINDOW_ASSOCIATION,
            "Action timestamp overlaps one explicit Agent Turn Window",
            supporting_evidence_ids=window.evidence_ids,
            turn_id=window.turn_id,
            agent_native_session_id=window.agent_native_session_id,
            limitations=("TEMPORAL_ASSOCIATION_ONLY",),
        )

    def _turn_window_matches_native(self, window: TurnWindow, action: NormalizedAction) -> bool:
        if self.expected_agent_native_session_id is not None:
            if window.agent_native_session_id != self.expected_agent_native_session_id:
                return False
        if action.agent_native_session_id is not None and window.agent_native_session_id != action.agent_native_session_id:
            return False
        return True

    def _active_competitors(self, action: NormalizedAction) -> tuple[CompetingCandidate, ...]:
        agent_identities = {
            item.process_identity
            for item in self._lifetimes
            if item.contains(action.observed_at) and self._is_verified_agent_lifetime(item)
        }
        return tuple(
            candidate
            for candidate in sorted(
                self.competing_candidates,
                key=lambda item: (item.active_from, item.candidate_id),
            )
            if candidate.applies_to(action)
            and candidate.process_identity not in agent_identities
        )

    def _result(
        self,
        action: NormalizedAction,
        grade: AttributionGrade,
        reason_code: AttributionReason,
        reason: str,
        *,
        supporting_evidence_ids: Iterable[str] = (),
        tool_use_id: str | None = None,
        turn_id: str | None = None,
        agent_native_session_id: str | None = None,
        process_identity: ProcessIdentity | None = None,
        root_process_identity: ProcessIdentity | None = None,
        competing_candidates: Iterable[CompetingCandidate] = (),
        limitations: Iterable[str] = (),
        duplicate_evidence_count: int = 0,
    ) -> AttributionResult:
        return AttributionResult(
            action_id=action.action_id,
            aia_session_id=action.aia_session_id,
            grade=grade,
            reason_code=reason_code,
            reason=reason,
            supporting_evidence_ids=tuple(dict.fromkeys(supporting_evidence_ids)),
            tool_use_id=tool_use_id if tool_use_id is not None else action.tool_use_id,
            turn_id=turn_id if turn_id is not None else action.turn_id,
            agent_native_session_id=(
                agent_native_session_id
                if agent_native_session_id is not None
                else action.agent_native_session_id
            ),
            process_identity=process_identity,
            root_process_identity=root_process_identity,
            competing_candidates=tuple(competing_candidates),
            limitations=tuple(dict.fromkeys(limitations)),
            duplicate_evidence_count=duplicate_evidence_count,
        )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def attribute_actions(
    actions: Iterable[NormalizedAction],
    *,
    aia_session_id: str,
    raw_evidence: Mapping[str, RawEvidenceRecord] | Iterable[RawEvidenceRecord] = (),
    launch_context: Any | None = None,
    root_process_registration: RootProcessRegistration | None = None,
    root_process_identity: ProcessIdentity | None = None,
    root_process_provenance: str | None = None,
    turn_windows: Iterable[TurnWindow] = (),
    competing_candidates: Iterable[CompetingCandidate] = (),
    expected_agent_native_session_id: str | None = None,
) -> AttributionBatchResult:
    return AttributionEngine(
        aia_session_id,
        raw_evidence,
        launch_context=launch_context,
        root_process_registration=root_process_registration,
        root_process_identity=root_process_identity,
        root_process_provenance=root_process_provenance,
        turn_windows=turn_windows,
        competing_candidates=competing_candidates,
        expected_agent_native_session_id=expected_agent_native_session_id,
    ).attribute_batch(actions)


__all__ = [
    "AttributionBatchResult",
    "AttributionEngine",
    "AttributionError",
    "AttributionGrade",
    "AttributionReason",
    "AttributionReasonCode",
    "AttributionResult",
    "AttributedAction",
    "CompetingCandidate",
    "ProcessTreeLifetime",
    "RawEvidenceIndex",
    "TurnWindow",
    "attribute_actions",
]
