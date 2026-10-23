"""Qt adapter lifetime owner for the headless desktop engine."""

from __future__ import annotations

from collections.abc import Callable
import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from shiboken6 import delete as delete_qobject

from gui.alarm_config import AlarmConfig
from gui.alarm_player import FatigueAlarmController


AdapterConnect = Callable[[object], None]
AlarmControllerFactory = Callable[[AlarmConfig, QObject], FatigueAlarmController]
ThreadFactory = Callable[[QObject], QThread]
TimerCallback = Callable[[], None]
TimerFactory = Callable[[QObject], QTimer]
logger = logging.getLogger(__name__)


class EngineRuntime(QObject):
    """Own engine Qt adapters and timers independently of the application adapter."""

    adapter_released = Signal(str, object)
    _adapter_finished = Signal(str, object)

    def __init__(
        self,
        parent: QObject,
        *,
        thread_factory: ThreadFactory = QThread,
        timer_factory: TimerFactory = QTimer,
        alarm_controller_factory: AlarmControllerFactory = FatigueAlarmController,
    ) -> None:
        super().__init__(parent)
        self._thread_factory = thread_factory
        self._timer_factory = timer_factory
        self._alarm_controller_factory = alarm_controller_factory
        self._alarm_controller: FatigueAlarmController | None = None
        self._adapters: dict[str, tuple[object, QThread]] = {}
        self._stopping_adapters: set[str] = set()
        self._finished_pending: dict[str, object] = {}
        self._finished_join_scheduled = False
        self._timers: dict[str, QTimer] = {}
        self._deferred_timers: list[QTimer] = []
        self._adapter_finished.connect(self._on_adapter_finished)

    @property
    def alarm_controller(self) -> FatigueAlarmController | None:
        return self._alarm_controller

    def initialize_alarm(self, config: AlarmConfig) -> FatigueAlarmController:
        """Create the application-owned alarm controller once settings are loaded."""
        if self._alarm_controller is not None:
            raise RuntimeError("Alarm controller is already initialized")
        controller = self._alarm_controller_factory(config, self)
        self._alarm_controller = controller
        return controller

    def replace_alarm_controller(self, controller: FatigueAlarmController) -> None:
        """Replace the owned controller while retaining one lifecycle boundary."""
        if controller is self._alarm_controller:
            return
        self.close_alarm()
        self._alarm_controller = controller

    def configure_alarm(self, config: AlarmConfig) -> None:
        controller = self._alarm_controller
        if controller is None:
            raise RuntimeError("Alarm controller is not initialized")
        controller.set_config(config)

    def preview_alarm(
        self,
        scenario: str,
        *,
        config: AlarmConfig | None = None,
    ) -> str | None:
        controller = self._alarm_controller
        if controller is None:
            return None
        return controller.preview_scenario(scenario, config=config)

    def handle_alarm_metrics(self, metrics: object) -> None:
        controller = self._alarm_controller
        if controller is not None:
            controller.on_metrics(metrics)

    def close_alarm(self) -> bool:
        controller = self._alarm_controller
        if controller is None:
            return False
        self._alarm_controller = None
        try:
            controller.close()
        except Exception:
            logger.exception("Alarm controller cleanup failed")
        return True

    def start_periodic_timer(
        self,
        kind: str,
        interval_ms: int,
        callback: TimerCallback,
    ) -> QTimer:
        """Create and start one runtime-owned periodic timer."""
        self.cancel_timer(kind)
        timer = self._timer_factory(self)
        timer.setInterval(interval_ms)
        timer.timeout.connect(callback)
        self._timers[kind] = timer
        try:
            timer.start()
        except Exception:
            if self._timers.get(kind) is timer:
                del self._timers[kind]
            self._dispose_timer(timer)
            raise
        return timer

    def schedule_timer(
        self,
        kind: str,
        delay_ms: int,
        callback: TimerCallback,
    ) -> QTimer:
        """Replace one named runtime-owned single-shot timer."""
        self.cancel_timer(kind)
        timer = self._timer_factory(self)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)

        def on_timeout() -> None:
            if self._timers.get(kind) is not timer:
                return
            try:
                callback()
            finally:
                if self._timers.get(kind) is timer:
                    del self._timers[kind]
                    self._dispose_timer(timer)

        timer.timeout.connect(on_timeout)
        self._timers[kind] = timer
        try:
            timer.start()
        except Exception:
            if self._timers.get(kind) is timer:
                del self._timers[kind]
            self._dispose_timer(timer)
            raise
        return timer

    def cancel_timer(self, kind: str) -> bool:
        """Cancel and release one named runtime-owned timer."""
        timer = self._timers.pop(kind, None)
        if timer is None:
            return False
        self._dispose_timer(timer)
        return True

    def timer_active(self, kind: str) -> bool:
        timer = self._timers.get(kind)
        return timer is not None and timer.isActive()

    def defer(self, delay_ms: int, callback: TimerCallback) -> QTimer:
        """Keep an anonymous single-shot callback alive until it fires."""
        timer = self._timer_factory(self)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)

        def on_timeout() -> None:
            if not self._release_deferred_timer(timer):
                return
            self._dispose_timer(timer)
            callback()

        timer.timeout.connect(on_timeout)
        self._deferred_timers.append(timer)
        try:
            timer.start()
        except Exception:
            self._release_deferred_timer(timer)
            self._dispose_timer(timer)
            raise
        return timer

    @staticmethod
    def _dispose_timer(timer: QTimer) -> None:
        timer.stop()
        timer.deleteLater()

    def _release_deferred_timer(self, timer: QTimer) -> bool:
        for index, current in enumerate(self._deferred_timers):
            if current is timer:
                del self._deferred_timers[index]
                return True
        return False

    def start_adapter(
        self,
        kind: str,
        worker: object,
        *,
        connect: AdapterConnect | None = None,
    ) -> QThread:
        """Move, wire, and start one worker without exposing its ownership."""
        if kind in self._adapters:
            logger.error("Engine adapter is still cleaning up: %s", kind)
            raise RuntimeError(f"Adapter '{kind}' is still cleaning up")

        try:
            if connect is not None:
                connect(worker)
        except Exception:
            logger.exception("Engine adapter signal wiring failed: %s", kind)
            raise

        thread = self._thread_factory(self)
        move_to_thread = getattr(worker, "moveToThread")
        thread.started.connect(getattr(worker, "run"))
        getattr(worker, "finished").connect(thread.quit)
        thread.finished.connect(
            lambda adapter_kind=kind, current=thread: self._adapter_finished.emit(
                adapter_kind,
                current,
            )
        )
        if not isinstance(worker, QObject):
            thread.finished.connect(getattr(worker, "deleteLater"))

        self._adapters[kind] = (worker, thread)
        self._stopping_adapters.discard(kind)
        try:
            move_to_thread(thread)
            thread.start()
        except Exception:
            current = self._adapters.get(kind)
            if current is not None and current[1] is thread:
                del self._adapters[kind]
            if isinstance(worker, QObject):
                delete_qobject(worker)
            else:
                getattr(worker, "deleteLater")()
            thread.deleteLater()
            logger.exception("Engine adapter start failed: %s", kind)
            raise
        return thread

    def request_adapter_stop(self, kind: str) -> bool:
        """Request cooperative stop without forcing or joining the adapter thread."""
        session = self._adapters.get(kind)
        if session is None:
            return False
        worker, _thread = session
        self._stopping_adapters.add(kind)
        getattr(worker, "request_stop")()
        return True

    def accepts_worker_event(self, kind: str, sender: object) -> bool:
        """已要求停止或被新 session 取代的 worker 不得再送入業務 callback。"""
        worker = self.worker(kind)
        return worker is not None and worker is sender and kind not in self._stopping_adapters

    def join_adapter(self, kind: str, timeout_ms: int | None) -> bool:
        """Quit and join one adapter while retaining ownership on timeout."""
        session = self._adapters.get(kind)
        if session is None:
            return True
        _worker, thread = session
        thread.quit()
        joined = thread.wait() if timeout_ms is None else thread.wait(timeout_ms)
        if joined is False:
            if timeout_ms is not None and timeout_ms > 0:
                logger.warning(
                    "Engine adapter stop timed out after %d ms: %s",
                    timeout_ms,
                    kind,
                )
            return False
        self._release_joined_adapter(kind, thread)
        return True

    def stop_adapter(self, kind: str, timeout_ms: int | None) -> bool:
        """Request cooperative stop, then join the adapter thread."""
        if not self.request_adapter_stop(kind):
            return True
        return self.join_adapter(kind, timeout_ms)

    def close_adapters(self) -> bool:
        """主事件迴圈已結束時，同步停止及 join 剩餘 adapters。"""
        for kind in tuple(self._adapters):
            try:
                self.stop_adapter(kind, None)
            except Exception:
                logger.exception("Engine adapter final cleanup failed: %s", kind)
        return self.all_stopped()

    def release_adapter(
        self,
        kind: str,
        expected_thread: QThread | object | None = None,
    ) -> bool:
        """Release only the expected session, protecting a newer restart."""
        session = self._adapters.get(kind)
        if session is None:
            return False
        _worker, thread = session
        if expected_thread is not None and thread is not expected_thread:
            return False
        del self._adapters[kind]
        self._stopping_adapters.discard(kind)
        if self._finished_pending.get(kind) is thread:
            del self._finished_pending[kind]
        self.adapter_released.emit(kind, thread)
        return True

    @Slot(str, object)
    def _on_adapter_finished(self, kind: str, thread: object) -> None:
        """Join a finished thread on the runtime thread before releasing ownership."""
        if self.thread(kind) is not thread:
            return
        self._finished_pending[kind] = thread
        self._drain_finished_adapters()

    @Slot()
    def _drain_finished_adapters(self) -> None:
        self._finished_join_scheduled = False
        for kind, thread in tuple(self._finished_pending.items()):
            if self.thread(kind) is not thread:
                del self._finished_pending[kind]
                continue
            if getattr(thread, "wait")(0) is not False:
                self._release_joined_adapter(kind, thread)
        if self._finished_pending and not self._finished_join_scheduled:
            self._finished_join_scheduled = True
            QTimer.singleShot(1, self._drain_finished_adapters)

    def _release_joined_adapter(self, kind: str, thread: object) -> None:
        session = self._adapters.get(kind)
        if session is None or session[1] is not thread:
            return
        if isinstance(session[0], QObject):
            # wait 已保證原線程不再處理事件；主線程析構避免 Qt mutex/GIL 鎖反序。
            delete_qobject(session[0])
        if self.release_adapter(kind, thread):
            getattr(thread, "deleteLater")()

    def worker(self, kind: str) -> object | None:
        session = self._adapters.get(kind)
        return None if session is None else session[0]

    def thread(self, kind: str) -> QThread | None:
        session = self._adapters.get(kind)
        return None if session is None else session[1]

    def all_stopped(self) -> bool:
        return not self._adapters
