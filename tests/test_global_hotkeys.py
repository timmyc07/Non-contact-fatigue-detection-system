from __future__ import annotations

from ctypes import addressof, wintypes

import pytest
from PySide6.QtCore import QThread

import gui.global_hotkeys as global_hotkeys_module
from gui.global_hotkeys import GlobalHotkeyRuntime


class _FakeApplication:
    def __init__(self) -> None:
        self.installed: list[object] = []
        self.removed: list[object] = []
        self.owner_thread: object = QThread.currentThread()

    def thread(self) -> object:
        return self.owner_thread

    def installNativeEventFilter(self, event_filter: object) -> None:  # noqa: N802
        self.installed.append(event_filter)

    def removeNativeEventFilter(self, event_filter: object) -> None:  # noqa: N802
        self.removed.append(event_filter)


class _FakeUser32:
    def __init__(self) -> None:
        self.registered: list[tuple[object, int, int, int]] = []
        self.unregistered: list[tuple[object, int]] = []

    def RegisterHotKey(
        self,
        hwnd: object,
        hotkey_id: int,
        modifiers: int,
        key: int,
    ) -> bool:
        self.registered.append((hwnd, hotkey_id, modifiers, key))
        return True

    def UnregisterHotKey(self, hwnd: object, hotkey_id: int) -> bool:
        self.unregistered.append((hwnd, hotkey_id))
        return True


class _ConflictingUser32(_FakeUser32):
    def RegisterHotKey(
        self,
        hwnd: object,
        hotkey_id: int,
        modifiers: int,
        key: int,
    ) -> bool:
        if hotkey_id == 2:
            self.registered.append((hwnd, hotkey_id, modifiers, key))
            return False
        return super().RegisterHotKey(hwnd, hotkey_id, modifiers, key)


class _FailingUnregisterUser32(_FakeUser32):
    def __init__(self) -> None:
        super().__init__()
        self.allow_unregister = False

    def UnregisterHotKey(self, hwnd: object, hotkey_id: int) -> bool:
        self.unregistered.append((hwnd, hotkey_id))
        return self.allow_unregister


class _ExplodingRegisterUser32(_FakeUser32):
    def RegisterHotKey(
        self,
        hwnd: object,
        hotkey_id: int,
        modifiers: int,
        key: int,
    ) -> bool:
        if hotkey_id == 2:
            raise OSError("registration crashed")
        return super().RegisterHotKey(hwnd, hotkey_id, modifiers, key)


def test_runtime_uses_thread_queue_and_dispatches_registered_hotkey() -> None:
    application = _FakeApplication()
    user32 = _FakeUser32()
    dispatched: list[int] = []
    runtime = GlobalHotkeyRuntime(
        dispatched.append,
        supported=True,
        application=application,
        user32=user32,
    )

    failures = runtime.register({1: (0x0002, 0x41)})

    assert failures == ()
    assert application.installed == [runtime]
    assert user32.registered == [(None, 1, 0x0002, 0x41)]

    message = wintypes.MSG()
    message.message = 0x0312
    message.wParam = 1
    handled, result = runtime.nativeEventFilter(
        b"windows_dispatcher_MSG",
        addressof(message),
    )

    assert (handled, result) == (True, 0)
    assert dispatched == [1]

    runtime.unregister()

    assert user32.unregistered == [(None, 1)]
    assert application.removed == [runtime]


def test_runtime_reports_partial_failure_and_ignores_unregistered_message() -> None:
    application = _FakeApplication()
    user32 = _ConflictingUser32()
    dispatched: list[int] = []
    runtime = GlobalHotkeyRuntime(
        dispatched.append,
        supported=True,
        application=application,
        user32=user32,
        get_last_error=lambda: 1409,
    )

    failures = runtime.register({1: (0x0002, 0x41), 2: (0x0001, 0x42)})

    assert [(item.hotkey_id, item.code, item.reason) for item in failures] == [
        (2, 1409, "already_registered")
    ]

    message = wintypes.MSG()
    message.message = 0x0312
    message.wParam = 2
    assert runtime.nativeEventFilter(
        b"windows_dispatcher_MSG",
        addressof(message),
    ) == (False, 0)
    assert dispatched == []

    runtime.unregister()

    assert user32.unregistered == [(None, 1)]


