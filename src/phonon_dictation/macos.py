"""macOS input and clipboard backend; no Linux input libraries are imported."""
from __future__ import annotations

import ctypes
import subprocess
import time
from types import SimpleNamespace


# Internal evdev-compatible identifiers, not macOS virtual key codes.
ecodes = SimpleNamespace(EV_KEY=1, KEY_RIGHTCTRL=97, KEY_RIGHTSHIFT=54)
MAC_KEYS = {ecodes.KEY_RIGHTCTRL: 62, ecodes.KEY_RIGHTSHIFT: 60}
DEVICE = "macos-session"


def quartz():
    import Quartz
    return Quartz


def accessibility_trusted():
    from ApplicationServices import AXIsProcessTrusted
    return AXIsProcessTrusted()


def suspend_offset():
    """Difference between suspend-inclusive and awake Mach clocks."""
    # Initialize once; these clocks share the same timebase.
    if not hasattr(suspend_offset, "clock"):
        clock = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

        base = Timebase()
        clock.mach_timebase_info(ctypes.byref(base))
        clock.mach_continuous_time.restype = ctypes.c_uint64
        clock.mach_absolute_time.restype = ctypes.c_uint64
        suspend_offset.clock = clock
        suspend_offset.scale = base.numer / base.denom / 1e9
    clock = suspend_offset.clock
    return (clock.mach_continuous_time() - clock.mach_absolute_time()) * suspend_offset.scale


class KeyboardMonitor:
    """Poll only the two hotkey modifiers, never ordinary typed characters.

    macOS exposes session-wide key state, not physical-keyboard ownership.
    """

    def __init__(self, added, removed, talk_key="right-control"):
        self.added, self.removed = added, removed
        self.q = quartz()
        self.held = set()
        self.keys = dict(MAC_KEYS)
        # Normalize the configurable physical key to the shared talk identifier.
        self.keys[ecodes.KEY_RIGHTCTRL] = {"right-control": 62, "right-option": 61}[talk_key]

    def read_held(self):
        return {
            key for key, code in self.keys.items()
            if self.q.CGEventSourceKeyState(self.q.kCGEventSourceStateCombinedSessionState, code)
        }

    def reconcile(self):
        if not self.q.CGPreflightListenEventAccess():
            self.q.CGRequestListenEventAccess()
            raise SystemExit(
                "Enable Input Monitoring for your terminal/Python in System Settings > "
                "Privacy & Security, then restart the terminal and retry."
            )
        if not accessibility_trusted():
            raise SystemExit(
                "Enable Accessibility for your terminal/Python in System Settings > "
                "Privacy & Security, then restart the terminal and retry."
            )
        self.held = self.read_held()
        self.added(DEVICE, self.held)

    def poll(self):
        time.sleep(0.01)
        held = self.read_held()
        # Shift first so simultaneous Ctrl/Shift changes retain terminal mode.
        events = [
            (DEVICE, SimpleNamespace(type=ecodes.EV_KEY, code=key, value=int(key in held)))
            for key in (ecodes.KEY_RIGHTSHIFT, ecodes.KEY_RIGHTCTRL)
            if (key in held) != (key in self.held)
        ]
        self.held = held
        return events

    def reset(self, reason):
        self.removed(DEVICE, reason)
        self.held = self.read_held()
        self.added(DEVICE, self.held)

    def close(self):
        pass


def paste(text, mode, delay):
    q = quartz()
    if not accessibility_trusted():
        raise OSError("Accessibility permission is required to paste")
    subprocess.run(["pbcopy"], input=text + " ", text=True, encoding="utf-8", check=True, timeout=5)
    time.sleep(max(0, delay))
    # Command+V is also the standard terminal paste shortcut on macOS.
    for down in (True, False):
        event = q.CGEventCreateKeyboardEvent(None, 9, down)
        q.CGEventSetFlags(event, q.kCGEventFlagMaskCommand)
        q.CGEventPost(q.kCGHIDEventTap, event)
