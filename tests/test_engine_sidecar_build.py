from __future__ import annotations

import os
from pathlib import Path

from scripts import build_engine_sidecar


def test_engine_executable_name_is_platform_specific() -> None:
    assert build_engine_sidecar.engine_executable_name("win32") == "ncfd-engine.exe"
    assert build_engine_sidecar.engine_executable_name("darwin") == "ncfd-engine"
    assert build_engine_sidecar.engine_executable_name("linux") == "ncfd-engine"


def test_add_data_argument_uses_host_path_separator(tmp_path: Path) -> None:
    source = tmp_path / "asset"

    assert build_engine_sidecar.add_data_argument(source, "models") == (
        f"{source}{os.pathsep}models"
    )


def test_build_command_keeps_required_runtime_resources(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models/face_landmarker.task").write_bytes(b"test model")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/mediapipe_tuning.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(build_engine_sidecar, "ROOT", tmp_path)
    command = build_engine_sidecar.build_command("python-for-test")
    rendered = "\n".join(command)

    assert command[:3] == ["python-for-test", "-m", "PyInstaller"]
    assert "--onedir" in command
    assert "face_landmarker.task" in rendered
    assert "mediapipe_tuning.json" in rendered
    assert "gui/web_ui" not in rendered
    assert "opencv-contrib-python" in rendered
    assert "--copy-metadata" in command
    assert command[-1].endswith("main.py")
