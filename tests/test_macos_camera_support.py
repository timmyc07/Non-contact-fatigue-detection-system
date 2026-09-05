from __future__ import annotations

import gui.camera_devices as camera_devices


class _ClosedCapture:
    def isOpened(self) -> bool:  # noqa: N802
        return False

    def release(self) -> None:
        pass


class _OpenedCapture:
    def isOpened(self) -> bool:  # noqa: N802
        return True

    def read(self):
        return True, object()

    def release(self) -> None:
        pass


class _OpenedButUnreadableCapture(_OpenedCapture):
    def read(self):
        return False, None


def _select_macos(monkeypatch) -> None:
    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", True)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", False)


def test_macos_api_preferences_prioritise_avfoundation(monkeypatch) -> None:
    _select_macos(monkeypatch)
    monkeypatch.setattr(camera_devices.cv2, "CAP_AVFOUNDATION", 1200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)

    assert camera_devices._build_api_preferences(None) == [1200, 0]


def test_macos_scan_probes_numeric_indices_without_linux_devices(monkeypatch) -> None:
    _select_macos(monkeypatch)
    calls: list[tuple[int, int]] = []

    def fake_capture(index: int, api: int):
        calls.append((index, api))
        return _OpenedCapture() if index == 1 else _ClosedCapture()

    def fail_linux_enumeration():
        raise AssertionError("Linux enumeration must not run")

    monkeypatch.setattr(camera_devices, "_list_linux_video_indices", fail_linux_enumeration)
    monkeypatch.setattr(camera_devices, "_list_linux_v4l2_device_names", lambda: {})
    monkeypatch.setattr(camera_devices.cv2, "CAP_AVFOUNDATION", 1200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    assert camera_devices.list_camera_devices(max_index=3, warmup_read=False) == [(1, "Camera 1")]
    assert calls == [(0, 1200), (0, 0), (1, 1200), (2, 1200), (2, 0)]


def test_macos_scan_caps_probe_count(monkeypatch) -> None:
    _select_macos(monkeypatch)
    calls: list[int] = []

    def fake_capture(index: int, _api: int):
        calls.append(index)
        return _ClosedCapture()

    monkeypatch.setattr(camera_devices, "_build_api_preferences", lambda _prefs: [0])
    monkeypatch.setattr(camera_devices, "_list_linux_v4l2_device_names", lambda: {})
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    assert camera_devices.list_camera_devices(max_index=20, warmup_read=False) == []
    assert calls == list(range(8))


def test_macos_ffmpeg_fallback_uses_avfoundation_before_any(monkeypatch) -> None:
    _select_macos(monkeypatch)
    calls: list[int] = []

    def fake_capture(_index: int, api: int):
        calls.append(api)
        return _OpenedCapture() if api == 1200 else _ClosedCapture()

    monkeypatch.setattr(camera_devices.cv2, "CAP_FFMPEG", 1900, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_AVFOUNDATION", 1200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    assert camera_devices.open_camera_capture(0, backend="ffmpeg") is not None
    assert calls == [1900, 1200]


def test_macos_ffmpeg_fallback_skips_opened_backend_without_frames(monkeypatch) -> None:
    _select_macos(monkeypatch)
    calls: list[int] = []

    def fake_capture(_index: int, api: int):
        calls.append(api)
        if api == 1900:
            return _OpenedButUnreadableCapture()
        return _OpenedCapture()

    monkeypatch.setattr(camera_devices.cv2, "CAP_FFMPEG", 1900, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_AVFOUNDATION", 1200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "CAP_ANY", 0, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)
    monkeypatch.setattr(camera_devices.time, "sleep", lambda _seconds: None)
    ticks = iter((0.0, 0.0, 2.0, 3.0, 3.0))
    monkeypatch.setattr(camera_devices.time, "perf_counter", lambda: next(ticks))

    assert camera_devices.open_camera_capture(0, backend="ffmpeg") is not None
    assert calls == [1900, 1200]


def test_explicit_avfoundation_backend(monkeypatch) -> None:
    _select_macos(monkeypatch)
    calls: list[tuple[int, int]] = []

    def fake_capture(index: int, api: int):
        calls.append((index, api))
        return _OpenedCapture()

    monkeypatch.setattr(camera_devices.cv2, "CAP_AVFOUNDATION", 1200, raising=False)
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", fake_capture)

    assert camera_devices.open_camera_capture(2, backend="avfoundation") is not None
    assert calls == [(2, 1200)]
