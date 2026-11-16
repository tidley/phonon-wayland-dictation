"""Real Rust engine <-> IBus integration, with an isolated daemon and test clients.

Python is only the test client (Debian's installed GI bindings); the engine is
the compiled Rust binary. No audio, clipboard, synthetic keys, or desktop source
changes are involved.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import warnings

import gi

gi.require_version("IBus", "1.0")
from gi.repository import Gio, GLib, IBus

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from phonon_dictation import ibus as output

NAME = "org.freedesktop.IBus.Phonon"
CONTROL = "/org/phonon/Dictation"


def wait_until(predicate, description, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Timed out: {description}")


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def exercise(bus, helpers, installed=False):
    loop = GLib.MainLoop()
    errors = []
    received = [[], []]

    def call(method, args=None, signature="()"):
        return bus.get_connection().call_sync(
            NAME, CONTROL, "org.phonon.Dictation1", method, args,
            GLib.VariantType.new(signature), Gio.DBusCallFlags.NONE, 2000, None,
        ).unpack()

    def target():
        try:
            return call("GetTarget", signature="(ss)")
        except GLib.Error:
            return None

    def commit(token, text):
        call("Commit", GLib.Variant("(ss)", (token, text)))

    def rejected(token):
        try:
            commit(token, "must not be inserted")
        except GLib.Error as exc:
            assert "Focus changed" in str(exc) or "No enabled focused engine" in str(exc), str(exc)
        else:
            raise AssertionError("Stale focus token was accepted")

    def client():
        try:
            # Runtime-registered components appear in this legacy API, not the
            # static ListEngines registry. Limit the deprecation filter to it.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                wait_until(
                    lambda: any(d.get_name() == "phonon" for d in (bus.list_engines() if installed else bus.list_active_engines())),
                    "Rust engine registration",
                )
            if not installed:
                assert target() is None
            assert output.begin("auto") is None
            contexts = [bus.create_input_context(f"phonon-test-{i}") for i in range(2)]
            for index, context in enumerate(contexts):
                context.set_capabilities(int(IBus.Capabilite.FOCUS))
                context.connect("commit-text", lambda _, text, i=index: received[i].append(text.get_text()))

            contexts[0].focus_in()
            assert bus.set_global_engine("phonon")
            first = wait_until(target, "focused/enabled Rust engine")
            assert first[1] == contexts[0].get_object_path(), first
            assert bus.get_global_engine().get_layout() == "gb"

            text = "Direct Phonon input — café, Ελληνικά, 日本語.\nSecond line. "
            commit(first[0], text)
            wait_until(lambda: received[0] == [text], "exact Unicode/multiline text commit")
            assert not received[1]
            assert not contexts[0].process_key_event(IBus.KEY_a, 30, 0)
            assert not contexts[0].process_key_event(IBus.KEY_a, 30, int(IBus.ModifierType.RELEASE_MASK))

            # Native Python client, request reservations, and duplicate handling.
            reservation = output.begin("ibus")
            output.commit(reservation, "Socket delivery")
            output.commit(reservation, "Socket delivery")
            wait_until(lambda: received[0] == [text, "Socket delivery "], "deduplicated native IPC commit")
            conflict = output.request({"op": "commit", **reservation, "text": "different"})
            assert not conflict["ok"]

            def press(key, code=48, modifiers=0):
                handled = contexts[0].process_key_event(key, code, modifiers)
                released = contexts[0].process_key_event(key, code, int(IBus.ModifierType.RELEASE_MASK))
                assert handled and released

            press(IBus.KEY_dead_acute)
            press(IBus.KEY_e, 18)
            press(IBus.KEY_Multi_key)
            press(IBus.KEY_apostrophe)
            press(IBus.KEY_e, 18)
            press(IBus.KEY_U, 22, 5)  # Ctrl+Shift+U
            for key in "1f642":
                press(ord(key))
            press(IBus.KEY_Return)
            first_expected = [text, "Socket delivery ", "é", "é", "🙂"]
            wait_until(lambda: received[0] == first_expected, "dead key, Compose, and Unicode entry")
            stale_reservation = output.begin("ibus")

            contexts[1].focus_in()
            second = wait_until(
                lambda: (value if (value := target()) and value[1] == contexts[1].get_object_path() else None),
                "focus-ID change to second client",
            )
            assert second[0] != first[0]
            rejected(first[0])
            output.commit(reservation, "Socket delivery")  # No replay into the newly focused client.
            failed = output.request({"op": "commit", **stale_reservation, "text": "must not arrive"})
            assert not failed["ok"] and "Focus changed" in failed["error"]
            commit(second[0], "Second target")
            wait_until(lambda: received[1] == ["Second target"], "commit to new focused client")

            contexts[1].reset()
            after_reset = wait_until(
                lambda: (value if (value := target()) and value[0] != second[0] else None),
                "reset invalidation",
            )
            rejected(second[0])

            # A first milestone stress check: serialized commits stay ordered.
            for index in range(25):
                commit(after_reset[0], f"cycle-{index}")
            wait_until(lambda: len(received[1]) == 26, "25 ordered rapid commits")
            assert received[1][1:] == [f"cycle-{i}" for i in range(25)]
            assert received[0] == first_expected

            expired = output.begin("ibus")
            for _ in range(256):
                output.begin("ibus")
            failure = output.request({"op": "commit", **expired, "text": "expired request"})
            assert not failure["ok"] and "expired" in failure["error"]

            contexts[1].focus_out()
            wait_until(lambda: target() is None, "no real client focused")
            rejected(after_reset[0])
            contexts[1].focus_in()
            refocused = wait_until(target, "refocused client")
            assert refocused[0] != after_reset[0]
            rejected(after_reset[0])

            # Switching to an ordinary engine must invalidate outstanding work.
            assert bus.set_global_engine("xkb:us::eng")
            wait_until(lambda: target() is None, "engine disable invalidation")
            rejected(refocused[0])
            assert output.begin("auto") is None
            if helpers:
                helper = helpers[-1]
                assert helper.poll() is None
                stop(helper)
                wait_until(lambda: not bus.name_has_owner(NAME), "old helper bus-name release")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    wait_until(lambda: all(d.get_name() != "phonon" for d in bus.list_active_engines()), "old component removal")
                replacement = subprocess.Popen(helper.args)
                helpers.append(replacement)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    wait_until(lambda: any(d.get_name() == "phonon" for d in bus.list_active_engines()), "helper re-registration")
                assert bus.set_global_engine("xkb:us::eng")
                contexts[0].focus_out()
                contexts[0].focus_in()
                assert bus.set_global_engine("phonon")
                wait_until(lambda: (value if (value := target()) and value[1] == contexts[0].get_object_path() else None), "replacement helper focus")
                failed = output.request({"op": "commit", **stale_reservation, "text": "old helper request"})
                assert not failed["ok"]
                output.commit(output.begin("ibus"), "After restart")
                wait_until(lambda: received[0] == first_expected + ["After restart "], "replacement helper delivery")
            print("PASS: native IPC, deduplication, Compose/dead keys/Unicode entry,")
            print("      focus/reset/disable rejection, 25 ordered commits" + (", installed activation" if installed else ", helper restart"))
        except BaseException as exc:
            errors.append(AssertionError(f"{exc}; current target: {target()!r}; test-client results: {received!r}"))
        finally:
            GLib.idle_add(loop.quit)

    worker = threading.Thread(target=client, daemon=True)
    worker.start()
    watchdog = GLib.timeout_add_seconds(35, loop.quit)
    loop.run()
    GLib.source_remove(watchdog)
    worker.join(timeout=3)
    if worker.is_alive():
        raise AssertionError("Integration client did not finish")
    if errors:
        raise errors[0]


def private_session(binary, installed=False):
    with tempfile.TemporaryDirectory(prefix="phonon-ibus-test-") as root:
        address = f"unix:path={root}/bus"
        os.environ.update({
            "IBUS_ADDRESS": address,
            "XDG_CACHE_HOME": f"{root}/cache",
            "XDG_CONFIG_HOME": f"{root}/config",
            "GIO_USE_VFS": "local",
            "XDG_RUNTIME_DIR": f"{root}/runtime",
            "PHONON_IBUS_SOCKET": f"{root}/runtime/phonon/ibus.sock",
        })
        Path(root, "runtime").mkdir(mode=0o700)
        if installed:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
            from install_ibus import install
            _, descriptor = install(Path(root, "prefix"), Path(root, "config"), binary)
            os.environ["IBUS_COMPONENT_PATH"] = f"/usr/share/ibus/component:{descriptor.parent}"
            subprocess.run(["ibus", "write-cache"], check=True)
        os.environ.pop("DISPLAY", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
        daemon = subprocess.Popen([
            "ibus-daemon", "--single", "--emoji-extension=disable", "--cache=auto" if installed else "--cache=none",
            f"--address={address}",
        ])
        helpers = []
        try:
            wait_until(lambda: Path(root, "bus").exists(), "private daemon socket")
            IBus.init()
            bus = IBus.Bus.new()
            assert bus.is_connected()
            if not installed:
                helpers.append(subprocess.Popen([str(binary), "--address", address, "--socket", os.environ["PHONON_IBUS_SOCKET"]]))
            exercise(bus, helpers, installed)
        finally:
            for helper in helpers:
                stop(helper)
            stop(daemon)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=Path(__file__).resolve().parents[1] / "target/debug/phonon-ibus-helper")
    parser.add_argument("--private-session", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--installed", action="store_true", help="Test component discovery and automatic activation from a staged installation")
    args = parser.parse_args()
    if not args.helper.is_file():
        parser.error("Build the Rust helper first: cargo build --locked --manifest-path rust/ibus-helper/Cargo.toml")
    if args.private_session:
        private_session(args.helper.resolve(), args.installed)
    else:
        # A fresh session bus prevents accidental use of the desktop's services.
        command = [
            "dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
            "--private-session", "--helper", str(args.helper.resolve()),
        ]
        if args.installed:
            command.append("--installed")
        raise SystemExit(subprocess.run(command).returncode)
