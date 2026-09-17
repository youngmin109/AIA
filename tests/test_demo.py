from __future__ import annotations

import json
from pathlib import Path

import pytest

from aia import BundleVerificationStatus
from aia.demo import DEMO_SCENARIOS, run_demo
from aia_app.readers import ResultBundleReader


@pytest.mark.parametrize("scenario", DEMO_SCENARIOS)
def test_demo_publishes_a_verified_fixture_bundle(
    scenario: str,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    control_root = tmp_path / "control"

    result = run_demo(scenario, workspace=workspace, control_root=control_root)
    reader = ResultBundleReader(control_root)
    session_id = result["session_id"]

    verification = reader.verification(session_id)
    assert verification is not None
    assert verification.status is BundleVerificationStatus.VALID
    completed = reader.list_completed()
    assert completed[0]["run_classification"] == "ENGINEERING_FIXTURE"
    assert completed[0]["protection_state"] == "COMPLETED_VERIFIED"

    result_json = reader.read_result(session_id)
    assert result_json["run_classification"] == "ENGINEERING_FIXTURE"
    assert "DEMO_FIXTURE" in "\n".join(result_json["limitations"])

    evidence = reader.read_evidence_metadata(session_id)
    assert evidence
    assert all("payload" not in item for item in evidence)

    raw_result = json.dumps(result_json, ensure_ascii=False)
    assert "fixture-secret-marker" not in raw_result
    assert "destructive_fixture.py" not in raw_result

    if scenario == "process-kill":
        assert result_json["process_termination_result"]["action"] == "TERMINATED"
        assert result_json["process_termination_result"]["unrelated_process_affected"] is False
        assert any(item["record_type"] == "PROCESS_OBSERVED" for item in evidence)
    elif scenario == "hook-block":
        assert result_json["enforcement_results"][0]["enforcement_action"] == "BLOCKED"
        assert result_json["process_termination_result"] is None
        assert any(item["record_type"] == "PRETOOL_REQUEST" for item in evidence)
    else:
        assert result_json["recovery_result"]["recovery_status"] == "RESTORED"
        assert result_json["integrity_result"]["integrity_status"] == "VERIFIED"
        assert any(item["record_type"] == "FILESYSTEM_EVENT" for item in evidence)


def test_demo_refuses_to_reset_an_unmarked_nonempty_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "existing"
    workspace.mkdir()
    (workspace / "user-file.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to reset"):
        run_demo(
            "hook-block",
            workspace=workspace,
            control_root=tmp_path / "control",
        )

    assert (workspace / "user-file.txt").read_text(encoding="utf-8") == "keep me"
