from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from aia.evidence import (
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)
from aia_app.dto import CreateRunRequest, DTOValidationError, PolicyPreviewRequest
from aia_app.presenters import (
    action_view,
    action_summary,
    evidence_chain_views,
    incident_view,
    incident_views_for_result,
    result_action_chain_views,
    result_view,
    recovery_status_view,
    safe_event_views,
    evidence_timeline_views,
)
from aia_app.readers import ResultBundleReader
from aia_app.registry import RunRecord, RunRegistry
from aia import (
    ActionTargetKind,
    AttributionGrade,
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementRoute,
    Operation,
    PolicyDecision,
    ProcessIdentity,
    ProcessIdentityStatus,
    SessionStatus,
    CodexHookInstaller,
)
from aia_app.service import (
    ApplicationValidationError,
    _aia_cli_prefix,
    RunApplicationService,
    _sensor_summary_is_verified,
    _event_tool_name,
    _product_sensor_set_present,
    _sensors_runtime_healthy,
)
import aia_app.service as service_module


def make_record(tmp_path, session_id: str = "session-1") -> RunRecord:
    return RunRecord(
        session_id=session_id,
        workspace=tmp_path,
        agent="codex",
        model=None,
        policy_profile="BASIC_DEVELOPMENT",
        policy_id="basic-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="inspect",
        created_at=datetime.now(timezone.utc),
    )


def capture_service_launcher_factory(
    service, record, monkeypatch, output_handles=None
):
    captured = {}

    class FakeLauncher:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)
            self.managed_process_registry = object()
            self.process_sensor = None

    class InstalledHooks:
        def is_installed(self):
            return True

    monkeypatch.setattr(service_module, "CodexHookInstaller", InstalledHooks)
    monkeypatch.setattr(
        service_module,
        "CodexPreToolController",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(service_module, "ProtectedLauncher", FakeLauncher)
    monkeypatch.setattr(service_module, "ProcessManager", lambda *_args: object())
    launcher, _controller, options = service._create_protected_launcher(
        record,
        SimpleNamespace(session_id=record.session_id, workspace=record.workspace),
        SimpleNamespace(control_directory=record.workspace),
        object(),
        object(),
        object(),
        object(),
        SimpleNamespace(readiness_context=object()),
        output_handles if output_handles is not None else [],
    )
    return launcher, captured, options


def test_create_request_rejects_unknown_fields_and_bounds_task() -> None:
    with pytest.raises(DTOValidationError, match="unknown request fields"):
        CreateRunRequest.from_mapping({"workspace": ".", "unexpected": True})
    with pytest.raises(DTOValidationError, match="too large"):
        CreateRunRequest.from_mapping({"workspace": ".", "task": "x" * 50_001})


def test_create_request_normalizes_mode_and_preserves_explicit_profile() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "mode": "audit", "policy_profile": "CONSERVATIVE_SECURITY"}
    )
    assert request.mode == "AUDIT"
    assert request.policy_profile == "CONSERVATIVE_SECURITY"


def test_create_request_can_explicitly_open_interactive_session() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "interactive": True}
    )

    assert request.interactive is True
    assert request.task == ""


def test_create_request_accepts_protected_paths_and_normalizes_to_tuple() -> None:
    request = CreateRunRequest.from_mapping(
        {
            "workspace": ".",
            "protected_paths": [".env", "data/customers.db"],
        }
    )

    assert request.protected_paths == (".env", "data/customers.db")
    assert request.to_mapping()["protected_paths"] == [".env", "data/customers.db"]


def test_create_request_rejects_invalid_protected_paths() -> None:
    with pytest.raises(DTOValidationError, match="protected_paths"):
        CreateRunRequest.from_mapping({"workspace": ".", "protected_paths": ".env"})
    with pytest.raises(DTOValidationError, match="protected_paths"):
        CreateRunRequest.from_mapping({"workspace": ".", "protected_paths": [""]})


def test_create_request_supports_separate_windows_terminal_only_for_interactive() -> None:
    request = CreateRunRequest.from_mapping(
        {"workspace": ".", "interactive": True, "launch_mode": "new_terminal"}
    )
    assert request.launch_mode == "new_terminal"
    with pytest.raises(DTOValidationError, match="requires interactive"):
        CreateRunRequest.from_mapping(
            {"workspace": ".", "task": "inspect", "launch_mode": "new_terminal"}
        )


def test_create_request_rejects_retired_workbench_terminal() -> None:
    with pytest.raises(DTOValidationError, match="launch_mode must be"):
        CreateRunRequest.from_mapping(
            {"workspace": ".", "interactive": True, "launch_mode": "web_terminal"}
        )


def test_new_terminal_launch_maps_to_windows_create_new_console(monkeypatch) -> None:
    monkeypatch.setattr(service_module.os, "name", "nt")
    options = service_module._popen_kwargs_for_launch_mode("new_terminal")
    assert options["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    assert service_module._popen_kwargs_for_launch_mode("inherit") == {}


def test_safe_event_view_never_copies_command_or_secret() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "VIOLATION",
                "enforcement_action": "BLOCKED",
                "execution_result": "SUCCEEDED",
                "target": {
                    "target_kind": "COMMAND",
                    "raw_command": "type SUPER_SECRET",
                },
            }
        ]
    )
    assert events[0]["target_label"] == "명령 실행"
    assert events[0]["chain_action_id"] == "a1"
    assert events[0]["tool_name"] is None
    assert "SUPER_SECRET" not in repr(events)
    assert "type SUPER_SECRET" not in repr(events)


def test_safe_event_view_does_not_treat_observation_stage_as_hook_sensor() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "observation_stage": "POST_ACTION",
                "evidence_ids": ["process-1"],
                "target": {"target_kind": "PROCESS"},
            }
        ],
        evidence_metadata=[
            {
                "evidence_id": "process-1",
                "source": "PROCESS_RUNTIME",
                "record_type": "PROCESS_OBSERVED",
            }
        ],
    )

    assert events[0]["sensor"] == "PROCESS_RUNTIME"
    assert events[0]["event_origin"] == "PROCESS_OBSERVATION"
    assert events[0]["origin_label"] == "프로세스 관찰"
    assert events[0]["display_summary"] == "프로세스 실행 관찰"
    assert events[0]["display_target_label"] == "프로세스"
    assert events[0]["display_decision"] == "OBSERVED"


def test_safe_event_view_labels_filesystem_observation_separately_from_hook_request() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "DELETE",
                "evidence_ids": ["file-1"],
                "target": {"target_kind": "FILE"},
            },
            {
                "action_id": "a2",
                "operation": "MODIFY",
                "sensor": "AGENT_HOOK",
                "target": {"target_kind": "FILE"},
            },
        ],
        evidence_metadata=[
            {
                "evidence_id": "file-1",
                "source": "FILESYSTEM_WATCHER",
                "record_type": "FILESYSTEM_EVENT",
            }
        ],
    )

    assert events[0]["event_origin"] == "FILESYSTEM_OBSERVATION"
    assert events[0]["display_summary"] == "파일 삭제 관찰"
    assert events[0]["display_target_label"] == "파일 변화"
    assert events[0]["display_decision"] == "OBSERVED"
    assert events[1]["event_origin"] == "HOOK_REQUEST"
    assert events[1]["display_summary"] == "수정 요청"
    assert events[1]["origin_label"] == "Hook 요청"
    assert events[1]["display_decision"] == "OBSERVED"


def test_safe_event_view_uses_runtime_when_sensor_evidence_is_not_linked() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "observation_stage": "POST_ACTION",
                "target": {"target_kind": "COMMAND"},
            }
        ]
    )

    assert events[0]["sensor"] == "RUNTIME"


def test_safe_event_view_keeps_only_allowlisted_tool_labels() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "tool_name": "Bash",
                "target": {"target_kind": "COMMAND", "raw_command": "echo SECRET"},
            },
            {
                "action_id": "a2",
                "operation": "EXECUTE",
                "tool_name": "mcp__unknown__write_file",
                "target": {"target_kind": "COMMAND"},
            },
        ]
    )

    assert events[0]["tool_name"] == "Bash"
    assert events[1]["tool_name"] is None
    assert "SECRET" not in repr(events)


def test_event_tool_name_reads_allowlisted_hook_evidence_only() -> None:
    assert _event_tool_name(
        SimpleNamespace(records=(SimpleNamespace(payload={"tool_name": "Bash"}),))
    ) == "Bash"
    assert _event_tool_name(
        SimpleNamespace(records=(SimpleNamespace(payload={"tool_name": "mcp__unknown"}),))
    ) is None
    assert _event_tool_name(None) is None


def test_evidence_chain_links_sensor_metadata_without_copying_payload() -> None:
    chains = evidence_chain_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "VIOLATION",
                "matched_rule_ids": ["deny-dangerous-command"],
                "matched_asset_types": ["CRITICAL_CODE"],
                "attribution_grade": "EXACT",
                "enforcement_decision": "CONTAIN",
                "enforcement_action": "BLOCKED",
                "execution_result": "SUCCEEDED",
                "evidence_ids": ["hook-1", "file-1", "process-1"],
                "target": {
                    "target_kind": "COMMAND",
                    "raw_command": "type SUPER_SECRET",
                },
            }
        ],
        evidence_metadata=[
            {
                "evidence_id": "hook-1",
                "source": "AGENT_HOOK",
                "record_type": "PRETOOL_REQUEST",
                "captured_at": "2026-09-15T05:00:00+00:00",
            },
            {
                "evidence_id": "file-1",
                "source": "FILESYSTEM_WATCHER",
                "record_type": "FILESYSTEM_EVENT",
                "captured_at": "2026-09-15T05:00:01+00:00",
            },
            {
                "evidence_id": "process-1",
                "source": "PROCESS_RUNTIME",
                "record_type": "PROCESS_OBSERVED",
                "captured_at": "2026-09-15T05:00:02+00:00",
            },
        ],
        recovery={"recovery_status": "RESTORED"},
        integrity={"integrity_status": "VERIFIED"},
    )

    assert len(chains) == 1
    chain = chains[0]
    assert chain["evidence_link_status"] == "LINKED"
    assert chain["linked_evidence_count"] == 3
    assert {
        item["sensor"]: item["evidence_count"]
        for item in chain["sensor_links"]
    } == {
        "AGENT_HOOK": 1,
        "FILESYSTEM_WATCHER": 1,
        "PROCESS_RUNTIME": 1,
    }
    assert [stage["stage"] for stage in chain["stages"]] == [
        "RAW_EVIDENCE",
        "CANONICAL_ACTION",
        "POLICY",
        "ATTRIBUTION",
        "ENFORCEMENT",
        "RECOVERY",
        "INTEGRITY",
    ]
    assert chain["stages"][2]["asset_types"] == ["CRITICAL_CODE"]
    assert chain["stages"][5]["status"] == "RESTORED"
    assert chain["stages"][6]["status"] == "VERIFIED"
    assert "SUPER_SECRET" not in repr(chains)


