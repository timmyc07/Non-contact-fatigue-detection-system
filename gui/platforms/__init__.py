"""選擇作業系統整合層，不接觸共用分析程式。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .base import (
    MEDIAPIPE_RUNTIME_VERSION,
    OPENCV_RUNTIME_DISTRIBUTION,
    OPENCV_RUNTIME_VERSION,
    DesktopPlatformRuntime,
)
from .generic import RUNTIME as GENERIC_RUNTIME
from .linux import RUNTIME as LINUX_RUNTIME
from .macos import RUNTIME as MACOS_RUNTIME
from .windows import RUNTIME as WINDOWS_RUNTIME


def get_desktop_platform_runtime(platform_name: str | None = None) -> DesktopPlatformRuntime:
    name = (platform_name or sys.platform).lower()
    if name.startswith("win"):
        return WINDOWS_RUNTIME
    if name == "darwin":
        return MACOS_RUNTIME
    if name.startswith("linux"):
        return LINUX_RUNTIME
    return GENERIC_RUNTIME


def installed_mediapipe_version() -> str:
    try:
        import mediapipe

        return str(getattr(mediapipe, "__version__", "") or "")
    except Exception:
        return ""


def validate_mediapipe_runtime(
    *,
    platform_name: str | None = None,
    version: str | None = None,
) -> str:
    resolved_version = installed_mediapipe_version() if version is None else str(version)
    get_desktop_platform_runtime(platform_name).validate_mediapipe_version(resolved_version)
    return resolved_version


def create_face_landmarker_base_options(
    mp_python: Any,
    model_path: str | Path,
    *,
    platform_name: str | None = None,
    version: str | None = None,
) -> Any:
    runtime = get_desktop_platform_runtime(platform_name)
    validate_mediapipe_runtime(platform_name=platform_name, version=version)
    kwargs: dict[str, Any] = {"model_asset_path": str(model_path)}
    if runtime.force_mediapipe_cpu_delegate:
        delegate_enum = getattr(getattr(mp_python, "BaseOptions", None), "Delegate", None)
        cpu_delegate = getattr(delegate_enum, "CPU", None)
        if cpu_delegate is not None:
            kwargs["delegate"] = cpu_delegate
    return mp_python.BaseOptions(**kwargs)


__all__ = [
    "MEDIAPIPE_RUNTIME_VERSION",
    "OPENCV_RUNTIME_DISTRIBUTION",
    "OPENCV_RUNTIME_VERSION",
    "DesktopPlatformRuntime",
    "create_face_landmarker_base_options",
    "get_desktop_platform_runtime",
    "installed_mediapipe_version",
    "validate_mediapipe_runtime",
]
