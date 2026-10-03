"""五平台共用的能力與 artifact 契約。

這個 registry 只描述平台邊界，不載入相機、MediaPipe、Flutter 或原生 UI。
桌面 runtime policy 仍由同目錄下的 windows/macos/linux adapter 提供；
Android/iOS 在原生 runtime 完成前維持 planned，避免誤用 Python desktop engine。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


PLATFORM_IDS = ("windows", "macos", "linux", "android", "ios")
DESKTOP_PLATFORM_IDS = frozenset({"windows", "macos", "linux"})
MOBILE_PLATFORM_IDS = frozenset({"android", "ios"})
DESKTOP_RUNTIME_TYPE = "python_desktop"
MOBILE_RUNTIME_TYPE = "native_mobile"
CAPABILITY_IDS = frozenset(
    {
        "camera",
        "ble",
        "overlay",
        "tauri_shell",
        "native_inference",
        "background_lifecycle",
    }
)


class UnsupportedDesktopEngineError(RuntimeError):
    """平台沒有可用的 Python/Tauri desktop engine 時使用的錯誤。"""


@dataclass(frozen=True)
class PlatformDescriptor:
    """平台邊界的可序列化描述；不包含任何數值分析設定。"""

    key: str
    family: str
    runtime_type: str
    status: str
    desktop_engine_supported: bool
    native_inference_ready: bool
    capabilities: frozenset[str]
    artifact_types: tuple[str, ...]


PLATFORM_REGISTRY: dict[str, PlatformDescriptor] = {
    "windows": PlatformDescriptor(
        key="windows", family="desktop", runtime_type=DESKTOP_RUNTIME_TYPE, status="available",
        desktop_engine_supported=True, native_inference_ready=True,
        capabilities=frozenset({"camera", "ble", "overlay", "tauri_shell"}),
        artifact_types=("nsis",),
    ),
    "macos": PlatformDescriptor(
        key="macos", family="desktop", runtime_type=DESKTOP_RUNTIME_TYPE, status="available",
        desktop_engine_supported=True, native_inference_ready=True,
        capabilities=frozenset({"camera", "ble", "overlay", "tauri_shell"}),
        artifact_types=("app", "dmg"),
    ),
    "linux": PlatformDescriptor(
        key="linux", family="desktop", runtime_type=DESKTOP_RUNTIME_TYPE, status="available",
        desktop_engine_supported=True, native_inference_ready=True,
        capabilities=frozenset({"camera", "tauri_shell"}),
        artifact_types=("appimage", "deb"),
    ),
    "android": PlatformDescriptor(
        key="android", family="mobile", runtime_type=MOBILE_RUNTIME_TYPE, status="planned",
        desktop_engine_supported=False, native_inference_ready=False,
        capabilities=frozenset(), artifact_types=("apk", "aab"),
    ),
    "ios": PlatformDescriptor(
        key="ios", family="mobile", runtime_type=MOBILE_RUNTIME_TYPE, status="planned",
        desktop_engine_supported=False, native_inference_ready=False,
        capabilities=frozenset(), artifact_types=("ipa", "archive"),
    ),
}

_PLATFORM_ALIASES = {
    "win32": "windows", "cygwin": "windows",
    "darwin": "macos", "linux2": "linux",
}

_GENERIC_DESCRIPTOR = PlatformDescriptor(
    key="generic", family="unknown", runtime_type="unknown", status="unknown",
    desktop_engine_supported=True, native_inference_ready=False,
    capabilities=frozenset(), artifact_types=(),
)


def normalize_platform_name(platform_name: str | None = None) -> str:
    """將 Python/原生平台名稱轉成 registry key。"""
    value = (platform_name or sys.platform).strip().lower()
    if value in PLATFORM_REGISTRY:
        return value
    if value.startswith("win"):
        return "windows"
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("linux"):
        return "linux"
    return _PLATFORM_ALIASES.get(value, "generic")


def get_platform_descriptor(platform_name: str | None = None) -> PlatformDescriptor:
    """取得平台描述；未知平台保留 generic fallback。"""
    return PLATFORM_REGISTRY.get(normalize_platform_name(platform_name), _GENERIC_DESCRIPTOR)


def require_desktop_engine_support(platform_name: str | None = None) -> PlatformDescriptor:
    """要求平台可執行 Python desktop engine，否則 fail-closed。"""
    descriptor = get_platform_descriptor(platform_name)
    if not descriptor.desktop_engine_supported:
        raise UnsupportedDesktopEngineError(
            f"{descriptor.key} 尚未提供 Python/Tauri desktop engine；"
            "請使用對應的原生行動 runtime，完成前不可啟動 desktop engine。"
        )
    return descriptor


__all__ = [
    "CAPABILITY_IDS", "DESKTOP_PLATFORM_IDS", "DESKTOP_RUNTIME_TYPE", "MOBILE_PLATFORM_IDS",
    "MOBILE_RUNTIME_TYPE", "PLATFORM_IDS",
    "PLATFORM_REGISTRY", "PlatformDescriptor", "UnsupportedDesktopEngineError",
    "get_platform_descriptor", "normalize_platform_name", "require_desktop_engine_support",
]
