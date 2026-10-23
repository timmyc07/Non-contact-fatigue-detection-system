from __future__ import annotations

import os
import threading
from typing import Callable

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Qt, Signal  # noqa: E402
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from gui.alarm_config import AlarmConfig  # noqa: E402
from gui.alarm_player import QtAlarmPlaybackBackend  # noqa: E402
from gui.engine_runtime import EngineRuntime  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class _FakeTimer:
    def __init__(self, parent: object, events: list[str]) -> None:
        self.parent = parent
        self.events = events
        self.timeout = _FakeSignal()
        self.interval_ms: int | None = None
        self.single_shot = False
        self.active = False

    def setInterval(self, interval_ms: int) -> None:  # noqa: N802
        self.interval_ms = interval_ms
        self.events.append(f"timer.interval:{interval_ms}")

    def setSingleShot(self, single_shot: bool) -> None:  # noqa: N802
        self.single_shot = single_shot
        self.events.append(f"timer.single:{single_shot}")

    def start(self) -> None:
        self.active = True
        self.events.append("timer.start")

    def stop(self) -> None:
        self.active = False
        self.events.append("timer.stop")

    def isActive(self) -> bool:  # noqa: N802
        return self.active

    def deleteLater(self) -> None:
        self.events.append("timer.delete")


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

    def wait(self, timeout_ms: int | None = None) -> bool:
        self.events.append(f"thread.wait:{timeout_ms}")
        return self.wait_result

    def deleteLater(self) -> None:
        self.events.append("thread.delete")


class _FailingStartThread(_FakeThread):
    def start(self) -> None:
        self.events.append("thread.start")
        raise RuntimeError("thread start failed")


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


class _QtWorker(QObject):
    finished = Signal()

    def run(self) -> None:
        pass

    def request_stop(self) -> None:
        pass


@pytest.mark.parametrize("process_events", [False, True])
def test_finished_worker_is_destroyed_on_owner_only_after_join(
    qt_app: QApplication, process_events: bool,
) -> None:
    entered, stopping = threading.Event(), threading.Event()
    destroyed_on, lifecycle = [], []
    owner_thread_id = threading.get_ident()

    class Worker(QObject):
        finished = Signal()

        def run(self) -> None:
            entered.set()
            stopping.wait()
            self.finished.emit()

        def request_stop(self) -> None:
            stopping.set()

    worker = Worker()
    worker.destroyed.connect(
        lambda: (destroyed_on.append(threading.get_ident()), lifecycle.append("destroyed")),
        Qt.ConnectionType.DirectConnection,
    )
    runtime = EngineRuntime(qt_app)
    runtime.adapter_released.connect(lambda *_: lifecycle.append("released"))
    thread = runtime.start_adapter("camera_scan", worker)
    try:
        assert entered.wait(2)
        runtime.request_adapter_stop("camera_scan")
        thread.quit()
        if process_events:
            for _ in range(200):
                if runtime.all_stopped():
                    break
                QTest.qWait(5)
        else:
            assert thread.wait(2000)
            assert isValid(worker)
            assert runtime.join_adapter("camera_scan", 0)
        assert runtime.all_stopped()
        assert destroyed_on == [owner_thread_id]
        assert lifecycle == ["destroyed", "released"]
        assert not isValid(worker)
    finally:
        stopping.set()
        if runtime.worker("camera_scan") is not None:
            runtime.stop_adapter("camera_scan", None)


def test_close_adapters_joins_real_worker_without_main_event_loop(qt_app: QApplication) -> None:
    entered = threading.Event()
    stopping = threading.Event()
    drained = threading.Event()

    class Worker(QObject):
        finished = Signal()

        def run(self) -> None:
            entered.set()
            stopping.wait()
            drained.set()
            self.finished.emit()

        def request_stop(self) -> None:
            stopping.set()

    runtime = EngineRuntime(qt_app)
    thread = runtime.start_adapter("replay", Worker())
    try:
        assert entered.wait(2)
        assert runtime.close_adapters() is True
        assert drained.is_set()
        assert runtime.all_stopped() is True
    finally:
        stopping.set()
        thread.quit()
        thread.wait(2000)


def test_close_adapters_continues_after_one_stop_failure(qt_app: QApplication) -> None:
    events: list[str] = []
    threads = []

    def make_thread(_parent):
        thread = _FakeThread(events)
        threads.append(thread)
        return thread

    runtime = EngineRuntime(qt_app, thread_factory=make_thread)
    broken = _FakeWorker(events)
    broken.request_stop = lambda: (_ for _ in ()).throw(OSError("stop failed"))
    runtime.start_adapter("camera", broken)
    runtime.start_adapter("video", _FakeWorker(events))

    assert runtime.close_adapters() is False
    assert runtime.worker("camera") is broken
    assert runtime.worker("video") is None
    runtime.release_adapter("camera", threads[0])


