# Phonon Wayland Dictation

Offline, whole-recording push-to-talk dictation for macOS and Linux GNOME on Wayland, including Debian and NixOS. Hold a key while speaking; on release, the complete recording is transcribed by a local [Fermion Research Phonon-2](https://pypi.org/project/fermion-research/) server and pasted into the focused application (or inserted through optional IBus on Linux).

The model is downloaded once from its upstream source. After that download, audio is processed locally: recordings are sent only to `127.0.0.1`, not to a hosted transcription service.

See [CHANGELOG.md](CHANGELOG.md) for changes and verification notes.

## Features

- Full-recording transcription on key release, not incremental transcription.
- A local Phonon-2 HTTP server starts automatically when one is not already healthy.
- Reuses an independently started compatible local server and never terminates it.
- PipeWire/PulseAudio capture through FFmpeg, clipboard insertion through `wl-copy`, and input through `ydotool`.
- Optional systemd user service for graphical-login startup.
- Temporary WAV recordings are deleted after each attempt, including transcription failures.
- Keyboard hotplug, dock reconnection, and suspend/resume recovery without reloading Phonon-2.

## Support

This release has been exercised on Debian 13 GNOME Wayland and NixOS 26.05 GNOME Wayland with Python 3.13 and CPU inference. It needs enough memory for the local runtime; observed use on an AMD Ryzen 7 PRO 7840U is roughly 870-960 MB. Other distributions and Wayland desktops may work but are not validated here.

Phonon-2 and the `fermion-research` runtime are separate upstream software. Their model weights are downloaded into the Fermion/Hugging Face cache, are not included in this repository, and remain subject to their upstream terms.

## Installation

For macOS, use the [macOS instructions](#macos-installation) below.

For NixOS, use the [NixOS instructions](#nixos-installation) below. `install.sh`
is the Debian installer and manages the project-local `.venv`.

Clone the repository, then either install the Debian prerequisites yourself:

```bash
sudo apt install python3-venv ffmpeg curl wl-clipboard ydotool
./install.sh
```

or let the installer perform only that explicit privileged step:

```bash
./install.sh --install-system-deps
```

The installer validates Debian and Python, creates `.venv`, installs the exact upstream distribution `fermion-research`, selects the PyTorch CPU wheel, installs this package, and downloads or verifies Phonon-2. It is safe to run again. Use `./install.sh --skip-model-download` to defer the approximately 164 MB model download until the first server start.

If a prior `.venv` was created with an incompatible Python, remove only that project-local directory and rerun the installer:

```bash
rm -rf .venv
./install.sh
```

## macOS Installation

The macOS backend uses Quartz for global modifier-key state and paste, FFmpeg
AVFoundation for microphone capture, and `pbcopy` for the clipboard. Linux input
libraries are not installed on Mac. Hardware dictation on macOS has not yet been
validated; upstream Fermion/PyTorch wheel availability also depends on your
Python version and Mac architecture (especially Intel Macs).

Install [Homebrew](https://brew.sh), then:

```bash
brew install python@3.13 ffmpeg
bash install_macos.sh
.venv/bin/phonon-dictate
```

On a MacBook's built-in keyboard, run with **Right Option** instead:

```bash
.venv/bin/phonon-dictate --talk-key right-option
```

Alternatively, `./install.sh --install-system-deps` installs those Homebrew
prerequisites explicitly and then uses the Mac installer. Use
`--skip-model-download` to defer downloading the model. `PYTHON=/path/to/python`
selects a different Python 3.10+ interpreter. Do not reuse a Linux virtualenv.
The installer does not configure automatic startup; Linux systemd and IBus
installation instructions do not apply to macOS.

In **System Settings > Privacy & Security**, allow your terminal/Python:

- **Input Monitoring** for the global hotkey.
- **Accessibility** for simulated Command+V.
- **Microphone** when macOS prompts during the first recording.

Restart the terminal after granting access. Run as your regular user, not root.
Hold **Right Control** to record and release to transcribe and paste, or
**Right Option** when using `--talk-key right-option`. You can also set
`PHONON_TALK_KEY=right-option` in your environment.
Both normal and terminal modes use **Command+V**. The hotkey is not suppressed
from the focused application. The default requires a Right Control key;
many built-in Mac keyboards do not have one, so use the Right Option option
on those keyboards. Option-based shortcuts remain visible to applications.

To list microphones:

```bash
ffmpeg -f avfoundation -list_devices true -i ""
.venv/bin/phonon-dictate --source 0
```

The listing command normally exits nonzero after printing devices. `--source`
accepts an audio-device index or name; `default` selects audio device 0.
If capture fails, check Microphone permission and choose the appropriate device.
Clipboard text is replaced when pasting; secure input fields or applications
that reject synthetic events may not work.

Mac minis have no built-in microphone: connect a USB/Bluetooth microphone,
headset, or a display/webcam with a microphone. MacBooks normally have a built-in
microphone. Check **System Settings > Sound > Input**, then use the matching
AVFoundation audio-device index above.

The server may report that MLX is unavailable and fall back to CPU inference.
This is not a startup failure; CPU inference may be slower. Model download and
the first runtime compilation can take longer than subsequent starts. Successful
HTTP `200` health checks and the `Ready` message mean startup completed, not that
microphone capture or paste have been verified.

macOS reads session-wide state for only the selected trigger and Right Shift, rather
than Linux's per-keyboard events. Physical-keyboard ownership/disconnection
detection is therefore not available: release the trigger before unplugging a
keyboard. Interrupted recordings are discarded after sleep/wake. Verify capture,
Unicode paste in an editor and terminal, permission denial/recovery, and sleep
while recording on your Mac before relying on it.

### Testing on another Mac

Clone this repository (or `git pull --ff-only` in an existing checkout), then
run the Mac installer above to create that machine's own `.venv`. After updates,
rerun the installer or `.venv/bin/python -m pip install .`; pulling source alone
does not update a non-editable installed copy. Run from the project directory,
not your home directory.

1. Grant the three permissions above to the terminal app actually being used;
   fully quit/reopen it after permission changes.
2. List microphones and select a valid audio device. On a MacBook, start with
   `.venv/bin/phonon-dictate --talk-key right-option --source 0`, adjusting the
   microphone index as needed.
3. Focus a scratch text editor, hold the trigger, speak, and release. Confirm
   `Recording...`, `Transcription complete`, and one pasted sentence.
4. Repeat in a terminal with harmless text (do not press Return), including
   Unicode and repeated short recordings.
5. Check sleep/wake during recording discards interrupted capture, and a fresh
   recording works afterward. Quit with Ctrl+C and confirm a restart works.

Current manual verification: local server startup and its CPU fallback were
observed on a Mac mini. End-to-end microphone recording, physical hotkey use,
paste, and sleep/wake have **not** yet been verified on macOS.

For automated checks (no microphone or desktop permission required):

```bash
.venv/bin/python -m pip install -e '.[test]'
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Linux-specific evdev tests are skipped on macOS.

## Keyboard Access And Security (Linux)

`python-evdev` reads `/dev/input/event*`. A normal Debian solution is:

```bash
sudo usermod -aG input "$USER"
```

Then fully log out and log in before running the application or its user service. A long-lived systemd user manager does not inherit a newly added supplementary group. Do not add `SupplementaryGroups=input` to the user service: user services cannot perform that group transition and systemd reports `status=216/GROUP`.

Membership in `input` permits programs in your account to read raw input events, including passwords and other sensitive keyboard input. It is broad access, not an application-specific permission. The application requires read access, never changes device permissions, and excludes devices whose names contain `ydotool` (including the default `ydotoold virtual device`) to avoid feedback. Keep that identifying name if configuring ydotoold. Other virtual keyboards, including `solaar-keyboard`, are supported when their evdev capabilities include Right Ctrl. Right Shift is optional and enables terminal mode when present.

For a more restricted deployment, use a locally reviewed udev/logind policy that grants the active local seat user access only to physical devices marked `ID_INPUT_KEYBOARD=1`. That policy must cover newly enumerated event devices and should be tested after reconnecting keyboards. It requires administrator review because any process running as the logged-in user can still read those keyboard events. A temporary `setfacl` grant can diagnose a session that has not been logged out, but is intentionally not installed or persisted by this project.

`ydotoold` must be available. On Debian installations that package a user unit, enable it with:

```bash
systemctl --user enable --now ydotool.service
```

## Usage

```bash
.venv/bin/phonon-dictate
```

| Shortcut | Result |
| --- | --- |
| Hold Right Ctrl | Record microphone audio. |
| Release Right Ctrl | Transcribe the complete recording and paste with Ctrl+V. |
| Hold Right Ctrl, press Right Shift at any point | Select terminal paste mode. |
| Release Right Ctrl after selecting terminal mode | Transcribe the complete recording and paste with Ctrl+Shift+V. |

The trigger keys remain visible to the focused application. Pressing Right Shift after recording starts is supported. Repeated key events do not start a second recorder.

### Keyboard Lifecycle And Recovery

Input devices are discovered at startup and registered dynamically using `pyudev` and a selector. A five-second reconciliation scan also catches missed notifications, recreated event nodes, and devices that become readable after a permission/ACL change. No fixed event numbers are configured. When no usable keyboards are connected, the application waits and resumes monitoring when one appears; the speech server stays loaded.

Shift state is tracked per keyboard. Shift held before Ctrl, or pressed during a recording, selects terminal paste even if Shift is released first. Mirrored physical/Solaar events are merged by timestamp and repeated Ctrl presses are coalesced. Only the keyboard that initiated recording can stop it with a Ctrl release; unrelated or mirrored releases do not submit it again. Release held trigger keys before starting another recording or after reconnecting a keyboard. The terminal paste modifier applies to clipboard output; native IBus insertion does not need it.

Removing a monitored keyboard during recording conservatively cancels that recording, clears that device's modifier state, stops FFmpeg, and deletes the WAV without transcription or paste. Lost evdev events (`SYN_DROPPED`) and stale-device read errors also trigger safe recovery. On resume, the application detects elapsed suspend time using Linux's suspend-inclusive clock, cancels interrupted capture, clears modifiers, and reopens input handles even when event paths have not changed. No logind D-Bus dependency or systemd restart hook is needed. Resume checks occur at least once per second while the input loop is idle. A recording interrupted by resume is discarded, including when resume is detected before/during transcription.

Transcription and paste remain synchronous: input notifications are serviced after those operations finish (the transcription request has a 120-second timeout). Resume is checked before submitting audio and again before pasting its result. Keyboard rediscovery itself never starts or stops the model server.

Useful options:

```bash
.venv/bin/phonon-dictate --help
.venv/bin/phonon-dictate --source default --delay 0.25
.venv/bin/phonon-dictate --no-start-server
PHONON_PASTE_MODE=terminal .venv/bin/phonon-dictate
```

`--api-url` accepts only an HTTP loopback endpoint (`localhost`, `127.0.0.1`, or `::1`). `--server-command` defaults to `fermion serve phonon-2`; that command binds locally by default. Set `FERMION_CACHE_DIR` or `HF_HOME` before installation if model files should live on another volume.

## Native IBus Input (Optional)

Phonon can also be selected as a GNOME input source, inserting text directly
without clipboard changes or simulated paste. The engine is Rust and uses the
GB keyboard layout. On Debian and conventional distributions, install the
existing dictation service first, then install the optional engine from this
checkout (current Rust/Cargo and the libxkbcommon development package, named
`libxkbcommon-dev` on Debian, are needed for its build):

```bash
/usr/bin/python3 install_ibus.py --configure-service --add-source --refresh
```

Run this while not recording: the refresh briefly restarts GNOME IBus and the
dictation service. Select **Phonon Dictation (English, UK)** using **Super+Space**
or the top-bar input-source menu, focus a text field, and dictate as usual.
Your other sources are retained. Selecting your regular source restores the
clipboard destination; native recordings log `Output: IBus` and need no terminal
paste-mode modifier.

See the [IBus guide](rust/ibus-helper/README.md) for installation details,
focus behavior, developer tests, compatibility checks, and uninstallation.
Native application compatibility is still being validated under [issue #2](https://github.com/tidley/phonon-wayland-dictation/issues/2).

On GNOME, native/auto output also watches session unlocks. GNOME can cancel
overlapping engine switches during password-field teardown and leave its US
keyboard fallback active even while the indicator still shows Phonon. After
unlock, dictation briefly waits for that transition to settle and restores
Phonon if it remains your most-recently selected source and the fallback is
still active. Recovery runs in the background, rechecks that the screen is
unlocked and your source choice is unchanged, and retries at most three times.
Per-window input-source mode is excluded because its selection cannot be
inferred from the global preference. This uses `gdbus`, `gsettings`, and `ibus`
from the GNOME runtime; successful recovery logs
`Restored Phonon input after unlock`.

## NixOS Installation

The integration has been built and tested on NixOS 26.05, GNOME 50.6,
IBus 1.5.33 and Python 3.13. Use a separate Python environment and Cargo target
when sharing this checkout with Debian. Do not run `install.sh` on NixOS.

### Runtime environment

`nix/shell.nix` supplies Nix-managed Python `evdev`, `pyudev` and PyGObject,
FFmpeg, curl, PipeWire, PortAudio, libudev (systemd), the C/C++ runtime,
wl-clipboard, ydotool, IBus, libxkbcommon, and the Rust/Cargo toolchain.
It also includes pytest and the IBus/GI developer-test dependencies.
This bypasses unconfigured system rustup shims. Its Cargo target is
`build/nixos/ibus-helper`; Debian's `rust/ibus-helper/target` is retained.
An explicit `CARGO_TARGET_DIR` is honoured by `install_ibus.py`, including with
`--no-build`. Declarative Nix builds use their own sandbox target directories.

For an existing working Nix environment, keep it and add any missing dependencies
from this shell. For a new installation, enter `nix-shell nix/shell.nix`, then:

```bash
uv venv --python "$(command -v python)" --system-site-packages ~/.local/share/venvs/phonon-nix
source ~/.local/share/venvs/phonon-nix/bin/activate
uv pip install --torch-backend cpu fermion-research
uv pip install --no-deps -e .
python -c 'import evdev, pyudev; print(evdev.__file__, pyudev.__file__)'
phonon-dictate --output clipboard
```

The import check should show Nix-managed input libraries. Run the application
inside the Nix shell, including from systemd. The model downloads on first use;
subsequent inference uses the local cache. Existing environments and model caches
need no reinstallation or redownload.

### Declarative engine and login service (recommended)

Import `nix/module.nix` from your NixOS configuration. For example, add the
following to `/etc/nixos/modules/dictation.nix`, using your actual checkout path:

```nix
imports = [ /home/alice/code/phonon-wayland-dictation/nix/module.nix ];
services.phonon-dictation = {
  enable = true;
  user = "alice";
  shellFile = "/home/alice/code/phonon-wayland-dictation/nix/shell.nix";
  venv = "/home/alice/.local/share/venvs/phonon-nix";
};
```

Alternatively, `shellFile` can name your existing
`~/.config/phonon-nix/shell.nix` (use an absolute path).
The module adds Phonon to `i18n.inputMethod.ibus.engines` using NixOS's list
merging, retaining engines configured elsewhere. It builds the locked Rust
helper with libxkbcommon, generates the same XML descriptor as the conventional
installer, and keeps the entire runtime closure reachable from the system
generation. It enables the standard ydotool system service and uses the
`input`/`ydotool` groups, without changing device/socket permissions. Its Phonon
user service is restricted to the configured user and starts at graphical login
with **`--output auto`** and `YDOTOOL_SOCKET=/run/ydotoold/socket`.

```bash
sudo nixos-rebuild switch
```

If a hand-written `~/.config/systemd/user/phonon-dictation.service` already
exists, it takes precedence over the declarative unit. Either keep it with
`--output auto`, or back it up outside the systemd unit search path after
rebuilding to use the declarative unit. `PHONON_OUTPUT=auto` cannot override an
explicit `--output clipboard` argument. Inspect `systemctl --user cat
phonon-dictation.service` to confirm the effective command.

Log out and in (also required for newly added groups), then register the source:

```bash
nix-shell nix/shell.nix --run 'python install_ibus.py --register-only --add-source'
systemctl --user status phonon-dictation.service
```

If staying in the current session, use `--register-only --add-source --refresh`
when idle to restart IBus and discover the new package. Adding the GNOME source
is idempotent and appends Phonon without replacing existing keyboard sources.
Select **Phonon Dictation (English, UK)** with Super+Space or the top-bar menu.
Both the engine and service survive logout, reboot and NixOS rebuilds while the
module remains enabled; the checkout/runtime shell and virtualenv must be on a
partition mounted before graphical login.

**Why not the conventional installer?** NixOS's `ibus-with-plugins` wrapper
unconditionally exports its own `IBUS_COMPONENT_PATH`. An environment-only
systemd drop-in is ignored. Do not replace the path with
`/usr/share/ibus/component`, pin discovered store paths into a global environment,
or replace the existing engine list. `--register-only` leaves IBus paths and
the helper installation under NixOS's control. On conventional distributions,
the installer discovers the running daemon's and unit's component paths,
XDG data directories and the installed IBus prefix instead of assuming `/usr`.

### Migrating a manually configured IBus service

If you previously activated a custom IBus package through a user-service
`ExecStart` override, that override takes precedence over NixOS's generated
unit. After successfully activating the system module, remove only the
Phonon-specific bootstrap override (for example, `60-phonon-nixos.conf`), run
`systemctl --user daemon-reload`, and log out/in. Verify the effective command
with `systemctl --user cat org.freedesktop.IBus.session.GNOME.service` before
removing its old package GC root. Preserve unrelated user-service configuration.

A manually built package is a snapshot of its configured engines. Keeping a
GC root retains that snapshot across rebuilds, but does not update it when the
system's IBus version or engine list changes. Use the declarative module for
automatic rebuild integration.

### Verification

```bash
ibus list-engine                         # must contain phonon
gsettings get org.gnome.desktop.input-sources sources
systemctl status ydotoold.service        # system service on NixOS
systemctl --user cat phonon-dictation.service
journalctl --user -u phonon-dictation.service -f
curl --fail http://127.0.0.1:8000/health
```

With Phonon selected, hold/release Right Ctrl in a scratch editor and terminal;
expect `Output: IBus` and insertion without a clipboard change. Right Shift
remains supported; native insertion needs no paste shortcut. With the ordinary
keyboard source selected, test Right Ctrl clipboard paste and Right Ctrl + Right
Shift terminal paste. Auto routing reserves its destination at recording start;
changing focus/source during native transcription discards stale text rather
than pasting it elsewhere. Repeat after logout/reboot and a NixOS rebuild.

Developer checks (no changes to the real desktop input source):

```bash
nix-shell nix/shell.nix
cargo build --release --locked --manifest-path rust/ibus-helper/Cargo.toml
python rust/ibus-helper/tests/integration.py --helper "$CARGO_TARGET_DIR/release/phonon-ibus-helper"
python rust/ibus-helper/tests/integration.py --installed --helper "$CARGO_TARGET_DIR/release/phonon-ibus-helper"
PYTHONPATH=src python -m pytest -q
```

The integration harness also accepts `--packaged` to test the actual descriptor
and automatic activation in an IBus package on `PATH`, in a private D-Bus session.
See [nix/README.md](nix/README.md) for standalone package builds and a repeatable
Nix-packaged integration-test command.
To uninstall the declarative setup, remove/disable the module and rebuild;
remove only Phonon's GNOME source in Settings. Keep other sources/components.

NixOS migration verification: 67 Python tests passed; Rust release
build, Clippy and formatting checks passed; private-daemon runtime registration,
staged discovery and Nix-packaged discovery/activation passed on IBus 1.5.33.
A dedicated GTK scratch window in the real GNOME Wayland session received a
Unicode commit through Phonon, and its clipboard contents were identical before
and after. The running service loaded the cached CPU model successfully and
reported healthy keyboard monitoring. Physical speech/hotkey gestures,
logout/reboot and administrator-activated rebuild checks still require a manual
pass; the scratch test injected known text through the native client rather
than recording speech.

## Terminals And SSH

Terminal mode copies the text with `wl-copy`, waits for the configured delay, then sends a complete `Ctrl+Shift+V` press and release sequence. The trigger modifier is released before this happens. This is intended for GNOME terminals and SSH sessions inside them, including Herdr where its terminal frontend honors the standard paste shortcut.

Terminal emulators, browser terminals, remote desktops, and SSH frontends do not all interpret synthetic shortcuts or clipboard ownership identically. A literal `^[[200~` indicates that a bracketed-paste escape sequence reached a program as ordinary input; it is usually a terminal/frontend or focus/paste integration issue rather than transcription text. Do not disable bracketed paste globally. Instead verify focus, try a slightly longer `--delay`, confirm the terminal's configured paste shortcut, and compare with a local GNOME terminal. Universal terminal paste compatibility is not guaranteed on GNOME Wayland.

## Automatic Startup And Logs

On NixOS, the [declarative module](#nixos-installation) supplies graphical-login
startup. On Debian, install and enable the user service:

```bash
./install.sh --autostart
systemctl --user status phonon-dictation.service
journalctl --user -u phonon-dictation.service -f
```

The service starts at graphical login, starts or reuses the local server, and rate-limits repeated failures to three starts per minute. It does not run as root. Existing service files are deliberately preserved; update the generated service explicitly with:

```bash
./install.sh --autostart --force-service
```

Lifecycle logs report device names/paths, inaccessible devices, waiting/restored monitoring, and recording cancellations. Permission errors are retried without repeatedly logging the same failure. The dictation client does not log raw key events, microphone audio, or transcription text; it logs only transcription completion. An independently configured transcription server may have its own logging policy.

Manage it with:

```bash
systemctl --user restart phonon-dictation.service
systemctl --user stop phonon-dictation.service
systemctl --user disable --now phonon-dictation.service
```

## Troubleshooting And Manual Checklist

- No keyboard detected: confirm `id` shows the `input` group, then log out and in. Inspect `journalctl --user -u phonon-dictation.service` for inaccessible devices.
- Server startup fails: run `.venv/bin/fermion serve phonon-2` on Debian, or activate the separate virtualenv inside the Nix shell and run `fermion serve phonon-2` on NixOS. Check the upstream diagnostic, free cache space, and `curl http://127.0.0.1:8000/health` after startup.
- No paste: check `systemctl --user status ydotool.service` on Debian, or `systemctl status ydotoold.service` and `YDOTOOL_SOCKET=/run/ydotoold/socket` on NixOS; focus a graphical text editor and ensure `wl-copy` is installed.
- Wrong microphone: list PipeWire/PulseAudio sources and pass `--source NAME`.
- Lost input events (`SYN_DROPPED`) indicate an evdev buffer overrun. Monitoring discards events through the next `SYN_REPORT`, queries held modifiers, and keeps the device open. Recording continues if the initiating keyboard still holds Right Ctrl; it is cancelled if that key is released or its state cannot be queried. Removing another keyboard does not cancel capture; ownership is not transferred if the initiating keyboard disconnects.

Transcription and clipboard insertion run in a serial worker while the input loop drains readable devices to `EAGAIN`. Previously, synchronous transcription (up to 120 seconds), clipboard commands, and the paste delay prevented input reads; one read per readiness notification also left queued events behind. These are buffer-overrun contributors, especially with mirrored physical/Solaar streams. The exact source of overruns on a particular keyboard requires hardware observation.

Periodic discovery also caches successfully inspected devices without the hotkey modifiers, avoiding slow repeated opens that can delay keyboard reads. Device identity changes, udev notifications, and resume invalidate this cache; inaccessible devices are still retried for permission recovery.

Hardware and compositor behaviour require manual testing. Before relying on the service, verify:

```bash
systemctl --user restart phonon-dictation.service
journalctl --user -u phonon-dictation.service -f
```

1. Hold and release Right Ctrl in a graphical text editor; confirm a complete sentence is pasted with Ctrl+V.
2. Hold Right Ctrl, press Right Shift during speech, then release Right Ctrl; confirm Ctrl+Shift+V works in the intended terminal.
3. Repeat after a fresh graphical login and after reconnecting an external keyboard.
4. Stop and restart the service; confirm no duplicate `fermion serve` or FFmpeg processes remain.
5. Connect and disconnect the external keyboard and dock while idle; verify added/removed logs and dictation on both laptop and external keyboards without restarting the service.
6. Remove all usable keyboards, then reconnect one (including under a different event number); verify waiting/restored logs and normal/terminal paste.
7. Disconnect a keyboard while holding Right Ctrl; verify capture is cancelled, its temporary WAV is removed, and a fresh press records normally.
8. Suspend/resume both while idle and while recording. Verify interrupted capture is discarded and new recordings work, including when input event paths remain unchanged.
9. Repeat with Solaar enabled and confirm one recording/transcription per gesture. Check that the Phonon server PID remains unchanged throughout hotplug and resume tests.
10. With the Logitech keyboard, hold Right Ctrl continuously for 30 seconds, then release; confirm no premature cancellation. Repeat rapid dictation cycles and type while transcription is in progress. Disconnect an unrelated keyboard during capture; confirm recording continues. Repeat with Solaar both enabled and disabled and check that input recovery produces no false `Input device removed` log.

These hardware-specific recovery scenarios must be checked on the target laptop/dock; mocked automated tests do not establish physical suspend or hotplug results.

## Uninstallation

On NixOS, remove/disable the declarative module and rebuild, remove only Phonon's
GNOME input source, and remove its separate virtualenv if no longer needed.
Inspect and remove any Phonon-specific user-service overrides from an earlier
manual installation. Keep other input sources and IBus components.

For the Debian/project-local installation:

```bash
systemctl --user disable --now phonon-dictation.service
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/phonon-dictation.service"
systemctl --user daemon-reload
rm -rf .venv
```

Remove the project checkout separately if desired. Remove downloaded model data using the cache location reported by `fermion models`; do not remove unrelated Hugging Face cache entries unless intended. Remove yourself from the `input` group only after verifying no other software needs it.

## Contributing

Native IBus output is provided by an [optional Rust helper](rust/ibus-helper/README.md).
See the [feasibility investigation](IBUS_INVESTIGATION.md) and [issue #2](https://github.com/tidley/phonon-wayland-dictation/issues/2).
Its isolated integration test does not change the running dictation service or desktop input source.

Install test dependencies with `.venv/bin/python -m pip install -e '.[test]'`, then run the hardware-independent suite with `PYTHONPATH=src .venv/bin/python -m pytest`. The explicit source path also avoids testing an older non-editable installed copy. Do not commit recordings, model caches, virtual environments, logs, credentials, machine-specific service files, or other private data. Please include manual test notes for changes affecting audio, keyboard input, Wayland, or terminals.

## License

This project is licensed under the [MIT License](LICENSE). Phonon-2 and its weights are not redistributed by this project.
