# Phonon Wayland Dictation

Offline, whole-recording push-to-talk dictation for Debian GNOME on Wayland. Hold a key while speaking; on release, the complete recording is transcribed by a local [Fermion Research Phonon-2](https://pypi.org/project/fermion-research/) server and pasted into the focused application.

The model is downloaded once from its upstream source. After that download, audio is processed locally: recordings are sent only to `127.0.0.1`, not to a hosted transcription service.

## Features

- Full-recording transcription on key release, not incremental transcription.
- A local Phonon-2 HTTP server starts automatically when one is not already healthy.
- Reuses an independently started compatible local server and never terminates it.
- PipeWire/PulseAudio capture through FFmpeg, clipboard insertion through `wl-copy`, and input through `ydotool`.
- Optional systemd user service for graphical-login startup.
- Temporary WAV recordings are deleted after each attempt, including transcription failures.

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

Membership in `input` permits programs in your account to read raw input events, including passwords and other sensitive keyboard input. It is broad access, not an application-specific permission. The application filters out `ydotool`, `uinput`, and virtual keyboards to avoid feeding its synthetic paste shortcut back into dictation.

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

Hardware and compositor behaviour require manual testing. Before relying on the service, verify:

```bash
systemctl --user restart phonon-dictation.service
journalctl --user -u phonon-dictation.service -f
```

1. Hold and release Right Ctrl in a graphical text editor; confirm a complete sentence is pasted with Ctrl+V.
2. Hold Right Ctrl, press Right Shift during speech, then release Right Ctrl; confirm Ctrl+Shift+V works in the intended terminal.
3. Repeat after a fresh graphical login and after reconnecting an external keyboard.
4. Stop and restart the service; confirm no duplicate `fermion serve` or FFmpeg processes remain.

## Uninstallation

```bash
systemctl --user disable --now phonon-dictation.service
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/phonon-dictation.service"
systemctl --user daemon-reload
rm -rf .venv
```

Remove the project checkout separately if desired. Remove downloaded model data using the cache location reported by `fermion models`; do not remove unrelated Hugging Face cache entries unless intended. Remove yourself from the `input` group only after verifying no other software needs it.

## Contributing

Run the hardware-independent suite with `python -m pytest`. Do not commit recordings, model caches, virtual environments, logs, credentials, machine-specific service files, or other private data. Please include manual test notes for changes affecting audio, keyboard input, Wayland, or terminals.

## License

This project is licensed under the [MIT License](LICENSE). Phonon-2 and its weights are not redistributed by this project.
