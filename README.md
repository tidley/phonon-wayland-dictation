# Phonon Wayland Dictation

Offline, whole-recording push-to-talk dictation for Debian GNOME on Wayland. Hold a key while speaking; on release, the complete recording is transcribed by a local [Fermion Research Phonon-2](https://pypi.org/project/fermion-research/) server and pasted into the focused application.

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

This release has been exercised on Debian 13 GNOME Wayland, Python 3.13, and an AMD Ryzen 7 PRO 7840U using CPU inference. It needs enough memory for the local runtime; observed use is roughly 870-960 MB. Other Debian versions and Wayland desktops may work but are not validated here.

Phonon-2 and the `fermion-research` runtime are separate upstream software. Their model weights are downloaded into the Fermion/Hugging Face cache, are not included in this repository, and remain subject to their upstream terms.

## Installation

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

## Keyboard Access And Security

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

Shift state is tracked per keyboard. Shift held before Ctrl, or pressed during a recording, selects terminal paste even if Shift is released first. Mirrored physical/Solaar events are merged by timestamp and repeated Ctrl presses are coalesced. The first Ctrl release ends the recording, including a release routed through another keyboard; remaining mirrored releases do not submit it again. Release held trigger keys before starting another recording or after reconnecting a keyboard.

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

## Terminals And SSH

Terminal mode copies the text with `wl-copy`, waits for the configured delay, then sends a complete `Ctrl+Shift+V` press and release sequence. The trigger modifier is released before this happens. This is intended for GNOME terminals and SSH sessions inside them, including Herdr where its terminal frontend honors the standard paste shortcut.

Terminal emulators, browser terminals, remote desktops, and SSH frontends do not all interpret synthetic shortcuts or clipboard ownership identically. A literal `^[[200~` indicates that a bracketed-paste escape sequence reached a program as ordinary input; it is usually a terminal/frontend or focus/paste integration issue rather than transcription text. Do not disable bracketed paste globally. Instead verify focus, try a slightly longer `--delay`, confirm the terminal's configured paste shortcut, and compare with a local GNOME terminal. Universal terminal paste compatibility is not guaranteed on GNOME Wayland.

## Automatic Startup And Logs

Install and enable the user service:

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
- Server startup fails: run `.venv/bin/fermion serve phonon-2` in a terminal to see the upstream diagnostic, check free cache space, and verify `curl http://127.0.0.1:8000/health` after startup.
- No paste: check `systemctl --user status ydotool.service`, focus a graphical text editor, and ensure `wl-copy` is installed.
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

```bash
systemctl --user disable --now phonon-dictation.service
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/phonon-dictation.service"
systemctl --user daemon-reload
rm -rf .venv
```

Remove the project checkout separately if desired. Remove downloaded model data using the cache location reported by `fermion models`; do not remove unrelated Hugging Face cache entries unless intended. Remove yourself from the `input` group only after verifying no other software needs it.

## Contributing

Install test dependencies with `.venv/bin/python -m pip install -e '.[test]'`, then run the hardware-independent suite with `PYTHONPATH=src .venv/bin/python -m pytest`. The explicit source path also avoids testing an older non-editable installed copy. Do not commit recordings, model caches, virtual environments, logs, credentials, machine-specific service files, or other private data. Please include manual test notes for changes affecting audio, keyboard input, Wayland, or terminals.

## License

This project is licensed under the [MIT License](LICENSE). Phonon-2 and its weights are not redistributed by this project.
