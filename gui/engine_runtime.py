"""Qt adapter lifetime owner for the headless desktop engine."""

from __future__ import annotations

from collections.abc import Callable
import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from shiboken6 import delete as delete_qobject


AdapterConnect = Callable[[object], None]
ThreadFactory = Callable[[QObject], QThread]
logger = logging.getLogger(__name__)


class EngineRuntime(QObject):
    """Own engine adapter threads and workers independently of MainWindow."""

    adapter_released = Signal(str, object)
    _adapter_finished = Signal(str, object)

    def __init__(
        self,
        parent: QObject,
        *,
        thread_factory: ThreadFactory = QThread,
    ) -> None:
        super().__init__(parent)
        self._thread_factory = thread_factory
        self._adapters: dict[str, tuple[object, QThread]] = {}
        self._finished_pending: dict[str, object] = {}
        self._finished_join_scheduled = False
        self._adapter_finished.connect(self._on_adapter_finished)

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
        thread.finished.connect(getattr(worker, "deleteLater"))

        self._adapters[kind] = (worker, thread)
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
        getattr(worker, "request_stop")()
        return True

    def join_adapter(self, kind: str, timeout_ms: int) -> bool:
        """Quit and join one adapter while retaining ownership on timeout."""
        session = self._adapters.get(kind)
        if session is None:
            return True
        _worker, thread = session
        thread.quit()
        if thread.wait(timeout_ms) is False:
            logger.warning(
                "Engine adapter stop timed out after %d ms: %s",
                timeout_ms,
                kind,
            )
            return False
        self._release_joined_adapter(kind, thread)
        return True

    def stop_adapter(self, kind: str, timeout_ms: int) -> bool:
        """Request cooperative stop, then join the adapter thread."""
        if not self.request_adapter_stop(kind):
            return True
        return self.join_adapter(kind, timeout_ms)

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
