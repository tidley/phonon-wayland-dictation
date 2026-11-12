"""Dynamic evdev registration; independent of audio and the speech server."""
from __future__ import annotations

import os
import selectors
import time
from dataclasses import dataclass
from glob import glob

import pyudev
from evdev import InputDevice, ecodes


@dataclass
class KeySnapshot:
    """Ordered state recovery, rather than a synthetic press or release."""

    held: list[int] | None
    sec: int
    usec: int


def suspend_offset():
    """CLOCK_BOOTTIME includes suspend; CLOCK_MONOTONIC does not (Linux)."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()


def close_device(dev):
    try:
        dev.close()
    except OSError:
        # EBADF can be the reason we are cleaning up this handle.
        pass


class ResumeWatch:
    def __init__(self):
        self.offset = suspend_offset()

    def resumed(self):
        offset = suspend_offset()
        resumed = offset - self.offset > 0.1
        self.offset = offset
        return resumed


class KeyboardMonitor:
    """Use udev wakeups plus a five-second safety/permission reconciliation."""

    def __init__(self, added, removed):
        self.added = added
        self.removed = removed
        self.devices = {}
        self.identities = {}
        self.syncing = set()
        self.inaccessible = set()
        self.available = None
        self.next_scan = 0
        self.selector = selectors.DefaultSelector()
        self.udev = pyudev.Monitor.from_netlink(pyudev.Context())
        self.udev.filter_by(subsystem="input")
        # Listen before discovery so additions during the scan aren't lost.
        self.udev.start()
        self.selector.register(self.udev, selectors.EVENT_READ, None)

    @staticmethod
    def identity(stat):
        return stat.st_rdev, stat.st_ino

    def discard(self, path, reason="input device disconnected"):
        dev = self.devices.pop(path, None)
        if dev is None:
            return
        self.identities.pop(path, None)
        self.syncing.discard(path)
        try:
            self.selector.unregister(dev)
        except (KeyError, ValueError, OSError):
            pass
        close_device(dev)
        print(f"Input device removed: {dev.name} ({path})", flush=True)
        self.removed(path, reason)

    def reconcile(self):
        # evdev.list_devices() filters inaccessible devices (and in newer
        # versions defaults to requiring write access). Probe read access here
        # so denied devices can be diagnosed and retried after ACL changes.
        paths = set(glob("/dev/input/event*"))
        for path in list(self.devices):
            try:
                unchanged = self.identity(os.stat(path)) == self.identities[path]
            except OSError:
                unchanged = False
            if path not in paths or not unchanged:
                self.discard(path)
        self.inaccessible.intersection_update(paths)
        for path in sorted(paths - self.devices.keys()):
            dev = None
            try:
                dev = InputDevice(path)
                caps = dev.capabilities().get(ecodes.EV_KEY, [])
                # ydotoold's default uinput name; don't exclude Solaar or
                # arbitrary legitimate devices just because they're virtual.
                modifiers = {ecodes.KEY_RIGHTCTRL, ecodes.KEY_RIGHTSHIFT}
                if not modifiers.intersection(caps) or "ydotool" in dev.name.casefold():
                    close_device(dev)
                    continue
                identity = self.identity(os.fstat(dev.fd))
                held = dev.active_keys()
                self.selector.register(dev, selectors.EVENT_READ, dev)
                self.devices[path] = dev
                self.identities[path] = identity
                self.inaccessible.discard(path)
                self.added(path, held)
                print(f"Input device added: {dev.name} ({path})", flush=True)
            except OSError as exc:
                if dev is not None:
                    close_device(dev)
                if path not in self.inaccessible:
                    print(f"Input device inaccessible: {path} ({exc.strerror or exc})", flush=True)
                    self.inaccessible.add(path)
        available = bool(self.devices)
        if available != self.available:
            print("Keyboard monitoring restored" if available else
                  "No usable keyboards currently available; waiting for devices", flush=True)
            self.available = available
        self.next_scan = time.monotonic() + 5

    def reset(self, reason):
        for path in list(self.devices):
            self.discard(path, reason)
        self.reconcile()

    def poll(self, timeout=1):
        ready = self.selector.select(timeout)
        # Apply removals before returning any buffered key releases.
        for key, _ in ready:
            if key.data is None:
                while (event := self.udev.poll(timeout=0)) is not None:
                    if event.action == "remove":
                        self.discard(event.device_node)
                self.next_scan = 0
        if time.monotonic() >= self.next_scan:
            self.reconcile()
        events = []
        for key, _ in ready:
            dev = key.data
            if dev is None or self.devices.get(dev.path) is not dev:
                continue
            try:
                snapshot_at = None
                while True:
                    try:
                        batch = list(dev.read())
                    except BlockingIOError:
                        break
                    if not batch:
                        self.discard(dev.path)
                        break
                    for event in batch:
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            if dev.path not in self.syncing:
                                print(f"Input events lost; recovering: {dev.name} ({dev.path})", flush=True)
                            self.syncing.add(dev.path)
                            snapshot_at = None
                        elif dev.path in self.syncing:
                            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                                self.syncing.discard(dev.path)
                                snapshot_at = event
                        elif snapshot_at is not None:
                            # active_keys describes the state after all queued
                            # events, so don't replay these against that state.
                            snapshot_at = event
                        else:
                            events.append((dev.path, event))
                if snapshot_at is not None and dev.path in self.devices:
                    try:
                        held = dev.active_keys()
                    except OSError as exc:
                        held = None
                        print(f"Input state recovery failed: {dev.path} ({exc})", flush=True)
                    events.append((dev.path, KeySnapshot(held, snapshot_at.sec, snapshot_at.usec)))
            except BlockingIOError:
                pass
            except OSError:
                self.discard(dev.path)
        # A later read failure may have removed an earlier event's device.
        events = [(path, event) for path, event in events if path in self.devices]
        # Mirrored Solaar/physical streams must be merged chronologically,
        # rather than handling an entire press/release cycle twice.
        events.sort(key=lambda item: (item[1].sec, item[1].usec))
        return events

    def close(self):
        for dev in self.devices.values():
            close_device(dev)
        self.devices.clear()
        self.selector.close()
