"""Benchmark list_runs with growing persisted runtime-state collections.

Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\bench_run_history_listing.py

Synthetic runtime snapshots are written to temporary control roots. Completed
Result Bundle history is held empty so timings isolate runtime-state listing;
the benchmark prints aggregate counts and timings only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from aia_app.service import RunApplicationService


RUNTIME_STATE_COUNTS = (100, 1_000, 5_000)
STARTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _runtime_state(session_id: str, index: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "session": {
            "status": "COMPLETED",
            "workspace": "synthetic/workspace",
            "agent": "benchmark",
            "created_at": (STARTED_AT + timedelta(seconds=index)).isoformat(),
        },
        "policy": {"id": "synthetic", "version": "1"},
        "protection": {"state": "COMPLETED", "hook_events": index % 7},
        "incident_count": 0,
        "result_available": False,
    }


def _benchmark(runtime_state_count: int, runs: int) -> list[float]:
    expected_ids = [
        f"bench-session-{index:06d}"
        for index in reversed(range(runtime_state_count))
    ]
    with TemporaryDirectory(prefix="aia-run-history-bench-") as temporary_root:
        service = RunApplicationService(temporary_root, max_workers=1)
        # Keep the Result Bundle history scan out of this measurement. No
        # runtime fixture points at or contains a Result Bundle.
        service._list_completed_runs = lambda: []
        try:
            for index in range(runtime_state_count):
                session_id = f"bench-session-{index:06d}"
                service._write_runtime_state_payload(
                    session_id,
                    _runtime_state(session_id, index),
                )

            timings: list[float] = []
            listed_ids: list[str] = []
            for _ in range(runs):
                started = perf_counter()
                listed = service.list_runs()
                timings.append((perf_counter() - started) * 1000)
                listed_ids = [item["session_id"] for item in listed]
                if len(listed) != runtime_state_count:
                    raise RuntimeError("list_runs returned an unexpected run count")
                if listed_ids != expected_ids:
                    raise RuntimeError("list_runs returned unexpected run ordering")
            return timings
        finally:
            service.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=7, help="measured calls per size (minimum 3)")
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")

    print(f"runs_per_size={args.runs} history_source=empty")
    for runtime_state_count in RUNTIME_STATE_COUNTS:
        timings = _benchmark(runtime_state_count, args.runs)
        print(
            f"runtime_states={runtime_state_count} returned={runtime_state_count} "
            f"list_runs_ms_p50={median(timings):.3f} "
            f"p95={_percentile(timings, 0.95):.3f} ordering=newest_first"
        )
    print("fixture=synthetic_persisted_runtime_states payload_output=none")


if __name__ == "__main__":
    main()
