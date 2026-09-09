"""Standalone EPIC-015 Windows process-tree verification.

Run from an ordinary PowerShell session with:

    uv run python scripts/epic015_process_manager_smoke.py

This is deliberately outside pytest so a pytest runner Job Object cannot
change the process-tree result.  It exercises only the Process Manager
termination contract; it is not a Policy or destructive Codex E2E test.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import psutil

from aia import (
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    ManagedProcess,
    ManagedProcessRegistry,
    ProcessIdentity,
    ProcessIdentityStatus,
    ProcessManager,
    ProcessTerminationOutcome,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
)
from aia.evidence import ObservationStage


NOW = datetime.now(timezone.utc)


def _write_process_scripts(workspace: Path) -> tuple[Path, Path, Path]:
    grandchild = workspace / "grandchild.py"
    child = workspace / "child.py"
    root = workspace / "root.py"
    grandchild.write_text("import time; time.sleep(120)\n", encoding="utf-8")
    child.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1]])\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    root.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    return root, child, grandchild


def _wait_for_tree(root_pid: int) -> tuple[psutil.Process, psutil.Process, psutil.Process]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            root = psutil.Process(root_pid)
            descendants = root.children(recursive=True)
            child = next(
                process
                for process in descendants
                if process.parent() is not None and process.parent().pid == root_pid
            )
            grandchild = next(
                process
                for process in descendants
                if process.parent() is not None and process.parent().pid == child.pid
            )
            return root, child, grandchild
        except (psutil.Error, StopIteration):
            time.sleep(0.05)
    raise RuntimeError("Root -> Child -> Grandchild tree did not become observable")


def _make_gate(
    session: ProtectedRunSession,
    root_identity: ProcessIdentity,
) -> EnforcementGateResult:
    return EnforcementGateResult(
        action_id="epic-015-smoke-action",
        aia_session_id=session.session_id,
        policy_decision="VIOLATION",
        attribution_grade=AttributionGrade.EXACT,
        decision=EnforcementDecision.CONTAIN,
        route=EnforcementRoute.PROCESS_TERMINATION,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
        stage=ObservationStage.POST_ACTION,
        checked_at=NOW,
        gate_checks=(),
        failure_reasons=(),
        policy_fingerprint="epic-015-smoke-policy",
        root_process_identity=root_identity,
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )


def _cleanup_process_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        processes = root.children(recursive=True)
    except psutil.Error:
        processes = []
    for process in reversed(processes):
        try:
            process.kill()
        except psutil.Error:
            pass
    try:
        root.kill()
    except (UnboundLocalError, psutil.Error):
        pass
    for process in processes:
        try:
            process.wait(timeout=5)
        except psutil.Error:
            pass


def main() -> int:
    if os.name != "nt":
        print("SKIP: this runner is intended for Windows process integration")
        return 2

    root_process: subprocess.Popen[bytes] | None = None
    unrelated_process: subprocess.Popen[bytes] | None = None
    managed_pids: set[int] = set()
    with tempfile.TemporaryDirectory(prefix="aia-epic015-smoke-") as temporary:
        base = Path(temporary)
        workspace = base / "workspace"
        control_root = base / "control"
        workspace.mkdir()
        root_script, child_script, grandchild_script = _write_process_scripts(workspace)
        unrelated_process = subprocess.Popen(
            [sys.executable, str(grandchild_script)],
            cwd=workspace,
        )
        root_process = subprocess.Popen(
            [sys.executable, str(root_script), str(child_script), str(grandchild_script)],
            cwd=workspace,
        )
        try:
            root, child, grandchild = _wait_for_tree(root_process.pid)
            managed_pids.update(
                process.pid
                for process in [root, child, grandchild, *root.children(recursive=True)]
            )
            unrelated = psutil.Process(unrelated_process.pid)
            identities = {
                "root": ProcessIdentity(root.pid, root.create_time()),
                "child": ProcessIdentity(child.pid, child.create_time()),
                "grandchild": ProcessIdentity(grandchild.pid, grandchild.create_time()),
                "unrelated": ProcessIdentity(unrelated.pid, unrelated.create_time()),
            }
            print(
                "identities="
                + json.dumps(
                    {
                        name: {
                            "pid": identity.pid,
                            "create_time": identity.create_time,
                        }
                        for name, identity in identities.items()
                    },
                    sort_keys=True,
                )
            )

            session = ProtectedRunSession(
                workspace=workspace,
                agent="codex",
                mode=SessionMode.ENFORCE,
                policy_id="epic-015-smoke-policy",
                policy_version="1",
            )
            session.transition(SessionStatus.PREPARING, at=NOW)
            session.transition(SessionStatus.READY, at=NOW)
            session.transition(SessionStatus.RUNNING, at=NOW)
            owner = psutil.Process(os.getpid())
            lease_manager = WorkspaceLeaseManager(
                control_root,
                process_identity_provider=lambda pid: psutil.Process(pid).create_time(),
            )
            lease = lease_manager.acquire(
                workspace,
                session.session_id,
                owner_pid=owner.pid,
                owner_process_create_time=owner.create_time(),
            )
            registry = ManagedProcessRegistry()
            registry.register(
                ManagedProcess(
                    aia_session_id=session.session_id,
                    launch_id="epic-015-smoke-launch",
                    workspace=workspace,
                    root_process_identity=identities["root"],
                    launch_provenance="AIA_SPAWNED_ROOT",
                    registered_at=NOW,
                    executable=Path(sys.executable),
                )
            )
            launch_context = SimpleNamespace(
                launch_id="epic-015-smoke-launch",
                aia_session_id=session.session_id,
                workspace=session.workspace,
                root_process_identity=identities["root"],
                launch_provenance="AIA_SPAWNED_ROOT",
            )
            calls: list[tuple[str, int]] = []
            unrelated_pid = unrelated.pid

            class TrackingProcess:
                def __init__(self, process: psutil.Process) -> None:
                    self._process = process

                def __getattr__(self, name):
                    return getattr(self._process, name)

                def terminate(self):
                    calls.append(("terminate", self.pid))
                    return self._process.terminate()

                def kill(self):
                    calls.append(("kill", self.pid))
                    return self._process.kill()

            def process_factory(pid: int) -> TrackingProcess:
                return TrackingProcess(psutil.Process(pid))

            manager = ProcessManager(
                registry,
                lease_manager,
                process_factory=process_factory,
                terminate_wait_seconds=1.0,
                force_kill_wait_seconds=1.0,
            )
            result = manager.execute(
                _make_gate(session, identities["root"]),
                session=session,
                launch_context=launch_context,
                workspace_lease=lease,
            )
            managed_calls = [call for call in calls if call[1] != unrelated_pid]
            unrelated_calls = [call for call in calls if call[1] == unrelated_pid]
            unrelated_status = ProcessIdentityStatus.PROCESS_GONE
            try:
                current_unrelated = psutil.Process(unrelated_pid)
                current_create_time = current_unrelated.create_time()
                unrelated_status = (
                    ProcessIdentityStatus.LIVE_MATCH
                    if current_create_time == identities["unrelated"].create_time
                    else ProcessIdentityStatus.PID_REUSED
                )
            except psutil.NoSuchProcess:
                unrelated_status = ProcessIdentityStatus.PROCESS_GONE

            print(
                "termination_result="
                + json.dumps(
                    {
                        "outcome": result.outcome.value,
                        "action": result.action.value,
                        "execution_result": result.execution_result.value,
                        "entries": [
                            {
                                "pid": entry.process_identity.pid,
                                "role": entry.process_role,
                                "depth": entry.depth,
                                "initial_verification": entry.initial_verification.value,
                                "final_verification": entry.final_verification.value,
                                "outcome": entry.outcome.value,
                            }
                            for entry in result.entries
                        ],
                        "termination_api_order": managed_calls,
                        "unrelated_termination_calls": unrelated_calls,
                        "unrelated_status": unrelated_status.value,
                    },
                    sort_keys=True,
                )
            )
            if result.outcome is not ProcessTerminationOutcome.TERMINATED:
                raise RuntimeError(
                    f"unexpected ProcessManager outcome: {result.outcome}; {result.reason}"
                )
            if result.action is not EnforcementAction.TERMINATED:
                raise RuntimeError("successful smoke did not produce TERMINATED action")
            if result.execution_result is not EnforcementExecutionResult.SUCCEEDED:
                raise RuntimeError("successful smoke did not produce SUCCEEDED execution")
            if unrelated_status is not ProcessIdentityStatus.LIVE_MATCH:
                raise RuntimeError("unrelated process was not preserved")
            if unrelated_calls:
                raise RuntimeError(f"unrelated process received termination calls: {unrelated_calls}")
            if any(
                entry.final_verification is ProcessIdentityStatus.LIVE_MATCH
                for entry in result.entries
            ):
                raise RuntimeError("a managed identity remained LIVE_MATCH")
            print("PASS: EPIC-015 Windows process-tree termination smoke")
            return 0
        finally:
            try:
                if root_process is not None:
                    managed_pids.update(
                        process.pid
                        for process in psutil.Process(root_process.pid).children(
                            recursive=True
                        )
                    )
            except psutil.Error:
                pass
            for pid in managed_pids:
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass
            for process in (root_process, unrelated_process):
                if process is not None and process.poll() is None:
                    _cleanup_process_tree(process.pid)
                    try:
                        process.wait(timeout=5)
                    except psutil.Error:
                        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