class _FakeAlarmController:
    def __init__(self, config: AlarmConfig) -> None:
        self.config = config
        self.configs: list[AlarmConfig] = []
        self.metrics: list[object] = []
        self.previews: list[tuple[str, AlarmConfig | None]] = []
        self.close_calls = 0

    def set_config(self, config: AlarmConfig) -> None:
        self.config = config
        self.configs.append(config)

    def on_metrics(self, metrics: object) -> None:
        self.metrics.append(metrics)

    def preview_scenario(
        self,
        scenario: str,
        *,
        config: AlarmConfig | None = None,
    ) -> str | None:
        self.previews.append((scenario, config))
        return "file"

    def close(self) -> None:
        self.close_calls += 1


class _FailingQThread(QThread):
    def start(self, *args: object) -> None:
        raise RuntimeError("thread start failed")


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


def test_runtime_owns_and_routes_alarm_controller(qt_app: QApplication) -> None:
    created: list[tuple[AlarmConfig, object, _FakeAlarmController]] = []

    def create_alarm(
        config: AlarmConfig,
        parent: object,
    ) -> _FakeAlarmController:
        controller = _FakeAlarmController(config)
        created.append((config, parent, controller))
        return controller

    runtime = EngineRuntime(qt_app, alarm_controller_factory=create_alarm)  # type: ignore[arg-type]
    initial = AlarmConfig.defaults()

    controller = runtime.initialize_alarm(initial)

    assert created == [(initial, runtime, controller)]
    assert runtime.alarm_controller is controller

    updated = AlarmConfig.defaults()
    updated.volume = 25
    runtime.configure_alarm(updated)
    metrics = object()
    runtime.handle_alarm_metrics(metrics)

    assert runtime.preview_alarm("critical", config=updated) == "file"
    assert controller.configs == [updated]
    assert controller.metrics == [metrics]
    assert controller.previews == [("critical", updated)]


def test_runtime_is_qt_multimedia_parent(qt_app: QApplication) -> None:
    runtime = EngineRuntime(qt_app)

    runtime.initialize_alarm(AlarmConfig.defaults())

    backends = runtime.findChildren(QtAlarmPlaybackBackend)
    assert len(backends) == 1
    assert backends[0].parent() is runtime
    assert len(backends[0].findChildren(QMediaPlayer)) == 1
    assert len(backends[0].findChildren(QAudioOutput)) == 1
    runtime.close_alarm()


def test_runtime_alarm_close_releases_first_and_is_idempotent(
    qt_app: QApplication,
) -> None:
    controller = _FakeAlarmController(AlarmConfig.defaults())
    runtime = EngineRuntime(
        qt_app,
        alarm_controller_factory=lambda _config, _parent: controller,
    )
    runtime.initialize_alarm(controller.config)

    assert runtime.close_alarm() is True
    assert runtime.alarm_controller is None
    assert controller.close_calls == 1

    late_metrics = object()
    runtime.handle_alarm_metrics(late_metrics)
    assert runtime.preview_alarm("drowsy") is None
    assert runtime.close_alarm() is False
    assert controller.metrics == []
    assert controller.close_calls == 1


def test_runtime_alarm_close_is_best_effort(qt_app: QApplication) -> None:
    controller = _FakeAlarmController(AlarmConfig.defaults())

    def fail_close() -> None:
        controller.close_calls += 1
        raise RuntimeError("close failed")

    controller.close = fail_close  # type: ignore[method-assign]
    runtime = EngineRuntime(
        qt_app,
        alarm_controller_factory=lambda _config, _parent: controller,
    )
    runtime.initialize_alarm(controller.config)

    assert runtime.close_alarm() is True
    assert runtime.alarm_controller is None
    assert controller.close_calls == 1


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


