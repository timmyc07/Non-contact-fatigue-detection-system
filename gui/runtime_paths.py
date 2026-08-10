"""解析唯讀資源與使用者可寫 runtime 資料的位置。"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypeAlias


PathInput: TypeAlias = str | os.PathLike[str]

_APP_DATA_DIRECTORY = "FatigueMonitor"


def resource_root(
    *,
    env: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    meipass: PathInput | None = None,
    module_file: PathInput | None = None,
) -> Path:
    """回傳包含唯讀應用程式資源的根目錄。

    Tauri sidecar 可注入 ``NCFD_RESOURCE_ROOT``。PyInstaller 封裝程式使用
    ``sys._MEIPASS``；其餘情境維持由本模組位置推得的 repository 根目錄。
    """
    environment = os.environ if env is None else env
    configured = environment.get("NCFD_RESOURCE_ROOT")
    if configured:
        return _path(configured)

    packaged = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if packaged:
        bundle_root = meipass if meipass is not None else getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return _path(bundle_root)

    source_file = Path(__file__) if module_file is None else _path(module_file)
    return source_file.resolve().parents[1]


def data_root(
    *,
    env: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    platform: str | None = None,
    home: PathInput | None = None,
    module_file: PathInput | None = None,
) -> Path:
    """回傳可寫入 runtime 資料的根目錄。

    ``NCFD_DATA_ROOT`` 優先，供 Tauri 選定已安裝程式的資料目錄。開發模式
    維持 repository 相對寫入；Windows 封裝程式預設為
    ``LOCALAPPDATA/FatigueMonitor``。
    """
    environment = os.environ if env is None else env
    configured = environment.get("NCFD_DATA_ROOT")
    if configured:
        return _path(configured)

    packaged = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not packaged:
        return resource_root(env=environment, frozen=False, module_file=module_file)

    user_home = _path(home) if home is not None else Path.home()
    platform_name = sys.platform if platform is None else platform
    if platform_name.startswith("win"):
        local_app_data = environment.get("LOCALAPPDATA")
        base = _path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / _APP_DATA_DIRECTORY
    if platform_name == "darwin":
        return user_home / "Library" / "Application Support" / _APP_DATA_DIRECTORY
    return user_home / ".local" / "share" / _APP_DATA_DIRECTORY


def resource_path(*parts: PathInput, **context: object) -> Path:
    """回傳 :func:`resource_root` 之下的路徑。"""
    return _join_under_root(resource_root(**context), parts)


def data_path(*parts: PathInput, **context: object) -> Path:
    """回傳 :func:`data_root` 之下的路徑。"""
    return _join_under_root(data_root(**context), parts)


def _path(value: PathInput) -> Path:
    return Path(value).expanduser()


def _join_under_root(root: Path, parts: tuple[PathInput, ...]) -> Path:
    components = tuple(_path(part) for part in parts)
    if any(component.is_absolute() or component.anchor for component in components):
        raise ValueError("runtime path components must be relative")
    if any(".." in component.parts for component in components):
        raise ValueError("runtime path components must not include '..'")
    resolved_root = root.resolve()
    candidate = root.joinpath(*components)
    try:
        candidate.resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("runtime path escapes the selected root") from exc
    return candidate