def test_evidence_chain_marks_missing_sensor_link_as_partial() -> None:
    chains = evidence_chain_views(
        [{"action_id": "a1", "operation": "MODIFY", "evidence_ids": ["known", "missing"]}],
        evidence_metadata=[{"evidence_id": "known", "source": "AGENT_HOOK"}],
    )

    assert chains[0]["evidence_link_status"] == "PARTIAL"
    assert chains[0]["linked_evidence_count"] == 1
    assert chains[0]["stages"][0]["evidence_count"] == 2


def test_evidence_chain_distinguishes_run_observed_sensor_from_action_link() -> None:
    chains = evidence_chain_views(
        [{"action_id": "a1", "operation": "EXECUTE", "evidence_ids": ["h1"]}],
        evidence_metadata=[
            {"evidence_id": "h1", "source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"},
            {"evidence_id": "f1", "source": "FILESYSTEM_WATCHER", "record_type": "FILESYSTEM_EVENT"},
            {"evidence_id": "p1", "source": "PROCESS_RUNTIME", "record_type": "PROCESS_OBSERVED"},
            {"evidence_id": "health", "source": "PROCESS_RUNTIME", "record_type": "SENSOR_HEALTH"},
        ],
    )

    links = {item["sensor"]: item for item in chains[0]["sensor_links"]}
    assert links["AGENT_HOOK"]["status"] == "LINKED"
    assert links["FILESYSTEM_WATCHER"]["status"] == "RUN_OBSERVED"
    assert links["FILESYSTEM_WATCHER"]["run_evidence_count"] == 1
    assert links["PROCESS_RUNTIME"]["status"] == "RUN_OBSERVED"
    assert links["PROCESS_RUNTIME"]["run_evidence_count"] == 1


def test_attribution_supporting_evidence_can_link_process_sensor() -> None:
    chains = evidence_chain_views(
        [{"action_id": "a1", "operation": "MODIFY", "evidence_ids": ["h1"]}],
        evidence_metadata=[
            {"evidence_id": "h1", "source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"},
            {"evidence_id": "p1", "source": "PROCESS_RUNTIME", "record_type": "PROCESS_OBSERVED"},
        ],
        attribution_results=[
            {"action_id": "a1", "supporting_evidence_ids": ["h1", "p1"]},
        ],
    )

    links = {item["sensor"]: item for item in chains[0]["sensor_links"]}
    assert links["PROCESS_RUNTIME"]["status"] == "LINKED"
    assert chains[0]["linked_evidence_count"] == 2


def test_evidence_timeline_links_sensor_records_to_action_without_payload() -> None:
    timeline = evidence_timeline_views(
        [
            {
                "evidence_id": "h1",
                "captured_at": "2026-09-15T05:00:00+00:00",
                "line": 1,
                "source": "AGENT_HOOK",
                "record_type": "PRETOOL_REQUEST",
                "payload_keys": ["raw_command", "secret"],
            },
            {
                "evidence_id": "f1",
                "captured_at": "2026-09-15T05:00:01+00:00",
                "line": 2,
                "source": "FILESYSTEM_WATCHER",
                "record_type": "FILESYSTEM_EVENT",
            },
        ],
        actions=[
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "evidence_ids": ["h1"],
                "target": {"target_kind": "COMMAND", "raw_command": "type SECRET"},
            }
        ],
    )

    assert timeline[0]["linked_action_id"] == "a1"
    assert timeline[0]["link_status"] == "LINKED"
    assert timeline[1]["link_status"] == "UNLINKED"
    assert "SECRET" not in repr(timeline)


def test_evidence_timeline_bounded_selection_matches_stable_full_sort() -> None:
    metadata = [
        {"evidence_id": "early", "captured_at": "2026-01-01", "line": 10, "payload": "SECRET"},
        {"evidence_id": "tie-first", "captured_at": "2026-01-02", "line": "bad", "payload": "SECRET"},
        {"evidence_id": "invalid", "captured_at": "2026-01-03", "line": 99, "payload": "SECRET"},
        None,
        {"evidence_id": "tie-second", "captured_at": "2026-01-02", "line": None, "payload": "SECRET"},
        {"evidence_id": "latest", "captured_at": "2026-01-04", "line": "2", "payload": "SECRET"},
        {"evidence_id": "tie-third", "captured_at": "2026-01-02", "line": 0, "payload": "SECRET"},
    ]
    valid_metadata = [item for item in metadata if isinstance(item, dict) and item.get("evidence_id")]

    def line_number(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    legacy_order = sorted(
        valid_metadata,
        key=lambda item: (str(item.get("captured_at") or ""), line_number(item.get("line"))),
    )
    expected_ids = [item["evidence_id"] for item in legacy_order[-4:]]
    full_sort_equivalent = evidence_timeline_views(metadata, limit=len(valid_metadata))
    bounded = evidence_timeline_views(metadata, limit=4)

    assert [item["evidence_id"] for item in bounded] == expected_ids
    assert bounded == full_sort_equivalent[-4:]
    assert "SECRET" not in repr(bounded)


@pytest.mark.parametrize("limit", [0, -1])
def test_evidence_timeline_nonpositive_limit_returns_empty(limit: int) -> None:
    assert evidence_timeline_views([{"evidence_id": "e1", "payload": "SECRET"}], limit=limit) == []


def test_safe_event_view_preserves_containment_decision_before_block_confirmation() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "VIOLATION",
                "enforcement_action": "NONE",
                "enforcement_decision": "CONTAIN",
                "enforcement_route": "PRETOOL_BLOCK",
                "execution_result": "NOT_ATTEMPTED",
                "target": {"target_kind": "COMMAND"},
            }
        ]
    )

    assert events[0]["category"] == "ENFORCEMENT"
    assert events[0]["decision"] == "CONTAIN"
    assert events[0]["execution_result"] == "NOT_ATTEMPTED"


def test_safe_event_view_exposes_observation_time_for_live_timeline() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "COMPLIANT",
                "execution_result": "SUCCEEDED",
                "observed_at": "2026-09-15T05:00:00+00:00",
                "target": {"target_kind": "COMMAND"},
            }
        ]
    )

    assert events[0]["observed_at"] == "2026-09-15T05:00:00+00:00"


def test_safe_event_view_exposes_posttool_execution_observation() -> None:
    events = safe_event_views(
        [
            {
                "action_id": "a1",
                "operation": "EXECUTE",
                "policy_decision": "COMPLIANT",
                "execution_result": "NOT_ATTEMPTED",
                "execution_observed": True,
                "target": {"target_kind": "COMMAND"},
            }
        ]
    )

    assert events[0]["execution_result"] == "NOT_ATTEMPTED"
    assert events[0]["execution_observed"] is True


def test_result_view_reconnects_pretool_action_to_posttool_evidence(tmp_path) -> None:
    session_id = "session-posttool"
    store = RawEvidenceStore.for_session(tmp_path / "control", session_id)
    captured_at = datetime.now(timezone.utc)
    pretool = store.append(
        RawEvidenceRecord(
            session_id=session_id,
            source=EvidenceSource.AGENT_HOOK,
            record_type=EvidenceRecordType.PRETOOL_REQUEST,
            captured_at=captured_at,
            observation_stage=ObservationStage.PRE_ACTION,
            payload={"tool_use_id": "tool-1"},
            evidence_id="pretool-1",
        )
    )
    store.append(
        RawEvidenceRecord(
            session_id=session_id,
            source=EvidenceSource.AGENT_HOOK,
            record_type=EvidenceRecordType.POSTTOOL_OBSERVED,
            captured_at=captured_at,
            observation_stage=ObservationStage.POST_ACTION,
            payload={"tool_use_id": "tool-1"},
            evidence_id="posttool-1",
        )
    )
    view = {"actions": [{"evidence_ids": [pretool.evidence_id]}]}

    service_module._annotate_execution_observations(
        view,
        control_root=tmp_path / "control",
        session_id=session_id,
    )

    assert view["actions"][0]["execution_observed"] is True
    assert view["events"][0]["execution_observed"] is True


def test_policy_editor_document_is_strictly_validated_and_can_be_saved(tmp_path) -> None:
    document = {
        "정책명": "사용자 보호 정책",
        "정책ID": "user-policy",
        "정책버전": "1.0",
        "스키마버전": "1",
        "기본효과": "기록",
        "규칙": [
            {
                "규칙ID": "deny-env-read",
                "우선순위": 100,
                "자산유형": "비밀정보",
                "경로패턴": [".env"],
                "행위효과": {"읽기": "금지"},
            }
        ],
    }
    summary = RunApplicationService.validate_policy_document(document)
    assert summary["rule_count"] == 1
    saved = RunApplicationService.save_policy_document(
        {"document": document, "path": str(tmp_path / "user-policy.json")}
    )
    assert saved["path"].endswith("user-policy.json")
    assert (tmp_path / "user-policy.json").is_file()


