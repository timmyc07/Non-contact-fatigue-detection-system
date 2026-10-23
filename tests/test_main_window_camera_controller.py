from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.main_window as main_window_module  # noqa: E402
from gui.engine_controller import CameraDevice  # noqa: E402
from gui.main_window import EngineApplication  # noqa: E402


_START_CAMERA_SCAN = EngineApplication._start_camera_scan


def test_macos_permission_request_is_single_flight_and_grant_resumes_scan(
    camera_window, monkeypatch, qt_app,
):
    from gui import camera_devices
    from gui.desktop_control import BusyError

    window = camera_window
    requested, probes = [], []
    status = [Qt.PermissionStatus.Undetermined]
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: status[0])
    monkeypatch.setattr(qt_app, "requestPermission", lambda *_: pytest.fail("Qt requestPermission rejects source and frozen mainBundle metadata"))
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: requested.append(QThread.currentThread()), raising=False)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: probes.append(True) or [(9, "Camera")])
    _START_CAMERA_SCAN(window)
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    assert len(requested) == 1
    assert requested[0] != QThread.currentThread()
    assert probes == []
    state = window._desktop_control_state()
    assert state["camera_permission_pending"] is True
    assert state["camera_scanning"] is True
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    _process_until(lambda: bool(heartbeat))
    QTest.qWait(250)
    _START_CAMERA_SCAN(window)
    assert len(requested) == 1
    assert window._engine_runtime.timer_active("camera_permission")
    assert probes == []
    with pytest.raises(BusyError, match="discovery"):
        window._handle_desktop_command("pipeline.set", {"enabled": True})
    with pytest.raises(BusyError, match="discovery"):
        window._handle_desktop_command("auto_capture.set", {"enabled": True})
    window._toggle_pipeline()
    assert not window._engine_controller.pipeline_snapshot().running
    window._on_auto_capture_clicked()
    assert not window._engine_runtime.timer_active("auto_capture")
    status[0] = Qt.PermissionStatus.Granted
    _process_until(lambda: bool(probes) and window._engine_runtime.worker("camera_scan") is None)
    assert probes == [True]
    assert window.selected_camera_index == 9
    assert window._desktop_control_state()["camera_permission_pending"] is False


def test_macos_denied_permission_never_probes_or_requests_again(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    previous = window._engine_controller.camera_snapshot()
    notices = []
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: Qt.PermissionStatus.Denied)
    monkeypatch.setattr(qt_app, "requestPermission", lambda *_: pytest.fail("Denied permission cannot prompt again"))
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: pytest.fail("Denied permission cannot open a camera"))
    monkeypatch.setattr(window, "_publish_desktop_notice", lambda message: notices.append(message))
    _START_CAMERA_SCAN(window)
    _START_CAMERA_SCAN(window)
    assert len(notices) == 1
    assert window._engine_controller.camera_snapshot() == previous
    assert not window._desktop_control_state()["camera_scanning"]


@pytest.mark.parametrize("granted", [False, True])
def test_macos_permission_poll_after_cleanup_never_restarts_camera(camera_window, monkeypatch, qt_app, granted):
    from gui import camera_devices

    window = camera_window
    requested, status = [], [Qt.PermissionStatus.Undetermined]
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: status[0])
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: requested.append(True), raising=False)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: pytest.fail("Late permission callback cannot open a camera"))
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    assert requested == [True]
    assert window.close_runtime()
    assert not window._desktop_control_state()["camera_permission_pending"]
    assert not window._engine_runtime.timer_active("camera_permission")
    status[0] = Qt.PermissionStatus.Granted if granted else Qt.PermissionStatus.Denied
    window._poll_camera_permission()
    assert window._engine_runtime.worker("camera_scan") is None


def test_macos_permission_denial_does_not_repeat_probe(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    requested, notices = [], []
    status = [Qt.PermissionStatus.Undetermined]
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: status[0])
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: requested.append(True), raising=False)
    monkeypatch.setattr(window, "_publish_desktop_notice", notices.append)
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    status[0] = Qt.PermissionStatus.Denied
    _process_until(lambda: not window._camera_permission_pending)
    _START_CAMERA_SCAN(window)
    assert len(requested) == len(notices) == 1
    assert not window._desktop_control_state()["camera_scanning"]
    assert not window._engine_runtime.timer_active("camera_permission")


