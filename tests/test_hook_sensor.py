from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aia import (
    CheckpointValidity,
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    HookEvidenceStoreError,
    HookInputError,
    HookNotHealthyError,
    HookPayloadTooLargeError,
    HookSensor,
    ObservationStage,
    PolicyProfile,
    ProtectedRunSession,
    RawEvidenceRecord,
    RawEvidenceStore,
    SensorStartError,
    SensorStatus,
    SessionMode,
    SessionStatus,
    UnsupportedHookEventError,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
    validate_hook_input,
)


class FakeProcessIdentity:
    def __call__(self, pid: int) -> float:
        if pid != 101:
            raise ProcessLookupError(pid)
        return 10.5


class FailingEvidenceStore(RawEvidenceStore):
    def append(self, record):
        raise EvidenceStoreError("test store failure")


def prepared_hook_inputs(
    tmp_path: Path,
) -> tuple[Path, ProtectedRunSession, object, WorkspaceLeaseManager, object]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
    return workspace, session, context, lease_manager, checkpoint


def valid_payload(
    session: ProtectedRunSession,
    workspace: Path,
    **overrides,
) -> dict:
    payload = {
        "aia_session_id": session.session_id,
        "agent": "codex",
        "agent_native_session_id": "codex-native-1",
        "turn_id": "turn-1",
        "tool_use_id": "T100",
        "tool_name": "shell",
        "tool_input": {
            "command": "  Python reset_db.py  ",
            "cwd": str(workspace),
            "path": ".env",
            "target": ".env",
            "stdout": "do-not-store",
            "prompt": "do-not-store",
            "content": "do-not-store",
        },
        "hook_event_name": "PRE_TOOL_USE",
        "source_metadata": {
            "provider": "codex",
            "channel": "fixture",
            "secret": "do-not-store",
        },
    }
    payload.update(overrides)
    return payload


def release_lease(context, lease_manager: WorkspaceLeaseManager) -> None:
    try:
        lease_manager.release(context.workspace_lease)
    except Exception:
        pass


def make_sensor(
    tmp_path: Path,
    *,
    store: RawEvidenceStore | None = None,
) -> tuple[HookSensor, Path, ProtectedRunSession, object, WorkspaceLeaseManager]:
    workspace, session, context, lease_manager, checkpoint = prepared_hook_inputs(
        tmp_path
    )
    sensor = HookSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
        evidence_store=store,
    )
    return sensor, workspace, session, context, lease_manager


def test_valid_hook_input_preserves_correlation_and_filters_tool_input(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.AUDIT,
        policy_id="policy.default",
        policy_version="1.0",
    )
    request = validate_hook_input(
        valid_payload(session, workspace),
        expected_session_id=session.session_id,
        expected_agent=session.agent,
    )

    assert request.aia_session_id == session.session_id
    assert request.agent_native_session_id == "codex-native-1"
    assert request.turn_id == "turn-1"
    assert request.tool_use_id == "T100"
    assert request.tool_input["command"] == "  Python reset_db.py  "
    assert "stdout" not in request.tool_input
    assert "prompt" not in request.tool_input
    assert "content" not in request.tool_input
    assert request.source_metadata == {
        "provider": "codex",
        "channel": "fixture",
    }
    assert request.ingress_verified is False


@pytest.mark.parametrize(
    "payload",
    ["not-json", "[]", "null", b"{bad"],
)
def test_malformed_or_non_object_hook_payload_is_rejected(
    tmp_path: Path,
    payload,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.AUDIT,
        policy_id="policy.default",
        policy_version="1.0",
    )

    with pytest.raises(HookInputError):
        validate_hook_input(
            payload,
            expected_session_id=session.session_id,
            expected_agent=session.agent,
        )


def test_unknown_hook_key_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.AUDIT,
        policy_id="policy.default",
        policy_version="1.0",
    )
    payload = valid_payload(session, workspace)
    payload["tool_output"] = "secret"

    with pytest.raises(HookInputError):
        validate_hook_input(
            payload,
            expected_session_id=session.session_id,
            expected_agent=session.agent,
        )


