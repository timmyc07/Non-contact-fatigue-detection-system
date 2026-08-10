from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.alarm_config import AlarmConfig  # noqa: E402
from gui.alarm_player import FatigueAlarmController  # noqa: E402
from gui.desktop_control import (  # noqa: E402
    AlarmUnplayableError,
    HotkeyApplyError,
    SettingsWriteError,
)
import gui.main_window as main_window_module  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.video_replay import ReplayVideoSummary  # noqa: E402


_REGISTER_GLOBAL_HOTKEYS = MainWindow._register_global_hotkeys


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def settings_window(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> MainWindow:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(MainWindow, "_settings_path", lambda self: settings_path)
    monkeypatch.setattr(MainWindow, "_start_web_server", lambda self: None)
    monkeypatch.setattr(MainWindow, "_register_global_hotkeys", lambda self: None)
    monkeypatch.setattr(MainWindow, "_start_camera_scan", lambda self: None)
    window = MainWindow(engine_mode=True)
    yield window
    window._desktop_control_timer.stop()
    window.close()


def test_state_get_exposes_desktop_settings_v2(settings_window: MainWindow) -> None:
    state = settings_window._handle_desktop_command("state.get", {})

    assert state["desktop_api_version"] == 2
    assert state["hotkeys"] == {
        "toggle_metrics": "Ctrl+Alt+O",
        "toggle_preview": "Ctrl+Alt+P",
        "start_stop": "Ctrl+Alt+S",
        "lock_overlay": "Ctrl+Alt+F8",
        "toggle_all": "Ctrl+Alt+A",
        "toggle_recording": "Ctrl+Alt+F9",
    }
    assert state["user_profile"] == {
        "age": 28,
        "height_cm": 170,
        "weight_kg": 65.0,
        "bmi": 22.5,
    }
    assert state["alarm"]["enabled"] is False
    assert state["alarm"]["volume"] == 70
    assert set(state["alarm"]["scenarios"]) == {
        "low_vigilance",
        "drowsy",
        "critical",
        "microsleep",
    }
    assert state["settings_dirty"] is False
    assert state["hotkey_registration"]["failures"] == []
    assert state["rppg_enabled"] is False
    assert state["monitor_focus"] is False


def test_engine_mode_keeps_legacy_qt_overlay_hidden(
    settings_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[bool] = []
    hidden: list[bool] = []
    monkeypatch.setattr(
        settings_window._preview_overlay,
        "show",
        lambda: shown.append(True),
    )
    monkeypatch.setattr(
        settings_window._preview_overlay,
        "hide",
        lambda: hidden.append(True),
    )
    settings_window._pipeline_running = True
    settings_window._chk_preview.blockSignals(True)
    settings_window._chk_preview.setChecked(True)
    settings_window._chk_preview.blockSignals(False)

    settings_window._sync_overlay_visibility()

    assert shown == []
    assert hidden == [True]


def test_engine_mode_does_not_construct_legacy_visual_shell(
    settings_window: MainWindow,
) -> None:
    assert settings_window.centralWidget() is None
    assert type(settings_window._preview_overlay).__name__ == "_HeadlessOverlay"


def test_headless_analysis_command_preserves_worker_toggle_callbacks(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        settings_window,
        "_on_behavior_toggled",
        lambda checked: calls.append(("behavior", checked)),
    )
    monkeypatch.setattr(
        settings_window,
        "_on_stress_toggled",
        lambda checked: calls.append(("rppg", checked)),
    )

    settings_window._handle_desktop_command(
        "analysis.configure", {"behavior_enabled": False, "rppg_enabled": True}
    )

    assert calls == [("behavior", False), ("rppg", True)]
    assert settings_window._chk_behavior.isChecked() is False
    assert settings_window._chk_stress.isChecked() is True


def test_headless_hotkeys_update_overlay_state(
    settings_window: MainWindow,
) -> None:
    settings_window._menu_actions_hotkeys[0].trigger()
    assert settings_window._chk_metrics.isChecked() is False

    settings_window._menu_actions_hotkeys[4].trigger()
    assert settings_window._chk_all.isChecked() is False
    assert settings_window._chk_metrics.isChecked() is False
    assert settings_window._chk_preview.isChecked() is False

    settings_window._menu_actions_hotkeys[4].trigger()
    assert settings_window._chk_all.isChecked() is True
    assert settings_window._chk_metrics.isChecked() is True
    assert settings_window._chk_preview.isChecked() is True


def test_headless_replay_preview_and_queue_are_engine_safe(
    settings_window: MainWindow,
) -> None:
    summary = ReplayVideoSummary(
        subject="01",
        label="0",
        label_name="Alert",
        video_path="sample.mp4",
    )
    settings_window._replay_queue_upsert(summary, done=False)
    settings_window._on_replay_preview_frame(
        QImage(2, 2, QImage.Format.Format_RGB32)
    )
    settings_window._update_belt_panel()
    settings_window._refresh_monitor_metrics()


@pytest.mark.parametrize(
    ("failure_handler", "stop_method", "behavior", "rppg", "expected"),
    [
        (
            "_on_combined_failed",
            "_stop_combined_worker",
            True,
            True,
            [("rppg", False), ("behavior", False)],
        ),
        (
            "_on_rppg_failed",
            "_stop_rppg_worker",
            False,
            True,
            [("rppg", False)],
        ),
        (
            "_on_fatigue_failed",
            "_stop_fatigue_worker",
            True,
            False,
            [("behavior", False)],
        ),
    ],
)
def test_headless_worker_failure_applies_analysis_cleanup(
    settings_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    failure_handler: str,
    stop_method: str,
    behavior: bool,
    rppg: bool,
    expected: list[tuple[str, bool]],
) -> None:
    calls: list[tuple[str, bool]] = []
    settings_window._chk_behavior.setChecked(behavior)
    settings_window._chk_stress.setChecked(rppg)
    monkeypatch.setattr(settings_window, stop_method, lambda: None)
    monkeypatch.setattr(settings_window, "_append_log", lambda _message: None)
    monkeypatch.setattr(settings_window, "_notify_user", lambda _title, _message: None)
    monkeypatch.setattr(
        settings_window,
        "_on_behavior_toggled",
        lambda checked: calls.append(("behavior", checked)),
    )
    monkeypatch.setattr(
        settings_window,
        "_on_stress_toggled",
        lambda checked: calls.append(("rppg", checked)),
    )

    getattr(settings_window, failure_handler)("boom")

    assert calls == expected


def test_hotkeys_configure_replaces_all_shortcuts(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrations = 0

    def register() -> None:
        nonlocal registrations
        registrations += 1

    monkeypatch.setattr(settings_window, "_register_global_hotkeys", register)
    hotkeys = {
        "toggle_metrics": "Alt+1",
        "toggle_preview": "Alt+2",
        "start_stop": "Alt+3",
        "lock_overlay": "Alt+4",
        "toggle_all": "Alt+5",
        "toggle_recording": "",
    }

    state = settings_window._handle_desktop_command(
        "hotkeys.configure", {"hotkeys": hotkeys}
    )

    assert state["hotkeys"] == hotkeys
    assert state["settings_dirty"] is True
    assert registrations == 1
    assert [
        action.shortcut().toString()
        for action in settings_window._menu_actions_hotkeys
    ] == list(hotkeys.values())


def test_hotkeys_configure_rolls_back_when_apply_fails(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    applied_metrics: list[str] = []

    def flaky_apply() -> None:
        applied_metrics.append(settings_window._hotkeys.toggle_metrics)
        if len(applied_metrics) == 1:
            raise RuntimeError("native registration failed")

    monkeypatch.setattr(settings_window, "_apply_hotkey_shortcuts", flaky_apply)
    replacement = {
        "toggle_metrics": "Alt+1",
        "toggle_preview": "Alt+2",
        "start_stop": "Alt+3",
        "lock_overlay": "Alt+4",
        "toggle_all": "Alt+5",
        "toggle_recording": "Alt+6",
    }

    with pytest.raises(HotkeyApplyError):
        settings_window._handle_desktop_command(
            "hotkeys.configure", {"hotkeys": replacement}
        )

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["hotkeys"]["toggle_metrics"] == "Ctrl+Alt+O"
    assert state["settings_dirty"] is False
    assert applied_metrics == ["Alt+1", "Ctrl+Alt+O"]


def test_global_hotkey_registration_failures_are_exposed_in_state(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class User32:
        @staticmethod
        def RegisterHotKey(hwnd: int, hotkey_id: int, modifiers: int, key: int) -> bool:
            return False

        @staticmethod
        def UnregisterHotKey(hwnd: int, hotkey_id: int) -> bool:
            return True

    monkeypatch.setattr(main_window_module.ctypes, "WinDLL", lambda *args, **kwargs: User32())
    monkeypatch.setattr(main_window_module.ctypes, "get_last_error", lambda: 1409)
    settings_window._global_hotkey_enabled = True
    settings_window._global_hotkeys_registered = False

    _REGISTER_GLOBAL_HOTKEYS(settings_window)

    failures = settings_window._handle_desktop_command("state.get", {})[
        "hotkey_registration"
    ]["failures"]
    assert failures[0] == {
        "key": "toggle_metrics",
        "sequence": "Ctrl+Alt+O",
        "code": 1409,
        "reason": "already_registered",
    }
    assert len(failures) == 6


@pytest.mark.parametrize(
    "hotkeys",
    [
        {},
        {
            "toggle_metrics": "Ctrl+A, Ctrl+B",
            "toggle_preview": "Alt+2",
            "start_stop": "Alt+3",
            "lock_overlay": "Alt+4",
            "toggle_all": "Alt+5",
            "toggle_recording": "Alt+6",
        },
        {
            "toggle_metrics": 7,
            "toggle_preview": "Alt+2",
            "start_stop": "Alt+3",
            "lock_overlay": "Alt+4",
            "toggle_all": "Alt+5",
            "toggle_recording": "Alt+6",
        },
    ],
)
def test_hotkeys_configure_rejects_invalid_full_replacement(
    settings_window: MainWindow, hotkeys: dict[str, object]
) -> None:
    before = settings_window._handle_desktop_command("state.get", {})["hotkeys"]

    with pytest.raises(ValueError, match="hotkeys"):
        settings_window._handle_desktop_command(
            "hotkeys.configure", {"hotkeys": hotkeys}
        )

    assert settings_window._handle_desktop_command("state.get", {})["hotkeys"] == before


def test_user_profile_configure_accepts_boundaries_and_derives_bmi(
    settings_window: MainWindow,
) -> None:
    state = settings_window._handle_desktop_command(
        "user_profile.configure",
        {
            "user_profile": {
                "age": 0,
                "height_cm": 100,
                "weight_kg": 30.0,
            }
        },
    )

    assert state["user_profile"] == {
        "age": 0,
        "height_cm": 100,
        "weight_kg": 30.0,
        "bmi": 30.0,
    }
    assert state["settings_dirty"] is True


@pytest.mark.parametrize(
    "user_profile",
    [
        {"age": True, "height_cm": 170, "weight_kg": 65.0},
        {"age": 111, "height_cm": 170, "weight_kg": 65.0},
        {"age": 28, "height_cm": 99, "weight_kg": 65.0},
        {"age": 28, "height_cm": 170, "weight_kg": float("nan")},
        {"age": 28, "height_cm": 170, "weight_kg": 200.1},
    ],
)
def test_user_profile_configure_rejects_invalid_values(
    settings_window: MainWindow, user_profile: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="user_profile"):
        settings_window._handle_desktop_command(
            "user_profile.configure", {"user_profile": user_profile}
        )


def _alarm_payload(**changes: object) -> dict[str, object]:
    alarm: dict[str, object] = {
        "enabled": True,
        "volume": 80,
        "trigger_delay_sec": 1.5,
        "repeat_interval_sec": 20.0,
        "repeat_while_critical": False,
        "use_builtin_fallback": True,
        "scenarios": {
            "low_vigilance": {"enabled": False, "sound_path": ""},
            "drowsy": {"enabled": True, "sound_path": ""},
            "critical": {"enabled": True, "sound_path": ""},
            "microsleep": {"enabled": True, "sound_path": ""},
        },
    }
    alarm.update(changes)
    return alarm


def test_alarm_configure_updates_runtime_controller(
    settings_window: MainWindow,
) -> None:
    alarm = _alarm_payload()

    state = settings_window._handle_desktop_command(
        "alarm.configure", {"alarm": alarm}
    )

    assert state["alarm"] == alarm
    assert settings_window._alarm_controller.config.to_dict() == alarm
    assert state["settings_dirty"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"volume": True},
        {"volume": 101},
        {"trigger_delay_sec": 10.1},
        {"repeat_interval_sec": 4.9},
        {"repeat_while_critical": 1},
        {"scenarios": {}},
    ],
)
def test_alarm_configure_rejects_invalid_values(
    settings_window: MainWindow, changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="alarm"):
        settings_window._handle_desktop_command(
            "alarm.configure", {"alarm": _alarm_payload(**changes)}
        )


def test_alarm_configure_rejects_missing_file_without_fallback(
    settings_window: MainWindow, tmp_path: Path
) -> None:
    scenarios = _alarm_payload()["scenarios"]
    assert isinstance(scenarios, dict)
    scenarios["critical"] = {
        "enabled": True,
        "sound_path": str(tmp_path / "missing.wav"),
    }

    with pytest.raises(ValueError, match="sound_path does not exist"):
        settings_window._handle_desktop_command(
            "alarm.configure",
            {
                "alarm": _alarm_payload(
                    use_builtin_fallback=False,
                    scenarios=scenarios,
                )
            },
        )


class _PlaybackSpy:
    def __init__(self) -> None:
        self.files: list[tuple[str, float]] = []
        self.builtins: list[str] = []

    def play_file(self, path: str, *, volume: float) -> bool:
        self.files.append((path, volume))
        return True

    def play_builtin(self, scenario: str) -> None:
        self.builtins.append(scenario)


def test_alarm_test_uses_draft_without_mutating_runtime(
    settings_window: MainWindow, tmp_path: Path
) -> None:
    sound_path = tmp_path / "draft.wav"
    sound_path.write_bytes(b"RIFF")
    runtime = AlarmConfig.defaults()
    playback = _PlaybackSpy()
    settings_window._alarm_config = runtime
    settings_window._alarm_controller = FatigueAlarmController(
        runtime, playback=playback
    )
    draft = _alarm_payload(volume=25)
    scenarios = draft["scenarios"]
    assert isinstance(scenarios, dict)
    scenarios["critical"] = {"enabled": False, "sound_path": str(sound_path)}

    state = settings_window._handle_desktop_command(
        "alarm.test", {"scenario": "critical", "alarm": draft}
    )

    assert playback.files == [(str(sound_path), 0.25)]
    assert playback.builtins == []
    assert state["alarm"] == runtime.to_dict()
    assert settings_window._alarm_controller.config is runtime
    assert state["settings_dirty"] is False
    assert state["command_result"] == {
        "command": "alarm.test",
        "scenario": "critical",
        "dispatched": True,
        "source": "file",
    }


def test_alarm_test_reports_builtin_source(settings_window: MainWindow) -> None:
    runtime = AlarmConfig.defaults()
    playback = _PlaybackSpy()
    settings_window._alarm_config = runtime
    settings_window._alarm_controller = FatigueAlarmController(runtime, playback=playback)

    state = settings_window._handle_desktop_command(
        "alarm.test", {"scenario": "drowsy"}
    )

    assert playback.builtins == ["drowsy"]
    assert state["command_result"]["source"] == "builtin"


def test_alarm_test_raises_typed_error_when_no_source(
    settings_window: MainWindow,
) -> None:
    draft = _alarm_payload(use_builtin_fallback=False)

    with pytest.raises(AlarmUnplayableError) as exc_info:
        settings_window._handle_desktop_command(
            "alarm.test", {"scenario": "critical", "alarm": draft}
        )

    assert exc_info.value.code == "alarm_unplayable"


def test_settings_reset_only_resets_selected_sections(
    settings_window: MainWindow,
) -> None:
    settings_window._handle_desktop_command(
        "hotkeys.configure",
        {
            "hotkeys": {
                "toggle_metrics": "Alt+1",
                "toggle_preview": "Alt+2",
                "start_stop": "Alt+3",
                "lock_overlay": "Alt+4",
                "toggle_all": "Alt+5",
                "toggle_recording": "Alt+6",
            }
        },
    )
    settings_window._handle_desktop_command(
        "user_profile.configure",
        {"user_profile": {"age": 40, "height_cm": 180, "weight_kg": 90.0}},
    )
    settings_window._handle_desktop_command(
        "alarm.configure", {"alarm": _alarm_payload(volume=25)}
    )

    state = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["hotkeys", "alarm"]}
    )

    assert state["hotkeys"]["toggle_metrics"] == "Ctrl+Alt+O"
    assert state["alarm"] == AlarmConfig.defaults().to_dict()
    assert settings_window._alarm_controller.config.to_dict() == state["alarm"]
    assert state["user_profile"] == {
        "age": 40,
        "height_cm": 180,
        "weight_kg": 90.0,
        "bmi": 27.8,
    }
    assert state["settings_dirty"] is True


def test_settings_save_persists_atomically_and_clears_dirty(
    settings_window: MainWindow,
) -> None:
    settings_window._handle_desktop_command(
        "user_profile.configure",
        {"user_profile": {"age": 35, "height_cm": 175, "weight_kg": 70.0}},
    )

    state = settings_window._handle_desktop_command("settings.save", {})

    settings_path = settings_window._settings_path()
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["user"] == {"age": 35, "height_cm": 175, "weight_kg": 70.0}
    assert state["settings_dirty"] is False
    assert state["command_result"] == {
        "command": "settings.save",
        "path": str(settings_path),
    }
    assert list(settings_path.parent.glob(f".{settings_path.name}.*.tmp")) == []


def test_settings_save_replace_failure_preserves_old_file_and_dirty_state(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = settings_window._settings_path()
    old_content = '{"sentinel":"old"}'
    settings_path.write_text(old_content, encoding="utf-8")
    settings_window._handle_desktop_command(
        "user_profile.configure",
        {"user_profile": {"age": 35, "height_cm": 175, "weight_kg": 70.0}},
    )
    real_replace = Path.replace

    def fail_temp_replace(source: Path, target: Path) -> Path:
        if source.name.startswith(f".{settings_path.name}."):
            raise OSError("replace denied")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_temp_replace)

    with pytest.raises(SettingsWriteError) as exc_info:
        settings_window._handle_desktop_command("settings.save", {})

    assert exc_info.value.path == str(settings_path)
    assert settings_path.read_text(encoding="utf-8") == old_content
    assert settings_window._handle_desktop_command("state.get", {})["settings_dirty"] is True
    assert list(settings_path.parent.glob(f".{settings_path.name}.*.tmp")) == []


def test_settings_save_logs_temp_cleanup_failure(
    settings_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_window._handle_desktop_command(
        "user_profile.configure",
        {"user_profile": {"age": 35, "height_cm": 175, "weight_kg": 70.0}},
    )

    def fail_cleanup(path: Path, *, missing_ok: bool = False) -> None:
        raise OSError("cleanup denied")

    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    with caplog.at_level(logging.WARNING, logger="gui.main_window"):
        state = settings_window._handle_desktop_command("settings.save", {})

    assert state["settings_dirty"] is False
    assert "設定暫存檔清理失敗" in caplog.text


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("camera.configure", {"resolution": "800×600"}),
        ("analysis.configure", {"behavior_enabled": True}),
        ("preferences.configure", {"auto_record": True}),
        ("overlay.configure", {"opacity": 60}),
    ],
)
def test_persisted_configure_commands_mark_settings_dirty(
    settings_window: MainWindow, command: str, args: dict[str, object]
) -> None:
    assert settings_window._handle_desktop_command("state.get", {})["settings_dirty"] is False

    state = settings_window._handle_desktop_command(command, args)

    assert state["settings_dirty"] is True


