"""硬體 adapter 共用的桌面平台 runtime 契約。

模型、tuning 與 fatigue/rPPG 演算法不得放入本 package；此處只保存作業系統整合差異。
"""

from __future__ import annotations

from dataclasses import dataclass


MEDIAPIPE_RUNTIME_VERSION = "0.10.35"
OPENCV_RUNTIME_DISTRIBUTION = "opencv-contrib-python"
OPENCV_RUNTIME_VERSION = "5.0.0.93"


@dataclass(frozen=True)
class DesktopPlatformRuntime:
    """不進入數值分析路徑的平台專用 runtime 選項。"""

    key: str
    preferred_camera_api_names: tuple[str, ...]
    ffmpeg_fallback_api_names: tuple[str, ...]
    camera_probe_limit: int | None = None
    force_mediapipe_cpu_delegate: bool = False
    verify_camera_first_frame_on_fallback: bool = False

    def validate_mediapipe_version(self, version: str) -> None:
        if version == MEDIAPIPE_RUNTIME_VERSION:
            return
        raise RuntimeError(
            "MediaPipe runtime 版本不相容："
            f"目前為 {version or '未知'}，專案要求 {MEDIAPIPE_RUNTIME_VERSION}。"
            "請執行 `.venv/bin/python -m pip install -r requirements.txt`；"
            "Windows 請改用 `.\\.venv\\Scripts\\python -m pip install -r requirements.txt`。"
        )
