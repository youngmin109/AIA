"""Match the native Windows title bar to the dark glass theme (EPIC-020).

Windows 11 lets an app colour its own caption through DWM attributes, so the
window keeps the normal title bar (snap, drag, min/max/close) while blending
with the page. Windows 10 ignores the colour attributes and only applies the
dark caption; neither path affects protection behaviour.
"""

from __future__ import annotations

import ctypes
from typing import Any

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

# The darkest stop of each colour theme's page gradient (frontend theme.css).
TINT_CAPTIONS = {"violet": "#1d0d4d", "indigo": "#0f1a4d", "teal": "#0b2a3a"}
TEXT_COLOR = "#ffffff"


def colorref(hex_color: str) -> int:
    """``#rrggbb`` to a Win32 COLORREF (0x00bbggrr)."""

    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def apply_title_bar(hwnd: int, tint: str = "violet", *, dwmapi: Any | None = None) -> bool:
    """Colour the caption of ``hwnd``; True only when every attribute was accepted."""

    caption = TINT_CAPTIONS.get(tint, TINT_CAPTIONS["violet"])
    if dwmapi is None:
        dwmapi = ctypes.windll.dwmapi
    accepted = True
    for attribute, value in (
        (DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
        (DWMWA_CAPTION_COLOR, colorref(caption)),
        (DWMWA_BORDER_COLOR, colorref(caption)),
        (DWMWA_TEXT_COLOR, colorref(TEXT_COLOR)),
    ):
        data = ctypes.c_int(value)
        result = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
        )
        accepted = accepted and result == 0
    return accepted


def window_handle(window: Any) -> int | None:
    """The HWND behind a pywebview WinForms window, or None before it exists."""

    try:
        return int(window.native.Handle.ToInt64())
    except Exception:
        return None
