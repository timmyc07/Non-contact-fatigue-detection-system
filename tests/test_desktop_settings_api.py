from __future__ import annotations

import json
import logging
import os
import queue
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from gui.alarm_config import AlarmConfig  # noqa: E402
from gui.alarm_player import FatigueAlarmController  # noqa: E402
from gui.desktop_control import (  # noqa: E402
    AlarmUnplayableError,
    BusyError,
    HotkeyApplyError,
    SettingsWriteError,
)
import gui.main_window as main_window_module  # noqa: E402
from gui.engine_controller import AnalysisLifecyclePorts, CameraDevice  # noqa: E402
from gui.global_hotkeys import HotkeyRegistrationFailure  # noqa: E402
from gui.main_window import EngineApplication, _classify_log_message  # noqa: E402
from gui.video_replay import ReplayVideoSummary  # noqa: E402


_REGISTER_GLOBAL_HOTKEYS = EngineApplication._register_global_hotkeys
_SETTINGS_PATH = EngineApplication._settings_path
_RECORDINGS_DIR = EngineApplication._recordings_dir


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def settings_window(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> EngineApplication:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(EngineApplication, "_settings_path", lambda self: settings_path)
    monkeypatch.setattr(EngineApplication, "_start_web_server", lambda self: None)
    monkeypatch.setattr(EngineApplication, "_register_global_hotkeys", lambda self: None)
    monkeypatch.setattr(EngineApplication, "_start_camera_scan", lambda self: None)
    window = EngineApplication(engine_mode=True)
    yield window
    window._engine_runtime.cancel_timer("desktop_command")
    window.close_runtime()


def _install_runtime_adapter(
    window: EngineApplication, kind: str, worker: object, thread: object
) -> None:
    """Install a fake adapter session without restoring EngineApplication storage."""
    window._engine_runtime._adapters[kind] = (worker, thread)  # type: ignore[assignment]


def test_state_get_exposes_desktop_settings_v2(settings_window: EngineApplication) -> None:
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
    assert state["profile_status"] == "個人基線：未啟動"
    assert "benchmark_active" not in state


def test_engine_runtime_owns_desktop_command_drain_timer(
    settings_window: EngineApplication,
) -> None:
    assert settings_window._engine_runtime.timer_active("desktop_command") is True
    assert not hasattr(settings_window, "_desktop_control_timer")


def test_engine_runtime_owns_belt_tick_timer(settings_window: EngineApplication) -> None:
    assert settings_window._engine_runtime.timer_active("belt_tick") is False
    assert not hasattr(settings_window, "_belt_ui_timer")


def test_engine_runtime_owns_auto_capture_timer(settings_window: EngineApplication) -> None:
    assert settings_window._engine_runtime.timer_active("auto_capture") is False
    assert not hasattr(settings_window, "_auto_capture_timer")


def test_engine_mode_does_not_construct_legacy_visual_shell(
    settings_window: EngineApplication,
) -> None:
    assert isinstance(settings_window, QObject)
    assert not isinstance(settings_window, (QWidget, QMainWindow))
    assert settings_window._preview_overlay is None
    for name in (
        "_chk_all",
        "_chk_preview",
        "_chk_metrics",
        "_chk_lock",
        "_sld_opacity",
        "_chk_replay_annotated",
        "_spn_replay_jobs",
        "_lbl_replay_current",
        "_lbl_replay_dir",
        "_lbl_replay_parallel_status",
        "_lbl_replay_result",
        "_chk_auto_record",
        "_chk_belt_calib",
        "_chk_auto_capture_belt",
        "_spn_auto_capture_seconds",
        "_btn_auto_capture",
        "_chk_behavior",
        "_chk_stress",
        "_act_web_allow_lan",
        "_log",
        "_menu_actions_hotkeys",
        "_mon_blink",
        "_mon_bpm",
        "_mon_bpm_delta",
        "_mon_contrib_bars",
        "_mon_ear",
        "_mon_expr",
        "_mon_fused_level",
        "_mon_fused_score",
        "_mon_gaze",
        "_mon_head",
        "_mon_hrv_conf",
        "_mon_lfhf",
        "_mon_perclos",
        "_mon_rec_pill",
        "_mon_rmssd",
        "_mon_score_bar",
        "_mon_score_big",
        "_mon_sdnn",
        "_mon_sqi",
        "_mon_trend",
        "_mon_warmup",
        "_mon_wave",
        "_belt_banner_dot",
        "_belt_bpm_spark",
        "_belt_calib_bar",
        "_lbl_belt_address",
        "_lbl_belt_banner_battery",
        "_lbl_belt_banner_bpm",
        "_lbl_belt_banner_device",
        "_lbl_belt_banner_rssi",
        "_lbl_belt_battery",
        "_lbl_belt_bpm",
        "_lbl_belt_calib_confidence",
        "_lbl_belt_calib_corr_resid",
        "_lbl_belt_calib_offset",
        "_lbl_belt_calib_pairs",
        "_lbl_belt_calib_raw_resid",
        "_lbl_belt_calib_resid",
        "_lbl_belt_calib_status",
        "_lbl_belt_cfg_address",
        "_lbl_belt_cfg_capture",
        "_lbl_belt_cfg_name_prefix",
        "_lbl_belt_cfg_tuning",
        "_lbl_belt_connected_since",
        "_lbl_belt_contact",
        "_lbl_belt_device",
        "_lbl_belt_hrv_conf",
        "_lbl_belt_hrv_lfhf",
        "_lbl_belt_hrv_rmssd",
        "_lbl_belt_hrv_sdnn",
        "_lbl_belt_hrv_warmup",
        "_lbl_belt_last_error",
        "_lbl_belt_location",
        "_lbl_belt_notifications",
        "_lbl_belt_rr",
        "_lbl_belt_rssi",
        "_lbl_belt_stale",
        "_lbl_belt_status",
        "_lbl_dev_belt",
        "_brand_dot",
        "_btn_bench",
        "_btn_record",
        "_btn_record_baseline",
        "_btn_start",
        "_lbl_bench",
        "_lbl_camera",
        "_lbl_codec",
        "_lbl_dev_cam",
        "_lbl_dev_mp",
        "_lbl_face",
        "_lbl_fps",
        "_lbl_opacity",
        "_lbl_pipeline",
        "_lbl_preview_telemetry",
        "_lbl_profile_status",
        "_lbl_record",
        "_tag_mesh",
        "_tag_rppg",
    ):
        assert not hasattr(settings_window, name)
    assert not hasattr(settings_window, "_rec_ui_timer")


def test_engine_application_rejects_legacy_widget_mode(qt_app: QApplication) -> None:
    with pytest.raises(ValueError, match="engine-only"):
        EngineApplication(engine_mode=False)


def test_headless_settings_preserve_legacy_window_payload(
    settings_window: EngineApplication,
) -> None:
    legacy_window = {"geometry": "legacy-geometry", "state": "legacy-state"}
    settings_window._settings_path().write_text(
        json.dumps({"window": legacy_window}),
        encoding="utf-8",
    )

    settings_window._load_settings()
    settings_window._save_settings()

    saved = json.loads(settings_window._settings_path().read_text(encoding="utf-8"))
    assert saved["window"] == legacy_window


def test_engine_log_messages_use_python_logger(
    settings_window: EngineApplication, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="gui.main_window"):
        settings_window._append_log("pipeline ready")
        settings_window._append_log("⚠ camera warning")
        settings_window._append_log("⚠ camera start failed")
        settings_window._append_log("警告：camera unavailable")
        settings_window._append_log("✗ camera failure")

    records = [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == "gui.main_window"
    ]
    assert records == [
        (logging.INFO, "pipeline ready"),
        (logging.WARNING, "⚠ camera warning"),
        (logging.WARNING, "⚠ camera start failed"),
        (logging.WARNING, "警告：camera unavailable"),
        (logging.ERROR, "✗ camera failure"),
    ]


def test_log_classification_preserves_legacy_error_color_precedence() -> None:
    message = "⚠ Web 儀表板啟動失敗"

    assert _classify_log_message(message) == "error"
    assert _classify_log_message(message, warning_priority=True) == "warning"


def test_headless_analysis_command_updates_controller_owned_state(
    settings_window: EngineApplication,
) -> None:
    state = settings_window._handle_desktop_command(
        "analysis.configure", {"behavior_enabled": False, "rppg_enabled": True}
    )

    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is True
    plan = settings_window._engine_controller.analysis_snapshot()
    assert plan.fatigue_enabled is False
    assert plan.rppg_enabled is True


def test_headless_analysis_state_and_persistence_use_controller_state(
    settings_window: EngineApplication,
) -> None:
    settings_window._handle_desktop_command(
        "analysis.configure",
        {"behavior_enabled": False, "rppg_enabled": True},
    )
    state = settings_window._handle_desktop_command("settings.save", {})
    persisted = json.loads(
        settings_window._settings_path().read_text(encoding="utf-8")
    )

    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is True
    assert persisted["toggles"]["behavior"] is False
    assert persisted["toggles"]["stress"] is True


def test_settings_load_restores_controller_owned_analysis_state(
    settings_window: EngineApplication,
) -> None:
    settings_window._settings_path().write_text(
        json.dumps(
            {
                "toggles": {
                    "behavior": False,
                    "stress": True,
                }
            }
        ),
        encoding="utf-8",
    )

    settings_window._load_settings()

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is True


def test_capture_preferences_state_and_saved_json_remain_in_sync(
    settings_window: EngineApplication,
) -> None:
    state = settings_window._handle_desktop_command(
        "preferences.configure",
        {"auto_record": True, "belt_calibration": True},
    )
    assert state["auto_record"] is True
    assert state["belt_calibration"] is True

    state = settings_window._handle_desktop_command(
        "auto_capture.configure",
        {"duration_seconds": 120, "include_belt": True},
    )
    assert state["auto_capture_seconds"] == 120
    assert state["auto_capture_include_belt"] is True

    saved = settings_window._handle_desktop_command("settings.save", {})
    persisted = json.loads(
        settings_window._settings_path().read_text(encoding="utf-8")
    )
    assert saved["auto_record"] is persisted["toggles"]["auto_record"]
    assert saved["belt_calibration"] is persisted["toggles"]["belt_calib"]
    assert "auto_capture" not in persisted


def test_settings_load_and_reset_restore_capture_persisted_preferences(
    settings_window: EngineApplication,
) -> None:
    settings_window._settings_path().write_text(
        json.dumps(
            {
                "toggles": {
                    "auto_record": True,
                    "belt_calib": True,
                }
            }
        ),
        encoding="utf-8",
    )
    settings_window._capture_preferences.configure(
        auto_capture_seconds=180,
        auto_capture_include_belt=True,
    )

    settings_window._load_settings()
    loaded = settings_window._handle_desktop_command("state.get", {})
    assert loaded["auto_record"] is True
    assert loaded["belt_calibration"] is True
    assert loaded["auto_capture_seconds"] == 180
    assert loaded["auto_capture_include_belt"] is True

    reset = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["toggles"]}
    )
    assert reset["auto_record"] is False
    assert reset["belt_calibration"] is False
    assert reset["auto_capture_seconds"] == 180
    assert reset["auto_capture_include_belt"] is True


