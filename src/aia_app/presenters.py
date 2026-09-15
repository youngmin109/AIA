"""Pure presentation mapping from Core result data to console views."""

from __future__ import annotations

from typing import Any, Mapping


def safe_event_views(
    actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    *,
    sensor_health: Mapping[str, str] | None = None,
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """Build a display-only timeline without raw targets or payload values.

    The console intentionally exposes categories and outcomes, while paths,
    commands, secrets, and full evidence payloads remain in the protected
    bundle and are never copied into this live view.
    """

    known_sensors = {
        "AGENT_HOOK",
        "FILESYSTEM_WATCHER",
        "PROCESS_RUNTIME",
        "RUNTIME",
        "MULTI_SENSOR",
    }
    evidence_sources_by_id = {
        str(item.get("evidence_id")): str(item.get("source"))
        for item in evidence_metadata
        if isinstance(item, Mapping)
        and item.get("evidence_id")
        and item.get("source") in known_sensors
    }

    def event_sensor(action: Mapping[str, Any]) -> str:
        explicit_sensor = action.get("sensor") or action.get("source")
        if explicit_sensor in known_sensors:
            return str(explicit_sensor)
        evidence_sources = {
            evidence_sources_by_id[evidence_id]
            for evidence_id in action.get("evidence_ids", ())
            if isinstance(evidence_id, str) and evidence_id in evidence_sources_by_id
        }
        if len(evidence_sources) == 1:
            return next(iter(evidence_sources))
        if len(evidence_sources) > 1:
            return "MULTI_SENSOR"
        # observation_stage describes when an action was observed, not which
        # sensor produced it.  Never infer Hook Sensor from PRE/POST_ACTION.
        return "RUNTIME"

    events: list[dict[str, Any]] = []
    for action in actions:
        operation = str(action.get("operation") or "ACTION")
        policy = action.get("policy_decision") or action.get("policy")
        enforcement = action.get("enforcement_action") or action.get("enforcement")
        enforcement_decision = action.get("enforcement_decision")
        execution = action.get("execution_result")
        execution_observed = bool(action.get("execution_observed"))
        target = action.get("target") if isinstance(action.get("target"), Mapping) else {}
        target_kind = str(target.get("target_kind") or "")
        target_label = "명령 실행" if operation == "EXECUTE" or target_kind == "COMMAND" else "파일·프로세스 행위"
        severity = "CRITICAL" if execution == "FAILED" else "WARNING" if policy in {"VIOLATION", "INDETERMINATE"} or enforcement not in {None, "NONE"} else "INFO"
        display_decision = (
            enforcement_decision
            if enforcement_decision not in {None, "NONE"}
            else enforcement
            if enforcement not in {None, "NONE"}
            else policy
            or "OBSERVED"
        )
        events.append(
            {
                "event_id": str(action.get("action_id") or f"action-{len(events) + 1}"),
                "category": "ENFORCEMENT" if display_decision in {"CONTAIN", "REFUSE", "BLOCKED", "TERMINATED"} else "POLICY",
                "summary": f"{operation} 행위 관찰",
                "target_label": target_label,
                "decision": display_decision,
                "execution_result": execution or "NOT_REPORTED",
                "execution_observed": execution_observed,
                "sensor": event_sensor(action),
                "severity": severity,
                "observed_at": action.get("observed_at"),
                "chain_action_id": action.get("action_id"),
                "incident_action_id": action.get("action_id") if severity != "INFO" else None,
            }
        )
    for sensor, status in (sensor_health or {}).items():
        events.append(
            {
                "event_id": f"sensor-{sensor}",
                "category": "SENSOR",
                "summary": f"{sensor} 센서 상태",
                "target_label": "센서 상태",
                "decision": status,
                "execution_result": "NOT_APPLICABLE",
                "sensor": sensor,
                "severity": "INFO" if status in {"HEALTHY", "STOPPED"} else "CRITICAL",
                "observed_at": None,
                "chain_action_id": None,
                "incident_action_id": None,
            }
        )
    return events[-50:]


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
    policy_decision = action.get("policy_decision") or action.get("policy")
    attribution = (
        action.get("attribution_grade")
        or action.get("attribution_class")
        or action.get("attribution")
    )
    enforcement = action.get("enforcement_action") or action.get("enforcement")
    operation_effect = action.get("operation_effect") or action.get("policy_effect")
    route = action.get("enforcement_route") or action.get("route")
    return {
        "action_id": action.get("action_id"),
        "attribution": attribution,
        "attribution_reason": action.get("attribution_reason"),
        "enforcement": enforcement,
        "enforcement_action": enforcement,
        "enforcement_decision": action.get("enforcement_decision"),
        "execution_result": action.get("execution_result"),
        "execution_observed": bool(action.get("execution_observed")),
        "evidence_ids": list(action.get("evidence_ids") or []),
        "matched_asset_types": list(action.get("matched_asset_types") or []),
        "matched_rule_ids": list(action.get("matched_rule_ids") or []),
        "observation_stage": action.get("observation_stage"),
        "observed_at": action.get("observed_at"),
        "operation": action.get("operation"),
        "policy": policy_decision,
        "policy_decision": policy_decision,
        "operation_effect": operation_effect,
        "policy_effect": operation_effect or policy_decision,
        "attribution_class": attribution,
        "route": route,
        "enforcement_route": route,
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
        "process_observed": 0,
        "process_exit_observed": 0,
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
        elif source == "PROCESS_RUNTIME" and record_type == "PROCESS_OBSERVED":
            summary["process_observed"] += 1
        elif source == "PROCESS_RUNTIME" and record_type == "PROCESS_EXIT_OBSERVED":
            summary["process_exit_observed"] += 1
        elif record_type == "SENSOR_HEALTH":
            summary["sensor_health_events"] += 1
    return summary


def evidence_chain_views(
    actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    *,
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    attribution_results: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    recovery: Mapping[str, Any] | None = None,
    integrity: Mapping[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Build a safe, display-only evidence chain for each observed action.

    This is deliberately a presenter contract.  It joins identifiers that
    already exist in the Core action/result records and the metadata-only
    Evidence reader.  It never evaluates policy, infers intent, or copies
    command text, paths, file contents, or Evidence payload values.
    """

    metadata_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence_metadata
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    attribution_support_by_action: dict[str, tuple[str, ...]] = {}
    for item in attribution_results:
        if not isinstance(item, Mapping) or not item.get("action_id"):
            continue
        attribution_support_by_action[str(item["action_id"])] = tuple(
            str(value)
            for value in item.get("supporting_evidence_ids") or ()
            if isinstance(value, str) and value
        )
    run_records_by_sensor: dict[str, list[Mapping[str, Any]]] = {
        sensor: []
        for sensor in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME")
    }
    for item in evidence_metadata:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        if source in run_records_by_sensor and item.get("record_type") != "SENSOR_HEALTH":
            run_records_by_sensor[source].append(item)

    def _run_status(value: Any, *, key: str) -> str:
        if isinstance(value, Mapping):
            value = value.get(key) or value.get("status")
        return str(value or "NOT_ATTEMPTED")

    recovery_status = _run_status(recovery, key="recovery_status")
    integrity_status = _run_status(integrity, key="integrity_status")

    chains: list[dict[str, Any]] = []
    bounded_actions = list(actions)[-limit:] if limit > 0 else []
    for raw_action in bounded_actions:
        if not isinstance(raw_action, Mapping):
            continue
        action = action_view(raw_action)
        direct_evidence_ids = [
            str(item)
            for item in action.get("evidence_ids", [])
            if isinstance(item, str) and item
        ]
        supporting_evidence_ids = attribution_support_by_action.get(
            str(action.get("action_id")), ()
        )
        evidence_ids = list(dict.fromkeys((*direct_evidence_ids, *supporting_evidence_ids)))
        linked_records = [metadata_by_id[item] for item in evidence_ids if item in metadata_by_id]
        missing_count = len(evidence_ids) - len(linked_records)
        if not evidence_ids:
            evidence_link_status = "NOT_REPORTED"
        elif missing_count:
            evidence_link_status = "PARTIAL"
        else:
            evidence_link_status = "LINKED"

        sources = list(dict.fromkeys(
            str(item.get("source"))
            for item in linked_records
            if item.get("source")
        ))
        record_types = list(dict.fromkeys(
            str(item.get("record_type"))
            for item in linked_records
            if item.get("record_type")
        ))
        sensor_links = []
        for sensor in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME"):
            sensor_records = [
                item for item in linked_records if item.get("source") == sensor
            ]
            run_records = run_records_by_sensor[sensor]
            sensor_status = (
                "LINKED"
                if sensor_records
                else "RUN_OBSERVED"
                if run_records
                else "NOT_OBSERVED"
            )
            sensor_links.append(
                {
                    "sensor": sensor,
                    "status": sensor_status,
                    "evidence_count": len(sensor_records),
                    "record_types": list(dict.fromkeys(
                        str(item.get("record_type"))
                        for item in sensor_records
                        if item.get("record_type")
                    )),
                    "run_evidence_count": len(run_records),
                    "run_record_types": list(dict.fromkeys(
                        str(item.get("record_type"))
                        for item in run_records
                        if item.get("record_type")
                    )),
                }
            )
        observed_at = action.get("observed_at") or max(
            (
                str(item.get("captured_at"))
                for item in linked_records
                if item.get("captured_at")
            ),
            default=None,
        )
        operation = str(action.get("operation") or "ACTION")
        target = action.get("target") if isinstance(action.get("target"), Mapping) else {}
        target_label = (
            "명령 실행"
            if operation == "EXECUTE" or target.get("target_kind") == "COMMAND"
            else "파일·프로세스 행위"
        )

        policy_decision = action.get("policy_decision") or action.get("policy")
        attribution = action.get("attribution_class") or action.get("attribution")
        enforcement_action = action.get("enforcement_action") or action.get("enforcement")
        enforcement_decision = action.get("enforcement_decision")
        execution_result = action.get("execution_result") or "NOT_REPORTED"
        enforcement_status = enforcement_action
        if enforcement_status in {None, "NONE"}:
            enforcement_status = enforcement_decision or "NOT_REPORTED"

        stages = [
            {
                "stage": "RAW_EVIDENCE",
                "label": "원시 증거",
                "status": evidence_link_status,
                "link_status": evidence_link_status,
                "evidence_ids": evidence_ids,
                "evidence_count": len(evidence_ids),
                "linked_evidence_count": len(linked_records),
                "sources": sources,
                "record_types": record_types,
                "sensor_links": sensor_links,
                "observed_at": observed_at,
            },
            {
                "stage": "CANONICAL_ACTION",
                "label": "표준 행위",
                "status": "LINKED" if action.get("action_id") and operation else "NOT_REPORTED",
                "operation": operation,
                "target_label": target_label,
                "action_id": action.get("action_id"),
            },
            {
                "stage": "POLICY",
                "label": "정책 판정",
                "status": str(policy_decision or "NOT_REPORTED"),
                "decision": policy_decision or "NOT_REPORTED",
                "matched_rule_ids": list(action.get("matched_rule_ids") or []),
                "asset_types": list(action.get("matched_asset_types") or []),
            },
            {
                "stage": "ATTRIBUTION",
                "label": "행위 귀속",
                "status": str(attribution or "NOT_REPORTED"),
                "grade": attribution or "NOT_REPORTED",
            },
            {
                "stage": "ENFORCEMENT",
                "label": "집행",
                "status": str(enforcement_status),
                "decision": enforcement_decision or "NOT_REPORTED",
                "action": enforcement_action or "NONE",
                "execution_result": execution_result,
                "route": action.get("enforcement_route") or action.get("route"),
                "execution_observed": bool(action.get("execution_observed")),
            },
            {
                "stage": "RECOVERY",
                "label": "복구",
                "status": recovery_status,
                "scope": "RUN",
                "link_status": "RUN_LEVEL",
                "related_id": action.get("related_recovery_id"),
            },
            {
                "stage": "INTEGRITY",
                "label": "무결성",
                "status": integrity_status,
                "scope": "RUN",
                "link_status": "RUN_LEVEL",
            },
        ]
        chains.append(
            {
                "chain_id": str(action.get("action_id") or f"chain-{len(chains) + 1}"),
                "action_id": action.get("action_id"),
                "operation": operation,
                "target_label": target_label,
                "observed_at": observed_at,
                "evidence_link_status": evidence_link_status,
                "evidence_count": len(evidence_ids),
                "linked_evidence_count": len(linked_records),
                "sensor_links": sensor_links,
                "stages": stages,
            }
        )
    return chains


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
        evidence_ids = tuple(
            dict.fromkeys(
                tuple(
                    value
                    for value in action.get("evidence_ids") or ()
                    if isinstance(value, str) and value
                )
                + attribution_support_by_action.get(action_id, ())
            )
        )
        for evidence_id in evidence_ids:
            if isinstance(evidence_id, str) and evidence_id:
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
    for item in evidence_metadata:
        if not isinstance(item, Mapping) or not item.get("evidence_id"):
            continue
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
    def _line_number(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    records.sort(key=lambda item: (str(item.get("captured_at") or ""), _line_number(item.get("line"))))
    return records[-max(0, limit) :] if limit > 0 else []


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
        "events": safe_event_views(actions),
        "evidence_chains": evidence_chain_views(
            actions,
            attribution_results=result.get("attribution_results") or (),
            recovery=result.get("recovery_result"),
            integrity=result.get("integrity_result"),
        ),
        "evidence_timeline": [],
    }