def test_runtime_removes_filter_when_every_registration_fails() -> None:
    application = _FakeApplication()
    runtime = GlobalHotkeyRuntime(
        lambda _hotkey_id: None,
        supported=True,
        application=application,
        user32=_ConflictingUser32(),
        get_last_error=lambda: 1409,
    )

    failures = runtime.register({2: (0x0001, 0x42)})

    assert [(item.hotkey_id, item.reason) for item in failures] == [
        (2, "already_registered")
    ]
    assert application.removed == [runtime]


def test_unsupported_runtime_does_not_require_windows_ctypes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(global_hotkeys_module.ctypes, "get_last_error")
    runtime = GlobalHotkeyRuntime(lambda _hotkey_id: None, supported=False)

    assert runtime.supported is False
    assert runtime.register({1: (0x0002, 0x41)}) == ()


def test_unregister_failure_keeps_registration_and_filter_for_retry() -> None:
    application = _FakeApplication()
    user32 = _FailingUnregisterUser32()
    dispatched: list[int] = []
    runtime = GlobalHotkeyRuntime(
        dispatched.append,
        supported=True,
        application=application,
        user32=user32,
        get_last_error=lambda: 5,
    )
    assert runtime.register({1: (0x0002, 0x41)}) == ()

    failures = runtime.unregister()

    assert [(item.hotkey_id, item.code, item.reason) for item in failures] == [
        (1, 5, "unregistration_failed")
    ]
    assert application.removed == []

    message = wintypes.MSG()
    message.message = 0x0312
    message.wParam = 1
    assert runtime.nativeEventFilter(
        b"windows_generic_MSG",
        addressof(message),
    ) == (True, 0)
    assert dispatched == [1]

    user32.allow_unregister = True
    assert runtime.unregister() == ()
    assert application.removed == [runtime]


def test_registration_exception_rolls_back_successful_ids_and_filter() -> None:
    application = _FakeApplication()
    user32 = _ExplodingRegisterUser32()
    runtime = GlobalHotkeyRuntime(
        lambda _hotkey_id: None,
        supported=True,
        application=application,
        user32=user32,
    )

    with pytest.raises(OSError, match="registration crashed"):
        runtime.register({1: (0x0002, 0x41), 2: (0x0001, 0x42)})

    assert user32.unregistered == [(None, 1)]
    assert application.removed == [runtime]


def test_callback_exception_is_logged_without_breaking_later_dispatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = _FakeApplication()
    attempts: list[int] = []

    def dispatch(hotkey_id: int) -> None:
        attempts.append(hotkey_id)
        if len(attempts) == 1:
            raise RuntimeError("callback failed")

    runtime = GlobalHotkeyRuntime(
        dispatch,
        supported=True,
        application=application,
        user32=_FakeUser32(),
    )
    assert runtime.register({1: (0x0002, 0x41)}) == ()
    message = wintypes.MSG()
    message.message = 0x0312
    message.wParam = 1

    with caplog.at_level("ERROR"):
        first = runtime.nativeEventFilter(
            b"windows_dispatcher_MSG",
            addressof(message),
        )
        second = runtime.nativeEventFilter(
            b"windows_dispatcher_MSG",
            addressof(message),
        )

    assert first == second == (True, 0)
    assert attempts == [1, 1]
    assert "Global hotkey callback failed: id=1" in caplog.text
    runtime.unregister()


def test_runtime_rejects_management_outside_application_thread() -> None:
    application = _FakeApplication()
    application.owner_thread = object()
    user32 = _FakeUser32()
    runtime = GlobalHotkeyRuntime(
        lambda _hotkey_id: None,
        supported=True,
        application=application,
        user32=user32,
    )

    with pytest.raises(RuntimeError, match="Qt application thread"):
        runtime.register({1: (0x0002, 0x41)})

    assert application.installed == []
    assert user32.registered == []
