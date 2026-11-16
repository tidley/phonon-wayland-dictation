"""Small stdlib-only client for the Rust helper's user-runtime socket."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket


class IBusError(OSError):
    pass


def socket_path():
    override = os.getenv("PHONON_IBUS_SOCKET")
    if override:
        return override
    runtime = os.getenv("XDG_RUNTIME_DIR")
    if not runtime:
        raise IBusError("XDG_RUNTIME_DIR is unavailable")
    return str(Path(runtime) / "phonon/ibus.sock")


def request(message, timeout=0.25):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(socket_path())
        client.sendall(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        with client.makefile("rb") as response:
            line = response.readline(1024 * 1024 + 1)
        if not line.endswith(b"\n") or len(line) > 1024 * 1024:
            raise IBusError("Incomplete IBus response; delivery may be uncertain")
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise IBusError("Invalid IBus response") from exc
        if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
            raise IBusError("Invalid IBus response")
        return value


def begin(output):
    """Reserve the focused field at capture start; None selects clipboard."""
    if output == "clipboard":
        return None
    try:
        value = request({"op": "begin"})
    except (FileNotFoundError, ConnectionRefusedError):
        if output == "auto":
            return None
        raise IBusError("Select Phonon Dictation in the GNOME input-source menu")
    if not value["ok"]:
        if output == "auto" and value.get("selected") is False:
            return None
        raise IBusError(value.get("error", "No focused Phonon input field"))
    if not all(isinstance(value.get(key), str) and value[key] for key in ("token", "request_id", "context")):
        raise IBusError("IBus helper returned an invalid target")
    return {key: value[key] for key in ("token", "request_id")}


def commit(target, text):
    # No new request ID, transport retry, or paste fallback after an ambiguous
    # response. The helper deduplicates explicit repeats of the same reservation.
    value = request({"op": "commit", **target, "text": text + " "}, timeout=2)
    if not value["ok"]:
        raise IBusError(value.get("error", "IBus commit failed"))
