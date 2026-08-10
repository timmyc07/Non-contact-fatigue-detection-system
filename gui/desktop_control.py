"""Thread-safe command handoff from Flask workers to the Qt GUI thread."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


ControlHandler = Callable[[str, dict[str, Any]], dict[str, Any]]
DESKTOP_CONTROL_API_VERSION = 2


class DesktopControlError(Exception):
    """Structured command error that is safe to return to the local client."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        field: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.field = field
        self.path = path

    def to_payload(self) -> dict[str, str]:
        payload = {"code": self.code, "message": str(self)}
        if self.field is not None:
            payload["field"] = self.field
        if self.path is not None:
            payload["path"] = self.path
        return payload


class BusyError(DesktopControlError):
    def __init__(self, message: str) -> None:
        super().__init__("busy", message, status_code=409)


class SettingsWriteError(DesktopControlError, OSError):
    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(
            "settings_write_failed",
            message,
            status_code=409,
            path=path,
        )


class AlarmUnplayableError(DesktopControlError):
    def __init__(self, message: str) -> None:
        super().__init__("alarm_unplayable", message, status_code=400)


class HotkeyApplyError(DesktopControlError):
    def __init__(self, message: str) -> None:
        super().__init__("hotkey_apply_failed", message, status_code=409)


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