def test_workspace_protected_paths_create_high_priority_deny_policy(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    protected = workspace / ".env"
    protected.write_text("SECRET=redacted\n", encoding="utf-8")
    monkeypatch.setattr(service_module.Path, "home", staticmethod(lambda: tmp_path / "home"))

    path = RunApplicationService._workspace_policy_path(
        workspace,
        "PROTECTED_DEVELOPMENT",
        (str(protected),),
    )

    assert path is not None
    document = json.loads(path.read_text(encoding="utf-8"))
    selected = next(rule for rule in document["rules"] if rule["rule_id"] == "aia-user-protected-path-1")
    assert selected["path_patterns"] == [".env"]
    assert selected["asset_type"] == "WORKSPACE"
    assert selected["operation_effects"]["DELETE"] == "DENY"
    assert RunApplicationService.validate_policy_document(document)["rule_count"] >= 1


def test_policy_preview_request_validates_target_shape_and_unknown_fields() -> None:
    request = PolicyPreviewRequest.from_mapping(
        {"operation": "read", "path": ".env"}
    )
    assert request.operation == "READ"
    assert request.path == ".env"
    assert request.policy_profile == "PROTECTED_DEVELOPMENT"

    with pytest.raises(DTOValidationError, match="unknown request fields"):
        PolicyPreviewRequest.from_mapping(
            {"operation": "READ", "path": ".env", "asset_type": "WORKSPACE"}
        )
    with pytest.raises(DTOValidationError, match="accepts path"):
        PolicyPreviewRequest.from_mapping(
            {"operation": "READ", "path": ".env", "command": "type .env"}
        )
    with pytest.raises(DTOValidationError, match="requires command"):
        PolicyPreviewRequest.from_mapping({"operation": "EXECUTE"})


def test_registry_snapshot_excludes_runtime_and_isolated_lists(tmp_path) -> None:
    registry = RunRegistry()
    record = make_record(tmp_path)
    record.runtime["secret"] = "internal"
    record.actions.append({"action_id": "a1"})
    registry.add(record)
    snapshot = registry.snapshot(record.session_id)
    assert snapshot is not None
    assert snapshot.runtime == {}
    snapshot.actions.append({"action_id": "a2"})
    assert registry.require(record.session_id).actions == [{"action_id": "a1"}]


def test_registry_snapshots_exclude_runtime(tmp_path) -> None:
    registry = RunRegistry()
    record = make_record(tmp_path)
    record.runtime["secret"] = "internal"
    registry.add(record)

    snapshots = registry.snapshots()

    assert len(snapshots) == 1
    assert snapshots[0].runtime == {}


def test_application_lists_live_runs_without_runtime_contents(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["secret"] = "do-not-expose"
    service.registry.add(record)
    try:
        runs = service.list_runs()
        assert runs[0]["session_id"] == record.session_id
        assert "do-not-expose" not in repr(runs)
        assert runs[0]["protection_state"] == "STARTING"
    finally:
        service.shutdown()


def test_live_status_exposes_only_filesystem_evidence_counts(tmp_path) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    record = make_record(tmp_path)
    record.status = "RUNNING"
    service.registry.add(record)
    evidence_path = (
        control_root
        / "sessions"
        / record.session_id
        / "evidence"
        / "raw-evidence.jsonl"
    )
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "source": "FILESYSTEM_WATCHER",
                "record_type": "FILESYSTEM_EVENT",
                "payload": {"src_path": "C:/private.txt"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        status = service.get_run_status(record.session_id)
        assert status["evidence_summary"]["filesystem_events"] == 1
        assert status["bundle_status"] == "PENDING"
        assert "C:/private.txt" not in repr(status)
    finally:
        service.shutdown()


def test_application_does_not_present_unverified_runtime_as_committed_run(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        service._write_runtime_state_payload(
            "stale-session",
            {
                "schema_version": 1,
                "session_id": "stale-session",
                "session": {
                    "session_id": "stale-session",
                    "status": "COMPLETED",
                    "workspace": str(tmp_path / "workspace"),
                    "agent": "codex",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "protection": {"state": "COMPLETED_DEGRADED", "hook_events": 0},
                "policy": {"id": "basic", "version": "1.0"},
                "result_available": True,
                "result_path": str(tmp_path / "control" / "missing" / "result.json"),
            },
        )

        runs = service.list_runs()

        assert runs[0]["run_classification"] == "UNVERIFIED_RUNTIME_STATE"
        assert runs[0]["bundle_status"] == "UNVERIFIED"
    finally:
        service.shutdown()


def test_concurrent_runtime_state_writes_do_not_share_temporary_file(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    payload = {
        "schema_version": 1,
        "session_id": "concurrent-session",
        "session": {"status": "RUNNING"},
    }
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(
                    service._write_runtime_state_payload,
                    "concurrent-session",
                    payload,
                )
                for _ in range(32)
            ]
            for future in futures:
                future.result()
        assert service._read_runtime_state("concurrent-session") == payload
        assert not list((tmp_path / "control" / "run-status").glob("*.tmp"))
    finally:
        service.shutdown()


def test_application_marks_nonterminal_runtime_snapshot_as_live(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        service._write_runtime_state_payload(
            "live-session",
            {
                "schema_version": 1,
                "session_id": "live-session",
                "session": {
                    "session_id": "live-session",
                    "status": "RUNNING",
                    "workspace": str(tmp_path / "workspace"),
                    "agent": "codex",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1},
                "policy": {"id": "basic", "version": "1.0"},
                "result_available": False,
                "result_path": None,
            },
        )

        runs = service.list_runs()

        assert runs[0]["run_classification"] == "LIVE_PROTECTED_RUN"
        assert runs[0]["bundle_status"] == "PENDING"
    finally:
        service.shutdown()


def test_live_refresh_exposes_redacted_hook_action_before_run_finishes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    action = SimpleNamespace(
        action_id="action-live",
        operation=Operation.DELETE,
        target_kind=ActionTargetKind.FILE,
        canonical_path=".env",
        evidence_ids=("evidence-live",),
    )
    event = SimpleNamespace(
        action=action,
        policy_evaluation=SimpleNamespace(
            policy_decision=PolicyDecision.VIOLATION,
            matched_rule_ids=("deny-env",),
            asset_type=None,
        ),
        attribution=SimpleNamespace(
            grade=AttributionGrade.EXACT,
            reason="DIRECT_TRUSTED_HOOK",
        ),
        gate_result=SimpleNamespace(
            action=EnforcementAction.NONE,
            decision=EnforcementDecision.CONTAIN,
            execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
            route=EnforcementRoute.PRETOOL_BLOCK,
        ),
    )
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(event,),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="AGENT_HOOK")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="FILESYSTEM_WATCHER")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="PROCESS_RUNTIME")),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)

        assert record.protection_state == "ACTIVE_VERIFIED"
        assert record.hook_event_count == 1
        assert record.actions[0]["action_id"] == "action-live"
        assert record.incidents[0]["enforcement_route"] == "PRETOOL_BLOCK"
        assert "raw_command" not in repr(record.actions)
    finally:
        service.shutdown()


def test_verified_sensor_summary_requires_healthy_runtime_and_clean_stop() -> None:
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "AGENT_HOOK",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "PROCESS_RUNTIME",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
        ]
    ) is True
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "AGENT_HOOK",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
        ]
    ) is False
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "FAILED",
                "final_sensor_state": "STOPPED",
            }
        ]
    ) is False
    assert _sensor_summary_is_verified(
        [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "FAILED",
            }
        ]
    ) is False
    assert _sensor_summary_is_verified([]) is False


