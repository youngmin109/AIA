"""Deterministic Raw Evidence to Canonical Action normalization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import ntpath
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .action import (
    ActionTargetKind,
    NonActionEvidence,
    NormalizationCompleteness,
    NormalizationIssue,
    NormalizationResult,
    NormalizedAction,
)
from .evidence import (
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    RawEvidenceRecord,
)
from .policy import Operation, normalize_command
from .process_identity import ProcessIdentity


NORMALIZER_VERSION = "canonical-v1"

# Only a tool contract already present in the MVP fixtures is supported here.
# Similar-looking names are intentionally not accepted by fuzzy matching.
HOOK_TOOL_SEMANTICS = MappingProxyType(
    {
        "read_file": Operation.READ,
    }
)


class NormalizationError(ValueError):
    """Raised when the Normalizer configuration is invalid."""


@dataclass(frozen=True, slots=True)
class _PathResult:
    canonical_path: str | None
    limitation: str | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_session_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or any(separator in value for separator in ("/", "\\"))
    ):
        raise NormalizationError("aia_session_id is not a safe value")
    return value


def _collapse_parts(parts: Iterable[str]) -> tuple[str, ...] | None:
    result: list[str] = []
    for part in parts:
        if not part or part == ".":
            continue
        if part == "..":
            if not result:
                return None
            result.pop()
            continue
        result.append(part)
    return tuple(result)


def _absolute_parts(path: str) -> tuple[str, tuple[str, ...]] | None:
    drive, tail = ntpath.splitdrive(path.replace("/", "\\"))
    if not drive or not tail.startswith("\\"):
        return None
    parts = _collapse_parts(tail.replace("\\", "/").split("/"))
    if parts is None:
        return None
    return drive.casefold(), tuple(part.casefold() for part in parts)


def canonicalize_workspace_path(
    raw_path: str,
    workspace: str | Path,
) -> _PathResult:
    """Canonicalize a path lexically relative to a Windows workspace.

    The raw path is never resolved through the filesystem. This preserves the
    lexical security contract and avoids following symlinks or reparse points.
    """

    if not isinstance(raw_path, str) or not raw_path.strip():
        return _PathResult(None, "PATH_MISSING")
    workspace_text = str(Path(workspace).expanduser().resolve(strict=False))
    workspace_abs = _absolute_parts(workspace_text)
    if workspace_abs is None:
        return _PathResult(None, "INVALID_WORKSPACE_SCOPE")
    workspace_drive, workspace_parts = workspace_abs

    value = raw_path.strip().replace("\\", "/")
    drive, tail = ntpath.splitdrive(value.replace("/", "\\"))
    has_drive = bool(drive)
    is_absolute = value.startswith("/") or (
        has_drive and tail.startswith(("/", "\\"))
    )

    if has_drive and not is_absolute:
        return _PathResult(None, "OUTSIDE_WORKSPACE")

    if is_absolute:
        raw_abs = _absolute_parts(value)
        if raw_abs is None:
            return _PathResult(None, "OUTSIDE_WORKSPACE")
        raw_drive, raw_parts = raw_abs
        if raw_drive != workspace_drive:
            return _PathResult(None, "OUTSIDE_WORKSPACE")
        if len(raw_parts) < len(workspace_parts) or raw_parts[: len(workspace_parts)] != workspace_parts:
            return _PathResult(None, "OUTSIDE_WORKSPACE")
        relative_parts = raw_parts[len(workspace_parts) :]
    else:
        relative = _collapse_parts(value.split("/"))
        if relative is None:
            return _PathResult(None, "OUTSIDE_WORKSPACE")
        relative_parts = tuple(part.casefold() for part in relative)

    return _PathResult("/".join(relative_parts) or ".")


def _parent_path(value: str) -> str:
    return value.rsplit("/", 1)[0] if "/" in value else ""


def _action_id(
    *,
    session_id: str,
    evidence_ids: tuple[str, ...],
    interpretation: str,
    ordinal: int,
    normalizer_version: str,
) -> str:
    material = json.dumps(
        {
            "evidence_ids": evidence_ids,
            "interpretation": interpretation,
            "normalizer_version": normalizer_version,
            "ordinal": ordinal,
            "session_id": session_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid5(NAMESPACE_URL, material))


def _ordered_unique(values: Iterable[Any]) -> tuple[Any, ...]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class Normalizer:
    """Convert one Session's Raw Evidence into deterministic actions."""

    def __init__(
        self,
        aia_session_id: str,
        workspace: str | Path,
        *,
        normalizer_version: str = NORMALIZER_VERSION,
    ) -> None:
        self.aia_session_id = _safe_session_id(aia_session_id)
        try:
            self.workspace = Path(workspace).expanduser().resolve(strict=False)
        except (TypeError, ValueError, OSError) as error:
            raise NormalizationError("workspace is invalid") from error
        if not self.workspace.is_absolute():
            raise NormalizationError("workspace must be absolute")
        if not isinstance(normalizer_version, str) or not normalizer_version.strip():
            raise NormalizationError("normalizer_version must be non-empty")
        self.normalizer_version = normalizer_version

    def normalize(self, records: Iterable[RawEvidenceRecord]) -> NormalizationResult:
        """Normalize a batch without modifying or persisting Raw Evidence."""

        input_records = tuple(records)
        valid_records = tuple(
            record for record in input_records if isinstance(record, RawEvidenceRecord)
        )
        ordered = tuple(
            sorted(
                valid_records,
                key=lambda record: (
                    record.captured_at,
                    record.evidence_id,
                ),
            )
        )
        record_by_id = {
            record.evidence_id: record
            for record in ordered
            if isinstance(record, RawEvidenceRecord)
        }
        command_parent_ids = {
            parent_id
            for parent_id in (
                record.payload.get("parent_evidence_id")
                for record in ordered
                if record.record_type is EvidenceRecordType.COMMAND_OBSERVED
            )
            if isinstance(parent_id, str)
        }
        actions: list[NormalizedAction] = []
        issues: list[NormalizationIssue] = []
        non_actions: list[NonActionEvidence] = []
        for item in input_records:
            if not isinstance(item, RawEvidenceRecord):
                issues.append(
                    NormalizationIssue(
                        code="MALFORMED_INPUT_RECORD",
                        message="Input is not a RawEvidenceRecord",
                    )
                )

        for record in ordered:
            if record.session_id != self.aia_session_id:
                issues.append(
                    NormalizationIssue(
                        code="SESSION_MISMATCH",
                        message="Raw Evidence belongs to another AIA Session",
                        evidence_ids=(record.evidence_id,),
                    )
                )
                continue

            if record.record_type is EvidenceRecordType.FILESYSTEM_EVENT:
                action, record_issues = self._filesystem_action(record)
            elif record.record_type is EvidenceRecordType.PRETOOL_REQUEST:
                action, record_issues = self._pretool_action(
                    record,
                    command_parent_ids=command_parent_ids,
                )
            elif record.record_type is EvidenceRecordType.COMMAND_OBSERVED:
                action, record_issues = self._command_action(
                    record,
                    record_by_id=record_by_id,
                )
            elif record.record_type is EvidenceRecordType.PROCESS_OBSERVED:
                action, record_issues = self._process_action(record)
            elif record.record_type is EvidenceRecordType.PROCESS_EXIT_OBSERVED:
                action = None
                record_issues = ()
                non_actions.append(
                    NonActionEvidence(
                        evidence_id=record.evidence_id,
                        session_id=record.session_id,
                        record_type=record.record_type,
                        source=record.source,
                        captured_at=record.captured_at,
                        reason="NON_ACTION_LIFECYCLE_EVIDENCE",
                    )
                )
            elif record.record_type is EvidenceRecordType.SENSOR_HEALTH:
                action = None
                record_issues = ()
                non_actions.append(
                    NonActionEvidence(
                        evidence_id=record.evidence_id,
                        session_id=record.session_id,
                        record_type=record.record_type,
                        source=record.source,
                        captured_at=record.captured_at,
                        reason="NON_ACTION_SENSOR_EVIDENCE",
                    )
                )
            elif record.record_type is EvidenceRecordType.POSTTOOL_OBSERVED:
                action = None
                record_issues = ()
                non_actions.append(
                    NonActionEvidence(
                        evidence_id=record.evidence_id,
                        session_id=record.session_id,
                        record_type=record.record_type,
                        source=record.source,
                        captured_at=record.captured_at,
                        reason="NON_ACTION_POSTTOOL_CONFIRMATION_EVIDENCE",
                    )
                )
            else:
                action = None
                record_issues = (
                    NormalizationIssue(
                        code="UNSUPPORTED_RECORD_TYPE",
                        message="Raw Evidence record type is not supported",
                        evidence_ids=(record.evidence_id,),
                    ),
                )
            issues.extend(record_issues)
            if action is not None:
                actions.append(action)

        actions.sort(key=lambda action: (action.observed_at, action.evidence_ids, action.action_id))
        issues.sort(key=lambda issue: (issue.evidence_ids, issue.code, issue.message))
        non_actions.sort(key=lambda item: (item.captured_at, item.evidence_id))
        return NormalizationResult(
            aia_session_id=self.aia_session_id,
            normalized_at=_now_utc(),
            actions=tuple(actions),
            issues=tuple(issues),
            non_action_evidence=tuple(non_actions),
            total_input_records=len(input_records),
            normalized_action_count=len(actions),
            partial_count=sum(
                action.completeness is NormalizationCompleteness.PARTIAL
                for action in actions
            ),
            unusable_count=sum(
                action.completeness is NormalizationCompleteness.UNUSABLE
                for action in actions
            ),
            non_action_count=len(non_actions),
        )

    def _action(
        self,
        record: RawEvidenceRecord,
        *,
        evidence_ids: tuple[str, ...] | None = None,
        evidence_sources: tuple[EvidenceSource, ...] | None = None,
        interpretation: str,
        completeness: NormalizationCompleteness,
        limitations: tuple[str, ...] = (),
        **fields: Any,
    ) -> NormalizedAction:
        ids = evidence_ids or (record.evidence_id,)
        sources = evidence_sources or (record.source,)
        return NormalizedAction(
            action_id=_action_id(
                session_id=self.aia_session_id,
                evidence_ids=ids,
                interpretation=interpretation,
                ordinal=0,
                normalizer_version=self.normalizer_version,
            ),
            aia_session_id=self.aia_session_id,
            operation=fields.pop("operation"),
            stage=record.observation_stage,
            target_kind=fields.pop("target_kind"),
            observed_at=record.captured_at,
            evidence_ids=ids,
            evidence_sources=sources,
            completeness=completeness,
            normalizer_version=self.normalizer_version,
            limitations=limitations,
            **fields,
        )

    def _filesystem_action(
        self,
        record: RawEvidenceRecord,
    ) -> tuple[NormalizedAction | None, tuple[NormalizationIssue, ...]]:
        payload = record.payload
        event_type = payload.get("event_type")
        operation_by_event = {
            "created": Operation.CREATE,
            "modified": Operation.MODIFY,
            "deleted": Operation.DELETE,
        }
        issues: list[NormalizationIssue] = []
        if event_type == "moved":
            raw_source = payload.get("src_path")
            raw_destination = payload.get("dest_path")
            source = canonicalize_workspace_path(raw_source, self.workspace)
            destination = canonicalize_workspace_path(raw_destination, self.workspace)
            limitations = tuple(
                value
                for value in (source.limitation, destination.limitation)
                if value is not None
            )
            if source.canonical_path is None or destination.canonical_path is None:
                issues.append(
                    NormalizationIssue(
                        code="PATH_OUTSIDE_OR_INVALID",
                        message="MOVE/RENAME source or destination is outside the Workspace or invalid",
                        evidence_ids=(record.evidence_id,),
                    )
                )
                operation = Operation.MOVE
                completeness = NormalizationCompleteness.UNUSABLE
            else:
                operation = (
                    Operation.RENAME
                    if _parent_path(source.canonical_path)
                    == _parent_path(destination.canonical_path)
                    else Operation.MOVE
                )
                completeness = NormalizationCompleteness.COMPLETE
            return (
                self._action(
                    record,
                    interpretation="filesystem-move",
                    operation=operation,
                    target_kind=(
                        ActionTargetKind.DIRECTORY
                        if payload.get("is_directory") is True
                        else ActionTargetKind.FILE
                    ),
                    source_path=source.canonical_path,
                    destination_path=destination.canonical_path,
                    target_is_directory=(
                        payload.get("is_directory")
                        if isinstance(payload.get("is_directory"), bool)
                        else None
                    ),
                    completeness=completeness,
                    limitations=limitations,
                ),
                tuple(issues),
            )
        if event_type == "modified" and payload.get("content_unchanged") is True:
            # The File Sensor compared the bytes with the last known content
            # and found them identical: a permission or metadata change.
            return (
                None,
                (
                    NormalizationIssue(
                        code="CONTENT_UNCHANGED",
                        message="Modified event with unchanged content is kept as Raw Evidence, not a MODIFY action",
                        evidence_ids=(record.evidence_id,),
                    ),
                ),
            )
        operation = operation_by_event.get(event_type)
        if operation is None:
            return (
                None,
                (
                    NormalizationIssue(
                        code="UNSUPPORTED_FILESYSTEM_EVENT",
                        message="Filesystem event has no official Operation mapping",
                        evidence_ids=(record.evidence_id,),
                    ),
                ),
            )
        path = canonicalize_workspace_path(payload.get("src_path"), self.workspace)
        limitations = (path.limitation,) if path.limitation is not None else ()
        if path.canonical_path is None:
            issues.append(
                NormalizationIssue(
                    code="PATH_OUTSIDE_OR_INVALID",
                    message="Filesystem path is outside the Workspace or invalid",
                    evidence_ids=(record.evidence_id,),
                )
            )
        is_directory = payload.get("is_directory")
        target_kind = (
            ActionTargetKind.DIRECTORY
            if is_directory is True
            else ActionTargetKind.FILE
        )
        completeness = (
            NormalizationCompleteness.PARTIAL
            if path.canonical_path is None
            else NormalizationCompleteness.COMPLETE
        )
        if not isinstance(is_directory, bool):
            limitations = (*limitations, "DIRECTORY_FLAG_MISSING")
            completeness = NormalizationCompleteness.PARTIAL
        return (
            self._action(
                record,
                interpretation=f"filesystem-{event_type}",
                operation=operation,
                target_kind=target_kind,
                canonical_path=path.canonical_path,
                target_is_directory=is_directory if isinstance(is_directory, bool) else None,
                completeness=completeness,
                limitations=limitations,
            ),
            tuple(issues),
        )

    def _pretool_action(
        self,
        record: RawEvidenceRecord,
        *,
        command_parent_ids: set[Any],
    ) -> tuple[NormalizedAction | None, tuple[NormalizationIssue, ...]]:
        payload = record.payload
        if payload.get("command_observed") is True or record.evidence_id in command_parent_ids:
            if record.evidence_id not in command_parent_ids:
                return (
                    None,
                    (
                        NormalizationIssue(
                            code="COMMAND_EVIDENCE_MISSING",
                            message="PRETOOL_REQUEST declares a command but no child COMMAND_OBSERVED references it",
                            evidence_ids=(record.evidence_id,),
                        ),
                    ),
                )
            return None, ()

        tool_name = payload.get("tool_name")
        operation = HOOK_TOOL_SEMANTICS.get(tool_name)
        if operation is None:
            return (
                None,
                (
                    NormalizationIssue(
                        code="UNSUPPORTED_TOOL_SEMANTICS",
                        message="Hook tool has no explicit semantic registry entry",
                        evidence_ids=(record.evidence_id,),
                    ),
                ),
            )
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, Mapping):
            return (
                None,
                (
                    NormalizationIssue(
                        code="TOOL_INPUT_INVALID",
                        message="Supported file tool does not contain a structured tool_input object",
                        evidence_ids=(record.evidence_id,),
                    ),
                ),
            )
        raw_path = tool_input.get("path")
        raw_target = tool_input.get("target")
        issues: list[NormalizationIssue] = []
        path_result = canonicalize_workspace_path(raw_path, self.workspace)
        if raw_path is None and isinstance(raw_target, str):
            path_result = canonicalize_workspace_path(raw_target, self.workspace)
            limitations = ("PATH_FIELD_MISSING_TARGET_USED",)
        else:
            limitations = ()
        if isinstance(raw_path, str) and isinstance(raw_target, str):
            target_result = canonicalize_workspace_path(raw_target, self.workspace)
            if (
                path_result.canonical_path is not None
                and target_result.canonical_path is not None
                and path_result.canonical_path != target_result.canonical_path
            ):
                limitations = (*limitations, "CONFLICTING_PATH_TARGET")
                issues.append(
                    NormalizationIssue(
                        code="CONFLICTING_PATH_TARGET",
                        message="Hook path and target refer to different lexical targets",
                        evidence_ids=(record.evidence_id,),
                    )
                )
        if path_result.limitation is not None:
            limitations = (*limitations, path_result.limitation)
        if path_result.canonical_path is None:
            issues.append(
                NormalizationIssue(
                    code="PATH_MISSING_OR_INVALID",
                    message="Supported file tool has no safe Workspace-relative path",
                    evidence_ids=(record.evidence_id,),
                )
            )
        completeness = (
            NormalizationCompleteness.UNUSABLE
            if "CONFLICTING_PATH_TARGET" in limitations
            else (
                NormalizationCompleteness.PARTIAL
                if limitations or path_result.canonical_path is None
                else NormalizationCompleteness.COMPLETE
            )
        )
        return (
            self._action(
                record,
                interpretation="hook-file-tool",
                operation=operation,
                target_kind=ActionTargetKind.FILE,
                canonical_path=path_result.canonical_path,
                target_is_directory=None,
                agent_native_session_id=_as_text(payload.get("agent_native_session_id")),
                turn_id=_as_text(payload.get("turn_id")),
                tool_use_id=_as_text(payload.get("tool_use_id")),
                completeness=completeness,
                limitations=limitations,
            ),
            tuple(issues),
        )

    def _command_action(
        self,
        record: RawEvidenceRecord,
        *,
        record_by_id: Mapping[str, RawEvidenceRecord],
    ) -> tuple[NormalizedAction | None, tuple[NormalizationIssue, ...]]:
        payload = record.payload
        raw_command = payload.get("raw_command")
        issues: list[NormalizationIssue] = []
        limitations: list[str] = []
        parent_id = payload.get("parent_evidence_id")
        parent = record_by_id.get(parent_id) if isinstance(parent_id, str) else None
        valid_parent = (
            parent is not None
            and parent.record_type is EvidenceRecordType.PRETOOL_REQUEST
            and parent.session_id == record.session_id
            and isinstance(parent.payload.get("tool_use_id"), str)
            and isinstance(payload.get("tool_use_id"), str)
            and bool(parent.payload.get("tool_use_id"))
            and bool(payload.get("tool_use_id"))
            and parent.payload.get("tool_use_id") == payload.get("tool_use_id")
        )
        if valid_parent:
            evidence_ids = (parent.evidence_id, record.evidence_id)
            evidence_sources = _ordered_unique((parent.source, record.source))
            parent_payload = parent.payload
        else:
            evidence_ids = (record.evidence_id,)
            evidence_sources = (record.source,)
            parent_payload = {}
            limitations.append("COMMAND_PARENT_UNVERIFIED")
            issues.append(
                NormalizationIssue(
                    code="COMMAND_PARENT_UNVERIFIED",
                    message="COMMAND_OBSERVED parent is missing or does not match Session/tool identity",
                    evidence_ids=(record.evidence_id,),
                )
            )
        if not isinstance(raw_command, str) or not raw_command:
            limitations.append("RAW_COMMAND_MISSING")
            issues.append(
                NormalizationIssue(
                    code="RAW_COMMAND_MISSING",
                    message="COMMAND_OBSERVED has no non-empty raw command",
                    evidence_ids=(record.evidence_id,),
                )
            )
            return (
                self._action(
                    record,
                    evidence_ids=evidence_ids,
                    evidence_sources=evidence_sources,
                    interpretation="command",
                    operation=Operation.EXECUTE,
                    target_kind=ActionTargetKind.COMMAND,
                    raw_command=raw_command if isinstance(raw_command, str) else None,
                    normalized_command=None,
                    agent_native_session_id=_as_text(
                        payload.get("agent_native_session_id")
                        or parent_payload.get("agent_native_session_id")
                    ),
                    turn_id=_as_text(payload.get("turn_id") or parent_payload.get("turn_id")),
                    tool_use_id=_as_text(payload.get("tool_use_id")),
                    completeness=NormalizationCompleteness.UNUSABLE,
                    limitations=tuple(_ordered_unique(limitations)),
                ),
                tuple(issues),
            )
        try:
            normalized = normalize_command(raw_command)
        except (TypeError, ValueError):
            normalized = None
            limitations.append("COMMAND_NORMALIZATION_FAILED")
            issues.append(
                NormalizationIssue(
                    code="COMMAND_NORMALIZATION_FAILED",
                    message="Raw command cannot be lexically normalized",
                    evidence_ids=(record.evidence_id,),
                )
            )
        completeness = (
            NormalizationCompleteness.COMPLETE
            if valid_parent and normalized is not None
            else (
                NormalizationCompleteness.UNUSABLE
                if normalized is None
                else NormalizationCompleteness.PARTIAL
            )
        )
        return (
            self._action(
                record,
                evidence_ids=evidence_ids,
                evidence_sources=evidence_sources,
                interpretation="command",
                operation=Operation.EXECUTE,
                target_kind=ActionTargetKind.COMMAND,
                raw_command=raw_command,
                normalized_command=normalized,
                agent_native_session_id=_as_text(
                    payload.get("agent_native_session_id")
                    or parent_payload.get("agent_native_session_id")
                ),
                turn_id=_as_text(payload.get("turn_id") or parent_payload.get("turn_id")),
                tool_use_id=_as_text(payload.get("tool_use_id")),
                completeness=completeness,
                limitations=tuple(_ordered_unique(limitations)),
            ),
            tuple(issues),
        )

    def _process_action(
        self,
        record: RawEvidenceRecord,
    ) -> tuple[NormalizedAction | None, tuple[NormalizationIssue, ...]]:
        payload = record.payload
        issues: list[NormalizationIssue] = []
        limitations: list[str] = []

        def identity(prefix: str) -> ProcessIdentity | None:
            pid_key = f"{prefix}pid"
            time_key = f"{prefix}create_time"
            if pid_key not in payload or time_key not in payload:
                return None
            try:
                return ProcessIdentity(
                    pid=payload[pid_key],
                    create_time=payload[time_key],
                )
            except (TypeError, ValueError):
                return None

        process_identity = identity("")
        root_identity = identity("root_")
        parent_identity = identity("parent_")
        if process_identity is None or root_identity is None:
            limitations.append("PROCESS_IDENTITY_MISSING_OR_INVALID")
            issues.append(
                NormalizationIssue(
                    code="PROCESS_IDENTITY_MISSING_OR_INVALID",
                    message="PROCESS_OBSERVED does not contain valid process/root identity",
                    evidence_ids=(record.evidence_id,),
                )
            )
        metadata_status = payload.get("metadata_status")
        if metadata_status != "COMPLETE":
            limitations.append("PROCESS_METADATA_PARTIAL")
        raw_command = payload.get("raw_command")
        if raw_command is not None and (
            not isinstance(raw_command, str) or not raw_command.strip()
        ):
            raw_command = None
            limitations.append("PROCESS_COMMAND_LINE_INVALID")
            issues.append(
                NormalizationIssue(
                    code="PROCESS_COMMAND_LINE_INVALID",
                    message="PROCESS_OBSERVED raw command is not a valid command line",
                    evidence_ids=(record.evidence_id,),
                )
            )
        if ("parent_pid" in payload) != ("parent_create_time" in payload):
            limitations.append("PARENT_IDENTITY_PARTIAL")
            issues.append(
                NormalizationIssue(
                    code="PARENT_IDENTITY_PARTIAL",
                    message="PROCESS_OBSERVED contains only part of parent identity",
                    evidence_ids=(record.evidence_id,),
                )
            )
        if process_identity is None or root_identity is None:
            completeness = NormalizationCompleteness.UNUSABLE
        elif limitations:
            completeness = NormalizationCompleteness.PARTIAL
        else:
            completeness = NormalizationCompleteness.COMPLETE
        return (
            self._action(
                record,
                interpretation="process-observed",
                operation=Operation.EXECUTE,
                target_kind=ActionTargetKind.PROCESS,
                process_identity=process_identity,
                root_process_identity=root_identity,
                parent_process_identity=parent_identity,
                process_role=_as_text(payload.get("process_role")),
                process_name=_as_text(payload.get("name")),
                process_executable=_as_text(payload.get("executable")),
                raw_command=raw_command,
                normalized_command=(
                    normalize_command(raw_command)
                    if raw_command is not None
                    else None
                ),
                completeness=completeness,
                limitations=tuple(_ordered_unique(limitations)),
            ),
            tuple(issues),
        )


def normalize_evidence(
    records: Iterable[RawEvidenceRecord],
    *,
    aia_session_id: str,
    workspace: str | Path,
    normalizer_version: str = NORMALIZER_VERSION,
) -> NormalizationResult:
    """Functional convenience wrapper around :class:`Normalizer`."""

    return Normalizer(
        aia_session_id,
        workspace,
        normalizer_version=normalizer_version,
    ).normalize(records)


__all__ = [
    "HOOK_TOOL_SEMANTICS",
    "NORMALIZER_VERSION",
    "NormalizationError",
    "Normalizer",
    "canonicalize_workspace_path",
    "normalize_evidence",
]