def test_web_lan_marks_dirty_and_schedules_nonblocking_restart(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[bool] = []
    restarted: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_schedule_web_server_restart",
        lambda: scheduled.append(True),
        raising=False,
    )
    monkeypatch.setattr(
        settings_window,
        "_restart_web_server",
        lambda: restarted.append(True),
    )

    state = settings_window._handle_desktop_command(
        "settings.action", {"action": "web_lan", "enabled": True}
    )

    assert state["web_allow_lan"] is True
    assert state["settings_dirty"] is True
    assert scheduled == [True]
    assert restarted == []


@pytest.mark.parametrize(
    ("command", "args", "error"),
    [
        ("replay.choose", {}, "Unsupported desktop command"),
        ("settings.action", {"action": "hotkeys"}, "Unsupported settings action"),
        ("settings.action", {"action": "profile"}, "Unsupported settings action"),
        ("settings.action", {"action": "alarm"}, "Unsupported settings action"),
        ("settings.action", {"action": "reset"}, "Unsupported settings action"),
    ],
)
def test_engine_rejects_retired_qt_visible_actions(
    settings_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    args: dict[str, object],
    error: str,
) -> None:
    monkeypatch.setattr(settings_window, "_choose_replay_dir", lambda: None, raising=False)
    monkeypatch.setattr(settings_window, "_on_hotkeys", lambda: None, raising=False)
    monkeypatch.setattr(settings_window, "_on_user_profile", lambda: None, raising=False)
    monkeypatch.setattr(settings_window, "_on_alarm_settings", lambda: None, raising=False)
    monkeypatch.setattr(settings_window, "_on_reset_layout", lambda: None, raising=False)

    with pytest.raises(ValueError, match=error):
        settings_window._handle_desktop_command(command, args)


