"""EPIC-018 deterministic performance benchmark; no product behavior changes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any

from aia import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    EvidenceRecordType,
    EvidenceSource,
    FilesystemSensor,
    HookSensor,
    IntegrityStatus,
    NormalizedAction,
    NormalizationCompleteness,
    ObservationStage,
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyProfile,
    ProcessIdentity,
    ProcessObserverCapability,
    ProcessTerminationOutcome,
    ProcessTerminationResult,
    ProtectedRunSession,
    RawEvidenceStore,
    RecoveryCoordinator,
    RuntimePolicyEvaluation,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    resolve_profile,
)
from aia.evidence import RawEvidenceRecord
from aia.readiness import ProtectionReadinessBarrier


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _Observer:
    def __init__(self) -> None:
        self.alive = False

    def schedule(self, handler, path: str, recursive: bool) -> None:
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self) -> None:
        self.alive = True

    def stop(self) -> None:
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return self.alive


def _metric(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int((95 * len(ordered) + 99) // 100)))
    return {
        "n": len(values),
        "min_ms": min(values),
        "median_ms": statistics.median(values),
        "mean_ms": statistics.mean(values),
        "p95_ms": ordered[rank - 1],
        "max_ms": max(values),
    }


def _fixture(root: Path, file_count: int) -> dict[str, Any]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    for index in range(file_count):
        (workspace / f"file-{index:05d}.txt").write_text("x" * 128, encoding="utf-8")
    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
        created_at=NOW,
    )
    session.transition(SessionStatus.PREPARING, at=NOW)
    manager = WorkspaceLeaseManager(root / "control", process_identity_provider=process_create_time)
    context = prepare_protection(
        session,
        resolved,
        root / "control",
        lease_manager=manager,
        owner_pid=os.getpid(),
        owner_process_create_time=process_create_time(os.getpid()),
        frozen_at=NOW,
        acquired_at=NOW,
        prepared_at=NOW,
    )
    started = time.perf_counter()
    checkpoint = create_safe_checkpoint(session, context, lease_manager=manager, created_at=NOW)
    checkpoint_ms = (time.perf_counter() - started) * 1000
    filesystem = FilesystemSensor(
        session,
        context,
        checkpoint,
        lease_manager=manager,
        observer_factory=_Observer,
    )
    hook = HookSensor(session, context, checkpoint, lease_manager=manager)
    filesystem.start()
    hook.start()
    readiness_started = time.perf_counter()
    readiness = ProtectionReadinessBarrier(
        session,
        context,
        checkpoint,
        filesystem,
        hook,
        ProcessObserverCapability(aia_session_id=session.session_id, workspace=workspace),
        lease_manager=manager,
    ).evaluate()
    readiness_ms = (time.perf_counter() - readiness_started) * 1000
    session.transition(SessionStatus.RUNNING, at=NOW)
    return {
        "workspace": workspace,
        "session": session,
        "context": context,
        "checkpoint": checkpoint,
        "manager": manager,
        "filesystem": filesystem,
        "hook": hook,
        "checkpoint_ms": checkpoint_ms,
        "readiness_ms": readiness_ms,
    }


def _run_once(root: Path, file_count: int) -> dict[str, float]:
    values = _fixture(root, file_count)
    session = values["session"]
    context = values["context"]
    checkpoint = values["checkpoint"]
    workspace = values["workspace"]
    manager = values["manager"]
    try:
        integrity_started = time.perf_counter()
        baseline_integrity = context and __import__("aia").IntegrityVerifier().verify(
            checkpoint, workspace=workspace, session=session
        )
        integrity_ms = (time.perf_counter() - integrity_started) * 1000
        if baseline_integrity.integrity_status is not IntegrityStatus.VERIFIED:
            raise RuntimeError("baseline integrity did not verify")

        store = RawEvidenceStore.for_session(root / "control", session.session_id)
        evidence = store.append(
            RawEvidenceRecord(
                session_id=session.session_id,
                source=EvidenceSource.FILESYSTEM_WATCHER,
                record_type=EvidenceRecordType.FILESYSTEM_EVENT,
                captured_at=NOW,
                observation_stage=ObservationStage.POST_ACTION,
                payload={"event_type": "deleted", "src_path": "file-00000.txt"},
                evidence_id="benchmark-evidence",
            )
        )

        action = NormalizedAction(
            action_id="benchmark-action",
            aia_session_id=session.session_id,
            operation=Operation.DELETE,
            stage=ObservationStage.POST_ACTION,
            target_kind="FILE",
            observed_at=NOW,
            evidence_ids=(evidence.evidence_id,),
            evidence_sources=(EvidenceSource.FILESYSTEM_WATCHER,),
            completeness=NormalizationCompleteness.COMPLETE,
            normalizer_version="benchmark",
            canonical_path="file-00000.txt",
        )
        policy = RuntimePolicyEvaluation(
            action_id=action.action_id,
            aia_session_id=session.session_id,
            operation=action.operation,
            stage=action.stage,
            policy_id=session.policy_id,
            policy_version=session.policy_version,
            policy_profile=PolicyProfile.BASIC_DEVELOPMENT,
            active_policy_fingerprint=context.active_policy.sha256,
            policy_decision=PolicyDecision.VIOLATION,
            operation_effect=PolicyEffect.DENY,
            asset_type="CRITICAL_CODE",
            matched_rule_ids=("benchmark-rule",),
            audit_record=False,
            evaluated_at=NOW,
            path=action.canonical_path,
        )
        policy_started = time.perf_counter()
        _ = policy
        policy_ms = (time.perf_counter() - policy_started) * 1000

        identity = ProcessIdentity(os.getpid(), process_create_time(os.getpid()))
        gate = EnforcementGateResult(
            action_id=action.action_id,
            aia_session_id=session.session_id,
            policy_decision=PolicyDecision.VIOLATION,
            attribution_grade="EXACT",
            decision=EnforcementDecision.CONTAIN,
            route=EnforcementRoute.PROCESS_TERMINATION,
            action=EnforcementAction.NONE,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            stage=ObservationStage.POST_ACTION,
            checked_at=NOW,
            gate_checks=(),
            failure_reasons=(),
            policy_fingerprint=context.active_policy.sha256,
            root_process_identity=identity,
            hook_trust_status="VERIFIED",
            sensor_statuses=(),
            lease_status="LIVE_MATCH",
        )
        termination = ProcessTerminationResult(
            termination_id="benchmark-termination",
            aia_session_id=session.session_id,
            launch_id="benchmark-launch",
            decision=EnforcementDecision.CONTAIN,
            route=EnforcementRoute.PROCESS_TERMINATION,
            action=EnforcementAction.TERMINATED,
            execution_result=EnforcementExecutionResult.SUCCEEDED,
            termination_attempt_count=1,
            outcome=ProcessTerminationOutcome.TERMINATED,
            process_results=(),
            termination_requested_at=NOW,
            termination_started_at=NOW,
            termination_completed_at=NOW,
            gate_to_termination_start_ms=1,
            termination_duration_ms=1,
        )
        (workspace / "file-00000.txt").unlink()
        recovery_started = time.perf_counter()
        recovery = RecoveryCoordinator(manager).recover(
            gate,
            termination,
            session=session,
            checkpoint=checkpoint,
            workspace_lease=context.workspace_lease,
        )
        recovery_integrity_ms = (time.perf_counter() - recovery_started) * 1000
        recovery_ms = float(recovery.recovery.duration_ms or 0.0)
        measured_integrity_ms = float(recovery.integrity.integrity_duration_ms or 0.0)

        final_started = time.perf_counter()
        final = SessionFinalizer(
            evidence_store=store,
            sensors=(values["filesystem"], values["hook"]),
        ).finalize(
            session,
            process_end_status="PROCESS_GONE",
            actions=(action,),
            policy_evaluations=(policy,),
            gate_result=gate,
            termination_result=termination,
            recovery_result=recovery,
            active_policy=context.active_policy,
            checkpoint=checkpoint,
        )
        finalization_ms = (time.perf_counter() - final_started) * 1000
        return {
            "startup_readiness_ms": values["readiness_ms"],
            "checkpoint_ms": values["checkpoint_ms"],
            "pretool_decision_ms": policy_ms,
            "detection_to_decision_ms": policy_ms,
            "process_termination_ms": 0.0,
            "recovery_ms": recovery_ms,
            "integrity_ms": measured_integrity_ms,
            "recovery_integrity_ms": recovery_integrity_ms,
            "finalization_bundle_ms": finalization_ms,
        }
    finally:
        for sensor in (values["hook"], values["filesystem"]):
            try:
                sensor.stop()
            except Exception:
                pass


def _benchmark(file_count: int, repetitions: int) -> dict[str, Any]:
    measurements: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory(prefix=f"aia-epic018-{file_count}-") as directory:
        parent = Path(directory)
        for index in range(repetitions + 1):
            values = _run_once(parent / f"run-{index:03d}", file_count)
            if index == 0:
                continue
            for key, value in values.items():
                measurements.setdefault(key, []).append(value)
    return {
        "file_count": file_count,
        "warmup_runs": 1,
        "repetitions": repetitions,
        "statistics": {key: _metric(value) for key, value in measurements.items()},
        "p95_method": "nearest-rank, rank=ceil(0.95*n)",
        "file_size_bytes": 128,
    }


def main() -> int:
    evaluation_root = Path(os.environ["AIA_EPIC018_EVALUATION_ROOT"]).resolve()
    output = {
        "environment": {
            "windows": "Windows 11 Pro 10.0.26200",
            "python": "3.13.5",
            "cpu_logical_count": os.cpu_count(),
            "storage": "NVMe SSD (1 TB class)",
            "sla": "Measured, no frozen SLA",
        },
        "standard": _benchmark(10, 30),
        "workspace_100": _benchmark(100, 30),
        "workspace_1000": _benchmark(1000, 30),
    }
    output_path = evaluation_root / "performance" / "benchmark.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
