#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
python_path="$repo_root/.venv/bin/python"
export NCFD_ENGINE_PYTHON="$python_path"

test -x "$python_path"
command -v flutter >/dev/null
command -v npm >/dev/null
command -v cargo >/dev/null

cd "$repo_root"
npm ci
npm run desktop:build
