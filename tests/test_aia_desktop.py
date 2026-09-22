from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import socket
import sys

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
