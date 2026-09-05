#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export NCFD_ENGINE_ROOT="$repo_root"
export NCFD_ENGINE_PYTHON="$repo_root/.venv/bin/python"
export NCFD_BACKEND_PORT="5055"

test -x "$NCFD_ENGINE_PYTHON"
command -v flutter >/dev/null
command -v npm >/dev/null
command -v cargo >/dev/null
cd "$repo_root"
"$NCFD_ENGINE_PYTHON" -m scripts.runtime_preflight

cd "$repo_root/flutter_app"
flutter pub get
cd "$repo_root"
if [[ ! -x node_modules/.bin/tauri ]]; then
  npm ci
fi
npm run desktop