def test_empty_ids_and_wrong_types_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.AUDIT,
        policy_id="policy.default",
        policy_version="1.0",
    )
    for field in ("tool_use_id", "tool_name"):
        payload = valid_payload(session, workspace)
        payload[field] = ""
        with pytest.raises(HookInputError):
            validate_hook_input(
                payload,
                expected_session_id=session.session_id,
                expected_agent=session.agent,
            )

    payload = valid_payload(session, workspace)
    payload["turn_id"] = 7
    with pytest.raises(HookInputError):
        validate_hook_input(
            payload,
            expected_session_id=session.session_id,
            expected_agent=session.agent,
        )


def test_unsupported_event_and_oversized_payload_are_explicit_errors(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.AUDIT,
        policy_id="policy.default",
        policy_version="1.0",
    )
    unsupported = valid_payload(session, workspace, hook_event_name="POST_TOOL_USE")
    with pytest.raises(UnsupportedHookEventError):
        validate_hook_input(
            unsupported,
            expected_session_id=session.session_id,
            expected_agent=session.agent,
        )

    with pytest.raises(HookPayloadTooLargeError):
        validate_hook_input(
            valid_payload(
                session,
                workspace,
                tool_input={"path": "x" * 100},
            ),
            expected_session_id=session.session_id,
            expected_agent=session.agent,
            max_payload_bytes=32,
        )


