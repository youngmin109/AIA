"""Benchmark Workbench notification normalization, append, and replay.

Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\bench_workbench_event_buffer.py

The fixture is synthetic and stays in memory. Output contains event counts and
timings only; no conversation or tool payload is printed or persisted.
"""

from __future__ import annotations

import argparse
from statistics import median
from time import perf_counter

from aia_app.codex_app_server import CodexAppServerSession, normalize_notification


EVENT_COUNTS = (100, 1_000, 4_000, 10_000)
NOTIFICATION_METHOD = "item/agentMessage/delta"
NOTIFICATION_PARAMS = {"itemId": "benchmark-item", "delta": "synthetic"}


def _measure_normalization(event_count: int, runs: int) -> float:
    timings = []
    for _ in range(runs):
        started = perf_counter()
        for _ in range(event_count):
            if normalize_notification(NOTIFICATION_METHOD, NOTIFICATION_PARAMS) is None:
                raise RuntimeError("benchmark notification was not normalized")
        timings.append((perf_counter() - started) * 1000)
    return median(timings)


def _measure_append(event_count: int, runs: int) -> tuple[float, int, int]:
    timings = []
    retained_count = 0
    buffer_limit = CodexAppServerSession.MAX_EVENTS
    event = normalize_notification(NOTIFICATION_METHOD, NOTIFICATION_PARAMS)
    if event is None:
        raise RuntimeError("benchmark notification was not normalized")

    for _ in range(runs):
        session = CodexAppServerSession(["benchmark"], cwd=".", env={})
        started = perf_counter()
        for _ in range(event_count):
            session._append_event(dict(event))
        timings.append((perf_counter() - started) * 1000)
        retained_count = len(session._events)
        if retained_count != min(event_count, buffer_limit):
            raise RuntimeError("event buffer retained an unexpected count")
    return median(timings), retained_count, buffer_limit


def _measure_replay(event_count: int, runs: int) -> tuple[float, int, int]:
    session = CodexAppServerSession(["benchmark"], cwd=".", env={})
    event = normalize_notification(NOTIFICATION_METHOD, NOTIFICATION_PARAMS)
    if event is None:
        raise RuntimeError("benchmark notification was not normalized")
    for _ in range(event_count):
        session._append_event(dict(event))

    expected_count = min(event_count, session.MAX_EVENTS)
    timings = []
    replayed_count = 0
    for _ in range(runs):
        started = perf_counter()
        replayed = session.read_events()
        timings.append((perf_counter() - started) * 1000)
        replayed_count = len(replayed)
        if replayed_count != expected_count:
            raise RuntimeError("replay returned an unexpected event count")
        if replayed and replayed[-1]["sequence"] != event_count:
            raise RuntimeError("replay did not include the latest sequence")
    return median(timings), replayed_count, session.MAX_EVENTS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="measured runs per operation (minimum 3)")
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")

    print(f"runs_per_operation={args.runs} buffer_limit={CodexAppServerSession.MAX_EVENTS}")
    for event_count in EVENT_COUNTS:
        normalization_ms = _measure_normalization(event_count, args.runs)
        append_ms, retained_count, buffer_limit = _measure_append(event_count, args.runs)
        replay_ms, replayed_count, _ = _measure_replay(event_count, args.runs)
        print(
            f"events={event_count} retained={retained_count} replayed={replayed_count} "
            f"buffer_limit={buffer_limit} normalize_ms_p50={normalization_ms:.3f} "
            f"append_ms_p50={append_ms:.3f} replay_ms_p50={replay_ms:.3f}"
        )
    print("fixture=synthetic_in_memory payload_output=none persistence=none")


if __name__ == "__main__":
    main()
