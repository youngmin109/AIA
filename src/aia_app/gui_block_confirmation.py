from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re
from typing import Any

from aia.codex_runtime import CodexPreToolController
from aia.enforcement import EnforcementDecision, EnforcementRoute
from aia.evidence import EvidenceRecordType, EvidenceSource, RawEvidenceRecord
from .codex_app_server import CodexHookEvent, CodexHookEventSnapshot


_EXEC_CALL_ID = re.compile(
    r"exec-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_SAFE_CODEX_STATUSES = {"blocked", "completed", "running", "failed", "error", "missing", "ambiguous"}
_SAFE_TURN_STATUSES = {"completed", "interrupted", "failed", "inProgress"}


class HookRunIdentity:
    """Strictly parsed identity fields from a Codex hook_run_id."""

    __slots__ = ("event_type", "index", "hooks_path", "call_id")

    def __init__(self, event_type: str, index: int, hooks_path: str, call_id: str) -> None:
        self.event_type = event_type
        self.index = index
        self.hooks_path = hooks_path
        self.call_id = call_id


def parse_hook_run_id(value: Any) -> HookRunIdentity | None:
    """Parse only the observed event:index:path:exec-UUID form."""

    if not isinstance(value, str):
        return None
    event_type, first_separator, remainder = value.partition(":")
    index_text, second_separator, remainder = remainder.partition(":")
    hooks_path, last_separator, call_id = remainder.rpartition(":")
    if (
        not first_separator
        or not second_separator
        or not last_separator
        or event_type not in {"pre-tool-use", "post-tool-use"}
        or not index_text.isascii()
        or not index_text.isdigit()
        or not hooks_path
        or not os.path.isabs(hooks_path)
        or _EXEC_CALL_ID.fullmatch(call_id) is None
    ):
        return None
    return HookRunIdentity(event_type, int(index_text), hooks_path, call_id)


def _normalized_path(value: str | Path) -> str | None:
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(os.fspath(value)))))
    except (OSError, TypeError, ValueError):
        return None


def _record_type(record: RawEvidenceRecord) -> str:
    return str(getattr(record.record_type, "value", record.record_type))


def _tool_use_id(record: RawEvidenceRecord) -> str | None:
    value = record.payload.get("tool_use_id")
    return value if isinstance(value, str) and value else None


def _turn_id(record: RawEvidenceRecord) -> str | None:
    value = record.payload.get("turn_id")
    return value if isinstance(value, str) and value else None


def _is_pretool_deny(event: Any) -> bool:
    gate = getattr(event, "gate_result", None)
    return (
        getattr(gate, "decision", None) is EnforcementDecision.CONTAIN
        and getattr(gate, "route", None) is EnforcementRoute.PRETOOL_BLOCK
    )


def _event_records(event: Any) -> tuple[RawEvidenceRecord, ...]:
    return tuple(
        record
        for record in getattr(event, "records", ())
        if isinstance(record, RawEvidenceRecord)
        and record.source is EvidenceSource.AGENT_HOOK
        and _record_type(record) == EvidenceRecordType.PRETOOL_REQUEST.value
    )


