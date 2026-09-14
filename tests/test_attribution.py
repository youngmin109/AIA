from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aia import (
    ActionTargetKind,
    AttributionEngine,
    AttributionGrade,
    AttributionReason,
    CompetingCandidate,
    EvidenceRecordType,
    EvidenceSource,
    Normalizer,
    ObservationStage,
    Operation,
    ProcessIdentity,
    RawEvidenceRecord,
    TurnWindow,
)


SESSION = "session-1"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


def raw(
    record_type: EvidenceRecordType,
    payload: dict,
    *,
    evidence_id: str,
    captured_at: datetime = BASE_TIME,
    session_id: str = SESSION,
) -> RawEvidenceRecord:
    sources = {
        EvidenceRecordType.PRETOOL_REQUEST: EvidenceSource.AGENT_HOOK,
        EvidenceRecordType.COMMAND_OBSERVED: EvidenceSource.AGENT_HOOK,
        EvidenceRecordType.FILESYSTEM_EVENT: EvidenceSource.FILESYSTEM_WATCHER,
        EvidenceRecordType.PROCESS_OBSERVED: EvidenceSource.PROCESS_RUNTIME,
        EvidenceRecordType.PROCESS_EXIT_OBSERVED: EvidenceSource.PROCESS_RUNTIME,
    }
    stages = {
        EvidenceRecordType.PRETOOL_REQUEST: ObservationStage.PRE_ACTION,
        EvidenceRecordType.COMMAND_OBSERVED: ObservationStage.PRE_ACTION,
        EvidenceRecordType.FILESYSTEM_EVENT: ObservationStage.POST_ACTION,
        EvidenceRecordType.PROCESS_OBSERVED: ObservationStage.POST_ACTION,
        EvidenceRecordType.PROCESS_EXIT_OBSERVED: ObservationStage.POST_ACTION,
    }
    return RawEvidenceRecord(
        session_id=session_id,
        source=sources[record_type],
        record_type=record_type,
        captured_at=captured_at,
        observation_stage=stages[record_type],
        payload=payload,
        evidence_id=evidence_id,
    )


def pretool(
    *,
    evidence_id: str = "P1",
    tool_use_id: str = "T1",
    path: str = ".env",
    ingress_verified: bool = False,
    ingress_status: str | None = None,
    native_id: str | None = "native-1",
    turn_id: str | None = "turn-1",
    captured_at: datetime = BASE_TIME,
) -> RawEvidenceRecord:
    payload = {
        "aia_session_id": SESSION,
        "agent": "codex",
        "tool_use_id": tool_use_id,
        "tool_name": "read_file",
        "tool_input": {"path": path},
        "command_observed": False,
        "ingress_verified": ingress_verified,
        "ingress_status": ingress_status or ("VERIFIED" if ingress_verified else "UNVERIFIED"),
    }
    if native_id is not None:
        payload["agent_native_session_id"] = native_id
    if turn_id is not None:
        payload["turn_id"] = turn_id
    return raw(
        EvidenceRecordType.PRETOOL_REQUEST,
        payload,
        evidence_id=evidence_id,
        captured_at=captured_at,
    )


def command(
    *,
    evidence_id: str = "C1",
    parent_evidence_id: str = "P1",
    tool_use_id: str = "T1",
    raw_command: str = "python reset_db.py",
    ingress_verified: bool = False,
    captured_at: datetime = BASE_TIME + timedelta(milliseconds=1),
) -> RawEvidenceRecord:
    return raw(
        EvidenceRecordType.COMMAND_OBSERVED,
        {
            "parent_evidence_id": parent_evidence_id,
            "tool_use_id": tool_use_id,
            "raw_command": raw_command,
            "ingress_verified": ingress_verified,
            "ingress_status": "VERIFIED" if ingress_verified else "UNVERIFIED",
            "agent_native_session_id": "native-1",
            "turn_id": "turn-1",
        },
        evidence_id=evidence_id,
        captured_at=captured_at,
    )