def test_live_verified_state_requires_all_sensors_healthy(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        healthy = SimpleNamespace(health=SimpleNamespace(status="HEALTHY"))
        failed = SimpleNamespace(health=SimpleNamespace(status="FAILED"))
        assert _sensors_runtime_healthy((healthy,)) is True
        assert _sensors_runtime_healthy((healthy, failed)) is False
        assert _sensors_runtime_healthy(()) is False
    finally:
        service.shutdown()


def test_product_sensor_set_requires_hook_file_and_process() -> None:
    healthy = lambda sensor: SimpleNamespace(
        health=SimpleNamespace(status="HEALTHY", sensor=sensor)
    )
    assert _product_sensor_set_present(
        tuple(healthy(name) for name in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME"))
    ) is True
    assert _product_sensor_set_present(
        (healthy("AGENT_HOOK"), healthy("FILESYSTEM_WATCHER"))
    ) is False


def test_refresh_sensors_includes_process_sensor_after_launch_registration(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    sensors = tuple(
        SimpleNamespace(
            health=SimpleNamespace(
                status=SimpleNamespace(value="HEALTHY"),
                sensor=SimpleNamespace(value=sensor),
            ),
        )
        for sensor in ("AGENT_HOOK", "FILESYSTEM_WATCHER", "PROCESS_RUNTIME")
    )
    try:
        service._refresh_sensors(record, sensors)

        assert record.sensor_health == {
            "AGENT_HOOK": "HEALTHY",
            "FILESYSTEM_WATCHER": "HEALTHY",
            "PROCESS_RUNTIME": "HEALTHY",
        }
    finally:
        service.shutdown()


def test_running_state_degrades_when_product_process_sensor_is_missing(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    record.phase = "RUNNING"
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(SimpleNamespace(
            action=SimpleNamespace(
                action_id="action-live",
                operation=Operation.READ,
                target_kind=ActionTargetKind.FILE,
                canonical_path="README.md",
                evidence_ids=("evidence-live",),
            ),
            policy_evaluation=SimpleNamespace(
                policy_decision=PolicyDecision.COMPLIANT,
                matched_rule_ids=(),
                asset_type=None,
            ),
            attribution=SimpleNamespace(
                grade=AttributionGrade.EXACT,
                reason="DIRECT_TRUSTED_HOOK",
            ),
            gate_result=SimpleNamespace(
                action=EnforcementAction.NONE,
                decision=EnforcementDecision.CONTINUE,
                execution_result=EnforcementExecutionResult.NOT_ATTEMPTED,
                route=EnforcementRoute.NONE,
            ),
        ),),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="AGENT_HOOK")),
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY", sensor="FILESYSTEM_WATCHER")),
    )
    record.runtime["launcher"] = SimpleNamespace(
        hook_broker=SimpleNamespace(is_running=True),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)
        assert record.protection_state == "ACTIVE_DEGRADED"
    finally:
        service.shutdown()


def test_live_state_degrades_when_hook_broker_is_not_running(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "RUNNING"
    record.runtime["codex_controller"] = SimpleNamespace(
        events=(),
        errors=(),
        post_action_containments=(),
    )
    record.runtime["sensors"] = (
        SimpleNamespace(health=SimpleNamespace(status="HEALTHY")),
    )
    record.runtime["launcher"] = SimpleNamespace(
        hook_broker=SimpleNamespace(is_running=False),
    )
    service.registry.add(record)
    try:
        service._refresh_protection_state(record)

        assert record.protection_state == "DEGRADED"
        assert (
            service.get_run_status(record.session_id)["protection"]["hook_broker"]
            == "FAILED"
        )
    finally:
        service.shutdown()


def test_completed_bundle_requires_verified_sensor_summary(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    session_dir = tmp_path / "control" / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    base = {
        "session_status": "COMPLETED",
        "session_end_reason": "AGENT_EXITED",
        "limitations": [],
        "action_outcomes": [],
        "sensor_summary": [
            {
                "sensor": "FILESYSTEM_WATCHER",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "AGENT_HOOK",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
            {
                "sensor": "PROCESS_RUNTIME",
                "runtime_health_before_stop": "HEALTHY",
                "final_sensor_state": "STOPPED",
            },
        ],
    }
    monkeypatch.setattr(service.reader, "read_result", lambda _session_id: dict(base))
    monkeypatch.setattr(
        service.reader,
        "verification",
        lambda _session_id: SimpleNamespace(status=SimpleNamespace(value="VALID")),
    )
    monkeypatch.setattr(
        service,
        "_evidence_metadata",
        lambda _session_id, *, require_valid=True: [
            {"source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"}
        ],
    )
    monkeypatch.setattr(service.reader, "checkpoint_status", lambda _session_id: "READY")
    try:
        status = service._status_from_completed_bundle("session-1")
        assert status["protection"]["state"] == "COMPLETED_VERIFIED"
        assert status["checkpoint"] == "READY"
        base["sensor_summary"][0]["final_sensor_state"] = "FAILED"
        assert service._status_from_completed_bundle("session-1")["protection"]["state"] == "COMPLETED_DEGRADED"
        base["sensor_summary"][0]["final_sensor_state"] = "STOPPED"
        base["limitations"] = ["HOOK_BROKER_RUNTIME_NOT_VERIFIED"]
        assert service._status_from_completed_bundle("session-1")["protection"]["state"] == "COMPLETED_DEGRADED"
    finally:
        service.shutdown()


def test_recovery_is_requested_only_for_post_action_termination(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["lease_manager"] = object()
    termination = object()
    gate = SimpleNamespace(route=EnforcementRoute.PROCESS_TERMINATION)
    record.runtime["process_termination_result"] = termination
    record.runtime["post_action_gate_results"] = (gate,)
    calls: dict[str, object] = {}

    class FakeRecoveryCoordinator:
        def __init__(self, lease_manager) -> None:
            calls["lease_manager"] = lease_manager

        def recover(self, gate_result, termination_result, **kwargs):
            calls["gate_result"] = gate_result
            calls["termination_result"] = termination_result
            calls["kwargs"] = kwargs
            return SimpleNamespace(
                verified_recovery_success=True,
                integrity_result=SimpleNamespace(integrity_status="VERIFIED"),
            )

    monkeypatch.setattr("aia_app.service.RecoveryCoordinator", FakeRecoveryCoordinator)
    session = SimpleNamespace(session_id=record.session_id, workspace=tmp_path)
    launch_context = SimpleNamespace(launch_id="launch-1")
    try:
        result = service._recover_after_containment(
            record,
            session=session,
            preparation=object(),
            checkpoint=object(),
            lease=object(),
            launch_context=launch_context,
        )

        assert result.verified_recovery_success is True
        assert calls["lease_manager"] is record.runtime["lease_manager"]
        assert calls["gate_result"] is gate
        assert calls["termination_result"] is termination
        assert calls["kwargs"]["expected_launch_id"] == "launch-1"
        assert record.runtime["recovery_verification"] is result
    finally:
        service.shutdown()


def test_pretool_only_block_does_not_trigger_recovery(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.runtime["process_termination_result"] = object()
    record.runtime["post_action_gate_results"] = (
        SimpleNamespace(route=EnforcementRoute.PRETOOL_BLOCK),
    )
    monkeypatch.setattr(
        "aia_app.service.RecoveryCoordinator",
        lambda _lease_manager: pytest.fail("Recovery must not run for a pre-tool deny"),
    )
    try:
        result = service._recover_after_containment(
            record,
            session=SimpleNamespace(session_id=record.session_id, workspace=tmp_path),
            preparation=object(),
            checkpoint=object(),
            lease=object(),
            launch_context=SimpleNamespace(launch_id="launch-1"),
        )
        assert result is None
    finally:
        service.shutdown()


def test_presenters_keep_sensitive_target_values_out_of_views() -> None:
    action = {
        "action_id": "a1",
        "operation": "MODIFY",
        "policy_decision": "VIOLATION",
        "attribution_grade": "EXACT",
        "attribution_reason": "hook and process evidence",
        "enforcement_action": "CONTAIN",
        "execution_result": "SUCCEEDED",
        "target": {
            "canonical_path": "C:/workspace/app.py",
            "raw_command": "echo SUPER_SECRET",
            "payload": "SUPER_SECRET",
        },
    }
    view = action_view(action)
    assert view["target"]["display"] == "C:/workspace/app.py"
    assert "raw_command" not in view["target"]
    assert "SUPER_SECRET" not in repr(view)
    incident = incident_view(action)
    assert incident is not None
    assert incident["attribution_class"] == "EXACT"

    reparsed = action_view(view)
    assert reparsed["attribution_class"] == "EXACT"
    assert reparsed["enforcement_action"] == "CONTAIN"


def test_incident_presenter_localizes_summary_without_changing_decision_codes() -> None:
    view = incident_view(
        {
            "action_id": "a1",
            "operation": "EXECUTE",
            "policy_decision": "INDETERMINATE",
            "enforcement_action": "REFUSE",
            "execution_result": "NOT_ATTEMPTED",
            "target": {"canonical_path": "C:/workspace/app.py"},
        }
    )

    assert view is not None
    assert view["summary"] == "명령 실행 요청 · 판정 불가"
    assert view["policy_decision"] == "INDETERMINATE"
    assert view["reason"] == "판정 불가"
    assert view["tool_name"] is None
    assert "was classified" not in repr(view)
    assert "AIA exposes" not in repr(view)


def test_incident_presenter_localizes_attribution_reason_and_keeps_raw_free() -> None:
    view = incident_view(
        {
            "action_id": "a1",
            "operation": "MODIFY",
            "policy_decision": "VIOLATION",
            "attribution_grade": "PROCESS",
            "attribution_reason": "Process was observed in the verified Agent Process Tree",
            "tool_name": "Bash",
            "enforcement_action": "REFUSE",
            "execution_result": "NOT_ATTEMPTED",
            "target": {"canonical_path": "C:/workspace/app.py"},
        }
    )

    assert view is not None
    assert view["attribution_reason_label"] == "검증된 Agent Process Tree에서 프로세스가 관찰되었습니다."
    assert view["reason"] == "검증된 Agent Process Tree에서 프로세스가 관찰되었습니다."
    assert view["tool_name"] == "Bash"


def test_synthetic_incident_summaries_are_localized() -> None:
    incidents = incident_views_for_result(
        {
            "action_outcomes": [],
            "recovery_result": {"recovery_status": "FAILED"},
            "integrity_result": {"integrity_status": "FAILED"},
            "sensor_summary": [{"sensor": "PROCESS_RUNTIME", "runtime_health_before_stop": "FAILED"}],
        }
    )

    assert [item["summary"] for item in incidents] == [
        "복구 작업 · 실행 실패",
        "무결성 검증 · 실패",
        "센서 상태 · 실행 실패",
    ]


def test_result_presenter_exposes_recovery_and_integrity_as_separate_axes() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "recovery_result": {"status": "RESTORED"},
            "integrity_result": {"status": "FAILED"},
            "action_outcomes": [],
        },
        "VALID",
    )
    assert view["recovery_status"] == "RESTORED"
    assert view["integrity_status"] == "FAILED"
    assert view["bundle_status"] == "VALID"


def test_result_presenter_exposes_unsupported_tool_review_decisions() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "limitations": [
                "UNSUPPORTED_TOOL_REVIEW_APPROVED",
                "UNSUPPORTED_TOOL_REVIEW_DECLINED",
                "UNSUPPORTED_TOOL_REVIEW_TIMED_OUT",
                "UNSUPPORTED_TOOL_USER_APPROVED",
            ],
            "action_outcomes": [],
        },
        "VALID",
    )

    assert view["unsupported_tool_review_decisions"] == [
        "UNSUPPORTED_TOOL_REVIEW_APPROVED",
        "UNSUPPORTED_TOOL_REVIEW_DECLINED",
        "UNSUPPORTED_TOOL_REVIEW_TIMED_OUT",
    ]
    assert "UNSUPPORTED_TOOL_USER_APPROVED" in view["limitations"]


def test_recovery_status_presenter_keeps_restore_and_integrity_separate() -> None:
    view = recovery_status_view(
        {
            "status": "RESTORED",
            "integrity_status": "FAILED",
            "recovery_result": {"recovery_status": "RESTORED"},
            "integrity_result": {
                "integrity_status": "FAILED",
                "missing_paths": ["missing.txt"],
                "changed_paths": ["changed.txt", "missing.txt"],
                "unexpected_paths": [],
                "type_mismatches": [],
            },
        }
    )

    assert view == {
        "recovery_status": "RESTORED",
        "integrity_status": "FAILED",
        "mismatched_file_count": 2,
    }


def test_evidence_summary_counts_safe_record_metadata() -> None:
    from aia_app.presenters import evidence_summary

    summary = evidence_summary(
        [
            {"source": "FILESYSTEM_WATCHER", "record_type": "FILESYSTEM_EVENT"},
            {"source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"},
            {"source": "AGENT_HOOK", "record_type": "POSTTOOL_OBSERVED"},
            {"source": "PROCESS_RUNTIME", "record_type": "PROCESS_OBSERVED"},
            {"source": "PROCESS_RUNTIME", "record_type": "PROCESS_EXIT_OBSERVED"},
            {"source": "FILESYSTEM_WATCHER", "record_type": "SENSOR_HEALTH"},
        ]
    )

    assert summary == {
        "available": True,
        "filesystem_events": 1,
        "pretool_events": 1,
        "posttool_events": 1,
        "process_observed": 1,
        "process_exit_observed": 1,
        "sensor_health_events": 1,
    }


def test_result_presenter_aggregates_all_action_outcomes() -> None:
    summary = action_summary(
        {
            "action_outcomes": [
                {
                    "policy_decision": "VIOLATION",
                    "enforcement_decision": "CONTAIN",
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "policy_decision": "COMPLIANT",
                    "enforcement_decision": "CONTINUE",
                    "enforcement_action": "NONE",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "policy_decision": "COMPLIANT",
                    "operation_effect": "AUDIT",
                    "enforcement_decision": "CONTINUE",
                    "enforcement_action": "NONE",
                    "execution_result": "NOT_ATTEMPTED",
                },
                {
                    "policy_decision": "INDETERMINATE",
                    "enforcement_decision": "REFUSE",
                    "enforcement_action": "NONE",
                    "execution_result": "FAILED",
                },
            ]
        }
    )

    assert summary == {
        "total": 4,
        "compliant": 2,
        "audit": 1,
        "violation": 1,
        "indeterminate": 1,
        "contain": 1,
        "blocked": 1,
        "terminated": 0,
        "execution_succeeded": 2,
        "execution_failed": 1,
        "execution_not_attempted": 1,
    }
    assert result_view(
        {"action_outcomes": [{"policy_decision": "VIOLATION"}]}, "VALID"
    )["action_summary"]["total"] == 1


def test_result_presenter_exposes_redacted_recovery_and_integrity_counts() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "ABORTED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "recovery_result": {
                "recovery_status": "RESTORED",
                "planned_operation_count": 3,
                "succeeded_operation_count": 3,
                "failed_operation_count": 0,
                "restored_paths": ["a.py", "b.py"],
            },
            "integrity_result": {
                "integrity_status": "VERIFIED",
                "expected_entry_count": 4,
                "actual_entry_count": 4,
                "verification_errors": [],
            },
            "action_outcomes": [],
        },
        "VALID",
    )
    assert view["recovery_summary"]["succeeded_operations"] == 3
    assert view["recovery_summary"]["restored_paths"] == 2
    assert view["integrity_summary"]["expected_entries"] == 4
    assert view["integrity_summary"]["verification_errors"] == 0


