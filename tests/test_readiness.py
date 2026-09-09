from datetime import datetime, timezone
from pathlib import Path

import pytest
import aia.readiness as readiness_module
from aia import (
    CheckpointValidity,
    FilesystemSensor,
    HookSensor,
    PolicyProfile,
    ProcessObserverCapability,
    ProtectedRunSession,
    ProtectionReadinessBarrier,
    ReadinessStatus,
    SessionMode,
    SessionStatus,
    SensorStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)


class FakeProcessIdentity:
    def __call__(self, pid: int) -> float:
        if pid != 101:
            raise ProcessLookupError(pid)
        return 10.5


class FakeObserver:
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


@pytest.fixture
def readiness_inputs(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "baseline.txt").write_text("baseline", encoding="utf-8")
    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=resolved.policy_id,
        policy_version=resolved.policy_version,
    )
    session.transition(
        SessionStatus.PREPARING,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    lease_manager = WorkspaceLeaseManager(
        tmp_path / "control",
        process_identity_provider=FakeProcessIdentity(),
    )
    context = prepare_protection(
        session,
        resolved,
        tmp_path / "control",
        lease_manager=lease_manager,
        owner_pid=101,
        owner_process_create_time=10.5,
    )
    checkpoint = create_safe_checkpoint(
        session,
        context,
        lease_manager=lease_manager,
        created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )
    filesystem = FilesystemSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
        observer_factory=FakeObserver,
    )
    hook = HookSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
    )
    filesystem.start()
    hook.start()
    capability = ProcessObserverCapability(
        aia_session_id=session.session_id,
        workspace=workspace,
    )
    yield {
        "workspace": workspace,
        "session": session,
        "context": context,
        "checkpoint": checkpoint,
        "lease_manager": lease_manager,
        "filesystem": filesystem,
        "hook": hook,
        "capability": capability,
    }
    if hook.status is not SensorStatus.STOPPED:
        hook.stop()
    if filesystem.status is not SensorStatus.STOPPED:
        filesystem.stop()


def make_barrier(values: dict) -> ProtectionReadinessBarrier:
    return ProtectionReadinessBarrier(
        values["session"],
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        values["capability"],
        lease_manager=values["lease_manager"],
    )


def test_readiness_success_transitions_once_and_preserves_hook_trust(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    barrier = make_barrier(values)

    result = barrier.evaluate()

    assert result.status is ReadinessStatus.READY
    assert values["session"].status is SessionStatus.READY
    assert result.hook_ingress_verified is False
    assert result.readiness_context is not None
    assert result.checkpoint_content_sha256 == result.current_workspace_content_sha256
    assert result.active_policy_fingerprint != result.checkpoint_content_sha256
    assert result.process_observer_capability_status == "AVAILABLE"
    assert barrier.evaluate() is result


def test_readiness_failure_keeps_preparing_and_can_be_retried(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    (values["workspace"] / "created-after-checkpoint.txt").write_text(
        "drift", encoding="utf-8"
    )
    barrier = make_barrier(values)

    failed = barrier.evaluate()

    assert failed.status is ReadinessStatus.NOT_READY
    assert values["session"].status is SessionStatus.PREPARING
    assert any(
        check.reason == "WORKSPACE_DRIFTED_AFTER_CHECKPOINT"
        for check in failed.checks
    )
    (values["workspace"] / "created-after-checkpoint.txt").unlink()

    retried = barrier.evaluate()

    assert retried.status is ReadinessStatus.READY
    assert values["session"].status is SessionStatus.READY


def test_readiness_revalidates_active_policy_artifact(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    values["context"].active_policy.artifact_path.unlink()

    result = make_barrier(values).evaluate()

    assert result.status is ReadinessStatus.NOT_READY
    assert values["session"].status is SessionStatus.PREPARING
    assert any(
        check.reason == "ACTIVE_POLICY_INVALID" for check in result.checks
    )


def test_readiness_uses_live_sensor_status_and_sequence(
    readiness_inputs: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = readiness_inputs
    values["filesystem"].stop()
    result = make_barrier(values).evaluate()
    assert result.status is ReadinessStatus.NOT_READY
    assert values["session"].status is SessionStatus.PREPARING
    assert any(
        check.reason == "FILESYSTEM_SENSOR_UNHEALTHY" for check in result.checks
    )

    values["filesystem"].start()
    original_compare = readiness_module.compare_workspace_to_checkpoint

    def compare_and_change(checkpoint, workspace):
        values["filesystem"]._observation_sequence += 1
        return original_compare(checkpoint, workspace)

    monkeypatch.setattr(
        readiness_module,
        "compare_workspace_to_checkpoint",
        compare_and_change,
    )
    result = make_barrier(values).evaluate()

    assert result.status is ReadinessStatus.NOT_READY
    assert any(
        check.reason == "WORKSPACE_CHANGED_DURING_READINESS"
        for check in result.checks
    )


def test_unsupported_checkpoint_baseline_is_not_accepted(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    checkpoint_values = {
        field: getattr(values["checkpoint"], field)
        for field in values["checkpoint"].__dataclass_fields__
    }
    checkpoint_values["validity"] = CheckpointValidity.INVALID
    values["checkpoint"] = type(values["checkpoint"])(**checkpoint_values)
    result = make_barrier(values).evaluate()

    assert result.status is ReadinessStatus.NOT_READY
    assert values["session"].status is SessionStatus.PREPARING


def test_created_session_cannot_become_ready(readiness_inputs: dict) -> None:
    values = readiness_inputs
    created = ProtectedRunSession(
        workspace=values["workspace"],
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=values["session"].policy_id,
        policy_version=values["session"].policy_version,
    )
    values["session"] = created

    result = make_barrier(values).evaluate()

    assert result.status is ReadinessStatus.NOT_READY
    assert created.status is SessionStatus.CREATED
