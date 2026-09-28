"""Measure process sensor tree polling on a deterministic fake process tree."""

from __future__ import annotations

from time import perf_counter

import psutil

from aia import ProcessIdentity
from aia.sensors.process import ProcessRole
from aia.sensors.process import ProcessRuntimeSensor


class FakeProcess:
    def __init__(self, pid: int, ppid: int) -> None:
        self.pid = pid
        self._ppid = ppid
        self._children: list[FakeProcess] = []
        self.system_processes: dict[int, FakeProcess] = {}

    def create_time(self) -> float:
        return float(self.pid)

    def ppid(self) -> int:
        return self._ppid

    def children(self, recursive: bool = False) -> list[FakeProcess]:
        # psutil children() snapshots the process table for each queried node.
        return [
            process
            for process in self.system_processes.values()
            if process._ppid == self.pid
        ]

    def name(self) -> str:
        return f"process-{self.pid}"

    def exe(self) -> str:
        return f"/fake/process-{self.pid}"

    def cmdline(self) -> list[str]:
        return [self.exe()]


class SnapshotProcess:
    def __init__(self, process: FakeProcess) -> None:
        self._process = process
        self.pid = process.pid
        self.info = {"pid": process.pid, "ppid": process._ppid}

    def create_time(self) -> float:
        return self._process.create_time()

    def __getattr__(self, name: str):
        return getattr(self._process, name)


def build_tree(size: int) -> tuple[FakeProcess, dict[int, FakeProcess]]:
    processes: dict[int, FakeProcess] = {}
    for pid in range(1, size + 1):
        parent_pid = pid // 2 if pid > 1 else 0
        process = FakeProcess(pid, parent_pid)
        process.system_processes = processes
        processes[pid] = process
        if parent_pid:
            processes[parent_pid]._children.append(process)
    return processes[1], processes


def old_poll(sensor: ProcessRuntimeSensor, root: FakeProcess) -> None:
    root_identity = sensor.registration.root_process_identity
    sensor._metadata_cache = {}
    current = {
        root_identity: sensor._build_observation(
            root,
            root_identity,
            ProcessRole.ROOT,
            root_identity,
            parent_identity=None,
        )
    }
    stack = [(root, root_identity)]
    while stack:
        parent_process, parent_identity = stack.pop()
        for child_process in parent_process.children(recursive=False):
            identity, live_process = sensor._child_identity(child_process)
            if identity is None or live_process is None or identity in current:
                continue
            observation = sensor._build_observation(
                live_process,
                identity,
                ProcessRole.DESCENDANT,
                root_identity,
                parent_identity=parent_identity,
            )
            current[identity] = observation
            stack.append((live_process, identity))


def main() -> None:
    root, processes = build_tree(512)
    sensor = ProcessRuntimeSensor.__new__(ProcessRuntimeSensor)
    sensor.registration = type(
        "Registration", (), {"root_process_identity": ProcessIdentity(1, 1.0)}
    )()
    sensor.process_factory = processes.__getitem__
    sensor.capture_command_line = True
    sensor._metadata_cache = {}
    original_process_iter = psutil.process_iter
    psutil.process_iter = lambda attrs: (
        SnapshotProcess(process) for process in processes.values()
    )
    try:
        sensor._collect_tree(root)  # Warm the static metadata cache.
        iterations = 100
        started = perf_counter()
        for _ in range(iterations):
            old_poll(sensor, root)
        before_ms = (perf_counter() - started) * 1000 / iterations

        started = perf_counter()
        for _ in range(iterations):
            sensor._collect_tree(root)
        after_ms = (perf_counter() - started) * 1000 / iterations
    finally:
        psutil.process_iter = original_process_iter
    print(f"fake_tree_processes=512 iterations={iterations}")
    print(f"before_ms_per_poll={before_ms:.3f}")
    print(f"after_ms_per_poll={after_ms:.3f}")
    print(f"speedup={before_ms / after_ms:.2f}x")


if __name__ == "__main__":
    main()
