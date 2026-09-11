from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aia import (
    ActionTargetKind,
    EvidenceRecordType,
    EvidenceSource,
    HOOK_TOOL_SEMANTICS,
    NormalizationCompleteness,
    Normalizer,
    NormalizedAction,
    ObservationStage,
    Operation,
    ProcessIdentity,
    RawEvidenceRecord,
    canonicalize_workspace_path,
)


SESSION = "session-1"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def raw(
    record_type: EvidenceRecordType,
    payload: dict,
    *,
    evidence_id: str,
    session_id: str = SESSION,
    captured_at: datetime = BASE_TIME,
    stage: ObservationStage | None = None,
    source: EvidenceSource | None = None,
) -> RawEvidenceRecord:
    source_by_type = {
        EvidenceRecordType.FILESYSTEM_EVENT: EvidenceSource.FILESYSTEM_WATCHER,
        EvidenceRecordType.PRETOOL_REQUEST: EvidenceSource.AGENT_HOOK,
        EvidenceRecordType.COMMAND_OBSERVED: EvidenceSource.AGENT_HOOK,
        EvidenceRecordType.PROCESS_OBSERVED: EvidenceSource.PROCESS_RUNTIME,
        EvidenceRecordType.PROCESS_EXIT_OBSERVED: EvidenceSource.PROCESS_RUNTIME,
        EvidenceRecordType.SENSOR_HEALTH: EvidenceSource.PROCESS_RUNTIME,
    }
    stage_by_type = {
        EvidenceRecordType.FILESYSTEM_EVENT: ObservationStage.POST_ACTION,
        EvidenceRecordType.PRETOOL_REQUEST: ObservationStage.PRE_ACTION,
        EvidenceRecordType.COMMAND_OBSERVED: ObservationStage.PRE_ACTION,
        EvidenceRecordType.PROCESS_OBSERVED: ObservationStage.POST_ACTION,
        EvidenceRecordType.PROCESS_EXIT_OBSERVED: ObservationStage.POST_ACTION,
        EvidenceRecordType.SENSOR_HEALTH: ObservationStage.POST_ACTION,
    }
    return RawEvidenceRecord(
        session_id=session_id,
        source=source or source_by_type[record_type],
        record_type=record_type,
        captured_at=captured_at,
        observation_stage=stage or stage_by_type[record_type],
        payload=payload,
        evidence_id=evidence_id,
    )


def filesystem_payload(event_type: str, path: str, *, directory: bool = False) -> dict:
    return {
        "event_type": event_type,
        "src_path": path,
        "dest_path": None,
        "is_directory": directory,
    }


def pretool_payload(
    *,
    tool_name: str = "read_file",
    path: str | None = ".env",
    target: str | None = None,
    command_observed: bool = False,
) -> dict:
    tool_input: dict[str, object] = {}
    if path is not None:
        tool_input["path"] = path
    if target is not None:
        tool_input["target"] = target
    return {
        "agent": "codex",
        "aia_session_id": SESSION,
        "agent_native_session_id": "native-1",
        "turn_id": "turn-1",
        "tool_use_id": "T100",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "command_observed": command_observed,
    }


def command_payload(
    *,
    parent_evidence_id: str | None = "P1",
    tool_use_id: str = "T100",
    raw_command: str | None = "  Python reset_db.py; DROP TABLE users  ",
) -> dict:
    return {
        "parent_evidence_id": parent_evidence_id,
        "raw_command": raw_command,
        "tool_use_id": tool_use_id,
        "agent_native_session_id": "native-1",
        "turn_id": "turn-1",
        "ingress_status": "UNVERIFIED",
        "ingress_verified": False,
    }


def process_payload(*, metadata_status: str = "COMPLETE") -> dict:
    return {
        "pid": 101,
        "create_time": 10.5,
        "root_pid": 101,
        "root_create_time": 10.5,
        "process_role": "ROOT",
        "metadata_status": metadata_status,
        "name": "python.exe",
        "executable": r"C:\Python\python.exe",
    }


