"""Pure presentation mapping from Core result data to console views."""

from __future__ import annotations

from typing import Any, Mapping


def safe_target(target: Mapping[str, Any] | None) -> dict[str, Any]:
    target = target or {}
    allowed = ("canonical_path", "destination_path", "source_path", "target_kind", "command_fingerprint")
    safe = {key: target[key] for key in allowed if target.get(key) is not None}
    safe["display"] = (
        safe.get("canonical_path")
        or safe.get("source_path")
        or safe.get("destination_path")
        or safe.get("command_fingerprint")
        or "—"
    )
    return safe


def action_view(action: Mapping[str, Any]) -> dict[str, Any]:
    target = safe_target(action.get("target"))
    return {
        "action_id": action.get("action_id"),
        "attribution": action.get("attribution_grade"),
        "attribution_reason": action.get("attribution_reason"),
        "enforcement": action.get("enforcement_action"),
        "enforcement_action": action.get("enforcement_action"),
        "enforcement_decision": action.get("enforcement_decision"),
        "execution_result": action.get("execution_result"),
        "evidence_ids": list(action.get("evidence_ids") or []),
        "matched_asset_types": list(action.get("matched_asset_types") or []),
        "matched_rule_ids": list(action.get("matched_rule_ids") or []),
        "observation_stage": action.get("observation_stage"),
        "operation": action.get("operation"),
        "policy": action.get("policy_decision"),
        "policy_decision": action.get("policy_decision"),
        "operation_effect": action.get("operation_effect"),
        "policy_effect": action.get("operation_effect") or action.get("policy_decision"),
        "attribution_class": action.get("attribution_grade"),
        "route": action.get("enforcement_route") or action.get("route"),
        "enforcement_route": action.get("enforcement_route") or action.get("route"),
        "target": target,
    }


def incident_view(action: Mapping[str, Any]) -> dict[str, Any] | None:
    policy = action.get("policy_decision")
    enforcement = action.get("enforcement_action")
    execution = action.get("execution_result")
    if not (
        policy in {"VIOLATION", "INDETERMINATE"}
        or enforcement not in {None, "NONE"}
        or execution == "FAILED"
    ):
        return None
    recovery = action.get("recovery") or {}
    integrity = action.get("integrity") or {}
    return {
        "action_id": action.get("action_id"),
        "attribution": action.get("attribution_grade"),
        "attribution_class": action.get("attribution_grade"),
        "attribution_reason": action.get("attribution_reason"),
        "enforcement": enforcement,
        "enforcement_action": enforcement,
        "enforcement_decision": action.get("enforcement_decision"),
        "enforcement_route": action.get("enforcement_route") or action.get("route"),
        "execution_result": execution,
        "evidence_ids": list(action.get("evidence_ids") or []),
        "matched_asset_types": list(action.get("matched_asset_types") or []),
        "matched_rule_ids": list(action.get("matched_rule_ids") or []),
        "operation": action.get("operation"),
        "policy": policy,
        "policy_decision": policy,
        "operation_effect": action.get("operation_effect"),
        "policy_effect": action.get("operation_effect") or policy,
        "reason": action.get("attribution_reason") or policy,
        "proof": "AIA exposes normalized action metadata and evidence identifiers; raw payload values remain in the protected bundle.",
        "summary": f"{action.get('operation') or 'Action'} was classified as {policy or 'UNKNOWN'}.",
        "target": safe_target(action.get("target")),
        "observed_at": action.get("observed_at"),
        "recovery_status": recovery.get("recovery_status"),
        "integrity_status": integrity.get("integrity_status"),
    }


