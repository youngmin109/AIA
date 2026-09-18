"""Windows desktop shell for the AIA local Security Workbench.

The shell owns only the local server and the WebView2 window. Policy,
Hook/File/Process Sensors, Evidence, and enforcement remain in AIA Core and
the existing local web application.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
PORT_SEARCH_LIMIT = 20
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _is_windows() -> bool:
    return os.name == "nt"


def _webview2_runtime_present() -> bool:
    """Check the per-user and machine WebView2 Evergreen registry entries."""

    if not _is_windows():
        return False
    try:
        import winreg

        subkeys = (
            rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}",
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}",
        )
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in subkeys:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        version, _ = winreg.QueryValueEx(key, "pv")
                    if str(version).strip() and str(version) != "0.0.0.0":
                        return True
                except OSError:
                    continue
    except (ImportError, OSError):
        return False
    return False


def _webview_storage_path(session_id: int | str | None = None) -> Path:
    """Return an isolated per-run WebView2 profile directory.

    WebView2 user-data folders are locked by the browser process. Reusing one
    folder after a forced AIA termination can leave the next embedded window
    waiting on the previous browser session. A run-scoped folder keeps AIA
    launches independent while retaining the data under the user's AIA area.
    """

    local_app_data = os.environ.get("LOCALAPPDATA")
    root = (
        Path(local_app_data).expanduser()
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    run_id = str(session_id if session_id is not None else os.getpid())
    return root / "AIA" / "WebView2" / f"session-{run_id}"


def _remove_webview_storage(path: Path) -> None:
    """Best-effort cleanup after WebView2 has closed."""

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        # A browser child can release its last file handle shortly after the
        # window closes. Stale run-scoped folders are harmless and are not
        # allowed to affect a later run.
        return


def _show_message(title: str, message: str, *, error: bool = False) -> None:
    """Show a native message when the embedded WebView cannot start."""

    if _is_windows():
        flags = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
        return
    print(f"{title}: {message}")


def choose_loopback_port(preferred: int = DEFAULT_PORT) -> int:
    """Return an available loopback port, preferring the stable default."""

    for port in range(max(1, preferred), min(65536, preferred + PORT_SEARCH_LIMIT)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((DEFAULT_HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("AIA 로컬 콘솔에 사용할 수 있는 포트를 찾지 못했습니다.")


def _desktop_server_command(host: str, port: int) -> list[str]:
    """Build the command for the isolated local console server process."""

    arguments = ["console", "--host", host, "--port", str(port)]
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve(strict=False)
        candidates = (
            executable.parent / "aia-cli" / "aia-cli.exe",
            executable.parent.parent / "aia-cli" / "aia-cli.exe",
            executable.parent / "aia-cli.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate), *arguments]
        raise FileNotFoundError("aia-cli.exe is not installed next to AIA.exe")
    return [sys.executable, "-m", "aia.cli", *arguments]


class _EmbeddedServer:
    """Own a loopback Uvicorn server inside the already-approved AIA process.

    The packaged desktop shell used to spawn ``aia-cli.exe`` for this job.
    Windows application-control policy may allow the already-started AIA.exe
    while blocking that unsigned sibling executable.  Keeping the server in a
    daemon thread removes that unnecessary executable boundary; the server is
    still loopback-only and is shut down with the desktop window.
    """

    def __init__(self, host: str, port: int) -> None:
        import uvicorn

        from aia_web.app import app

        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
        )
        self._exit_code: int | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="aia-embedded-console",
            daemon=True,
        )

    def _run(self) -> None:
        try:
            asyncio.run(self._server.serve())
            self._exit_code = 0
        except BaseException as error:  # pragma: no cover - platform startup
            self._error = error
            self._exit_code = 1

    def start(self) -> None:
        self._thread.start()

    def poll(self) -> int | None:
        if self._thread.is_alive():
            return None
        return self._exit_code if self._exit_code is not None else 1

    def terminate(self) -> None:
        self._server.should_exit = True

    def wait(self, timeout: float | None = None) -> int:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired("aia-embedded-console", timeout)
        return self.poll() or 0

    def kill(self) -> None:
        self._server.force_exit = True
        self._server.should_exit = True


def _start_embedded_server(host: str, port: int) -> _EmbeddedServer:
    server = _EmbeddedServer(host, port)
    server.start()
    return server


def _start_server_process(host: str, port: int) -> Any:
    """Start the local server without spawning a blocked packaged CLI.

    Source mode keeps the separate module process for development isolation.
    The frozen desktop build embeds the server in AIA.exe so the application
    does not require Windows to authorize a second unsigned executable merely
    to render its local Workbench.
    """

    if getattr(sys, "frozen", False):
        return _start_embedded_server(host, port)

    process_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if _is_windows():
        process_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(_desktop_server_command(host, port), **process_kwargs)


def _server_stopped(server: Any) -> bool:
    poll = getattr(server, "poll", None)
    if callable(poll):
        return poll() is not None
    return bool(getattr(server, "should_exit", False))


def _wait_for_server(url: str, server: Any, timeout: float = 30.0) -> None:
    """Wait only for the loopback listener before creating the GUI window.

    Rendering ``/start`` performs filesystem-backed run listing and can take a
    few seconds on a workspace with many previous runs.  Waiting for that HTTP
    response on the desktop process' main thread makes Windows label the GUI
    as unresponsive before WebView2 has even been created.  WebView2 can load
    the page once the socket is accepting connections; the page already loads
    readiness data asynchronously.
    """

    parsed = urlparse(url)
    if parsed.hostname is None or parsed.port is None:
        raise RuntimeError("AIA 로컬 콘솔 주소가 올바르지 않습니다.")
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline and not _server_stopped(server):
        try:
            with socket.create_connection((parsed.hostname, parsed.port), timeout=0.2):
                return
        except Exception as error:  # pragma: no cover - platform startup timing
            last_error = error
        time.sleep(0.1)
    detail = type(last_error).__name__ if last_error else "SERVER_STOPPED"
    raise RuntimeError(f"AIA 로컬 콘솔을 시작하지 못했습니다: {detail}")


class DesktopBridge:
    """Small native bridge exposed to the setup page inside WebView2."""

    def __init__(self) -> None:
        self.window: Any | None = None

    def attach(self, window: Any) -> None:
        self.window = window

    def choose_workspace(self) -> dict[str, str | None]:
        return self.choose_directory()

    def choose_directory(self) -> dict[str, str | None]:
        if self.window is None:
            return {"path": None}
        import webview

        selected = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        path = selected[0] if selected else None
        return {"path": path}

    def choose_files(self) -> dict[str, list[str]]:
        if self.window is None:
            return {"paths": []}
        import webview

        selected = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
        )
        return {"paths": list(selected or ())}


def run_desktop(*, host: str = DEFAULT_HOST, preferred_port: int = DEFAULT_PORT) -> int:
    """Start the loopback FastAPI app and display it in a WebView2 window."""

    if host != DEFAULT_HOST:
        _show_message("AIA", "AIA Desktop은 외부 주소에 바인딩하지 않습니다.", error=True)
        return 2
    if not _is_windows():
        _show_message("AIA", "AIA Desktop은 Windows 11에서 실행할 수 있습니다.", error=True)
        return 2
    if not _webview2_runtime_present():
        _show_message(
            "AIA WebView2 필요",
            "AIA 화면을 열려면 Microsoft Edge WebView2 Runtime이 필요합니다.\n\n"
            f"설치 안내: {WEBVIEW2_DOWNLOAD_URL}",
            error=True,
        )
        return 2

    import webview

    port = choose_loopback_port(preferred_port)
    server_process: Any | None = None
    webview_storage_path = _webview_storage_path()
    bridge = DesktopBridge()
    try:
        server_process = _start_server_process(host, port)
        _wait_for_server(f"http://{host}:{port}/start", server_process)
        window = webview.create_window(
            "AIA · Protected Workbench",
            f"http://{host}:{port}/start",
            width=1440,
            height=900,
            min_size=(1024, 680),
            resizable=True,
            js_api=bridge,
        )
        bridge.attach(window)
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(webview_storage_path),
        )
    except Exception as error:
        _show_message(
            "AIA 실행 실패",
            f"AIA Workbench를 시작하지 못했습니다.\n\n{type(error).__name__}: {error}",
            error=True,
        )
        return 1
    finally:
        if server_process is not None and server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5.0)
        _remove_webview_storage(webview_storage_path)
    return 0


def main() -> int:
    return run_desktop()


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DesktopBridge",
    "WEBVIEW2_CLIENT_GUID",
    "_webview_storage_path",
    "choose_loopback_port",
    "main",
    "run_desktop",
]
