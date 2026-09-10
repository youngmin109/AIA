from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.product_evaluation.build_report import (
    EvaluationDataError,
    build_summary,
    load_runs,
    statistics_for,
)
from scripts.product_evaluation.scenarios import SCENARIOS


def _run(
    *,
    condition: str,
    repetition: int,
    scenario_id: str = "V-01",
    side_effect: bool = False,
    task_succeeded: bool = False,
    enforcement_action: str = "BLOCKED",
    elapsed_ms: float = 100.0,
    **extra,
) -> dict:
    return {
        "evaluation_id": "eval-test",
        "scenario_id": scenario_id,
        "condition": condition,
        "repetition": repetition,
        "agent": "fixture",
        "workspace_seed": f"seed-{repetition}-{condition}",
        "scenario_realized": True,
        "task_succeeded": task_succeeded,
        "side_effect_observed": side_effect,
        "policy_decision": "VIOLATION",
        "enforcement_action": enforcement_action,
        "execution_result": "SUCCEEDED",
        "recovery_status": "NOT_ATTEMPTED",
        "integrity_status": "NOT_CHECKED",
        "elapsed_ms": elapsed_ms,
        **extra,
    }


def test_scenario_matrix_contains_twelve_fixed_groups() -> None:
    assert len(SCENARIOS) == 12
    assert {item.scenario_id for item in SCENARIOS} == {
        "N-01",
        "N-02",
        "N-03",
        "N-04",
        "N-05",
        "N-06",
        "V-01",
        "V-02",
        "V-03",
        "V-04",
        "U-01",
        "R-01",
    }


def test_statistics_for_uses_nearest_rank_p95() -> None:
    result = statistics_for([1, 2, 3, 4, 5])

    assert result == {"n": 5, "min": 1.0, "median": 3.0, "p95": 5, "max": 5.0}


def test_summary_reports_before_after_security_rates_and_reduction() -> None:
    rows = [
        _run(condition="AIA_OFF", repetition=1, side_effect=True),
        _run(condition="AIA_OFF", repetition=2, side_effect=True),
        _run(condition="AIA_ON", repetition=1, side_effect=False),
        _run(condition="AIA_ON", repetition=2, side_effect=False),
    ]

    summary = build_summary(rows)

    assert summary["security"]["risk_side_effect_rate"]["AIA_OFF"]["rate"] == 1.0
    assert summary["security"]["risk_side_effect_rate"]["AIA_ON"]["rate"] == 0.0
    assert summary["risk_reduction_rate"] == 1.0


def test_summary_keeps_not_applicable_metrics_out_of_denominator() -> None:
    rows = [
        _run(
            condition="AIA_OFF",
            repetition=1,
            pretool_block_succeeded="NOT_APPLICABLE",
        ),
        _run(
            condition="AIA_ON",
            repetition=1,
            pretool_block_succeeded=True,
        ),
    ]

    summary = build_summary(rows)

    assert summary["security"]["pretool_block_success_rate"]["AIA_OFF"] is None
    assert summary["security"]["pretool_block_success_rate"]["AIA_ON"]["rate"] == 1.0


def test_summary_reports_quality_rates_and_timing_delta() -> None:
    rows = [
        _run(
            condition="AIA_OFF",
            repetition=1,
            elapsed_ms=100,
            decision_consistent=True,
            over_attributed=False,
        ),
        _run(
            condition="AIA_ON",
            repetition=1,
            elapsed_ms=125,
            decision_consistent=True,
            over_attributed=True,
        ),
    ]

    summary = build_summary(rows)

    assert summary["quality"]["decision_consistency_rate"]["AIA_ON"]["rate"] == 1.0
    assert summary["quality"]["over_attribution_rate"]["AIA_ON"]["rate"] == 1.0
    assert summary["timing_deltas"]["elapsed_ms"] == {
        "median_ms": 25.0,
        "p95_ms": 25.0,
    }


def test_load_runs_rejects_unknown_scenario(tmp_path: Path) -> None:
    path = tmp_path / "raw-runs.jsonl"
    row = _run(condition="AIA_ON", repetition=1)
    row["scenario_id"] = "UNKNOWN"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(EvaluationDataError, match="unknown scenario_id"):
        load_runs(path)


def test_load_runs_rejects_mixed_evaluation_ids(tmp_path: Path) -> None:
    path = tmp_path / "raw-runs.jsonl"
    first = _run(condition="AIA_ON", repetition=1)
    second = _run(condition="AIA_ON", repetition=2)
    second["evaluation_id"] = "other"
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EvaluationDataError, match="one evaluation_id"):
        load_runs(path)
