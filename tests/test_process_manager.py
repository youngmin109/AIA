from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from aia import (
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGateResult,
    EnforcementRoute,
    ManagedProcess,
    ManagedProcessRegistry,
    ManagedRootConflictError,
    ProcessIdentity,
    ProcessIdentityStatus,
    ProcessManager,
    ProcessTerminationOutcome,
    PolicyDecision,
    SessionMode,
    SessionStatus,
    ProtectedRunSession,
    TerminationAttemptResult,
)
from aia.evidence import ObservationStage


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _LeaseManager:
    def __init__(self, lease):
        self.lease = lease

    def validate_ownership(self, lease):
        if lease is not self.lease:
            raise ValueError("lease mismatch")
        return lease


def _environment(tmp_path: Path, identity: ProcessIdentity, *, process_factory=psutil.Process):
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir(exist_ok=True)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id="policy-015",
        policy_version="1",
    )
    session.transition(SessionStatus.PREPARING, at=NOW)
    session.transition(SessionStatus.READY, at=NOW)
    session.transition(SessionStatus.RUNNING, at=NOW)
    lease = SimpleNamespace(session_id=session.session_id, workspace=workspace)
    launch = SimpleNamespace(
        launch_id="launch-015",
        aia_session_id=session.session_id,
        workspace=workspace,
        root_process_identity=identity,
        launch_provenance="AIA_SPAWNED_ROOT",
    )
    registry = ManagedProcessRegistry()
    registry.register(
        ManagedProcess(
            aia_session_id=session.session_id,
            launch_id=launch.launch_id,
            workspace=workspace,
            root_process_identity=identity,
            launch_provenance="AIA_SPAWNED_ROOT",
            registered_at=NOW,
        )
    )
    gate = EnforcementGateResult(
        action_id="action-015",
        aia_session_id=session.session_id,
        policy_decision=PolicyDecision.VIOLATION,
        attribution_grade=AttributionGrade.EXACT,
        decision=EnforcementDecision.CONTAIN,
        route=EnforcementRoute.PROCESS_TERMINATION,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
        stage=ObservationStage.POST_ACTION,
        checked_at=NOW,
        gate_checks=(),
        failure_reasons=(),
        policy_fingerprint="fingerprint",
        root_process_identity=identity,
        hook_trust_status="VERIFIED",
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=process_factory,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    return session, launch, lease, gate, registry, manager


def test_registry_is_idempotent_and_refuses_conflicting_root(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = ManagedProcessRegistry()
    first = ManagedProcess(
        "session-1",
        "launch-1",
        workspace,
        ProcessIdentity(100, 1),
        "AIA_SPAWNED_ROOT",
        NOW,
    )
    assert registry.register(first) is first
    assert registry.register(first) == first
    with pytest.raises(ManagedRootConflictError) as error:
        registry.register(
            ManagedProcess(
                "session-1",
                "launch-2",
                workspace,
                ProcessIdentity(101, 2),
                "AIA_SPAWNED_ROOT",
                NOW,
            )
        )
    assert error.value.code == "MANAGED_ROOT_CONFLICT"


def test_gate_refusal_never_looks_up_a_process(tmp_path: Path):
    identity = ProcessIdentity(100, 1)
    session, launch, lease, gate, registry, _ = _environment(tmp_path, identity)
    refused_gate = EnforcementGateResult(
        action_id=gate.action_id,
        aia_session_id=gate.aia_session_id,
        policy_decision=gate.policy_decision,
        attribution_grade=gate.attribution_grade,
        decision=EnforcementDecision.REFUSE,
        route=EnforcementRoute.NONE,
        action=EnforcementAction.NONE,
        execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
        stage=gate.stage,
        checked_at=gate.checked_at,
        gate_checks=(),
        failure_reasons=("ATTRIBUTION_NOT_EXACT",),
        policy_fingerprint=gate.policy_fingerprint,
        root_process_identity=identity,
        hook_trust_status=gate.hook_trust_status,
        sensor_statuses=(),
        lease_status="LIVE_MATCH",
    )
    lookups = 0

    def should_not_lookup(_pid):
        nonlocal lookups
        lookups += 1
        raise AssertionError("a refused Gate must not reach process lookup")

    manager = ProcessManager(registry, _LeaseManager(lease), process_factory=should_not_lookup)
    result = manager.execute(
        refused_gate,
        session=session,
        launch_context=launch,
        workspace_lease=lease,
    )
    assert result.outcome is ProcessTerminationOutcome.REFUSED
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED
    assert lookups == 0


@pytest.mark.parametrize("mismatch", ["launch", "workspace", "lease"])
def test_binding_or_lease_mismatch_never_looks_up_a_process(
    tmp_path: Path,
    mismatch: str,
):
    identity = ProcessIdentity(101, 1)
    session, launch, lease, gate, registry, _ = _environment(tmp_path, identity)
    original_lease = lease
    if mismatch == "launch":
        launch = SimpleNamespace(**{**vars(launch), "launch_id": "different-launch"})
    elif mismatch == "workspace":
        other_workspace = (tmp_path / "other-workspace").resolve()
        other_workspace.mkdir()
        launch = SimpleNamespace(**{**vars(launch), "workspace": other_workspace})
    else:
        lease = SimpleNamespace(
            session_id=session.session_id,
            workspace=session.workspace,
        )

    lookups = 0

    def should_not_lookup(_pid):
        nonlocal lookups
        lookups += 1
        raise AssertionError("invalid binding must not reach process lookup")

    manager = ProcessManager(
        registry,
        _LeaseManager(original_lease),
        process_factory=should_not_lookup,
    )
    result = manager.execute(
        gate,
        session=session,
        launch_context=launch,
        workspace_lease=lease,
    )
    assert result.outcome is ProcessTerminationOutcome.REFUSED
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED
    assert lookups == 0


@dataclass
class _FakeProcess:
    pid: int
    created: float
    parent_process: "_FakeProcess | None" = None
    fail_termination: bool = False
    calls: list[str] | None = None
    alive: bool = True
    children_processes: list["_FakeProcess"] | None = None
    parent_exits_on_termination: bool = False
    gone_on_create_time_call: int | None = None
    create_time_calls: int = 0

    def __post_init__(self):
        if self.calls is None:
            self.calls = []
        if self.children_processes is None:
            self.children_processes = []

    def create_time(self):
        self.create_time_calls += 1
        if (
            self.gone_on_create_time_call is not None
            and self.create_time_calls >= self.gone_on_create_time_call
        ):
            self.alive = False
        if not self.alive:
            raise psutil.NoSuchProcess(self.pid)
        return self.created

    def parent(self):
        return self.parent_process

    def children(self, recursive=False):
        if not self.alive:
            raise psutil.NoSuchProcess(self.pid)
        direct = [child for child in self.children_processes if child.alive]
        if not recursive:
            return direct
        result = []
        for child in direct:
            result.append(child)
            result.extend(child.children(recursive=True))
        return result

    def terminate(self):
        self.calls.append(f"terminate:{self.pid}")
        if not self.fail_termination:
            self.alive = False
            if self.parent_exits_on_termination and self.parent_process is not None:
                self.parent_process.alive = False

    def kill(self):
        self.calls.append(f"kill:{self.pid}")
        if not self.fail_termination:
            self.alive = False


def _fake_tree(*, failing_child: bool = False):
    calls: list[str] = []
    root = _FakeProcess(1000, 1, calls=calls)
    child = _FakeProcess(1001, 1, parent_process=root, calls=calls)
    grandchild = _FakeProcess(1002, 1, parent_process=child, calls=calls)
    unrelated = _FakeProcess(2000, 1, calls=calls)
    child.fail_termination = failing_child
    root.children_processes = [child]
    child.children_processes = [grandchild]
    processes = {item.pid: item for item in (root, child, grandchild, unrelated)}
    return root, child, grandchild, unrelated, processes, calls


def test_children_first_tree_termination_excludes_unrelated_process(tmp_path: Path):
    root, child, grandchild, unrelated, processes, calls = _fake_tree()
    identity = ProcessIdentity(root.pid, root.created)
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=processes.__getitem__,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=processes.__getitem__,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    result = manager.execute(
        gate,
        session=session,
        launch_context=launch,
        workspace_lease=lease,
    )
    assert result.outcome is ProcessTerminationOutcome.TERMINATED
    assert result.action is EnforcementAction.TERMINATED
    assert result.execution_result is EnforcementExecutionResult.SUCCEEDED
    assert result.termination_attempt_count == 3
    assert calls[:3] == ["terminate:1002", "terminate:1001", "terminate:1000"]
    assert unrelated.alive
    assert all(
        entry.final_verification is not ProcessIdentityStatus.LIVE_MATCH
        for entry in result.entries
    )
    mapping = result.to_mapping()
    assert mapping["decision"] == "CONTAIN"
    assert mapping["action"] == "TERMINATED"
    assert mapping["execution_result"] == "SUCCEEDED"
    assert {
        item["process_identity"]["pid"] for item in mapping["process_results"]
    } == {1000, 1001, 1002}


def test_root_exit_during_descendant_containment_is_success(tmp_path: Path):
    root, child, grandchild, unrelated, processes, calls = _fake_tree()
    child.parent_exits_on_termination = True
    identity = ProcessIdentity(root.pid, root.created)
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=processes.__getitem__,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=processes.__getitem__,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )

    result = manager.execute(
        gate,
        session=session,
        launch_context=launch,
        workspace_lease=lease,
    )

    assert result.outcome is ProcessTerminationOutcome.TERMINATED
    assert result.action is EnforcementAction.TERMINATED
    assert result.execution_result is EnforcementExecutionResult.SUCCEEDED
    assert result.termination_attempt_count == 2
    assert calls == ["terminate:1002", "terminate:1001"]
    root_entry = next(entry for entry in result.entries if entry.process_role == "ROOT")
    assert root_entry.outcome is ProcessTerminationOutcome.EXITED_DURING_CONTAINMENT
    assert root_entry.final_verification is ProcessIdentityStatus.PROCESS_GONE
    assert unrelated.alive


def test_root_exit_without_intervention_is_not_attempted(tmp_path: Path):
    root, child, grandchild, unrelated, processes, calls = _fake_tree()
    root.gone_on_create_time_call = 2
    identity = ProcessIdentity(root.pid, root.created)
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=processes.__getitem__,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=processes.__getitem__,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )

    result = manager.execute(
        gate,
        session=session,
        launch_context=launch,
        workspace_lease=lease,
    )

    assert result.outcome is ProcessTerminationOutcome.ALREADY_EXITED
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED
    assert result.termination_attempt_count == 0
    assert calls == []
    assert child.alive
    assert grandchild.alive
    assert unrelated.alive


