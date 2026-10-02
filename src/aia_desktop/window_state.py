"""Remember the desktop window's normal bounds and maximized state.

The state is plain display preference: no run, policy or evidence data.
Bounds are stored in physical pixels with the DPI scale they were captured
at, and are handed to pywebview in logical pixels, which pywebview scales
back with the DPI of the new window.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
from typing import Any, Callable

DEFAULT_SIZE = (1440, 900)
MIN_SIZE = (1024, 680)
_MONITOR_DEFAULTTONULL = 0


def window_state_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    return root / "AIA" / "desktop-window.json"


def point_on_a_monitor(x: int, y: int) -> bool:
    """True when the screen point lies on a connected monitor."""

    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        return bool(user32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), _MONITOR_DEFAULTTONULL))
    except (AttributeError, OSError):
        return True


def load_window_geometry(
    path: Path,
    *,
    on_screen: Callable[[int, int], bool] = point_on_a_monitor,
) -> dict[str, Any]:
    """Return ``create_window`` geometry, falling back to the defaults.

    A missing or damaged file, or a saved position whose title bar would
    not be on any monitor (for example after unplugging a display), gives
    the default centred window.  Sizes never go below ``MIN_SIZE``.
    """

    defaults: dict[str, Any] = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        x, y, width, height = (int(state[key]) for key in ("x", "y", "width", "height"))
        scale = float(state.get("scale", 1.0))
        maximized = state.get("maximized") is True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return defaults
    if not 0.5 <= scale <= 5.0:
        return defaults
    # The title bar must stay reachable: its top centre has to be on a monitor.
    if not on_screen(x + width // 2, y + int(8 * scale)):
        return {**defaults, "maximized": maximized}
    return {
        "x": round(x / scale),
        "y": round(y / scale),
        "width": max(round(width / scale), MIN_SIZE[0]),
        "height": max(round(height / scale), MIN_SIZE[1]),
        "maximized": maximized,
    }


def capture_window_state(form: Any, dpi_for_window: Callable[[int], int] | None = None) -> dict[str, Any] | None:
    """Read the WinForms form's normal bounds; ``None`` if it cannot be read.

    ``RestoreBounds`` keeps the normal bounds while the window is maximized
    or minimized, so a maximized window reopens maximized over the same
    normal size.
    """

    try:
        state = str(form.WindowState)
        maximized = state.endswith("Maximized")
        bounds = form.Bounds if state.endswith("Normal") else form.RestoreBounds
        handle = int(form.Handle.ToInt64())
        dpi = (dpi_for_window or _dpi_for_window)(handle) or 96
        return {
            "x": int(bounds.X),
            "y": int(bounds.Y),
            "width": int(bounds.Width),
            "height": int(bounds.Height),
            "scale": dpi / 96,
            "maximized": maximized,
        }
    except Exception:
        return None


def save_window_state(path: Path, state: dict[str, Any] | None) -> None:
    if state is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # Losing the window position is harmless; never block closing.
        return


def _dpi_for_window(handle: int) -> int:
    return int(ctypes.windll.user32.GetDpiForWindow(ctypes.c_void_p(handle)))

