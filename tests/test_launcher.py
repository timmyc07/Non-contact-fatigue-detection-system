from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import main as launcher


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


def test_engine_entry_creates_only_headless_application_adapter(
    monkeypatch,
) -> None:
    events: list[object] = []

    class FakeApplication:
        def __init__(self, args: list[str]) -> None:
            events.append(("app", args))

        def setQuitOnLastWindowClosed(self, enabled: bool) -> None:  # noqa: N802
            events.append(("quit_on_last_window", enabled))

        def setStyle(self, _style: str) -> None:  # noqa: N802
            raise AssertionError("engine mode must not apply a visual Qt style")

        def setStyleSheet(self, _stylesheet: str) -> None:  # noqa: N802
            raise AssertionError("engine mode must not apply a visual stylesheet")

        def exec(self) -> int:
            return 0

    class FakeEngineApplication:
        def __init__(self) -> None:
            events.append("engine_application")

        def close_runtime(self) -> None:
            events.append("engine_close")

    monkeypatch.setattr(launcher, "QApplication", FakeApplication)
    monkeypatch.setattr(launcher, "EngineApplication", FakeEngineApplication)
    monkeypatch.setattr(launcher, "_missing_linux_qt_runtime_libraries", lambda: [])
    monkeypatch.setattr(sys, "argv", ["main.py", "--engine"])

    assert launcher.main() == 0
    assert events == [
        ("app", ["main.py"]),
        ("quit_on_last_window", False),
        "engine_application",
        "engine_close",
    ]
