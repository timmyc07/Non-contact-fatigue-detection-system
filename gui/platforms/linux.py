"""保留 Ubuntu 支援所需的 Linux runtime fallback。"""

from __future__ import annotations

from .base import DesktopPlatformRuntime


RUNTIME = DesktopPlatformRuntime(
    key="linux",
    preferred_camera_api_names=("CAP_V4L2", "CAP_ANY"),
    ffmpeg_fallback_api_names=("CAP_FFMPEG", "CAP_V4L2", "CAP_ANY"),
)
