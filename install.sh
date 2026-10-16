#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [--autostart] [--force-service] [--install-system-deps] [--skip-model-download]

Installs the application into .venv. System packages are only installed when
--install-system-deps is supplied. Existing service configuration is left
unchanged unless --force-service is supplied.
EOF
}

autostart=false
force_service=false
install_system_deps=false
download_model=true
for arg in "$@"; do
  case "$arg" in
    --autostart) autostart=true ;;
    --force-service) force_service=true ;;
    --install-system-deps) install_system_deps=true ;;
    --skip-model-download) download_model=false ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

if [[ ! -r /etc/os-release ]] || ! . /etc/os-release || [[ "${ID:-}" != "debian" ]]; then
  echo "This installer supports Debian. Install dependencies manually on other distributions." >&2
  exit 1
fi

command -v python3 >/dev/null || { echo "Python 3 is required (install python3 python3-venv)." >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10 or newer is required; found $(python3 --version)." >&2
  exit 1
}

packages=(python3-venv ffmpeg curl wl-clipboard ydotool)
missing_commands=()
for cmd in ffmpeg curl wl-copy ydotool ydotoold; do
  command -v "$cmd" >/dev/null || missing_commands+=("$cmd")
done
if ((${#missing_commands[@]})); then
  if ! "$install_system_deps"; then
    echo "Missing commands: ${missing_commands[*]}" >&2
    echo "Install required Debian packages, then retry:" >&2
    echo "  sudo apt install ${packages[*]}" >&2
    echo "Or rerun with: ./install.sh --install-system-deps" >&2
    exit 1
  fi
  command -v sudo >/dev/null || { echo "sudo is required for --install-system-deps." >&2; exit 1; }
  sudo apt update
  sudo apt install "${packages[@]}"
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
venv_python="$project_dir/.venv/bin/python"
[[ -x "$venv_python" ]] || { echo ".venv is not a usable virtual environment; remove it and retry." >&2; exit 1; }

"$venv_python" -m pip install --upgrade pip
# Fermion declares torch as a dependency. Install its CPU wheel first so a
# Debian CPU-only installation does not select an accelerator build.
"$venv_python" -m pip install --upgrade --index-url https://download.pytorch.org/whl/cpu torch
"$venv_python" -m pip install --upgrade .

if "$download_model"; then
  echo "Downloading or verifying the Phonon-2 model (about 164 MB on first run)..."
  "$project_dir/.venv/bin/fermion" transcribe phonon-2 /dev/null --download-only
fi

if "$autostart"; then
  command -v systemctl >/dev/null || { echo "systemctl is required for --autostart." >&2; exit 1; }
  service_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  dest="$service_dir/phonon-dictation.service"
  mkdir -p "$service_dir"
  if [[ -e "$dest" && "$force_service" != true ]]; then
    echo "Existing service left unchanged: $dest" >&2
    echo "Use --force-service to replace it with this release's template." >&2
    systemctl --user enable --now phonon-dictation.service
  else
    escaped_dir=${project_dir//\\/\\\\}
    escaped_dir=${escaped_dir//&/\\&}
    sed "s|@PROJECT_DIR@|$escaped_dir|g" systemd/phonon-dictation.service.in >"$dest"
    systemctl --user daemon-reload
    systemctl --user enable --now phonon-dictation.service
    echo "Service installed. Logs: journalctl --user -u phonon-dictation.service -f"
  fi
fi

cat <<EOF

Ready. Run: $project_dir/.venv/bin/phonon-dictate
For keyboard access, add yourself to the input group if needed:
  sudo usermod -aG input "$USER"
Then log out and log in before starting the user service.
EOF