@pytest.mark.parametrize("command", ["auto_capture.configure", "auto_capture.set"])
def test_auto_capture_commands_reject_non_boolean_include_belt(
    settings_window: EngineApplication,
    command: str,
) -> None:
    args: dict[str, object] = {
        "duration_seconds": 60,
        "include_belt": "false",
    }
    if command == "auto_capture.set":
        args["enabled"] = True

    with pytest.raises(ValueError, match="include_belt"):
        settings_window._handle_desktop_command(command, args)

    assert settings_window._capture_preferences.snapshot().auto_capture_include_belt is False


def test_auto_capture_command_uses_runtime_timer_without_stopping_existing_recording(
    settings_window: EngineApplication,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.start_pipeline()
    settings_window._engine_controller.start_recording()
    settings_window._recording_db_path = Path("existing.db")

    started = settings_window._handle_desktop_command(
        "auto_capture.set",
        {"enabled": True, "duration_seconds": 10, "include_belt": False},
    )

    assert started["auto_capture_active"] is True
    assert settings_window._engine_runtime.timer_active("auto_capture") is True

    stopped = settings_window._handle_desktop_command(
        "auto_capture.set",
        {"enabled": False},
    )

    assert stopped["auto_capture_active"] is False
    assert settings_window._engine_runtime.timer_active("auto_capture") is False
    assert settings_window._engine_controller.pipeline_snapshot().recording is True
    settings_window._engine_controller.stop_recording()
    settings_window._engine_controller.stop_pipeline()


def test_belt_calibration_preference_rolls_back_when_ble_start_fails(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    belt_runtime = settings_window._engine_controller.belt_runtime
    monkeypatch.setattr(belt_runtime, "start_belt", lambda _config=None: "BLE unavailable")

    state = settings_window._handle_desktop_command(
        "preferences.configure", {"belt_calibration": True}
    )

    assert state["belt_calibration"] is False
    assert settings_window._belt_calibrator is None
    assert settings_window._engine_controller.belt_running is False
    assert state["settings_dirty"] is False


def test_other_capture_changes_survive_belt_soft_failure_and_mark_dirty(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    belt_runtime = settings_window._engine_controller.belt_runtime
    monkeypatch.setattr(belt_runtime, "start_belt", lambda _config=None: "BLE unavailable")

    state = settings_window._handle_desktop_command(
        "preferences.configure",
        {"auto_record": True, "belt_calibration": True},
    )

    assert state["auto_record"] is True
    assert state["belt_calibration"] is False
    assert state["settings_dirty"] is True


def test_capture_preference_rolls_back_when_runtime_adapter_raises(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dirty = settings_window._settings_dirty
    monkeypatch.setattr(
        settings_window,
        "_on_belt_calib_toggled",
        lambda _checked: (_ for _ in ()).throw(RuntimeError("adapter failed")),
    )

    with pytest.raises(RuntimeError, match="adapter failed"):
        settings_window._handle_desktop_command(
            "preferences.configure",
            {"auto_record": True, "belt_calibration": True},
        )

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["auto_record"] is False
    assert state["belt_calibration"] is False
    assert state["settings_dirty"] is original_dirty


@pytest.mark.parametrize("failure_point", ["calibrator", "timer", "coordinator", "dispatch"])
def test_belt_calibration_start_failure_cleans_new_runtime_resources(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    class FakeHub:
        def clear(self) -> None:
            pass

    class FakeWriter:
        path = Path("belt-truth.jsonl")
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeBeltRuntime:
        def __init__(self) -> None:
            self.hub = FakeHub()
            self.belt_running = False
            self.writer = FakeWriter()

        def start_belt(self, _config: object = None) -> str:
            self.belt_running = True
            return ""

        def stop_belt(self) -> None:
            self.belt_running = False

        def create_truth_capture_writer(self, _path: object = None) -> FakeWriter:
            return self.writer

    runtime = FakeBeltRuntime()
    settings_window._engine_controller._belt_runtime = runtime
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    config = main_window_module.HrBeltConfig(
        rppg_param_tuning_enabled=failure_point == "coordinator",
        capture_enabled=failure_point == "dispatch",
    )
    monkeypatch.setattr(main_window_module, "load_hr_belt_config", lambda: config)

    if failure_point == "calibrator":
        monkeypatch.setattr(
            main_window_module,
            "OnlineBpmCalibrator",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("calibrator failed")),
        )
    elif failure_point == "timer":
        monkeypatch.setattr(
            settings_window._engine_runtime,
            "start_periodic_timer",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("timer failed")
            ),
        )
    elif failure_point == "coordinator":
        monkeypatch.setattr(
            main_window_module,
            "RppgParamCoordinator",
            lambda: (_ for _ in ()).throw(RuntimeError("coordinator failed")),
        )
    else:
        monkeypatch.setattr(
            settings_window,
            "_dispatch_belt_truth_capture",
            lambda _writer: (_ for _ in ()).throw(RuntimeError("dispatch failed")),
        )

    with pytest.raises(RuntimeError, match="failed"):
        settings_window._handle_desktop_command(
            "preferences.configure",
            {"belt_calibration": True},
        )

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["belt_calibration"] is False
    assert state["settings_dirty"] is False
    assert runtime.belt_running is False
    assert settings_window._engine_runtime.timer_active("belt_tick") is False
    assert settings_window._belt_calibrator is None
    assert settings_window._rppg_param_coordinator is None
    assert settings_window._belt_truth_capture is None
    assert runtime.writer.closed is (failure_point == "dispatch")


def test_belt_calibration_failure_preserves_preexisting_belt_runtime(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    belt_runtime = settings_window._engine_controller.belt_runtime
    monkeypatch.setattr(type(belt_runtime), "belt_running", property(lambda _self: True))
    stop_calls: list[bool] = []
    monkeypatch.setattr(belt_runtime, "stop_belt", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        main_window_module,
        "OnlineBpmCalibrator",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("calibrator failed")),
    )

    with pytest.raises(RuntimeError, match="calibrator failed"):
        settings_window._handle_desktop_command(
            "preferences.configure",
            {"belt_calibration": True},
        )

    assert stop_calls == []
    assert settings_window._capture_preferences.snapshot().belt_calibration is False


def test_capture_preferences_validate_entire_command_before_applying(
    settings_window: EngineApplication,
) -> None:
    with pytest.raises(ValueError, match="overlay_locked"):
        settings_window._handle_desktop_command(
            "preferences.configure",
            {"auto_record": True, "overlay_locked": "false"},
        )

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["auto_record"] is False
    assert state["overlay_locked"] is True
    assert state["settings_dirty"] is False


def test_session_only_auto_capture_preferences_do_not_mark_settings_dirty(
    settings_window: EngineApplication,
) -> None:
    state = settings_window._handle_desktop_command(
        "auto_capture.configure",
        {"duration_seconds": 120, "include_belt": True},
    )

    assert state["auto_capture_seconds"] == 120
    assert state["auto_capture_include_belt"] is True
    assert state["settings_dirty"] is False


def test_settings_reset_rolls_back_capture_state_when_runtime_adapter_raises(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._capture_preferences.configure(
        auto_record=True,
        belt_calibration=True,
    )
    original_dirty = settings_window._settings_dirty
    monkeypatch.setattr(
        settings_window,
        "_on_belt_calib_toggled",
        lambda _checked: (_ for _ in ()).throw(RuntimeError("reset adapter failed")),
    )

    with pytest.raises(RuntimeError, match="reset adapter failed"):
        settings_window._handle_desktop_command(
            "settings.reset",
            {"sections": ["toggles"]},
        )

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["auto_record"] is True
    assert state["belt_calibration"] is True
    assert state["settings_dirty"] is original_dirty


def test_overlay_commands_state_and_saved_json_remain_in_sync(
    settings_window: EngineApplication,
) -> None:
    state = settings_window._handle_desktop_command(
        "preferences.configure",
        {
            "overlay_preview": True,
            "overlay_metrics": False,
            "overlay_locked": False,
        },
    )
    assert state["overlay_preview"] is True
    assert state["overlay_metrics"] is False
    assert state["overlay_locked"] is False

    state = settings_window._handle_desktop_command(
        "overlay.configure", {"all": False, "opacity": 73}
    )
    assert state["overlay_all"] is False
    assert state["overlay_preview"] is False
    assert state["overlay_metrics"] is False
    assert state["overlay_opacity"] == 73

    saved_state = settings_window._handle_desktop_command("settings.save", {})
    persisted = json.loads(
        settings_window._settings_path().read_text(encoding="utf-8")
    )
    assert saved_state["overlay_all"] is persisted["toggles"]["all"]
    assert saved_state["overlay_preview"] is persisted["toggles"]["preview"]
    assert saved_state["overlay_metrics"] is persisted["toggles"]["metrics"]
    assert saved_state["overlay_locked"] is persisted["toggles"]["lock"]
    assert saved_state["overlay_opacity"] == persisted["overlay"]["opacity"]
    assert saved_state["overlay_geometry"] is None
    assert persisted["overlay"]["geometry"] is None


def test_overlay_geometry_command_round_trips_through_settings(
    settings_window: EngineApplication,
) -> None:
    geometry = {"x": -1280, "y": 24, "width": 720, "height": 480}

    state = settings_window._handle_desktop_command(
        "overlay.configure", {"geometry": geometry}
    )
    assert state["overlay_geometry"] == geometry
    assert state["settings_dirty"] is True

    saved = settings_window._handle_desktop_command("settings.save", {})
    persisted = json.loads(
        settings_window._settings_path().read_text(encoding="utf-8")
    )
    assert saved["overlay_geometry"] == geometry
    assert persisted["overlay"]["geometry"] == geometry

    settings_window._overlay_state.reset()
    settings_window._load_settings()
    assert settings_window._desktop_control_state()["overlay_geometry"] == geometry


def test_overlay_geometry_unchanged_command_does_not_mark_dirty(
    settings_window: EngineApplication,
) -> None:
    geometry = {"x": 10, "y": 20, "width": 720, "height": 480}
    settings_window._overlay_state.configure(geometry=geometry)

    state = settings_window._handle_desktop_command(
        "overlay.configure", {"geometry": geometry}
    )

    assert state["settings_dirty"] is False


@pytest.mark.parametrize(
    "geometry",
    [
        "legacy-base64",
        {"x": 0, "y": 0, "width": 10, "height": 10},
        {"x": 0, "y": 0, "width": 720, "height": False},
    ],
)
def test_overlay_geometry_command_rejects_invalid_payload_without_partial_apply(
    settings_window: EngineApplication,
    geometry: object,
) -> None:
    with pytest.raises(ValueError, match="geometry"):
        settings_window._handle_desktop_command(
            "overlay.configure",
            {"all": False, "geometry": geometry},
        )

    state = settings_window._desktop_control_state()
    assert state["overlay_all"] is True
    assert state["overlay_geometry"] is None
    assert state["settings_dirty"] is False


def test_settings_load_and_reset_restore_overlay_runtime_state(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._settings_path().write_text(
        json.dumps(
            {
                "toggles": {
                    "all": False,
                    "preview": True,
                    "metrics": False,
                    "lock": False,
                },
                "overlay": {"opacity": 81},
            }
        ),
        encoding="utf-8",
    )

    settings_window._load_settings()

    loaded = settings_window._handle_desktop_command("state.get", {})
    assert loaded["overlay_all"] is False
    assert loaded["overlay_preview"] is True
    assert loaded["overlay_metrics"] is False
    assert loaded["overlay_locked"] is False
    assert loaded["overlay_opacity"] == 81

    applied: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_apply_overlay_state",
        lambda: applied.append(True),
    )
    reset = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["toggles", "overlay"]}
    )
    assert reset["overlay_all"] is True
    assert reset["overlay_preview"] is False
    assert reset["overlay_metrics"] is True
    assert reset["overlay_locked"] is True
    assert reset["overlay_opacity"] == 55
    assert reset["overlay_geometry"] is None
    assert applied == [True]


def test_overlay_reset_sections_do_not_change_each_other(
    settings_window: EngineApplication,
) -> None:
    settings_window._handle_desktop_command(
        "overlay.configure", {"all": False, "opacity": 81}
    )
    settings_window._handle_desktop_command(
        "preferences.configure",
        {
            "overlay_preview": True,
            "overlay_metrics": False,
            "overlay_locked": False,
        },
    )

    toggles_reset = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["toggles"]}
    )
    assert toggles_reset["overlay_all"] is True
    assert toggles_reset["overlay_preview"] is False
    assert toggles_reset["overlay_metrics"] is True
    assert toggles_reset["overlay_locked"] is True
    assert toggles_reset["overlay_opacity"] == 81

    settings_window._handle_desktop_command(
        "preferences.configure",
        {
            "overlay_preview": True,
            "overlay_metrics": False,
            "overlay_locked": False,
        },
    )
    overlay_reset = settings_window._handle_desktop_command(
        "settings.reset", {"sections": ["overlay"]}
    )
    assert overlay_reset["overlay_all"] is True
    assert overlay_reset["overlay_preview"] is True
    assert overlay_reset["overlay_metrics"] is False
    assert overlay_reset["overlay_locked"] is False
    assert overlay_reset["overlay_opacity"] == 55


