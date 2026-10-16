from types import SimpleNamespace

import pytest

from phonon_dictation import app


def event(code, value, event_type=app.ecodes.EV_KEY):
    return SimpleNamespace(code=code, value=value, type=event_type)


def test_right_shift_can_be_pressed_after_recording_starts():
    state = app.KeyboardState()

    assert state.handle("/dev/input/event1", event(app.KEY_TALK, 1)) == "start"
    assert state.handle("/dev/input/event2", event(app.KEY_SHIFT, 1)) is None
    assert state.handle("/dev/input/event1", event(app.KEY_TALK, 0)) == "stop"
    assert state.terminal_requested is True


def test_shift_release_on_one_device_keeps_other_shift_held():
    state = app.KeyboardState()
    state.handle("one", event(app.KEY_SHIFT, 1))
    state.handle("two", event(app.KEY_SHIFT, 1))
    state.handle("one", event(app.KEY_SHIFT, 0))

    assert state.handle("two", event(app.KEY_TALK, 1)) == "start"
    assert state.terminal_requested is True


def test_repeated_right_ctrl_press_does_not_start_duplicate_recording():
    state = app.KeyboardState()

    assert state.handle("keyboard", event(app.KEY_TALK, 1)) == "start"
    assert state.handle("keyboard", event(app.KEY_TALK, 2)) is None
    assert state.handle("keyboard", event(app.KEY_TALK, 1)) is None


def test_paste_uses_expected_clipboard_and_shortcut(monkeypatch):
    calls = []
    monkeypatch.setattr(app.time, "sleep", lambda delay: calls.append(("sleep", delay)))
    monkeypatch.setattr(app.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    app.paste("hello", "terminal", 0.1)

    assert calls[0] == ((["wl-copy", "--type", "text/plain"],), {
        "input": "hello ", "text": True, "check": True, "timeout": 5,
    })
    assert calls[1] == ("sleep", 0.1)
    assert calls[2] == ((["ydotool", "key", *app.KEYCODES["terminal"]],), {
        "check": True, "timeout": 5,
    })


def test_server_ready_rejects_non_local_endpoint():
    with pytest.raises(ValueError, match="local"):
        app.server_ready("https://example.com/v1/audio/transcriptions")


def test_server_ready_uses_local_health_endpoint(monkeypatch):
    requested = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        requested.append((request, timeout))
        return Response()

    monkeypatch.setattr(app.urllib.request, "urlopen", urlopen)

    assert app.server_ready("http://127.0.0.1:8000/v1/audio/transcriptions") is True
    assert requested == [("http://127.0.0.1:8000/health", 1)]


def test_ensure_server_reuses_healthy_server(monkeypatch):
    args = SimpleNamespace(api_url="http://127.0.0.1:8000/v1/audio/transcriptions", no_start_server=False)
    monkeypatch.setattr(app, "server_ready", lambda url: True)
    monkeypatch.setattr(app.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("should not start"))

    assert app.ensure_server(args) is None


def test_stop_process_kills_unresponsive_child():
    class Process:
        def __init__(self):
            self.signals = []
            self.killed = False
            self.wait_calls = 0

        def poll(self):
            return None

        def send_signal(self, value):
            self.signals.append(value)

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise app.subprocess.TimeoutExpired("ffmpeg", timeout)

        def kill(self):
            self.killed = True

    process = Process()
    app.stop_process(process)

    assert process.signals == [app.signal.SIGINT]
    assert process.killed is True


def test_transcribe_returns_empty_text_without_pasting(monkeypatch, tmp_path):
    recording = tmp_path / "recording.wav"
    recording.write_bytes(b"audio")
    monkeypatch.setattr(
        app.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout='{"text": "   "}'),
    )

    assert app.transcribe(recording, "http://127.0.0.1:8000/v1/audio/transcriptions") == ""


def test_remove_recording_is_safe_after_failure(tmp_path):
    recording = tmp_path / "failed.wav"
    recording.write_bytes(b"partial")

    app.remove_recording(recording)
    app.remove_recording(recording)

    assert not recording.exists()
