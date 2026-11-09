"""Hardware-independent input lifecycle and application recovery tests."""
import errno
from types import SimpleNamespace

import pytest

from phonon_dictation import app, keyboards


def key(code, value, timestamp=0):
    return SimpleNamespace(type=app.ecodes.EV_KEY, code=code, value=value, sec=timestamp, usec=0)


class Device:
    def __init__(self, path, name="keyboard", caps=None, inode=1):
        self.path, self.name, self.inode = path, name, inode
        self.fd = self
        self.caps = [app.KEY_TALK, app.KEY_SHIFT] if caps is None else caps
        self.closed = False
        self.held = []
        self.events = []
        self.error = None

    def capabilities(self):
        return {app.ecodes.EV_KEY: self.caps}

    def active_keys(self):
        return self.held

    def close(self):
        self.closed = True

    def read(self):
        if self.error:
            raise self.error
        events, self.events = self.events, []
        return iter(events)


class Selector:
    def __init__(self):
        self.registered = {}
        self.ready = []

    def register(self, obj, mask, data):
        assert obj not in self.registered
        self.registered[obj] = SimpleNamespace(data=data)

    def unregister(self, obj):
        del self.registered[obj]

    def select(self, timeout):
        ready, self.ready = self.ready, []
        return [(self.registered[obj], 1) for obj in ready]

    def close(self):
        self.registered.clear()


