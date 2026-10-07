from types import SimpleNamespace
import sys

from aia_desktop.launcher import DesktopBridge


class Event:
    def __init__(self): self.handlers = []
    def __iadd__(self, handler): self.handlers.append(handler); return self


def test_guardian_is_independent_on_top_and_survives_hide_main_but_closes_with_main(monkeypatch):
    calls = []
    child = SimpleNamespace(events=SimpleNamespace(closing=Event()), hide=lambda: calls.append('hide'),
                            show=lambda: calls.append('show'), destroy=lambda: calls.append('destroy'))
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
    child = SimpleNamespace(events=SimpleNamespace(closing=Event()),
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
