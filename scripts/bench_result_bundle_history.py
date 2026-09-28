"""Benchmark ResultBundleReader history scans over committed bundles.

Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\bench_result_bundle_history.py

By default this creates 100 valid bundles in a temporary directory, measures
20 cold scans (a fresh reader each time) and 20 warm scans (one reused reader),
and checks every returned bundle's verification status on every scan.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
from aia_app.readers import ResultBundleReader
from aia.evidence import (
    EvidenceRecordType,
    EvidenceSource,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _create_bundles(
    control_root: Path,
    count: int,
    evidence_records_per_bundle: int,
) -> list[str]:
    workspace = control_root.parent / "workspace"
    workspace.mkdir()
    session_ids: list[str] = []
    now = datetime.now(timezone.utc)
    for index in range(count):
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
        for record_index in range(evidence_records_per_bundle):
            store.append(
                RawEvidenceRecord(
                    session_id=session.session_id,
                    source=EvidenceSource.AGENT_HOOK,
                    record_type=EvidenceRecordType.PRETOOL_REQUEST,
                    captured_at=now,
                    observation_stage=ObservationStage.PRE_ACTION,
                    payload={"benchmark_record": record_index},
                )
            )
        SessionFinalizer(evidence_store=store).finalize(
            session,
            process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        )
        session_ids.append(session.session_id)
    return session_ids


def _measure_scan(
    reader_factory,
    expected_ids: set[str],
    expected_hook_event_count: int,
) -> float:
    reader = reader_factory()
    started = perf_counter()
    bundles = reader.list_completed()
    elapsed_ms = (perf_counter() - started) * 1000
    returned_ids = {str(item["session_id"]) for item in bundles}
    if returned_ids != expected_ids or len(bundles) != len(expected_ids):
        raise RuntimeError(
            f"scan returned {len(bundles)} bundles; expected {len(expected_ids)}"
        )
    invalid = [item["session_id"] for item in bundles if item["bundle_status"] != "VALID"]
    if invalid:
        raise RuntimeError(f"scan returned non-valid bundles: {invalid[:5]}")
    incorrect_counts = [
        (item["session_id"], item["hook_event_count"])
        for item in bundles
        if item["hook_event_count"] != expected_hook_event_count
    ]
    if incorrect_counts:
        raise RuntimeError(
            "scan returned bundles with unexpected hook event counts: "
            f"{incorrect_counts[:5]} (expected {expected_hook_event_count})"
        )
    return elapsed_ms


def _measure(
    control_root: Path,
    expected_ids: set[str],
    expected_hook_event_count: int,
    iterations: int,
) -> tuple[list[float], list[float]]:
    cold_ms: list[float] = []
    warm_ms: list[float] = []
    warm_reader = ResultBundleReader(control_root)
    for _ in range(iterations):
        # A fresh reader excludes the parsed result and evidence metadata caches.
        cold_ms.append(
            _measure_scan(
                lambda: ResultBundleReader(control_root),
                expected_ids,
                expected_hook_event_count,
            )
        )
        warm_ms.append(
            _measure_scan(lambda: warm_reader, expected_ids, expected_hook_event_count)
        )
    return cold_ms, warm_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles", type=int, default=100, help="valid bundles to create (minimum 100)")
    parser.add_argument(
        "--evidence-records-per-bundle",
        type=int,
        default=10,
        help="AGENT_HOOK PRETOOL_REQUEST records to create in each bundle",
    )
    parser.add_argument("--iterations", type=int, default=20, help="scans per cold and warm measurement")
    args = parser.parse_args()
    if args.bundles < 100:
        parser.error("--bundles must be at least 100")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if args.evidence_records_per_bundle < 0:
        parser.error("--evidence-records-per-bundle must be non-negative")

    with TemporaryDirectory(prefix="aia-result-history-bench-") as temporary:
        root = Path(temporary) / "control"
        expected_ids = set(
            _create_bundles(root, args.bundles, args.evidence_records_per_bundle)
        )
        cold_ms, warm_ms = _measure(
            root,
            expected_ids,
            args.evidence_records_per_bundle,
            args.iterations,
        )

    print(
        f"bundles={args.bundles} evidence_records_per_bundle={args.evidence_records_per_bundle} "
        f"total_evidence_records={args.bundles * args.evidence_records_per_bundle} "
        f"iterations_per_mode={args.iterations}"
    )
    print(
        f"scan_validation=all {args.bundles} bundles returned with bundle_status=VALID "
        f"and hook_event_count={args.evidence_records_per_bundle}"
    )
    print(f"cold_ms_p50={median(cold_ms):.3f} cold_ms_p95={_percentile(cold_ms, 0.95):.3f}")
    print(f"warm_ms_p50={median(warm_ms):.3f} warm_ms_p95={_percentile(warm_ms, 0.95):.3f}")


if __name__ == "__main__":
    main()
