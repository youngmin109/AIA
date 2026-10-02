"""Windows desktop shell for the AIA local Security Workbench.

The shell owns only the local server and the WebView2 window. Policy,
Hook/File/Process Sensors, Evidence, and enforcement remain in AIA Core and
the existing local web application.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time
from threading import Thread
from typing import Any
from urllib.parse import urlparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
PORT_SEARCH_LIMIT = 20
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _ensure_gui_stdio() -> None:
    """Give GUI builds safe streams for Uvicorn and Python logging.

    PyInstaller's ``--windowed`` bootloader intentionally sets stdout and
    stderr to ``None``. Uvicorn and dependencies still configure logging while
    the embedded local server starts, so leaving those streams unset can make
    the packaged server stall before it serves the first request. A sink is
    sufficient because the desktop product has no console; diagnostics remain
    available through the local API and the CLI build.
    """

    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _detach_desktop_console(kernel32: Any | None = None) -> bool:
    """Leave the hidden bootloader console before the desktop shell starts.

    The packaged build uses PyInstaller's console bootloader with its console
    hidden, because the windowed bootloader fails before Python starts on some
    Windows/Python 3.13 combinations.  The desktop window must still own no
    console: the Workbench switches each Codex app-server console to UTF-8 by
    attaching to it (codex_app_server), and Windows refuses that while this
    process is attached to a console of its own, which brings back garbled
    Korean output.  Source runs keep their console for logging.
    """

    if not (_is_windows() and getattr(sys, "frozen", False)):
        return False
    if kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32")
    if not kernel32.GetConsoleWindow():
        return False
    kernel32.FreeConsole()
    # The console handles behind stdout/stderr are gone; give logging a sink.
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
    return True


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


WINDOW_TITLE = "AIA · Protected Workbench"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


def _desktop_instance_key() -> str:
    """Identify the control root this desktop window serves.

    Protected runs, their conversations and their Codex processes live inside
    the AIA process that started them.  A second window on the same control
    root lists those runs from disk but cannot drive them, so one desktop
    instance is allowed per control root.
    """

    configured = os.environ.get("AIA_CONTROL_ROOT")
    root = Path(configured).expanduser() if configured else Path.home() / ".aia" / "control"
    normalized = str(root.resolve(strict=False)).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _desktop_instance_record(key: str) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    return root / "AIA" / "desktop-instances" / f"{key}.json"


class _DesktopInstanceLock:
    """Hold the per-control-root desktop mutex for this process's lifetime."""

    def __init__(self, handle: int | None, record: Path | None) -> None:
        self._handle = handle
        self._record = record

    def release(self) -> None:
        if self._record is not None:
            try:
                if json.loads(self._record.read_text(encoding="utf-8")).get("pid") == os.getpid():
                    self._record.unlink()
            except (OSError, ValueError, AttributeError):
                pass
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None


def _acquire_desktop_instance() -> _DesktopInstanceLock | None:
    """Return the instance lock, or ``None`` when another window owns it.

    If the mutex cannot be created at all the window still starts: refusing
    to open is worse than the duplicate-window problem this guards against.
    """

    key = _desktop_instance_key()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\AIA-Desktop-{key}")
    if not handle:
        return _DesktopInstanceLock(None, None)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    record = _desktop_instance_record(key)
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    except OSError:
        record = None
    return _DesktopInstanceLock(handle, record)


def _activate_existing_desktop() -> bool:
    """Bring the window of the running instance to the front."""

    try:
        owner = int(json.loads(_desktop_instance_record(_desktop_instance_key()).read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _lparam):  # type: ignore[no-untyped-def]
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        if pid.value == owner and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            length = user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, length + 1)
            if buffer.value == WINDOW_TITLE:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, None)
    if not found:
        return False
    hwnd = ctypes.c_void_p(found[0])
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    if not user32.SetForegroundWindow(hwnd):
        # Windows may refuse to hand over focus (for example when this launch
        # did not come from the user's own click); flash the taskbar button so
        # the running window is still easy to find.
        user32.FlashWindow(hwnd, True)
    return True


_TERMINAL_RUN_STATUSES = frozenset({"COMPLETED", "ABORTED", "FAILED"})
_MB_YESNO = 0x04
_MB_ICONWARNING = 0x30
_MB_SETFOREGROUND = 0x10000
_MB_TOPMOST = 0x40000
_IDYES = 6


def _embedded_service() -> Any | None:
    """Return the application service of the in-process console, if loaded."""

    module = sys.modules.get("aia_web.app")
    app = getattr(module, "app", None) if module is not None else None
    return getattr(getattr(app, "state", None), "service", None)


def _live_run_count(service: Any) -> int:
    try:
        return sum(1 for record in service.registry.snapshots() if record.status not in _TERMINAL_RUN_STATUSES)
    except Exception:
        return 0


