from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _flutter_desktop_commands() -> set[str]:
    source = (ROOT / "flutter_app" / "lib" / "main.dart").read_text(encoding="utf-8")
    return set(re.findall(r"(?:onCommand|_runCommand)\(\s*'([^']+)'", source))


def _engine_desktop_commands() -> set[str]:
    source = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
    return set(re.findall(r'command == "([^"]+)"', source))


def test_flutter_visible_controls_only_call_supported_engine_commands() -> None:
    flutter_commands = _flutter_desktop_commands()
    engine_commands = _engine_desktop_commands()

    assert flutter_commands
    assert flutter_commands <= engine_commands
    assert {
        "alarm.test",
        "pipeline.set",
        "recording.set",
        "camera.select",
        "camera.configure",
        "camera.refresh",
        "analysis.configure",
        "overlay.configure",
        "preferences.configure",
        "auto_capture.configure",
        "auto_capture.set",
        "baseline.start",
        "monitor.layout",
        "replay.configure",
        "replay.set",
        "hotkeys.configure",
        "user_profile.configure",
        "alarm.configure",
        "settings.action",
        "settings.reset",
        "settings.save",
    } == flutter_commands
