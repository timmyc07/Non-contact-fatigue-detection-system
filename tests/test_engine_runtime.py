from __future__ import annotations

import os
from typing import Callable

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gui.engine_runtime import EngineRuntime  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class _FakeThread:
    def __init__(self, events: list[str], wait_result: bool = True) -> None:
        self.events = events
        self.wait_result = wait_result
        self.started = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self) -> None:
        self.events.append("thread.start")
        self.started.emit()

    def quit(self) -> None:
        self.events.append("thread.quit")

    def wait(self, timeout_ms: int) -> bool:
        self.events.append(f"thread.wait:{timeout_ms}")
        return self.wait_result

    def deleteLater(self) -> None:
        self.events.append("thread.delete")


class _FakeWorker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.finished = _FakeSignal()

    def moveToThread(self, _thread: object) -> None:
        self.events.append("worker.move")

    def run(self) -> None:
        self.events.append("worker.run")

    def request_stop(self) -> None:
        self.events.append("worker.stop")

    def deleteLater(self) -> None:
        self.events.append("worker.delete")


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


def test_start_wires_worker_before_thread_start_and_releases_on_finish(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    thread = _FakeThread(events)
    worker = _FakeWorker(events)
    thread_parents: list[object] = []

    def create_thread(parent: object) -> _FakeThread:
        thread_parents.append(parent)
        return thread

    runtime = EngineRuntime(qt_app, thread_factory=create_thread)  # type: ignore[arg-type]
    releases: list[tuple[str, object]] = []
    runtime.adapter_released.connect(lambda kind, released: releases.append((kind, released)))

    runtime.start_adapter(
        "camera", worker, connect=lambda _worker: events.append("specific.connect")
    )

    assert runtime.parent() is qt_app
    assert thread_parents == [runtime]
    assert events[:4] == ["specific.connect", "worker.move", "thread.start", "worker.run"]
    assert runtime.worker("camera") is worker
    assert runtime.thread("camera") is thread

    thread.finished.emit()

    assert runtime.worker("camera") is None
    assert runtime.thread("camera") is None
    assert releases == [("camera", thread)]
    assert events[-2:] == ["thread.delete", "worker.delete"]


def test_stop_timeout_keeps_ownership_until_the_same_thread_finishes(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    thread = _FakeThread(events, wait_result=False)
    worker = _FakeWorker(events)
    runtime = EngineRuntime(qt_app, thread_factory=lambda _parent: thread)

    runtime.start_adapter("combined", worker)

    assert runtime.stop_adapter("combined", 5000) is False
    assert runtime.worker("combined") is worker
    assert runtime.thread("combined") is thread
    assert events[-3:] == ["worker.stop", "thread.quit", "thread.wait:5000"]

    thread.finished.emit()

    assert runtime.all_stopped() is False
    assert "thread.delete" not in events

    thread.wait_result = True
    QTest.qWait(25)
    qt_app.processEvents()

    assert runtime.all_stopped() is True


def test_stale_finish_cannot_release_a_new_adapter_session(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    first = _FakeThread(events)
    second = _FakeThread(events)
    threads = iter((first, second))
    runtime = EngineRuntime(qt_app, thread_factory=lambda _parent: next(threads))

    first_worker = _FakeWorker(events)
    runtime.start_adapter("rppg", first_worker)
    assert runtime.release_adapter("rppg", first) is True

    second_worker = _FakeWorker(events)
    runtime.start_adapter("rppg", second_worker)

    assert runtime.release_adapter("rppg", first) is False
    assert runtime.worker("rppg") is second_worker
    assert runtime.thread("rppg") is second


def test_connect_failure_does_not_create_a_partial_thread_session(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    created: list[object] = []

    def create_thread(_parent: object) -> _FakeThread:
        created.append(True)
        return _FakeThread(events)

    runtime = EngineRuntime(qt_app, thread_factory=create_thread)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="connect failed"):
        runtime.start_adapter(
            "fatigue",
            _FakeWorker(events),
            connect=lambda _worker: (_ for _ in ()).throw(
                RuntimeError("connect failed")
            ),
        )

    assert created == []
    assert runtime.all_stopped() is True
