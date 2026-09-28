"""Benchmark list_runs with mixed runtime-state and Result Bundle histories.

Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\bench_run_history_listing.py

Each documented size is the number of runtime states; half also have a
committed Result Bundle. The other half of each source is source-only, giving
overlapping, runtime-only, and bundle-only sessions. Temporary control roots
are used, and output contains aggregate counts and timings only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from aia import (
    ProcessIdentityStatus,
    ProtectedRunSession,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
)
from aia.evidence import RawEvidenceStore
from aia_app.service import RunApplicationService


RUNTIME_STATE_COUNTS = (100, 500, 1_000, 5_000)
STARTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
OVERLAP_LAUNCH_MODE = "codex_app_server"
RUNTIME_ONLY_LAUNCH_MODE = "web_terminal"


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _runtime_state(
    session_id: str,
    index: int,
    *,
    result_available: bool,
    launch_mode: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "launch_mode": launch_mode,
        "session": {
            "status": "COMPLETED",
            "workspace": "synthetic/workspace",
            "agent": "benchmark",
            "created_at": (STARTED_AT + timedelta(seconds=index)).isoformat(),
        },
        "policy": {"id": "synthetic", "version": "1"},
        "protection": {"state": "COMPLETED", "hook_events": index % 7},
        "incident_count": 0,
        "result_available": result_available,
    }


def _create_bundle(control_root: Path, workspace: Path) -> str:
    now = datetime.now(timezone.utc)
    session = ProtectedRunSession(
        workspace=workspace,
        agent="benchmark",
        mode=SessionMode.ENFORCE,
        policy_id="benchmark-policy",
        policy_version="1.0.0",
        created_at=now,
    )
    for status in (SessionStatus.PREPARING, SessionStatus.READY, SessionStatus.RUNNING):
        session.transition(status, at=now)
    store = RawEvidenceStore.for_session(control_root, session.session_id)
    SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        run_classification="PRODUCT_PROTECTED_RUN",
    )
    return session.session_id


def _validate_listing(
    listed: list[dict[str, object]],
    *,
    runtime_ids: set[str],
    bundle_ids: set[str],
    overlap_ids: set[str],
) -> dict[str, int]:
    expected_ids = runtime_ids | bundle_ids
    listed_ids = [str(item.get("session_id")) for item in listed]
    if len(listed) != len(expected_ids) or set(listed_ids) != expected_ids:
        raise RuntimeError("list_runs returned an unexpected session count")
    if len(listed_ids) != len(set(listed_ids)):
        raise RuntimeError("list_runs returned duplicate sessions")

    sort_keys = [
        str(item.get("ended_at") or item.get("created_at") or "")
        for item in listed
    ]
    if sort_keys != sorted(sort_keys, reverse=True):
        raise RuntimeError("list_runs returned unexpected newest-first ordering")

    by_id = {str(item["session_id"]): item for item in listed}
    runtime_only_ids = runtime_ids - bundle_ids
    bundle_only_ids = bundle_ids - runtime_ids
    for session_id in runtime_only_ids:
        item = by_id[session_id]
        if item.get("run_classification") != "UNVERIFIED_RUNTIME_STATE":
            raise RuntimeError("runtime-only session has an unexpected classification")
        if item.get("launch_mode") != RUNTIME_ONLY_LAUNCH_MODE:
            raise RuntimeError("runtime-only session has an unexpected launch mode")
    for session_id in bundle_only_ids:
        item = by_id[session_id]
        if item.get("run_classification") != "PRODUCT_PROTECTED_RUN":
            raise RuntimeError("bundle-only session has an unexpected classification")
        if item.get("launch_mode") != "inherit":
            raise RuntimeError("bundle-only session has an unexpected launch mode")
    for session_id in overlap_ids:
        item = by_id[session_id]
        if item.get("run_classification") != "PRODUCT_PROTECTED_RUN":
            raise RuntimeError("overlapping session has an unexpected classification")
        if item.get("launch_mode") != OVERLAP_LAUNCH_MODE:
            raise RuntimeError("overlapping session lost runtime launch-mode metadata")

    return {
        "returned": len(listed),
        "runtime_only": len(runtime_only_ids),
        "bundle_only": len(bundle_only_ids),
        "overlap": len(overlap_ids),
    }


def _benchmark(
    runtime_state_count: int,
    runs: int,
) -> tuple[list[float], list[float], dict[str, int], int]:
    bundle_count = runtime_state_count // 2
    with TemporaryDirectory(prefix="aia-run-history-bench-") as temporary_root:
        control_root = Path(temporary_root) / "control"
        workspace = Path(temporary_root) / "workspace"
        workspace.mkdir()
        service = RunApplicationService(control_root, max_workers=1)
        try:
            bundle_ids = {
                _create_bundle(control_root, workspace)
                for _ in range(bundle_count)
            }
            overlap_ids = set(sorted(bundle_ids)[: bundle_count // 2])
            runtime_only_count = runtime_state_count - len(overlap_ids)
            runtime_ids = set(overlap_ids)
            for index in range(runtime_only_count):
                session_id = f"bench-runtime-{index:06d}"
                runtime_ids.add(session_id)
                service._write_runtime_state_payload(
                    session_id,
                    _runtime_state(
                        session_id,
                        index,
                        result_available=False,
                        launch_mode=RUNTIME_ONLY_LAUNCH_MODE,
                    ),
                )
            for index, session_id in enumerate(sorted(overlap_ids)):
                service._write_runtime_state_payload(
                    session_id,
                    _runtime_state(
                        session_id,
                        index,
                        result_available=True,
                        launch_mode=OVERLAP_LAUNCH_MODE,
                    ),
                )

            cold_timings: list[float] = []
            repeated_timings: list[float] = []
            summary: dict[str, int] = {}
            for _ in range(runs):
                cold_service = RunApplicationService(control_root, max_workers=1)
                try:
                    started = perf_counter()
                    listed = cold_service.list_runs()
                    cold_timings.append((perf_counter() - started) * 1000)
                    summary = _validate_listing(
                        listed,
                        runtime_ids=runtime_ids,
                        bundle_ids=bundle_ids,
                        overlap_ids=overlap_ids,
                    )
                finally:
                    cold_service.shutdown()

            for batch_start in range(0, runs, 3):
                repeated_service = RunApplicationService(control_root, max_workers=1)
                try:
                    warmed = repeated_service.list_runs()
                    summary = _validate_listing(
                        warmed,
                        runtime_ids=runtime_ids,
                        bundle_ids=bundle_ids,
                        overlap_ids=overlap_ids,
                    )
                    for _ in range(min(3, runs - batch_start)):
                        started = perf_counter()
                        listed = repeated_service.list_runs()
                        repeated_timings.append((perf_counter() - started) * 1000)
                        summary = _validate_listing(
                            listed,
                            runtime_ids=runtime_ids,
                            bundle_ids=bundle_ids,
                            overlap_ids=overlap_ids,
                        )
                finally:
                    repeated_service.shutdown()
            return cold_timings, repeated_timings, summary, bundle_count
        finally:
            service.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=7, help="measured calls per size (minimum 3)")
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")

    collection_sizes = ",".join(str(count) for count in RUNTIME_STATE_COUNTS)
    print(f"runs_per_size={args.runs} collection_sizes={collection_sizes}")
    for runtime_state_count in RUNTIME_STATE_COUNTS:
        cold_timings, repeated_timings, counts, bundle_count = _benchmark(
            runtime_state_count,
            args.runs,
        )
        print(
            f"runtime_states={runtime_state_count} result_bundles={bundle_count} "
            f"returned={counts['returned']} runtime_only={counts['runtime_only']} "
            f"bundle_only={counts['bundle_only']} overlap={counts['overlap']} "
            f"cold_p50={median(cold_timings):.3f}ms "
            f"cold_p95={_percentile(cold_timings, 0.95):.3f}ms "
            f"repeated_p50={median(repeated_timings):.3f}ms "
            f"repeated_p95={_percentile(repeated_timings, 0.95):.3f}ms"
        )
    print("fixture=synthetic_mixed_history payload_output=none")


if __name__ == "__main__":
    main()