@pytest.mark.parametrize("mode", ["single", "parallel"])
def test_replay_commands_configure_start_and_stop(
    settings_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        settings_window,
        "_start_replay",
        lambda: events.append("single"),
    )
    monkeypatch.setattr(
        settings_window,
        "_start_replay_parallel",
        lambda *, notify=True: events.append(f"parallel:{notify}"),
    )
    monkeypatch.setattr(
        settings_window,
        "_stop_replay",
        lambda: events.append("stop"),
    )

    configured = settings_window._handle_desktop_command(
        "replay.configure",
        {"path": str(tmp_path), "jobs": 3, "annotated": True},
    )
    settings_window._handle_desktop_command(
        "replay.set", {"enabled": True, "mode": mode}
    )
    settings_window._handle_desktop_command("replay.set", {"enabled": False})

    assert configured["replay_dataset_dir"] == str(tmp_path)
    assert configured["replay_jobs"] == 3
    assert configured["replay_annotated"] is True
    expected_start = "single" if mode == "single" else "parallel:False"
    assert events == [expected_start, "stop"]


def test_web_reset_updates_state_and_schedules_nonblocking_restart(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_window._act_web_allow_lan.blockSignals(True)
    settings_window._act_web_allow_lan.setChecked(True)
    settings_window._act_web_allow_lan.blockSignals(False)
    scheduled: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_schedule_web_server_restart",
        lambda: scheduled.append(True),
    )

    state = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["web"]}
    )

    assert state["web_allow_lan"] is False
    assert state["settings_dirty"] is True
    assert scheduled == [True]


