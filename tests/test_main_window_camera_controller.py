from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.main_window as main_window_module  # noqa: E402
from gui.engine_controller import CameraDevice  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def camera_window(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> MainWindow:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "camera": {
                    "index": 2,
                    "resolution": "800×600",
                    "fps": "24",
                    "backend": "ffmpeg",
                    "horizontal_flip": False,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MainWindow, "_settings_path", lambda self: settings_path)
    monkeypatch.setattr(MainWindow, "_start_web_server", lambda self: None)
    monkeypatch.setattr(MainWindow, "_register_global_hotkeys", lambda self: None)
    monkeypatch.setattr(
        MainWindow,
        "_start_camera_scan",
        lambda self: self._finish_camera_scan_ui(
            [(0, "Integrated Camera"), (2, "USB Camera")]
        ),
    )
    window = MainWindow(engine_mode=True)
    yield window
    window._desktop_control_timer.stop()
    window.close()


def test_camera_settings_commands_state_and_scan_use_controller(
    camera_window: MainWindow,
) -> None:
    window = camera_window
    snapshot = window._engine_controller.camera_snapshot()
    assert snapshot.selected_index == 2
    assert snapshot.resolution == "800×600"
    assert snapshot.fps == "24"
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
        {"resolution": "1280×800", "fps": 60, "horizontal_flip": True},
    )
    window._handle_desktop_command("camera.select", {"index": 0})
    configured = window._engine_controller.camera_snapshot()
    assert configured.selected_index == 0
    assert configured.resolution == "1280×800"
    assert configured.fps == "60"
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
        "fps": "60",
        "backend": "ffmpeg",
        "horizontal_flip": True,
    }

    window._finish_camera_scan_ui([(4, "Capture Card")])
    refreshed = window._engine_controller.camera_snapshot()
    assert refreshed.selected_index == 4
    assert refreshed.devices == (CameraDevice(4, "[4] Capture Card"),)


def test_scan_adapter_keeps_unavailable_settings_preference(
    camera_window: MainWindow,
) -> None:
    window = camera_window
    window._engine_controller.restore_camera(9)
    window._sync_camera_widgets()
    assert window.selected_camera_index == 2

    window._finish_camera_scan_ui([(2, "USB Camera"), (9, "Later Camera")])

    assert window.selected_camera_index == 9


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
    camera_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = camera_window
    window._finish_camera_scan_ui([(7, "USB Camera")])
    window._handle_desktop_command(
        "camera.configure",
        {
            "resolution": "1920×1080（1080p）",
            "fps": "60",
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
                "target_fps": 60,
                "backend": "ffmpeg",
                "horizontal_flip": False,
            },
        )
    ]