def test_running_analysis_command_reconciles_two_changes_once(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=False,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    events: list[str] = []
    monkeypatch.setattr(
        settings_window,
        "_stop_analysis_workers",
        lambda: events.append("stop"),
    )
    monkeypatch.setattr(settings_window, "_start_rppg_worker", lambda: events.append("rppg"))
    monkeypatch.setattr(settings_window, "_ensure_belt_calibration", lambda: None)
    monkeypatch.setattr(settings_window, "_emit_web_metrics", lambda **_kwargs: None)

    state = settings_window._handle_desktop_command(
        "analysis.configure",
        {"behavior_enabled": False, "rppg_enabled": True},
    )

    assert events == ["stop", "rppg"]
    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is True


def test_running_analysis_command_rolls_back_controller_state_on_reconcile_failure(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=False,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    original_dirty = settings_window._settings_dirty
    monkeypatch.setattr(settings_window, "_stop_analysis_workers", lambda: None)
    monkeypatch.setattr(
        settings_window, "_start_rppg_worker", lambda: (_ for _ in ()).throw(RuntimeError("topology failed"))
    )
    monkeypatch.setattr(settings_window, "_start_fatigue_worker", lambda: None)

    with pytest.raises(RuntimeError, match="topology failed"):
        settings_window._handle_desktop_command(
            "analysis.configure",
            {"behavior_enabled": False, "rppg_enabled": True},
        )

    plan = settings_window._engine_controller.analysis_snapshot()
    assert plan.fatigue_enabled is True
    assert plan.rppg_enabled is False
    assert settings_window._settings_dirty is original_dirty


def test_running_analysis_command_cleans_adapters_after_fail_closed(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=False,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._pipeline_running = True
    cleanup: list[bool] = []

    monkeypatch.setattr(settings_window, "_stop_analysis_workers", lambda: None)
    monkeypatch.setattr(
        settings_window, "_start_rppg_worker", lambda: (_ for _ in ()).throw(RuntimeError("start failed"))
    )
    monkeypatch.setattr(
        settings_window, "_start_fatigue_worker", lambda: (_ for _ in ()).throw(RuntimeError("rollback failed"))
    )
    monkeypatch.setattr(
        settings_window,
        "_fail_closed_pipeline_adapters",
        lambda: cleanup.append(True),
    )

    with pytest.raises(RuntimeError, match="rollback failed"):
        settings_window._handle_desktop_command(
            "analysis.configure",
            {"behavior_enabled": False, "rppg_enabled": True},
        )

    assert cleanup == [True]


def test_fail_closed_pipeline_cleanup_releases_live_adapter_resources(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[object] = []

    class FakeCameraWorker:
        def detach_bgr_queue(self) -> None:
            events.append("detach")

        def request_stop(self) -> None:
            events.append("camera.stop")

    class FakeCameraThread:
        def quit(self) -> None:
            events.append("thread.quit")

        def wait(self, timeout_ms: int) -> None:
            events.append(("thread.wait", timeout_ms))

    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._pipeline_running = True
    settings_window._recording = True
    _install_runtime_adapter(
        settings_window, "camera", FakeCameraWorker(), FakeCameraThread()
    )
    monkeypatch.setattr(settings_window, "_stop_recording", lambda: events.append("recording"))

    settings_window._fail_closed_pipeline_adapters()

    assert events == [
        "recording",
        "detach",
        "camera.stop",
        "thread.quit",
        ("thread.wait", 3000),
    ]
    assert settings_window._cam_worker is None
    assert settings_window._cam_thread is None
    assert settings_window._pipeline_running is False
    assert settings_window._recording is False
    assert settings_window._engine_controller.pipeline_snapshot().running is False


def test_fail_closed_pipeline_keeps_camera_ownership_when_thread_times_out(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCameraWorker:
        def detach_bgr_queue(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    class FakeCameraThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return False

    worker = FakeCameraWorker()
    thread = FakeCameraThread()
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    _install_runtime_adapter(settings_window, "camera", worker, thread)
    monkeypatch.setattr(settings_window, "_stop_recording", lambda: None)

    settings_window._fail_closed_pipeline_adapters()

    assert settings_window._cam_worker is worker
    assert settings_window._cam_thread is thread
    snapshot = settings_window._engine_controller.pipeline_snapshot()
    assert snapshot.running is False
    assert snapshot.cleanup_pending is True
    with pytest.raises(RuntimeError, match="cleanup"):
        settings_window._engine_controller.start_replay()
    settings_window._engine_runtime.release_adapter("camera", thread)
    settings_window._engine_controller.finish_pipeline_cleanup()


def test_late_camera_finish_releases_pending_cleanup_and_allows_replay(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCameraWorker:
        def detach_bgr_queue(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    class FakeCameraThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return False

    worker = FakeCameraWorker()
    thread = FakeCameraThread()
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    _install_runtime_adapter(settings_window, "camera", worker, thread)
    monkeypatch.setattr(settings_window, "_stop_recording", lambda: True)

    settings_window._fail_closed_pipeline_adapters()
    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is True

    settings_window._engine_runtime.release_adapter("camera", thread)

    assert settings_window._cam_worker is None
    assert settings_window._cam_thread is None
    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is False
    settings_window._engine_controller.start_replay()
    assert settings_window._engine_controller.replay_snapshot().running is True
    settings_window._engine_controller.finish_replay()


def test_headless_hotkeys_update_overlay_state(
    settings_window: EngineApplication,
) -> None:
    settings_window._on_global_hotkey(1)
    state = settings_window._handle_desktop_command("state.get", {})
    assert state["overlay_metrics"] is False
    assert state["settings_dirty"] is True

    settings_window._on_global_hotkey(5)
    state = settings_window._handle_desktop_command("state.get", {})
    assert state["overlay_all"] is False
    assert state["overlay_metrics"] is False
    assert state["overlay_preview"] is False

    settings_window._on_global_hotkey(5)
    state = settings_window._handle_desktop_command("state.get", {})
    assert state["overlay_all"] is True
    assert state["overlay_metrics"] is True
    assert state["overlay_preview"] is True


def test_engine_hotkey_bindings_dispatch_all_six_callbacks(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        settings_window,
        "_toggle_overlay_preference",
        lambda field: calls.append(field),
    )
    monkeypatch.setattr(
        settings_window, "_toggle_pipeline", lambda: calls.append("pipeline")
    )
    monkeypatch.setattr(
        settings_window, "_toggle_recording", lambda: calls.append("recording")
    )
    monkeypatch.setattr(settings_window, "_register_global_hotkeys", lambda: None)

    settings_window._apply_hotkey_shortcuts()

    expected = (
        (1, "toggle_metrics", "Ctrl+Alt+O", "metrics"),
        (2, "toggle_preview", "Ctrl+Alt+P", "preview"),
        (3, "start_stop", "Ctrl+Alt+S", "pipeline"),
        (4, "lock_overlay", "Ctrl+Alt+F8", "locked"),
        (5, "toggle_all", "Ctrl+Alt+A", "all_enabled"),
        (6, "toggle_recording", "Ctrl+Alt+F9", "recording"),
    )
    for hotkey_id, field, sequence, callback_name in expected:
        binding = settings_window._global_hotkey_bindings[hotkey_id]
        assert binding.field == field
        assert binding.sequence == sequence
        before = list(calls)
        settings_window._on_global_hotkey(hotkey_id)
        assert calls == [*before, callback_name]


def test_engine_application_does_not_expose_legacy_widget_renderers(
    settings_window: EngineApplication,
) -> None:
    for name in (
        "_build_central",
        "_build_monitor_page",
        "_build_belt_page",
        "_build_replay_page",
        "_build_settings_page",
        "_replay_queue_upsert",
        "_set_legacy_text",
        "_set_legacy_enabled",
    ):
        assert not hasattr(settings_window, name)


def test_engine_application_does_not_expose_belt_renderers(
    settings_window: EngineApplication,
) -> None:
    for name in (
        "_refresh_belt_cfg_labels",
        "_update_belt_status_label",
        "_reset_belt_panel",
        "_update_belt_panel",
    ):
        assert not hasattr(settings_window, name)


def test_engine_belt_tick_keeps_calibration_and_coordinator_side_effects(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Calibrator:
        def __init__(self) -> None:
            self.observations: list[tuple[float, float, bool, bool, object]] = []

        def observe(
            self,
            timestamp: float,
            bpm: float,
            contact_ok: bool,
            fresh: bool,
            metrics: object,
        ) -> None:
            self.observations.append((timestamp, bpm, contact_ok, fresh, metrics))

    status = type(
        "BeltStatus",
        (),
        {
            "state": "connected",
            "bpm": 72,
            "sensor_contact_detected": True,
            "sensor_contact_supported": True,
        },
    )()
    metrics = object()
    calibrator = Calibrator()
    coordinator_ticks: list[object] = []

    with monkeypatch.context() as patch:
        patch.setattr(settings_window, "_belt_calibrator", calibrator)
        patch.setattr(settings_window, "_latest_rppg_metrics", metrics)
        patch.setattr(settings_window._engine_controller, "belt_status", lambda: status)
        patch.setattr(main_window_module, "hr_is_stale", lambda _status: False)
        patch.setattr(main_window_module, "metrics_to_feed_dict", lambda value: value)
        patch.setattr(
            settings_window,
            "_tick_rppg_param_coordinator",
            lambda value: coordinator_ticks.append(value),
        )

        settings_window._tick_belt_calibration()
        settings_window._tick_belt_calibration()

    assert len(calibrator.observations) == 1
    _, bpm, contact_ok, fresh, observed_metrics = calibrator.observations[0]
    assert (bpm, contact_ok, fresh, observed_metrics) == (72.0, True, True, metrics)
    assert coordinator_ticks == [calibrator, calibrator]


def test_engine_runtime_callbacks_update_headless_state_without_legacy_controls(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    emitted: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_emit_web_metrics",
        lambda *args, **kwargs: emitted.append(bool(kwargs.get("force", False))),
    )

    settings_window._on_camera_info("MJPG", 1280, 720, 30.0)
    settings_window._on_fps(29.5)
    settings_window._set_profile_status("個人基線：測試")

    assert settings_window._last_camera_info == {
        "codec": "MJPG",
        "width": 1280,
        "height": 720,
    }
    assert settings_window._last_fps == 29.5
    assert settings_window._desktop_control_state()["profile_status"] == "個人基線：測試"
    assert emitted == [True, False]


def test_engine_metric_callbacks_keep_non_visual_side_effects(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    rppg_metrics = object()
    fatigue_metrics = object()
    fused_score = object()
    events: list[tuple[str, object]] = []
    _install_runtime_adapter(settings_window, "combined", object(), object())
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "handle_alarm_metrics",
        lambda metrics: events.append(("alarm", metrics)),
    )
    monkeypatch.setattr(
        settings_window,
        "_feed_baseline_collectors",
        lambda metrics: events.append(("baseline", metrics)),
    )
    monkeypatch.setattr(
        settings_window,
        "_record_metrics",
        lambda: events.append(("record", None)),
    )
    monkeypatch.setattr(
        settings_window,
        "_emit_web_metrics",
        lambda **_kwargs: events.append(("emit", None)),
    )

    settings_window._on_rppg_metrics(rppg_metrics)
    assert settings_window._latest_rppg_metrics is rppg_metrics
    assert events == [("record", None), ("emit", None)]

    events.clear()
    settings_window._on_fatigue_metrics(fatigue_metrics)
    assert settings_window._latest_fatigue_metrics is fatigue_metrics
    assert events == [
        ("alarm", fatigue_metrics),
        ("baseline", fatigue_metrics),
        ("record", None),
        ("emit", None),
    ]

    events.clear()
    settings_window._on_fused_score(fused_score)
    assert settings_window._latest_fused_score is fused_score
    assert events == [("record", None), ("emit", None)]


@pytest.mark.parametrize(
    ("failure_handler", "stop_method", "behavior", "rppg"),
    [
        (
            "_on_combined_failed",
            "_stop_combined_worker",
            True,
            True,
        ),
        (
            "_on_rppg_failed",
            "_stop_rppg_worker",
            False,
            True,
        ),
        (
            "_on_fatigue_failed",
            "_stop_fatigue_worker",
            True,
            False,
        ),
    ],
)
def test_headless_worker_failure_applies_analysis_cleanup(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    failure_handler: str,
    stop_method: str,
    behavior: bool,
    rppg: bool,
) -> None:
    settings_window._engine_controller.configure_analysis(
        fatigue_enabled=behavior,
        rppg_enabled=rppg,
    )
    monkeypatch.setattr(settings_window, stop_method, lambda: None)
    monkeypatch.setattr(settings_window, "_append_log", lambda _message: None)
    monkeypatch.setattr(settings_window, "_notify_user", lambda _title, _message: None)

    getattr(settings_window, failure_handler)("boom")

    state = settings_window._desktop_control_state()
    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is False


def test_hotkeys_configure_replaces_all_shortcuts(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
        binding.sequence
        for binding in settings_window._global_hotkey_bindings.values()
    ] == list(hotkeys.values())


def test_hotkeys_configure_rolls_back_when_apply_fails(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
    settings_window: EngineApplication,
) -> None:
    class Runtime:
        supported = True

        def __init__(self) -> None:
            self.bindings: dict[int, tuple[int, int]] | None = None

        def register(
            self,
            bindings: dict[int, tuple[int, int]],
        ) -> tuple[HotkeyRegistrationFailure, ...]:
            self.bindings = bindings
            return tuple(
                HotkeyRegistrationFailure(
                    hotkey_id=hotkey_id,
                    code=1409,
                    reason="already_registered",
                )
                for hotkey_id in bindings
            )

        def unregister(self) -> tuple[()]:
            return ()

    runtime = Runtime()
    settings_window._global_hotkey_runtime = runtime

    _REGISTER_GLOBAL_HOTKEYS(settings_window)

    assert runtime.bindings is not None
    assert len(runtime.bindings) == 6
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
    settings_window: EngineApplication, hotkeys: dict[str, object]
) -> None:
    before = settings_window._handle_desktop_command("state.get", {})["hotkeys"]

    with pytest.raises(ValueError, match="hotkeys"):
        settings_window._handle_desktop_command(
            "hotkeys.configure", {"hotkeys": hotkeys}
        )

    assert settings_window._handle_desktop_command("state.get", {})["hotkeys"] == before


def test_user_profile_configure_accepts_boundaries_and_derives_bmi(
    settings_window: EngineApplication,
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
    settings_window: EngineApplication, user_profile: dict[str, object]
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
    settings_window: EngineApplication,
) -> None:
    alarm = _alarm_payload()

    state = settings_window._handle_desktop_command(
        "alarm.configure", {"alarm": alarm}
    )

    assert state["alarm"] == alarm
    controller = settings_window._engine_runtime.alarm_controller
    assert controller is not None
    assert controller.config.to_dict() == alarm
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
    settings_window: EngineApplication, changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="alarm"):
        settings_window._handle_desktop_command(
            "alarm.configure", {"alarm": _alarm_payload(**changes)}
        )


def test_alarm_configure_rejects_missing_file_without_fallback(
    settings_window: EngineApplication, tmp_path: Path
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

    def close(self) -> None:
        pass


def test_alarm_test_uses_draft_without_mutating_runtime(
    settings_window: EngineApplication, tmp_path: Path
) -> None:
    sound_path = tmp_path / "draft.wav"
    sound_path.write_bytes(b"RIFF")
    runtime = AlarmConfig.defaults()
    playback = _PlaybackSpy()
    settings_window._alarm_config = runtime
    controller = FatigueAlarmController(runtime, playback=playback)
    settings_window._engine_runtime.replace_alarm_controller(
        controller
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
    assert settings_window._engine_runtime.alarm_controller is controller
    assert controller.config is runtime
    assert state["settings_dirty"] is False
    assert state["command_result"] == {
        "command": "alarm.test",
        "scenario": "critical",
        "dispatched": True,
        "source": "file",
    }


def test_alarm_test_reports_builtin_source(settings_window: EngineApplication) -> None:
    runtime = AlarmConfig.defaults()
    playback = _PlaybackSpy()
    settings_window._alarm_config = runtime
    settings_window._engine_runtime.replace_alarm_controller(
        FatigueAlarmController(runtime, playback=playback)
    )

    state = settings_window._handle_desktop_command(
        "alarm.test", {"scenario": "drowsy"}
    )

    assert playback.builtins == ["drowsy"]
    assert state["command_result"]["source"] == "builtin"


def test_alarm_test_raises_typed_error_when_no_source(
    settings_window: EngineApplication,
) -> None:
    draft = _alarm_payload(use_builtin_fallback=False)

    with pytest.raises(AlarmUnplayableError) as exc_info:
        settings_window._handle_desktop_command(
            "alarm.test", {"scenario": "critical", "alarm": draft}
        )

    assert exc_info.value.code == "alarm_unplayable"


def test_settings_reset_only_resets_selected_sections(
    settings_window: EngineApplication,
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
    controller = settings_window._engine_runtime.alarm_controller
    assert controller is not None
    assert controller.config.to_dict() == state["alarm"]
    assert state["user_profile"] == {
        "age": 40,
        "height_cm": 180,
        "weight_kg": 90.0,
        "bmi": 27.8,
    }
    assert state["settings_dirty"] is True


def test_settings_save_persists_atomically_and_clears_dirty(
    settings_window: EngineApplication,
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


def test_settings_and_recordings_use_configured_data_root(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "runtime-data"
    monkeypatch.setenv("NCFD_DATA_ROOT", str(data_root))
    monkeypatch.setattr(
        settings_window,
        "_settings_path",
        lambda: _SETTINGS_PATH(settings_window),
    )

    settings_window._handle_desktop_command("settings.save", {})
    recordings = _RECORDINGS_DIR(settings_window)

    assert (data_root / "settings.json").exists()
    assert recordings == data_root / "recordings"
    assert recordings.is_dir()


def test_settings_save_replace_failure_preserves_old_file_and_dirty_state(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
    settings_window: EngineApplication,
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
    settings_window: EngineApplication, command: str, args: dict[str, object]
) -> None:
    assert settings_window._handle_desktop_command("state.get", {})["settings_dirty"] is False

    state = settings_window._handle_desktop_command(command, args)

    assert state["settings_dirty"] is True


def test_web_lan_marks_dirty_and_schedules_nonblocking_restart(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_schedule_web_server_restart",
        lambda: scheduled.append(True),
        raising=False,
    )

    state = settings_window._handle_desktop_command(
        "settings.action", {"action": "web_lan", "enabled": True}
    )

    assert state["web_allow_lan"] is True
    assert state["settings_dirty"] is True
    assert scheduled == [True]


def test_headless_web_preference_round_trip_preserves_bind_contract(
    settings_window: EngineApplication,
) -> None:
    settings_window._settings_path().write_text(
        json.dumps({"web": {"allow_lan": True}}),
        encoding="utf-8",
    )

    settings_window._load_settings()

    assert settings_window._web_bind_host() == "0.0.0.0"
    state = settings_window._handle_desktop_command("settings.save", {})
    persisted = json.loads(
        settings_window._settings_path().read_text(encoding="utf-8")
    )
    assert state["web_allow_lan"] is True
    assert persisted["web"] == {"allow_lan": True}


@pytest.mark.parametrize(
    ("command", "args", "error"),
    [
        ("benchmark.set", {"enabled": True}, "Unsupported desktop command"),
        ("replay.choose", {}, "Unsupported desktop command"),
        ("settings.action", {"action": "hotkeys"}, "Unsupported settings action"),
        ("settings.action", {"action": "profile"}, "Unsupported settings action"),
        ("settings.action", {"action": "alarm"}, "Unsupported settings action"),
        ("settings.action", {"action": "reset"}, "Unsupported settings action"),
    ],
)
def test_engine_rejects_retired_qt_visible_actions(
    settings_window: EngineApplication,
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
    settings_window: EngineApplication,
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


def test_headless_replay_state_does_not_depend_on_legacy_widget_mirrors(
    settings_window: EngineApplication,
    tmp_path: Path,
) -> None:
    configured = settings_window._handle_desktop_command(
        "replay.configure",
        {"path": str(tmp_path), "jobs": 4, "annotated": True},
    )

    assert configured["replay_dataset_dir"] == str(tmp_path)
    assert configured["replay_jobs"] == 4
    assert configured["replay_annotated"] is True
    assert not hasattr(settings_window, "_spn_replay_jobs")
    assert not hasattr(settings_window, "_chk_replay_annotated")


def test_replay_configure_is_atomic_when_later_field_is_invalid(
    settings_window: EngineApplication,
    tmp_path: Path,
) -> None:
    before = settings_window._replay_state.snapshot()

    with pytest.raises(ValueError, match="jobs"):
        settings_window._handle_desktop_command(
            "replay.configure",
            {"path": str(tmp_path), "jobs": 9, "annotated": True},
        )

    assert settings_window._replay_state.snapshot() == before


def test_headless_replay_progress_projects_without_qt_replay_widgets(
    settings_window: EngineApplication,
) -> None:
    summary = ReplayVideoSummary(
        subject="01",
        label="0",
        label_name="Alert",
        video_path="sample.mp4",
        frames=12,
        face_frames=10,
        fps=30.0,
        width=640,
        height=480,
    )
    settings_window._replay_state.begin(
        mode_label="回放中",
        parallel_status_text="處理清單：等待第一支影片",
    )

    settings_window._on_replay_progress("video_start", 1, 2, summary)
    settings_window._on_replay_progress("video_done", 1, 2, summary)

    state = settings_window._handle_desktop_command("state.get", {})
    assert state["replay_total"] == 2
    assert state["replay_done"] == 1
    assert "已完成 1/2" in state["replay_current"]
    assert "已完成：1/2" in state["replay_parallel_status"]


def test_replay_runtime_state_supplies_existing_worker_parameters(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class FakeThread:
        def __init__(self, _parent) -> None:
            self.started = FakeSignal()
            self.finished = FakeSignal()

        def start(self) -> None:
            captured["started"] = True

        def quit(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    class FakeWorker:
        def __init__(self, dataset_root: Path, **kwargs: object) -> None:
            captured["dataset_root"] = dataset_root
            captured.update(kwargs)
            self.progress = FakeSignal()
            self.preview_frame = FakeSignal()
            self.finished_ok = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

        def moveToThread(self, _thread) -> None:
            pass

        def run(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    monkeypatch.setattr(settings_window._engine_runtime, "_thread_factory", FakeThread)
    monkeypatch.setattr(main_window_module, "VideoReplayWorker", FakeWorker)
    settings_window._replay_state.configure(
        dataset_dir=tmp_path,
        jobs=3,
        annotated=True,
    )

    settings_window._start_replay_run(
        jobs=3,
        preview_enabled=False,
        mode_label="平行驗證中 x3",
    )

    assert captured == {
        "dataset_root": tmp_path,
        "write_annotated_video": True,
        "jobs": 3,
        "preview_enabled": False,
        "started": True,
    }
    assert settings_window._engine_controller.replay_snapshot().running is True
    thread = settings_window._replay_thread
    assert thread is not None
    assert settings_window._engine_runtime.release_adapter("replay", thread) is True


def test_replay_start_failure_rolls_back_controller_and_presentation(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = settings_window._replay_state.configure(
        dataset_dir=tmp_path,
        jobs=2,
        annotated=False,
    )

    class FailingThread:
        def __init__(self, _parent) -> None:
            self.started = type("Signal", (), {"connect": lambda self, callback: None})()
            self.finished = type("Signal", (), {"connect": lambda self, callback: None})()

        def start(self) -> None:
            raise RuntimeError("thread start failed")

        def quit(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    class FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class FakeWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = FakeSignal()
            self.preview_frame = FakeSignal()
            self.finished_ok = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

        def moveToThread(self, _thread) -> None:
            pass

        def run(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    monkeypatch.setattr(settings_window._engine_runtime, "_thread_factory", FailingThread)
    monkeypatch.setattr(main_window_module, "VideoReplayWorker", FakeWorker)

    with pytest.raises(RuntimeError, match="thread start failed"):
        settings_window._start_replay_run(
            jobs=2,
            preview_enabled=False,
            mode_label="平行驗證中 x2",
        )

    assert settings_window._replay_state.snapshot() == before
    assert settings_window._engine_controller.replay_snapshot().running is False
    assert settings_window._replay_thread is None
    assert settings_window._replay_worker is None


def test_replay_command_uses_controller_pipeline_state(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._pipeline_running = False
    settings_window._recording = False
    settings_window._replay_state.configure(dataset_dir=tmp_path)
    starts: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_start_replay",
        lambda: starts.append(True),
    )

    with pytest.raises(BusyError, match="pipeline"):
        settings_window._handle_desktop_command(
            "replay.set",
            {"enabled": True, "mode": "single"},
        )

    assert starts == []
    assert settings_window._engine_controller.replay_snapshot().running is False


def test_replay_start_rechecks_controller_before_creating_adapter(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._replay_state.configure(dataset_dir=tmp_path)
    start_replay = settings_window._start_replay
    thread_created: list[bool] = []

    def start_after_pipeline_race() -> None:
        settings_window._engine_controller.configure_analysis(
            rppg_enabled=True,
            fatigue_enabled=True,
        )
        settings_window._engine_controller.start_pipeline()
        start_replay()

    def fail_if_thread_created(*args, **kwargs):
        thread_created.append(True)
        raise AssertionError("replay QThread must not be created")

    monkeypatch.setattr(settings_window, "_start_replay", start_after_pipeline_race)
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "_thread_factory",
        fail_if_thread_created,
    )

    state = settings_window._handle_desktop_command(
        "replay.set",
        {"enabled": True, "mode": "single"},
    )

    assert thread_created == []
    assert state["pipeline_running"] is True
    assert state["replay_running"] is False


def test_app_shutdown_command_defers_cleanup_through_engine_runtime(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[tuple[int, object]] = []
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "defer",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)),
    )

    state = settings_window._handle_desktop_command("app.shutdown", {})

    assert state["engine_mode"] is True
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0
    assert getattr(scheduled[0][1], "__self__", None) is settings_window


def test_engine_shutdown_waits_for_active_replay(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    replay_thread = object()
    _install_runtime_adapter(settings_window, "replay", object(), replay_thread)
    settings_window._engine_controller.start_replay()
    monkeypatch.setattr(settings_window, "_stop_replay", lambda: events.append("stop"))
    monkeypatch.setattr(
        settings_window,
        "_cleanup_runtime",
        lambda: events.append("cleanup"),
        raising=False,
    )

    class FakeApplication:
        @staticmethod
        def instance():
            raise AssertionError("application must not quit before replay finishes")

    monkeypatch.setattr("gui.main_window.QApplication", FakeApplication)

    settings_window._shutdown_engine()

    replay = settings_window._engine_controller.replay_snapshot()
    assert replay.shutdown_pending is True
    assert replay.stopping is True
    assert events == ["stop"]
    settings_window._engine_controller.finish_replay()
    settings_window._engine_runtime.release_adapter("replay", replay_thread)


def test_engine_shutdown_cleans_runtime_before_quit_without_closing_window(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def cleanup_runtime() -> bool:
        events.append("cleanup")
        return True

    monkeypatch.setattr(
        settings_window,
        "_cleanup_runtime",
        cleanup_runtime,
        raising=False,
    )
    assert not hasattr(settings_window, "close")

    class FakeApp:
        def quit(self) -> None:
            events.append("quit")

    class FakeApplication:
        @staticmethod
        def instance():
            return FakeApp()

    monkeypatch.setattr("gui.main_window.QApplication", FakeApplication)

    settings_window._shutdown_engine()

    assert events == ["cleanup", "quit"]


def test_engine_shutdown_resumes_after_replay_thread_finishes(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    replay_thread = object()
    _install_runtime_adapter(settings_window, "replay", object(), replay_thread)
    settings_window._engine_controller.start_replay()
    assert settings_window._engine_controller.request_shutdown() == "stop_replay"
    def cleanup_runtime() -> bool:
        events.append("cleanup")
        return True

    monkeypatch.setattr(
        settings_window,
        "_cleanup_runtime",
        cleanup_runtime,
        raising=False,
    )

    class FakeApp:
        def quit(self) -> None:
            events.append("quit")

    class FakeApplication:
        @staticmethod
        def instance():
            return FakeApp()

    monkeypatch.setattr("gui.main_window.QApplication", FakeApplication)

    settings_window._engine_runtime.release_adapter("replay", replay_thread)

    assert settings_window._replay_thread is None
    assert settings_window._replay_worker is None
    assert settings_window._engine_controller.replay_snapshot().running is False
    assert events == ["cleanup", "quit"]


def test_engine_shutdown_resumes_only_after_adapter_thread_finishes(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    cleanup_results = [False, True]
    thread = object()
    _install_runtime_adapter(settings_window, "camera", object(), thread)

    def cleanup_runtime() -> bool:
        result = cleanup_results.pop(0) if cleanup_results else True
        events.append(f"cleanup:{result}")
        return result

    class FakeApp:
        def quit(self) -> None:
            events.append("quit")

    class FakeApplication:
        @staticmethod
        def instance():
            return FakeApp()

    monkeypatch.setattr(settings_window, "_cleanup_runtime", cleanup_runtime)
    monkeypatch.setattr(main_window_module, "QApplication", FakeApplication)
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "defer",
        lambda delay_ms, callback: (
            events.append(f"scheduled:{delay_ms}"),
            callback(),
        ),
    )

    settings_window._shutdown_engine()

    assert settings_window._runtime_shutdown_waiting_for_adapters is True
    assert events == ["cleanup:False"]

    settings_window._engine_runtime.release_adapter("camera", thread)

    assert settings_window._cam_thread is None
    assert settings_window._runtime_shutdown_waiting_for_adapters is False
    assert events == ["cleanup:False", "scheduled:0", "cleanup:True", "quit"]


def test_engine_shutdown_retries_cleanup_error_before_quit(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    cleanup_results = [False, True]

    def cleanup_runtime() -> bool:
        result = cleanup_results.pop(0) if cleanup_results else True
        events.append(f"cleanup:{result}")
        return result

    class FakeApp:
        def quit(self) -> None:
            events.append("quit")

    class FakeApplication:
        @staticmethod
        def instance():
            return FakeApp()

    monkeypatch.setattr(settings_window, "_cleanup_runtime", cleanup_runtime)
    monkeypatch.setattr(main_window_module, "QApplication", FakeApplication)
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "defer",
        lambda delay_ms, callback: (
            events.append(f"scheduled:{delay_ms}"),
            callback(),
        ),
    )

    settings_window._shutdown_engine()

    assert settings_window._runtime_cleanup_retry_attempted is True
    assert settings_window._runtime_cleanup_retry_scheduled is False
    assert events == ["cleanup:False", "scheduled:100", "cleanup:True", "quit"]


def test_runtime_cleanup_is_ordered_and_idempotent(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class FakeOverlay:
        def hide(self) -> None:
            events.append("overlay.hide")

        def close(self) -> None:
            events.append("overlay.close")

    settings_window._belt_calibrator = object()  # type: ignore[assignment]
    settings_window._preview_overlay = FakeOverlay()  # type: ignore[assignment]
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "cancel_timer",
        lambda kind: events.append(f"{kind}.cancel"),
    )
    monkeypatch.setattr(
        settings_window,
        "_unregister_global_hotkeys",
        lambda: events.append("hotkeys.unregister"),
    )
    monkeypatch.setattr(
        settings_window,
        "_cancel_pending_auto_capture_timer",
        lambda: events.append("auto_capture.cancel"),
    )
    monkeypatch.setattr(
        settings_window,
        "_stop_belt_calibration",
        lambda: events.append("belt_calibration.stop"),
    )
    monkeypatch.setattr(
        settings_window._engine_controller,
        "stop_belt",
        lambda: events.append("belt.stop"),
    )
    monkeypatch.setattr(
        settings_window,
        "_stop_web_server",
        lambda: events.append("web.stop"),
    )
    monkeypatch.setattr(
        settings_window,
        "_stop_recording",
        lambda: events.append("recording.stop"),
    )
    monkeypatch.setattr(
        settings_window,
        "_stop_camera_worker",
        lambda: events.append("camera.stop"),
    )
    monkeypatch.setattr(
        settings_window._engine_runtime,
        "close_alarm",
        lambda: events.append("alarm.close"),
    )

    settings_window._cleanup_runtime()
    settings_window._cleanup_runtime()

    assert events == [
        "desktop_command.cancel",
        "hotkeys.unregister",
        "auto_capture.cancel",
        "belt_calibration.stop",
        "belt_tick.cancel",
        "belt.stop",
        "web.stop",
        "recording.stop",
        "camera.stop",
        "alarm.close",
        "overlay.hide",
        "overlay.close",
    ]
    assert settings_window._web_restart_shutdown is True
    assert settings_window._web_restart_scheduled is False


def test_runtime_cleanup_guard_allows_retry_after_failure(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unregister = settings_window._unregister_global_hotkeys
    attempts = 0

    def flaky_unregister() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("cleanup failed")
        original_unregister()

    monkeypatch.setattr(
        settings_window,
        "_unregister_global_hotkeys",
        flaky_unregister,
    )

    assert settings_window._cleanup_runtime() is False

    assert settings_window._runtime_cleanup_in_progress is False
    assert settings_window._runtime_cleanup_complete is False

    assert settings_window._cleanup_runtime() is True

    assert attempts == 2
    assert settings_window._runtime_cleanup_complete is True


def test_camera_failure_stops_active_recording_runtime(
    settings_window: EngineApplication,
) -> None:
    events: list[object] = []

    class FakeMetricsRecorder:
        def close(self) -> None:
            events.append("metrics.close")

    class FakeVideoWorker:
        def request_stop(self) -> None:
            events.append("video.stop")

    class FakeVideoThread:
        def quit(self) -> None:
            events.append("thread.quit")

        def wait(self, timeout_ms: int) -> None:
            events.append(("thread.wait", timeout_ms))

        def deleteLater(self) -> None:
            pass

    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._engine_controller.start_recording()
    settings_window._pipeline_running = True
    settings_window._recording = True
    settings_window._metrics_recorder = FakeMetricsRecorder()  # type: ignore[assignment]
    _install_runtime_adapter(
        settings_window,
        "video",
        FakeVideoWorker(),
        FakeVideoThread(),
    )

    settings_window._on_camera_failed("camera disconnected")

    assert events == [
        "metrics.close",
        "video.stop",
        "thread.quit",
        ("thread.wait", 2000),
    ]
    assert settings_window._recording is False
    assert settings_window._metrics_recorder is None
    assert settings_window._video_worker is None
    assert settings_window._video_thread is None
    assert settings_window._engine_controller.pipeline_snapshot().running is False
    assert settings_window._engine_controller.pipeline_snapshot().recording is False


def test_camera_failure_timeout_blocks_replay_until_adapter_release(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCameraWorker:
        def detach_bgr_queue(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    class FakeCameraThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return False

    worker = FakeCameraWorker()
    thread = FakeCameraThread()
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.start_pipeline()
    _install_runtime_adapter(settings_window, "camera", worker, thread)
    monkeypatch.setattr(settings_window, "_stop_analysis_workers", lambda: None)

    settings_window._on_camera_failed("camera disconnected")

    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is True
    with pytest.raises(RuntimeError, match="cleanup"):
        settings_window._engine_controller.start_replay()

    settings_window._engine_runtime.release_adapter("camera", thread)

    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is False
    settings_window._engine_controller.start_replay()
    settings_window._engine_controller.finish_replay()


def test_pipeline_command_rolls_back_when_replay_is_active(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.start_replay()
    camera_started: list[bool] = []
    monkeypatch.setattr(
        settings_window,
        "_start_camera_worker",
        lambda: camera_started.append(True),
    )
    monkeypatch.setattr(
        settings_window,
        "_analysis_lifecycle_ports",
        lambda: AnalysisLifecyclePorts(
            stop_all=lambda: None,
            start_combined=lambda: None,
            start_rppg=lambda: None,
            start_fatigue=lambda: None,
            restore_raw_routing=lambda: None,
        ),
    )

    with pytest.raises(BusyError, match="replay"):
        settings_window._handle_desktop_command(
            "pipeline.set",
            {"enabled": True},
        )

    assert camera_started == []
    assert settings_window._pipeline_running is False
    assert settings_window._engine_controller.pipeline_snapshot().running is False
    assert settings_window._engine_controller.replay_snapshot().running is True


def test_pipeline_command_uses_controller_snapshot_for_success_and_stop(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    monkeypatch.setattr(settings_window, "_start_camera_worker", lambda: None)
    monkeypatch.setattr(settings_window, "_stop_camera_worker", lambda: None)
    monkeypatch.setattr(
        settings_window,
        "_analysis_lifecycle_ports",
        lambda: AnalysisLifecyclePorts(
            stop_all=lambda: None,
            start_combined=lambda: None,
            start_rppg=lambda: None,
            start_fatigue=lambda: None,
            restore_raw_routing=lambda: None,
        ),
    )

    started = settings_window._handle_desktop_command(
        "pipeline.set",
        {"enabled": True},
    )
    assert started["pipeline_running"] is True
    assert settings_window._engine_controller.pipeline_snapshot().running is True

    settings_window._pipeline_running = False
    stopped = settings_window._handle_desktop_command(
        "pipeline.set",
        {"enabled": False},
    )
    assert stopped["pipeline_running"] is False
    assert settings_window._engine_controller.pipeline_snapshot().running is False


@pytest.mark.parametrize("failure_stage", ["camera", "analysis"])
def test_pipeline_command_rolls_back_adapter_start_failure(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    cleanup: list[str] = []

    if failure_stage == "camera":
        monkeypatch.setattr(
            settings_window,
            "_start_camera_worker",
            lambda: (_ for _ in ()).throw(RuntimeError("camera failed")),
        )
    else:
        monkeypatch.setattr(settings_window, "_start_camera_worker", lambda: None)
        monkeypatch.setattr(
            settings_window._engine_controller,
            "activate_current_analysis",
            lambda _ports: (_ for _ in ()).throw(RuntimeError("analysis failed")),
        )
    monkeypatch.setattr(
        settings_window,
        "_stop_camera_worker",
        lambda: cleanup.append("stop"),
    )

    state = settings_window._handle_desktop_command(
        "pipeline.set",
        {"enabled": True},
    )

    assert state["pipeline_running"] is False
    assert settings_window._pipeline_running is False
    assert settings_window._engine_controller.pipeline_snapshot().running is False
    assert cleanup == ["stop"]


def test_state_get_uses_controller_lifecycle_snapshot(
    settings_window: EngineApplication,
) -> None:
    settings_window._pipeline_running = True
    settings_window._recording = True

    state = settings_window._handle_desktop_command("state.get", {})

    assert state["pipeline_running"] is False
    assert state["recording"] is False


def test_recording_command_rolls_back_partial_writer_failure(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeMetricsRecorder:
        def close(self) -> None:
            events.append("metrics.close")

    class FakeVideoWorker:
        def request_stop(self) -> None:
            events.append("video.stop")

    class FakeVideoThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return True

        def deleteLater(self) -> None:
            pass

    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._pipeline_running = True

    def fail_after_partial_setup() -> None:
        settings_window._metrics_recorder = FakeMetricsRecorder()  # type: ignore[assignment]
        _install_runtime_adapter(
            settings_window,
            "video",
            FakeVideoWorker(),
            FakeVideoThread(),
        )
        raise OSError("writer unavailable")

    monkeypatch.setattr(settings_window, "_start_recording", fail_after_partial_setup)

    state = settings_window._handle_desktop_command(
        "recording.set",
        {"enabled": True},
    )

    assert state["recording"] is False
    assert settings_window._recording is False
    assert settings_window._metrics_recorder is None
    assert settings_window._video_worker is None
    assert settings_window._engine_controller.pipeline_snapshot().recording is False
    assert events == ["metrics.close", "video.stop"]


def test_recording_command_uses_controller_pipeline_state(
    settings_window: EngineApplication,
) -> None:
    settings_window._pipeline_running = True

    with pytest.raises(ValueError, match="pipeline"):
        settings_window._handle_desktop_command(
            "recording.set",
            {"enabled": True},
        )

    assert settings_window._engine_controller.pipeline_snapshot().running is False
    assert settings_window._engine_controller.pipeline_snapshot().recording is False


def test_video_failure_stops_all_recording_resources(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._engine_controller.start_recording()
    settings_window._recording = True
    cleanup: list[bool] = []

    def stop_recording() -> None:
        cleanup.append(True)
        settings_window._engine_controller.stop_recording()

    monkeypatch.setattr(settings_window, "_stop_recording", stop_recording)

    settings_window._on_video_recording_failed("writer failed")

    assert settings_window._recording is False
    assert settings_window._engine_controller.pipeline_snapshot().recording is False
    assert cleanup == [True]


def test_video_warning_keeps_recording_active(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    settings_window._engine_controller.start_recording()
    settings_window._recording = True
    cleanup: list[bool] = []
    monkeypatch.setattr(settings_window, "_stop_recording", lambda: cleanup.append(True))

    settings_window._on_video_recording_warning("fallback active")

    assert settings_window._recording is True
    assert settings_window._engine_controller.pipeline_snapshot().recording is True
    assert cleanup == []


def test_recording_stop_keeps_video_ownership_when_thread_times_out(
    settings_window: EngineApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeVideoWorker:
        def request_stop(self) -> None:
            pass

    class FakeVideoThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return False

    worker = FakeVideoWorker()
    thread = FakeVideoThread()
    frame_queue: queue.Queue = queue.Queue()
    _install_runtime_adapter(settings_window, "video", worker, thread)
    settings_window._video_queue = frame_queue
    settings_window._recording_video_path = Path("capture.mp4")
    settings_window._runtime_shutdown_waiting_for_adapters = True
    scheduled: list[int] = []

    monkeypatch.setattr(
        settings_window._engine_runtime,
        "defer",
        lambda delay_ms, _callback: scheduled.append(delay_ms),
    )

    stopped = settings_window._stop_recording()

    assert stopped is False
    assert settings_window._video_worker is worker
    assert settings_window._video_thread is thread
    assert settings_window._video_queue is frame_queue
    settings_window._engine_runtime.release_adapter("video", thread)
    assert settings_window._video_worker is None
    assert settings_window._video_thread is None
    assert settings_window._video_queue is None
    assert settings_window._recording_video_path is None
    assert scheduled == [0]


def test_recording_start_rejects_previous_video_cleanup(
    settings_window: EngineApplication,
) -> None:
    thread = object()
    _install_runtime_adapter(settings_window, "video", object(), thread)

    with pytest.raises(RuntimeError, match="cleanup"):
        settings_window._start_recording()

    settings_window._engine_runtime.release_adapter("video", thread)


def test_normal_camera_stop_timeout_blocks_restart_until_late_finish(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCameraWorker:
        def detach_bgr_queue(self) -> None:
            pass

        def request_stop(self) -> None:
            pass

    class FakeCameraThread:
        def quit(self) -> None:
            pass

        def wait(self, _timeout_ms: int) -> bool:
            return False

    thread = FakeCameraThread()
    settings_window._engine_controller.replace_cameras([CameraDevice(0, "Camera")])
    settings_window._engine_controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    settings_window._engine_controller.start_pipeline()
    _install_runtime_adapter(settings_window, "camera", FakeCameraWorker(), thread)
    monkeypatch.setattr(settings_window, "_stop_recording", lambda: True)

    settings_window._stop_camera_worker()

    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is True
    with pytest.raises(RuntimeError, match="cleanup"):
        settings_window._engine_controller.start_pipeline()

    settings_window._engine_runtime.release_adapter("camera", thread)
    assert settings_window._engine_controller.pipeline_snapshot().cleanup_pending is False


def test_analysis_command_allows_raw_camera_mode(
    settings_window: EngineApplication,
) -> None:
    state = settings_window._handle_desktop_command(
        "analysis.configure",
        {"behavior_enabled": False, "rppg_enabled": False},
    )

    assert state["behavior_enabled"] is False
    assert state["rppg_enabled"] is False


def test_web_reset_updates_state_and_schedules_nonblocking_restart(
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_window._web_preferences.configure(allow_lan=True)
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
    settings_window: EngineApplication, qt_app: QApplication, monkeypatch: pytest.MonkeyPatch
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
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
    settings_window: EngineApplication, monkeypatch: pytest.MonkeyPatch
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
