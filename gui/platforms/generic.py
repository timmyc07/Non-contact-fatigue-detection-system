"""未知桌面平台使用的保守 runtime fallback。"""

from __future__ import annotations

from .base import DesktopPlatformRuntime


RUNTIME = DesktopPlatformRuntime(
    key="generic",
    preferred_camera_api_names=("CAP_ANY",),
    ffmpeg_fallback_api_names=("CAP_FFMPEG", "CAP_ANY"),
)
