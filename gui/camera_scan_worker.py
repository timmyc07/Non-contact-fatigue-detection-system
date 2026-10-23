"""Cooperative camera discovery owned by the engine's Qt runtime."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot


class CameraScanWorker(QObject):
    succeeded = Signal(object, object)
    failed = Signal(object, str)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._stop = threading.Event()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stopped:
                return
            from gui.camera_devices import list_camera_devices

            devices = list_camera_devices(
                max_index=20, warmup_read=True, stop_requested=self._stop.is_set
            )
            if not self.stopped:
                self.succeeded.emit(self, devices)
        except Exception as exc:
            if not self.stopped:
                self.failed.emit(self, str(exc))
        finally:
            self.finished.emit()
