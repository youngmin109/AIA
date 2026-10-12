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
    bridge.attach(SimpleNamespace(show=lambda: calls.append('show'), maximize=lambda: calls.append('maximize'),
                                  evaluate_js=lambda script: calls.append(script)))
    assert bridge.open_main('work', 'session-123') is True
    # Opened from the pet, AIA comes back maximized rather than as a small window.
    assert calls[:2] == ['show', 'maximize']
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
    assert (calls[0]['width'], calls[0]['height']) == (260, 286)
    assert bridge.set_guardian_size('small')
    assert calls[-2] == (160, 176)
    assert '"80"' in calls[-1]
    before = list(calls)
    assert bridge.set_guardian_size(None) is False
    assert bridge.set_guardian_size('arbitrary-script') is False
    for invalid in [True, False, 69, 141, 101, 100.0, float('nan'), float('inf'), [], {}]:
        assert bridge.set_guardian_size(invalid) is False
    assert calls == before
    assert bridge.set_guardian_size(70)
    assert bridge.set_guardian_size(140)


def test_pet_window_is_reshown_without_focus_so_the_desktop_shows_through(monkeypatch):
    # pywebview paints a transparent window grey after its first load and after
    # it grows; a hide and a no-activate show clear it.
    native = []
    monkeypatch.setattr(launcher.ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
        ShowWindow=lambda handle, command: native.append((handle, command)))), raising=False)
    calls = []
    monkeypatch.setattr(launcher.guardian_window, 'hide_from_switcher', lambda handle: None)
    monkeypatch.setattr(launcher.guardian_window, 'window_screen', lambda handle: ((0, 0, 200, 220), (0, 0, 1920, 1080), 1.0))
    monkeypatch.setattr(launcher.guardian_window, 'place_window', lambda handle, rect: calls.append(rect[2:]))
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
    assert calls[-1] == (260, 286) and native[-2:] == [(77, 0), (77, 4)]

    # A hidden pet stays hidden: no resize (it would show the window) and no reshow.
    assert bridge.set_guardian_visible(False)
    native.clear(); calls.clear()
    assert bridge.set_guardian_size('small')
    child.events.loaded.handlers[0]()
    assert calls == [] and native == []
    # Shown again, it takes the chosen size.
    assert bridge.set_guardian_visible(True)
    assert calls == [(160, 176), 'show'] and native == [(77, 0), (77, 4)]


def test_folding_puts_a_bubble_on_the_pet_and_unfolding_grows_around_it_on_screen():
    from aia_desktop.guardian_window import fold_rect

    work = (0, 0, 1920, 1040)
    # A 280x340 pet at (1000, 300): the bubble sits on the figure, and unfolds back to the same place.
    assert fold_rect((1000, 300, 1280, 640), work, 1.0, (280, 340), folded=True) == (1102, 384, 76, 76)
    assert fold_rect((1102, 384, 1178, 460), work, 1.0, (280, 340), folded=False) == (1000, 300, 280, 340)
    # A bubble dragged to the corner unfolds inside the work area.
    assert fold_rect((1840, 960, 1916, 1036), work, 1.0, (280, 340), folded=False) == (1640, 700, 280, 340)
    assert fold_rect((-30, -30, 46, 46), work, 1.0, (280, 340), folded=False) == (0, 0, 280, 340)
    # Physical pixels follow the DPI scale.
    assert fold_rect((0, 0, 420, 510), work, 1.5, (280, 340), folded=True)[2:] == (114, 114)


def test_folding_moves_the_window_and_a_folded_pet_keeps_its_bubble(monkeypatch):
    native, placed, calls = [], [], []
    monkeypatch.setattr(launcher.guardian_window, 'hide_from_switcher', lambda handle: None)
    monkeypatch.setattr(launcher.ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
        ShowWindow=lambda handle, command: native.append((handle, command)))), raising=False)
    monkeypatch.setattr(launcher.guardian_window, 'window_screen',
                        lambda handle: ((1000, 300, 1280, 640), (0, 0, 1920, 1040), 1.0))
    monkeypatch.setattr(launcher.guardian_window, 'place_window', lambda handle, rect: placed.append((handle, rect)))
    child = SimpleNamespace(events=SimpleNamespace(closing=Event(), loaded=Event()),
                            native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 77)),
                            hide=lambda: calls.append('hide'), show=lambda: calls.append('show'),
                            resize=lambda *size: calls.append(size), evaluate_js=lambda script: None)
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(create_window=lambda title, url, **options: child))
    bridge = DesktopBridge()
    bridge._configure_guardian('http://127.0.0.1:8787/')
    assert bridge.set_guardian_folded(True) is False  # no pet window yet
    assert bridge.set_guardian_visible(True)
    assert bridge.set_guardian_folded('yes') is False

    assert bridge.set_guardian_folded(True)
    # Every change of size is reshown so the corners around the bubble stay see-through.
    assert placed == [(77, (1102, 384, 76, 76))] and native == [(77, 0), (77, 4)]
    assert bridge.set_guardian_folded(True) and len(placed) == 1
    # Folded, a new size waits for the unfold, and showing again keeps the bubble.
    assert bridge.set_guardian_size('large') and calls == []
    assert bridge.set_guardian_visible(False) and bridge.set_guardian_visible(True)
    assert calls == ['hide', 'show']

    calls.clear(); native.clear()
    assert bridge.set_guardian_folded(False)
    assert placed[-1] == (77, (1010, 367, 260, 286))
    assert native == [(77, 0), (77, 4)]


