"""macOS 專用桌面 runtime 整合設定。"""

from __future__ import annotations

from .base import DesktopPlatformRuntime


RUNTIME = DesktopPlatformRuntime(
    key="macos",
    preferred_camera_api_names=("CAP_AVFOUNDATION", "CAP_ANY"),
    # 原生相機輸入優先走 AVFoundation；CAP_FFMPEG 對整數 camera index 在
    # macOS/OpenCV builds 常不支援，保留為最後 fallback 以維持相容性。
    ffmpeg_fallback_api_names=("CAP_AVFOUNDATION", "CAP_ANY", "CAP_FFMPEG"),
    camera_probe_limit=8,
    # MediaPipe 0.10.35 在 macOS 的 Face Landmarker 使用 XNNPACK CPU；明確指定
    # delegate，避免未來的隱含預設誤入不穩定的 Metal inference 路徑。
    force_mediapipe_cpu_delegate=True,
    verify_camera_first_frame_on_fallback=True,
)
