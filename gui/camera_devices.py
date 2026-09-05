"""Enumerate cameras across Windows, macOS, and Linux backends.

Windows: if pygrabber returns DirectShow device names, we **do not** open VideoCapture per
index (instant list, same as V1). Only fall back to OpenCV probing when names are unavailable.
Linux: prefer V4L2 and expose stable `/dev/v4l/by-id` labels when available.
macOS: probe camera indices with AVFoundation before the generic OpenCV backend.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Optional, Sequence

import cv2

from gui.platforms import get_desktop_platform_runtime

try:
    _CAP_DEVICE_DESC = cv2.CAP_PROP_DEVICE_DESCRIPTION  # type: ignore[union-attr]
except Exception:
    _CAP_DEVICE_DESC = None

_IS_WIN = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")

try:
    if cv2 is not None:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


def _list_windows_dshow_device_names() -> list[str]:
    if not _IS_WIN:
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph  # pyright: ignore[reportMissingModuleSource]

        graph = FilterGraph()
        names = graph.get_input_devices()
        return [str(n).strip() for n in names if str(n).strip()]
    except Exception:
        return []


def _list_linux_v4l2_device_names() -> dict[int, str]:
    if not _IS_LINUX:
        return {}
    try:
        import glob
        import os
    except Exception:
        return {}

    devices: dict[int, str] = {}
    for link in sorted(glob.glob("/dev/v4l/by-id/*")):
        try:
            real = os.path.realpath(link)
            if not real.startswith("/dev/video"):
                continue
            suffix = real.replace("/dev/video", "", 1)
            if not suffix.isdigit():
                continue
            devices[int(suffix)] = os.path.basename(link)
        except Exception:
            continue
    return devices


def _list_linux_video_indices() -> list[int]:
    if not _IS_LINUX:
        return []
    try:
        import glob
        import os
    except Exception:
        return []

    indices: list[int] = []
    for node in glob.glob("/dev/video*"):
        if not _is_linux_video_capture_node(node):
            continue
        suffix = os.path.basename(node).replace("video", "", 1)
        if suffix.isdigit():
            indices.append(int(suffix))
    return sorted(set(indices))


def _is_linux_video_capture_node(path: str) -> bool:
    if not _IS_LINUX:
        return False
    try:
        import fcntl
        import os
    except Exception:
        return True

    vidioc_querycap = 0x80685600
    v4l2_cap_video_capture = 0x00000001
    v4l2_cap_video_capture_mplane = 0x00001000
    v4l2_cap_device_caps = 0x80000000
    fd: int | None = None
    try:
        nonblock = int(getattr(os, "O_NONBLOCK", 0))
        fd = os.open(path, os.O_RDONLY | nonblock)
        buf = bytearray(104)
        ioctl = getattr(fcntl, "ioctl", None)
        if not callable(ioctl):
            return True
        ioctl(fd, vidioc_querycap, buf, True)
        capabilities = int.from_bytes(buf[84:88], "little")
        device_caps = int.from_bytes(buf[88:92], "little")
        caps = device_caps if capabilities & v4l2_cap_device_caps else capabilities
        return bool(caps & (v4l2_cap_video_capture | v4l2_cap_video_capture_mplane))
    except Exception:
        return True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def _build_api_preferences(api_preferences: Sequence[int] | None) -> list[int]:
    if api_preferences is not None:
        return [int(api) for api in api_preferences]

    prefs: list[int] = []
    runtime = get_desktop_platform_runtime(_selected_platform_name())
    for attr in runtime.preferred_camera_api_names:
        api = getattr(cv2, attr, None)
        if isinstance(api, int) and api not in prefs:
            prefs.append(api)
    return prefs


def _selected_platform_name() -> str:
    """解析目前 adapter，並保留測試覆寫平台旗標的能力。"""
    if _IS_WIN:
        return "win32"
    if _IS_MAC:
        return "darwin"
    if _IS_LINUX:
        return "linux"
    return sys.platform


def _probe_camera_index(index: int, warmup_read: bool, api_preferences: Sequence[int]) -> bool:
    for api in api_preferences:
        cap: Optional[Any] = None
        try:
            cap = cv2.VideoCapture(index, int(api))
            if not cap.isOpened():
                continue
            if warmup_read:
                ok, _ = cap.read()
                if not ok:
                    continue
            return True
        except Exception:
            continue
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
    return False


def list_camera_devices(*, max_index: int = 20, warmup_read: bool = True) -> list[tuple[int, str]]:
    """Return ``[(opencv_index, display_name), ...]`` for the camera dropdown.

    - **Windows + pygrabber**: same as V1 — enumerate DirectShow names only (no OpenCV open).
    - **Otherwise**: probe indices with OpenCV (DSHOW-first on Windows).
    """
    if cv2 is None:
        return [(0, "Camera 0（未安裝 OpenCV）")]

    dshow_names = _list_windows_dshow_device_names()
    if _IS_WIN and dshow_names:
        return [(i, name) for i, name in enumerate(dshow_names[:max_index])]

    api_preferences = _build_api_preferences(None)
    linux_labels = _list_linux_v4l2_device_names()
    found: list[tuple[int, str]] = []

    if _IS_LINUX:
        candidate_indices = [i for i in _list_linux_video_indices() if i < max_index]
    elif _IS_MAC:
        probe_limit = get_desktop_platform_runtime("darwin").camera_probe_limit
        candidate_indices = list(range(min(max_index, probe_limit or max_index)))
    else:
        candidate_indices = list(range(max_index))

    for i in candidate_indices:
        if not _probe_camera_index(i, warmup_read, api_preferences):
            continue
        if _IS_WIN:
            label = f"Camera {i}"
        else:
            label = linux_labels.get(i, f"Camera {i}")
        found.append((i, label))

    return found


def _apply_msmf_io_timeouts(cap: Optional[Any]) -> None:
    """Windows MSMF 專用：嘗試設定開啟／讀取逾時，緩解驅動異常時 ``cap.read()``
    無逾時地無限阻塞（P1-6 cap.read() hang 緩解）。

    ``CAP_PROP_OPEN_TIMEOUT_MSEC`` / ``CAP_PROP_READ_TIMEOUT_MSEC`` 為新版 OpenCV
    才有的屬性，用 ``hasattr``/``try`` 包住以相容舊版 OpenCV（屬性不存在時
    ``getattr`` 回傳 ``None``，直接跳過）。DSHOW 與 V4L2 後端沒有對應屬性可設，
    為已知限制，不在此函式處理。
    """
    if cap is None:
        return
    open_timeout_prop = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    if open_timeout_prop is not None:
        try:
            cap.set(open_timeout_prop, 10000)
        except Exception:
            pass
    read_timeout_prop = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    if read_timeout_prop is not None:
        try:
            cap.set(read_timeout_prop, 5000)
        except Exception:
            pass


def open_camera_capture(index: int, backend: str = "auto"):
    """Open the first working VideoCapture for ``index``.

    ``backend``:
        ``"auto"``   — Platform-preferred order without explicit backend.
        ``"avfoundation"`` — macOS AVFoundation directly.
        ``"v4l2"``   — Linux Video4Linux2 directly.
        ``"ffmpeg"`` — Try CAP_FFMPEG first (file/stream path on Windows);
                       if that fails (common for integer camera indices),
                       fall back through platform-preferred APIs.
                       cap.set() works without pipeline rebuild.
        ``"msmf"``   — Windows Media Foundation directly; preserves native MJPG.
                       cap.set() causes pipeline rebuild (~1 s each).
        ``"dshow"``  — Windows DirectShow directly; useful for some virtual
                       cameras and drivers that do not work through MSMF.
    """
    if cv2 is None:
        return None

    b = backend.lower().strip()

    def _try(api: int, *, verify_first_frame: bool = False) -> Optional[Any]:
        try:
            cap = cv2.VideoCapture(index, api)
            if cap.isOpened():
                if verify_first_frame:
                    deadline = time.perf_counter() + 1.5
                    while time.perf_counter() < deadline:
                        ok, frame = cap.read()
                        if ok and frame is not None:
                            return cap
                        time.sleep(0.01)
                    cap.release()
                    return None
                return cap
            cap.release()
        except Exception:
            pass
        return None

    if b == "msmf":
        msmf = getattr(cv2, "CAP_MSMF", None)
        if msmf is not None:
            cap = _try(int(msmf))
            _apply_msmf_io_timeouts(cap)
            return cap
        return None

    if b == "dshow":
        # DSHOW 無 CAP_PROP_OPEN_TIMEOUT_MSEC / CAP_PROP_READ_TIMEOUT_MSEC 可設，
        # 為已知限制（driver hang 時 cap.read() 仍可能無逾時地阻塞）。
        dshow = getattr(cv2, "CAP_DSHOW", None)
        if dshow is not None:
            return _try(int(dshow))
        return None

    if b == "v4l2":
        # V4L2 同樣無對應 timeout 屬性可設，為已知限制。
        v4l2 = getattr(cv2, "CAP_V4L2", None)
        if v4l2 is not None:
            return _try(int(v4l2))
        return None

    if b == "avfoundation":
        avfoundation = getattr(cv2, "CAP_AVFOUNDATION", None)
        if avfoundation is not None:
            return _try(int(avfoundation))
        return None

    if b == "ffmpeg":
        # CAP_FFMPEG only accepts integer indices on some builds/platforms;
        # cascade through workable alternatives if it fails.
        runtime = get_desktop_platform_runtime(_selected_platform_name())
        attrs = runtime.ffmpeg_fallback_api_names
        for attr in attrs:
            api_val = getattr(cv2, attr, None)
            if api_val is None:
                continue
            cap = _try(
                int(api_val),
                verify_first_frame=runtime.verify_camera_first_frame_on_fallback,
            )
            if cap is not None:
                if attr == "CAP_MSMF":
                    _apply_msmf_io_timeouts(cap)
                return cap
        return None

    # "auto": platform-preferred order
    msmf_api = getattr(cv2, "CAP_MSMF", None)
    for api in _build_api_preferences(None):
        cap = _try(api)
        if cap is not None:
            if msmf_api is not None and api == int(msmf_api):
                _apply_msmf_io_timeouts(cap)
            return cap
    return None


def configure_camera_capture(
    cap: Any,
    *,
    width: int,
    height: int,
    target_fps: float,
    prefer_mjpg: bool = True,
    apply_format: bool = True,
) -> None:
    """套用 OpenCV 相機協商參數。

    Linux UVC webcam 常在 720p 的 YUYV 模式只能提供 10 FPS，但同解析度
    MJPG 可達 30 FPS；因此在 Linux 先要求 MJPG，再設定解析度與 FPS。
    CAP_PROP_* 是否生效取決於 OpenCV backend 與驅動；失敗時保持原協商值。
    """
    if cv2 is None:
        return

    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not apply_format:
            return
        if prefer_mjpg:
            fourcc_fn = getattr(cv2, "VideoWriter_fourcc", None)
            if callable(fourcc_fn):
                cap.set(cv2.CAP_PROP_FOURCC, fourcc_fn(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        cap.set(cv2.CAP_PROP_FPS, float(target_fps))
    except Exception:
        pass
