#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export NCFD_ENGINE_PYTHON="${NCFD_ENGINE_PYTHON:-$repo_root/.venv/bin/python}"
export NCFD_ENGINE_ROOT="$repo_root"
test -x "$NCFD_ENGINE_PYTHON"
command -v flutter >/dev/null
command -v npm >/dev/null
command -v cargo >/dev/null
cd "$repo_root"
"$NCFD_ENGINE_PYTHON" -m scripts.runtime_preflight
cd "$repo_root/flutter_app"
flutter pub get
cd "$repo_root"
npm ci
node scripts/prepare_engine_sidecar.mjs
npx tauri build --config src-tauri/tauri.linux.conf.json
