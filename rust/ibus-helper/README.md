# Rust IBus input source

Native offline dictation for Debian GNOME/Wayland, tracked in
[issue #2](https://github.com/tidley/phonon-wayland-dictation/issues/2).
The engine, Compose handling, focus tracking, and IPC server are Rust. The
existing Python application still handles evdev, audio, and transcription.

## Install and select

First install the speech application with the repository's normal installer.
Build requirements for this optional engine are a current Rust/Cargo toolchain
and `libxkbcommon-dev`. Runtime requirements are `ibus`, `libxkbcommon0`, and
the existing dictation service. The installer uses system Python/GI for GNOME
configuration (`python3-gi`, `gir1.2-ibus-1.0` for integration tests).

From the repository root, when not recording:

```bash
/usr/bin/python3 install_ibus.py --configure-service --add-source --refresh
```

This builds the locked release binary, installs it under `~/.local/libexec`,
writes `~/.local/share/ibus/component/phonon.xml`, and adds dedicated per-user
systemd drop-ins. No sudo is needed. Existing base service files and input
sources are retained. The one-time refresh restarts GNOME IBus and dictation.
Use `--no-build` when reinstalling an already built release.

The IBus drop-in adds the user component directory alongside
`/usr/share/ibus/component`: Debian's IBus does not search the user directory
by default. The installer also rebuilds the user registry cache. The dictation
drop-in sets `PHONON_OUTPUT=auto`.

Select **Phonon Dictation (English, UK)** using **Super+Space** or GNOME's input
source menu. It uses the GB keyboard layout. Focus a scratch text field, hold
Right Ctrl, speak, and release. Text is committed through IBus and the clipboard
is unchanged. Right Shift is not needed for native insertion into terminals.

Switch back to your normal input source to use the existing clipboard dictation
path. Automatic routing chooses a destination at recording start; native failures
never trigger a paste retry. `--output ibus` requires a focused Phonon field;
`--output clipboard` always uses the original path. CLI options override the
`PHONON_OUTPUT` environment setting.

To install without restarting anything, omit `--refresh`, then log out and back
in. To remove the native input source and its owned configuration:

```bash
/usr/bin/python3 install_ibus.py --uninstall --refresh
```

Uninstallation removes Phonon from the source list while retaining other
sources, removes the helper/descriptor and generated drop-ins, rebuilds the
registry cache, and returns the service to its previous output configuration.
The speech application, model, and base dictation service are retained.

## Runtime and request handling

IBus launches `phonon-ibus-helper --ibus` on selection. The helper discovers the
session's IBus address with `ibus address`, exports its factory, and serves
`$XDG_RUNTIME_DIR/phonon/ibus.sock`. The directory is mode 0700 and socket 0600.
It exits on daemon disconnect or SIGINT/SIGTERM; a later source selection can
activate a fresh helper. If an engine has crashed, switch away and reselect it.

The application uses newline-delimited JSON, one request/response per connection:

- `{"op":"begin"}` reserves the current focused input field and returns an
  instance-scoped token, context ID, and request ID. The application does this at
  recording start. When another source is selected, auto routing uses clipboard.
- `{"op":"commit","request_id":"…","token":"…","text":"…"}` validates
  that reservation and emits IBus `CommitText`. The application supplies its
  normal trailing space. Request text is not logged.

Focus changes, reset, disable, and a helper restart invalidate uncommitted work.
The daemon's `fake` client is not a target. Identical repeated commits return
`already_emitted` without reinserting text; different payloads for an already
used ID fail. The bounded reservation history retains 256 requests; evicted IDs
are rejected rather than treated as new commits. Ambiguous send outcomes are
not emitted again, and there is no implicit clipboard fallback or transport retry.

A successful commit response means the signal was enqueued, not that an
application acknowledged insertion. Ordering is enforced against focus events
handled by the helper; this cannot remove every race with events still in
transit from another connection. Actual within-window focus behavior and toolkit
compatibility require the manual checks below.

The helper preserves ordinary typing and shortcuts. libxkbcommon supplies
Compose/dead-key handling; Ctrl+Shift+U hexadecimal Unicode entry is supported.
Compose cancellation currently clears the sequence. This is not a complete
reimplementation of every `IBus.EngineSimple` extension.

## Developer checks

```bash
cargo build --locked --manifest-path rust/ibus-helper/Cargo.toml
/usr/bin/python3 rust/ibus-helper/tests/integration.py
/usr/bin/python3 rust/ibus-helper/tests/integration.py --installed
cargo clippy --locked --manifest-path rust/ibus-helper/Cargo.toml -- -D warnings
cargo fmt --manifest-path rust/ibus-helper/Cargo.toml -- --check
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Both harness modes use a private D-Bus session, temporary config/cache/runtime
directories, and a separate IBus daemon. The default mode explicitly registers
the engine and tests helper restart; `--installed` stages the actual installer
descriptor, builds a registry cache, and tests discovery and automatic activation.
They do not select an engine on the real desktop or invoke clipboard/synthetic
input commands. Python is only the independent IBus/GI test client.

Assertions cover native IPC, exact Unicode/multiline commits and trailing space,
duplicate/conflicting requests, ordinary press/release passthrough, Compose,
dead keys, Unicode entry, focus IDs across two clients, stale-token rejection,
reset, focus-out/refocus, source switching, 25 ordered commits, and helper restart.

IBus 1.5.32 has two interoperability details captured in the implementation:

- Its libibus introspection advertises `FocusId`/`ActiveSurroundingText` as `(b)`,
  but the daemon actually reads plain `b` properties.
- It negotiates those properties asynchronously and can miss the initial
  `FocusInId` if replies are reversed. The helper serializes property replies,
  matching libibus/GDBus, and never offers an unidentified field as a target.

## Manual desktop checks

Initial desktop validation on the target GNOME laptop confirmed normal keyboard
typing and Right Ctrl dictation with Phonon selected, with `Output: IBus` in the
service log. The following broader compatibility checks remain useful:

1. Select Phonon and test ordinary GB typing, shortcuts, Compose/dead keys, and
   Ctrl+Shift+U. Confirm source switching restores your other layout.
2. Dictate into GNOME Text Editor, Terminator/VTE, Firefox, and the Electron/
   Wayland apps in use. For SSH, insertion happens in the local terminal; no
   remote IBus installation is required. No Enter/submission is generated.
3. Compare clipboard contents before/after native dictation. Test 30–60-second
   holds and rapid cycles while transcription is still running.
4. Change application, text field, or source during recording/transcription;
   confirm stale results are discarded and no duplicate/paste fallback occurs.
5. Test lock/unlock, suspend/resume, helper termination/reselection, and IBus
   restart. Existing keyboard hotplug/recovery behavior should be preserved.

Logs: `journalctl --user -u phonon-dictation.service -f`. Native recordings log
`Output: IBus`; focus/delivery failures log a dictation error. If the input source
is absent, confirm `ibus list-engine` contains `phonon`, inspect the IBus user
service drop-in, then refresh when idle or log out/in. Enable GNOME's “show all
input sources” setting if its Add Input Source dialog filters the engine.
