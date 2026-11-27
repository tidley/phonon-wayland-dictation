from types import SimpleNamespace
import sys

import pytest

from phonon_dictation import app, macos


@pytest.mark.parametrize("source,expected", [("default", ":0"), ("2", ":2"), ("USB Mic", ":USB Mic")])
def test_mac_recording(monkeypatch, source, expected):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    command = app.recording_command(source, "recording.wav")
    assert command[command.index("-f") + 1] == "avfoundation"
    assert command[command.index("-i") + 1] == expected
    assert command[-5:] == ["-ac", "1", "-ar", "16000", "recording.wav"]


def test_linux_recording(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    command = app.recording_command("default", "recording.wav")
    assert command[command.index("-f") + 1] == "pulse"
    assert command[command.index("-i") + 1] == "default"


def fake_quartz():
    held = set()
    q = SimpleNamespace(
        kCGEventSourceStateCombinedSessionState=0,
        CGEventSourceKeyState=lambda state, code: code in held,
        CGPreflightListenEventAccess=lambda: True,
    )
    return q, held


def test_hotkey_transitions_and_initial_held_keys(monkeypatch):
    q, held = fake_quartz()
    monkeypatch.setattr(macos, "accessibility_trusted", lambda: True)
    monkeypatch.setattr(macos, "quartz", lambda: q)
    monkeypatch.setattr(macos.time, "sleep", lambda _: None)
    state = app.KeyboardState()
    monitor = macos.KeyboardMonitor(state.added, lambda *args: None)
    held.add(62)
    monitor.reconcile()
    assert monitor.poll() == []
    held.clear()
    assert state.handle(*monitor.poll()[0]) is None
    held.update((60, 62))
    actions = [state.handle(*event) for event in monitor.poll()]
    assert actions == [None, "start"]
    assert state.terminal_requested
    assert monitor.poll() == []
    held.clear()
    assert [state.handle(*event) for event in monitor.poll()] == [None, "stop"]


def test_input_permission_error(monkeypatch):
    q, _ = fake_quartz()
    requested = []
    q.CGPreflightListenEventAccess = lambda: False
    q.CGRequestListenEventAccess = lambda: requested.append(True)
    monkeypatch.setattr(macos, "quartz", lambda: q)
    monitor = macos.KeyboardMonitor(lambda *args: None, lambda *args: None)
    with pytest.raises(SystemExit, match="Input Monitoring"):
        monitor.reconcile()
    assert requested == [True]


def test_right_option_trigger(monkeypatch):
    q, held = fake_quartz()
    monkeypatch.setattr(macos, "quartz", lambda: q)
    monkeypatch.setattr(macos.time, "sleep", lambda _: None)
    monitor = macos.KeyboardMonitor(lambda *args: None, lambda *args: None, talk_key="right-option")
    held.add(62)
    assert monitor.poll() == []  # Right Control no longer triggers recording.
    held.add(61)
    events = monitor.poll()
    assert len(events) == 1
    assert events[0][1].code == app.KEY_TALK
    assert events[0][1].value == 1
    held.clear()
    assert monitor.poll()[0][1].value == 0


def test_mac_trigger_option(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    assert app.parser().parse_args(["--talk-key", "right-option"]).talk_key == "right-option"


def test_mac_paste_uses_command_v_for_terminal(monkeypatch):
    monkeypatch.setattr(macos, "accessibility_trusted", lambda: True)
    calls = []
    q = SimpleNamespace(
        kCGEventFlagMaskCommand=123,
        kCGHIDEventTap=0,
        CGEventCreateKeyboardEvent=lambda source, key, down: (key, down),
        CGEventSetFlags=lambda event, flags: calls.append(("flags", event, flags)),
        CGEventPost=lambda tap, event: calls.append(("post", event)),
    )
    monkeypatch.setattr(macos, "quartz", lambda: q)
    monkeypatch.setattr(macos.time, "sleep", lambda _: None)
    monkeypatch.setattr(macos.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    macos.paste("héllo", "terminal", 0)
    assert calls[0][0] == ["pbcopy"]
    assert calls[0][1]["input"] == "héllo "
    assert calls[1:] == [
        ("flags", (9, True), 123), ("post", (9, True)),
        ("flags", (9, False), 123), ("post", (9, False)),
    ]


def test_accessibility_check_uses_application_services(monkeypatch):
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(
        AXIsProcessTrusted=lambda: True,
    ))
    assert macos.accessibility_trusted() is True


def test_accessibility_permission_error(monkeypatch):
    q, _ = fake_quartz()
    monkeypatch.setattr(macos, "quartz", lambda: q)
    monkeypatch.setattr(macos, "accessibility_trusted", lambda: False)
    monitor = macos.KeyboardMonitor(lambda *args: None, lambda *args: None)
    with pytest.raises(SystemExit, match="Enable Accessibility"):
        monitor.reconcile()
    with pytest.raises(OSError, match="Accessibility permission"):
        macos.paste("hello", "normal", 0)