def test_macos_permission_probe_failure_clears_pending_and_does_not_scan(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: Qt.PermissionStatus.Undetermined)
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: (_ for _ in ()).throw(RuntimeError("permission backend unavailable")), raising=False)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: pytest.fail("Permission probe failure cannot enumerate cameras"))
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    state = window._desktop_control_state()
    assert not state["camera_permission_pending"]
    assert not state["camera_scanning"]
    assert "permission backend unavailable" in state["desktop_notice"]["message"]
    assert not window._engine_runtime.timer_active("camera_permission")


def test_macos_permission_grant_waits_until_probe_adapter_released(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    entered, release = threading.Event(), threading.Event()
    status, probes = [Qt.PermissionStatus.Undetermined], []

    def request_permission():
        entered.set()
        release.wait(2.0)

    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: status[0])
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", request_permission, raising=False)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: probes.append(True) or [(9, "Camera")])
    try:
        _START_CAMERA_SCAN(window)
        _process_until(entered.is_set)
        status[0] = Qt.PermissionStatus.Granted
        window._poll_camera_permission()
        assert window._camera_permission_pending
        assert window._engine_runtime.timer_active("camera_permission")
        assert probes == []
    finally:
        release.set()
        _process_until(lambda: bool(probes) and window._engine_runtime.worker("camera_scan") is None)
    assert probes == [True]
    assert not window._camera_permission_pending


def test_macos_pending_permission_poll_error_clears_pending_once(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    notices, fail_status = [], [False]

    def check_permission(_permission):
        if fail_status[0]:
            raise RuntimeError("permission status unavailable")
        return Qt.PermissionStatus.Undetermined

    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", check_permission)
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: None, raising=False)
    monkeypatch.setattr(window, "_publish_desktop_notice", notices.append)
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    fail_status[0] = True
    window._poll_camera_permission()
    window._poll_camera_permission()
    assert len(notices) == 1
    assert "permission status unavailable" in notices[0]
    assert not window._camera_scan_pending()
    assert not window._engine_runtime.timer_active("camera_permission")


def test_macos_permission_cleanup_is_nonblocking_with_probe_still_owned(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    entered, release = threading.Event(), threading.Event()
    status = [Qt.PermissionStatus.Undetermined]

    def request_permission():
        entered.set()
        release.wait(2.0)

    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: status[0])
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", request_permission)
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: pytest.fail("Shutdown cannot start a camera scan"))
    try:
        _START_CAMERA_SCAN(window)
        _process_until(entered.is_set)
        started = time.perf_counter()
        assert not window._cleanup_runtime()
        assert time.perf_counter() - started < 0.1
        assert window._engine_runtime.worker("camera_scan") is not None
        assert not window._camera_permission_pending
        assert not window._engine_runtime.timer_active("camera_permission")
        status[0] = Qt.PermissionStatus.Granted
        window._poll_camera_permission()
    finally:
        release.set()
        _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    assert window.close_runtime()


def test_macos_initial_permission_status_error_never_probes(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: (_ for _ in ()).throw(RuntimeError("status unavailable")))
    monkeypatch.setattr(camera_devices, "request_macos_camera_permission", lambda: pytest.fail("Unknown permission status cannot open a camera"))
    _START_CAMERA_SCAN(window)
    assert not window._camera_scan_pending()
    assert "status unavailable" in window._desktop_control_state()["desktop_notice"]["message"]


