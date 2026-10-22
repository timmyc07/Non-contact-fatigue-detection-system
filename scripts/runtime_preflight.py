"""檢查桌面 engine 啟動所需的關鍵 Python runtime 與平台後端。"""

from __future__ import annotations

import subprocess
import sys
from importlib import import_module
from importlib.metadata import distributions
from pathlib import Path

from gui.platforms import (
    OPENCV_RUNTIME_DISTRIBUTION,
    OPENCV_RUNTIME_VERSION,
    get_desktop_platform_runtime,
    get_platform_descriptor,
    validate_mediapipe_runtime,
)


ROOT = Path(__file__).resolve().parents[1]


def installed_opencv_distributions() -> dict[str, str]:
    installed: dict[str, str] = {}
    names = {
        "opencv-python",
        "opencv-contrib-python",
        "opencv-python-headless",
        "opencv-contrib-python-headless",
    }
    for distribution in distributions():
        name = str(distribution.metadata.get("Name", "") or "").lower()
        if name in names:
            installed[name] = str(distribution.version)
    return installed


def check_runtime() -> list[str]:
    errors: list[str] = []
    platform = get_platform_descriptor()
    if not platform.desktop_engine_supported:
        return [
            f"{platform.key} 尚未提供 Python/Tauri desktop engine；"
            "請使用對應的原生行動 runtime。"
        ]
    loaded: dict[str, object] = {}
    for module_name in ("cv2", "mediapipe", "PySide6", "numpy"):
        try:
            loaded[module_name] = import_module(module_name)
        except Exception as exc:
            errors.append(f"無法匯入 {module_name}：{exc}")

    if "mediapipe" in loaded:
        try:
            validate_mediapipe_runtime()
        except RuntimeError as exc:
            errors.append(str(exc))

    opencv_distributions = installed_opencv_distributions()
    expected_opencv = {
        OPENCV_RUNTIME_DISTRIBUTION: OPENCV_RUNTIME_VERSION,
    }
    if opencv_distributions != expected_opencv:
        details = ", ".join(
            f"{name}=={version}" for name, version in sorted(opencv_distributions.items())
        ) or "未找到 OpenCV distribution"
        errors.append(
            "OpenCV runtime 必須只安裝 "
            f"{OPENCV_RUNTIME_DISTRIBUTION}=={OPENCV_RUNTIME_VERSION}；目前為 {details}。"
            "若曾安裝 opencv-python，請先移除，再依 requirements.txt 重裝 contrib wheel。"
        )

    cv2 = loaded.get("cv2")
    runtime = get_desktop_platform_runtime()
    if cv2 is not None:
        registry = getattr(cv2, "videoio_registry", None)
        camera_apis = registry.getCameraBackends() if registry is not None else ()
        available_apis = [
            name
            for name in runtime.preferred_camera_api_names
            if isinstance(getattr(cv2, name, None), int)
            and getattr(cv2, name) in camera_apis
            and registry.hasBackend(getattr(cv2, name))
        ]
        if not available_apis:
            errors.append(
                f"{runtime.key} 的 OpenCV 沒有任何可用相機後端："
                f"{', '.join(runtime.preferred_camera_api_names)}"
            )

    return errors


def run_face_landmarker_smoke() -> str | None:
    command = [
        sys.executable,
        str(ROOT / "main.py"),
        "--runtime-preflight-face-landmarker",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Face Landmarker 隔離初始化失敗：{exc}"
    if completed.returncode == 0:
        return None
    output = completed.stdout.strip()
    detail = output[-2000:] if output else f"exit={completed.returncode}"
    return f"Face Landmarker 隔離初始化失敗：{detail}"


def main() -> int:
    errors = check_runtime()
    if not errors:
        face_landmarker_error = run_face_landmarker_smoke()
        if face_landmarker_error is not None:
            errors.append(face_landmarker_error)
    if errors:
        print("[Runtime preflight] 檢查失敗：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 78
    runtime = get_desktop_platform_runtime()
    print(f"[Runtime preflight] {runtime.key} Python runtime 檢查通過。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
