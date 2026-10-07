from types import SimpleNamespace
import sys

from aia_desktop import launcher
from aia_desktop.launcher import DesktopBridge


class Event:
    def __init__(self): self.handlers = []
    def __iadd__(self, handler): self.handlers.append(handler); return self


def test_guardian_is_independent_on_top_and_survives_hide_main_but_closes_with_main(monkeypatch):
    calls = []
    child = SimpleNamespace(events=SimpleNamespace(closing=Event(), loaded=Event()), hide=lambda: calls.append('hide'),
                            show=lambda: calls.append('show'), destroy=lambda: calls.append('destroy'),
                            resize=lambda *size: calls.append(size))
    def create(title, url, **options):
        calls.append((title, url, options)); return child
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(create_window=create))
    bridge = DesktopBridge()
    bridge._configure_guardian('http://127.0.0.1:8787/')
    assert bridge.set_guardian_visible(True)
    options = calls[0][2]
    assert options['on_top'] and options['frameless'] and options['transparent']
    assert calls[0][1].endswith('?surface=guardian')
    assert bridge.set_guardian_visible(False)
    assert bridge.set_guardian_visible(True)
    assert child.events.closing.handlers[0]() is False
    assert calls[-1] == 'hide'
    bridge._close_guardian()
    assert calls[-1] == 'destroy'
    assert child.events.closing.handlers[0]() is True
    assert bridge.set_guardian_visible(True) is False


def test_guardian_navigation_is_display_only_and_rejects_untrusted_values():
    calls = []
    bridge = DesktopBridge()
    bridge.attach(SimpleNamespace(show=lambda: calls.append('show'), restore=lambda: calls.append('restore'),
                                  evaluate_js=lambda script: calls.append(script)))
    assert bridge.open_main('work', 'session-123') is True
    assert 'aia:navigate' in calls[-1]
    assert bridge.open_main('execute', None) is False
    assert bridge.open_main('work', '../secret') is False


def test_guardian_size_is_validated_and_applies_before_and_after_creation(monkeypatch):
    calls = []
    child = SimpleNamespace(events=SimpleNamespace(closing=Event(), loaded=Event()),
                            resize=lambda *size: calls.append(size),
                            evaluate_js=lambda script: calls.append(script))
    def create(title, url, **options):
        calls.append(options); return child
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(create_window=create))
    bridge = DesktopBridge()
    bridge._configure_guardian('http://127.0.0.1:8787/')
    assert bridge.set_guardian_size('large')
    assert bridge.set_guardian_visible(True)
    assert (calls[0]['width'], calls[0]['height']) == (340, 410)
    assert bridge.set_guardian_size('small')
    assert calls[-2] == (240, 300)
    assert '"small"' in calls[-1]
    before = list(calls)
    assert bridge.set_guardian_size(None) is False
    assert bridge.set_guardian_size('arbitrary-script') is False
    assert calls == before


def test_pet_window_is_reshown_without_focus_so_the_desktop_shows_through(monkeypatch):
    # pywebview paints a transparent window grey after its first load and after
    # it grows; a hide and a no-activate show clear it.
    native = []
    monkeypatch.setattr(launcher.ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
        ShowWindow=lambda handle, command: native.append((handle, command)))), raising=False)
    calls = []
    child = SimpleNamespace(events=SimpleNamespace(closing=Event(), loaded=Event()),
                            native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 77)),
                            hide=lambda: calls.append('hide'), show=lambda: calls.append('show'),
                            resize=lambda *size: calls.append(size), evaluate_js=lambda script: None)
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(create_window=lambda title, url, **options: child))
    bridge = DesktopBridge()
    bridge._configure_guardian('http://127.0.0.1:8787/')
    assert bridge.set_guardian_visible(True)
    child.events.loaded.handlers[0]()
    assert native == [(77, 0), (77, 4)]
    assert bridge.set_guardian_size('large')
    assert calls[-1] == (340, 410) and native[-2:] == [(77, 0), (77, 4)]

    # A hidden pet stays hidden: no resize (it would show the window) and no reshow.
    assert bridge.set_guardian_visible(False)
    native.clear(); calls.clear()
    assert bridge.set_guardian_size('small')
    child.events.loaded.handlers[0]()
    assert calls == [] and native == []
    # Shown again, it takes the chosen size.
    assert bridge.set_guardian_visible(True)
    assert calls == [(240, 300), 'show'] and native == [(77, 0), (77, 4)]