def test_result_presenter_exposes_codex_block_confirmation() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "block_confirmation_available": True,
                    "reason": "CODEX_HOOK_BLOCKED_EVENT",
                }
            },
            "action_outcomes": [
                {
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                }
            ],
        },
        "VALID",
    )

    assert view["codex_block_confirmation"] == "BLOCK_CONFIRMED"
    assert view["codex_block_confirmation_reason"] == "CODEX_HOOK_BLOCKED_EVENT"


def test_result_presenter_reports_unavailable_block_confirmation() -> None:
    view = result_view({"action_outcomes": []}, "VALID")

    assert view["codex_block_confirmation"] == "NOT_AVAILABLE"


def test_result_presenter_exposes_effective_codex_execution_policy() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "effective_sandbox": "read-only",
                    "effective_approval_policy": "never",
                }
            },
            "action_outcomes": [],
        },
        "VALID",
    )

    assert view["execution_policy_status"] == "DEGRADED"
    assert view["requested_sandbox"] == "workspace-write"
    assert view["effective_sandbox"] == "read-only"
    assert view["effective_approval_policy"] == "never"


@pytest.mark.parametrize(
    ("observation", "expected_status"),
    [
        (
            {
                "effective_sandbox": "workspace-write",
                "effective_approval_policy": "on-request",
            },
            "MATCHED",
        ),
        ({}, "NOT_OBSERVED"),
    ],
)
def test_result_presenter_reports_execution_policy_status(
    observation: dict[str, str], expected_status: str
) -> None:
    view = result_view(
        {
            "agent_execution": {"output_observation": observation},
            "action_outcomes": [],
        },
        "VALID",
    )

    assert view["execution_policy_status"] == expected_status


def test_result_presenter_does_not_confirm_from_output_metadata_alone() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "agent_execution": {
                "output_observation": {
                    "block_confirmation_available": True,
                    "reason": "CODEX_BLOCK_AND_NO_RUN_MESSAGE",
                }
            },
            "action_outcomes": [
                {
                    "enforcement_action": "NONE",
                    "execution_result": "FAILED",
                }
            ],
        },
        "VALID",
    )

    assert view["codex_block_confirmation"] == "NOT_CONFIRMED"


def test_result_presenter_marks_action_incidents_for_result_links() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "action_outcomes": [
                {
                    "action_id": "a1",
                    "operation": "DELETE",
                    "policy_decision": "VIOLATION",
                    "attribution_grade": "EXACT",
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                    "target": {"canonical_path": "secret.txt"},
                },
            ],
        },
        "VALID",
    )
    assert view["actions"][0]["incident"] is True


def test_result_presenter_preserves_attribution_in_evidence_chain() -> None:
    view = result_view(
        {
            "aia_session_id": "session-1",
            "session_status": "COMPLETED",
            "policy": {"policy_id": "p1", "policy_version": "1.0"},
            "action_outcomes": [
                {
                    "action_id": "a1",
                    "operation": "MODIFY",
                    "policy_decision": "COMPLIANT",
                    "attribution_grade": "EXACT",
                    "enforcement_action": "NONE",
                    "execution_result": "SUCCEEDED",
                    "evidence_ids": ["h1"],
                },
            ],
            "attribution_results": [
                {
                    "action_id": "a1",
                    "grade": "EXACT",
                    "supporting_evidence_ids": ["h1"],
                },
            ],
        },
        "VALID",
    )

    assert view["evidence_chains"][0]["stages"][3]["status"] == "EXACT"


def test_result_presenter_summarizes_attribution_grades_and_control() -> None:
    view = result_view(
        {
            "action_outcomes": [
                {"action_id": "exact", "attribution_grade": "EXACT"},
                {"action_id": "process", "attribution_grade": "PROCESS"},
            ],
            "attribution_results": [
                {"action_id": "exact", "grade": "EXACT"},
                {"action_id": "temporal", "grade": "TEMPORAL"},
                {"action_id": "unknown", "grade": "UNKNOWN"},
            ],
            "enforcement_results": [
                {
                    "action_id": "exact",
                    "attribution_grade": "EXACT",
                    "enforcement_decision": "CONTAIN",
                    "enforcement_action": "TERMINATED",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "action_id": "process",
                    "attribution_grade": "PROCESS",
                    "enforcement_decision": "REFUSE",
                    "enforcement_action": "NONE",
                    "execution_result": "NOT_ATTEMPTED",
                },
            ],
        },
        "VALID",
    )

    assert view["attribution_summary"] == {
        "counts": {"EXACT": 1, "PROCESS": 1, "TEMPORAL": 1, "UNKNOWN": 1},
        "automatic_control_happened": True,
        "automatic_control_grades": ["EXACT"],
    }
    refused = result_view(
        {
            "enforcement_results": [
                {
                    "attribution_grade": "PROCESS",
                    "enforcement_decision": "REFUSE",
                    "enforcement_action": "NONE",
                    "execution_result": "NOT_ATTEMPTED",
                }
            ]
        },
        "VALID",
    )
    assert refused["attribution_summary"]["automatic_control_happened"] is False
    assert refused["attribution_summary"]["automatic_control_grades"] == []


def test_result_action_chain_shows_recorded_stages_and_marks_missing_links() -> None:
    secret = "FAKE_SECRET_DO_NOT_RENDER"
    actions = [
        {
            "action_id": "complete",
            "tool_name": "Bash",
            "policy_decision": "VIOLATION",
            "enforcement_action": "BLOCKED",
            "evidence_ids": ["hook", "process", "file"],
            "target": {"raw_command": secret},
            "payload": {"content": secret},
        },
        {"action_id": "partial", "payload": {"content": secret}},
    ]
    metadata = [
        {"evidence_id": "hook", "source": "AGENT_HOOK", "record_type": "PRETOOL_REQUEST"},
        {"evidence_id": "process", "source": "PROCESS_RUNTIME", "record_type": "PROCESS_OBSERVED"},
        {"evidence_id": "file", "source": "FILESYSTEM_WATCHER", "record_type": "FILESYSTEM_EVENT"},
    ]

    chains = result_action_chain_views(
        actions,
        evidence_metadata=metadata,
        recovery={"recovery_status": "RESTORED"},
    )

    assert [stage["stage"] for stage in chains[0]["stages"]] == [
        "TOOL_REQUEST",
        "PROCESS",
        "FILE_CHANGE",
        "POLICY",
        "ENFORCEMENT",
        "RECOVERY",
    ]
    assert [stage["status"] for stage in chains[0]["stages"]] == [
        "OBSERVED", "OBSERVED", "OBSERVED", "VIOLATION", "BLOCKED", "RESTORED"
    ]
    assert all(stage["value"] == "not observed" for stage in chains[1]["stages"][:5])
    assert chains[1]["stages"][5]["value"] == "RESTORED"
    assert secret not in repr(chains)


def test_result_bundle_reader_rejects_path_traversal_and_unverified_bundle(tmp_path) -> None:
    reader = ResultBundleReader(tmp_path)
    with pytest.raises(ValueError, match="invalid session_id"):
        reader.session_directory("../secret")
    with pytest.raises(ValueError, match="Integrity Failure"):
        reader.read_result("missing-session")


