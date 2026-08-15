from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QThread


_WM_HOTKEY = 0x0312
_WINDOWS_MESSAGE_TYPES = {
    b"windows_dispatcher_MSG",
    b"windows_generic_MSG",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HotkeyRegistrationFailure:
    hotkey_id: int
    code: int
    reason: str


@dataclass(frozen=True)
class HotkeyUnregistrationFailure:
    hotkey_id: int
    code: int
    reason: str = "unregistration_failed"


class GlobalHotkeyRuntime(QAbstractNativeEventFilter):
    """Register Windows thread hotkeys without requiring a native window."""

    def __init__(
        self,
        dispatch: Callable[[int], None],
        *,
        supported: bool | None = None,
        application: Any | None = None,
        user32: Any | None = None,
        get_last_error: Callable[[], int] | None = None,
    ) -> None:
        super().__init__()
        self._dispatch = dispatch
        self._supported = sys.platform.startswith("win") if supported is None else supported
        self._application = application
        self._user32 = user32
        default_get_last_error = cast(
            Callable[[], int],
            getattr(ctypes, "get_last_error", lambda: 0),
        )
        self._get_last_error = get_last_error or default_get_last_error
        self._installed_on: Any | None = None
        self._registered_ids: set[int] = set()

    @property
    def supported(self) -> bool:
        return self._supported

    def register(
        self,
        bindings: Mapping[int, tuple[int, int]],
    ) -> tuple[HotkeyRegistrationFailure, ...]:
        cleanup_failures = self.unregister()
        if cleanup_failures:
            return tuple(
                HotkeyRegistrationFailure(
                    hotkey_id=failure.hotkey_id,
                    code=failure.code,
                    reason=failure.reason,
                )
                for failure in cleanup_failures
            )
        if not self._supported or not bindings:
            return ()

        application = self._application or QCoreApplication.instance()
        if application is None:
            raise RuntimeError("Qt application is required for global hotkeys")
        self._require_application_thread(application)
        user32 = self._resolve_user32()
        application.installNativeEventFilter(self)
        self._installed_on = application

        failures: list[HotkeyRegistrationFailure] = []
        try:
            for hotkey_id, (modifiers, key) in bindings.items():
                if user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                    self._registered_ids.add(hotkey_id)
                    continue
                code = int(self._get_last_error())
                failures.append(
                    HotkeyRegistrationFailure(
                        hotkey_id=hotkey_id,
                        code=code,
                        reason=(
                            "already_registered"
                            if code == 1409
                            else "registration_failed"
                        ),
                    )
                )
        except Exception:
            rollback_failures = self.unregister()
            if rollback_failures:
                logger.error(
                    "Global hotkey registration rollback failed: %s",
                    rollback_failures,
                )
            raise
        self._remove_filter_if_idle()
        return tuple(failures)

    def unregister(self) -> tuple[HotkeyUnregistrationFailure, ...]:
        failures: list[HotkeyUnregistrationFailure] = []
        if self._supported and self._registered_ids:
            application = self._installed_on or self._application or QCoreApplication.instance()
            if application is not None:
                self._require_application_thread(application)
            user32 = self._resolve_user32()
            for hotkey_id in sorted(self._registered_ids):
                if user32.UnregisterHotKey(None, hotkey_id):
                    self._registered_ids.remove(hotkey_id)
                    continue
                failures.append(
                    HotkeyUnregistrationFailure(
                        hotkey_id=hotkey_id,
                        code=int(self._get_last_error()),
                    )
                )
        self._remove_filter_if_idle()
        return tuple(failures)

    def nativeEventFilter(self, event_type: object, message: int) -> tuple[bool, int]:  # noqa: N802
        if bytes(cast(Any, event_type)) not in _WINDOWS_MESSAGE_TYPES:
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        hotkey_id = int(msg.wParam)
        if msg.message != _WM_HOTKEY or hotkey_id not in self._registered_ids:
            return False, 0
        try:
            self._dispatch(hotkey_id)
        except Exception:
            logger.exception("Global hotkey callback failed: id=%s", hotkey_id)
        return True, 0

    def _resolve_user32(self) -> Any:
        if self._user32 is None:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        return self._user32

    def _remove_filter_if_idle(self) -> None:
        if self._installed_on is not None and not self._registered_ids:
            self._installed_on.removeNativeEventFilter(self)
            self._installed_on = None

    @staticmethod
    def _require_application_thread(application: Any) -> None:
        application_thread = getattr(application, "thread", None)
        if callable(application_thread) and QThread.currentThread() != application_thread():
            raise RuntimeError("Global hotkeys must be managed on the Qt application thread")