def test_operation_vocabulary_is_single_and_exact() -> None:
    assert tuple(operation.value for operation in Operation) == (
        "READ",
        "CREATE",
        "MODIFY",
        "DELETE",
        "MOVE",
        "RENAME",
        "EXECUTE",
    )
    assert set(HOOK_TOOL_SEMANTICS.values()) == {Operation.READ}


def test_normalized_action_is_immutable_and_versioned(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    action = Normalizer(SESSION, workspace).normalize(
        [raw(EvidenceRecordType.FILESYSTEM_EVENT, filesystem_payload("created", "a.txt"), evidence_id="E1")]
    ).actions[0]

    assert action.normalizer_version == "canonical-v1"
    with pytest.raises(AttributeError):
        action.operation = Operation.DELETE


def test_same_evidence_is_deterministic_and_different_evidence_is_not() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        workspace = Path(directory)
        record = raw(
            EvidenceRecordType.FILESYSTEM_EVENT,
            filesystem_payload("created", "a.txt"),
            evidence_id="E1",
        )
        normalizer = Normalizer(SESSION, workspace)
        first = normalizer.normalize([record]).actions[0]
        second = normalizer.normalize([record]).actions[0]
        different = normalizer.normalize(
            [
                raw(
                    EvidenceRecordType.FILESYSTEM_EVENT,
                    filesystem_payload("created", "a.txt"),
                    evidence_id="E2",
                )
            ]
        ).actions[0]
        assert first == second
        assert first.action_id == second.action_id
        assert first.action_id != different.action_id


@pytest.mark.parametrize(
    ("raw_path", "expected"),
    [
        (r"src\Config.py", "src/config.py"),
        (r".\src\\..\src\config.py", "src/config.py"),
        (r"src\\nested\\file.txt", "src/nested/file.txt"),
    ],
)
def test_path_canonicalization_is_lexical_and_case_insensitive(
    tmp_path: Path,
    raw_path: str,
    expected: str,
) -> None:
    workspace = make_workspace(tmp_path)
    result = canonicalize_workspace_path(raw_path, workspace)
    assert result.canonical_path == expected
    assert result.limitation is None


def test_absolute_workspace_path_is_relative_without_filesystem_resolution(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    raw_path = str(workspace / "link" / "secret.txt")
    result = canonicalize_workspace_path(raw_path, workspace)
    assert result.canonical_path == "link/secret.txt"


@pytest.mark.parametrize("raw_path", [r"..\outside.txt", r"C:\other\secret.txt"])
def test_path_escape_and_other_volume_are_marked_outside_workspace(
    tmp_path: Path,
    raw_path: str,
) -> None:
    workspace = make_workspace(tmp_path)
    result = canonicalize_workspace_path(raw_path, workspace)
    assert result.canonical_path is None
    assert result.limitation == "OUTSIDE_WORKSPACE"


def test_filesystem_mapping_and_directory_flag(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    records = [
        raw(
            EvidenceRecordType.FILESYSTEM_EVENT,
            filesystem_payload(event, f"{event}.txt", directory=event == "created"),
            evidence_id=f"E-{event}",
            captured_at=BASE_TIME + timedelta(seconds=index),
        )
        for index, event in enumerate(("created", "modified", "deleted"))
    ]
    result = Normalizer(SESSION, workspace).normalize(records)

    assert [action.operation for action in result.actions] == [
        Operation.CREATE,
        Operation.MODIFY,
        Operation.DELETE,
    ]
    assert all(action.stage is ObservationStage.POST_ACTION for action in result.actions)
    assert result.actions[0].target_kind is ActionTargetKind.DIRECTORY
    assert all(action.target_kind is ActionTargetKind.FILE for action in result.actions[1:])
    assert all(action.operation is not Operation.READ for action in result.actions)


def test_move_and_rename_preserve_both_paths(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    same_parent = raw(
        EvidenceRecordType.FILESYSTEM_EVENT,
        {
            "event_type": "moved",
            "src_path": r"C:\project\a\Foo.txt",
            "dest_path": r"C:\project\a\foo.txt",
            "is_directory": False,
        },
        evidence_id="E1",
    )
    cross_parent = raw(
        EvidenceRecordType.FILESYSTEM_EVENT,
        {
            "event_type": "moved",
            "src_path": r"C:\project\a\foo.txt",
            "dest_path": r"C:\project\b\foo.txt",
            "is_directory": False,
        },
        evidence_id="E2",
    )
    # Use the actual workspace spelling in absolute test paths.
    same_parent = RawEvidenceRecord(
        session_id=SESSION,
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.FILESYSTEM_EVENT,
        captured_at=BASE_TIME,
        observation_stage=ObservationStage.POST_ACTION,
        payload={
            "event_type": "moved",
            "src_path": str(workspace / "a" / "Foo.txt"),
            "dest_path": str(workspace / "a" / "foo.txt"),
            "is_directory": False,
        },
        evidence_id="E1",
    )
    cross_parent = RawEvidenceRecord(
        session_id=SESSION,
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.FILESYSTEM_EVENT,
        captured_at=BASE_TIME + timedelta(seconds=1),
        observation_stage=ObservationStage.POST_ACTION,
        payload={
            "event_type": "moved",
            "src_path": str(workspace / "a" / "foo.txt"),
            "dest_path": str(workspace / "b" / "foo.txt"),
            "is_directory": False,
        },
        evidence_id="E2",
    )
    actions = Normalizer(SESSION, workspace).normalize([same_parent, cross_parent]).actions

    assert actions[0].operation is Operation.RENAME
    assert actions[0].source_path == "a/foo.txt"
    assert actions[0].destination_path == "a/foo.txt"
    assert actions[1].operation is Operation.MOVE
    assert actions[1].source_path == "a/foo.txt"
    assert actions[1].destination_path == "b/foo.txt"


def test_outside_filesystem_path_is_retained_as_partial_with_limitation(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.FILESYSTEM_EVENT,
                filesystem_payload("deleted", r"C:\outside\secret.txt"),
                evidence_id="E1",
            )
        ]
    )
    action = result.actions[0]
    assert action.canonical_path is None
    assert action.completeness is NormalizationCompleteness.PARTIAL
    assert "OUTSIDE_WORKSPACE" in action.limitations
    assert result.issues[0].code == "PATH_OUTSIDE_OR_INVALID"


def test_command_maps_to_one_pre_action_execute_with_lineage_and_no_semantic_inference(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    parent = raw(
        EvidenceRecordType.PRETOOL_REQUEST,
        pretool_payload(tool_name="shell", command_observed=True),
        evidence_id="P1",
    )
    command = raw(
        EvidenceRecordType.COMMAND_OBSERVED,
        command_payload(),
        evidence_id="C1",
        captured_at=BASE_TIME + timedelta(seconds=1),
    )
    result = Normalizer(SESSION, workspace).normalize([parent, command])

    assert len(result.actions) == 1
    action = result.actions[0]
    assert action.operation is Operation.EXECUTE
    assert action.target_kind is ActionTargetKind.COMMAND
    assert action.stage is ObservationStage.PRE_ACTION
    assert action.evidence_ids == ("P1", "C1")
    assert action.raw_command == "  Python reset_db.py; DROP TABLE users  "
    assert action.normalized_command == "python reset_db.py; drop table users"
    assert action.completeness is NormalizationCompleteness.COMPLETE
    assert "DROP_TABLE" not in {operation.value for operation in Operation}
    assert result.non_action_count == 0


def test_pretool_command_parent_does_not_create_duplicate_execute_action(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    parent = raw(
        EvidenceRecordType.PRETOOL_REQUEST,
        pretool_payload(tool_name="shell", command_observed=True),
        evidence_id="P1",
    )
    child = raw(
        EvidenceRecordType.COMMAND_OBSERVED,
        command_payload(),
        evidence_id="C1",
        captured_at=BASE_TIME + timedelta(seconds=1),
    )
    result = Normalizer(SESSION, workspace).normalize([parent, child])
    assert result.normalized_action_count == 1
    assert all(action.evidence_ids[-1] == "C1" for action in result.actions)


def test_command_parent_is_verified_and_duplicate_tool_ids_do_not_merge(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    p1 = raw(EvidenceRecordType.PRETOOL_REQUEST, pretool_payload(command_observed=True), evidence_id="P1")
    p2 = raw(EvidenceRecordType.PRETOOL_REQUEST, pretool_payload(command_observed=True), evidence_id="P2", captured_at=BASE_TIME + timedelta(seconds=1))
    c1 = raw(EvidenceRecordType.COMMAND_OBSERVED, command_payload(parent_evidence_id="P1"), evidence_id="C1", captured_at=BASE_TIME + timedelta(seconds=2))
    c2 = raw(EvidenceRecordType.COMMAND_OBSERVED, command_payload(parent_evidence_id="P2"), evidence_id="C2", captured_at=BASE_TIME + timedelta(seconds=3))
    result = Normalizer(SESSION, workspace).normalize([p2, c2, p1, c1])
    assert [action.evidence_ids for action in result.actions] == [("P1", "C1"), ("P2", "C2")]
    assert all(action.completeness is NormalizationCompleteness.COMPLETE for action in result.actions)


def test_command_missing_parent_is_partial_and_not_claimed_as_verified(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.COMMAND_OBSERVED,
                command_payload(parent_evidence_id="missing"),
                evidence_id="C1",
            )
        ]
    )
    action = result.actions[0]
    assert action.completeness is NormalizationCompleteness.PARTIAL
    assert action.evidence_ids == ("C1",)
    assert "COMMAND_PARENT_UNVERIFIED" in action.limitations


@pytest.mark.parametrize(
    "tool_name",
    ["read_file"],
)
def test_hook_read_file_is_explicit_file_action_and_native_context_is_preserved(
    tmp_path: Path,
    tool_name: str,
) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.PRETOOL_REQUEST,
                pretool_payload(tool_name=tool_name, path=".env"),
                evidence_id="P1",
            )
        ]
    )
    action = result.actions[0]
    assert action.operation is Operation.READ
    assert action.canonical_path == ".env"
    assert action.stage is ObservationStage.PRE_ACTION
    assert action.agent_native_session_id == "native-1"
    assert action.turn_id == "turn-1"
    assert action.tool_use_id == "T100"


