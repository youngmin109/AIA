"""Where the desktop pet window goes when it folds into a bubble and back.

Display only: no run, policy or evidence data.  All values are physical
pixels, like the Win32 calls that read and place the window.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

# Side of the folded pet window, in logical pixels.
BUBBLE_SIZE = 76
# The pet figure's centre in the unfolded window, as a share of its height
# (the status note takes the bottom of the window).
FIGURE_CENTRE = 0.36

Rect = tuple[int, int, int, int]


def fold_rect(window: Rect, work_area: Rect, scale: float, size: tuple[int, int], *, folded: bool) -> Rect:
    """New ``(x, y, width, height)`` of the pet window.

    Folding puts the bubble on the pet figure; unfolding grows the window
    around the bubble.  Either way the window stays inside the monitor's
    work area.
    """

    left, top, right, bottom = window
    if folded:
        width = height = round(BUBBLE_SIZE * scale)
        x = (left + right) // 2 - width // 2
        y = top + round((bottom - top) * FIGURE_CENTRE) - height // 2
    else:
        width, height = round(size[0] * scale), round(size[1] * scale)
        x = (left + right) // 2 - width // 2
        y = (top + bottom) // 2 - round(height * FIGURE_CENTRE)
    work_left, work_top, work_right, work_bottom = work_area
    x = max(work_left, min(x, work_right - width))
    y = max(work_top, min(y, work_bottom - height))
    return x, y, width, height


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def window_screen(handle: int) -> tuple[Rect, Rect, float]:
    """The window's rectangle, its monitor's work area and its DPI scale."""

    user32 = ctypes.windll.user32
    hwnd = ctypes.c_void_p(handle)
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
    work = info.rcWork
    scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
    return (rect.left, rect.top, rect.right, rect.bottom), (work.left, work.top, work.right, work.bottom), scale


def place_window(handle: int, rect: Rect) -> None:
    """Move and size the window without taking focus or changing its stacking."""

    x, y, width, height = rect
    # SWP_NOZORDER | SWP_NOACTIVATE
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(handle), None, x, y, width, height, 0x0004 | 0x0010)