def test_partial_tree_failure_does_not_claim_termination(tmp_path: Path):
    root, child, grandchild, unrelated, processes, calls = _fake_tree(failing_child=True)
    # The failing child is the direct child.  Its grandchild can still be
    # terminated, while the root and the failing child demonstrate PARTIAL.
    identity = ProcessIdentity(root.pid, root.created)
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=processes.__getitem__,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=processes.__getitem__,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    result = manager.execute(gate, session=session, launch_context=launch, workspace_lease=lease)
    assert result.outcome is ProcessTerminationOutcome.PARTIAL
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.FAILED
    assert any(entry.process_identity.pid == child.pid and entry.outcome is ProcessTerminationOutcome.FAILED for entry in result.entries)
    assert unrelated.alive


def test_pid_reuse_refuses_without_termination_api(tmp_path: Path):
    identity = ProcessIdentity(5000, 1)
    reused = _FakeProcess(5000, 2)
    calls: list[str] = []
    reused.calls = calls
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=lambda _pid: reused,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=lambda _pid: reused,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    result = manager.execute(gate, session=session, launch_context=launch, workspace_lease=lease)
    assert result.outcome is ProcessTerminationOutcome.IDENTITY_REUSED
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED
    assert calls == []


def test_root_already_gone_is_not_attempted(tmp_path: Path):
    identity = ProcessIdentity(5001, 1)

    def gone(_pid):
        raise psutil.NoSuchProcess(_pid)

    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=gone,
    )
    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=gone,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    result = manager.execute(gate, session=session, launch_context=launch, workspace_lease=lease)
    assert result.outcome is ProcessTerminationOutcome.ALREADY_EXITED
    assert result.action is EnforcementAction.NONE
    assert result.execution_result is EnforcementExecutionResult.NOT_ATTEMPTED
    assert result.entries[0].terminate_result is TerminationAttemptResult.NOT_ATTEMPTED


