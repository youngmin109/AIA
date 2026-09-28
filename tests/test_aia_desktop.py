from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import socket
import sys

import pytest

import aia_desktop.launcher as launcher
from aia_desktop.launcher import (
    DesktopBridge,
    _EmbeddedLocalServer,
    _ensure_gui_stdio,
    _wait_for_server,
    _webview_storage_path,
    choose_loopback_port,
    run_desktop,
)


def test_choose_loopback_port_skips_ports_that_are_in_use() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        first_port = occupied.getsockname()[1]
        selected = choose_loopback_port(first_port)

    assert selected != first_port
    assert first_port <= selected < first_port + 20


def test_desktop_bridge_is_safe_before_webview_window_attach() -> None:
    bridge = DesktopBridge()

    assert not hasattr(bridge, "window")
    assert bridge.choose_workspace() == {"path": None}
    assert bridge.choose_files() == {"paths": []}


def test_gui_stdio_is_initialized_when_windowed_bootloader_removes_streams(monkeypatch) -> None:
    class Sink:
        def write(self, text: str) -> int:
            return len(text)

        def flush(self) -> None:
            return None

    stdout = sys.stdout
    stderr = sys.stderr
    try:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        monkeypatch.setattr(
            "aia_desktop.launcher.open",
            lambda *args, **kwargs: Sink(),
            raising=False,
        )
        _ensure_gui_stdio()
        assert sys.stdout is not None
        assert sys.stderr is not None
    finally:
        sys.stdout = stdout
        sys.stderr = stderr


def test_desktop_rejects_non_loopback_binding(monkeypatch) -> None:
    monkeypatch.setattr("aia_desktop.launcher._show_message", lambda *args, **kwargs: None)

    assert run_desktop(host="0.0.0.0") == 2


def test_desktop_waits_for_listener_without_rendering_setup_page(monkeypatch) -> None:
    class Server:
        should_exit = False

    monkeypatch.setattr(
        "aia_desktop.launcher.socket.create_connection",
        lambda *args, **kwargs: nullcontext(),
    )

    _wait_for_server("http://127.0.0.1:8787/start", Server(), timeout=0.1)


def test_embedded_local_server_exposes_a_pollable_lifecycle(monkeypatch) -> None:
    class FakeServer:
        should_exit = False
        force_exit = False

        def run(self):
            while not self.should_exit and not self.force_exit:
                import time

                time.sleep(0.001)

    class FakeUvicorn:
        Server = lambda self, config: FakeServer()
        Config = lambda self, *args, **kwargs: object()

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn())
    server = _EmbeddedLocalServer("127.0.0.1", 8787)
    server.start()
    try:
        assert server.poll() is None
    finally:
        server.stop()
    assert server.poll() == 0


def test_webview_storage_path_is_per_user_and_isolated_per_run(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    first = _webview_storage_path("first")
    second = _webview_storage_path("second")

    assert first == tmp_path / "AIA" / "WebView2" / "session-first"
    assert second == tmp_path / "AIA" / "WebView2" / "session-second"
    assert first != second


@pytest.mark.skipif(os.name != "nt", reason="the desktop instance guard uses a Windows named mutex")
def test_only_one_desktop_instance_per_control_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("AIA_CONTROL_ROOT", str(tmp_path / "control-a"))
    first = launcher._acquire_desktop_instance()
    try:
        assert first is not None
        record = launcher._desktop_instance_record(launcher._desktop_instance_key())
        assert json.loads(record.read_text(encoding="utf-8")) == {"pid": os.getpid()}
        assert launcher._acquire_desktop_instance() is None

        # A different control root is a separate product instance.
        monkeypatch.setenv("AIA_CONTROL_ROOT", str(tmp_path / "control-b"))
        other = launcher._acquire_desktop_instance()
        assert other is not None
        other.release()
    finally:
        monkeypatch.setenv("AIA_CONTROL_ROOT", str(tmp_path / "control-a"))
        first.release()
    assert not record.exists()
    again = launcher._acquire_desktop_instance()
    assert again is not None
    again.release()


def test_second_desktop_launch_focuses_the_running_window_instead_of_starting(monkeypatch) -> None:
    started = []
    monkeypatch.setattr(launcher, "_is_windows", lambda: True)
    monkeypatch.setattr(launcher, "_webview2_runtime_present", lambda: True)
    monkeypatch.setattr(launcher, "_acquire_desktop_instance", lambda: None)
    monkeypatch.setattr(launcher, "_activate_existing_desktop", lambda: True)
    monkeypatch.setattr(launcher, "_start_local_server", lambda *args: started.append(args))
    monkeypatch.setattr(launcher, "_show_message", lambda *args, **kwargs: started.append(("message", args)))

    assert run_desktop() == 0
    assert started == []


def test_second_desktop_launch_explains_when_the_window_cannot_be_focused(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr(launcher, "_is_windows", lambda: True)
    monkeypatch.setattr(launcher, "_webview2_runtime_present", lambda: True)
    monkeypatch.setattr(launcher, "_acquire_desktop_instance", lambda: None)
    monkeypatch.setattr(launcher, "_activate_existing_desktop", lambda: False)
    monkeypatch.setattr(launcher, "_show_message", lambda title, message, **kwargs: messages.append(message))

    assert run_desktop() == 0
    assert "이미 실행 중" in messages[0]


class _FakeRunService:
    """Stands in for the in-process console service seen by the launcher."""

    def __init__(self, statuses: list[str]) -> None:
        from types import SimpleNamespace

        self.records = [SimpleNamespace(status=status) for status in statuses]
        self.registry = SimpleNamespace(snapshots=lambda: list(self.records))
        self.shutdown_calls: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)
        # The worker finalizes each stopped run shortly afterwards.
        for record in self.records:
            record.status = "ABORTED"


def _install_console_service(monkeypatch, service) -> None:
    from types import SimpleNamespace

    module = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(service=service)))
    monkeypatch.setitem(sys.modules, "aia_web.app", module)


def test_window_close_stops_live_runs_even_when_server_lifespan_is_skipped(monkeypatch) -> None:
    service = _FakeRunService(["RUNNING", "COMPLETED"])
    _install_console_service(monkeypatch, service)

    launcher._stop_live_runs(timeout=2.0)

    assert service.shutdown_calls == [False]
    assert launcher._live_run_count(service) == 0


def test_stop_live_runs_is_a_no_op_before_the_console_loaded(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "aia_web.app", raising=False)
    launcher._stop_live_runs(timeout=0.1)


def test_closing_without_live_runs_does_not_prompt(monkeypatch) -> None:
    from types import SimpleNamespace

    prompts = []
    _install_console_service(monkeypatch, _FakeRunService(["COMPLETED"]))
    monkeypatch.setattr(launcher.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(MessageBoxW=lambda *a: prompts.append(a))), raising=False)

    assert launcher._confirm_close_with_live_runs() is True
    assert prompts == []


@pytest.mark.parametrize(("answer", "closes"), [(6, True), (7, False)])
def test_closing_with_a_live_run_asks_first(monkeypatch, answer, closes) -> None:
    from types import SimpleNamespace

    prompts = []
    _install_console_service(monkeypatch, _FakeRunService(["RUNNING"]))
    monkeypatch.setattr(
        launcher.ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(MessageBoxW=lambda *a: prompts.append(a[1]) or answer)),
        raising=False,
    )

    assert launcher._confirm_close_with_live_runs() is closes
    assert "진행 중인 보호 실행이 1건" in prompts[0]
