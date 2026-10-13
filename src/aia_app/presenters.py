"""Pure presentation mapping from Core result data to console views."""

from __future__ import annotations

from collections import deque
from heapq import nlargest
from typing import Any, Mapping

from .presenters_evidence_chain import (
    _SAFE_TOOL_NAMES,
    _evidence_chain_action_view,
    _evidence_chain_indexes,
    _evidence_chain_run_status,
    _evidence_chain_sensor_links,
    _evidence_chain_stages,
    action_view,
    evidence_chain_views,
    result_action_chain_views,
    safe_target,
    safe_tool_name,
)


from .presenters_result_events import (
    _INCIDENT_DECISION_LABELS,
    _INCIDENT_OPERATION_LABELS,
    _INCIDENT_REASON_LABELS,
    _INCIDENT_RESULT_LABELS,
    _SAFE_EVENT_OPERATION_LABELS,
    _incident_reason_label,
    _incident_summary,
    action_summary,
    evidence_summary,
    incident_view,
    incident_views_for_result,
    safe_event_views,
)


def evidence_timeline_views(
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    *,
    actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    attribution_results: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Build a chronological, metadata-only sensor timeline.

    The timeline is intentionally separate from the policy event list.  It
    shows what each sensor recorded, then links the record to an Action ID
    when the existing evidence identifier relationship proves that link.
    Payload values are never copied into this view.
    """

    if limit <= 0:
        return []

    def _line_number(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _sort_key(indexed_item: tuple[int, Mapping[str, Any]]) -> tuple[str, int, int]:
        index, item = indexed_item
        return (str(item.get("captured_at") or ""), _line_number(item.get("line")), index)

    chronological_tail: deque[tuple[int, Mapping[str, Any]]] = deque(maxlen=limit)
    previous_key: tuple[str, int, int] | None = None
    input_is_chronological = True
    for index, item in enumerate(evidence_metadata):
        if not isinstance(item, Mapping) or not item.get("evidence_id"):
            continue
        indexed_item = (index, item)
        key = _sort_key(indexed_item)
        if previous_key is not None and key < previous_key:
            input_is_chronological = False
            break
        chronological_tail.append(indexed_item)
        previous_key = key
    if input_is_chronological:
        latest_metadata = list(chronological_tail)
    else:
        latest_metadata = nlargest(
            limit,
            (
                (index, item)
                for index, item in enumerate(evidence_metadata)
                if isinstance(item, Mapping) and item.get("evidence_id")
            ),
            key=_sort_key,
        )
        latest_metadata.sort(key=_sort_key)
    selected_evidence_ids = {str(item["evidence_id"]) for _, item in latest_metadata}

    action_by_evidence: dict[str, Mapping[str, Any]] = {}
    attribution_support_by_action: dict[str, tuple[str, ...]] = {}
    for item in attribution_results:
        if not isinstance(item, Mapping) or not item.get("action_id"):
            continue
        attribution_support_by_action[str(item["action_id"])] = tuple(
            str(value)
            for value in item.get("supporting_evidence_ids") or ()
            if isinstance(value, str) and value
        )
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_id = str(action.get("action_id")) if action.get("action_id") else ""
        for evidence_id in action.get("evidence_ids") or ():
            if isinstance(evidence_id, str) and evidence_id in selected_evidence_ids:
                action_by_evidence[evidence_id] = action
        for evidence_id in attribution_support_by_action.get(action_id, ()):
            if evidence_id in selected_evidence_ids:
                action_by_evidence[evidence_id] = action

    summaries = {
        "PRETOOL_REQUEST": "PreToolUse 요청",
        "POSTTOOL_OBSERVED": "도구 실행 결과 관찰",
        "FILESYSTEM_EVENT": "파일 시스템 변화",
        "PROCESS_OBSERVED": "프로세스 관찰",
        "PROCESS_EXIT_OBSERVED": "프로세스 종료 관찰",
        "SENSOR_HEALTH": "센서 상태 기록",
    }
    records: list[dict[str, Any]] = []
    for _, item in latest_metadata:
        evidence_id = str(item["evidence_id"])
        record_type = str(item.get("record_type") or "EVIDENCE")
        source = str(item.get("source") or "UNKNOWN")
        action = action_by_evidence.get(evidence_id)
        operation = str(action.get("operation")) if action and action.get("operation") else None
        target = action.get("target") if action and isinstance(action.get("target"), Mapping) else {}
        target_label = (
            "명령 실행"
            if operation == "EXECUTE" or target.get("target_kind") == "COMMAND"
            else "파일·프로세스 행위"
            if action
            else "센서 기록"
        )
        records.append(
            {
                "evidence_id": evidence_id,
                "captured_at": item.get("captured_at"),
                "line": item.get("line"),
                "source": source,
                "record_type": record_type,
                "observation_stage": item.get("observation_stage"),
                "summary": summaries.get(record_type, "Evidence 관찰"),
                "linked_action_id": action.get("action_id") if action else None,
                "operation": operation,
                "target_label": target_label,
                "link_status": "LINKED" if action else "UNLINKED",
            }
        )
    return records


def attribution_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    grades = {grade: 0 for grade in ("EXACT", "PROCESS", "TEMPORAL", "UNKNOWN")}
    counted_action_ids: set[str] = set()
    for item in result.get("action_outcomes") or ():
        if not isinstance(item, Mapping):
            continue
        action_id = item.get("action_id")
        grade = item.get("attribution_grade") or item.get("attribution_class")
        if grade in grades:
            grades[grade] += 1
            if action_id is not None:
                counted_action_ids.add(str(action_id))
    for item in result.get("attribution_results") or ():
        if not isinstance(item, Mapping):
            continue
        action_id = item.get("action_id")
        if action_id is not None and str(action_id) in counted_action_ids:
            continue
        grade = item.get("grade") or item.get("attribution_grade")
        if grade in grades:
            grades[grade] += 1
            if action_id is not None:
                counted_action_ids.add(str(action_id))

    automatic_control_happened = False
    control_grades = []
    for item in result.get("enforcement_results") or ():
        if not isinstance(item, Mapping):
            continue
        if not (
            item.get("enforcement_decision") == "CONTAIN"
            and item.get("enforcement_action") in {"BLOCKED", "TERMINATED"}
            and item.get("execution_result") == "SUCCEEDED"
        ):
            continue
        automatic_control_happened = True
        grade = item.get("attribution_grade")
        if grade in grades and grade not in control_grades:
            control_grades.append(grade)
    return {
        "counts": grades,
        "automatic_control_happened": automatic_control_happened,
        "automatic_control_grades": control_grades,
    }


def _result_execution_policy(
    result: Mapping[str, Any], action_outcomes: list[Mapping[str, Any]]
) -> dict[str, Any]:
    agent_execution = result.get("agent_execution") or {}
    output_observation = agent_execution.get("output_observation") or {}
    effective_sandbox = (
        output_observation.get("effective_sandbox")
        if isinstance(output_observation, Mapping)
        else None
    )
    effective_approval_policy = (
        output_observation.get("effective_approval_policy")
        if isinstance(output_observation, Mapping)
        else None
    )
    requested_sandbox = "workspace-write"
    requested_approval_policy = "on-request"
    if "CODEX_FULL_ACCESS_USER_SELECTED" in (result.get("limitations") or ()) and effective_sandbox == "danger-full-access":
        # The run started in full access (YOLO), as the user chose.
        requested_sandbox, requested_approval_policy = "danger-full-access", "never"
    if effective_sandbox is None and effective_approval_policy is None:
        execution_policy_status = "NOT_OBSERVED"
    elif (
        effective_sandbox == requested_sandbox
        and effective_approval_policy == requested_approval_policy
    ):
        execution_policy_status = "MATCHED"
    else:
        execution_policy_status = "DEGRADED"
    verified_block = any(
        isinstance(item, Mapping)
        and item.get("enforcement_action") == "BLOCKED"
        and item.get("execution_result") == "SUCCEEDED"
        for item in action_outcomes
    )
    if verified_block:
        codex_block_confirmation = "BLOCK_CONFIRMED"
    elif output_observation:
        codex_block_confirmation = "NOT_CONFIRMED"
    else:
        codex_block_confirmation = "NOT_AVAILABLE"
    return {
        "codex_block_confirmation": codex_block_confirmation,
        "codex_block_confirmation_reason": output_observation.get("reason"),
        "execution_policy_status": execution_policy_status,
        "requested_sandbox": requested_sandbox,
        "requested_approval_policy": requested_approval_policy,
        "effective_sandbox": effective_sandbox,
        "effective_approval_policy": effective_approval_policy,
    }


def _recovery_summary(recovery: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": recovery.get("recovery_status") or recovery.get("status") or "NOT_ATTEMPTED",
        "reason": recovery.get("reason"),
        "planned_operations": int(recovery.get("planned_operation_count") or 0),
        "attempted_operations": int(recovery.get("attempted_operation_count") or 0),
        "succeeded_operations": int(recovery.get("succeeded_operation_count") or 0),
        "failed_operations": int(recovery.get("failed_operation_count") or 0),
        "restored_paths": len(recovery.get("restored_paths") or []),
        "removed_paths": len(recovery.get("removed_paths") or []),
        "failed_paths": len(recovery.get("failed_paths") or []),
    }


def _integrity_summary(integrity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": integrity.get("integrity_status") or integrity.get("status") or "NOT_ATTEMPTED",
        "reason": integrity.get("reason"),
        "expected_entries": int(integrity.get("expected_entry_count") or 0),
        "actual_entries": int(integrity.get("actual_entry_count") or 0),
        "missing_paths": len(integrity.get("missing_paths") or []),
        "unexpected_paths": len(integrity.get("unexpected_paths") or []),
        "changed_paths": len(integrity.get("changed_paths") or []),
        "verification_errors": len(integrity.get("verification_errors") or []),
    }


def result_view(result: Mapping[str, Any], bundle_status: str) -> dict[str, Any]:
    incidents = incident_views_for_result(result)
    incident_action_ids = {
        item.get("action_id")
        for item in incidents
        if item.get("action_id") is not None
    }
    actions = [
        {
            **action_view(item),
            "incident": item.get("action_id") in incident_action_ids,
        }
        for item in result.get("action_outcomes", [])
    ]
    policy = result.get("policy") or {}
    recovery = result.get("recovery_result") or {}
    integrity = result.get("integrity_result") or {}
    action_outcomes = result.get("action_outcomes") or []
    execution_policy = _result_execution_policy(result, action_outcomes)
    limitations = list(result.get("limitations") or [])
    unsupported_tool_review_decisions = [
        item
        for item in limitations
        if item in {
            "UNSUPPORTED_TOOL_REVIEW_APPROVED",
            "UNSUPPORTED_TOOL_REVIEW_DECLINED",
            "UNSUPPORTED_TOOL_REVIEW_TIMED_OUT",
        }
    ]
    limitations.extend(
        item
        for item in (
            "PROCESS는 exact file writer 증명이 아닙니다.",
            "post-action 감지는 prevention이 아닙니다.",
            "structured READ interception은 제한됩니다.",
            "지원 범위 밖 경로 또는 Hook 우회 시 보호 수준이 저하될 수 있습니다.",
        )
        if item not in limitations
    )
    first_action = actions[0] if actions else {}
    recovery_summary = _recovery_summary(recovery)
    integrity_summary = _integrity_summary(integrity)
    return {
        "action_summary": action_summary(result),
        "attribution_summary": attribution_summary(result),
        "evidence_summary": result.get("evidence_summary") or evidence_summary(()),
        "agent": result.get("agent"),
        "attribution_results": list(result.get("attribution_results") or []),
        "bundle_status": bundle_status,
        **execution_policy,
        "ended_at": result.get("ended_at"),
        "enforcement_results": list(result.get("enforcement_results") or []),
        "incidents": incidents,
        "integrity": result.get("integrity_result"),
        "user_abort_termination": result.get("user_abort_termination_result"),
        "protection_failure_termination": result.get(
            "protection_failure_termination_result"
        ),
        "limitations": limitations,
        "unsupported_tool_review_decisions": unsupported_tool_review_decisions,
        "mode": result.get("mode"),
        "posttool_event_count": int(result.get("posttool_event_count") or 0),
        "policy": result.get("policy"),
        "policy_id": policy.get("policy_id") or policy.get("id"),
        "policy_version": policy.get("policy_version") or policy.get("version"),
        "run_classification": result.get("run_classification"),
        "recovery": result.get("recovery_result"),
        "recovery_summary": recovery_summary,
        "recovery_status": recovery.get("status") or recovery.get("recovery_status") or "NOT_ATTEMPTED",
        "integrity_status": integrity.get("status") or integrity.get("integrity_status") or "NOT_ATTEMPTED",
        "integrity_summary": integrity_summary,
        "session_end_reason": result.get("session_end_reason"),
        "policy_state": first_action.get("policy") or "—",
        "policy_effect_state": first_action.get("policy_effect") or "—",
        "attribution_state": first_action.get("attribution_class") or "—",
        "enforcement_state": first_action.get("enforcement_action") or "—",
        "execution_state": first_action.get("execution_result") or "—",
        "evidence_ids": first_action.get("evidence_ids") or [],
        "sensor_summary": list(result.get("sensor_summary") or []),
        "session_end_reason": result.get("session_end_reason"),
        "session_status": result.get("session_status"),
        "session_id": result.get("aia_session_id"),
        "started_at": result.get("started_at"),
        "workspace": result.get("workspace"),
        "actions": actions,
        "events": safe_event_views(actions),
        "result_action_chains": result_action_chain_views(
            action_outcomes,
            attribution_results=result.get("attribution_results") or (),
            recovery=result.get("recovery_result"),
        ),
        "evidence_chains": evidence_chain_views(
            actions,
            attribution_results=result.get("attribution_results") or (),
            recovery=result.get("recovery_result"),
            integrity=result.get("integrity_result"),
        ),
        "evidence_timeline": [],
    }


def recovery_status_view(recovery_status: Mapping[str, Any]) -> dict[str, Any]:
    """Present the independent recovery and integrity axes from the recovery API."""
    recovery = recovery_status.get("recovery_result")
    integrity = recovery_status.get("integrity_result")
    recovery = recovery if isinstance(recovery, Mapping) else {}
    integrity = integrity if isinstance(integrity, Mapping) else {}
    mismatch_paths: set[str] = set()
    mismatch_details_available = False
    for key in ("missing_paths", "unexpected_paths", "type_mismatches", "changed_paths"):
        paths = integrity.get(key) or []
        if isinstance(paths, (list, tuple)):
            mismatch_details_available = True
            mismatch_paths.update(str(path) for path in paths)
    integrity_status = (
        integrity.get("integrity_status")
        or recovery_status.get("integrity_status")
        or "NOT_CHECKED"
    )
    return {
        "recovery_status": recovery.get("recovery_status")
        or recovery_status.get("status")
        or "NOT_ATTEMPTED",
        "integrity_status": integrity_status,
        "mismatched_file_count": (
            len(mismatch_paths)
            if mismatch_details_available
            else 0 if integrity_status == "VERIFIED" else None
        ),
    }