def test_result_bundle_reader_can_read_live_metadata_without_valid_bundle(tmp_path) -> None:
    reader = ResultBundleReader(tmp_path)
    evidence_path = tmp_path / "sessions" / "session-1" / "evidence" / "raw-evidence.jsonl"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_id": "e1",
                "source": "AGENT_HOOK",
                "record_type": "PRETOOL_REQUEST",
                "payload": {"command": "secret command"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metadata = reader.read_evidence_metadata("session-1", require_valid=False)

    assert metadata[0]["record_type"] == "PRETOOL_REQUEST"
    assert "command" in metadata[0]["payload_keys"]
    assert "secret command" not in repr(metadata)


def test_result_bundle_reader_reports_verified_checkpoint_status(
    tmp_path,
    monkeypatch,
) -> None:
    reader = ResultBundleReader(tmp_path)
    session_id = "session-1"
    checkpoint_id = "checkpoint-1"
    session_dir = tmp_path / "sessions" / session_id
    checkpoint_dir = session_dir / "checkpoints" / checkpoint_id
    result_dir = session_dir / "result"
    checkpoint_dir.mkdir(parents=True)
    result_dir.mkdir()
    (checkpoint_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (checkpoint_dir / "metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_id": checkpoint_id,
                "schema_version": "1.0",
                "session_id": session_id,
                "validity": "VALID",
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "evidence-manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "artifact_type": "CHECKPOINT_MANIFEST",
                        "relative_path": f"checkpoints/{checkpoint_id}/manifest.json",
                    },
                    {
                        "artifact_type": "CHECKPOINT_METADATA",
                        "relative_path": f"checkpoints/{checkpoint_id}/metadata.json",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "_require_valid", lambda _session_id: None)
    assert reader.checkpoint_status(session_id) == "READY"

    (checkpoint_dir / "metadata.json").write_text(
        json.dumps(
            {
                "checkpoint_id": checkpoint_id,
                "schema_version": "1.0",
                "session_id": session_id,
                "validity": "INVALID",
            }
        ),
        encoding="utf-8",
    )
    assert reader.checkpoint_status(session_id) == "UNKNOWN"


@pytest.mark.parametrize(
    ("status", "end_reason", "hook_event", "limitations", "expected_state"),
    [
        ("COMPLETED", "AGENT_EXITED", True, [], "COMPLETED_VERIFIED"),
        ("COMPLETED", "AGENT_EXITED", False, [], "COMPLETED_DEGRADED"),
        (
            "COMPLETED",
            "AGENT_EXITED",
            True,
            ["CODEX_APPROVAL_POLICY_DOWNGRADED"],
            "COMPLETED_DEGRADED",
        ),
        ("ABORTED", "USER_ABORT", True, [], "ABORTED_VERIFIED"),
        ("ABORTED", "USER_ABORT", False, [], "ABORTED_DEGRADED"),
        (
            "ABORTED",
            "USER_ABORT",
            True,
            ["PROTECTION_BOUNDARY_LOST"],
            "ABORTED_DEGRADED",
        ),
        ("FAILED", "PROTECTION_FAILURE", True, [], "FAILED_DEGRADED"),
    ],
)
def test_result_bundle_reader_classifies_protection_state_in_history(
    tmp_path,
    monkeypatch,
    status,
    end_reason,
    hook_event,
    limitations,
    expected_state,
) -> None:
    reader = ResultBundleReader(tmp_path)
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    monkeypatch.setattr(
        reader,
        "_read_verified_result",
        lambda _session_id: (
            {
                "session_status": status,
                "session_end_reason": end_reason,
                "launch_mode": "web_terminal",
                "limitations": limitations,
                "action_outcomes": [],
            },
            SimpleNamespace(status=SimpleNamespace(value="VALID")),
        ),
    )
    monkeypatch.setattr(
        reader,
        "read_evidence_metadata",
        lambda _session_id, *, require_valid=True: [
            {
                "source": "AGENT_HOOK",
                "record_type": "PRETOOL_REQUEST",
                "payload": {"command": "secret command"},
            }
        ]
        if hook_event
        else [],
    )

    runs = reader.list_completed()

    assert runs[0]["protection_state"] == expected_state
    assert runs[0]["launch_mode"] == "web_terminal"
    assert "secret command" not in repr(runs)


def test_application_exposes_fixed_profile_choices(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        profiles = service.policy_profiles()
        assert {item["value"] for item in profiles} == {
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
            "CUSTOM",
        }
        assert all(item["description"] for item in profiles)
    finally:
        service.shutdown()


def test_application_policy_preview_uses_resolved_protected_profile(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        blocked = service.preview_policy({"operation": "READ", "path": ".env"})
        assert blocked["policy_decision"] == "VIOLATION"
        assert blocked["operation_effect"] == "DENY"
        assert blocked["asset_type"] == "SECRET"
        assert blocked["matched_rule_ids"] == ["protected-secret-files"]

        allowed = service.preview_policy(
            {"operation": "MODIFY", "path": "src/app.py"}
        )
        assert allowed["policy_decision"] == "COMPLIANT"
        assert allowed["operation_effect"] == "AUDIT"
        assert allowed["asset_type"] is None
        assert allowed["matched_rule_ids"] == []
    finally:
        service.shutdown()


def test_application_preflight_reports_required_and_optional_hook_state(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_posttool_installed",
        lambda _installer: False,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["ready"] is True
        assert result["readiness_code"] == "READY"
        assert result["hook_trust"]["status"] == "MANUAL_REVIEW_REQUIRED"
        assert result["hook_activation"]["status"] == "NOT_OBSERVED"
        assert result["protection_claim"]["status"] == "CLAIM_ALLOWED_AFTER_SESSION_EVENT"
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["pretool_hook"]["ok"] is True
        assert "검토 필요" in checks["pretool_hook"]["detail"]
        assert checks["posttool_hook"]["optional"] is True
        assert checks["posttool_hook"]["ok"] is False
        assert checks["codex_hook_trust"]["optional"] is True
        assert checks["codex_hook_trust"]["ok"] is False
        assert result["codex_hook_trust"]["hooks"][0]["trust_status"] == "MODIFIED"
    finally:
        service.shutdown()


def test_application_preflight_explains_stale_hook_path(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: False,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.has_aia_runtime",
        lambda _installer, event="PreToolUse": True,
    )
    try:
        result = service.preflight()
        checks = {item["name"]: item for item in result["checks"]}
        assert result["readiness_code"] == "NOT_READY"
        assert checks["pretool_hook"]["stale"] is True
        assert "기존 AIA Hook 경로" in checks["pretool_hook"]["detail"]
        assert "갱신" in result["next_step"]
    finally:
        service.shutdown()


def test_application_preflight_reports_actual_trusted_hook_status(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_posttool_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "TRUSTED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["hook_trust"]["status"] == "TRUSTED"
        assert "신뢰된 상태" in result["hook_trust"]["detail"]
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["pretool_hook"]["detail"] == "설치됨 · Trust 확인됨"
    finally:
        service.shutdown()


def test_application_preflight_requires_live_hook_verification_when_enabled(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_posttool_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "TRUSTED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["ready"] is False
        assert result["readiness_code"] == "HOOK_VERIFICATION_REQUIRED"
        assert "hook verify" in result["next_step"]
        checks = {item["name"]: item for item in result["checks"]}
        assert checks["hook_verification"]["ok"] is False
        expected_cli_prefix = _aia_cli_prefix(CodexHookInstaller())
        assert checks["hook_verification"]["detail"] == (
            f"{expected_cli_prefix} hook verify 필요"
        )
    finally:
        service.shutdown()


def test_application_preflight_exposes_untrusted_hook_remediation(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.CodexHookInstaller.is_installed",
        lambda _installer: True,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                    ],
                }
            },
        )(),
    )
    try:
        result = service.preflight()
        assert result["ready"] is False
        assert result["readiness_code"] == "CODEX_HOOK_TRUST_REQUIRED"
        assert "/hooks" in result["next_step"]
        expected_cli_prefix = _aia_cli_prefix(CodexHookInstaller())
        assert f"{expected_cli_prefix} hook verify" in result["next_step"]
    finally:
        service.shutdown()


def test_frozen_preflight_points_to_allowed_sibling_cli_entrypoint(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    fake_aia = tmp_path / "AIA" / "AIA.exe"
    fake_aia.parent.mkdir(parents=True)
    fake_aia.write_bytes(b"")
    fake_cli = tmp_path / "aia-cli" / "aia-cli.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_bytes(b"")
    monkeypatch.setattr("aia_app.service.sys.executable", str(fake_aia))
    monkeypatch.setattr("aia_app.service.sys.frozen", True, raising=False)
    try:
        assert _aia_cli_prefix(CodexHookInstaller()) == str(fake_cli)
    finally:
        service.shutdown()


def test_application_create_rejects_currently_untrusted_hook(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    monkeypatch.setattr(
        "aia_app.service.HookVerificationStore.is_current",
        lambda self, installer, executable: True,
    )
    monkeypatch.setattr(
        "aia_app.service.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                    ],
                }
            },
        )(),
    )
    try:
        with pytest.raises(ApplicationValidationError, match="Hook Trust"):
            service.create_protected_run(
                {"workspace": str(tmp_path), "task": "inspect"}
            )
    finally:
        service.shutdown()


def test_application_rejects_run_without_live_hook_verification(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(
        tmp_path / "control",
        require_hook_verification=True,
    )
    monkeypatch.setattr(
        "aia_app.service.CodexAdapter.discover",
        lambda _adapter: tmp_path / "codex.exe",
    )
    try:
        with pytest.raises(ApplicationValidationError, match="Hook 검증"):
            service.create_protected_run(
                {"workspace": str(tmp_path), "task": "inspect"}
            )
    finally:
        service.shutdown()


def test_application_rejects_invalid_workspace_before_background_launch(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        with pytest.raises(ApplicationValidationError, match="workspace validation failed"):
            service.create_protected_run(
                {"workspace": str(tmp_path / "missing"), "task": "inspect"}
            )
    finally:
        service.shutdown()


def test_application_rejects_empty_non_interactive_task(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        with pytest.raises(ApplicationValidationError, match="task is required"):
            service.create_protected_run({"workspace": str(tmp_path), "task": ""})
    finally:
        service.shutdown()


def test_protected_run_lifecycle_keeps_successful_phases_in_order(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    events = []
    session = SimpleNamespace(
        transition=lambda status, **_kwargs: events.append(f"session:{status.value}")
    )
    record.runtime.update({"session": session, "resolved_policy": object()})
    sensors = (object(), object())

    monkeypatch.setattr(
        service,
        "_phase",
        lambda _record, phase, *_args: events.append(f"phase:{phase}"),
    )

    def prepare(*_args):
        events.append("preparation")
        return object(), object(), sensors, object(), object(), object(), True

    monkeypatch.setattr(service, "_prepare_protected_run", prepare)
    monkeypatch.setattr(
        service,
        "_create_protected_launcher",
        lambda *_args: (events.append("launcher") or object(), object(), object()),
    )
    monkeypatch.setattr(
        service,
        "_observe_protected_run",
        lambda *_args: (
            events.append("observation") or (object(), sensors, 0, True, None)
        ),
    )

    def finalize(*_args):
        events.append("finalization")
        record.status = "COMPLETED"
        return True

    monkeypatch.setattr(service, "_finalize_completed_protected_run", finalize)
    monkeypatch.setattr(
        service,
        "_cleanup_run_lifecycle",
        lambda *_args: events.append("cleanup"),
    )
    try:
        service._run_protected_lifecycle(record)

        assert events == [
            "phase:PREPARING",
            "session:PREPARING",
            "preparation",
            "launcher",
            "phase:LAUNCHING",
            "observation",
            "finalization",
            "cleanup",
        ]
        assert record.status == "COMPLETED"
    finally:
        service.shutdown()


def test_protected_run_lifecycle_cleans_up_after_prelaunch_abort(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    events = []
    session = SimpleNamespace(transition=lambda *_args, **_kwargs: None)
    record.runtime.update({"session": session, "resolved_policy": object()})
    sensors = (object(), object())

    monkeypatch.setattr(service, "_phase", lambda *_args: None)

    def prepare(*_args):
        record.status = "ABORTED"
        events.append("abort_finalized")
        return object(), object(), sensors, object(), object(), object(), False

    monkeypatch.setattr(service, "_prepare_protected_run", prepare)

    def cleanup(*_args):
        events.append(("cleanup", record.status))

    monkeypatch.setattr(service, "_cleanup_run_lifecycle", cleanup)
    try:
        service._run_protected_lifecycle(record)

        assert events == ["abort_finalized", ("cleanup", "ABORTED")]
        assert record.status == "ABORTED"
    finally:
        service.shutdown()


def test_protected_run_lifecycle_cleans_up_after_exception_without_losing_failure(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    events = []
    session = SimpleNamespace(transition=lambda *_args, **_kwargs: None)
    record.runtime.update({"session": session, "resolved_policy": object()})

    monkeypatch.setattr(service, "_phase", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "_prepare_protected_run",
        lambda *_args: (
            object(),
            object(),
            (object(), object()),
            object(),
            object(),
            object(),
            True,
        ),
    )

    def fail_launcher(*_args):
        raise RuntimeError("launcher setup failed")

    monkeypatch.setattr(service, "_create_protected_launcher", fail_launcher)

    def cleanup(*_args):
        events.append(("cleanup", record.status))

    monkeypatch.setattr(service, "_cleanup_run_lifecycle", cleanup)
    try:
        service._run_protected_lifecycle(record)

        assert events == [("cleanup", "FAILED")]
        assert record.status == "FAILED"
        assert record.error == "RuntimeError: launcher setup failed"
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    ("launch_mode", "expected_app_server"),
    [
        ("inherit", False),
        ("codex_app_server", True),
        ("new_terminal", False),
    ],
)
def test_interactive_launcher_keeps_protected_adapter_configuration(
    tmp_path, monkeypatch, launch_mode, expected_app_server
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.interactive = True
    record.launch_mode = launch_mode
    try:
        _launcher, captured, options = capture_service_launcher_factory(
            service, record, monkeypatch
        )

        assert options == {
            "approval_policy": "on-request",
            "sandbox": "workspace-write",
            "interactive": True,
            **({"app_server": True} if expected_app_server else {}),
        }
        assert captured["adapter"].enable_hooks is True
    finally:
        service.shutdown()


def test_non_interactive_launcher_keeps_current_adapter_options(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    try:
        _launcher, _captured, options = capture_service_launcher_factory(
            service, record, monkeypatch
        )

        assert options == {
            "approve_for_me": True,
            "skip_git_repo_check": True,
        }
    finally:
        service.shutdown()


def test_non_interactive_launch_failure_closes_temporary_output_handles(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    output_handles = []
    try:
        _launcher, captured, _options = capture_service_launcher_factory(
            service, record, monkeypatch, output_handles
        )

        def fail_popen(*_args, **_kwargs):
            raise OSError("simulated process launch failure")

        monkeypatch.setattr(service_module.subprocess, "Popen", fail_popen)
        with pytest.raises(OSError, match="simulated process launch failure"):
            captured["popen_factory"](
                ["codex", "exec"], cwd=str(tmp_path), env={}
            )

        assert len(output_handles) == 2
        assert all(handle.closed for handle in output_handles)
    finally:
        service.shutdown()


def test_application_returns_session_before_worker_finishes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    service._run = lambda record: None
    try:
        created = service.create_protected_run(
            {"workspace": str(tmp_path), "task": "inspect"}
        )
        assert created["session_id"]
        assert created["redirect_url"].endswith(created["session_id"])
        status = service.get_run_status(created["session_id"])
        assert status["protection"]["state"] == "STARTING"
    finally:
        service.shutdown()


def test_new_interactive_run_uses_codex_app_server_without_web_terminal(
    tmp_path, monkeypatch
) -> None:
    service = RunApplicationService(tmp_path / "control")
    records = []
    service._run = records.append
    monkeypatch.setattr(
        service._executor,
        "submit",
        lambda callback, record: callback(record),
    )
    try:
        created = service.create_protected_run(
            {
                "workspace": str(tmp_path),
                "interactive": True,
                "launch_mode": "codex_app_server",
            }
        )

        assert created["redirect_url"].endswith("/workbench")
        assert len(records) == 1
        assert records[0].launch_mode == "codex_app_server"
        assert "terminal_session" not in records[0].runtime
    finally:
        service.shutdown()


def test_new_run_persists_aia_coordinator_identity(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    service._run = lambda record: None
    try:
        created = service.create_protected_run(
            {"workspace": str(tmp_path), "task": "inspect"}
        )
        state = service._read_runtime_state(created["session_id"])
        assert state["coordinator"]["pid"] > 0
        assert state["coordinator"]["create_time"] >= 0
        assert state["managed_process"] is None
    finally:
        service.shutdown()


def test_runtime_state_persists_verified_agent_root_identity(tmp_path) -> None:
    record = make_record(tmp_path)
    record.runtime["launch_context"] = SimpleNamespace(
        launch_id="launch-1",
        launch_provenance="AIA_SPAWNED_ROOT",
        root_process_identity=ProcessIdentity(pid=4243, create_time=20.0),
    )

    state = RunApplicationService._runtime_state_mapping(record)

    assert state["managed_process"] == {
        "launch_id": "launch-1",
        "launch_provenance": "AIA_SPAWNED_ROOT",
        "root_process_identity": {"pid": 4243, "create_time": 20.0},
    }


def test_runtime_status_can_be_read_from_another_service_process(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    writer = RunApplicationService(control_root)
    record = make_record(tmp_path, session_id="session-1")
    record.status = "RUNNING"
    record.phase = "RUNNING"
    record.protection_state = "ACTIVE_VERIFIED"
    record.checkpoint = "READY"
    record.lease = "ACTIVE"
    writer.registry.add(record)
    writer._persist_runtime_state(record, strict=True)
    reader = RunApplicationService(control_root)
    monkeypatch.setattr(
        reader.reader,
        "read_result",
        lambda requested: (_ for _ in ()).throw(ValueError("not completed")),
    )
    try:
        status = reader.get_run_status(record.session_id)
        assert status["phase"] == "RUNNING"
        assert status["protection"]["state"] == "ACTIVE_VERIFIED"
        assert status["session"]["workspace"] == str(tmp_path)
    finally:
        reader.shutdown()
        writer.shutdown()


def test_list_runs_includes_runtime_state_from_another_service_process(tmp_path) -> None:
    control_root = tmp_path / "control"
    writer = RunApplicationService(control_root)
    record = make_record(tmp_path, session_id="session-1")
    record.status = "RUNNING"
    record.phase = "RUNNING"
    writer.registry.add(record)
    writer._persist_runtime_state(record, strict=True)
    reader = RunApplicationService(control_root)
    try:
        runs = reader.list_runs()
        assert runs[0]["session_id"] == "session-1"
        assert runs[0]["status"] == "RUNNING"
    finally:
        reader.shutdown()
        writer.shutdown()


def test_list_runs_skips_malformed_and_mismatched_runtime_state_files(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    run_status = tmp_path / "control" / "run-status"
    run_status.mkdir(parents=True)
    service._write_runtime_state_payload(
        "valid-session",
        {
            "schema_version": 1,
            "session_id": "valid-session",
            "session": {"status": "COMPLETED", "created_at": "2026-01-01T00:00:00+00:00"},
            "result_available": False,
        },
    )
    (run_status / "malformed-session.json").write_text("{", encoding="utf-8")
    (run_status / "mismatched-session.json").write_text(
        json.dumps({"session_id": "another-session", "session": {"status": "FAILED"}}),
        encoding="utf-8",
    )
    try:
        runs = service.list_runs()

        assert [run["session_id"] for run in runs] == ["valid-session"]
        assert runs[0]["run_classification"] == "UNVERIFIED_RUNTIME_STATE"
    finally:
        service.shutdown()


def test_list_runs_reuses_verified_history_for_refresh_burst(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    calls = 0

    def list_completed() -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [
            {
                "session_id": "completed-1",
                "status": "COMPLETED",
                "created_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:01:00+00:00",
                "workspace": str(tmp_path),
                "agent": "codex",
                "policy": {},
                "launch_mode": "inherit",
                "bundle_status": "VALID",
            }
        ]

    monkeypatch.setattr(service.reader, "list_completed", list_completed)
    try:
        assert service.list_runs()[0]["session_id"] == "completed-1"
        assert service.list_runs()[0]["session_id"] == "completed-1"
        assert calls == 1
    finally:
        service.shutdown()


def test_list_runs_preserves_workbench_launch_mode_when_bundle_omits_it(
    tmp_path,
    monkeypatch,
) -> None:
    service = RunApplicationService(tmp_path / "control")
    runtime_state = {
        "session_id": "session-1",
        "launch_mode": "web_terminal",
        "result_available": False,
        "session": {
            "status": "RUNNING",
            "created_at": "2026-01-01T00:00:00+00:00",
            "workspace": str(tmp_path),
            "agent": "codex",
        },
        "policy": {"id": "basic", "version": "1.0"},
        "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1},
    }
    monkeypatch.setattr(service, "_list_runtime_states", lambda: [runtime_state])
    monkeypatch.setattr(
        service.reader,
        "list_completed",
        lambda: [{
            "session_id": "session-1",
            "status": "COMPLETED",
            "launch_mode": "inherit",
        }],
    )
    try:
        runs = service.list_runs()
        assert runs[0]["launch_mode"] == "web_terminal"
    finally:
        service.shutdown()


def test_completed_status_preserves_workbench_launch_mode_from_runtime_state(
    tmp_path,
    monkeypatch,
) -> None:
    service = RunApplicationService(tmp_path / "control")
    monkeypatch.setattr(
        service,
        "_status_from_completed_bundle",
        lambda _session_id: {
            "launch_mode": "inherit",
            "session": {"status": "ABORTED"},
        },
    )
    monkeypatch.setattr(
        service,
        "_read_runtime_state",
        lambda _session_id: {"launch_mode": "web_terminal"},
    )
    try:
        status = service.get_run_status("session-1")
        assert status["launch_mode"] == "web_terminal"
        assert status["session"]["launch_mode"] == "web_terminal"
    finally:
        service.shutdown()


def test_request_stop_marks_pending_run_without_exposing_runtime(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    service.registry.add(record)
    try:
        result = service.request_stop(record.session_id)
        assert result["accepted"] is True
        assert result["status"] == "STOP_REQUESTED"
        status = service.get_run_status(record.session_id)
        assert status["stop"]["requested"] is True
    finally:
        service.shutdown()


def test_request_stop_can_terminate_a_verified_root_during_launch(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    record.phase = "LAUNCHING"

    class Launcher:
        status = SimpleNamespace(value="STARTING")

        @staticmethod
        def request_user_abort() -> bool:
            return True

    record.runtime["launcher"] = Launcher()
    service.registry.add(record)
    try:
        result = service.request_stop(record.session_id)
        assert result["accepted"] is True
        assert result["reason"] == "USER_ABORT_DURING_LAUNCH"
        assert record.stop_requested is True
        assert record.protection_state == "STOP_REQUESTED"
    finally:
        service.shutdown()


def test_shutdown_requests_stop_for_live_run_before_executor_closes(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.status = "READY"
    record.phase = "READY"
    service.registry.add(record)
    try:
        service.shutdown(wait=True)
        assert record.stop_requested is True
        assert record.protection_state == "STOP_REQUESTED"
    finally:
        # The shutdown above is intentionally part of the assertion.  This
        # second call keeps the test safe if setup fails before that point.
        service.shutdown(wait=True)


def test_wait_for_agent_stops_managed_tree_when_hook_broker_is_lost(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    service.registry.add(record)

    class Process:
        def __init__(self):
            self.calls = 0

        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("codex", timeout)
            return 0

    class Launcher:
        hook_broker = SimpleNamespace(is_running=False)

        @staticmethod
        def request_protection_failure_termination_result(reason):
            return {
                "termination_id": "protection-failure-1",
                "status": "SUCCEEDED",
                "outcome": "TERMINATED",
                "verified_tree_gone": True,
                "reason": reason,
                "control": "PROTECTION_FAILURE",
            }

    try:
        assert service._wait_for_agent(record, Process(), Launcher()) == 0
        assert record.protection_state == "DEGRADED"
        assert record.runtime["protection_failure_reason"] == "HOOK_BROKER_LOST"
        assert record.runtime["protection_failure_termination_result"]["status"] == "SUCCEEDED"
    finally:
        service.shutdown()


def test_request_stop_reports_persisted_terminal_run(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        session_id = "persisted-session"
        monkeypatch.setattr(
            service.reader,
            "read_result",
            lambda requested: {"session_status": "COMPLETED"}
            if requested == session_id
            else {},
        )
        result = service.request_stop(session_id)
        assert result["accepted"] is False
        assert result["status"] == "COMPLETED"
        assert result["reason"] == "RUN_ALREADY_TERMINAL"
    finally:
        service.shutdown()


def test_request_stop_persists_cross_process_user_abort_request(tmp_path, monkeypatch) -> None:
    service = RunApplicationService(tmp_path / "control")
    session_id = str(uuid4())
    monkeypatch.setattr(
        service.reader,
        "read_result",
        lambda requested: (_ for _ in ()).throw(ValueError("not completed")),
    )
    try:
        result = service.request_stop(session_id)
        assert result["accepted"] is True
        assert result["reason"] == "STOP_REQUEST_STORED"
        request_path = tmp_path / "control" / "stop-requests" / f"{session_id}.json"
        assert request_path.is_file()
        assert json.loads(request_path.read_text(encoding="utf-8"))["reason"] == "USER_ABORT"
    finally:
        service.shutdown()


def test_application_failure_moves_phase_to_terminal_failed(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    record.phase = "READY"
    try:
        service._fail_record(record, RuntimeError("launch failed"))
        assert record.status == "FAILED"
        assert record.phase == "FAILED"
        assert "launch failed" in record.error
    finally:
        service.shutdown()


def test_launching_phase_is_visible_while_codex_is_being_registered(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    record = make_record(tmp_path)
    try:
        service.registry.add(record)
        service._phase(record, "LAUNCHING", SessionStatus.READY)
        record.protection_state = "LAUNCHING"
        status = service.get_run_status(record.session_id)
        assert status["phase"] == "LAUNCHING"
        assert status["session"]["status"] == "READY"
        assert status["protection"]["state"] == "LAUNCHING"
    finally:
        service.shutdown()


def test_launching_phase_is_visible_from_persisted_runtime_state(tmp_path) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    record = make_record(tmp_path)
    observer = RunApplicationService(control_root)
    try:
        service.registry.add(record)
        record.protection_state = "LAUNCHING"
        service._phase(record, "LAUNCHING", SessionStatus.READY)
        status = observer.get_run_status(record.session_id)
        assert status["phase"] == "LAUNCHING"
        assert status["protection"]["state"] == "LAUNCHING"
    finally:
        observer.shutdown()
        service.shutdown()


def _orphaned_runtime_state(session_id: str = "session-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "coordinator": {"pid": 4242, "create_time": 10.0},
        "managed_process": {
            "launch_id": "launch-1",
            "launch_provenance": "AIA_SPAWNED_ROOT",
            "root_process_identity": {"pid": 4243, "create_time": 20.0},
        },
        "session": {
            "agent": "codex",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": None,
            "session_id": session_id,
            "status": "RUNNING",
            "workspace": "C:\\workspace\\orphaned",
        },
        "phase": "RUNNING",
        "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1},
        "checkpoint": "READY",
        "lease": "ACTIVE",
        "mode": "ENFORCE",
        "policy": {"id": "policy", "profile": "BASIC_DEVELOPMENT", "version": "1.0.0"},
        "incident_count": 0,
        "latest_actions": [],
        "sensor_health": {},
        "stop": {"requested": False, "error": None},
        "error": None,
        "result_path": None,
        "result_available": False,
    }


def test_persisted_run_reports_orphaned_when_coordinator_is_gone(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    def verify(identity):
        return ProcessIdentityStatus.PROCESS_GONE

    monkeypatch.setattr("aia_app.service.verify_process_identity", verify)
    state = _orphaned_runtime_state()
    service._write_runtime_state_payload("session-1", state)
    try:
        status = service.get_run_status("session-1")
        assert status["session"]["status"] == "RUNNING"
        assert status["protection"]["state"] == "ORPHANED_DEGRADED"
        assert status["runtime_reconciliation"]["orphaned"] is True
        assert status["runtime_reconciliation"]["action"] == "REVIEW_AND_RESTART"
    finally:
        service.shutdown()


def test_orphan_reconcile_requires_recorded_agent_root_to_be_gone(tmp_path, monkeypatch) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    def verify(identity):
        return (
            ProcessIdentityStatus.PROCESS_GONE
            if identity.pid == 4242
            else ProcessIdentityStatus.LIVE_MATCH
        )

    monkeypatch.setattr("aia_app.service.verify_process_identity", verify)
    service._write_runtime_state_payload("session-1", _orphaned_runtime_state())
    try:
        result = service.reconcile_orphaned_run("session-1")
        assert result["reconciled"] is False
        assert result["reason"] == "RECORDED_AGENT_ROOT_NOT_PROVEN_GONE"
        assert not service._read_runtime_state("session-1").get("orphan_reconciliation")
    finally:
        service.shutdown()


def test_orphan_reconcile_acknowledges_only_after_agent_root_identity_is_gone(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)

    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", _orphaned_runtime_state())
    try:
        result = service.reconcile_orphaned_run("session-1")
        assert result["reconciled"] is True
        assert result["reason"] == "ORPHAN_RECONCILED_AFTER_ROOT_CHECK"
        assert result["runtime_reconciliation"]["action"] == "RECONCILED"
        persisted = service._read_runtime_state("session-1")
        assert persisted["orphan_reconciliation"]["status"] == "ACKNOWLEDGED"
    finally:
        service.shutdown()


def test_orphan_reconcile_allows_preparing_run_without_recorded_agent_root(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    state = _orphaned_runtime_state()
    state["managed_process"] = None
    state["session"]["status"] = "PREPARING"
    state["phase"] = "PREPARING"
    state["protection"] = {"state": "STARTING", "hook_events": 0}
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        result = service.reconcile_orphaned_run("session-1")
        assert result["reconciled"] is True
        assert result["reason"] == "ORPHAN_RECONCILED_AFTER_ROOT_CHECK"
        assert result["runtime_reconciliation"]["agent_process_status"] == "NOT_STARTED"
        persisted = service._read_runtime_state("session-1")
        assert persisted["orphan_reconciliation"]["reason"] == "AGENT_ROOT_NOT_STARTED"
    finally:
        service.shutdown()


def test_new_run_refuses_workspace_with_unresolved_orphaned_agent(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    state = _orphaned_runtime_state()
    state["session"]["workspace"] = str(tmp_path)
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: (
            ProcessIdentityStatus.PROCESS_GONE
            if identity.pid == 4242
            else ProcessIdentityStatus.LIVE_MATCH
        ),
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        with pytest.raises(ApplicationValidationError, match="정리되지 않은 이전 Protected Run"):
            service.create_protected_run({"workspace": str(tmp_path), "task": "inspect"})
    finally:
        service.shutdown()


def test_validate_workspace_exposes_orphan_recovery_action(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    state = _orphaned_runtime_state()
    state["session"]["workspace"] = str(tmp_path)
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        result = service.validate_workspace(str(tmp_path))
        assert result["recovery"] == {
            "required": True,
            "session_id": "session-1",
            "status": "STALE_PROCESS_GONE",
            "action": "REVIEW_AND_RESTART",
            "agent_process_status": "PROCESS_GONE",
        }
    finally:
        service.shutdown()


def test_new_run_allows_workspace_after_orphan_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    control_root = tmp_path / "control"
    service = RunApplicationService(control_root)
    service._run = lambda record: None
    state = _orphaned_runtime_state()
    state["session"]["workspace"] = str(tmp_path)
    monkeypatch.setattr(
        "aia_app.service.verify_process_identity",
        lambda identity: ProcessIdentityStatus.PROCESS_GONE,
    )
    service._write_runtime_state_payload("session-1", state)
    try:
        assert service.reconcile_orphaned_run("session-1")["reconciled"] is True
        created = service.create_protected_run({"workspace": str(tmp_path), "task": "inspect"})
        assert created["session_id"]
    finally:
        service.shutdown()