def test_non_macos_discovery_does_not_use_camera_permission_api(camera_window, monkeypatch, qt_app):
    from gui import camera_devices

    window = camera_window
    probes = []
    monkeypatch.setattr(main_window_module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(qt_app, "checkPermission", lambda _: pytest.fail("Only macOS requests camera permission"))
    monkeypatch.setattr(camera_devices, "list_camera_devices", lambda **_: probes.append(True) or [(9, "Camera")])
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
    assert probes == [True]
    assert window.selected_camera_index == 9


def _process_until(condition: Any) -> None:
    deadline = time.monotonic() + 3.0
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert condition()


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def camera_window(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> EngineApplication:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "camera": {
                    "index": 2,
                    "resolution": "800×600",
                    "fps": "60",
                    "backend": "ffmpeg",
                    "horizontal_flip": False,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(EngineApplication, "_settings_path", lambda self: settings_path)
    monkeypatch.setattr(EngineApplication, "_start_web_server", lambda self: None)
    monkeypatch.setattr(EngineApplication, "_register_global_hotkeys", lambda self: None)
    monkeypatch.setattr(
        EngineApplication,
        "_start_camera_scan",
        lambda self: self._finish_camera_scan_ui(
            [(0, "Integrated Camera"), (2, "USB Camera")]
        ),
    )
    window = EngineApplication(engine_mode=True)
    yield window
    window._engine_runtime.cancel_timer("desktop_command")
    window.close_runtime()


def test_camera_settings_commands_state_and_scan_use_controller(
    camera_window: EngineApplication,
) -> None:
    window = camera_window
    snapshot = window._engine_controller.camera_snapshot()
    assert snapshot.selected_index == 2
    assert snapshot.resolution == "800×600"
    assert snapshot.fps == "30"
    assert snapshot.backend == "ffmpeg"
    assert snapshot.horizontal_flip is False

    state = window._handle_desktop_command("state.get", {})
    assert state["selected_camera_index"] == 2
    assert state["resolution"] == "800×600"
    assert state["cameras"] == [
        {"index": 0, "label": "[0] Integrated Camera"},
        {"index": 2, "label": "[2] USB Camera"},
    ]

    window._handle_desktop_command(
        "camera.configure",
        {"resolution": "1280×800", "fps": 30, "horizontal_flip": True},
    )
    window._handle_desktop_command("camera.select", {"index": 0})
    configured = window._engine_controller.camera_snapshot()
    assert configured.selected_index == 0
    assert configured.resolution == "1280×800"
    assert configured.fps == "30"
    assert configured.horizontal_flip is True
    for name in (
        "_cmb_camera",
        "_cmb_resolution",
        "_cmb_fps",
        "_cmb_backend",
        "_chk_horizontal_flip",
        "_lbl_cam_hint",
    ):
        assert name not in window.__dict__

    saved_path = window._save_settings()
    saved_camera = json.loads(saved_path.read_text(encoding="utf-8"))["camera"]
    assert saved_camera == {
        "index": 0,
        "resolution": "1280×800",
        "fps": "30",
        "backend": "ffmpeg",
        "horizontal_flip": True,
    }

    window._finish_camera_scan_ui([(4, "Capture Card")])
    refreshed = window._engine_controller.camera_snapshot()
    assert refreshed.selected_index == 4
    assert refreshed.devices == (CameraDevice(4, "[4] Capture Card"),)


def test_scan_adapter_keeps_unavailable_settings_preference(
    camera_window: EngineApplication,
) -> None:
    window = camera_window
    window._engine_controller.restore_camera(9)
    assert window.selected_camera_index == 2

    window._finish_camera_scan_ui([(2, "USB Camera"), (9, "Later Camera")])

    assert window.selected_camera_index == 9


def test_camera_discovery_keeps_qt_responsive_and_is_single_flight(
    camera_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui import camera_devices
    from gui.desktop_control import BusyError

    window = camera_window
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    calls: list[QThread] = []
    heartbeat: list[bool] = []
    applied_on: list[QThread] = []
    replace = window._engine_controller.replace_cameras

    def enumerate_devices(**_kwargs: Any) -> list[tuple[int, str]]:
        calls.append(QThread.currentThread())
        entered.set()
        release.wait(2.0)
        returned.set()
        return [(9, "Later Camera")]

    def replace_cameras(devices: Any) -> None:
        applied_on.append(QThread.currentThread())
        replace(devices)

    monkeypatch.setattr(camera_devices, "list_camera_devices", enumerate_devices)
    monkeypatch.setattr(window._engine_controller, "replace_cameras", replace_cameras)
    window._engine_controller.restore_camera(9)
    try:
        _START_CAMERA_SCAN(window)
        _process_until(entered.is_set)
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        _process_until(lambda: bool(heartbeat))
        assert not returned.is_set()
        assert len(calls) == 1
        assert calls[0] != QThread.currentThread()
        _START_CAMERA_SCAN(window)
        assert len(calls) == 1
        assert window._desktop_control_state()["camera_scanning"] is True
        with pytest.raises(BusyError, match="discovery"):
            window._handle_desktop_command("pipeline.set", {"enabled": True})
        with pytest.raises(BusyError, match="discovery"):
            window._handle_desktop_command("auto_capture.set", {"enabled": True})
        window._toggle_pipeline()
        assert not window._engine_controller.pipeline_snapshot().running
    finally:
        release.set()
        _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)

    assert applied_on == [QThread.currentThread()]
    assert window.selected_camera_index == 9
    assert window._desktop_control_state()["camera_scanning"] is False


def test_camera_discovery_failure_keeps_previous_devices(
    camera_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui import camera_devices

    window = camera_window
    previous = window._engine_controller.camera_snapshot()

    def fail_scan(**_kwargs: Any) -> list[tuple[int, str]]:
        raise OSError("camera backend unavailable")

    monkeypatch.setattr(camera_devices, "list_camera_devices", fail_scan)
    _START_CAMERA_SCAN(window)
    _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)

    assert window._engine_controller.camera_snapshot() == previous


@pytest.mark.parametrize("ending", ["cancelled", "shutdown"])
def test_camera_discovery_ignores_result_after_stop(
    camera_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    from gui import camera_devices

    window = camera_window
    previous = window._engine_controller.camera_snapshot()
    entered = threading.Event()
    release = threading.Event()

    def enumerate_devices(**_kwargs: Any) -> list[tuple[int, str]]:
        entered.set()
        release.wait(2.0)
        return [(9, "Late Camera")]

    monkeypatch.setattr(camera_devices, "list_camera_devices", enumerate_devices)
    try:
        _START_CAMERA_SCAN(window)
        _process_until(entered.is_set)
        if ending == "cancelled":
            window._engine_runtime.request_adapter_stop("camera_scan")
        else:
            window._runtime_cleanup_in_progress = True
        release.set()
        _process_until(lambda: window._engine_runtime.worker("camera_scan") is None)
        assert window._engine_controller.camera_snapshot() == previous
    finally:
        release.set()
        window._runtime_cleanup_in_progress = False


def test_camera_discovery_ignores_replaced_session_and_live_scan_is_busy(
    camera_window: EngineApplication,
) -> None:
    from gui.camera_scan_worker import CameraScanWorker
    from gui.desktop_control import BusyError

    window = camera_window
    previous = window._engine_controller.camera_snapshot()
    obsolete = CameraScanWorker()
    window._on_camera_scan_succeeded(obsolete, [(9, "Old scan")])
    assert window._engine_controller.camera_snapshot() == previous

    window._engine_controller.start_pipeline()
    try:
        with pytest.raises(BusyError, match="Stop the pipeline"):
            _START_CAMERA_SCAN(window)
    finally:
        window._engine_controller.stop_pipeline()

    window._engine_controller.mark_pipeline_cleanup_pending()
    try:
        with pytest.raises(BusyError, match="cleanup"):
            _START_CAMERA_SCAN(window)
    finally:
        window._engine_controller.finish_pipeline_cleanup()


class _FakeSignal:
    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def connect(self, handler: Any) -> None:
        self.handlers.append(handler)

    def disconnect(self, handler: Any) -> None:
        if handler in self.handlers:
            self.handlers.remove(handler)


class _FakeCameraWorker:
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.created.append((args, kwargs))
        self.camera_info = _FakeSignal()
        self.diagnostic_ready = _FakeSignal()
        self.fps_ready = _FakeSignal()
        self.failed = _FakeSignal()
        self.finished = _FakeSignal()
        self.frame_ready = _FakeSignal()

    def moveToThread(self, thread: Any) -> None:  # noqa: N802
        self.thread = thread

    def run(self) -> None:
        return

    def detach_bgr_queue(self, queue: Any = None) -> None:
        return

    def request_stop(self) -> None:
        return

    def deleteLater(self) -> None:  # noqa: N802
        return


class _FakeThread:
    def __init__(self, parent: Any) -> None:
        self.parent = parent
        self.started = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self) -> None:
        return

    def quit(self) -> None:
        return

    def wait(self, timeout: int) -> bool:
        return True

    def deleteLater(self) -> None:  # noqa: N802
        return


def test_start_camera_worker_uses_controller_start_spec(
    camera_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = camera_window
    window._finish_camera_scan_ui([(7, "USB Camera")])
    window._handle_desktop_command(
        "camera.configure",
        {
            "resolution": "1920×1080（1080p）",
            "fps": "30",
            "backend": "ffmpeg",
            "horizontal_flip": False,
        },
    )
    _FakeCameraWorker.created.clear()
    monkeypatch.setattr(main_window_module, "CameraStreamWorker", _FakeCameraWorker)
    monkeypatch.setattr(main_window_module, "QThread", _FakeThread)

    window._start_camera_worker()

    assert _FakeCameraWorker.created == [
        (
            (7,),
            {
                "width": 1920,
                "height": 1080,
                "target_fps": 30,
                "backend": "ffmpeg",
                "horizontal_flip": False,
            },
        )
    ]
