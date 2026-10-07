import json
import sys
import types
from types import SimpleNamespace

import pytest

from aia_desktop import launcher
from aia_desktop.webview_recovery import (
    NONE,
    RELOAD,
    REPAINT,
    RESTART_REQUIRED,
    WebViewWatchdog,
    action_for_process_failure,
    desktop_log,
)
from aia_desktop.window_state import (
    DEFAULT_SIZE,
    MIN_SIZE,
    capture_window_state,
    load_window_geometry,
    save_window_state,
)

ANYWHERE = lambda x, y: True  # noqa: E731
NOWHERE = lambda x, y: False  # noqa: E731
DEFAULTS = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}


def _write(path, **state):
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


@pytest.mark.parametrize("width, scale", [(float("inf"), 1.0), (10**100, 1.0), (2_147_483_647, 0.5)])
def test_invalid_window_dimensions_fall_back_instead_of_crashing(tmp_path, width, scale) -> None:
    path = _write(tmp_path / "w.json", x=0, y=0, width=width, height=900, scale=scale)
    assert load_window_geometry(path, on_screen=ANYWHERE) == DEFAULTS


def test_missing_or_damaged_window_state_gives_the_default_window(tmp_path) -> None:
    path = tmp_path / "desktop-window.json"
    assert load_window_geometry(path, on_screen=ANYWHERE) == DEFAULTS
    path.write_text("{not json", encoding="utf-8")
    assert load_window_geometry(path, on_screen=ANYWHERE) == DEFAULTS
    _write(path, x=10, y=10, width="wide", height=900)
    assert load_window_geometry(path, on_screen=ANYWHERE) == DEFAULTS
    _write(path, x=10, y=10, width=1500, height=900, scale=40)
    assert load_window_geometry(path, on_screen=ANYWHERE) == DEFAULTS


def test_saved_physical_bounds_become_logical_geometry(tmp_path) -> None:
    path = _write(tmp_path / "w.json", x=300, y=150, width=2160, height=1350, scale=1.5, maximized=False)
    assert load_window_geometry(path, on_screen=ANYWHERE) == {
        "x": 200, "y": 100, "width": 1440, "height": 900, "maximized": False,
    }


def test_window_smaller_than_the_minimum_is_enlarged(tmp_path) -> None:
    path = _write(tmp_path / "w.json", x=0, y=0, width=400, height=300, scale=1.0)
    geometry = load_window_geometry(path, on_screen=ANYWHERE)
    assert (geometry["width"], geometry["height"]) == MIN_SIZE


def test_window_whose_title_bar_is_off_every_monitor_is_recentred(tmp_path) -> None:
    path = _write(tmp_path / "w.json", x=5000, y=5000, width=1500, height=900, scale=1.0, maximized=True)
    checked = []
    geometry = load_window_geometry(path, on_screen=lambda x, y: checked.append((x, y)) or False)
    assert geometry == {**DEFAULTS, "maximized": True}
    assert checked == [(5750, 5008)]


def _form(state: str, bounds, restore_bounds):
    return SimpleNamespace(
        WindowState=state,
        Bounds=SimpleNamespace(X=bounds[0], Y=bounds[1], Width=bounds[2], Height=bounds[3]),
        RestoreBounds=SimpleNamespace(X=restore_bounds[0], Y=restore_bounds[1], Width=restore_bounds[2], Height=restore_bounds[3]),
        Handle=SimpleNamespace(ToInt64=lambda: 42),
    )


def test_capture_keeps_normal_bounds_for_a_maximized_window_and_round_trips(tmp_path) -> None:
    maximized = _form("Maximized", (-8, -8, 2576, 1416), (100, 80, 1800, 1100))
    state = capture_window_state(maximized, dpi_for_window=lambda handle: 120)
    assert state == {"x": 100, "y": 80, "width": 1800, "height": 1100, "scale": 1.25, "maximized": True}
    path = tmp_path / "w.json"
    save_window_state(path, state)
    assert load_window_geometry(path, on_screen=ANYWHERE) == {
        "x": 80, "y": 64, "width": 1440, "height": 880, "maximized": True,
    }
    normal = _form("Normal", (10, 20, 1500, 950), (0, 0, 1, 1))
    assert capture_window_state(normal, dpi_for_window=lambda handle: 96)["width"] == 1500


def test_unreadable_form_saves_nothing(tmp_path) -> None:
    assert capture_window_state(object(), dpi_for_window=lambda handle: 96) is None
    path = tmp_path / "w.json"
    save_window_state(path, None)
    assert not path.exists()


@pytest.mark.parametrize(
    ("kind", "action"),
    [
        ("RenderProcessExited", RELOAD),
        ("RenderProcessUnresponsive", RELOAD),
        ("GpuProcessExited", REPAINT),
        ("BrowserProcessExited", RESTART_REQUIRED),
        ("FrameRenderProcessExited", NONE),
        ("UtilityProcessExited", NONE),
    ],
)
def test_process_failures_map_to_recoveries(kind, action) -> None:
    assert action_for_process_failure(kind) == action


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_live_page_is_left_alone_and_background_window_is_never_touched() -> None:
    clock = Clock()
    watchdog = WebViewWatchdog(clock)
    for _ in range(30):
        clock.now += 10
        watchdog.heartbeat()
        assert watchdog.next_action(foreground=True)[0] == NONE
    clock.now += 600  # minimized or behind other windows: no heartbeat, no action
    assert watchdog.next_action(foreground=False)[0] == NONE


