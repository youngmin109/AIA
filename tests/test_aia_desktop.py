from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import socket

from aia_desktop.launcher import (
    DesktopBridge,
    _desktop_server_command,
    _start_server_process,
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

    assert bridge.choose_workspace() == {"path": None}
    assert bridge.choose_files() == {"paths": []}


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


def test_desktop_server_uses_module_cli_in_source_mode(monkeypatch) -> None:
    monkeypatch.delattr("sys.frozen", raising=False)

    command = _desktop_server_command("127.0.0.1", 8787)

    assert command[1:4] == ["-m", "aia.cli", "console"]
    assert command[-4:] == ["--host", "127.0.0.1", "--port", "8787"]


def test_frozen_desktop_embeds_server_instead_of_spawning_packaged_cli(monkeypatch) -> None:
    monkeypatch.setattr("aia_desktop.launcher.sys.frozen", True, raising=False)
    sentinel = object()
    monkeypatch.setattr(
        "aia_desktop.launcher._start_embedded_server",
        lambda host, port: sentinel,
    )

    assert _start_server_process("127.0.0.1", 8787) is sentinel


def test_webview_storage_path_is_per_user_and_isolated_per_run(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    first = _webview_storage_path("first")
    second = _webview_storage_path("second")

    assert first == tmp_path / "AIA" / "WebView2" / "session-first"
    assert second == tmp_path / "AIA" / "WebView2" / "session-second"
    assert first != second