def filesystem(
    workspace_path: Path,
    *,
    evidence_id: str = "F1",
    path: str = "file.txt",
    captured_at: datetime = BASE_TIME,
    session_id: str = SESSION,
) -> RawEvidenceRecord:
    return raw(
        EvidenceRecordType.FILESYSTEM_EVENT,
        {
            "event_type": "deleted",
            "src_path": str(workspace_path / path),
            "dest_path": None,
            "is_directory": False,
        },
        evidence_id=evidence_id,
        captured_at=captured_at,
        session_id=session_id,
    )


def process(
    *,
    evidence_id: str,
    pid: int,
    create_time: float,
    role: str,
    captured_at: datetime,
    root_pid: int = 101,
    root_create_time: float = 10.5,
    parent_pid: int | None = None,
    parent_create_time: float | None = None,
) -> RawEvidenceRecord:
    payload = {
        "pid": pid,
        "create_time": create_time,
        "root_pid": root_pid,
        "root_create_time": root_create_time,
        "process_role": role,
        "metadata_status": "COMPLETE",
        "name": "python.exe",
        "executable": r"C:\Python\python.exe",
    }
    if parent_pid is not None:
        payload["parent_pid"] = parent_pid
        payload["parent_create_time"] = parent_create_time
    return raw(
        EvidenceRecordType.PROCESS_OBSERVED,
        payload,
        evidence_id=evidence_id,
        captured_at=captured_at,
    )


def process_exit(
    *,
    evidence_id: str,
    pid: int,
    create_time: float,
    captured_at: datetime,
) -> RawEvidenceRecord:
    return raw(
        EvidenceRecordType.PROCESS_EXIT_OBSERVED,
        {
            "pid": pid,
            "create_time": create_time,
            "root_pid": 101,
            "root_create_time": 10.5,
            "process_role": "ROOT",
        },
        evidence_id=evidence_id,
        captured_at=captured_at,
    )


def normalized(records: list[RawEvidenceRecord], workspace_path: Path):
    return Normalizer(SESSION, workspace_path).normalize(records)


