#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" == ubuntu ]] && dpkg --compare-versions "${VERSION_ID:-0}" lt 24.04; then
    echo "Ubuntu 24.04 or newer is required for Tauri's WebKitGTK 4.1 build dependency." >&2
    exit 1
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  echo "Installing Ubuntu runtime packages. sudo may ask for your password."
  sudo apt-get update
  sudo apt-get install -y \
    python3-venv \
    python3-pip \
    build-essential \
    curl \
    file \
    libssl-dev \
    libxdo-dev \
    librsvg2-dev \
    libwebkit2gtk-4.1-dev \
    libgl1 \
    libglib2.0-0 \
    libdbus-1-3 \
    libfontconfig1 \
    libfreetype6 \
    libice6 \
    libsm6 \
    libx11-xcb1 \
    libxext6 \
    libxrender1 \
    libxcb-cursor0 \
    libxcb-cursor-dev \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-util1 \
    libxcb-xfixes0 \
    libxcb-xkb1 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libegl1 \
    v4l-utils
else
  echo "apt-get not found; skipping system package installation."
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

echo
echo "Done. Activate with:"
echo "  source $VENV_DIR/bin/activate"
echo "Run the app with:"
echo "  $VENV_DIR/bin/python main.py --engine"
echo "Then start the Tauri/Flutter panel from the repository root with:"
echo "  bash scripts/start_desktop_linux.sh"
echo "Build Linux AppImage/deb bundles with:"
echo "  bash scripts/build_desktop_linux.sh"