def test_replay_returns_same_result_without_new_lookup(tmp_path: Path):
    root, child, grandchild, unrelated, processes, calls = _fake_tree()
    identity = ProcessIdentity(root.pid, root.created)
    session, launch, lease, gate, registry, _ = _environment(
        tmp_path,
        identity,
        process_factory=processes.__getitem__,
    )
    lookups = 0

    def counting_factory(pid):
        nonlocal lookups
        lookups += 1
        return processes[pid]

    manager = ProcessManager(
        registry,
        _LeaseManager(lease),
        process_factory=counting_factory,
        terminate_wait_seconds=0,
        force_kill_wait_seconds=0,
        sleeper=lambda _: None,
    )
    first = manager.execute(gate, session=session, launch_context=launch, workspace_lease=lease)
    before_replay = lookups
    second = manager.execute(gate, session=session, launch_context=launch, workspace_lease=lease)
    assert first is second
    assert lookups == before_replay


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows test-runner Job Object may terminate the protected root with descendants",
)
def test_real_root_child_grandchild_termination(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    grandchild_script = workspace / "grandchild.py"
    child_script = workspace / "child.py"
    root_script = workspace / "root.py"
    grandchild_script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
    child_script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1]])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    root_script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    unrelated = subprocess.Popen([sys.executable, str(grandchild_script)], cwd=workspace)
    root_process = subprocess.Popen(
        [sys.executable, str(root_script), str(child_script), str(grandchild_script)],
        cwd=workspace,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if len(psutil.Process(root_process.pid).children(recursive=True)) >= 2:
                    break
            except psutil.Error:
                pass
            time.sleep(0.05)
        root = psutil.Process(root_process.pid)
        identity = ProcessIdentity(root.pid, root.create_time())
        session, launch, lease, gate, registry, _ = _environment(tmp_path, identity)
        manager = ProcessManager(
            registry,
            _LeaseManager(lease),
            terminate_wait_seconds=0.5,
            force_kill_wait_seconds=0.5,
        )
        result = manager.execute(
            gate,
            session=session,
            launch_context=launch,
            workspace_lease=lease,
        )
        assert result.outcome is ProcessTerminationOutcome.TERMINATED
        assert result.action is EnforcementAction.TERMINATED
        assert result.execution_result is EnforcementExecutionResult.SUCCEEDED
        assert unrelated.poll() is None
        assert len([entry for entry in result.entries if entry.process_role == "DESCENDANT"]) >= 2
    finally:
        for process in (root_process, unrelated):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
