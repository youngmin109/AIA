from __future__ import annotations

import ctypes
import types

from aia_desktop.launcher import DesktopBridge
from aia_desktop.title_bar import (
    DWMWA_CAPTION_COLOR,
    DWMWA_TEXT_COLOR,
    DWMWA_USE_IMMERSIVE_DARK_MODE,
    apply_title_bar,
    colorref,
    window_handle,
)


class FakeDwm:
    def __init__(self, result: int = 0) -> None:
        self.calls: list[tuple[int, int]] = []
        self.result = result

    def DwmSetWindowAttribute(self, hwnd, attribute, data, size):  # noqa: N802 - Win32 name
        value = ctypes.cast(data, ctypes.POINTER(ctypes.c_int)).contents.value
        self.calls.append((attribute, value))
        return self.result


def test_colorref_uses_win32_byte_order() -> None:
    assert colorref("#1d0d4d") == 0x4D0D1D
    assert colorref("ffffff") == 0xFFFFFF


def test_title_bar_follows_the_colour_theme_with_white_text() -> None:
    dwm = FakeDwm()

    assert apply_title_bar(42, "teal", dwmapi=dwm) is True
    attributes = dict(dwm.calls)
    assert attributes[DWMWA_USE_IMMERSIVE_DARK_MODE] == 1
    assert attributes[DWMWA_CAPTION_COLOR] == colorref("#0b2a3a")
    assert attributes[DWMWA_TEXT_COLOR] == colorref("#ffffff")


def test_unknown_tint_falls_back_and_rejection_is_reported() -> None:
    dwm = FakeDwm(result=-2147024809)  # E_INVALIDARG on Windows 10 for caption colour

    assert apply_title_bar(42, "light", dwmapi=dwm) is False
    assert dict(dwm.calls)[DWMWA_CAPTION_COLOR] == colorref("#1d0d4d")


def test_bridge_without_a_native_window_does_nothing() -> None:
    bridge = DesktopBridge()
    assert bridge.set_title_bar("violet") is False
    bridge.attach(types.SimpleNamespace(native=None))
    assert window_handle(types.SimpleNamespace(native=None)) is None
    assert bridge.set_title_bar("violet") is False
