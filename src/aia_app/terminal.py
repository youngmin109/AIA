"""Local interactive terminal transport for the AIA Workbench.

This module only transports terminal input and output.  It does not make
policy, attribution, or enforcement decisions.  The protected launcher still
owns the process identity and the existing Hook/File/Process Sensors remain
the authoritative observation path.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from threading import Condition, Lock, Thread, current_thread
import time
from typing import Any, Mapping, Protocol, Sequence


class TerminalSessionError(RuntimeError):
    """Raised when the Workbench terminal cannot be started or used."""


class TerminalSession(Protocol):
    """Minimal transport contract used by the local web console."""

    @property
    def process_handle(self) -> Any: ...

    def start(self) -> None: ...

    def send_input(self, value: str) -> None: ...

    def submit_input(self) -> None: ...

    def resize(self, rows: int, cols: int) -> None: ...

    def read_output(self, after_sequence: int = 0) -> list[dict[str, Any]]: ...

    def drain_output(self) -> list[dict[str, Any]]: ...

    def snapshot(self) -> dict[str, Any]: ...

    def close(self, *, force: bool = False) -> None: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class _OutputChunk:
    sequence: int
    data: str
    recorded_at: datetime


class _PtyProcessHandle:
    """Popen-compatible identity handle backed by a pywinpty process."""

    def __init__(self, session: "WinPtyTerminalSession") -> None:
        self._session = session
        self.pid = session.pid
        self.stdin = None

    def poll(self) -> int | None:
        return self._session.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._session.wait(timeout=timeout)

    def terminate(self) -> None:
        self._session.close(force=False)

    def kill(self) -> None:
        self._session.close(force=True)


class WinPtyTerminalSession:
    """Run one interactive Codex process in a Windows pseudo terminal.

    Output is held in a bounded in-memory queue so a disconnected browser does
    not grow the AIA process indefinitely.  Terminal output is never persisted
    into the Evidence Bundle or the Result Bundle.
    """

    MAX_INPUT_CHARS = 32_000
    MAX_OUTPUT_CHUNKS = 2_000
    MAX_OUTPUT_CHARS = 512_000
    # Codex's Workbench launch binds composer.submit to Ctrl+X.  Sending the
    # control byte as a separate PTY write avoids treating the browser's whole
    # message as a paste, which leaves the draft in Codex's composer instead of
    # submitting it.
    SUBMIT_SEQUENCE = "\x18"
    # ConPTY intermittently panics inside winpty-rs when the packaged AIA
    # server has no console of its own. WinPTY is the supported fallback in
    # pywinpty for this Windows product and keeps the child attached to the
    # same pseudo-terminal contract.
    PTY_BACKEND = 1

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str,
        env: Mapping[str, str],
        rows: int = 32,
        cols: int = 120,
    ) -> None:
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise TerminalSessionError("terminal argv must contain non-empty strings")
        if os.name != "nt":
            raise TerminalSessionError("web_terminal requires Windows 11")
        self.argv = tuple(argv)
        self.cwd = Path(cwd).expanduser().resolve(strict=False)
        self.env = dict(env)
        # Codex refuses its interactive TUI when inherited TERM is ``dumb``
        # (common when AIA itself is started from a plain PowerShell).  The
        # browser terminal is a real pseudo terminal, so advertise a normal
        # Windows-compatible terminal capability to the child process.
        if self.env.get("TERM", "").lower() in {"", "dumb"}:
            self.env["TERM"] = "xterm-256color"
        self.env.setdefault("COLORTERM", "truecolor")
        self._rows = self._validate_dimension(rows, "rows")
        self._cols = self._validate_dimension(cols, "cols")
        self._pty: Any | None = None
        self._handle: _PtyProcessHandle | None = None
        self._reader: Thread | None = None
        self._reader_error: str | None = None
        self._exit_code: int | None = None
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None
        self._closed = False
        self._next_sequence = 1
        self._chunks: deque[_OutputChunk] = deque()
        self._buffered_chars = 0
        self._lock = Lock()
        self._condition = Condition(self._lock)

    @staticmethod
    def _validate_dimension(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 500:
            raise TerminalSessionError(f"{name} must be between 1 and 500")
        return value

    @property
    def pid(self) -> int:
        if self._pty is None or not getattr(self._pty, "pid", None):
            raise TerminalSessionError("terminal process has not started")
        return int(self._pty.pid)

    @property
    def process_handle(self) -> _PtyProcessHandle:
        if self._handle is None:
            raise TerminalSessionError("terminal process has not started")
        return self._handle

    def start(self) -> None:
        with self._lock:
            if self._pty is not None:
                raise TerminalSessionError("terminal session is already started")
        try:
            from winpty import PtyProcess

            pty = PtyProcess.spawn(
                list(self.argv),
                cwd=str(self.cwd),
                env=self.env,
                dimensions=(self._rows, self._cols),
                backend=self.PTY_BACKEND,
            )
        except Exception as error:
            raise TerminalSessionError(
                f"Windows PTY start failed: {type(error).__name__}"
            ) from error
        with self._lock:
            self._pty = pty
            self._handle = _PtyProcessHandle(self)
            self._started_at = _now()
            reader = Thread(
                target=self._read_loop,
                name=f"aia-web-terminal-{self.pid}",
                daemon=True,
            )
            self._reader = reader
            reader.start()

    def _read_loop(self) -> None:
        while True:
            with self._lock:
                pty = self._pty
            if pty is None:
                return
            try:
                data = pty.read(8192)
            except EOFError:
                break
            except Exception as error:
                with self._lock:
                    self._reader_error = type(error).__name__
                break
            if data:
                self._append_output(data)
            if not pty.isalive():
                break
        with self._lock:
            exit_code: int | None = None
            try:
                value = pty.exitstatus
                exit_code = int(value) if value is not None else 0
            except Exception:
                pass
            self._exit_code = exit_code
            self._ended_at = self._ended_at or _now()
            self._condition.notify_all()

    def _append_output(self, data: str) -> None:
        if not data:
            return
        if len(data) > self.MAX_OUTPUT_CHARS:
            data = data[-self.MAX_OUTPUT_CHARS :]
        with self._lock:
            chunk = _OutputChunk(self._next_sequence, data, _now())
            self._next_sequence += 1
            self._chunks.append(chunk)
            self._buffered_chars += len(data)
            while len(self._chunks) > self.MAX_OUTPUT_CHUNKS or self._buffered_chars > self.MAX_OUTPUT_CHARS:
                removed = self._chunks.popleft()
                self._buffered_chars -= len(removed.data)
            self._condition.notify_all()

    def send_input(self, value: str) -> None:
        if not isinstance(value, str) or len(value) > self.MAX_INPUT_CHARS:
            raise TerminalSessionError("terminal input is invalid or too large")
        with self._lock:
            pty = self._pty
        if pty is None or not pty.isalive():
            raise TerminalSessionError("terminal process is not running")
        try:
            pty.write(value)
        except Exception as error:
            raise TerminalSessionError("terminal input failed") from error

    def submit_input(self) -> None:
        """Submit the current Codex composer draft through its bound key."""

        with self._lock:
            pty = self._pty
        if pty is None or not pty.isalive():
            raise TerminalSessionError("terminal process is not running")
        try:
            pty.write(self.SUBMIT_SEQUENCE)
        except Exception as error:
            raise TerminalSessionError("terminal submit failed") from error

    def resize(self, rows: int, cols: int) -> None:
        rows = self._validate_dimension(rows, "rows")
        cols = self._validate_dimension(cols, "cols")
        with self._lock:
            pty = self._pty
            self._rows = rows
            self._cols = cols
        if pty is None:
            raise TerminalSessionError("terminal process has not started")
        try:
            pty.setwinsize(rows, cols)
        except Exception as error:
            raise TerminalSessionError("terminal resize failed") from error

    def drain_output(self) -> list[dict[str, Any]]:
        with self._lock:
            chunks = list(self._chunks)
            self._chunks.clear()
            self._buffered_chars = 0
        return self._output_items(chunks)

    @staticmethod
    def _output_items(chunks: Sequence[_OutputChunk]) -> list[dict[str, Any]]:
        return [
            {
                "type": "output",
                "sequence": item.sequence,
                "data": item.data,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in chunks
        ]

    def read_output(self, after_sequence: int = 0) -> list[dict[str, Any]]:
        """Read buffered output without consuming it.

        Each Workbench WebSocket keeps its own sequence cursor.  Keeping the
        bounded buffer intact allows a browser refresh or reconnect to replay
        the current terminal view without persisting terminal content.

        The WS loop calls this on every poll tick (as often as every ~20ms),
        so the common "nothing new since last check" case must be O(1), and
        the "some new output" case must scale with how much is new, not with
        the full MAX_OUTPUT_CHUNKS buffer -- a linear scan of the whole deque
        on every tick pegged a CPU core on long sessions with a large
        accumulated backlog. Sequences are strictly increasing and the deque
        is append-only, so walking back from the newest item and stopping at
        the first one at or before after_sequence is equivalent to the old
        full-buffer filter.
        """

        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise TerminalSessionError("after_sequence must be a non-negative integer")
        with self._lock:
            if not self._chunks or self._chunks[-1].sequence <= after_sequence:
                return []
            newest_first: list[_OutputChunk] = []
            for item in reversed(self._chunks):
                if item.sequence <= after_sequence:
                    break
                newest_first.append(item)
            chunks = list(reversed(newest_first))
        return self._output_items(chunks)

    def poll(self) -> int | None:
        with self._lock:
            pty = self._pty
            cached_exit_code = getattr(self, "_exit_code", None)
        if pty is None or pty.isalive():
            return None
        if cached_exit_code is not None:
            return cached_exit_code
        try:
            value = pty.exitstatus
            exit_code = int(value) if value is not None else 0
        except Exception:
            exit_code = 0
        with self._lock:
            self._exit_code = exit_code
        return exit_code

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            result = self.poll()
            if result is not None:
                reader = self._reader
                if reader is not None and reader is not current_thread():
                    remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                    # ``poll`` observes the PTY exit before the reader thread
                    # necessarily consumes the final buffered bytes. Join it
                    # before returning so callers never see a successful exit
                    # with a missing last response.
                    reader.join(timeout=remaining)
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.argv, timeout)
            with self._condition:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                self._condition.wait(timeout=min(0.05, remaining) if remaining is not None else 0.05)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            pty = self._pty
            reader_error = self._reader_error
            exit_code = getattr(self, "_exit_code", None)
            started_at = self._started_at
            ended_at = self._ended_at
            rows = self._rows
            cols = self._cols
        if pty is None:
            status = "NOT_STARTED"
            pid = None
        else:
            alive = False
            try:
                alive = bool(pty.isalive())
            except Exception:
                pass
            status = "FAILED" if reader_error else "RUNNING" if alive else "EXITED"
            pid = int(pty.pid)
        return {
            "mode": "web_terminal",
            "status": status,
            "pid": pid,
            "rows": rows,
            "cols": cols,
            "started_at": started_at.isoformat() if started_at else None,
            "ended_at": ended_at.isoformat() if ended_at else None,
            "exit_code": exit_code,
            "error": reader_error,
        }

    def close(self, *, force: bool = False) -> None:
        with self._lock:
            pty = self._pty
            self._closed = True
        if pty is None:
            return
        try:
            if pty.isalive():
                pty.close(force=force)
        except Exception:
            if force:
                try:
                    pty.terminate(force=True)
                except Exception:
                    pass
        reader = self._reader
        if reader is not None and reader is not current_thread():
            reader.join(timeout=1.0)
        with self._lock:
            self._ended_at = self._ended_at or _now()
            self._condition.notify_all()
