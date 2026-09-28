"""Benchmark Evidence Chain presenters with deterministic large inputs.

Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\bench_evidence_chain_presenters.py

The fixture contains 1,000 actions and 10,000 metadata records. Each presenter
is measured independently; output contains timings and aggregate link counts only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median
from time import perf_counter
from typing import Callable

from aia_app.presenters import evidence_chain_views, evidence_timeline_views


ACTION_COUNT = 1_000
METADATA_COUNT = 10_000
CHAIN_LIMIT = 20
TIMELINE_LIMIT = 80


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    actions = [
        {
            "action_id": f"action-{index:04d}",
            "operation": "EXECUTE",
            "evidence_ids": [f"evidence-{index:05d}"],
        }
        for index in range(ACTION_COUNT)
    ]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    metadata: list[dict[str, object]] = []
    for index in range(METADATA_COUNT):
        linked_index = index - (METADATA_COUNT - ACTION_COUNT)
        evidence_id = (
            f"evidence-{linked_index:05d}"
            if linked_index >= 0
            else f"unlinked-{index:05d}"
        )
        metadata.append(
            {
                "evidence_id": evidence_id,
                "captured_at": (start + timedelta(seconds=index)).isoformat(),
                "line": index + 1,
                "source": "AGENT_HOOK" if index % 3 == 0 else "PROCESS_RUNTIME",
                "record_type": "PRETOOL_REQUEST" if index % 3 == 0 else "PROCESS_OBSERVED",
                # The presenter must not copy this payload into its display view.
                "payload": "BENCHMARK_PRIVATE_PAYLOAD",
            }
        )
    return actions, metadata


def _measure(label: str, presenter: Callable[[], list[dict[str, object]]], runs: int) -> tuple[list[float], list[dict[str, object]]]:
    timings: list[float] = []
    result: list[dict[str, object]] = []
    for _ in range(runs):
        started = perf_counter()
        result = presenter()
        timings.append((perf_counter() - started) * 1000)
    if "BENCHMARK_PRIVATE_PAYLOAD" in repr(result):
        raise RuntimeError(f"{label} view included fixture payload")
    return timings, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="measured runs per presenter (minimum 3)")
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")

    actions, metadata = _fixture()
    chain_times, chains = _measure(
        "evidence_chain_views",
        lambda: evidence_chain_views(actions, evidence_metadata=metadata, limit=CHAIN_LIMIT),
        args.runs,
    )
    timeline_times, timeline = _measure(
        "evidence_timeline_views",
        lambda: evidence_timeline_views(metadata, actions=actions, limit=TIMELINE_LIMIT),
        args.runs,
    )

    expected_timeline_ids = {f"evidence-{index:05d}" for index in range(920, 1_000)}
    linked_chains = sum(chain["evidence_link_status"] == "LINKED" for chain in chains)
    linked_timeline = sum(record["link_status"] == "LINKED" for record in timeline)
    actual_timeline_ids = {record["evidence_id"] for record in timeline}
    if len(chains) != CHAIN_LIMIT or linked_chains != CHAIN_LIMIT:
        raise RuntimeError("chain result count or expected evidence links were incorrect")
    if len(timeline) != TIMELINE_LIMIT or actual_timeline_ids != expected_timeline_ids:
        raise RuntimeError("timeline result count or bounded records were incorrect")
    if linked_timeline != TIMELINE_LIMIT:
        raise RuntimeError("timeline action links were incorrect")

    print(f"actions={ACTION_COUNT} metadata_records={METADATA_COUNT} runs_per_presenter={args.runs}")
    print(f"chain_results={len(chains)} linked_chains={linked_chains} limit={CHAIN_LIMIT}")
    print(f"timeline_results={len(timeline)} linked_records={linked_timeline} limit={TIMELINE_LIMIT}")
    print(
        f"evidence_chain_views_ms_p50={median(chain_times):.3f} "
        f"p95={_percentile(chain_times, 0.95):.3f}"
    )
    print(
        f"evidence_timeline_views_ms_p50={median(timeline_times):.3f} "
        f"p95={_percentile(timeline_times, 0.95):.3f}"
    )
    print(
        "timeline_selection=bounded latest-record selection; "
        "chain indexing scans metadata twice, then processes only the bounded action slice"
    )
    print("payload_output=none")


if __name__ == "__main__":
    main()