@pytest.fixture
def rig(monkeypatch):
    devices, opened, notifications, removed = {}, [], [], []
    selector = Selector()
    class Udev:
        def filter_by(self, **kwargs):
            pass

        def start(self):
            pass

        def poll(self, timeout):
            return notifications.pop(0) if notifications else None

    udev = Udev()
    monkeypatch.setattr(keyboards.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(keyboards.pyudev, "Context", lambda: None)
    monkeypatch.setattr(keyboards.pyudev.Monitor, "from_netlink", lambda context: udev)
    monkeypatch.setattr(keyboards, "glob", lambda pattern: list(devices))

    def open_device(path):
        dev = devices[path]
        if isinstance(dev, OSError):
            raise dev
        opened.append(dev)
        return dev

    monkeypatch.setattr(keyboards, "InputDevice", open_device)
    monkeypatch.setattr(keyboards, "os", SimpleNamespace(
        stat=lambda path: SimpleNamespace(st_rdev=1, st_ino=devices[path].inode),
        fstat=lambda dev: SimpleNamespace(st_rdev=1, st_ino=dev.inode),
    ))
    state = app.KeyboardState()

    def remove(path, reason):
        removed.append((path, state.removed(path), reason))

    monitor = keyboards.KeyboardMonitor(state.added, remove)
    result = SimpleNamespace(devices=devices, opened=opened, notifications=notifications,
                             selector=selector, udev=udev, monitor=monitor, state=state, removed=removed)
    yield result
    monitor.close()


def notify(rig, action, path):
    rig.notifications.append(SimpleNamespace(action=action, device_node=path))
    rig.selector.ready.append(rig.udev)
    return rig.monitor.poll(0)


def test_initial_discovery_identification_and_duplicate_add(rig):
    rig.devices.update({
        "laptop": Device("laptop"),
        "solaar": Device("solaar", "solaar-keyboard virtual uinput"),
        "ctrl-only": Device("ctrl-only", caps=[app.KEY_TALK]),
        "shift-only": Device("shift-only", caps=[app.KEY_SHIFT]),
        "synthetic": Device("synthetic", "ydotoold virtual device"),
    })
    rig.monitor.reconcile()
    assert set(rig.monitor.devices) == {"laptop", "solaar", "ctrl-only"}
    assert rig.devices["synthetic"].closed
    assert rig.devices["shift-only"].closed
    notify(rig, "add", "laptop")
    assert rig.opened.count(rig.devices["laptop"]) == 1
    assert not rig.removed


def test_add_remove_last_and_reconnect_new_event_number(rig, capsys):
    rig.monitor.reconcile()
    assert "waiting for devices" in capsys.readouterr().out
    first = rig.devices["event9"] = Device("event9")
    notify(rig, "add", "event9")
    assert set(rig.monitor.devices) == {"event9"}
    del rig.devices["event9"]
    notify(rig, "remove", "event9")
    assert not rig.monitor.devices
    assert first.closed
    rig.devices["event23"] = Device("event23")
    notify(rig, "add", "event23")
    assert set(rig.monitor.devices) == {"event23"}
    assert "Keyboard monitoring restored" in capsys.readouterr().out


def test_recreation_at_same_path_detected_without_udev(rig):
    old = rig.devices["event0"] = Device("event0")
    rig.monitor.reconcile()
    new = rig.devices["event0"] = Device("event0", inode=2)
    rig.monitor.reconcile()
    assert old.closed
    assert rig.monitor.devices["event0"] is new


def test_external_keyboard_add_remove_preserves_laptop(rig):
    laptop = rig.devices["laptop"] = Device("laptop")
    rig.monitor.reconcile()
    rig.devices["external"] = Device("external")
    notify(rig, "add", "external")
    assert set(rig.monitor.devices) == {"laptop", "external"}
    del rig.devices["external"]
    notify(rig, "remove", "external")
    notify(rig, "remove", "external")
    assert set(rig.monitor.devices) == {"laptop"}
    assert not laptop.closed
    assert len(rig.removed) == 1


def test_mirrored_device_batches_are_merged_before_handling(rig):
    physical = rig.devices["physical"] = Device("physical")
    virtual = rig.devices["virtual"] = Device("virtual", "solaar-keyboard")
    rig.monitor.reconcile()
    physical.events = [key(app.KEY_TALK, 1, 1), key(app.KEY_TALK, 0, 3)]
    virtual.events = [key(app.KEY_TALK, 1, 2), key(app.KEY_TALK, 0, 4)]
    rig.selector.ready = [physical, virtual]
    actions = [rig.state.handle(path, event) for path, event in rig.monitor.poll(0)]
    assert [action for action in actions if action] == ["start", "stop"]


def test_permission_denied_retried_without_log_spam(rig, capsys):
    rig.devices["locked"] = PermissionError(errno.EACCES, "Permission denied")
    rig.monitor.reconcile()
    rig.monitor.reconcile()
    assert capsys.readouterr().out.count("Input device inaccessible") == 1
    rig.devices["locked"] = Device("locked")
    rig.monitor.next_scan = 0
    rig.monitor.poll(0)
    assert "locked" in rig.monitor.devices


@pytest.mark.parametrize("error", [errno.ENODEV, errno.EBADF, errno.EIO])
def test_stale_read_closes_device_and_cancels_state(rig, error):
    dev = rig.devices["kbd"] = Device("kbd")
    rig.monitor.reconcile()
    rig.state.handle("kbd", key(app.KEY_SHIFT, 1))
    rig.state.handle("kbd", key(app.KEY_TALK, 1))
    dev.error = OSError(error, "disconnected")
    rig.selector.ready = [dev]
    assert rig.monitor.poll(0) == []
    assert dev.closed
    assert rig.removed == [("kbd", True, "input device disconnected")]
    assert not rig.state.recording
    assert not rig.state.shift_devices
    assert not rig.state.talk_devices


def test_removal_processed_before_buffered_release(rig):
    dev = rig.devices["kbd"] = Device("kbd")
    rig.monitor.reconcile()
    rig.state.handle("kbd", key(app.KEY_TALK, 1))
    dev.events = [key(app.KEY_TALK, 0)]
    del rig.devices["kbd"]
    rig.selector.ready = [dev]
    assert notify(rig, "remove", "kbd") == []
    assert rig.removed[0][1] is True


def test_syn_dropped_cancels_instead_of_transcribing(rig):
    dev = rig.devices["kbd"] = Device("kbd")
    rig.monitor.reconcile()
    rig.state.handle("kbd", key(app.KEY_TALK, 1))
    dev.events = [SimpleNamespace(type=app.ecodes.EV_SYN, code=app.ecodes.SYN_DROPPED)]
    rig.selector.ready = [dev]
    assert rig.monitor.poll(0) == []
    assert rig.removed == [("kbd", True, "input events lost")]


def test_bad_descriptor_on_close_does_not_prevent_state_cleanup(rig):
    dev = rig.devices["kbd"] = Device("kbd")
    rig.monitor.reconcile()
    rig.state.handle("kbd", key(app.KEY_TALK, 1))

    def bad_close():
        raise OSError(errno.EBADF, "Bad file descriptor")

    dev.close = bad_close
    rig.monitor.discard("kbd")
    assert not rig.state.recording
    assert not rig.monitor.devices


def test_eof_deregisters_instead_of_busy_looping(rig):
    dev = rig.devices["kbd"] = Device("kbd")
    rig.monitor.reconcile()
    rig.selector.ready = [dev]
    assert rig.monitor.poll(0) == []
    assert dev.closed
    assert not rig.monitor.devices


def test_keys_already_held_on_discovery_do_not_start_recording(rig):
    dev = rig.devices["kbd"] = Device("kbd")
    dev.held = [app.KEY_TALK, app.KEY_SHIFT]
    rig.monitor.reconcile()
    assert rig.state.handle("kbd", key(app.KEY_TALK, 1)) is None
    assert rig.state.handle("kbd", key(app.KEY_TALK, 0)) is None
    assert rig.state.handle("kbd", key(app.KEY_TALK, 1)) == "start"
    assert rig.state.terminal_requested


def test_mirrored_modifiers_produce_only_one_start_and_stop():
    state = app.KeyboardState()
    actions = [state.handle(path, key(code, value)) for path, code, value in [
        ("physical", app.KEY_SHIFT, 1), ("physical", app.KEY_TALK, 1),
        ("solaar", app.KEY_TALK, 1), ("physical", app.KEY_SHIFT, 0),
        ("physical", app.KEY_TALK, 0), ("solaar", app.KEY_TALK, 1),
        ("solaar", app.KEY_TALK, 0),
    ]]
    assert [action for action in actions if action] == ["start", "stop"]
    assert state.terminal_requested
    assert state.handle("physical", key(app.KEY_TALK, 1)) == "start"


def test_release_from_other_keyboard_does_not_leave_trigger_stuck():
    state = app.KeyboardState()
    assert state.handle("one", key(app.KEY_TALK, 1)) == "start"
    assert state.handle("two", key(app.KEY_TALK, 0)) == "stop"
    assert state.handle("one", key(app.KEY_TALK, 1)) == "start"


def test_resume_detected_from_suspend_inclusive_clock(monkeypatch):
    offsets = iter([10, 10.001, 40, 40.001])
    monkeypatch.setattr(keyboards, "suspend_offset", lambda: next(offsets))
    watch = keyboards.ResumeWatch()
    assert not watch.resumed()
    assert watch.resumed()
    assert not watch.resumed()


@pytest.mark.parametrize("recovery", ["disconnect", "resume"])
def test_main_cancels_capture_cleans_file_and_keeps_server(monkeypatch, tmp_path, recovery):
    calls, paths = [], []
    server, recorder = object(), object()
    monkeypatch.setattr(app.sys, "argv", ["phonon-dictate"])
    monkeypatch.setattr(app.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(app, "ensure_server", lambda args: calls.append("server-start") or server)

    def start(command, **kwargs):
        paths.append(app.Path(command[-1]))
        calls.append("record")
        return recorder

    monkeypatch.setattr(app.subprocess, "Popen", start)
    monkeypatch.setattr(app, "stop_process", lambda process, *args: calls.append(
        "server-stop" if process is server else "record-stop"))
    monkeypatch.setattr(app, "transcribe", lambda *args: pytest.fail("cancelled audio must not be transcribed"))
    monkeypatch.setattr(app, "paste", lambda *args: pytest.fail("cancelled audio must not be pasted"))

    class Monitor:
        def __init__(self, added, removed):
            self.added, self.removed, self.step = added, removed, 0

        def reconcile(self):
            self.added("kbd", [])

        def poll(self):
            self.step += 1
            if self.step == 1:
                return [("kbd", key(app.KEY_TALK, 1))]
            if self.step == 2:
                if recovery == "disconnect":
                    self.removed("kbd", "input device disconnected")
                    self.added("new-kbd", [])
                return []
            assert calls == ["server-start", "record", "record-stop"]
            assert paths and all(not path.exists() for path in paths)
            raise KeyboardInterrupt

        def reset(self, reason):
            calls.append("reset")
            self.removed("kbd", reason)
            self.added("kbd", [])
            # The server must remain loaded throughout rediscovery.
            assert calls.count("server-start") == 1
            assert "server-stop" not in calls
            calls.remove("reset")

        def close(self):
            pass

    class Server:
        def poll(self):
            return None

    server = Server()
    resume_values = iter([False, recovery == "resume"])
    monkeypatch.setattr(app, "KeyboardMonitor", Monitor)
    monkeypatch.setattr(app, "ResumeWatch", lambda: SimpleNamespace(resumed=lambda: next(resume_values)))
    app.main()
    assert calls == ["server-start", "record", "record-stop", "server-stop"]


@pytest.mark.parametrize("suspended", [False, True])
def test_main_transcription_privacy_and_resume_before_paste(monkeypatch, tmp_path, capsys, suspended):
    monkeypatch.setattr(app.sys, "argv", ["phonon-dictate"])
    monkeypatch.setattr(app.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(app, "ensure_server", lambda args: None)
    monkeypatch.setattr(app, "stop_process", lambda *args: None)
    pasted = []

    def capture(command, **kwargs):
        app.Path(command[-1]).write_bytes(b"x" * 2000)
        return SimpleNamespace(returncode=255)

    monkeypatch.setattr(app.subprocess, "Popen", capture)
    monkeypatch.setattr(app, "transcribe", lambda *args: "private transcription")
    monkeypatch.setattr(app, "paste", lambda *args: pasted.append(args))

    class Monitor:
        def __init__(self, added, removed):
            self.added, self.removed, self.step = added, removed, 0

        def reconcile(self):
            self.added("kbd", [])

        def poll(self):
            self.step += 1
            if self.step == 1:
                return [("kbd", key(app.KEY_SHIFT, 1)), ("kbd", key(app.KEY_TALK, 1))]
            if self.step == 2:
                return [("kbd", key(app.KEY_SHIFT, 0)), ("kbd", key(app.KEY_TALK, 0))]
            raise KeyboardInterrupt

        def reset(self, reason):
            assert suspended
            self.removed("kbd", reason)
            self.reconcile()

        def close(self):
            pass

    checks = iter([False, False, False, suspended])
    monkeypatch.setattr(app, "KeyboardMonitor", Monitor)
    monkeypatch.setattr(app, "ResumeWatch", lambda: SimpleNamespace(resumed=lambda: next(checks)))
    app.main()
    assert pasted == ([] if suspended else [("private transcription", "terminal", 0.25)])
    assert "private transcription" not in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
