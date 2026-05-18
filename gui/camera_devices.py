"""Enumerate cameras — aligned with mediapipe_rppg_system V1 ``camera_utils.list_cameras``.

Windows: if pygrabber returns DirectShow device names, we **do not** open VideoCapture per
index (instant list, same as V1). Only fall back to OpenCV probing when names are unavailable.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, Sequence

import cv2

try:
    _CAP_DEVICE_DESC = cv2.CAP_PROP_DEVICE_DESCRIPTION  # type: ignore[union-attr]
except Exception:
    _CAP_DEVICE_DESC = None

_IS_WIN = sys.platform.startswith("win")

try:
    if cv2 is not None:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


def _list_windows_dshow_device_names() -> list[str]:
    if not _IS_WIN:
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph

        graph = FilterGraph()
        names = graph.get_input_devices()
        return [str(n).strip() for n in names if str(n).strip()]
    except Exception:
        return []


def _list_linux_v4l2_device_names() -> dict[int, str]:
    if _IS_WIN:
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


def _build_api_preferences(api_preferences: Sequence[int] | None) -> list[int]:
    if api_preferences is not None:
        return [int(api) for api in api_preferences]

    prefs: list[int] = []
    if _IS_WIN:
        # Prefer MSMF: preserves native codec (e.g. MJPG) without driver-level
        # decompression that DirectShow typically applies.
        cap_msmf = getattr(cv2, "CAP_MSMF", None)
        if isinstance(cap_msmf, int):
            prefs.append(cap_msmf)
    else:
        cap_v4l2 = getattr(cv2, "CAP_V4L2", None)
        if isinstance(cap_v4l2, int):
            prefs.append(cap_v4l2)
    prefs.append(getattr(cv2, "CAP_ANY", 0))
    return prefs


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

    for i in range(max_index):
        if not _probe_camera_index(i, warmup_read, api_preferences):
            continue
        if _IS_WIN:
            label = f"Camera {i}"
        else:
            label = linux_labels.get(i, f"Camera {i}")
        found.append((i, label))

    if not found:
        found.append((0, "Camera 0（未偵測到裝置）"))
    return found


def open_camera_capture(index: int, backend: str = "ffmpeg"):
    """Open the first working VideoCapture for ``index``.

    ``backend``:
        ``"ffmpeg"`` — Try CAP_FFMPEG first (file/stream path on Windows);
                       if that fails (common for integer camera indices),
                       fall back through CAP_MSMF → CAP_ANY.
                       cap.set() works without pipeline rebuild.
        ``"msmf"``   — Windows Media Foundation directly; preserves native MJPG.
                       cap.set() causes pipeline rebuild (~1 s each).
        ``"auto"``   — Platform-preferred order without explicit backend.
    """
    if cv2 is None:
        return None

    b = backend.lower().strip()

    def _try(api: int) -> Optional[Any]:
        try:
            cap = cv2.VideoCapture(index, api)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception:
            pass
        return None

    if b == "msmf":
        msmf = getattr(cv2, "CAP_MSMF", None)
        if msmf is not None:
            return _try(int(msmf))
        return None

    if b == "ffmpeg":
        # CAP_FFMPEG only accepts integer indices on some builds/platforms;
        # cascade through workable alternatives if it fails.
        for attr in ("CAP_FFMPEG", "CAP_MSMF", "CAP_ANY"):
            api_val = getattr(cv2, attr, None)
            if api_val is None:
                continue
            cap = _try(int(api_val))
            if cap is not None:
                return cap
        return None

    # "auto": platform-preferred order
    for api in _build_api_preferences(None):
        cap = _try(api)
        if cap is not None:
            return cap
    return None
