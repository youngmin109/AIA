"""Keep the WebView2 window painting after renderer failures, idle and minimize.

pywebview does not handle WebView2's ``ProcessFailed`` event, so a renderer
that exits or hangs leaves a blank white window, and pywebview also turns
off the browser accelerator keys (F5 does nothing).  This module

* reloads the page when WebView2 reports that the page's renderer exited
  or stopped responding,
* watches a heartbeat that the console page sends while it is visible, and
  when the window is in front but the page has gone quiet, first forces the
  WebView to repaint and then reloads it,
* writes what happened to a small local log so a recurrence can be
  diagnosed.

Reloading only redraws the console.  Protected runs, conversations and
evidence live in the local server and are not touched.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

HEARTBEAT_STALE_SECONDS = 25.0
RELOAD_AFTER_SECONDS = 40.0
FOREGROUND_GRACE_SECONDS = 10.0
RELOAD_GRACE_SECONDS = 30.0
LOG_MAX_BYTES = 512 * 1024

NONE = "none"
REPAINT = "repaint"
RELOAD = "reload"
RESTART_REQUIRED = "restart-required"


def action_for_process_failure(kind: str) -> str:
    """Map a WebView2 ``CoreWebView2ProcessFailedKind`` name to a recovery."""

    if kind in {"RenderProcessExited", "RenderProcessUnresponsive"}:
        return RELOAD
    if kind == "GpuProcessExited":
        # WebView2 restarts the GPU process itself; make sure the surface is redrawn.
        return REPAINT
    if kind == "BrowserProcessExited":
        # The WebView2 instance is gone; only a new window can show the console again.
        return RESTART_REQUIRED
    return NONE


class WebViewWatchdog:
    """Decide when the console needs a repaint or a reload.

    Thread-safe: the page heartbeat arrives on pywebview's API threads,
    process failures on the UI thread and decisions on the watchdog thread.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        now = clock()
        self._last_heartbeat = now
        self._grace_until = now + RELOAD_GRACE_SECONDS
        self._repainted = False
        self._quiet_reload_spent = False
        self._was_foreground = False
        self._failures: list[str] = []

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = self._clock()
            self._repainted = False
            self._quiet_reload_spent = False

    def process_failed(self, kind: str) -> None:
        with self._lock:
            self._failures.append(kind)

    def next_action(self, *, foreground: bool) -> tuple[str, str]:
        """Return ``(action, reason)`` for this tick."""

        with self._lock:
            now = self._clock()
            while self._failures:
                kind = self._failures.pop(0)
                action = action_for_process_failure(kind)
                if action != NONE:
                    if action == RELOAD:
                        self._reloaded(now)
                    return action, f"process-failed:{kind}"
            if foreground and not self._was_foreground:
                # A page coming back from hidden sends a heartbeat at once;
                # give it a moment before judging.
                self._grace_until = max(self._grace_until, now + FOREGROUND_GRACE_SECONDS)
            self._was_foreground = foreground
            if not foreground or now < self._grace_until:
                return NONE, ""
            quiet = now - self._last_heartbeat
            if quiet >= RELOAD_AFTER_SECONDS and self._repainted:
                if self._quiet_reload_spent:
                    # One reload did not bring the page back; reloading again
                    # in a loop would only throw away what the user typed.
                    return NONE, ""
                self._reloaded(now)
                self._quiet_reload_spent = True
                return RELOAD, f"no-heartbeat:{quiet:.0f}s"
            if quiet >= HEARTBEAT_STALE_SECONDS and not self._repainted:
                self._repainted = True
                return REPAINT, f"no-heartbeat:{quiet:.0f}s"
            return NONE, ""

    def _reloaded(self, now: float) -> None:
        self._last_heartbeat = now
        self._grace_until = now + RELOAD_GRACE_SECONDS
        self._repainted = False


def desktop_log_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    return root / "AIA" / "logs" / "desktop.log"


def desktop_log(event: str, path: Path | None = None, **fields: Any) -> None:
    """Append one JSON line; keeps one rotated file.  Never raises."""

    target = path or desktop_log_path()
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > LOG_MAX_BYTES:
            os.replace(target, target.with_name(target.name + ".1"))
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


class WebViewRecovery:
    """Wire a pywebview window to the watchdog.  Windows/WebView2 only."""

    def __init__(self, window: Any, url: str, watchdog: WebViewWatchdog | None = None) -> None:
        self._window = window
        self._url = url
        self.watchdog = watchdog or WebViewWatchdog()
        self._hwnd: int | None = None
        self._heard = False
        self._attached_core: Any = None
        self._handler: Any = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="aia-webview-watchdog", daemon=True)

    def start(self) -> None:
        self._window.events.loaded += self._on_loaded
        self._window.events.minimized += lambda: desktop_log("window-minimized")
        self._window.events.restored += lambda: desktop_log("window-restored")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def heartbeat(self) -> None:
        """Page heartbeat; the first one after start or a reload is logged."""

        if not self._heard:
            self._heard = True
            desktop_log("page-heartbeat")
        self.watchdog.heartbeat()

    def _on_ui_thread(self, function: Callable[[], None]) -> None:
        from System import Action  # pythonnet, loaded by pywebview's WinForms GUI

        self._window.native.Invoke(Action(function))

    def _on_loaded(self) -> None:
        try:
            self._on_ui_thread(self._attach)
        except Exception as error:
            desktop_log("attach-failed", error=type(error).__name__)

    def _attach(self) -> None:
        form = self._window.native
        self._hwnd = int(form.Handle.ToInt64())
        core = form.browser.webview.CoreWebView2
        if core is None or core is self._attached_core:
            return

        def on_process_failed(_sender: Any, args: Any) -> None:
            kind = str(args.ProcessFailedKind)
            desktop_log("process-failed", kind=kind)
            self.watchdog.process_failed(kind)

        self._handler = on_process_failed
        core.ProcessFailed += on_process_failed
        self._attached_core = core

    def _foreground(self) -> bool:
        if self._hwnd is None:
            return False
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = ctypes.c_void_p(self._hwnd)
        return user32.GetForegroundWindow() == self._hwnd and not user32.IsIconic(hwnd)

    def _reload(self) -> None:
        # pywebview's load_url only assigns Source, which does nothing when
        # the URL is unchanged, so reload through CoreWebView2 directly.
        core = self._window.native.browser.webview.CoreWebView2
        try:
            core.Reload()
        except Exception:
            core.Navigate(self._url)

    def _repaint(self) -> None:
        control = self._window.native.browser.webview
        control.Visible = False
        control.Visible = True
        control.Focus()

    def _run(self) -> None:
        while not self._stop.wait(2.0):
            try:
                action, reason = self.watchdog.next_action(foreground=self._foreground())
                if action == NONE:
                    continue
                desktop_log("recovery", action=action, reason=reason)
                if action == REPAINT:
                    self._on_ui_thread(self._repaint)
                elif action == RELOAD:
                    self._heard = False
                    self._on_ui_thread(self._reload)
                elif action == RESTART_REQUIRED:
                    _show_restart_required()
            except Exception as error:
                desktop_log("recovery-failed", error=type(error).__name__)


def _show_restart_required() -> None:
    ctypes.windll.user32.MessageBoxW(
        None,
        "AIA 화면을 그리는 WebView2가 종료됐습니다.\n\n"
        "로컬 서버와 보호 실행 기록은 그대로입니다. 진행 중인 실행이 끝난 뒤 "
        "AIA를 닫았다 다시 열어 주세요. 창을 닫으면 진행 중인 실행은 중지됩니다.",
        "AIA",
        0x30 | 0x10000,
    )