def _confirm_close_with_live_runs() -> bool:
    """Ask before a window close stops protected runs; ``False`` keeps it open."""

    service = _embedded_service()
    count = _live_run_count(service) if service is not None else 0
    if count == 0:
        return True
    answer = ctypes.windll.user32.MessageBoxW(
        None,
        f"진행 중인 보호 실행이 {count}건 있습니다.\n\n"
        "창을 닫으면 Codex를 중지하고 결과를 확정합니다. 닫을까요?",
        "AIA",
        _MB_YESNO | _MB_ICONWARNING | _MB_SETFOREGROUND | _MB_TOPMOST,
    )
    return answer == _IDYES


def _stop_live_runs(timeout: float = 60.0) -> None:
    """Stop this window's protected runs before the console server stops.

    Runs, their conversations and their Codex processes belong to this
    process, and the executor thread that finalizes them keeps the process
    alive.  The server's lifespan shutdown also stops runs, but it is skipped
    whenever the server has to be forced down, which left AIA running without
    a window and with a live Codex.  Request the stop here directly and give
    finalization a bounded time to record the result.
    """

    service = _embedded_service()
    if service is None:
        return
    try:
        service.shutdown(wait=False)
    except Exception:
        return
    deadline = time.monotonic() + timeout
    while _live_run_count(service) and time.monotonic() < deadline:
        time.sleep(0.2)


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


class _EmbeddedLocalServer:
    """Run the local FastAPI server without spawning another executable.

    Windows application-control policies can allow the interactive AIA
    executable while rejecting a second unsigned AIA executable launched by
    it. Keeping Uvicorn in a daemon thread avoids that child-process boundary;
    the WebView and local server still communicate only over loopback.
    """

    def __init__(self, host: str, port: int) -> None:
        _ensure_gui_stdio()
        import uvicorn

        self._server = uvicorn.Server(
            uvicorn.Config(
                "aia_web.app:app",
                host=host,
                port=port,
                reload=False,
                access_log=False,
                log_level="warning",
            )
        )
        self._thread = Thread(
            target=self._run,
            name="aia-local-console-server",
            daemon=True,
        )
        self._error: BaseException | None = None

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as error:  # pragma: no cover - uvicorn boundary
            self._error = error

    def start(self) -> None:
        self._thread.start()

    def poll(self) -> int | None:
        if self._thread.is_alive():
            return None
        return 1 if self._error is not None else 0

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            self._server.force_exit = True
            self._thread.join(timeout=5.0)


def _start_local_server(host: str, port: int) -> _EmbeddedLocalServer:
    """Start the loopback server without a Windows child-process spawn."""

    server = _EmbeddedLocalServer(host, port)
    server.start()
    return server


def _server_stopped(server: Any) -> bool:
    poll = getattr(server, "poll", None)
    if callable(poll):
        return poll() is not None
    return bool(getattr(server, "should_exit", False))


def _wait_for_server(url: str, server: Any, timeout: float = 30.0) -> None:
    """Wait only for the loopback listener before creating the GUI window.

    The SPA's own API calls (run listing, preflight, etc.) can take a few
    seconds on a workspace with many previous runs.  Waiting for a full HTTP
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
        # pywebview recursively exposes public attributes of the JS API.  A
        # WebView window contains the native WinForms/WebView2 object graph;
        # keeping it public makes pywebview walk that graph while generating
        # ``window.pywebview.api`` and can freeze the desktop window.  Private
        # attributes are intentionally skipped by pywebview's API scanner.
        self._window: Any | None = None

    def attach(self, window: Any) -> None:
        self._window = window

    def choose_workspace(self) -> dict[str, str | None]:
        return self.choose_directory()

    def choose_directory(self) -> dict[str, str | None]:
        if self._window is None:
            return {"path": None}
        import webview

        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        path = selected[0] if selected else None
        return {"path": path}

    def choose_files(self) -> dict[str, list[str]]:
        if self._window is None:
            return {"paths": []}
        import webview

        selected = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
        )
        return {"paths": list(selected or ())}


def run_desktop(*, host: str = DEFAULT_HOST, preferred_port: int = DEFAULT_PORT) -> int:
    """Start the loopback FastAPI app and display it in a WebView2 window."""

    _detach_desktop_console()
    _ensure_gui_stdio()
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

    instance = _acquire_desktop_instance()
    if instance is None:
        if not _activate_existing_desktop():
            _show_message(
                "AIA",
                "AIA가 이미 실행 중입니다.\n\n작업 표시줄에서 열려 있는 AIA 창을 사용하세요. "
                "보호 실행과 Codex 대화는 그 창에서만 이어갈 수 있습니다.",
            )
        return 0

    import webview

    port = choose_loopback_port(preferred_port)
    server: _EmbeddedLocalServer | None = None
    webview_storage_path = _webview_storage_path()
    bridge = DesktopBridge()
    try:
        server = _start_local_server(host, port)
        _wait_for_server(f"http://{host}:{port}/", server)
        window = webview.create_window(
            WINDOW_TITLE,
            f"http://{host}:{port}/",
            width=1440,
            height=900,
            min_size=(1024, 680),
            resizable=True,
            js_api=bridge,
        )
        bridge.attach(window)
        # Returning False from a closing handler keeps the window open.
        window.events.closing += _confirm_close_with_live_runs
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
        _stop_live_runs()
        if server is not None:
            server.stop()
        _remove_webview_storage(webview_storage_path)
        instance.release()
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
