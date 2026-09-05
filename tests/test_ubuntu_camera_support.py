from __future__ import annotations

import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gui.camera_devices as camera_devices  # noqa: E402
from gui.frame_queue import get_latest, put_latest  # noqa: E402


class _ClosedCapture:
    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        pass


class _OpenedCapture:
    def __init__(self) -> None:
        self.released = False
        self.set_calls: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return True

    def set(self, prop: int, value: float) -> bool:
        self.set_calls.append((prop, value))
        return True

    def release(self) -> None:
        self.released = True


def test_linux_api_preferences_prioritise_v4l2(monkeypatch) -> None:
    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", False)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", True)
    monkeypatch.setattr(camera_devices.cv2, "CAP_V4L2", 200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)

    assert camera_devices._build_api_preferences(None) == [200, 0]


def test_windows_api_preferences_prioritise_dshow_then_msmf(monkeypatch) -> None:
    monkeypatch.setattr(camera_devices, "_IS_WIN", True)
    monkeypatch.setattr(camera_devices, "_IS_MAC", False)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_MSMF", 1400, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_DSHOW", 700, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)

    assert camera_devices._build_api_preferences(None) == [700, 1400, 0]


def test_list_camera_devices_returns_empty_when_probe_finds_nothing(monkeypatch) -> None:
    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", False)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", True)
    monkeypatch.setattr(camera_devices, "_list_linux_v4l2_device_names", lambda: {})
    monkeypatch.setattr(camera_devices, "_build_api_preferences", lambda _prefs: [0])
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", lambda _index, _api: _ClosedCapture())

    assert camera_devices.list_camera_devices(max_index=3, warmup_read=True) == []


def test_linux_camera_scan_only_probes_existing_video_nodes(monkeypatch) -> None:
    calls: list[int] = []

    def fake_capture(index: int, _api: int) -> _OpenedCapture:
        calls.append(index)
        return _OpenedCapture()

    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", False)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", True)
    monkeypatch.setattr(camera_devices, "_list_linux_v4l2_device_names", lambda: {})
    monkeypatch.setattr(camera_devices, "_list_linux_video_indices", lambda: [0, 1])
    monkeypatch.setattr(camera_devices, "_build_api_preferences", lambda _prefs: [0])
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    devices = camera_devices.list_camera_devices(max_index=20, warmup_read=False)

    assert calls == [0, 1]
    assert devices == [(0, "Camera 0"), (1, "Camera 1")]


def test_linux_video_indices_skip_metadata_nodes(monkeypatch) -> None:
    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", False)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", True)

    import glob
    import os

    monkeypatch.setattr(glob, "glob", lambda _pattern: ["/dev/video0", "/dev/video1", "/dev/media0"])
    monkeypatch.setattr(os.path, "basename", lambda path: path.rsplit("/", 1)[-1])
    monkeypatch.setattr(
        camera_devices,
        "_is_linux_video_capture_node",
        lambda path: path.endswith("video0"),
    )

    assert camera_devices._list_linux_video_indices() == [0]


def test_open_camera_capture_uses_v4l2_backend(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_capture(index: int, api: int) -> _OpenedCapture:
        calls.append((index, api))
        return _OpenedCapture()

    monkeypatch.setattr(camera_devices.cv2, "CAP_V4L2", 200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    cap = camera_devices.open_camera_capture(2, backend="v4l2")

    assert cap is not None
    assert calls == [(2, 200)]


def test_configure_camera_capture_prefers_mjpg_before_size_and_fps(monkeypatch) -> None:
    cap = _OpenedCapture()
    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_FOURCC", 6, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_BUFFERSIZE", 38, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_FRAME_WIDTH", 3, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_FRAME_HEIGHT", 4, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_FPS", 5, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoWriter_fourcc", lambda *chars: 1196444237)

    camera_devices.configure_camera_capture(cap, width=1280, height=720, target_fps=30)

    assert cap.set_calls == [
        (38, 1),
        (6, 1196444237),
        (3, 1280.0),
        (4, 720.0),
        (5, 30.0),
    ]


def test_configure_camera_capture_can_only_reduce_buffer(monkeypatch) -> None:
    cap = _OpenedCapture()
    monkeypatch.setattr(camera_devices.cv2, "CAP_PROP_BUFFERSIZE", 38, raising=False)

    camera_devices.configure_camera_capture(
        cap,
        width=1280,
        height=720,
        target_fps=30,
        apply_format=False,
    )

    assert cap.set_calls == [(38, 1)]


def test_frame_queue_keeps_latest_item_when_full() -> None:
    q: "queue.Queue[int]" = queue.Queue(maxsize=2)

    put_latest(q, 1)
    put_latest(q, 2)
    put_latest(q, 3)

    assert list(q.queue) == [2, 3]
    put_latest(q, 4)
    assert get_latest(q, timeout=0.01) == 4


def test_setup_ubuntu_lists_qt_xcb_and_v4l2_packages() -> None:
    setup = (ROOT / "scripts" / "setup_ubuntu.sh").read_text(encoding="utf-8")

    for package in ("libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-xkb1", "libxkbcommon-x11-0", "v4l-utils"):
        assert package in setup


def test_readme_lists_qt_and_camera_diagnostics() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (
        "QT_DEBUG_PLUGINS=1",
        "QT_QPA_PLATFORM=xcb",
        "scripts/diagnose_camera.py",
        "v4l2-ctl --list-devices",
        "--list-cameras --backend v4l2",
    ):
        assert text in readme
