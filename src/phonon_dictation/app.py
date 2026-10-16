"""Hold Right Ctrl to record, release to transcribe and paste."""
from __future__ import annotations

import argparse
import atexit
import urllib.request
import urllib.error
import json
import os
import select
import signal
import sys
import subprocess
import tempfile
import time
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices


KEY_TALK = ecodes.KEY_RIGHTCTRL
KEY_SHIFT = ecodes.KEY_RIGHTSHIFT
KEYCODES = {
    "normal": ["29:1", "47:1", "47:0", "29:0"],
    "terminal": ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=KEYCODES, default=os.getenv("PHONON_PASTE_MODE", "normal"),
                   help="Fallback paste mode when Right Shift was not held (default: normal)")
    p.add_argument("--source", default=os.getenv("PHONON_MIC", "default"), help="PulseAudio/PipeWire source name")
    p.add_argument("--api-url", default=os.getenv("PHONON_API_URL", "http://127.0.0.1:8000/v1/audio/transcriptions"))
    p.add_argument("--delay", type=float, default=0.25, help="Delay between key release and paste")
    p.add_argument("--server-command", default=os.getenv("PHONON_SERVER_COMMAND", "fermion serve phonon-2"), help="Command to start local speech server")
    p.add_argument("--no-start-server", action="store_true", help="Require an already-running speech server")
    return p


def paste(text: str, mode: str, delay: float):
    # wl-copy supplies clipboard data; ydotool sends a paste shortcut.
    # Text is not passed as a command argument to a shell.
    subprocess.run(["wl-copy", "--type", "text/plain"], input=text + " ", text=True, check=True, timeout=5)
    time.sleep(max(0, delay))
    subprocess.run(["ydotool", "key", *KEYCODES[mode]], check=True, timeout=5)


def transcribe(path: Path, api_url: str):
    response = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--max-time", "120", api_url,
         "-F", f"file=@{path}", "-F", "model=phonon-2"],
        text=True, capture_output=True, check=True,
    )
    return json.loads(response.stdout)["text"].strip()


def open_keyboards():
    devices = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            # Ignore synthetic keyboard to avoid feeding back injected shortcuts.
            name = dev.name.lower()
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            if KEY_TALK in caps and not any(x in name for x in ("ydotool", "virtual", "uinput")):
                devices.append(dev)
                print(f"Monitoring: {dev.name} ({path})", flush=True)
            else:
                dev.close()
        except (OSError, PermissionError):
            continue
    return devices


def server_ready(url: str) -> bool:
    """Probe local API without sending any user audio."""
    from urllib.parse import urlsplit
    u = urlsplit(url)
    if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Only a local HTTP transcription endpoint is supported")
    health_url = f"{u.scheme}://{u.netloc}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def ensure_server(args):
    """Start Phonon if not running; return the process only if owned by us."""
    if server_ready(args.api_url):
        print("Phonon server already running", flush=True)
        return None
    if args.no_start_server:
        raise SystemExit("Phonon server unavailable (--no-start-server set)")
    import shlex
    command = shlex.split(args.server_command)
    if not command:
        raise SystemExit("Empty Phonon server command")
    if command[0] == "fermion":
        local_fermion = Path(sys.executable).parent / "fermion"
        if local_fermion.is_file():
            command[0] = str(local_fermion)
    print("Starting local Phonon-2 server...", flush=True)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    for _ in range(120):  # up to 60 seconds for cold start
        if process.poll() is not None:
            raise SystemExit(f"Phonon server exited with code {process.returncode}")
        if server_ready(args.api_url):
            print("Phonon server ready", flush=True)
            return process
        time.sleep(0.5)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    raise SystemExit("Phonon server failed to become ready within 60 seconds")


def main():
    args = parser().parse_args()
    if args.delay < 0:
        raise SystemExit("--delay must be >= 0")
    devices = open_keyboards()
    if not devices:
        raise SystemExit("No accessible keyboard. Check 'input' group membership and session permissions.")

    server_proc = None
    recording = None
    recording_path = None
    shift_held = False
    terminal_requested = False
    server_proc = ensure_server(args)
    print("Ready. Right Ctrl = normal paste; Right Ctrl + Right Shift = terminal paste.", flush=True)

    try:
        while True:
            readable, _, _ = select.select(devices, [], [])
            for dev in readable:
                for event in dev.read():
                    if event.type != ecodes.EV_KEY:
                        continue
                    if event.code == KEY_SHIFT and event.value in (0, 1):
                        shift_held = event.value == 1
                        if shift_held and recording is not None:
                            terminal_requested = True
                    elif event.code == KEY_TALK and event.value == 1 and recording is None:
                        terminal_requested = shift_held
                        with tempfile.NamedTemporaryFile(suffix=".wav", prefix="phonon-dictation-", delete=False) as f:
                            recording_path = Path(f.name)
                        recording = subprocess.Popen(
                            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "pulse", "-i", args.source,
                             "-ac", "1", "-ar", "16000", str(recording_path)],
                            stdin=subprocess.DEVNULL,
                        )
                        print("Recording...", flush=True)
                    elif event.code == KEY_TALK and event.value == 0 and recording is not None:
                        recording.send_signal(signal.SIGINT)
                        try:
                            recording.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            recording.kill()
                            recording.wait()
                        recording = None
                        selected_mode = "terminal" if terminal_requested else args.mode
                        print(f"Paste mode: {selected_mode}", flush=True)
                        try:
                            if recording_path.stat().st_size < 1000:
                                print("Recording too short; skipped", flush=True)
                                continue
                            text = transcribe(recording_path, args.api_url)
                            if text:
                                print(f"Transcribed: {text}", flush=True)
                                paste(text, selected_mode, args.delay)
                        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                            print(f"Dictation error: {exc}", flush=True)
                        finally:
                            recording_path.unlink(missing_ok=True)
                            recording_path = None
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        if recording is not None:
            recording.send_signal(signal.SIGINT)
            try:
                recording.wait(timeout=5)
            except subprocess.TimeoutExpired:
                recording.kill()
                recording.wait()
        if recording_path is not None:
            recording_path.unlink(missing_ok=True)
        for dev in devices:
            dev.close()
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    main()
