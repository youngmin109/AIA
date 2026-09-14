from datetime import datetime, timezone

import pytest

from aia import (
    InvalidSessionTransition,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceValidationError,
)


def make_session(workspace, **overrides) -> ProtectedRunSession:
    values = {
        "workspace": workspace,
        "agent": "codex",
        "mode": SessionMode.AUDIT,
        "policy_id": "policy.default",
        "policy_version": "1.0",
    }
    values.update(overrides)
    return ProtectedRunSession(**values)


def test_session_creation_canonicalizes_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    session = make_session(workspace)

    assert session.status is SessionStatus.CREATED
    assert session.workspace == workspace.resolve()
    assert session.created_at.tzinfo is not None
    assert session.agent == "codex"
    assert session.policy_id == "policy.default"
    assert session.policy_version == "1.0"
    assert session.started_at is None


def test_each_session_gets_a_unique_aia_session_id(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    first = make_session(workspace)
    second = make_session(workspace)

    assert first.session_id != second.session_id


def test_workspace_path_is_canonicalized(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)

    session = make_session(nested / "..")

    assert session.workspace == workspace.resolve()
    assert session.workspace.is_absolute()


def test_missing_workspace_is_rejected(tmp_path) -> None:
    with pytest.raises(WorkspaceValidationError):
        make_session(tmp_path / "missing")


def test_file_path_is_rejected_as_workspace(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(WorkspaceValidationError):
        make_session(file_path)


def test_normal_state_transition_records_started_and_ended_at(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    started = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc)

    session.transition(SessionStatus.PREPARING, at=started)
    assert session.started_at == started
    session.transition(SessionStatus.READY)
    started_at_preparing = session.started_at
    session.transition(SessionStatus.RUNNING)
    assert session.started_at == started_at_preparing
    session.transition(SessionStatus.COMPLETED, at=ended)

    assert session.status is SessionStatus.COMPLETED
    assert session.started_at == started
    assert session.ended_at == ended
    assert session.is_terminal


def test_preparing_can_fail(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)

    session.transition(SessionStatus.PREPARING)
    session.transition(SessionStatus.FAILED)

    assert session.status is SessionStatus.FAILED
    assert session.ended_at is not None


def test_created_can_be_aborted_and_records_end_time(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    ended = datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc)

    session.transition(SessionStatus.ABORTED, at=ended)

    assert session.status is SessionStatus.ABORTED
    assert session.started_at is None
    assert session.ended_at == ended


def test_preparing_can_be_aborted_and_records_end_time(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    started = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 1, 1, 1, 5, tzinfo=timezone.utc)

    session.transition(SessionStatus.PREPARING, at=started)
    session.transition(SessionStatus.ABORTED, at=ended)

    assert session.started_at == started
    assert session.ended_at == ended


def test_started_at_is_unchanged_when_entering_ready_and_running(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    started = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)

    session.transition(SessionStatus.PREPARING, at=started)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)

    assert session.started_at == started


def test_invalid_state_transition_is_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)

    with pytest.raises(InvalidSessionTransition):
        session.transition(SessionStatus.READY)


def test_terminal_state_cannot_transition_again(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    session.transition(SessionStatus.PREPARING)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.ABORTED)

    with pytest.raises(InvalidSessionTransition):
        session.transition(SessionStatus.FAILED)


def test_started_at_is_timezone_aware_and_normalized_to_utc(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(workspace)
    started = datetime.fromisoformat("2026-01-01T10:00:00+09:00")

    session.transition(SessionStatus.PREPARING, at=started)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)

    assert session.started_at == datetime(
        2026,
        1,
        1,
        1,
        0,
        tzinfo=timezone.utc,
    )


def test_agent_native_session_id_is_optional(tmp_path) -> None:
    workspace = tmp_path / "workspace"

    workspace.mkdir()
    without_native = make_session(workspace)
    with_native = make_session(
        workspace,
        agent_native_session_id="codex-native-123",
    )

    assert without_native.agent_native_session_id is None
    assert with_native.agent_native_session_id == "codex-native-123"


def test_audit_and_enforce_modes_are_represented(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    audit = make_session(workspace, mode="AUDIT")
    enforce = make_session(workspace, mode="ENFORCE")

    assert audit.mode is SessionMode.AUDIT
    assert enforce.mode is SessionMode.ENFORCE
    assert "TERMINATED" not in SessionStatus.__members__