def test_quiet_page_in_front_is_repainted_then_reloaded() -> None:
    clock = Clock()
    watchdog = WebViewWatchdog(clock)
    clock.now += 60
    watchdog.heartbeat()
    assert watchdog.next_action(foreground=True)[0] == NONE  # brought to front: grace
    clock.now += 26
    action, reason = watchdog.next_action(foreground=True)
    assert action == REPAINT and reason.startswith("no-heartbeat")
    clock.now += 5
    assert watchdog.next_action(foreground=True)[0] == NONE
    clock.now += 10
    assert watchdog.next_action(foreground=True)[0] == RELOAD
    clock.now += 20  # the reloaded page gets time to start
    assert watchdog.next_action(foreground=True)[0] == NONE


def test_heartbeat_after_a_repaint_cancels_the_reload() -> None:
    clock = Clock()
    watchdog = WebViewWatchdog(clock)
    clock.now += 60
    watchdog.next_action(foreground=True)
    clock.now += 30
    assert watchdog.next_action(foreground=True)[0] == REPAINT
    watchdog.heartbeat()
    clock.now += 15
    assert watchdog.next_action(foreground=True)[0] == NONE


def test_window_brought_back_to_front_gets_a_grace_period() -> None:
    clock = Clock()
    watchdog = WebViewWatchdog(clock)
    clock.now += 300  # minimized for five minutes
    assert watchdog.next_action(foreground=False)[0] == NONE
    assert watchdog.next_action(foreground=True)[0] == NONE
    clock.now += 5
    watchdog.heartbeat()  # the page answers as soon as it becomes visible
    clock.now += 6
    assert watchdog.next_action(foreground=True)[0] == NONE


def test_renderer_exit_reloads_at_once_even_in_the_background() -> None:
    watchdog = WebViewWatchdog(Clock())
    watchdog.process_failed("FrameRenderProcessExited")
    watchdog.process_failed("RenderProcessExited")
    action, reason = watchdog.next_action(foreground=False)
    assert action == RELOAD and reason == "process-failed:RenderProcessExited"
    assert watchdog.next_action(foreground=False)[0] == NONE


def test_desktop_log_rotates_instead_of_growing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("aia_desktop.webview_recovery.LOG_MAX_BYTES", 200)
    path = tmp_path / "desktop.log"
    for index in range(20):
        desktop_log("recovery", path=path, action="reload", index=index)
    assert path.with_name("desktop.log.1").exists()
    assert path.stat().st_size <= 400
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["index"] == 19


def test_bridge_heartbeat_reaches_the_watchdog_and_is_safe_before_attach() -> None:
    bridge = launcher.DesktopBridge()
    assert bridge.heartbeat() is True
    beats = []
    bridge.attach(object(), on_heartbeat=lambda: beats.append(1))
    bridge.heartbeat()
    assert beats == [1]


class FakeEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def test_run_desktop_opens_the_window_where_it_was_last_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "AIA").mkdir()
    _write(tmp_path / "AIA" / "desktop-window.json", x=320, y=240, width=1600, height=1000, scale=1.0, maximized=True)
    created = {}
    window = SimpleNamespace(events=SimpleNamespace(closing=FakeEvent(), loaded=FakeEvent(), shown=FakeEvent(), minimized=FakeEvent(), restored=FakeEvent()))

    def create_window(title, url, **kwargs):
        created.update(kwargs, url=url)
        return window

    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = create_window
    fake_webview.start = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(launcher, "_detach_desktop_console", lambda: False)
    monkeypatch.setattr(launcher, "_is_windows", lambda: True)
    monkeypatch.setattr(launcher, "_webview2_runtime_present", lambda: True)
    monkeypatch.setattr(launcher, "_acquire_desktop_instance", lambda: SimpleNamespace(release=lambda: None))
    monkeypatch.setattr(launcher, "choose_loopback_port", lambda preferred: 8799)
    monkeypatch.setattr(launcher, "_start_local_server", lambda host, port: SimpleNamespace(stop=lambda: None))
    monkeypatch.setattr(launcher, "_wait_for_server", lambda url, server: None)
    monkeypatch.setattr(launcher, "_stop_live_runs", lambda: None)
    monkeypatch.setattr(launcher, "load_window_geometry", lambda path: load_window_geometry(path, on_screen=ANYWHERE))
    started = []
    monkeypatch.setattr(launcher.WebViewRecovery, "start", lambda self: started.append(self))
    assert launcher.run_desktop() == 0
    assert created["url"] == "http://127.0.0.1:8799/"
    assert (created["x"], created["y"], created["width"], created["height"]) == (320, 240, 1600, 1000)
    assert created["maximized"] is True and created["min_size"] == MIN_SIZE
    assert len(started) == 1
    # The window state is saved before the live-run close confirmation runs.
    assert len(window.events.closing.handlers) == 2
    assert window.events.closing.handlers[1] is launcher._confirm_close_with_live_runs


def test_quiet_page_is_reloaded_once_not_in_a_loop() -> None:
    clock = Clock()
    watchdog = WebViewWatchdog(clock)
    clock.now += 60
    watchdog.next_action(foreground=True)
    actions = []
    for _ in range(120):  # four minutes in front of a page that never answers
        clock.now += 2
        action = watchdog.next_action(foreground=True)[0]
        if action != NONE:
            actions.append(action)
    assert actions == [REPAINT, RELOAD, REPAINT]
    watchdog.heartbeat()  # the page answers again: a later hang may reload once more
    clock.now += 30
    assert watchdog.next_action(foreground=True)[0] == REPAINT
    clock.now += 15
    assert watchdog.next_action(foreground=True)[0] == RELOAD
