from pathlib import Path

from scripts.product_evaluation.build_report import load_runs
from scripts.product_evaluation.run_fixture_evaluation import run_fixture_evaluation


def test_fixture_runner_records_both_recovery_axes_and_policy_block(tmp_path: Path) -> None:
    raw_path = run_fixture_evaluation(
        tmp_path / "evaluation",
        repetitions=1,
        evaluation_id="fixture-test",
    )

    rows = load_runs(raw_path)

    assert len(rows) == 26
    secret_block = next(
        row
        for row in rows
        if row["scenario_id"] == "V-01" and row["condition"] == "AIA_ON"
    )
    assert secret_block["policy_decision"] == "VIOLATION"
    assert secret_block["enforcement_action"] == "BLOCKED"
    assert secret_block["side_effect_observed"] is False
    assert secret_block["matched_asset_type"] == "SECRET"
    assert {row["integrity_status"] for row in rows if row["scenario_id"] == "R-01" and row["condition"] == "AIA_ON"} == {
        "VERIFIED",
        "FAILED",
    }
