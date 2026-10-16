#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: ./install.sh [--autostart]"
  exit 0
fi
for cmd in ffmpeg curl wl-copy ydotool ydotoold; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd. Install Debian packages: ffmpeg curl wl-clipboard ydotool" >&2; exit 1; }
done
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
if ! .venv/bin/python -c 'import fermion' >/dev/null 2>&1 && ! [[ -x .venv/bin/fermion ]]; then
  echo "Installing Phonon-2 CPU runtime (first installation may take some time)..."
  .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  .venv/bin/python -m pip install fermion-research safetensors soundfile scipy zstandard
fi
if [[ "${1:-}" == "--autostart" ]]; then
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  dest="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/phonon-dictation.service"
  cat >"$dest" <<EOF
[Unit]
Description=Phonon-2 push-to-talk dictation
After=graphical-session.target pipewire.service ydotool.service
Wants=ydotool.service
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/phonon-dictate
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now phonon-dictation.service
  echo "Service installed. View: journalctl --user -u phonon-dictation -f"
  echo "Note: user services may need a fresh login to inherit new 'input' group membership."
fi
printf '\nReady. Run: %s/.venv/bin/phonon-dictate\n' "$PWD"
