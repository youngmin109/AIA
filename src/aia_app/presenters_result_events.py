"""Presentation mappings for result events, incidents, and summaries."""

from __future__ import annotations

from typing import Any, Mapping

from .presenters_evidence_chain import safe_target, safe_tool_name

_INCIDENT_OPERATION_LABELS = {
    "READ": "파일 읽기",
    "CREATE": "파일 생성",
    "MODIFY": "파일 수정",
    "DELETE": "파일 삭제",
    "MOVE": "파일 이동",
    "RENAME": "파일 이름 변경",
    "EXECUTE": "명령 실행",
    "RECOVERY": "복구 작업",
    "INTEGRITY": "무결성 검증",
    "SENSOR": "센서 상태",
}
_INCIDENT_DECISION_LABELS = {
    "VIOLATION": "정책 위반",
    "INDETERMINATE": "판정 불가",
    "COMPLIANT": "정상·허용",
    "OBSERVED": "관찰됨",
}
_INCIDENT_RESULT_LABELS = {
    "RESTORED": "복원 완료",
    "RECOVERY_UNAVAILABLE": "복원 불가",
    "FAILED": "실행 실패",
}
_INCIDENT_REASON_LABELS = {
    "DIRECT_TRUSTED_HOOK": "신뢰된 직접 Hook Evidence가 Agent Tool 사용을 식별했습니다.",
    "VERIFIED_AGENT_PROCESS": "검증된 Agent Process Tree에서 프로세스가 관찰되었습니다.",
    "PROCESS_WINDOW_ASSOCIATION": "검증된 Agent Process Tree의 관찰 시간과 파일 행위가 겹칩니다.",
    "TURN_WINDOW_ASSOCIATION": "행위 시각이 명시된 Agent Turn 구간과 겹칩니다.",
    "HOOK_INGRESS_UNVERIFIED": "Hook 유입 검증이 완료되지 않았습니다.",
    "SESSION_MISMATCH": "행위와 AIA Session이 일치하지 않습니다.",
    "NATIVE_SESSION_MISMATCH": "Hook의 Native Session ID가 예상 값과 일치하지 않습니다.",
    "TOOL_IDENTIFIER_MISSING": "신뢰된 직접 Hook에 Tool 식별자가 없습니다.",
    "CONFLICTING_TOOL_IDENTIFIER": "동일 Tool 식별자에 서로 다른 Hook 정보가 있습니다.",
    "PROCESS_IDENTITY_MISMATCH": "프로세스 식별자를 보호 대상 Agent Root와 검증할 수 없습니다.",
    "COMPETING_CANDIDATE": "동일 행위와 겹치는 다른 후보가 확인되었습니다.",
    "AMBIGUOUS_TURN_WINDOW": "둘 이상의 Agent Turn 구간이 행위 시각과 겹칩니다.",
    "INSUFFICIENT_EVIDENCE": "신뢰할 수 있는 직접 Hook·Process·Turn Evidence가 부족합니다.",
    "UNSUPPORTED_PROVENANCE": "지원하지 않는 실행 출처입니다.",
    "MALFORMED_LINEAGE": "Hook Evidence 연결 관계가 예상 형식과 다릅니다.",
    "TURN_IDENTIFIER_MISMATCH": "Turn 식별자가 예상 값과 일치하지 않습니다.",
    "Trusted direct Hook Evidence identifies the Agent Tool Use": "신뢰된 직접 Hook Evidence가 Agent Tool 사용을 식별했습니다.",
    "Process Action does not reference PROCESS_OBSERVED Raw Evidence": "프로세스 행위가 PROCESS_OBSERVED Raw Evidence를 참조하지 않습니다.",
    "Process Action has no valid observed lifetime": "프로세스 행위의 유효한 관찰 수명이 없습니다.",
    "Process identity cannot be verified against the protected Agent Root": "프로세스 식별자를 보호 대상 Agent Root와 검증할 수 없습니다.",
    "Process was observed in the verified Agent Process Tree": "검증된 Agent Process Tree에서 프로세스가 관찰되었습니다.",
    "Filesystem Action overlaps a verified Agent Process Tree observation window": "검증된 Agent Process Tree의 관찰 시간과 파일 행위가 겹칩니다.",
    "Action timestamp overlaps one explicit Agent Turn Window": "행위 시각이 명시된 Agent Turn 구간과 겹칩니다.",
    "hook and process evidence": "Hook과 Process Evidence가 함께 확인되었습니다.",
}
_SAFE_EVENT_OPERATION_LABELS = {
    "READ": "읽기",
    "CREATE": "생성",
    "MODIFY": "수정",
    "DELETE": "삭제",
    "MOVE": "이동",
    "RENAME": "이름 변경",
    "EXECUTE": "명령 실행",
}


def _incident_reason_label(value: Any, fallback: Any = None) -> str:
    """Return a Korean reason while retaining the original value separately."""

    raw = value if value is not None and value != "" else fallback
    if raw is None or raw == "":
        return "추가 사유 없음"
    decision = _INCIDENT_DECISION_LABELS.get(str(raw))
    if decision:
        return decision
    return _INCIDENT_REASON_LABELS.get(str(raw), str(raw))


