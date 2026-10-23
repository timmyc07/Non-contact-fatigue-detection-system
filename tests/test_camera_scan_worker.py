from __future__ import annotations

from typing import Any

import pytest

from gui import camera_devices
from gui.camera_scan_worker import CameraScanWorker


def test_permission_probe_opens_only_avfoundation_and_always_releases(monkeypatch) -> None:
    from gui.camera_devices import request_macos_camera_permission

    opened, released = [], []

    class Capture:
        def read(self):
            pytest.fail("Permission request must not read frames")

        def release(self):
            released.append(True)

    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", lambda index, api: opened.append((index, api)) or Capture())
    request_macos_camera_permission()
    assert opened == [(0, camera_devices.cv2.CAP_AVFOUNDATION)]
    assert released == [True]


@pytest.mark.parametrize("failure", [False, True])
def test_permission_worker_requests_once_without_discovery_and_finishes(monkeypatch, failure) -> None:
    calls, results, errors, finished = [], [], [], []

    def request_permission():
        calls.append(True)
        if failure:
            raise OSError("Permission backend unavailable")

    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", request_permission, raising=False)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: pytest.fail("Permission probe cannot enumerate cameras"))
    worker = CameraScanWorker(permission_only=True)
    worker.succeeded.connect(lambda _worker, devices: results.append(devices))
    worker.failed.connect(lambda _worker, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert calls == [True]
    assert results == ([] if failure else [None])
    assert errors == (["Permission backend unavailable"] if failure else [])
    assert finished == [True]


@pytest.mark.parametrize("failure", [False, True])
def test_scan_stop_suppresses_results_and_finishes(
    monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    worker = CameraScanWorker()
    results: list[Any] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.succeeded.connect(lambda _worker, devices: results.append(devices))
    worker.failed.connect(lambda _worker, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    def enumerate_devices(**kwargs: Any) -> list[tuple[int, str]]:
        assert not kwargs["stop_requested"]()
        worker.request_stop()
        assert kwargs["stop_requested"]()
        if failure:
            raise OSError("cancelled backend")
        return [(0, "Camera 0")]

    monkeypatch.setattr(camera_devices, "list_camera_devices", enumerate_devices)
    worker.run()
    assert results == []
    assert errors == []
    assert finished == [True]


@pytest.mark.parametrize("permission_only", [False, True])
def test_scan_stopped_before_start_does_not_open_camera(
    monkeypatch: pytest.MonkeyPatch, permission_only: bool,
) -> None:
    def unexpected_probe(**_kwargs: Any) -> None:
        pytest.fail("Stopped discovery must not probe camera hardware")

    monkeypatch.setattr(camera_devices, "list_camera_devices", unexpected_probe)
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", unexpected_probe)
    worker = CameraScanWorker(permission_only=permission_only)
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))
    worker.request_stop()
    worker.run()
    assert finished == [True]


def test_discovery_cancellation_releases_current_capture_and_skips_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = False
    opened: list[tuple[int, int]] = []
    released: list[bool] = []

    class Capture:
        def isOpened(self) -> bool:  # noqa: N802
            nonlocal stopped
            stopped = True
            return True

        def read(self) -> None:
            pytest.fail("Cancellation before warmup must skip camera read")

        def release(self) -> None:
            released.append(True)

    def open_capture(index: int, api: int) -> Capture:
        opened.append((index, api))
        return Capture()

    monkeypatch.setattr(camera_devices, "_IS_WIN", False)
    monkeypatch.setattr(camera_devices, "_IS_MAC", True)
    monkeypatch.setattr(camera_devices, "_IS_LINUX", False)
    monkeypatch.setattr(camera_devices, "_build_api_preferences", lambda _prefs: [1200, 0])
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", open_capture)

    assert camera_devices.list_camera_devices(stop_requested=lambda: stopped) == []
    assert opened == [(0, 1200)]
    assert released == [True]
