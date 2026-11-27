"""GNOME unlock recovery must respect source choices and session state."""
from types import SimpleNamespace
from io import StringIO
import subprocess

import pytest

from phonon_dictation.session import UnlockRecovery


def recovery(monkeypatch, *, source="phonon", locked=False, engine="xkb:us::eng", per_window=False):
    watcher = UnlockRecovery()
    calls = []
    state = {"engine": engine}

    def command(*args):
        calls.append(args)
        if args[0] == "gsettings":
            if args[-1] == "per-window":
                return str(per_window).lower()
            return repr([("ibus", "phonon"), ("xkb", "gb")] if source == "phonon"
                        else [("xkb", "gb"), ("ibus", "phonon")])
        if args[0] == "gdbus":
            return "(true,)" if locked else "(false,)"
        if len(args) == 3:
            state["engine"] = args[2]
            return ""
        return state["engine"]

    monkeypatch.setattr(watcher, "command", command)
    monkeypatch.setattr(watcher.stopping, "wait", lambda _: watcher.stopping.is_set())
    return watcher, calls, state


def test_unlock_restores_native_input_after_gnome_fallback(monkeypatch, capsys):
    watcher, calls, state = recovery(monkeypatch)
    watcher.process = SimpleNamespace(stdout=StringIO(
        "/org/gnome/ScreenSaver: org.gnome.ScreenSaver.ActiveChanged (true,)\n"
        "/org/gnome/ScreenSaver: org.gnome.ScreenSaver.ActiveChanged (false,)\n"
    ))
    watcher.watch()
    assert state["engine"] == "phonon"
    assert calls.count(("ibus", "engine", "phonon")) == 1
    assert "Restored Phonon" in capsys.readouterr().out


@pytest.mark.parametrize("options", [
    {"source": "keyboard"}, {"locked": True}, {"per_window": True},
    {"engine": "phonon"}, {"engine": "xkb:gb::eng"},
])
def test_unlock_does_not_override_other_sources_or_locked_session(monkeypatch, options):
    watcher, calls, _ = recovery(monkeypatch, **options)
    watcher.recover()
    assert ("ibus", "engine", "phonon") not in calls


def test_retry_rechecks_user_choice(monkeypatch):
    watcher, calls, _ = recovery(monkeypatch)
    original = watcher.command
    attempts = []

    def command(*args):
        if args == ("ibus", "engine", "phonon"):
            attempts.append(args)
            raise subprocess.CalledProcessError(1, args)
        if attempts and args[-1] == "mru-sources":
            return "[('xkb', 'gb'), ('ibus', 'phonon')]"
        return original(*args)

    monkeypatch.setattr(watcher, "command", command)
    watcher.recover()
    assert len(attempts) == 1


def test_shutdown_cancels_pending_restoration(monkeypatch):
    watcher, calls, _ = recovery(monkeypatch)
    watcher.stopping.set()
    watcher.recover()
    assert calls == []


def test_failed_activation_has_bounded_retries(monkeypatch, capsys):
    watcher = UnlockRecovery()
    monkeypatch.setattr(watcher.stopping, "wait", lambda _: False)
    monkeypatch.setattr(watcher, "should_restore", lambda: True)
    attempts = []

    def fail(*args):
        attempts.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(watcher, "command", fail)
    watcher.recover()
    assert len(attempts) == 3
    assert "Could not restore" in capsys.readouterr().out
