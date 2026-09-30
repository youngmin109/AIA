"""Presentation mappings for the result Evidence Chain."""

from __future__ import annotations

from typing import Any, Mapping

_SAFE_TOOL_NAMES = frozenset({"Bash", "apply_patch", "Edit", "Write"})


def safe_tool_name(value: Any) -> str | None:
    """Return a supported tool label without exposing arbitrary Hook input."""

    return str(value) if isinstance(value, str) and value in _SAFE_TOOL_NAMES else None


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
        "tool_name": safe_tool_name(action.get("tool_name") or action.get("tool")),
    }


def _evidence_chain_run_status(value: Any, *, key: str) -> str:
    if isinstance(value, Mapping):
        value = value.get(key) or value.get("status")
    return str(value or "NOT_ATTEMPTED")


def _evidence_chain_indexes(
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    attribution_results: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, tuple[str, ...]],
    dict[str, list[Mapping[str, Any]]],
]:
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
    return metadata_by_id, attribution_support_by_action, run_records_by_sensor


def _evidence_chain_sensor_links(
    linked_records: list[Mapping[str, Any]],
    run_records_by_sensor: Mapping[str, list[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    sensor_links = []
    for sensor in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME"):
        sensor_records = [item for item in linked_records if item.get("source") == sensor]
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
    return sensor_links


def _evidence_chain_stages(
    action: Mapping[str, Any],
    *,
    operation: str,
    target_label: str,
    evidence_link_status: str,
    evidence_ids: list[str],
    linked_records: list[Mapping[str, Any]],
    sensor_links: list[dict[str, Any]],
    observed_at: Any,
    recovery_status: str,
    integrity_status: str,
) -> list[dict[str, Any]]:
    policy_decision = action.get("policy_decision") or action.get("policy")
    attribution = action.get("attribution_class") or action.get("attribution")
    enforcement_action = action.get("enforcement_action") or action.get("enforcement")
    enforcement_decision = action.get("enforcement_decision")
    execution_result = action.get("execution_result") or "NOT_REPORTED"
    enforcement_status = enforcement_action
    if enforcement_status in {None, "NONE"}:
        enforcement_status = enforcement_decision or "NOT_REPORTED"
    sources = list(dict.fromkeys(
        str(item.get("source")) for item in linked_records if item.get("source")
    ))
    record_types = list(dict.fromkeys(
        str(item.get("record_type")) for item in linked_records if item.get("record_type")
    ))
    return [
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


def _evidence_chain_action_view(
    raw_action: Mapping[str, Any],
    *,
    chain_number: int,
    metadata_by_id: Mapping[str, Mapping[str, Any]],
    attribution_support_by_action: Mapping[str, tuple[str, ...]],
    run_records_by_sensor: Mapping[str, list[Mapping[str, Any]]],
    recovery_status: str,
    integrity_status: str,
) -> dict[str, Any]:
    action = action_view(raw_action)
    direct_evidence_ids = [
        str(item) for item in action.get("evidence_ids", [])
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
    sensor_links = _evidence_chain_sensor_links(linked_records, run_records_by_sensor)
    observed_at = action.get("observed_at") or max(
        (str(item.get("captured_at")) for item in linked_records if item.get("captured_at")),
        default=None,
    )
    operation = str(action.get("operation") or "ACTION")
    target = action.get("target") if isinstance(action.get("target"), Mapping) else {}
    target_label = (
        "명령 실행"
        if operation == "EXECUTE" or target.get("target_kind") == "COMMAND"
        else "파일·프로세스 행위"
    )
    stages = _evidence_chain_stages(
        action,
        operation=operation,
        target_label=target_label,
        evidence_link_status=evidence_link_status,
        evidence_ids=evidence_ids,
        linked_records=linked_records,
        sensor_links=sensor_links,
        observed_at=observed_at,
        recovery_status=recovery_status,
        integrity_status=integrity_status,
    )
    return {
        "chain_id": str(action.get("action_id") or f"chain-{chain_number}"),
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


def evidence_chain_views(
    actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    *,
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    attribution_results: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    recovery: Mapping[str, Any] | None = None,
    integrity: Mapping[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Build display-only chains from existing action and evidence identifiers.

    This presenter never evaluates policy, infers intent, or copies raw
    command text, paths, file contents, or evidence payload values.
    """
    metadata_by_id, attribution_support_by_action, run_records_by_sensor = (
        _evidence_chain_indexes(evidence_metadata, attribution_results)
    )
    recovery_status = _evidence_chain_run_status(recovery, key="recovery_status")
    integrity_status = _evidence_chain_run_status(integrity, key="integrity_status")
    bounded_actions = list(actions)[-limit:] if limit > 0 else []
    chains = []
    for raw_action in bounded_actions:
        if not isinstance(raw_action, Mapping):
            continue
        chains.append(
            _evidence_chain_action_view(
                raw_action,
                chain_number=len(chains) + 1,
                metadata_by_id=metadata_by_id,
                attribution_support_by_action=attribution_support_by_action,
                run_records_by_sensor=run_records_by_sensor,
                recovery_status=recovery_status,
                integrity_status=integrity_status,
            )
        )
    return chains


def result_action_chain_views(
    actions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    *,
    evidence_metadata: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    attribution_results: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] = (),
    recovery: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the result screen's ordered, action-linked evidence chains."""
    metadata_by_id, attribution_support_by_action, _ = _evidence_chain_indexes(
        evidence_metadata, attribution_results
    )
    recovery_status = _evidence_chain_run_status(recovery, key="recovery_status")
    chains = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_id = str(action.get("action_id") or "")
        evidence_ids = {
            str(value)
            for value in action.get("evidence_ids") or ()
            if isinstance(value, str) and value
        }
        evidence_ids.update(attribution_support_by_action.get(action_id, ()))
        linked_records = [metadata_by_id[value] for value in evidence_ids if value in metadata_by_id]

        def observed_record(source: str, record_type: str) -> bool:
            return any(
                item.get("source") == source and item.get("record_type") == record_type
                for item in linked_records
            )

        tool_request_observed = observed_record("AGENT_HOOK", "PRETOOL_REQUEST")
        process_observed = observed_record("PROCESS_RUNTIME", "PROCESS_OBSERVED")
        file_change_observed = observed_record("FILESYSTEM_WATCHER", "FILESYSTEM_EVENT")
        tool_name = safe_tool_name(action.get("tool_name") or action.get("tool"))
        policy = action.get("policy_decision") or action.get("policy")
        enforcement = action.get("enforcement_action") or action.get("enforcement")
        enforcement_decision = action.get("enforcement_decision")
        stages = [
            {
                "stage": "TOOL_REQUEST",
                "label": "Tool request",
                "status": "OBSERVED" if tool_request_observed else "NOT_OBSERVED",
                "value": (tool_name or "observed") if tool_request_observed else "not observed",
            },
            {
                "stage": "PROCESS",
                "label": "Process",
                "status": "OBSERVED" if process_observed else "NOT_OBSERVED",
                "value": "observed" if process_observed else "not observed",
            },
            {
                "stage": "FILE_CHANGE",
                "label": "File change",
                "status": "OBSERVED" if file_change_observed else "NOT_OBSERVED",
                "value": "observed" if file_change_observed else "not observed",
            },
            {
                "stage": "POLICY",
                "label": "Policy decision",
                "status": str(policy) if policy else "NOT_OBSERVED",
                "value": str(policy) if policy else "not observed",
            },
            {
                "stage": "ENFORCEMENT",
                "label": "Enforcement",
                "status": str(enforcement or enforcement_decision) if enforcement or enforcement_decision else "NOT_OBSERVED",
                "value": str(enforcement or enforcement_decision) if enforcement or enforcement_decision else "not observed",
            },
            {
                "stage": "RECOVERY",
                "label": "Recovery (run level)",
                "status": recovery_status if recovery_status != "NOT_ATTEMPTED" else "NOT_OBSERVED",
                "value": recovery_status if recovery_status != "NOT_ATTEMPTED" else "not observed",
            },
        ]
        chains.append({"action_id": action.get("action_id"), "stages": stages})
    return chains