def test_web_restart_is_background_and_coalesced(
    settings_window: MainWindow, qt_app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_thread = __import__("threading").get_ident()
    stop_threads: list[int] = []
    starts: list[int] = []

    class Server:
        def stop(self, *, join_timeout: float = 5.0) -> bool:
            stop_threads.append(__import__("threading").get_ident())
            return True

        @staticmethod
        def is_alive() -> bool:
            return False

    settings_window._web_server = Server()
    monkeypatch.setattr(
        settings_window,
        "_start_web_server",
        lambda: starts.append(__import__("threading").get_ident()),
    )

    settings_window._schedule_web_server_restart()
    settings_window._schedule_web_server_restart()
    deadline = __import__("time").monotonic() + 1.0
    while not starts and __import__("time").monotonic() < deadline:
        qt_app.processEvents()

    assert len(stop_threads) == 1
    assert stop_threads[0] != main_thread
    assert starts == [main_thread]


def test_web_restart_does_not_rebind_while_old_server_is_alive(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Server:
        @staticmethod
        def stop(*, join_timeout: float = 5.0) -> bool:
            return False

        @staticmethod
        def is_alive() -> bool:
            return True

    server = Server()
    starts: list[bool] = []
    settings_window._web_restart_in_progress = True
    settings_window._web_restart_stopping_server = server
    monkeypatch.setattr(
        settings_window,
        "_start_web_server",
        lambda: starts.append(True),
    )

    settings_window._on_web_restart_stopped(False, True)

    assert settings_window._web_server is server
    assert settings_window._web_restart_in_progress is False
    assert settings_window._web_restart_stopping_server is None
    assert starts == []


def test_web_restart_callback_does_not_start_server_during_shutdown(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[bool] = []
    settings_window._web_restart_shutdown = True
    settings_window._web_restart_in_progress = True
    settings_window._web_restart_stopping_server = object()
    monkeypatch.setattr(
        settings_window,
        "_start_web_server",
        lambda: starts.append(True),
    )

    settings_window._on_web_restart_stopped(True, False)

    assert settings_window._web_server is None
    assert settings_window._web_restart_in_progress is False
    assert settings_window._web_restart_stopping_server is None
    assert starts == []


def test_web_restart_starts_when_server_exits_just_after_stop_timeout(
    settings_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[bool] = []
    settings_window._web_restart_in_progress = True
    settings_window._web_restart_stopping_server = object()
    monkeypatch.setattr(
        settings_window,
        "_start_web_server",
        lambda: starts.append(True),
    )

    settings_window._on_web_restart_stopped(False, False)

    assert settings_window._web_server is None
    assert settings_window._web_restart_in_progress is False
    assert settings_window._web_restart_stopping_server is None
    assert starts == [True]


def test_desktop_settings_contract_module_is_qt_free() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "gui" / "desktop_settings_contract.py"
    ).read_text(encoding="utf-8")

    assert "PySide6" not in source
