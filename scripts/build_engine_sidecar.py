"""Build the platform-native PyInstaller engine used by Tauri releases."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist"
ENGINE_DIST = DIST_ROOT / "ncfd-engine"
WORK_ROOT = ROOT / "build" / "pyinstaller"


def engine_executable_name(platform_name: str | None = None) -> str:
    platform_value = sys.platform if platform_name is None else platform_name
    return "ncfd-engine.exe" if platform_value.startswith("win") else "ncfd-engine"


def add_data_argument(source: Path, destination: str) -> str:
    return f"{source}{os.pathsep}{destination}"


def build_command(python_executable: str | Path = sys.executable) -> list[str]:
    model_path = ROOT / "models" / "face_landmarker.task"
    tuning_path = ROOT / "config" / "mediapipe_tuning.json"
    web_ui_path = ROOT / "gui" / "web_ui"
    for required_path in (model_path, tuning_path, web_ui_path):
        if not required_path.exists():
            raise FileNotFoundError(f"Required engine resource is missing: {required_path}")

    return [
        str(python_executable),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "ncfd-engine",
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(WORK_ROOT),
        "--specpath",
        str(WORK_ROOT),
        "--collect-all",
        "mediapipe",
        "--collect-all",
        "cv2",
        "--exclude-module",
        "mediapipe.tasks.python.test",
        "--hidden-import",
        "engineio.async_drivers.threading",
        "--hidden-import",
        "flask_socketio",
        "--add-data",
        add_data_argument(model_path, "models"),
        "--add-data",
        add_data_argument(tuning_path, "config"),
        "--add-data",
        add_data_argument(web_ui_path, "gui/web_ui"),
        str(ROOT / "main.py"),
    ]


def main() -> int:
    if ENGINE_DIST.exists():
        shutil.rmtree(ENGINE_DIST)
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)

    subprocess.run(build_command(), cwd=ROOT, check=True)
    engine_executable = ENGINE_DIST / engine_executable_name()
    if not engine_executable.is_file():
        raise FileNotFoundError(f"PyInstaller output is missing: {engine_executable}")
    if not sys.platform.startswith("win") and not os.access(engine_executable, os.X_OK):
        raise PermissionError(f"PyInstaller output is not executable: {engine_executable}")

    mediapipe_tests = ENGINE_DIST / "_internal" / "mediapipe" / "tasks" / "python" / "test"
    if mediapipe_tests.exists():
        shutil.rmtree(mediapipe_tests)
    print(f"Engine sidecar ready: {ENGINE_DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
