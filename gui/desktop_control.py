"""Thread-safe command handoff from Flask workers to the Qt GUI thread."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


ControlHandler = Callable[[str, dict[str, Any]], dict[str, Any]]
DESKTOP_CONTROL_API_VERSION = 1


def desktop_dialog_parent(window: Any, *, engine_mode: bool) -> Any | None:
    """Keep engine-mode dialogs independent from the hidden legacy window."""
    if engine_mode or not window.isVisible():
        return None
    return window


@dataclass(slots=True)
class _PendingCommand:
    name: str
    args: dict[str, Any]
    completed: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: Exception | None = None
    cancelled: bool = False


class DesktopCommandBroker:
    """Queue control requests until the owning Qt thread drains them."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = max(float(timeout_seconds), 0.1)
        self._pending: queue.Queue[_PendingCommand] = queue.Queue()

    @property
    def pending_count(self) -> int:
        return self._pending.qsize()

    def submit(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        request = _PendingCommand(name=name, args=dict(args or {}))
        self._pending.put(request)
        if not request.completed.wait(self._timeout_seconds):
            request.cancelled = True
            raise TimeoutError(f"Desktop command timed out: {name}")
        if request.error is not None:
            raise request.error
        return dict(request.result or {})

    def process_pending(self, handler: ControlHandler, *, max_items: int = 16) -> int:
        processed = 0
        while processed < max_items:
            try:
                request = self._pending.get_nowait()
            except queue.Empty:
                break
            try:
                if request.cancelled:
                    continue
                result = handler(request.name, request.args)
                if not isinstance(result, dict):
                    raise TypeError("Desktop control handlers must return a dict")
                request.result = result
            except Exception as exc:  # Propagate the original domain error to Flask.
                request.error = exc
            finally:
                request.completed.set()
                processed += 1
        return processed