@pytest.mark.parametrize("tool_name", ["inspect_secret", "read_file_backup", "cleanup"])
def test_unknown_or_fuzzy_hook_tool_has_no_inferred_operation(tmp_path: Path, tool_name: str) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.PRETOOL_REQUEST,
                pretool_payload(tool_name=tool_name),
                evidence_id="P1",
            )
        ]
    )
    assert result.actions == ()
    assert result.issues[0].code == "UNSUPPORTED_TOOL_SEMANTICS"


def test_hook_missing_and_conflicting_target_are_explicit_limitations(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    missing = raw(
        EvidenceRecordType.PRETOOL_REQUEST,
        pretool_payload(path=None),
        evidence_id="P1",
    )
    conflicting = raw(
        EvidenceRecordType.PRETOOL_REQUEST,
        pretool_payload(path="a.txt", target="b.txt"),
        evidence_id="P2",
        captured_at=BASE_TIME + timedelta(seconds=1),
    )
    result = Normalizer(SESSION, workspace).normalize([missing, conflicting])
    assert result.actions[0].completeness is NormalizationCompleteness.PARTIAL
    assert "PATH_MISSING" in result.actions[0].limitations
    assert result.actions[1].completeness is NormalizationCompleteness.UNUSABLE
    assert "CONFLICTING_PATH_TARGET" in result.actions[1].limitations


def test_process_observation_is_process_execute_and_does_not_become_file_writer(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.PROCESS_OBSERVED,
                process_payload(),
                evidence_id="R1",
            )
        ]
    )
    action = result.actions[0]
    assert action.operation is Operation.EXECUTE
    assert action.target_kind is ActionTargetKind.PROCESS
    assert action.process_identity == ProcessIdentity(101, 10.5)
    assert action.root_process_identity == ProcessIdentity(101, 10.5)
    assert action.raw_command is None
    assert action.process_executable == r"C:\Python\python.exe"
    assert action.completeness is NormalizationCompleteness.COMPLETE


