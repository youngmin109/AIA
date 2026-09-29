"""Measure process-tree collection with the per-poll PPID snapshot disabled.

The baseline wrapper repeats the former per-identity ppid() read. Both modes
observe real helper processes through psutil, and alternate order to reduce drift.
Run from the repository root with:
    .venv\\Scripts\\python.exe scripts\\benchmarks\\bench_process_sensor_fallback.py
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from test_process_sensor import prepared_process_inputs, release_lease
from aia import ProcessIdentity, ProcessRuntimeSensor


def _launch_node(role: str) -> None:
    child_count = {"root": 5, "branch": 3, "leaf": 0}[role]
    for _ in range(child_count):
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "node",
                "branch" if role == "root" else "leaf",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    while True:
        time.sleep(60)


def _run_measurement() -> None:
    root = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "node", "root"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        root_process = psutil.Process(root.pid)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if len(root_process.children(recursive=True)) >= 20:
                break
            time.sleep(0.1)
        nodes = root_process.children(recursive=True)
        if len(nodes) < 20:
            raise RuntimeError(f"real process tree did not start: {len(nodes) + 1} nodes")

        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp_name:
            temp_path = Path(temp_name)
            workspace, session, context, lease_manager, checkpoint, registration = (
                prepared_process_inputs(temp_path)
            )
            registration = replace(
                registration,
                root_process_identity=ProcessIdentity(
                    root.pid,
                    root_process.create_time(),
                ),
                registration_source="REAL_PROCESS_BENCHMARK",
            )
            sensor = ProcessRuntimeSensor(
                session,
                context,
                checkpoint,
                registration,
                lease_manager=lease_manager,
                process_factory=psutil.Process,
                ppid_snapshot=lambda: None,
            )
            try:
                durations = {"baseline": [], "optimized": []}
                observations = {}
                optimized_builder = sensor._build_observation

                def baseline_builder(
                    process,
                    identity,
                    role,
                    root_identity,
                    *,
                    parent_identity,
                    ppid=None,
                ):
                    if ppid is None:
                        ppid = sensor._read_ppid(process)
                    return optimized_builder(
                        process,
                        identity,
                        role,
                        root_identity,
                        parent_identity=parent_identity,
                        ppid=ppid,
                    )

                for iteration in range(4):
                    order = (
                        ("baseline", "optimized")
                        if iteration % 2 == 0
                        else ("optimized", "baseline")
                    )
                    for mode in order:
                        sensor._build_observation = (
                            baseline_builder
                            if mode == "baseline"
                            else optimized_builder
                        )
                        started = time.perf_counter()
                        observations = sensor._collect_tree(root_process)
                        durations[mode].append(
                            (time.perf_counter() - started) * 1000
                        )
                        sensor._observed.update(observations)
                sensor._build_observation = optimized_builder
                print(
                    f"nodes={len(observations)} initially_listed={len(nodes) + 1} "
                    f"polls_per_mode={len(durations['baseline'])} "
                    f"baseline_median_ms={statistics.median(durations['baseline']):.3f} "
                    f"optimized_median_ms={statistics.median(durations['optimized']):.3f}"
                )
            finally:
                release_lease(context, lease_manager)
    finally:
        try:
            descendants = psutil.Process(root.pid).children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            descendants = []
        processes = descendants + [psutil.Process(root.pid)]
        for process in processes:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(processes, timeout=3)
        for process in processes:
            try:
                if process.is_running():
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            root.wait(timeout=3)
        except subprocess.TimeoutExpired:
            root.kill()
            root.wait()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "node":
        _launch_node(sys.argv[2])
    else:
        _run_measurement()