def test_attribution_domain_has_four_grades_and_result_is_separate(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    hook = pretool()
    action = normalized([hook], workspace_path).actions[0]
    result = AttributionEngine(SESSION, [hook]).attribute(action)

    assert set(AttributionGrade) == {
        AttributionGrade.EXACT,
        AttributionGrade.PROCESS,
        AttributionGrade.TEMPORAL,
        AttributionGrade.UNKNOWN,
    }
    assert result.grade is AttributionGrade.UNKNOWN
    assert not hasattr(result, "kill_authorized")
    assert not hasattr(result, "policy_decision")
    with pytest.raises(AttributeError):
        result.grade = AttributionGrade.EXACT


def test_trusted_file_hook_is_exact_and_preserves_preact_action(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    hook = pretool(ingress_verified=True)
    action = normalized([hook], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [hook],
        expected_agent_native_session_id="native-1",
    ).attribute(action)

    assert result.grade is AttributionGrade.EXACT
    assert result.reason_code is AttributionReason.DIRECT_TRUSTED_HOOK
    assert result.tool_use_id == "T1"
    assert result.turn_id == "turn-1"
    assert result.agent_native_session_id == "native-1"
    assert result.supporting_evidence_ids == ("P1",)
    assert action.stage is ObservationStage.PRE_ACTION
    assert action.operation is Operation.READ


def test_trusted_command_hook_is_exact_only_for_valid_parent_child_lineage(
    tmp_path: Path,
) -> None:
    workspace_path = workspace(tmp_path)
    parent = pretool(ingress_verified=True)
    child = command(ingress_verified=True)
    action = normalized([parent, child], workspace_path).actions[0]
    result = AttributionEngine(SESSION, [parent, child]).attribute(action)

    assert result.grade is AttributionGrade.EXACT
    assert result.reason_code is AttributionReason.DIRECT_TRUSTED_HOOK
    assert result.supporting_evidence_ids == ("P1", "C1")
    assert action.stage is ObservationStage.PRE_ACTION
    assert action.raw_command == "python reset_db.py"


def test_unverified_hook_stays_unknown_even_with_process_or_turn_overlap(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    hook = pretool(ingress_verified=False)
    process_record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    action = normalized([hook], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [hook, process_record],
        root_process_identity=ProcessIdentity(101, 10.5),
        turn_windows=[
            TurnWindow(
                "turn-1",
                SESSION,
                BASE_TIME - timedelta(seconds=1),
                BASE_TIME + timedelta(seconds=1),
            )
        ],
    ).attribute(action)

    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.HOOK_INGRESS_UNVERIFIED


def test_same_tool_id_identical_replay_is_allowed_but_count_is_retained(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    first = pretool(evidence_id="P1", ingress_verified=True)
    replay = pretool(evidence_id="P2", ingress_verified=True)
    action = normalized([first], workspace_path).actions[0]
    result = AttributionEngine(SESSION, [first, replay]).attribute(action)

    assert result.grade is AttributionGrade.EXACT
    assert result.duplicate_evidence_count == 2


def test_same_tool_id_different_target_is_unknown_for_all_replays(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    first = pretool(evidence_id="P1", path="a.txt", ingress_verified=True)
    conflict = pretool(evidence_id="P2", path="b.txt", ingress_verified=True)
    actions = normalized([first, conflict], workspace_path).actions
    results = AttributionEngine(SESSION, [first, conflict]).attribute_batch(actions)

    assert results.unknown_count == 2
    assert all(
        result.reason_code is AttributionReason.CONFLICTING_TOOL_IDENTIFIER
        for result in results.results
    )


def test_same_tool_id_different_command_is_unknown(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    p1 = pretool(evidence_id="P1", ingress_verified=True)
    p2 = pretool(evidence_id="P2", ingress_verified=True)
    c1 = command(evidence_id="C1", parent_evidence_id="P1", ingress_verified=True, raw_command="echo one")
    c2 = command(evidence_id="C2", parent_evidence_id="P2", ingress_verified=True, raw_command="echo two")
    actions = normalized([p1, c1, p2, c2], workspace_path).actions
    results = AttributionEngine(SESSION, [p1, c1, p2, c2]).attribute_batch(actions)

    assert results.unknown_count == 2
    assert all(result.reason_code is AttributionReason.CONFLICTING_TOOL_IDENTIFIER for result in results.results)


def test_native_session_mismatch_blocks_exact(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    hook = pretool(ingress_verified=True, native_id="native-actual")
    action = normalized([hook], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [hook],
        expected_agent_native_session_id="native-expected",
    ).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.NATIVE_SESSION_MISMATCH


def test_verified_root_process_is_process_not_exact(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    action = normalized([record], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [record],
        root_process_identity=ProcessIdentity(101, 10.5),
    ).attribute(action)

    assert result.grade is AttributionGrade.PROCESS
    assert result.reason_code is AttributionReason.VERIFIED_AGENT_PROCESS
    assert result.process_identity == ProcessIdentity(101, 10.5)
    assert result.root_process_identity == ProcessIdentity(101, 10.5)


def test_verified_descendant_requires_root_chain_and_create_time(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    root = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    child = process(
        evidence_id="R2",
        pid=202,
        create_time=20.5,
        role="DESCENDANT",
        parent_pid=101,
        parent_create_time=10.5,
        captured_at=BASE_TIME + timedelta(seconds=1),
    )
    action = normalized([root, child], workspace_path).actions[1]
    result = AttributionEngine(
        SESSION,
        [root, child],
        root_process_identity=ProcessIdentity(101, 10.5),
    ).attribute(action)

    assert result.grade is AttributionGrade.PROCESS
    assert result.process_identity == ProcessIdentity(202, 20.5)


@pytest.mark.parametrize(
    "root_identity",
    [ProcessIdentity(101, 99.0), ProcessIdentity(999, 10.5)],
)
def test_process_root_mismatch_and_pid_reuse_are_unknown(
    tmp_path: Path,
    root_identity: ProcessIdentity,
) -> None:
    workspace_path = workspace(tmp_path)
    record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    action = normalized([record], workspace_path).actions[0]
    result = AttributionEngine(SESSION, [record], root_process_identity=root_identity).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.PROCESS_IDENTITY_MISMATCH


def test_pid_without_create_time_is_not_a_process_identity(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    payload = dict(record.payload)
    payload.pop("create_time")
    malformed = replace(record, payload=payload)
    action = normalized([malformed], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [malformed],
        root_process_identity=ProcessIdentity(101, 10.5),
    ).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.PROCESS_IDENTITY_MISMATCH


def test_filesystem_action_overlapping_verified_process_window_is_process_only(
    tmp_path: Path,
) -> None:
    workspace_path = workspace(tmp_path)
    process_record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    file_record = filesystem(
        workspace_path,
        evidence_id="F1",
        captured_at=BASE_TIME + timedelta(seconds=1),
    )
    actions = normalized([process_record, file_record], workspace_path).actions
    file_action = next(action for action in actions if action.target_kind is ActionTargetKind.FILE)
    result = AttributionEngine(
        SESSION,
        [process_record, file_record],
        root_process_identity=ProcessIdentity(101, 10.5),
    ).attribute(file_action)

    assert result.grade is AttributionGrade.PROCESS
    assert result.reason_code is AttributionReason.PROCESS_WINDOW_ASSOCIATION
    assert "PROCESS_TREE_ASSOCIATION_ONLY" in result.limitations
    assert result.process_identity == ProcessIdentity(101, 10.5)


def test_filesystem_before_process_and_after_exit_cannot_use_process_window(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    process_record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME + timedelta(seconds=2),
    )
    before = filesystem(workspace_path, evidence_id="F1", captured_at=BASE_TIME)
    after = filesystem(
        workspace_path,
        evidence_id="F2",
        captured_at=BASE_TIME + timedelta(seconds=4),
    )
    exit_record = process_exit(
        evidence_id="X1",
        pid=101,
        create_time=10.5,
        captured_at=BASE_TIME + timedelta(seconds=3),
    )
    actions = normalized([process_record, before, after, exit_record], workspace_path).actions
    engine = AttributionEngine(
        SESSION,
        [process_record, before, after, exit_record],
        root_process_identity=ProcessIdentity(101, 10.5),
    )
    file_actions = [action for action in actions if action.target_kind is ActionTargetKind.FILE]

    before_result = engine.attribute(file_actions[0])
    after_result = engine.attribute(file_actions[1])
    assert before_result.grade is AttributionGrade.UNKNOWN
    assert after_result.grade is AttributionGrade.UNKNOWN


def test_known_decoy_candidate_blocks_process_attribution(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    process_record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    file_record = filesystem(workspace_path, captured_at=BASE_TIME + timedelta(seconds=1))
    action = next(
        action
        for action in normalized([process_record, file_record], workspace_path).actions
        if action.target_kind is ActionTargetKind.FILE
    )
    decoy = CompetingCandidate(
        candidate_id="decoy-1",
        candidate_kind="UNRELATED_PROCESS",
        active_from=BASE_TIME,
        active_until=BASE_TIME + timedelta(seconds=2),
        reason="known decoy overlaps the target event",
        canonical_path="file.txt",
    )
    result = AttributionEngine(
        SESSION,
        [process_record, file_record],
        root_process_identity=ProcessIdentity(101, 10.5),
        competing_candidates=[decoy],
    ).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.COMPETING_CANDIDATE
    assert result.competing_candidates == (decoy,)


def test_explicit_turn_window_produces_temporal_only(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    file_record = filesystem(workspace_path, captured_at=BASE_TIME + timedelta(seconds=2))
    action = normalized([file_record], workspace_path).actions[0]
    window = TurnWindow(
        turn_id="turn-explicit",
        aia_session_id=SESSION,
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(seconds=3),
        evidence_ids=("TURN-E1",),
    )
    result = AttributionEngine(SESSION, [file_record], turn_windows=[window]).attribute(action)
    assert result.grade is AttributionGrade.TEMPORAL
    assert result.reason_code is AttributionReason.TURN_WINDOW_ASSOCIATION
    assert result.turn_id == "turn-explicit"
    assert result.supporting_evidence_ids == ("TURN-E1",)


def test_turn_window_outside_and_missing_window_do_not_create_temporal(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    file_record = filesystem(workspace_path, captured_at=BASE_TIME + timedelta(seconds=5))
    action = normalized([file_record], workspace_path).actions[0]
    window = TurnWindow(
        "turn-explicit",
        SESSION,
        BASE_TIME,
        BASE_TIME + timedelta(seconds=3),
    )
    result = AttributionEngine(SESSION, [file_record], turn_windows=[window]).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.INSUFFICIENT_EVIDENCE


def test_overlapping_turns_are_ambiguous_unknown(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    file_record = filesystem(workspace_path, captured_at=BASE_TIME + timedelta(seconds=1))
    action = normalized([file_record], workspace_path).actions[0]
    windows = [
        TurnWindow("turn-1", SESSION, BASE_TIME, BASE_TIME + timedelta(seconds=2)),
        TurnWindow("turn-2", SESSION, BASE_TIME, BASE_TIME + timedelta(seconds=2)),
    ]
    result = AttributionEngine(SESSION, [file_record], turn_windows=windows).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.AMBIGUOUS_TURN_WINDOW


def test_session_mismatch_is_unknown_and_action_is_not_mutated(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    record = filesystem(workspace_path)
    action = normalized([record], workspace_path).actions[0]
    before = action
    result = AttributionEngine("other-session", [record]).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.SESSION_MISMATCH
    assert action == before


def test_stage_is_preserved_for_exact_and_process_results(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    hook = pretool(ingress_verified=True)
    hook_action = normalized([hook], workspace_path).actions[0]
    process_record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    process_action = normalized([process_record], workspace_path).actions[0]
    hook_result = AttributionEngine(SESSION, [hook]).attribute(hook_action)
    process_result = AttributionEngine(
        SESSION,
        [process_record],
        root_process_identity=ProcessIdentity(101, 10.5),
    ).attribute(process_action)
    assert hook_result.grade is AttributionGrade.EXACT
    assert process_result.grade is AttributionGrade.PROCESS
    assert hook_action.stage is ObservationStage.PRE_ACTION
    assert process_action.stage is ObservationStage.POST_ACTION


def test_batch_is_deterministic_and_keeps_other_results_when_one_is_unknown(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    trusted = pretool(evidence_id="P1", ingress_verified=True, captured_at=BASE_TIME)
    unknown = filesystem(workspace_path, evidence_id="F1", captured_at=BASE_TIME + timedelta(seconds=1))
    actions = normalized([unknown, trusted], workspace_path).actions
    engine = AttributionEngine(SESSION, [trusted, unknown])
    first = engine.attribute_batch(actions)
    second = engine.attribute_batch(tuple(reversed(actions)))
    assert first.results == second.results
    assert first.exact_count == 1
    assert first.unknown_count == 1
    assert [result.action_id for result in first.results] == [action.action_id for action in actions]


def test_root_provenance_mismatch_is_not_silently_accepted(tmp_path: Path) -> None:
    workspace_path = workspace(tmp_path)
    record = process(
        evidence_id="R1",
        pid=101,
        create_time=10.5,
        role="ROOT",
        captured_at=BASE_TIME,
    )
    action = normalized([record], workspace_path).actions[0]
    result = AttributionEngine(
        SESSION,
        [record],
        root_process_identity=ProcessIdentity(101, 10.5),
        root_process_provenance="UNTRUSTED_SOURCE",
    ).attribute(action)
    assert result.grade is AttributionGrade.UNKNOWN
    assert result.reason_code is AttributionReason.UNSUPPORTED_PROVENANCE
