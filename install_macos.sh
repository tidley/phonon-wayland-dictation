#!/usr/bin/env bash
set -euo pipefail

download_model=true
install_deps=false
for arg in "$@"; do
  case "$arg" in
    --skip-model-download) download_model=false ;;
    --install-system-deps) install_deps=true ;;
    --help|-h)
      echo "Usage: bash install_macos.sh [--install-system-deps] [--skip-model-download]"
      echo "Uses Homebrew for prerequisites only when --install-system-deps is supplied."
      exit 0 ;;
    *) echo "Unsupported macOS option: $arg (automatic startup is not configured)." >&2; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Darwin ]] || { echo "This installer requires macOS." >&2; exit 1; }
cd "$(dirname "$0")"
if "$install_deps"; then
  command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh" >&2; exit 1; }
  brew install python@3.13 ffmpeg
fi
# Prefer a supported Homebrew Python over Apple's older system Python.
python="${PYTHON:-python3}"
if [[ -z "${PYTHON:-}" ]] && command -v brew >/dev/null; then
  brew_python="$(brew --prefix)/opt/python@3.13/bin/python3.13"
  [[ ! -x "$brew_python" ]] || python="$brew_python"
fi
"$python" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' || {
  echo "Python 3.10+ required; install Homebrew python@3.13 or set PYTHON." >&2; exit 1;
}
for cmd in ffmpeg curl pbcopy; do
  command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }
done
if [[ ! -d .venv ]]; then
  "$python" -m venv .venv
fi
.venv/bin/python -c 'import sys; raise SystemExit(sys.platform != "darwin" or sys.version_info < (3, 10))'
.venv/bin/python -m pip install --upgrade pip
# Use native macOS PyTorch wheels, never the Linux CPU wheel index.
.venv/bin/python -m pip install --upgrade .
if "$download_model"; then
  .venv/bin/fermion transcribe phonon-2 /dev/null --download-only
fi
echo "Ready. Run: .venv/bin/phonon-dictate"
echo "Allow Input Monitoring, Accessibility, and Microphone for your terminal/Python"
echo "in System Settings > Privacy & Security. Restart the terminal after granting access."