def _incident_summary(action: Mapping[str, Any]) -> str:
    """Build a safe, localized incident label from normalized result fields."""

    operation = _INCIDENT_OPERATION_LABELS.get(
        str(action.get("operation") or ""), "보호 대상 행위"
    )
    policy = _INCIDENT_DECISION_LABELS.get(str(action.get("policy_decision") or ""))
    if policy:
        return f"{operation} 요청 · {policy}"

    recovery_data = action.get("recovery")
    integrity_data = action.get("integrity")
    recovery = action.get("recovery_status") or (
        recovery_data.get("recovery_status")
        if isinstance(recovery_data, Mapping)
        else None
    )
    integrity = action.get("integrity_status") or (
        integrity_data.get("integrity_status")
        if isinstance(integrity_data, Mapping)
        else None
    )
    result = action.get("execution_result")
    if operation == "복구 작업" and recovery:
        return f"{operation} · {_INCIDENT_RESULT_LABELS.get(str(recovery), '확인 필요')}"
    if operation == "무결성 검증" and integrity:
        return f"{operation} · {_INCIDENT_RESULT_LABELS.get(str(integrity), '확인 필요')}"
    if operation == "센서 상태" and result == "FAILED":
        return f"{operation} · 실행 실패"
    if result == "FAILED":
        return f"{operation} 요청 · 실행 실패"
    return f"{operation} 요청 · 확인 필요"


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
        sensor = event_sensor(action)
        tool_name = safe_tool_name(action.get("tool_name") or action.get("tool"))
        target_label = "명령 실행" if operation == "EXECUTE" or target_kind == "COMMAND" else "파일·프로세스 행위"
        operation_label = _SAFE_EVENT_OPERATION_LABELS.get(operation, "보호 대상 행위")
        event_origin = "RUNTIME_ACTION"
        origin_label = "행위 기록"
        display_summary = f"{operation_label} 행위 관찰"
        display_target_label = target_label
        if target_kind == "PROCESS":
            event_origin = "PROCESS_OBSERVATION"
            origin_label = "프로세스 관찰"
            display_summary = (
                "프로세스 실행 관찰"
                if operation == "EXECUTE"
                else f"프로세스 {operation_label} 관찰"
            )
            display_target_label = "프로세스"
        elif sensor == "FILESYSTEM_WATCHER" and target_kind == "FILE":
            event_origin = "FILESYSTEM_OBSERVATION"
            origin_label = "파일 관찰"
            display_summary = f"파일 {operation_label} 관찰"
            display_target_label = "파일 변화"
        elif sensor == "AGENT_HOOK":
            event_origin = "HOOK_REQUEST"
            origin_label = "Hook 요청"
            display_summary = f"{operation_label} 요청"
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
                "display_summary": display_summary,
                "display_target_label": display_target_label,
                "event_origin": event_origin,
                "origin_label": origin_label,
                "tool_name": tool_name,
                "decision": display_decision,
                # Process and filesystem sensors report observed effects. They
                # do not perform a policy evaluation, so do not let a
                # transport-level CONTINUE value look like a policy result in
                # the user-facing timeline.
                "display_decision": (
                    "OBSERVED"
                    if event_origin
                    in {"PROCESS_OBSERVATION", "FILESYSTEM_OBSERVATION"}
                    else display_decision
                ),
                "execution_result": execution or "NOT_REPORTED",
                "execution_observed": execution_observed,
                "sensor": sensor,
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
        "tool_name": safe_tool_name(action.get("tool_name") or action.get("tool")),
        "policy": policy,
        "policy_decision": policy,
        "operation_effect": action.get("operation_effect"),
        "policy_effect": action.get("operation_effect") or policy,
        "reason": _incident_reason_label(action.get("attribution_reason"), policy),
        "proof": "정규화된 행위 정보와 Evidence ID를 표시합니다. 원본 payload 값은 보호된 Bundle에 보관됩니다.",
        "summary": _incident_summary(action),
        "target": safe_target(action.get("target")),
        "observed_at": action.get("observed_at"),
        "recovery_status": recovery.get("recovery_status"),
        "integrity_status": integrity.get("integrity_status"),
        "attribution_reason_label": _incident_reason_label(action.get("attribution_reason"), policy),
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
                "summary": f"복구 작업 · {_INCIDENT_RESULT_LABELS.get(recovery_status, '확인 필요')}",
                "proof": "검증된 Result Bundle에 기록된 복구 결과를 표시합니다.",
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
                "summary": "무결성 검증 · 실패",
                "proof": "검증된 Result Bundle에 기록된 무결성 결과를 표시합니다.",
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
                    "summary": "센서 상태 · 실행 실패",
                    "proof": "최종 Core Result Bundle에 기록된 센서 상태를 표시합니다.",
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