def _safe_status(value: Any, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _matching_codex_pair(
    hook_events: Sequence[CodexHookEvent],
    *,
    tool_use_id: str,
    hooks_path: str,
) -> tuple[CodexHookEvent | None, CodexHookEvent | None, str, bool]:
    expected_path = _normalized_path(hooks_path)
    if expected_path is None:
        return None, None, "missing", False
    matches: list[tuple[CodexHookEvent, Any]] = []
    for event in hook_events:
        if event.event_name != "preToolUse":
            continue
        identity = parse_hook_run_id(event.hook_run_id)
        if identity is None or identity.event_type != "pre-tool-use":
            continue
        if identity.call_id != tool_use_id:
            continue
        if _normalized_path(identity.hooks_path) != expected_path:
            continue
        matches.append((event, identity))

    started = [(event, identity) for event, identity in matches if event.phase == "started"]
    completed = [(event, identity) for event, identity in matches if event.phase == "completed"]
    if len(completed) == 1:
        codex_status = _safe_status(completed[0][0].status, _SAFE_CODEX_STATUSES)
    elif len(completed) > 1 or len(matches) > 2:
        codex_status = "ambiguous"
    else:
        codex_status = "missing"
    if len(started) != 1 or len(completed) != 1 or len(matches) != 2:
        return (
            started[0][0] if len(started) == 1 else None,
            completed[0][0] if len(completed) == 1 else None,
            codex_status,
            False,
        )

    started_event, started_identity = started[0]
    completed_event, completed_identity = completed[0]
    paired = (
        started_event.hook_run_id == completed_event.hook_run_id
        and started_identity.call_id == completed_identity.call_id
        and started_identity.hooks_path == completed_identity.hooks_path
        and started_identity.index == completed_identity.index
        and started_event.sequence < completed_event.sequence
        and (
            not started_event.turn_id
            or not completed_event.turn_id
            or started_event.turn_id == completed_event.turn_id
        )
    )
    return started_event, completed_event, codex_status, paired


def _basis(
    *,
    codex_status: str,
    posttool_count: int | None,
    posttool_absent: bool | None,
    pretool_count: int | None,
    protected_file_change_count: int | None,
    file_sensor_healthy: bool | None,
    turn_status: str,
    collection_complete: bool,
    broker_drained: bool,
    process_status: str,
) -> dict[str, Any]:
    return {
        "method": "app_server_call_identity_1_to_1",
        "codex_status": codex_status,
        "aia_pretool_count": pretool_count,
        "posttool_count": posttool_count,
        "posttool_absent": posttool_absent,
        "protected_file_change_count": protected_file_change_count,
        "file_sensor_status": (
            "HEALTHY" if file_sensor_healthy is True
            else "UNHEALTHY" if file_sensor_healthy is False
            else "UNKNOWN"
        ),
        "turn_status": turn_status,
        "collection_status": "COMPLETE" if collection_complete else "INCOMPLETE",
        "broker_barrier_status": "COMPLETE" if broker_drained else "INCOMPLETE",
        "process_status": process_status,
    }


def confirm_gui_pretool_blocks(
    controller: CodexPreToolController,
    *,
    hook_snapshot: CodexHookEventSnapshot | None,
    evidence_records: Sequence[RawEvidenceRecord] | None,
    hooks_path: str | Path,
    broker_drained: bool,
    protected_file_change_count: int | None,
    file_sensor_healthy: bool | None,
    hook_sensor_healthy: bool | None,
    interrupted: bool = False,
) -> tuple[bool | None, ...]:
    """Confirm each GUI deny only when its independent call-level proof is complete."""

    events = tuple(controller.events)
    all_records = tuple(evidence_records) if evidence_records is not None else None
    normalized_hooks_path = _normalized_path(hooks_path)
    snapshot_complete = bool(
        hook_snapshot is not None
        and hook_snapshot.collection_complete
        and hook_snapshot.reader_finished
        and not hook_snapshot.overflowed
        and not hook_snapshot.missing
        and hook_snapshot.all_turns_completed
    )
    process_ok = bool(
        hook_snapshot is not None
        and hook_snapshot.process_exit_code == 0
        and hook_snapshot.unexpected_exit is False
    )
    process_status = (
        "EXITED" if process_ok
        else "FAILED" if hook_snapshot is not None and hook_snapshot.process_exit_code not in {None, 0}
        else "UNKNOWN"
    )
    results: list[bool | None] = []

    for event in events:
        if not _is_pretool_deny(event):
            continue
        event_pretool_records = _event_records(event)
        tool_use_id = getattr(event, "tool_use_id", None)
        action_id = getattr(getattr(event, "action", None), "action_id", None)
        if not isinstance(tool_use_id, str) or not tool_use_id:
            if isinstance(action_id, str):
                controller.confirm_block(
                    tool_use_id if isinstance(tool_use_id, str) else "",
                    None,
                    action_id=action_id,
                    confirmation_basis=_basis(
                        codex_status="missing",
                        posttool_count=None,
                        posttool_absent=None,
                        pretool_count=None,
                        protected_file_change_count=protected_file_change_count,
                        file_sensor_healthy=file_sensor_healthy,
                        turn_status="unknown",
                        collection_complete=snapshot_complete,
                        broker_drained=broker_drained,
                        process_status=process_status,
                    ),
                )
            results.append(None)
            continue

        pretool_records = (
            [record for record in all_records
             if record.source is EvidenceSource.AGENT_HOOK
             and _record_type(record) == EvidenceRecordType.PRETOOL_REQUEST.value
             and _tool_use_id(record) == tool_use_id]
            if all_records is not None
            else None
        )
        posttool_records = (
            [record for record in all_records
             if record.source is EvidenceSource.AGENT_HOOK
             and _record_type(record) == EvidenceRecordType.POSTTOOL_OBSERVED.value
             and _tool_use_id(record) == tool_use_id]
            if all_records is not None
            else None
        )
        pretool_count = len(pretool_records) if pretool_records is not None else None
        posttool_count = len(posttool_records) if posttool_records is not None else None
        controller_call_count = sum(
            1 for item in events if getattr(item, "tool_use_id", None) == tool_use_id
        )
        aia_turn = _turn_id(pretool_records[0]) if pretool_records and len(pretool_records) == 1 else None
        event_turn = _turn_id(event_pretool_records[0]) if len(event_pretool_records) == 1 else None
        if aia_turn and event_turn and aia_turn != event_turn:
            turn_status = "mismatch"
        else:
            event_turn = event_turn or aia_turn
            turn_status = "unknown"

        codex_status = "missing"
        pair_valid = False
        started_event = None
        completed_event = None
        if hook_snapshot is not None and normalized_hooks_path is not None:
            started_event, completed_event, codex_status, pair_valid = _matching_codex_pair(
                hook_snapshot.events,
                tool_use_id=tool_use_id,
                hooks_path=os.fspath(hooks_path),
            )
            codex_turns = {
                item for item in (
                    getattr(started_event, "turn_id", None),
                    getattr(completed_event, "turn_id", None),
                ) if isinstance(item, str) and item
            }
            if len(codex_turns) > 1 or (event_turn and codex_turns and event_turn not in codex_turns):
                turn_status = "mismatch"
            else:
                event_turn = event_turn or next(iter(codex_turns), None)
                if turn_status != "mismatch" and hook_snapshot is not None and event_turn:
                    raw_turn_status = hook_snapshot.turn_statuses.get(event_turn)
                    turn_status = _safe_status(raw_turn_status, _SAFE_TURN_STATUSES)
                    completed_sequence = hook_snapshot.turn_completion_sequences.get(event_turn)
                    if (
                        turn_status == "completed"
                        and completed_event is not None
                        and (completed_sequence is None or completed_sequence <= completed_event.sequence)
                    ):
                        turn_status = "incomplete"

        direct_posttool = getattr(event, "confirmed_block", None) is False
        posttool_seen = direct_posttool or (posttool_count is not None and posttool_count > 0)
        if posttool_seen:
            confirmation: bool | None = False
        else:
            confirmation = True if (
                not interrupted
                and all_records is not None
                and pretool_count == 1
                and len(event_pretool_records) == 1
                and _tool_use_id(event_pretool_records[0]) == tool_use_id
                and pretool_records[0].evidence_id == event_pretool_records[0].evidence_id
                and controller_call_count == 1
                and hook_sensor_healthy is True
                and not controller.errors
                and codex_status == "blocked"
                and pair_valid
                and snapshot_complete
                and process_ok
                and turn_status == "completed"
                and broker_drained
                and file_sensor_healthy is True
                and protected_file_change_count == 0
                and normalized_hooks_path is not None
            ) else None

        basis = _basis(
            codex_status=codex_status,
            posttool_count=posttool_count,
            posttool_absent=(
                False if direct_posttool
                else None if posttool_count is None
                else posttool_count == 0
            ),
            pretool_count=pretool_count,
            protected_file_change_count=protected_file_change_count,
            file_sensor_healthy=file_sensor_healthy,
            turn_status=turn_status,
            collection_complete=snapshot_complete,
            broker_drained=broker_drained,
            process_status=process_status,
        )
        controller.confirm_block(
            tool_use_id,
            confirmation,
            action_id=action_id if isinstance(action_id, str) else None,
            confirmation_basis=basis,
        )
        results.append(confirmation)
    return tuple(results)