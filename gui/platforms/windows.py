"""Windows 專用桌面 runtime 整合設定。"""

from __future__ import annotations

from .base import DesktopPlatformRuntime


RUNTIME = DesktopPlatformRuntime(
    key="windows",
    preferred_camera_api_names=("CAP_DSHOW", "CAP_MSMF", "CAP_ANY"),
    ffmpeg_fallback_api_names=("CAP_FFMPEG", "CAP_MSMF", "CAP_DSHOW", "CAP_ANY"),
    # 保留既有 Windows MediaPipe delegate 選擇，避免改變已驗證的 Windows 執行路徑。
    force_mediapipe_cpu_delegate=False,
)