def test_process_command_line_is_normalized_as_lexical_execute_evidence(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    payload = process_payload()
    payload["raw_command"] = r'python "AIA_PROCESS_CANARY.py" --flag'
    action = Normalizer(SESSION, workspace).normalize(
        [raw(EvidenceRecordType.PROCESS_OBSERVED, payload, evidence_id="R1")]
    ).actions[0]
    assert action.target_kind is ActionTargetKind.PROCESS
    assert action.raw_command == r'python "AIA_PROCESS_CANARY.py" --flag'
    assert action.normalized_command == r'python "aia_process_canary.py" --flag'


def test_partial_process_metadata_is_partial(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    action = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.PROCESS_OBSERVED,
                process_payload(metadata_status="PARTIAL"),
                evidence_id="R1",
            )
        ]
    ).actions[0]
    assert action.completeness is NormalizationCompleteness.PARTIAL
    assert "PROCESS_METADATA_PARTIAL" in action.limitations


def test_process_exit_and_sensor_health_are_non_action_evidence(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(EvidenceRecordType.PROCESS_EXIT_OBSERVED, {}, evidence_id="X1"),
            raw(EvidenceRecordType.SENSOR_HEALTH, {"status": "HEALTHY"}, evidence_id="H1", source=EvidenceSource.FILESYSTEM_WATCHER),
        ]
    )
    assert result.actions == ()
    assert result.non_action_count == 2
    assert {item.reason for item in result.non_action_evidence} == {
        "NON_ACTION_LIFECYCLE_EVIDENCE",
        "NON_ACTION_SENSOR_EVIDENCE",
    }