def incident_views_for_result(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build presentation incidents without changing Core result semantics."""
    incidents = [
        item
        for item in (incident_view(action) for action in result.get("action_outcomes", []))
        if item
    ]
    recovery = result.get("recovery_result") or {}
    integrity = result.get("integrity_result") or {}
    recovery_status = recovery.get("recovery_status") or "NOT_ATTEMPTED"
    integrity_status = integrity.get("integrity_status") or "NOT_ATTEMPTED"
    for item in incidents:
        item["recovery_status"] = recovery_status
        item["integrity_status"] = integrity_status
    if recovery_status in {"FAILED", "RECOVERY_UNAVAILABLE", "REFUSED"}:
        incidents.append(
            {
                "action_id": "recovery",
                "operation": "RECOVERY",
                "policy_effect": None,
                "attribution_class": None,
                "enforcement_action": None,
                "execution_result": None,
                "enforcement_decision": None,
                "enforcement_route": None,
                "target": {"display": "Workspace"},
                "evidence_ids": [],
                "matched_rule_ids": [],
                "matched_asset_types": [],
                "reason": recovery.get("reason") or recovery_status,
                "summary": f"Recovery is {recovery_status}.",
                "proof": "The Recovery result is displayed from the verified Result Bundle.",
                "recovery_status": recovery_status,
                "integrity_status": integrity_status,
            }
        )
    if integrity_status == "FAILED":
        incidents.append(
            {
                "action_id": "integrity",
                "operation": "INTEGRITY",
                "policy_effect": None,
                "attribution_class": None,
                "enforcement_action": None,
                "execution_result": None,
                "enforcement_decision": None,
                "enforcement_route": None,
                "target": {"display": "Workspace"},
                "evidence_ids": [],
                "matched_rule_ids": [],
                "matched_asset_types": [],
                "reason": integrity.get("reason") or integrity_status,
                "summary": "Post-recovery integrity verification failed.",
                "proof": "The Integrity result is displayed from the verified Result Bundle.",
                "recovery_status": recovery_status,
                "integrity_status": integrity_status,
            }
        )
    for sensor in result.get("sensor_summary", []):
        if sensor.get("runtime_health_before_stop") == "FAILED":
            incidents.append(
                {
                    "action_id": f"sensor-{sensor.get('sensor', 'unknown')}",
                    "operation": "SENSOR",
                    "policy_effect": None,
                    "attribution_class": None,
                    "enforcement_action": None,
                    "execution_result": "FAILED",
                    "enforcement_decision": None,
                    "enforcement_route": None,
                    "target": {"display": sensor.get("sensor", "unknown")},
                    "evidence_ids": [],
                    "matched_rule_ids": [],
                    "matched_asset_types": [],
                    "reason": sensor.get("reason") or "SENSOR_RUNTIME_FAILED",
                    "summary": f"Sensor {sensor.get('sensor', 'unknown')} reported FAILED.",
                    "proof": "Sensor health is displayed from the finalized Core Result Bundle.",
                    "recovery_status": recovery_status,
                    "integrity_status": integrity_status,
                }
            )
    return incidents


def action_summary(result: Mapping[str, Any]) -> dict[str, int]:
    """Aggregate authoritative action outcomes for a human-readable result view."""

    actions = [
        item
        for item in (result.get("action_outcomes") or [])
        if isinstance(item, Mapping)
    ]

    def count(field: str, value: str) -> int:
        return sum(1 for item in actions if item.get(field) == value)

    return {
        "total": len(actions),
        "compliant": count("policy_decision", "COMPLIANT"),
        "audit": count("operation_effect", "AUDIT"),
        "violation": count("policy_decision", "VIOLATION"),
        "indeterminate": count("policy_decision", "INDETERMINATE"),
        "contain": count("enforcement_decision", "CONTAIN"),
        "blocked": count("enforcement_action", "BLOCKED"),
        "terminated": count("enforcement_action", "TERMINATED"),
        "execution_succeeded": count("execution_result", "SUCCEEDED"),
        "execution_failed": count("execution_result", "FAILED"),
        "execution_not_attempted": count("execution_result", "NOT_ATTEMPTED"),
    }


def evidence_summary(evidence: Any) -> dict[str, int | bool]:
    """Count bounded Evidence metadata without exposing payload values."""

    summary: dict[str, int | bool] = {
        "available": False,
        "filesystem_events": 0,
        "pretool_events": 0,
        "posttool_events": 0,
        "sensor_health_events": 0,
    }
    if not isinstance(evidence, (list, tuple)):
        return summary
    summary["available"] = True
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        record_type = item.get("record_type")
        if source == "FILESYSTEM_WATCHER" and record_type == "FILESYSTEM_EVENT":
            summary["filesystem_events"] += 1
        elif source == "AGENT_HOOK" and record_type == "PRETOOL_REQUEST":
            summary["pretool_events"] += 1
        elif source == "AGENT_HOOK" and record_type == "POSTTOOL_OBSERVED":
            summary["posttool_events"] += 1
        elif record_type == "SENSOR_HEALTH":
            summary["sensor_health_events"] += 1
    return summary


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
    limitations = list(result.get("limitations") or [])
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
    recovery_summary = {
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
    integrity_summary = {
        "status": integrity.get("integrity_status") or integrity.get("status") or "NOT_ATTEMPTED",
        "reason": integrity.get("reason"),
        "expected_entries": int(integrity.get("expected_entry_count") or 0),
        "actual_entries": int(integrity.get("actual_entry_count") or 0),
        "missing_paths": len(integrity.get("missing_paths") or []),
        "unexpected_paths": len(integrity.get("unexpected_paths") or []),
        "changed_paths": len(integrity.get("changed_paths") or []),
        "verification_errors": len(integrity.get("verification_errors") or []),
    }
    return {
        "action_summary": action_summary(result),
        "evidence_summary": result.get("evidence_summary") or evidence_summary(()),
        "agent": result.get("agent"),
        "attribution_results": list(result.get("attribution_results") or []),
        "bundle_status": bundle_status,
        "codex_block_confirmation": codex_block_confirmation,
        "codex_block_confirmation_reason": output_observation.get("reason"),
        "execution_policy_status": execution_policy_status,
        "requested_sandbox": requested_sandbox,
        "requested_approval_policy": requested_approval_policy,
        "effective_sandbox": effective_sandbox,
        "effective_approval_policy": effective_approval_policy,
        "ended_at": result.get("ended_at"),
        "enforcement_results": list(result.get("enforcement_results") or []),
        "incidents": incidents,
        "integrity": result.get("integrity_result"),
        "user_abort_termination": result.get("user_abort_termination_result"),
        "protection_failure_termination": result.get(
            "protection_failure_termination_result"
        ),
        "limitations": limitations,
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
    }
