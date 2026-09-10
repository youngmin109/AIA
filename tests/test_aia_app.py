from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest

from aia_app.dto import CreateRunRequest, DTOValidationError
from aia_app.presenters import action_view, incident_view, result_view
from aia_app.readers import ResultBundleReader
from aia_app.registry import RunRecord, RunRegistry
from aia_app.service import ApplicationValidationError, RunApplicationService


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


def test_result_bundle_reader_rejects_path_traversal_and_unverified_bundle(tmp_path) -> None:
    reader = ResultBundleReader(tmp_path)
    with pytest.raises(ValueError, match="invalid session_id"):
        reader.session_directory("../secret")
    with pytest.raises(ValueError, match="Integrity Failure"):
        reader.read_result("missing-session")


def test_application_exposes_fixed_profile_choices(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    try:
        profiles = service.policy_profiles()
        assert {item["value"] for item in profiles} == {
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
            "CUSTOM",
        }
        assert all(item["description"] for item in profiles)
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
