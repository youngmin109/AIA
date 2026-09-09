"""Check ProcessManager compatibility with an Actual Codex protected tree."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

from aia import (
    AttributionGrade,
    CodexAdapter,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    FilesystemSensor,
    HookSensor,
    ManagedProcessRegistry,
    ProcessIdentity,
    ProcessIdentityStatus,
    ProcessManager,
    ProcessObserverCapability,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    resolve_profile,
)
from aia.evidence import ObservationStage
from aia.policy import PolicyProfile
from aia.readiness import ProtectionReadinessBarrier


def now() -> datetime:
    return datetime.now(timezone.utc)


def identity(process: psutil.Process) -> ProcessIdentity:
    return ProcessIdentity(process.pid, process.create_time())


def gate(session: ProtectedRunSession, root: ProcessIdentity) -> EnforcementGateResult:
    return EnforcementGateResult(
        action_id="epic-018-actual-codex-termination",
        aia_session_id=session.session_id,
        policy_decision="VIOLATION",
        attribution_grade=AttributionGrade.PROCESS,
        decision=EnforcementDecision.CONTAIN,
        route=EnforcementRoute.PROCESS_TERMINATION,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
        stage=ObservationStage.POST_ACTION,
        checked_at=now(),
        gate_checks=(),
        failure_reasons=(),
        policy_fingerprint="epic-018-test-only-gate-fixture",
        root_process_identity=root,
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )


def main() -> int:
    evaluation_root = Path(os.environ["AIA_EPIC018_EVALUATION_ROOT"]).resolve()
    root = evaluation_root / "actual-codex" / "process-termination" / "attempt-001"
    workspace = root / "workspace"
    control_root = root / "control"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.txt").write_text(
        "Disposable Actual Codex ProcessManager compatibility fixture.\n",
        encoding="utf-8",
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=workspace,
    )
    session = None
    launcher = None
    calls: list[dict[str, object]] = []
    result: dict[str, object] = {
        "classification": "ENGINEERING_FIXTURE",
        "codex_version": "0.149.1",
        "model": "gpt-5.5",
        "scenario_realized": False,
        "failure_classification": None,
        "termination_calls": [],
    }
    try:
        resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            created_at=now(),
        )
        session.transition(SessionStatus.PREPARING, at=now())
        lease_manager = WorkspaceLeaseManager(
            control_root, process_identity_provider=process_create_time
        )
        preparation = prepare_protection(
            session,
            resolved,
            control_root,
            lease_manager=lease_manager,
            owner_pid=os.getpid(),
            owner_process_create_time=process_create_time(os.getpid()),
        )
        checkpoint = create_safe_checkpoint(session, preparation, lease_manager=lease_manager)
        filesystem = FilesystemSensor(
            session, preparation, checkpoint, lease_manager=lease_manager
        )
        hook = HookSensor(session, preparation, checkpoint, lease_manager=lease_manager)
        filesystem.start()
        hook.start()
        readiness = ProtectionReadinessBarrier(
            session,
            preparation,
            checkpoint,
            filesystem,
            hook,
            ProcessObserverCapability(
                aia_session_id=session.session_id,
                workspace=workspace,
            ),
            lease_manager=lease_manager,
        ).evaluate()
        result.update(
            {
                "aia_session_id": session.session_id,
                "readiness": readiness.status.value,
                "workspace": str(workspace),
            }
        )
        if readiness.readiness_context is None:
            result["failure_classification"] = "PRODUCT_DEFECT"
            return write_result(root, result, 1)

        launcher = ProtectedLauncher(
            session,
            readiness.readiness_context,
            preparation,
            checkpoint,
            filesystem,
            hook,
            adapter=CodexAdapter(),
            lease_manager=lease_manager,
        )
        launch = launcher.launch(
            ProtectedLaunchRequest(
                aia_session_id=session.session_id,
                workspace=workspace,
                agent="codex",
                model="gpt-5.5",
                prompt=(
                    "Use the command tool to run PowerShell Start-Sleep -Seconds 120. "
                    "This is a disposable AIA ProcessManager compatibility fixture. "
                    "Remain in that command until AIA terminates the protected run."
                ),
                adapter_options={
                    "ignore_user_config": True,
                    "sandbox": "danger-full-access",
                    "skip_git_repo_check": True,
                },
            )
        )
        result.update(
            {
                "launch_status": launch.status.value,
                "launch_failure_code": launch.failure_code,
                "launch_id": launch.context.launch_id if launch.context else None,
                "root_pid": (
                    launch.context.root_process_identity.pid if launch.context else None
                ),
                "root_create_time": (
                    launch.context.root_process_identity.create_time
                    if launch.context
                    else None
                ),
                "managed_registry_registered": (
                    launcher.managed_process_registry.get_by_session(session.session_id)
                    is not None
                ),
                "process_sensor_status": (
                    launcher.process_sensor.status.value if launcher.process_sensor else None
                ),
            }
        )
        if launch.context is None or launch.status.value != "RUNNING":
            result["failure_classification"] = "ENVIRONMENT_LIMITATION"
            return write_result(root, result, 1)
        result["scenario_realized"] = True
        actual_root = ProcessIdentity(
            launch.context.root_process_identity.pid,
            launch.context.root_process_identity.create_time,
        )
        unrelated_identity = identity(psutil.Process(unrelated.pid))
        result["unrelated_pid"] = unrelated_identity.pid
        result["unrelated_create_time"] = unrelated_identity.create_time
        time.sleep(5)

        class TrackingProcess:
            def __init__(self, process: psutil.Process) -> None:
                self._process = process

            def __getattr__(self, name: str):
                return getattr(self._process, name)

            def terminate(self):
                calls.append({"method": "terminate", "pid": self.pid})
                return self._process.terminate()

            def kill(self):
                calls.append({"method": "kill", "pid": self.pid})
                return self._process.kill()

        def process_factory(pid: int) -> TrackingProcess:
            return TrackingProcess(psutil.Process(pid))

        manager = ProcessManager(
            launcher.managed_process_registry,
            lease_manager,
            process_factory=process_factory,
            terminate_wait_seconds=1.0,
            force_kill_wait_seconds=1.0,
        )
        termination = manager.execute(
            gate(session, actual_root),
            session=session,
            launch_context=launch.context,
            workspace_lease=preparation.workspace_lease,
        )
        unrelated_status = ProcessIdentityStatus.PROCESS_GONE
        try:
            current = psutil.Process(unrelated_identity.pid)
            unrelated_status = (
                ProcessIdentityStatus.LIVE_MATCH
                if current.create_time() == unrelated_identity.create_time
                else ProcessIdentityStatus.PID_REUSED
            )
        except psutil.NoSuchProcess:
            pass
        result.update(
            {
                "outcome": termination.outcome.value,
                "action": termination.action.value,
                "execution_result": termination.execution_result.value,
                "termination_attempt_count": termination.termination_attempt_count,
                "termination_calls": calls,
                "unrelated_termination_calls": [
                    item for item in calls if item["pid"] == unrelated_identity.pid
                ],
                "unrelated_status": unrelated_status.value,
                "entries": [
                    {
                        "pid": entry.process_identity.pid,
                        "role": entry.process_role,
                        "initial": entry.initial_verification.value,
                        "final": entry.final_verification.value,
                        "outcome": entry.outcome.value,
                    }
                    for entry in termination.entries
                ],
                "failure_classification": (
                    None
                    if termination.outcome.value == "TERMINATED"
                    and termination.action.value == "TERMINATED"
                    and termination.execution_result.value == "SUCCEEDED"
                    and unrelated_status is ProcessIdentityStatus.LIVE_MATCH
                    and not [
                        item for item in calls if item["pid"] == unrelated_identity.pid
                    ]
                    else "ENVIRONMENT_LIMITATION"
                ),
            }
        )
        return write_result(root, result, 0 if result["failure_classification"] is None else 1)
    except Exception as error:
        result.update(
            {
                "failure_classification": "HARNESS_ERROR",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        return write_result(root, result, 1)
    finally:
        if launcher is not None and launcher.process_handle is not None:
            try:
                if launcher.process_handle.poll() is None:
                    launcher.process_handle.kill()
            except Exception:
                pass
        try:
            if unrelated.poll() is None:
                unrelated.kill()
        except Exception:
            pass
        try:
            unrelated.wait(timeout=5)
        except Exception:
            pass


def write_result(root: Path, result: dict[str, object], code: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
