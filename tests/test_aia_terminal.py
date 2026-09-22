from __future__ import annotations

import os
import sys
from collections import deque
from datetime import datetime, timezone
from threading import Lock

import pytest

from aia_app.terminal import _OutputChunk, TerminalSessionError, WinPtyTerminalSession


def test_workbench_submit_input_writes_dedicated_control_key() -> None:
    class FakePty:
        def __init__(self) -> None:
            self.writes = []

        def isalive(self) -> bool:
            return True

        def write(self, value: str) -> None:
            self.writes.append(value)

    pty = FakePty()
    session = object.__new__(WinPtyTerminalSession)
    session._pty = pty
    session._lock = Lock()

    session.submit_input()

    assert pty.writes == ["\x18"]


def test_terminal_output_can_be_replayed_without_consuming_the_bounded_buffer() -> None:
    session = object.__new__(WinPtyTerminalSession)
    session._lock = Lock()
    session._chunks = deque(
        [
            _OutputChunk(1, "first", datetime.now(timezone.utc)),
            _OutputChunk(2, "second", datetime.now(timezone.utc)),
        ]
    )
    session._buffered_chars = len("firstsecond")

    assert [item["sequence"] for item in session.read_output()] == [1, 2]
    assert [item["sequence"] for item in session.read_output(after_sequence=1)] == [2]
    assert [item["sequence"] for item in session.read_output()] == [1, 2]
    assert [item["sequence"] for item in session.drain_output()] == [1, 2]
    assert session.read_output() == []


def test_workbench_terminal_uses_winpty_backend_for_packaged_windows_runs() -> None:
    assert WinPtyTerminalSession.PTY_BACKEND == 1


@pytest.mark.skipif(os.name != "nt", reason="Workbench terminal requires Windows PTY")
def test_winpty_terminal_supports_input_output_and_resize(tmp_path) -> None:
    session = WinPtyTerminalSession(
        [
            sys.executable,
            "-c",
            "import sys; print('AIA_TERMINAL_READY', flush=True); value=sys.stdin.readline(); print('AIA_TERMINAL_ECHO:' + value.strip(), flush=True)",
        ],
        cwd=tmp_path,
        env=os.environ,
    )
    try:
        session.start()
        assert session.snapshot()["status"] == "RUNNING"
        session.resize(40, 140)
        session.send_input("workbench-input\r")
        assert session.wait(timeout=10) == 0
        output = "".join(item["data"] for item in session.drain_output())
        assert "AIA_TERMINAL_READY" in output
        assert "AIA_TERMINAL_ECHO:workbench-input" in output
        assert session.snapshot()["status"] == "EXITED"
    finally:
        session.close(force=True)


def test_winpty_terminal_rejects_invalid_dimensions(tmp_path) -> None:
    with pytest.raises(TerminalSessionError, match="rows"):
        WinPtyTerminalSession(
            [sys.executable, "-c", "print('x')"],
            cwd=tmp_path,
            env=os.environ,
            rows=0,
        )