def test_request_stop_can_defer_join_until_replay_finishes(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    thread = _FakeThread(events)
    worker = _FakeWorker(events)
    runtime = EngineRuntime(qt_app, thread_factory=lambda _parent: thread)

    runtime.start_adapter("replay", worker)

    assert runtime.request_adapter_stop("replay") is True
    assert runtime.worker("replay") is worker
    assert runtime.thread("replay") is thread
    assert events[-1:] == ["worker.stop"]
    assert "thread.quit" not in events
    assert not any(event.startswith("thread.wait:") for event in events)

    thread.finished.emit()

    assert runtime.all_stopped() is True


def test_stopping_and_obsolete_worker_events_are_rejected(qt_app: QApplication) -> None:
    events = []
    runtime = EngineRuntime(qt_app, thread_factory=lambda _parent: _FakeThread(events))
    previous, current = _FakeWorker(events), _FakeWorker(events)
    runtime.start_adapter("fatigue", previous)
    assert runtime.accepts_worker_event("fatigue", previous)
    assert not runtime.accepts_worker_event("fatigue", current)
    runtime.request_adapter_stop("fatigue")
    assert not runtime.accepts_worker_event("fatigue", previous)
    runtime.release_adapter("fatigue")
    runtime.start_adapter("fatigue", current)
    assert runtime.accepts_worker_event("fatigue", current)
    assert not runtime.accepts_worker_event("fatigue", previous)
    runtime.close_adapters()


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


def test_thread_start_failure_does_not_leave_partial_ownership(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    thread = _FailingStartThread(events)
    runtime = EngineRuntime(qt_app, thread_factory=lambda _parent: thread)

    with pytest.raises(RuntimeError, match="thread start failed"):
        runtime.start_adapter("replay", _FakeWorker(events))

    assert runtime.worker("replay") is None
    assert runtime.thread("replay") is None
    assert runtime.all_stopped() is True
    assert events[-2:] == ["worker.delete", "thread.delete"]


def test_thread_start_failure_disposes_real_qt_worker_and_thread(
    qt_app: QApplication,
) -> None:
    created: list[_FailingQThread] = []

    def create_thread(parent: QObject) -> _FailingQThread:
        thread = _FailingQThread(parent)
        created.append(thread)
        return thread

    worker = _QtWorker()
    runtime = EngineRuntime(qt_app, thread_factory=create_thread)

    with pytest.raises(RuntimeError, match="thread start failed"):
        runtime.start_adapter("replay", worker)

    assert isValid(worker) is False
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert isValid(created[0]) is False
    assert runtime.all_stopped() is True


def test_runtime_owns_periodic_timer_until_cancelled(qt_app: QApplication) -> None:
    events: list[str] = []
    timers: list[_FakeTimer] = []

    def create_timer(parent: object) -> _FakeTimer:
        timer = _FakeTimer(parent, events)
        timers.append(timer)
        return timer

    runtime = EngineRuntime(qt_app, timer_factory=create_timer)  # type: ignore[arg-type]
    ticks: list[str] = []

    timer = runtime.start_periodic_timer(
        "command_drain",
        20,
        lambda: ticks.append("tick"),
    )

    assert timer is timers[0]
    assert timer.parent is runtime
    assert timer.interval_ms == 20
    assert timer.single_shot is False
    assert runtime.timer_active("command_drain") is True

    timer.timeout.emit()
    assert ticks == ["tick"]

    assert runtime.cancel_timer("command_drain") is True
    assert runtime.timer_active("command_drain") is False
    assert events[-2:] == ["timer.stop", "timer.delete"]
    assert runtime.cancel_timer("command_drain") is False


def test_named_single_shot_replaces_stale_timer_without_firing_it(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    timers: list[_FakeTimer] = []

    def create_timer(parent: object) -> _FakeTimer:
        timer = _FakeTimer(parent, events)
        timers.append(timer)
        return timer

    runtime = EngineRuntime(qt_app, timer_factory=create_timer)  # type: ignore[arg-type]
    fired: list[str] = []
    cancelled_from_callback: list[bool] = []

    def fire_second() -> None:
        cancelled_from_callback.append(runtime.cancel_timer("auto_capture"))
        fired.append("second")

    first = runtime.schedule_timer("auto_capture", 1000, lambda: fired.append("first"))
    second = runtime.schedule_timer("auto_capture", 2000, fire_second)

    assert first is timers[0]
    assert second is timers[1]
    assert first.active is False
    assert second.active is True
    assert second.single_shot is True
    assert second.interval_ms == 2000

    first.timeout.emit()
    assert fired == []
    assert runtime.timer_active("auto_capture") is True

    second.timeout.emit()
    assert fired == ["second"]
    assert cancelled_from_callback == [True]
    assert runtime.timer_active("auto_capture") is False
    assert events[-1] == "timer.delete"


def test_runtime_defer_keeps_each_callback_owned_until_timeout(
    qt_app: QApplication,
) -> None:
    events: list[str] = []
    timers: list[_FakeTimer] = []

    def create_timer(parent: object) -> _FakeTimer:
        timer = _FakeTimer(parent, events)
        timers.append(timer)
        return timer

    runtime = EngineRuntime(qt_app, timer_factory=create_timer)  # type: ignore[arg-type]
    fired: list[str] = []

    first = runtime.defer(0, lambda: fired.append("first"))
    second = runtime.defer(100, lambda: fired.append("second"))

    first.timeout.emit()
    second.timeout.emit()

    assert fired == ["first", "second"]
    assert timers == [first, second]
    assert events.count("timer.delete") == 2


def test_real_qt_single_shot_callback_can_cancel_its_runtime_owner(
    qt_app: QApplication,
) -> None:
    runtime = EngineRuntime(qt_app)
    cancelled: list[bool] = []

    runtime.schedule_timer(
        "auto_capture",
        0,
        lambda: cancelled.append(runtime.cancel_timer("auto_capture")),
    )
    QTest.qWait(10)
    qt_app.processEvents()

    assert cancelled == [True]
    assert runtime.timer_active("auto_capture") is False
