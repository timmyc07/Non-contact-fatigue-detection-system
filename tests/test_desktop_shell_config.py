from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_shell_uses_opaque_webview_surface() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    window = config["app"]["windows"][0]

    assert window["decorations"] is False
    assert window["transparent"] is False


def test_flutter_bootstrap_page_has_opaque_fallback_background() -> None:
    html = (ROOT / "flutter_app" / "web" / "index.html").read_text(encoding="utf-8")

    assert "background:transparent" not in html.replace(" ", "").lower()


def test_tauri_csp_allows_flutter_canvaskit_and_fonts() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"]

    assert "https://www.gstatic.com" in csp
    assert "https://fonts.gstatic.com" in csp
