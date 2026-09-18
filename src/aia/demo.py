"""Deterministic presentation fixtures for the AIA product demo.

The demo deliberately writes normal, verifiable Result Bundles instead of
inventing a second UI data format.  It is presentation data, not evidence
that an Actual Codex run occurred; the ``ENGINEERING_FIXTURE`` classification
and explicit limitation make that boundary visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from .audit import AuditEventType, AuditRecord, audit_jsonl
from .evidence import (
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)
from .evidence_bundle import EvidenceBundleCommitter
from .report import ReportGenerator
from .result import ActionOutcomeRecord, RunClassification, SensorSummary, SessionResult
from .session import SessionEndReason, SessionMode, SessionStatus


DEMO_SCENARIOS = ("process-kill", "hook-block", "file-rollback")
DEFAULT_DEMO_WORKSPACE = Path(r"C:\workspace\aia-demo")
DEFAULT_DEMO_CONTROL_ROOT = Path(r"C:\workspace\aia-demo-control")
DEMO_WORKSPACE_MARKER = ".aia-demo-workspace"
DEMO_CONTROL_MARKER = ".aia-demo-control-root"


@dataclass(frozen=True, slots=True)
class DemoScenario:
    name: str
    title: str
    policy_id: str
    rule_id: str
    operation: str
    target_kind: str
    target_label: str
    asset_type: str
    route: str
    enforcement_action: str
    evidence: tuple[tuple[str, str, str, str], ...]
    attribution: str
    session_end_reason: str
    recovery: dict[str, Any] | None = None
    integrity: dict[str, Any] | None = None
    termination: dict[str, Any] | None = None


SCENARIOS: dict[str, DemoScenario] = {
    "process-kill": DemoScenario(
        name="process-kill",
        title="Process Sensor 관리 트리 종료",
        policy_id="demo-process-guardrail",
        rule_id="demo-destructive-process-deny",
        operation="EXECUTE",
        target_kind="COMMAND",
        target_label="파괴적 프로세스 실행",
        asset_type="WORKSPACE",
        route="PROCESS_TERMINATION",
        enforcement_action="TERMINATED",
        evidence=(
            ("AGENT_HOOK", "PRETOOL_REQUEST", "PRE_ACTION", "hook-process-request"),
            ("PROCESS_RUNTIME", "PROCESS_OBSERVED", "POST_ACTION", "process-root-observed"),
            ("PROCESS_RUNTIME", "PROCESS_OBSERVED", "POST_ACTION", "process-child-observed"),
            ("PROCESS_RUNTIME", "PROCESS_EXIT_OBSERVED", "POST_ACTION", "process-tree-exited"),
        ),
        attribution="EXACT",
        session_end_reason=SessionEndReason.SECURITY_CONTAINMENT.value,
        termination={
            "termination_id": "demo-process-termination",
            "action": "TERMINATED",
            "decision": "CONTAIN",
            "route": "PROCESS_TERMINATION",
            "execution_result": "SUCCEEDED",
            "termination_attempt_count": 3,
            "managed_tree_status": "PROCESS_GONE",
            "unrelated_process_affected": False,
        },
    ),
    "hook-block": DemoScenario(
        name="hook-block",
        title="Hook Sensor PreToolUse 사전 차단",
        policy_id="demo-hook-guardrail",
        rule_id="demo-dangerous-command-deny",
        operation="EXECUTE",
        target_kind="COMMAND",
        target_label="정책 위반 명령 실행 요청",
        asset_type="WORKSPACE",
        route="PRETOOL_BLOCK",
        enforcement_action="BLOCKED",
        evidence=(
            ("AGENT_HOOK", "PRETOOL_REQUEST", "PRE_ACTION", "hook-block-request"),
            ("AGENT_HOOK", "SENSOR_HEALTH", "PRE_ACTION", "hook-health"),
        ),
        attribution="EXACT",
        session_end_reason=SessionEndReason.AGENT_EXITED.value,
    ),
    "file-rollback": DemoScenario(
        name="file-rollback",
        title="File Sensor 삭제 감지와 검증 복구",
        policy_id="demo-file-guardrail",
        rule_id="demo-critical-file-delete-deny",
        operation="DELETE",
        target_kind="FILE",
        target_label="중요 데이터 파일 삭제",
        asset_type="CRITICAL_CODE",
        route="PROCESS_TERMINATION",
        enforcement_action="TERMINATED",
        evidence=(
            ("AGENT_HOOK", "PRETOOL_REQUEST", "PRE_ACTION", "hook-file-request"),
            ("FILESYSTEM_WATCHER", "FILESYSTEM_EVENT", "POST_ACTION", "file-delete-observed"),
            ("PROCESS_RUNTIME", "PROCESS_EXIT_OBSERVED", "POST_ACTION", "file-agent-stopped"),
        ),
        attribution="EXACT",
        session_end_reason=SessionEndReason.SECURITY_CONTAINMENT.value,
        termination={
            "termination_id": "demo-file-termination",
            "action": "TERMINATED",
            "decision": "CONTAIN",
            "route": "PROCESS_TERMINATION",
            "execution_result": "SUCCEEDED",
            "termination_attempt_count": 1,
            "managed_tree_status": "PROCESS_GONE",
        },
        recovery={
            "recovery_id": "demo-file-recovery",
            "recovery_status": "RESTORED",
            "planned_operation_count": 1,
            "attempted_operation_count": 1,
            "succeeded_operation_count": 1,
            "failed_operation_count": 0,
            "restored_paths": ["important-data.txt"],
            "removed_paths": [],
            "failed_paths": [],
        },
        integrity={
            "integrity_status": "VERIFIED",
            "expected_entry_count": 3,
            "actual_entry_count": 3,
            "missing_paths": [],
            "unexpected_paths": [],
            "changed_paths": [],
            "verification_errors": [],
        },
    ),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _prepare_workspace(workspace: Path) -> None:
    workspace = workspace.expanduser().resolve(strict=False)
    if workspace.exists() and not workspace.is_dir():
        raise ValueError(f"demo workspace is not a directory: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / DEMO_WORKSPACE_MARKER
    if any(workspace.iterdir()) and not marker.is_file():
        raise ValueError(
            f"refusing to reset a non-demo directory: {workspace}; "
            f"create {DEMO_WORKSPACE_MARKER} first"
        )
    for child in tuple(workspace.iterdir()):
        if child.name == DEMO_WORKSPACE_MARKER:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    marker.write_text("AIA deterministic presentation workspace\n", encoding="utf-8")
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text(
        "def protected_value():\n    return 'baseline'\n", encoding="utf-8"
    )
    (workspace / "important-data.txt").write_text(
        "AIA demo baseline data\n", encoding="utf-8"
    )
    (workspace / "README.md").write_text(
        "# AIA Demo Workspace\n\nThis folder is reset by the AIA demo runner.\n",
        encoding="utf-8",
    )


def _prepare_control_root(control_root: Path) -> None:
    control_root = control_root.expanduser().resolve(strict=False)
    control_root.mkdir(parents=True, exist_ok=True)
    marker = control_root / DEMO_CONTROL_MARKER
    if any(control_root.iterdir()) and not marker.is_file():
        raise ValueError(
            f"refusing to reset a non-demo control root: {control_root}; "
            f"create {DEMO_CONTROL_MARKER} first"
        )
    marker.write_text("AIA deterministic demo Control Root\n", encoding="utf-8")
    sessions = control_root / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)


def _write_checkpoint_artifacts(session_dir: Path, session_id: str) -> tuple[dict[str, Any], ...]:
    checkpoint = session_dir / "checkpoint" / "demo-checkpoint"
    checkpoint.mkdir(parents=True, exist_ok=True)
    metadata = checkpoint / "metadata.json"
    manifest = checkpoint / "manifest.json"
    metadata.write_text(
        json.dumps(
            {
                "checkpoint_id": "demo-checkpoint",
                "schema_version": "1.0",
                "session_id": session_id,
                "validity": "VALID",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "checkpoint_id": "demo-checkpoint",
                "schema_version": "aia-checkpoint-manifest-1",
                "session_id": session_id,
                "entries": [{"path": "important-data.txt", "sha256": "demo-baseline"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return (
        {"path": metadata, "relative_path": "checkpoint/demo-checkpoint/metadata.json", "type": "CHECKPOINT_METADATA"},
        {"path": manifest, "relative_path": "checkpoint/demo-checkpoint/manifest.json", "type": "CHECKPOINT_MANIFEST"},
    )


def _audit_records(scenario: DemoScenario, session_id: str, now: datetime, action_id: str) -> bytes:
    names = (
        (AuditEventType.SESSION_CREATED, "session"),
        (AuditEventType.PROTECTION_STARTED, "protection"),
        (AuditEventType.POLICY_FROZEN, "policy"),
        (AuditEventType.LEASE_ACQUIRED, "lease"),
        (AuditEventType.CHECKPOINT_CREATED, "checkpoint"),
        (AuditEventType.SENSOR_HEALTH, "sensors"),
        (AuditEventType.ACTION_OBSERVED, action_id),
        (AuditEventType.POLICY_EVALUATED, action_id),
        (AuditEventType.ATTRIBUTION_EVALUATED, action_id),
        (AuditEventType.ENFORCEMENT_DECIDED, action_id),
        (AuditEventType.ENFORCEMENT_EXECUTED, action_id),
    )
    if scenario.termination:
        names += ((AuditEventType.PROCESS_TERMINATED, "termination"),)
    if scenario.recovery:
        names += ((AuditEventType.RECOVERY_EXECUTED, "recovery"), (AuditEventType.INTEGRITY_VERIFIED, "integrity"))
    names += ((AuditEventType.SENSOR_STOPPED, "sensors"), (AuditEventType.SESSION_FINALIZED, "session"))
    records = tuple(
        AuditRecord(
            audit_id=f"demo-audit-{index:02d}",
            aia_session_id=session_id,
            occurred_at=now + timedelta(milliseconds=index),
            event_type=event,
            entity_type="demo",
            entity_id=entity,
            source_reference=f"demo:{scenario.name}",
            action_id=action_id if entity == action_id else None,
            summary=f"Demo fixture: {scenario.title}",
        )
        for index, (event, entity) in enumerate(names, 1)
    )
    return audit_jsonl(records)


def _build_result(scenario: DemoScenario, session_id: str, workspace: Path, now: datetime) -> SessionResult:
    action_id = f"demo-action-{scenario.name}"
    evidence_ids = tuple(item[3] for item in scenario.evidence if item[1] != "SENSOR_HEALTH")
    operation_effect = "DENY" if scenario.enforcement_action == "BLOCKED" else "CONTAIN"
    action = ActionOutcomeRecord(
        action_id=action_id,
        operation=scenario.operation,
        target={"target_kind": scenario.target_kind, "label": scenario.target_label},
        observation_stage="PRE_ACTION" if scenario.name == "hook-block" else "POST_ACTION",
        evidence_ids=evidence_ids,
        policy_decision="VIOLATION",
        matched_rule_ids=(scenario.rule_id,),
        matched_asset_types=(scenario.asset_type,),
        attribution_grade=scenario.attribution,
        attribution_reason="Hook·Sensor Evidence와 Session이 Demo Fixture에 연결됨",
        enforcement_decision="CONTAIN",
        enforcement_route=scenario.route,
        enforcement_action=scenario.enforcement_action,
        execution_result="SUCCEEDED",
        related_termination_id=(scenario.termination or {}).get("termination_id"),
        related_recovery_id=(scenario.recovery or {}).get("recovery_id"),
        operation_effect=operation_effect,
    )
    sensor_summary = tuple(
        SensorSummary(sensor, "HEALTHY", "STOPPED", reason="DEMO_FIXTURE")
        for sensor in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME")
    )
    policy = {
        "policy_id": scenario.policy_id,
        "policy_version": "1.0-demo",
        "profile": "DEMO_GUARDRAIL",
        "fingerprint": f"demo:{scenario.name}",
    }
    return SessionResult(
        schema_version="aia-result-1",
        result_id=f"demo-result-{scenario.name}",
        aia_session_id=session_id,
        workspace=str(workspace),
        agent="demo-fixture",
        mode=SessionMode.ENFORCE,
        policy=policy,
        created_at=now,
        started_at=now + timedelta(milliseconds=40),
        ended_at=now + timedelta(milliseconds=580),
        session_status=SessionStatus.COMPLETED,
        session_end_reason=scenario.session_end_reason,
        sensor_summary=tuple(item.to_mapping() for item in sensor_summary),
        action_outcomes=(action,),
        policy_evaluations=({
            "action_id": action_id,
            "policy_decision": "VIOLATION",
            "matched_rule_ids": [scenario.rule_id],
            "asset_type": scenario.asset_type,
            "reason": "Demo guardrail matched",
        },),
        attribution_results=({
            "action_id": action_id,
            "grade": scenario.attribution,
            "reason": "Session-bound demo evidence",
            "supporting_evidence_ids": list(evidence_ids),
        },),
        enforcement_results=({
            "action_id": action_id,
            "enforcement_decision": "CONTAIN",
            "enforcement_action": scenario.enforcement_action,
            "execution_result": "SUCCEEDED",
            "route": scenario.route,
        },),
        process_termination_result=scenario.termination,
        user_abort_termination_result=None,
        protection_failure_termination_result=None,
        recovery_result=scenario.recovery,
        integrity_result=scenario.integrity,
        limitations=(
            "DEMO_FIXTURE: this Result Bundle is deterministic presentation data, not an Actual Codex run.",
            "PROCESS는 exact file writer 증명이 아닙니다.",
        ),
        evidence_references=tuple(
            {"evidence_id": item[3], "source": item[0], "record_type": item[1]}
            for item in scenario.evidence
        ),
        generated_at=now + timedelta(milliseconds=600),
        finalization_started_at=now + timedelta(milliseconds=590),
        finalization_completed_at=now + timedelta(milliseconds=600),
        finalization_duration_ms=10.0,
        review_required=False,
        run_classification=RunClassification.ENGINEERING_FIXTURE,
        agent_execution={
            "output_observation": {
                "effective_sandbox": "workspace-write",
                "effective_approval_policy": "on-request",
                "reason": "DEMO_FIXTURE",
            }
        },
    )


def run_demo(
    scenario_name: str,
    *,
    workspace: Path = DEFAULT_DEMO_WORKSPACE,
    control_root: Path = DEFAULT_DEMO_CONTROL_ROOT,
) -> dict[str, Any]:
    """Reset the dedicated demo roots and publish one verified demo bundle."""

    if scenario_name not in SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario_name}")
    workspace = workspace.expanduser().resolve(strict=False)
    control_root = control_root.expanduser().resolve(strict=False)
    _prepare_workspace(workspace)
    _prepare_control_root(control_root)
    scenario = SCENARIOS[scenario_name]
    session_id = f"demo-{scenario.name}"
    session_dir = control_root / "sessions" / session_id
    now = _now()
    store = RawEvidenceStore.for_session(control_root, session_id)
    for source, record_type, stage, evidence_id in scenario.evidence:
        payload: dict[str, Any] = {"demo": True, "scenario": scenario.name}
        if record_type == "PROCESS_OBSERVED":
            payload.update({"pid": 2401 if evidence_id.endswith("root-observed") else 2402, "process_role": "managed"})
        elif record_type == "PROCESS_EXIT_OBSERVED":
            payload.update({"pid": 2401, "process_role": "managed", "exit_status": "TERMINATED"})
        elif record_type == "FILESYSTEM_EVENT":
            payload.update({"event_type": "deleted", "path_label": "important-data.txt"})
        elif record_type == "PRETOOL_REQUEST":
            payload.update({"tool_name": "Bash", "operation": scenario.operation})
        store.append(
            RawEvidenceRecord(
                session_id=session_id,
                source=source,
                record_type=record_type,
                captured_at=now,
                observation_stage=stage,
                payload=payload,
                evidence_id=evidence_id,
            )
        )
    store.seal(sealed_at=now + timedelta(milliseconds=400))
    store.build_index()
    result = _build_result(scenario, session_id, workspace, now)
    checkpoint_artifacts = _write_checkpoint_artifacts(session_dir, session_id)
    evidence_artifacts = (
        {"path": store.path, "relative_path": "evidence/raw-evidence.jsonl", "type": "RAW_EVIDENCE"},
        {"path": store.seal_path, "relative_path": "evidence/raw-evidence.seal.json", "type": "EVIDENCE_SEAL"},
        {"path": store.index_path, "relative_path": "evidence/evidence-index.json", "type": "EVIDENCE_INDEX"},
    )
    commit = EvidenceBundleCommitter(session_dir).commit(
        result,
        audit_bytes=_audit_records(scenario, session_id, now, f"demo-action-{scenario.name}"),
        report_bytes=ReportGenerator().render(result).encode("utf-8"),
        evidence_artifacts=evidence_artifacts,
        extra_artifacts=checkpoint_artifacts,
        committed_at=now + timedelta(milliseconds=610),
    )
    return {
        "scenario": scenario.name,
        "title": scenario.title,
        "session_id": session_id,
        "workspace": str(workspace),
        "control_root": str(control_root),
        "result_path": str(commit.result_directory / "result.json"),
        "bundle_status": "VALID",
        "classification": RunClassification.ENGINEERING_FIXTURE.value,
        "next_step": f"$env:AIA_CONTROL_ROOT='{control_root}'; uv run --isolated --project . python -m aia.cli console --open",
    }


__all__ = [
    "DEFAULT_DEMO_CONTROL_ROOT",
    "DEFAULT_DEMO_WORKSPACE",
    "DEMO_SCENARIOS",
    "DemoScenario",
    "run_demo",
]