def test_hook_sensor_emits_pretool_and_command_records_to_same_stream(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.start()

    records = sensor.observe(valid_payload(session, workspace))

    assert len(records) == 2
    pretool, command = records
    assert pretool.session_id == session.session_id
    assert pretool.source is EvidenceSource.AGENT_HOOK
    assert pretool.record_type is EvidenceRecordType.PRETOOL_REQUEST
    assert pretool.observation_stage is ObservationStage.PRE_ACTION
    assert pretool.payload["tool_use_id"] == "T100"
    assert pretool.payload["tool_input"]["path"] == ".env"
    assert pretool.payload["ingress_verified"] is False
    assert pretool.payload["ingress_status"] == "UNVERIFIED"
    assert command.record_type is EvidenceRecordType.COMMAND_OBSERVED
    assert command.payload["raw_command"] == "  Python reset_db.py  "
    assert command.payload["cwd"] == str(workspace)
    assert command.payload["hook_evidence_id"] == pretool.evidence_id
    assert "DROP" not in command.payload
    assert len(sensor.evidence_store.records()) == 4
    sensor.stop()
    release_lease(context, lease_manager)


def test_hook_sensor_without_command_stores_only_pretool_request(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    payload = valid_payload(
        session,
        workspace,
        tool_name="read_file",
        tool_input={"path": ".env"},
    )

    records = sensor.observe(payload)

    assert len(records) == 1
    assert records[0].record_type is EvidenceRecordType.PRETOOL_REQUEST
    assert records[0].payload["tool_name"] == "read_file"
    assert records[0].payload["tool_input"] == {"path": ".env"}
    assert "operation" not in records[0].payload
    assert "READ" not in records[0].payload
    sensor.stop()
    release_lease(context, lease_manager)


def test_optional_native_session_and_turn_are_not_generated(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    payload = valid_payload(session, workspace)
    payload.pop("agent_native_session_id")
    payload.pop("turn_id")

    record = sensor.observe(payload)[0]

    assert "agent_native_session_id" not in record.payload
    assert "turn_id" not in record.payload
    sensor.stop()
    release_lease(context, lease_manager)


def test_duplicate_tool_use_id_events_are_preserved_without_dedup(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    payload = valid_payload(session, workspace)

    first = sensor.observe(payload)
    second = sensor.observe(payload)

    pretools = [
        record
        for record in sensor.evidence_store.records()
        if record.record_type is EvidenceRecordType.PRETOOL_REQUEST
    ]
    commands = [
        record
        for record in sensor.evidence_store.records()
        if record.record_type is EvidenceRecordType.COMMAND_OBSERVED
    ]
    assert len(pretools) == 2
    assert len(commands) == 2
    assert pretools[0].payload["tool_use_id"] == pretools[1].payload["tool_use_id"]
    assert first[0].evidence_id != second[0].evidence_id
    sensor.stop()
    release_lease(context, lease_manager)


def test_hook_health_uses_shared_sensor_domain_and_session_stays_preparing(
    tmp_path: Path,
) -> None:
    sensor, _, session, context, lease_manager = make_sensor(tmp_path)

    started = sensor.start()
    stopped = sensor.stop()

    assert started.status is SensorStatus.HEALTHY
    assert started.aia_session_id == session.session_id
    assert started.session_id == session.session_id
    assert started.ingress_verified is False
    assert stopped.status is SensorStatus.STOPPED
    assert session.status is SessionStatus.PREPARING
    health = [
        record
        for record in sensor.evidence_store.records()
        if record.record_type is EvidenceRecordType.SENSOR_HEALTH
    ]
    assert [record.payload["status"] for record in health] == [
        "STARTING",
        "HEALTHY",
        "STOPPED",
    ]
    assert all(record.source is EvidenceSource.AGENT_HOOK for record in health)
    release_lease(context, lease_manager)


def test_observe_before_start_is_rejected_without_evidence(tmp_path: Path) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)

    with pytest.raises(HookNotHealthyError):
        sensor.observe(valid_payload(session, workspace))

    assert sensor.evidence_store.records() == ()
    release_lease(context, lease_manager)


def test_hook_start_requires_preparing_valid_checkpoint_and_current_lease(
    tmp_path: Path,
) -> None:
    sensor, _, session, context, lease_manager = make_sensor(tmp_path)
    session.transition(SessionStatus.READY)

    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED
    release_lease(context, lease_manager)


def test_hook_start_rejects_invalid_checkpoint(tmp_path: Path) -> None:
    _, session, context, lease_manager, checkpoint = prepared_hook_inputs(tmp_path)
    sensor = HookSensor(
        session,
        context,
        replace(checkpoint, validity=CheckpointValidity.INVALID),
        lease_manager=lease_manager,
    )

    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED
    release_lease(context, lease_manager)


def test_hook_start_revalidates_lease_ownership(tmp_path: Path) -> None:
    sensor, _, _, context, lease_manager = make_sensor(tmp_path)
    lease_manager.release(context.workspace_lease)

    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED


def test_hook_store_failure_marks_sensor_failed(tmp_path: Path) -> None:
    _, session, context, lease_manager, checkpoint = prepared_hook_inputs(tmp_path)
    store = FailingEvidenceStore(
        context.control_directory / "evidence" / "raw-evidence.jsonl"
    )
    sensor = HookSensor(
        session,
        context,
        checkpoint,
        lease_manager=lease_manager,
        evidence_store=store,
    )

    with pytest.raises(SensorStartError):
        sensor.start()
    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "EVIDENCE_STORE_FAILURE"
    release_lease(context, lease_manager)


def test_hook_store_failure_during_observation_marks_sensor_failed(
    tmp_path: Path,
) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.start()
    sensor.evidence_store = FailingEvidenceStore(
        sensor.evidence_store.path,
        session_id=session.session_id,
    )

    with pytest.raises(HookEvidenceStoreError):
        sensor.observe(valid_payload(session, workspace))

    assert sensor.status is SensorStatus.FAILED
    assert sensor.health.reason == "EVIDENCE_STORE_FAILURE"
    release_lease(context, lease_manager)


def test_hook_and_filesystem_records_share_one_session_stream(tmp_path: Path) -> None:
    sensor, workspace, session, context, lease_manager = make_sensor(tmp_path)
    sensor.evidence_store.append(
        RawEvidenceRecord(
            session_id=session.session_id,
            source=EvidenceSource.FILESYSTEM_WATCHER,
            record_type=EvidenceRecordType.FILESYSTEM_EVENT,
            captured_at=datetime.now(timezone.utc),
            observation_stage=ObservationStage.POST_ACTION,
            payload={
                "event_type": "deleted",
                "src_path": str(workspace / "foo.txt"),
                "dest_path": None,
                "is_directory": False,
            },
        )
    )
    sensor.start()
    sensor.observe(valid_payload(session, workspace))

    sources = {
        record.source for record in sensor.evidence_store.records()
    }
    assert sources == {
        EvidenceSource.AGENT_HOOK,
        EvidenceSource.FILESYSTEM_WATCHER,
    }
    sensor.stop()
    release_lease(context, lease_manager)
