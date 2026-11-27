"""Recover GNOME's cancelled IBus activation after unlocking the session."""
from __future__ import annotations

import ast
import os
import subprocess
import threading


class UnlockRecovery:
    """Watch only session transitions; never hold up keyboard monitoring."""

    def __init__(self):
        self.stopping = threading.Event()
        self.process = None
        self.thread = None

    def start(self, output):
        if output == "clipboard" or "GNOME" not in os.getenv("XDG_CURRENT_DESKTOP", "").upper().split(":"):
            return
        try:
            self.process = subprocess.Popen(
                ["gdbus", "monitor", "--session", "--dest", "org.gnome.ScreenSaver",
                 "--object-path", "/org/gnome/ScreenSaver"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            print(f"Unlock recovery unavailable: {exc}", flush=True)
            return
        self.thread = threading.Thread(target=self.watch, name="unlock-recovery", daemon=True)
        self.thread.start()

    def command(self, *args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=2).stdout.strip()

    def should_restore(self):
        # MRU is the user's selection, unlike the temporary password/fallback
        # engine. Per-window selection cannot be inferred from this setting.
        schema = "org.gnome.desktop.input-sources"
        if self.command("gsettings", "get", schema, "per-window") != "false":
            return False
        sources = ast.literal_eval(
            self.command("gsettings", "get", schema, "mru-sources").removeprefix("@a(ss) ")
        )
        if not sources or sources[0] != ("ibus", "phonon"):
            return False
        active = self.command(
            "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
            "--object-path", "/org/gnome/ScreenSaver", "--method", "org.gnome.ScreenSaver.GetActive",
        )
        if active != "(false,)":
            return False
        # This is GNOME's hard-coded fallback after SetGlobalEngine fails.
        # Do not replace other engines or reactivate an already-working Phonon.
        return self.command("ibus", "engine") == "xkb:us::eng"

    def recover(self):
        # Let GNOME finish password-context teardown before reactivating. A
        # bounded retry handles another cancelled request without a polling loop.
        for _ in range(3):
            if self.stopping.wait(0.75):
                return
            try:
                if not self.should_restore():
                    return
                if self.stopping.is_set():
                    return
                self.command("ibus", "engine", "phonon")
                if self.command("ibus", "engine") == "phonon":
                    print("Restored Phonon input after unlock", flush=True)
                    return
            except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
                continue
        print("Could not restore Phonon input after unlock; select it from the input-source menu", flush=True)

    def watch(self):
        for line in self.process.stdout:
            if self.stopping.is_set():
                break
            if "org.gnome.ScreenSaver.ActiveChanged (false,)" in line:
                self.recover()

    def close(self):
        self.stopping.set()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.thread is not None:
            self.thread.join(timeout=10)
        if self.process is not None:
            self.process.stdout.close()
