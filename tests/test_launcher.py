from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_panel_flag_is_rejected_without_starting_qt() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--legacy-ui"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "舊版 PySide 主面板已移除" in result.stdout
    assert "npm run desktop" in result.stdout
