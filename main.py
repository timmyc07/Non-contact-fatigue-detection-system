"""Launch the Tauri/Flutter shell or its hidden Python engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from ctypes.util import find_library
from pathlib import Path

# Align with demo: reduce log noise when Qt / MediaPipe coexist later
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")

from PySide6.QtCore import QLibraryInfo
from PySide6.QtWidgets import QApplication


# 延後載入重量級 engine adapter；測試可覆寫此 seam，preflight 也不需匯入完整 GUI runtime。
EngineApplication = None


_UBUNTU_QT_RUNTIME_PACKAGES = (
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-render-util0",
    "libxcb-xinerama0",
    "libxcb-xkb1",
    "libxkbcommon-x11-0",
)


def _prefer_pyside6_qt_plugins() -> None:
    """避免 OpenCV wheel 的 Qt plugin 路徑蓋掉 PySide6 的 platform plugins."""
    if not sys.platform.startswith("linux"):
        return

    plugins_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    platforms_dir = plugins_dir / "platforms"
    if platforms_dir.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)


def _missing_linux_qt_runtime_libraries() -> list[str]:
    if not sys.platform.startswith("linux"):
        return []
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return []

    required = {
        "xcb-cursor": "libxcb-cursor0",
    }
    missing: list[str] = []
    for lib_name, package_name in required.items():
        if find_library(lib_name) is None:
            missing.append(package_name)
    return missing


def _print_linux_qt_runtime_help(missing_packages: list[str]) -> None:
    package_text = " ".join(_UBUNTU_QT_RUNTIME_PACKAGES)
    missing_text = "、".join(missing_packages)
    print(
        "\n[Ubuntu Qt 相依套件缺失]\n"
        f"目前缺少：{missing_text}\n\n"
        "Qt 6.5+ 在 Linux 載入 xcb platform plugin 時需要這些系統套件；"
        "這不是 Python 套件重裝能解決的問題。\n\n"
        "請在一般終端機執行其中一種方式：\n"
        "  bash scripts/setup_ubuntu.sh\n"
        "或只補 Qt runtime：\n"
        f"  sudo apt-get update && sudo apt-get install -y {package_text}\n\n"
        "安裝完成後再執行：\n"
        "  .venv/bin/python main.py\n",
        file=sys.stderr,
    )


_prefer_pyside6_qt_plugins()


def _legacy_ui_requested() -> bool:
    return "--legacy-ui" in sys.argv


def _should_launch_tauri() -> bool:
    return "--engine" not in sys.argv


def _face_landmarker_preflight_requested() -> bool:
    return "--runtime-preflight-face-landmarker" in sys.argv


def _runtime_preflight_requested() -> bool:
    return "--runtime-preflight" in sys.argv


def _configure_frozen_matplotlib_cache() -> None:
    if not getattr(sys, "frozen", False):
        return
    from gui.runtime_paths import data_path

    try:
        cache = data_path("cache", "matplotlib")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=cache) as probe:
            probe.write(b"1")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[Runtime cache] 無法使用持久字型快取，沿用封裝的暫存目錄：{exc}", file=sys.stderr)
        return
    # PyInstaller hook 先覆寫此值；必須在 entry 重新指定，且早於 MediaPipe 匯入 pyplot。
    os.environ["MPLCONFIGDIR"] = str(cache)


def _run_face_landmarker_preflight() -> int:
    try:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        from gui.platforms import create_face_landmarker_base_options
        from gui.runtime_paths import resource_path

        model_path = resource_path("models", "face_landmarker.task")
        base_options = create_face_landmarker_base_options(mp_python, model_path)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            num_faces=1,
        )
        with mp_vision.FaceLandmarker.create_from_options(options):
            pass
    except Exception as exc:
        print(f"[Runtime preflight] Face Landmarker 初始化失敗：{exc}", file=sys.stderr)
        return 78
    print("[Runtime preflight] Face Landmarker 初始化通過。")
    return 0


def _launch_tauri() -> int:
    npm = shutil.which("npm")
    flutter = shutil.which("flutter")
    root = Path(__file__).resolve().parent
    if npm is None or flutter is None or not (root / "src-tauri" / "tauri.conf.json").exists():
        print(
            "[Launcher] Flutter/Tauri toolchain unavailable. "
            "Install Flutter and Node.js, then run `npm run desktop`."
        )
        return 78
    try:
        return subprocess.call([npm, "run", "desktop"], cwd=root)
    except OSError as exc:
        print(f"[Launcher] Unable to start Tauri: {exc}")
        return 78


def main() -> int:
    global EngineApplication
    _configure_frozen_matplotlib_cache()
    if _face_landmarker_preflight_requested():
        return _run_face_landmarker_preflight()
    if _runtime_preflight_requested():
        from scripts.runtime_preflight import check_runtime

        errors = check_runtime()
        if errors:
            for error in errors:
                print(f"[Runtime preflight] {error}", file=sys.stderr)
            return 78
        return 0
    if _legacy_ui_requested():
        print(
            "[Launcher] 舊版 PySide 主面板已移除。"
            "請使用 `npm run desktop` 啟動正式 Tauri/Flutter 面板；"
            "若只需背景服務，請使用 `python main.py --engine`."
        )
        return 2
    if _should_launch_tauri():
        return _launch_tauri()
    _prefer_pyside6_qt_plugins()
    missing_packages = _missing_linux_qt_runtime_libraries()
    if missing_packages:
        _print_linux_qt_runtime_help(missing_packages)
        return 78

    qt_args = [arg for arg in sys.argv if arg != "--engine"]
    app = QApplication(qt_args)
    app.setQuitOnLastWindowClosed(False)
    if EngineApplication is None:
        from gui.main_window import EngineApplication as _EngineApplication

        EngineApplication = _EngineApplication

    engine = EngineApplication()
    from gui.web_server import WEB_DASHBOARD_DEFAULT_PORT

    print(
        "[Engine] Desktop control backend listening on "
        f"http://127.0.0.1:{WEB_DASHBOARD_DEFAULT_PORT}"
    )
    exit_code = app.exec()
    if not engine.close_runtime():
        print("[Engine] Runtime cleanup did not complete", file=sys.stderr)
        return exit_code or 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
