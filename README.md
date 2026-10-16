# Phonon Wayland Dictation

Offline whole-recording push-to-talk for GNOME Wayland, using **Phonon-2**.

- Hold **Right Ctrl** → speak → release: full transcription is pasted via `Ctrl+V`.
- Hold **Right Ctrl + Right Shift** during recording: paste via `Ctrl+Shift+V` (useful in local terminals / SSH sessions).
- A **single application command** starts the local Phonon server automatically if needed, then listens for keyboard input. No second terminal is needed.
- Optional systemd user service starts everything at GNOME login.
- Clipboard-based insertion is quick but replaces the existing clipboard. The trigger keys are still visible to the focused application.
- All speech processing remains on your device; the server listens on localhost. No recordings or model weights are bundled.

## Debian installation

Install host dependencies (Debian 13 may require `trixie-backports` for `ydotool`):

```bash
sudo apt install python3-venv ffmpeg curl wl-clipboard ydotool
sudo usermod -aG input "$USER"
```

**Security:** `input` group membership allows programs in your account to read raw keyboard events, including passwords. Consider a more restricted input mechanism in future. Log out and in to apply group membership fully, or use `newgrp input` for testing in one shell. The `ydotool` user service must be active (`systemctl --user status ydotool.service`).

Then from the unpacked project directory:

```bash
./install.sh
.venv/bin/phonon-dictate
```

The first run may download the local model. `install.sh` sets up a project-local Python environment and CPU speech engine; it never requires your old prototype virtual environment.

## Autostart

```bash
./install.sh --autostart
systemctl --user status phonon-dictation.service
journalctl --user -u phonon-dictation.service -f
```

Stop/disable: `systemctl --user disable --now phonon-dictation.service`.

A systemd user manager started **before** `input` group membership was activated may not have the necessary permissions; a fresh GNOME login resolves this. This is a limitation of systemd credential inheritance, not the dictation code.

## CLI

```bash
.venv/bin/phonon-dictate --help
.venv/bin/phonon-dictate --no-start-server  # attach to already-running server
```

Configurable: `--source`, `--api-url` (loopback only), `--delay`, `--mode`, `--server-command`.

## Limitations

- Some terminal applications use different paste shortcuts, so `Ctrl+Shift+V` cannot guarantee every terminal/SSH frontend.
- Clipboard contents are overwritten; paste behaviour and focus depend on compositor/application.
- Press and release modifiers normally; Right Ctrl remains visible to the focused application.
- Audio captured to a temporary WAV, deleted after transcription, and POSTed only to localhost.
- The user service is intended for GNOME sessions and may require permission/session adjustments on other desktops.

## Contributing

Issues and pull requests welcome. No machine paths, personal audio or secrets should be committed. Software is MIT-licensed; Phonon-2 model weights have their own licence and are not redistributed.
