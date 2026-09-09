"""Deterministic Korean human-readable Security Report rendering."""

from __future__ import annotations

import re
from typing import Any

from .result import SessionResult


_SECRET_PATTERN = re.compile(
    r"(?i)(token|password|api[_-]?key|secret|authorization|bearer)\s*[:=]\s*[^\s,;]+"
)


def redact_text(value: str | None) -> str:
    if value is None:
        return ""
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<REDACTED>", str(value))


def _state(value: Any) -> str:
    return getattr(value, "value", str(value))


class ReportGenerator:
    """Render only existing Result facts; never creates security decisions."""

    def render(self, result: SessionResult) -> str:
        headline = self._headline(result)
        lines = [
            "# AIA Security Report",
            "",
            f"> {headline}",
            "",
            "## 실행 정보",
            f"- Session ID: `{result.aia_session_id}`",
            f"- Agent: `{redact_text(result.agent)}`",
            f"- Workspace: `{result.workspace}`",
            f"- Mode: `{_state(result.mode)}`",
            f"- Created: `{result.created_at.isoformat()}`",
            f"- Started: `{result.started_at.isoformat() if result.started_at else 'N/A'}`",
            f"- Ended: `{result.ended_at.isoformat()}`",
            "",
            "## 최종 상태",
            f"- Session: `{_state(result.session_status)}`",
            f"- End Reason: `{_state(result.session_end_reason)}`",
            f"- Review Required: `{str(result.review_required).lower()}`",
            "",
            "## 무슨 일이 발생했는가",
            self._event_summary(result),
            "",
            "## 왜 이런 판정이 나왔는가",
            self._decision_summary(result),
            "",
            "## AIA가 수행한 조치",
            self._action_summary(result),
            "",
            "## Policy",
            self._policy_section(result),
            "",
            "## Attribution",
            self._attribution_section(result),
            "",
            "## Enforcement",
            self._enforcement_section(result),
            "",
            "## Recovery",
            self._mapping_section(result.recovery_result),
            "",
            "## Integrity",
            self._mapping_section(result.integrity_result),
            "",
            "## Sensor 상태",
            self._sensor_section(result),
            "",
            "## 주요 Action / Incident",
            self._action_section(result),
            "",
            "## Evidence",
            self._evidence_section(result),
            "",
            "## Limitation",
            self._limitations_section(result),
            "",
        ]
        return "\n".join(lines)

    def _headline(self, result: SessionResult) -> str:
        policy_values = {item.get("policy_decision") for item in result.policy_evaluations}
        enforcement_values = {item.get("enforcement_decision") for item in result.enforcement_results}
        actions = {item.enforcement_action for item in result.action_outcomes}
        if "INDETERMINATE" in policy_values:
            return "판정에 필요한 증거가 부족해 사용자 검토가 필요합니다."
        if "BLOCKED" in actions:
            return "보안 정책 위반이 실행 전에 차단되었습니다."
        if "PROCESS" in {item.attribution_grade for item in result.action_outcomes} and "REFUSE" in enforcement_values:
            return "정책 위반은 확인됐지만 자동 종료에 필요한 귀속 근거가 부족해 통제를 수행하지 않았습니다."
        recovery = result.recovery_result or {}
        integrity = result.integrity_result or {}
        if (
            result.session_end_reason == "SECURITY_CONTAINMENT"
            and recovery.get("recovery_status") == "RESTORED"
            and integrity.get("integrity_status") == "VERIFIED"
        ):
            return "Agent 실행을 중단하고 Workspace를 검증 복구했습니다."
        if recovery.get("recovery_status") == "RECOVERY_UNAVAILABLE":
            return "Agent containment는 성공했지만 신뢰 가능한 Checkpoint가 없어 복구할 수 없었습니다."
        if recovery.get("recovery_status") == "RESTORED" and integrity.get("integrity_status") == "FAILED":
            return "복원 실행은 완료됐지만 최종 무결성 검증에 실패했습니다."
        if result.session_status == "FAILED":
            return "AIA 보호 체계가 정상적으로 실행을 완료하지 못했습니다."
        return "보호 실행이 정상 종료되었습니다."

    def _event_summary(self, result: SessionResult) -> str:
        if not result.action_outcomes:
            return "- 기록된 Canonical Action이 없습니다."
        return "\n".join(
            f"- `{item.operation}` Action `{item.action_id}`가 `{item.observation_stage}` 단계에서 관찰되었습니다."
            for item in result.action_outcomes
        )

    def _decision_summary(self, result: SessionResult) -> str:
        lines: list[str] = []
        for item in result.action_outcomes:
            policy = item.policy_decision or "UNRESOLVED"
            attribution = item.attribution_grade or "UNRESOLVED"
            enforcement = item.enforcement_decision or "UNRESOLVED"
            if policy == "VIOLATION" and attribution in {"PROCESS", "TEMPORAL", "UNKNOWN"} and enforcement == "REFUSE":
                text = "정책 위반은 확인됐지만 자동 종료에 필요한 귀속 근거가 부족해 사용자 검토가 필요합니다."
            elif policy == "INDETERMINATE":
                text = "필수 증거가 부족하거나 판정이 충돌해 정상 또는 준수로 해석할 수 없습니다."
            else:
                text = f"Policy `{policy}`, Attribution `{attribution}`, Enforcement `{enforcement}` 결과를 유지했습니다."
            lines.append(f"- Action `{item.action_id}`: {text}")
        return "\n".join(lines) if lines else "- 연결된 판정이 없습니다."

    def _action_summary(self, result: SessionResult) -> str:
        if not result.enforcement_results:
            return "- 자동 Enforcement 결과가 없습니다."
        return "\n".join(
            f"- `{item.get('action_id', 'unknown')}`: decision=`{item.get('enforcement_decision', 'N/A')}`, action=`{item.get('enforcement_action', 'N/A')}`, execution=`{item.get('execution_result', 'N/A')}`"
            for item in result.enforcement_results
        )

    def _policy_section(self, result: SessionResult) -> str:
        policy = result.policy
        return "\n".join(
            [
                f"- Policy ID: `{policy.get('policy_id', result.policy.get('id', 'N/A'))}`",
                f"- Version: `{policy.get('policy_version', 'N/A')}`",
                f"- Profile: `{policy.get('profile', 'N/A')}`",
                f"- Fingerprint: `{policy.get('fingerprint', 'N/A')}`",
            ]
        )

    def _attribution_section(self, result: SessionResult) -> str:
        if not result.attribution_results:
            return "- Attribution 결과가 없습니다."
        return "\n".join(
            f"- Action `{item.get('action_id', 'unknown')}`: grade=`{item.get('grade', 'N/A')}`, reason=`{redact_text(item.get('reason'))}`"
            for item in result.attribution_results
        )

    def _enforcement_section(self, result: SessionResult) -> str:
        return self._action_summary(result)

    def _mapping_section(self, value: dict[str, Any] | None) -> str:
        if not value:
            return "- 결과가 없습니다."
        return "\n".join(
            f"- {key}: `{redact_text(value[key]) if isinstance(value[key], str) else value[key]}`"
            for key in sorted(value)
            if key not in {"raw_command", "payload", "content"}
        )

    def _sensor_section(self, result: SessionResult) -> str:
        if not result.sensor_summary:
            return "- Sensor 정보가 없습니다."
        return "\n".join(
            f"- `{item.get('sensor')}`: runtime=`{item.get('runtime_health_before_stop')}`, final=`{item.get('final_sensor_state')}`"
            for item in result.sensor_summary
        )

    def _action_section(self, result: SessionResult) -> str:
        if not result.action_outcomes:
            return "- 주요 Action이 없습니다."
        return "\n".join(
            f"- `{item.action_id}`: operation=`{item.operation}`, evidence_ids=`{', '.join(item.evidence_ids)}`"
            for item in result.action_outcomes
        )

    def _evidence_section(self, result: SessionResult) -> str:
        if not result.evidence_references:
            return "- Evidence Bundle reference가 없습니다."
        return "\n".join(
            f"- `{item.get('type')}`: `{item.get('relative_path')}` sha256=`{item.get('sha256')}`"
            for item in result.evidence_references
        )

    def _limitations_section(self, result: SessionResult) -> str:
        if not result.limitations:
            return "- 현재 기록된 limitation이 없습니다."
        return "\n".join(f"- {redact_text(item)}" for item in result.limitations)


def render_security_report(result: SessionResult) -> str:
    return ReportGenerator().render(result)


__all__ = ["ReportGenerator", "redact_text", "render_security_report"]