def test_pet_is_tool_window_not_app_window_without_changing_other_styles(monkeypatch):
    from aia_desktop import guardian_window
    writes, positions = [], []
    # Existing APPWINDOW, TOPMOST, NOACTIVATE and LAYERED flags.
    initial = 0x40000 | 0x8 | 0x08000000 | 0x80000
    getter = lambda handle, index: initial
    setter = lambda handle, index, style: writes.append((index, style))
    api = SimpleNamespace(SetWindowPos=lambda *args: positions.append(args))
    suffix = 'PtrW' if launcher.ctypes.sizeof(launcher.ctypes.c_void_p) == 8 else 'W'
    setattr(api, 'GetWindowLong' + suffix, getter)
    setattr(api, 'SetWindowLong' + suffix, setter)
    monkeypatch.setattr(guardian_window.ctypes, 'windll', SimpleNamespace(user32=api), raising=False)
    guardian_window.hide_from_switcher(77)
    assert writes == [(-20, (initial | 0x80) & ~0x40000)]
    assert positions[0][-1] == 0x37  # no focus, position, size or z-order changes


def test_pet_resize_keeps_centre_and_stays_on_current_monitor():
    from aia_desktop.guardian_window import resized_rect
    assert resized_rect((400, 400, 600, 620), (0, 0, 1920, 1040), 1, (280, 308)) == (360, 356, 280, 308)
    assert resized_rect((1820, 930, 1920, 1040), (0, 0, 1920, 1040), 1, (280, 308)) == (1640, 732, 280, 308)
    assert resized_rect((-1920, 0, -1720, 220), (-1920, 0, 0, 1040), 1.5, (280, 308)) == (-1920, 0, 420, 462)


def test_pet_help_opens_main_help_without_navigating_or_performing_security_actions():
    calls = []
    bridge = DesktopBridge()
    assert bridge.open_guardian_help('report') is False
    bridge.attach(SimpleNamespace(show=lambda: calls.append('show'), maximize=lambda: calls.append('maximize'),
                                  evaluate_js=lambda script: calls.append(script)))
    assert bridge.open_guardian_help('report')
    assert calls[:2] == ['show', 'maximize']
    assert 'aia:guardian-help' in calls[-1] and '"report"' in calls[-1]
    assert 'aia:navigate' not in calls[-1]
    before = list(calls)
    for invalid in ['execute', 'approve', '../secret', None, []]:
        assert bridge.open_guardian_help(invalid) is False
    assert calls == before


def test_codex_trust_terminal_is_a_fixed_command_with_codex_typed_in_not_run(monkeypatch):
    started = []
    monkeypatch.setattr(launcher, '_is_windows', lambda: True)
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda args, **options: started.append((args, options)))
    monkeypatch.setenv('CODEX_THREAD_ID', 'leak')
    monkeypatch.setenv('CODEX_HOME', 'C:/codex-home')
    assert DesktopBridge().open_codex_terminal() is True
    args, options = started[0]
    assert args[:4] == ['powershell.exe', '-NoExit', '-NoLogo', '-Command']
    # "codex" is inserted into the prompt for the user to run; nothing is executed for them.
    assert "Insert('codex')" in args[4] and '/hooks' in args[4]
    assert 'CODEX_THREAD_ID' not in options['env'] and options['env']['CODEX_HOME'] == 'C:/codex-home'

    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda args, **options: (_ for _ in ()).throw(OSError('no shell')))
    assert DesktopBridge().open_codex_terminal() is False
    monkeypatch.setattr(launcher, '_is_windows', lambda: False)
    assert DesktopBridge().open_codex_terminal() is False


def test_records_folder_opens_the_control_root_only(monkeypatch, tmp_path):
    opened = []
    root = tmp_path / 'control'
    monkeypatch.setattr(launcher, '_is_windows', lambda: True)
    monkeypatch.setenv('AIA_CONTROL_ROOT', str(root))
    monkeypatch.setattr(launcher.os, 'startfile', lambda path: opened.append(path), raising=False)
    assert DesktopBridge().open_records_folder() is True
    assert opened == [str(root)] and root.is_dir()
