#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if command -v apt-get >/dev/null 2>&1; then
  echo "Installing Ubuntu runtime packages. sudo may ask for your password."
  sudo apt-get update
  sudo apt-get install -y \
    python3-venv \
    python3-pip \
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
echo "  $VENV_DIR/bin/python main.py"