def test_session_mismatch_does_not_become_current_session_action(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(
                EvidenceRecordType.FILESYSTEM_EVENT,
                filesystem_payload("created", "foreign.txt"),
                evidence_id="F1",
                session_id="other-session",
            )
        ]
    )
    assert result.actions == ()
    assert result.issues[0].code == "SESSION_MISMATCH"


def test_malformed_event_does_not_drop_other_valid_record(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = Normalizer(SESSION, workspace).normalize(
        [
            raw(EvidenceRecordType.FILESYSTEM_EVENT, {"event_type": "opened", "src_path": "x"}, evidence_id="BAD"),
            raw(EvidenceRecordType.FILESYSTEM_EVENT, filesystem_payload("created", "good.txt"), evidence_id="GOOD", captured_at=BASE_TIME + timedelta(seconds=1)),
        ]
    )
    assert result.normalized_action_count == 1
    assert result.actions[0].evidence_ids == ("GOOD",)
    assert result.issues[0].code == "UNSUPPORTED_FILESYSTEM_EVENT"


def test_raw_evidence_is_not_modified_and_payload_is_not_copied_wholesale(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    payload = filesystem_payload("created", "src\\a.txt")
    original = dict(payload)
    record = raw(EvidenceRecordType.FILESYSTEM_EVENT, payload, evidence_id="E1")
    action = Normalizer(SESSION, workspace).normalize([record]).actions[0]
    assert dict(record.payload) == original
    assert action.evidence_ids == ("E1",)
    assert not hasattr(action, "payload")


def test_mixed_sources_remain_separate_and_batch_order_is_deterministic(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    records = [
        raw(EvidenceRecordType.PROCESS_OBSERVED, process_payload(), evidence_id="R1", captured_at=BASE_TIME + timedelta(seconds=2)),
        raw(EvidenceRecordType.FILESYSTEM_EVENT, filesystem_payload("modified", "a.txt"), evidence_id="F1", captured_at=BASE_TIME),
        raw(EvidenceRecordType.PRETOOL_REQUEST, pretool_payload(), evidence_id="P1", captured_at=BASE_TIME + timedelta(seconds=1)),
    ]
    first = Normalizer(SESSION, workspace).normalize(records)
    second = Normalizer(SESSION, workspace).normalize(tuple(reversed(records)))
    assert [action.evidence_ids for action in first.actions] == [("F1",), ("P1",), ("R1",)]
    assert first.actions == second.actions
    assert {action.target_kind for action in first.actions} == {
        ActionTargetKind.FILE,
        ActionTargetKind.PROCESS,
    }
    assert first.total_input_records == 3
    assert first.normalized_action_count == 3
    assert first.partial_count == 0
    assert first.unusable_count == 0
