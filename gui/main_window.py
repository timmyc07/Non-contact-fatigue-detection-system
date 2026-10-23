from __future__ import annotations

import json
import logging
import os
import queue
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Qt, QThread, QTimer, Slot
from PySide6.QtGui import (
    QImage,
    QImageWriter,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
)

from gui.alarm_config import (
    ALARM_SCENARIO_KEYS,
    AlarmConfig,
)
from gui.belt_runtime import BeltRuntime
from gui.camera_scan_worker import CameraScanWorker
from gui.camera_stream_worker import CameraStreamWorker
from gui.capture_preferences_state import CapturePreferencesState
from gui.combined_worker import CombinedWorker
from gui.desktop_models import HotkeyConfig, UserProfile
from gui.desktop_control import (
    AlarmUnplayableError,
    BusyError,
    DESKTOP_CONTROL_API_VERSION,
    DesktopCommandBroker,
    HotkeyApplyError,
    SettingsWriteError,
)
from gui.desktop_settings_contract import (
    parse_alarm_config,
    parse_settings_reset_sections,
    parse_user_profile,
)
from gui.engine_controller import (
    AnalysisLifecyclePorts,
    CameraDevice,
    EngineController,
)
from gui.engine_runtime import EngineRuntime
from gui.fatigue_scorer import FuserConfig
from gui.fatigue_worker import FatigueWorker
from gui.global_hotkeys import GlobalHotkeyRuntime
from gui.metrics_recorder import MetricsRecorder
from gui.overlay_runtime_state import OverlayRuntimeState
from gui.personal_profile import (
    PersonalBaselineCollector,
    PersonalProfileStore,
    resolve_active_baseline,
)
from gui.replay_runtime_state import ReplayRuntimeState
from gui.runtime_paths import data_path
from gui.video_replay import ReplayBatchResult, VideoReplayWorker, ReplayVideoSummary
from gui.web_preferences_state import WebPreferencesState
from rppg.belt_truth_capture import BeltTruthCaptureWriter
from rppg.hr_belt_ble import HrBeltConfig, hr_is_stale, load_hr_belt_config
from rppg.watch_physio import compute_watch_physio
from rppg.rppg_worker import RppgWorker, ROI_BASE_WEIGHTS, resolve_roi_weights_override
from rppg.adaptive_calibration import CONF_LOW, OnlineBpmCalibrator, RppgParamCoordinator
from rppg.calibration import (
    CalibrationVersionStore,
    apply_calibration_to_metrics,
    effective_bpm,
    metrics_to_feed_dict,
    write_live_feed,
)
from gui.video_recorder import VideoRecorderWorker
from gui.web_server import (
    MetricsBuffer,
    PlaybackManager,
    WEB_DASHBOARD_DEFAULT_PORT,
    WebServerThread,
    format_web_dashboard_urls,
)

WEB_PREVIEW_TARGET_FPS = 30.0
logger = logging.getLogger(__name__)


def _classify_log_message(message: str, *, warning_priority: bool = False) -> str:
    text = str(message)
    warning = "⚠" in text or "警告" in text
    error = "✗" in text or "錯誤" in text or "失敗" in text
    if warning_priority and warning:
        return "warning"
    if error:
        return "error"
    if warning:
        return "warning"
    if "✓" in text:
        return "success"
    if "http://" in text or "https://" in text:
        return "link"
    return "info"


@dataclass(frozen=True, slots=True)
class _GlobalHotkeyBinding:
    field: str
    sequence: str
    callback: Callable[[], None]


# ── 視覺主題 token（僅影響 QSS 外觀，絕不影響任何 signal/slot 或數值行為） ──
# 轉譯自 claude.ai/design 設計稿（Industry design system）：深色為預設，另備淺色。
# 語意色（ok/warn/bad、綜合疲勞等級動態色）由資料驅動，不放進 palette。
class EngineApplication(QObject):
    """Headless Qt application adapter for the production Python engine."""

    def __init__(self, *, engine_mode: bool = True) -> None:
        if engine_mode is not True:
            raise ValueError("EngineApplication is engine-only")
        super().__init__()
        self._engine_mode = True
        self._engine_controller = EngineController(belt_runtime=BeltRuntime())

        self._pipeline_running = False
        self._recording = False
        self._hotkeys = HotkeyConfig()
        self._user = UserProfile()
        self._overlay_state = OverlayRuntimeState()
        self._capture_preferences = CapturePreferencesState()
        self._web_preferences = WebPreferencesState()

        app = QApplication.instance()
        if app is None:
            raise RuntimeError("EngineApplication requires a QApplication instance")
        self._engine_runtime = EngineRuntime(app)
        self._engine_runtime.adapter_released.connect(self._on_adapter_released)
        self._bgr_queue: "queue.Queue | None" = None
        self._fatigue_queue: "queue.Queue | None" = None
        self._combined_queue: "queue.Queue | None" = None

        self._metrics_recorder: MetricsRecorder | None = None
        self._finalizing_metrics_recorder: MetricsRecorder | None = None
        self._recording_db_path: Path | None = None
        self._recording_started_at: float | None = None
        self._recording_count: int = 0
        self._recording_video_path: Path | None = None
        self._video_queue: "queue.Queue | None" = None
        self._frame_source: str | None = None
        self._record_source: str | None = None
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None

        self._last_camera_info = {"codec": "", "width": 0, "height": 0}
        self._last_fps: float = 0.0
        self._fps_measurement_samples = 0
        self._camera_fps_warning_sent = False

        self._global_hotkey_runtime = GlobalHotkeyRuntime(self._on_global_hotkey)
        self._global_hotkey_bindings: dict[int, _GlobalHotkeyBinding] = {}
        self._hotkey_failed_once: set[str] = set()
        self._hotkey_registration_failures: list[dict[str, Any]] = []
        self._legacy_window_settings: dict[str, str] = {}
        self._settings_dirty = False
        self._desktop_notice_seq = 0
        self._desktop_notice: dict[str, Any] | None = None
        self._web_metrics_buffer = MetricsBuffer(maxsize=300)
        self._web_server: WebServerThread | None = None
        self._web_restart_scheduled = False
        self._web_restart_in_progress = False
        self._web_restart_shutdown = False
        self._web_restart_stopping_server: WebServerThread | None = None
        self._web_finalizing_servers: set[WebServerThread] = set()
        self._web_finalization_retried: set[WebServerThread] = set()
        self._runtime_cleanup_in_progress = False
        self._runtime_cleanup_complete = False
        self._runtime_cleanup_retry_attempted = False
        self._runtime_cleanup_retry_scheduled = False
        self._runtime_shutdown_waiting_for_adapters = False
        self._adapter_cleanup_in_progress = False
        self._desktop_control_broker = DesktopCommandBroker(timeout_seconds=10.0)
        self._web_emit_interval = 0.25
        self._web_frame_interval = 1.0 / WEB_PREVIEW_TARGET_FPS
        self._web_last_emit = 0.0
        self._web_last_frame_emit = 0.0
        self._replay_state = ReplayRuntimeState()
        self._replay_stopping = False
        self._replay_active_videos: dict[str, ReplayVideoSummary] = {}
        self._replay_recent_done: list[str] = []
        self._replay_queue_rows: dict[str, int] = {}
        self._replay_completed_summaries: list[ReplayVideoSummary] = []
        self._alarm_config = AlarmConfig.defaults()
        self._rppg_calibration_store = CalibrationVersionStore()
        # 個人清醒基線：跨 session 載入上次的 manual profile（無則 None → 行為門檻走預設）。
        self._personal_profile_store = PersonalProfileStore()
        self._personal_profile = self._personal_profile_store.load()
        self._profile_status = "個人基線：未啟動"
        # 啟動自動蒐集（暫定基線）與手動「記錄清醒基線」按鈕各自的蒐集器。
        self._auto_baseline_collector: PersonalBaselineCollector | None = None
        self._manual_baseline_collector: PersonalBaselineCollector | None = None
        # 心跳帶真值校準（背景）：心跳帶 HR 當參考，線上微調 rPPG BPM offset，
        # 不進疲勞融合分數（見 _ensure_belt_calibration / OnlineBpmCalibrator）。
        self._belt_calibrator: OnlineBpmCalibrator | None = None
        # 記錄最後餵給校正器的 rPPG metrics 物件，避免 rPPG 凍結時把同一筆
        # 樣本每秒重複計入而扭曲殘差（每次 rPPG 更新都是新物件，凍結則同物件）。
        self._last_calib_fed_metrics: object | None = None
        # P6b-3b：rPPG ROI 權重線上協調層（預設 OFF，見 HrBeltConfig.
        # rppg_param_tuning_enabled）。協調層本身與其產生的候選皆只在心跳帶校準
        # 啟動且設定檔開關為 True 時才建立；為 None 時 GUI tick / worker 候選重算
        # 全部 early-return，逐位元回退現況。
        self._belt_cfg: HrBeltConfig | None = None
        # P6b-4：belt-truth 同步錄製 writer（預設 OFF，見 HrBeltConfig.capture_enabled）。
        # 只在心跳帶真值校準啟動且設定檔開關為 True 時才建立；為 None 時 worker
        # 的 _maybe_capture_belt_truth 全部 early-return，逐位元回退現況。
        self._belt_truth_capture: BeltTruthCaptureWriter | None = None
        self._rppg_param_coordinator: RppgParamCoordinator | None = None
        self._rppg_param_current_weights: dict[str, float] = dict(ROI_BASE_WEIGHTS)
        # 自動採集：一鍵串接既有「開始」/「開始記錄」/「心跳帶真值校準」觸發點，
        # 不重寫任何 worker 啟停或記錄/校準邏輯本身（見 _on_auto_capture_clicked）。
        self._auto_capture_belt_path: Path | None = None
        self._auto_capture_started_belt_calib: bool = False
        self._auto_capture_started_stress: bool = False
        # True 僅當本次自動採集自己呼叫 _toggle_recording() 啟動了記錄；若使用者按
        # 「自動採集」前已手動開始記錄，自動採集只是沿用既有錄製，此旗標維持 False，
        # 收尾時就不會誤停這段與自動採集無關的錄製。
        self._auto_capture_started_recording: bool = False
        # 啟動計時器當下記錄的 _recording_db_path，供 _finish_auto_capture 收尾時比對，
        # 避免誤停使用者在倒數期間另行啟動的、與本次自動採集無關的新錄製。
        self._auto_capture_expected_db_path: Path | None = None
        self._monitor_focus = False

        self._start_camera_scan()

        self._engine_runtime.start_periodic_timer(
            "desktop_command",
            20,
            self._drain_desktop_commands,
        )

        self._load_settings()
        self._engine_runtime.initialize_alarm(self._alarm_config)
        self._apply_hotkey_shortcuts()
        self._start_web_server()

    @property
    def _cam_thread(self) -> QThread | None:
        return self._engine_runtime.thread("camera")

    @property
    def _cam_worker(self) -> CameraStreamWorker | None:
        return cast(CameraStreamWorker | None, self._engine_runtime.worker("camera"))

    @property
    def _combined_thread(self) -> QThread | None:
        return self._engine_runtime.thread("combined")

    @property
    def _combined_worker(self) -> CombinedWorker | None:
        return cast(CombinedWorker | None, self._engine_runtime.worker("combined"))

    @property
    def _rppg_thread(self) -> QThread | None:
        return self._engine_runtime.thread("rppg")

    @property
    def _rppg_worker(self) -> RppgWorker | None:
        return cast(RppgWorker | None, self._engine_runtime.worker("rppg"))

    @property
    def _fatigue_thread(self) -> QThread | None:
        return self._engine_runtime.thread("fatigue")

    @property
    def _fatigue_worker(self) -> FatigueWorker | None:
        return cast(FatigueWorker | None, self._engine_runtime.worker("fatigue"))

    @property
    def _video_thread(self) -> QThread | None:
        return self._engine_runtime.thread("video")

    @property
    def _video_worker(self) -> VideoRecorderWorker | None:
        return cast(VideoRecorderWorker | None, self._engine_runtime.worker("video"))

    @property
    def _replay_thread(self) -> QThread | None:
        return self._engine_runtime.thread("replay")

    @property
    def _replay_worker(self) -> VideoReplayWorker | None:
        return cast(VideoReplayWorker | None, self._engine_runtime.worker("replay"))

    def _toggle_overlay_preference(self, field: str) -> None:
        state = self._overlay_state.snapshot()
        current = getattr(state, field)
        self._configure_overlay(**{field: not current})

    def _set_monitor_layout(self, focus: bool) -> None:
        """Store the Flutter dashboard layout preference in engine state."""
        self._monitor_focus = bool(focus)

    def _configure_overlay(self, **changes: object) -> None:
        previous = self._overlay_state.snapshot()
        current = self._overlay_state.configure(**changes)
        if current == previous:
            return
        self._settings_dirty = True

    def _configure_replay(self, **changes: object) -> None:
        self._replay_state.configure(**changes)

    def _update_replay_presentation(self, **changes: object) -> None:
        self._replay_state.update_presentation(**changes)

    def _configure_web_preferences(
        self,
        *,
        allow_lan: bool,
        mark_dirty: bool = True,
        restart_server: bool = True,
    ) -> None:
        self._web_preferences.configure(allow_lan=allow_lan)
        if mark_dirty:
            self._settings_dirty = True
        if restart_server:
            self._schedule_web_server_restart()

    def _configure_capture_preferences(
        self,
        *,
        mark_dirty: bool = True,
        **changes: object,
    ) -> None:
        previous = self._capture_preferences.snapshot()
        current = self._capture_preferences.configure(**changes)
        if current == previous:
            return
        if current.belt_calibration != previous.belt_calibration:
            belt_was_running = self._engine_controller.belt_running
            try:
                self._on_belt_calib_toggled(current.belt_calibration)
            except Exception:
                if current.belt_calibration:
                    self._rollback_failed_belt_calibration_start(
                        stop_belt=not belt_was_running
                    )
                self._capture_preferences.restore(previous)
                raise
            current = self._capture_preferences.snapshot()
        if current.auto_record != previous.auto_record:
            self._append_log(
                f"[UI] 按下開始時自動記錄 → {'開啟' if current.auto_record else '關閉'}"
            )
        persisted_changed = (
            current.auto_record != previous.auto_record
            or current.belt_calibration != previous.belt_calibration
        )
        if mark_dirty and persisted_changed:
            self._settings_dirty = True

    def _configure_analysis(
        self,
        *,
        behavior_enabled: bool,
        rppg_enabled: bool,
    ) -> None:
        previous = self._engine_controller.analysis_snapshot()
        if (
            previous.fatigue_enabled == behavior_enabled
            and previous.rppg_enabled == rppg_enabled
        ):
            return
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        running = self._engine_controller.pipeline_snapshot().running
        try:
            self._engine_controller.configure_analysis(
                rppg_enabled=rppg_enabled,
                fatigue_enabled=behavior_enabled,
                ports=self._analysis_lifecycle_ports() if running else None,
            )
        except Exception:
            if not self._engine_controller.pipeline_snapshot().running:
                self._fail_closed_pipeline_adapters()
            raise
        if previous.fatigue_enabled != behavior_enabled:
            self._append_log(
                f"[UI] 行為警覺 → {'開啟' if behavior_enabled else '關閉'}"
            )
        if previous.rppg_enabled != rppg_enabled:
            self._append_log(
                f"[UI] 壓力／HRV → {'開啟' if rppg_enabled else '關閉'}"
            )
        if running:
            self._ensure_belt_calibration()
            self._emit_web_metrics(force=True)

    def _qt_key_to_vk(self, qt_key: int) -> int | None:
        if Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z:
            return ord("A") + (qt_key - Qt.Key.Key_A)
        if Qt.Key.Key_0 <= qt_key <= Qt.Key.Key_9:
            return ord("0") + (qt_key - Qt.Key.Key_0)
        if Qt.Key.Key_F1 <= qt_key <= Qt.Key.Key_F24:
            return 0x70 + (qt_key - Qt.Key.Key_F1)
        if qt_key == Qt.Key.Key_Space:
            return 0x20
        if qt_key == Qt.Key.Key_Escape:
            return 0x1B
        if qt_key == Qt.Key.Key_Tab:
            return 0x09
        if qt_key == Qt.Key.Key_Backspace:
            return 0x08
        if qt_key == Qt.Key.Key_Return or qt_key == Qt.Key.Key_Enter:
            return 0x0D
        return None

    def _parse_hotkey(self, seq_text: str) -> tuple[int, int] | None:
        if not seq_text:
            return None
        seq = QKeySequence(seq_text)
        if seq.isEmpty():
            return None
        first = cast(Any, seq)[0]
        if hasattr(first, "toCombined"):
            combined = int(first.toCombined())
        else:
            combined = int(first)
        mod_mask_flag = (
            Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        mod_mask = self._qt_enum_int(mod_mask_flag)
        modifiers = combined & mod_mask
        qt_key = combined & ~mod_mask

        mod_flags = 0
        ctrl_flag = Qt.KeyboardModifier.ControlModifier
        alt_flag = Qt.KeyboardModifier.AltModifier
        shift_flag = Qt.KeyboardModifier.ShiftModifier
        meta_flag = Qt.KeyboardModifier.MetaModifier
        ctrl_mask = self._qt_enum_int(ctrl_flag)
        alt_mask = self._qt_enum_int(alt_flag)
        shift_mask = self._qt_enum_int(shift_flag)
        meta_mask = self._qt_enum_int(meta_flag)

        if modifiers & ctrl_mask:
            mod_flags |= 0x0002
        if modifiers & alt_mask:
            mod_flags |= 0x0001
        if modifiers & shift_mask:
            mod_flags |= 0x0004
        if modifiers & meta_mask:
            mod_flags |= 0x0008

        vk = self._qt_key_to_vk(qt_key)
        if vk is None:
            return None
        return mod_flags, vk

    @staticmethod
    def _qt_enum_int(value: object) -> int:
        return int(cast(Any, getattr(value, "value", value)))

    def _register_global_hotkeys(self) -> None:
        self._hotkey_registration_failures = []
        if not self._global_hotkey_runtime.supported:
            return

        native_bindings: dict[int, tuple[int, int]] = {}
        for hotkey_id, binding in self._global_hotkey_bindings.items():
            seq = binding.sequence
            parsed = self._parse_hotkey(seq)
            if parsed is None:
                if seq:
                    self._hotkey_registration_failures.append(
                        {
                            "key": binding.field,
                            "sequence": seq,
                            "code": 0,
                            "reason": "unsupported_sequence",
                        }
                    )
                continue
            native_bindings[hotkey_id] = parsed

        for failure in self._global_hotkey_runtime.register(native_bindings):
            binding = self._global_hotkey_bindings[failure.hotkey_id]
            seq = binding.sequence
            self._hotkey_registration_failures.append(
                {
                    "key": binding.field,
                    "sequence": seq,
                    "code": failure.code,
                    "reason": failure.reason,
                }
            )
            if seq not in self._hotkey_failed_once:
                if failure.reason == "already_registered":
                    self._append_log(
                        f"⚠ 全域快捷鍵已被占用：{seq}（錯誤 {failure.code}）"
                    )
                else:
                    self._append_log(
                        f"⚠ 註冊全域快捷鍵失敗：{seq}（錯誤 {failure.code}）"
                    )
                self._hotkey_failed_once.add(seq)

    def _unregister_global_hotkeys(self) -> None:
        for failure in self._global_hotkey_runtime.unregister():
            binding = self._global_hotkey_bindings.get(failure.hotkey_id)
            sequence = binding.sequence if binding is not None else str(failure.hotkey_id)
            self._append_log(
                f"⚠ 解除全域快捷鍵失敗：{sequence}（錯誤 {failure.code}）"
            )

    def _on_global_hotkey(self, hotkey_id: int) -> None:
        binding = self._global_hotkey_bindings.get(hotkey_id)
        if binding is None:
            return
        binding.callback()

    def _settings_path(self) -> Path:
        return data_path("settings.json")

    def _on_camera_config_changed(self, **changes: object) -> None:
        self._engine_controller.configure_camera(**changes)

    def _load_settings(self) -> None:
        path = self._settings_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._append_log(f"⚠ 設定檔讀取失敗：{exc}")
            return

        win = data.get("window", {})
        if isinstance(win, dict):
            self._legacy_window_settings = {
                key: value
                for key, value in win.items()
                if key in {"geometry", "state"} and isinstance(value, str)
            }

        overlay = data.get("overlay", {})

        hotkeys = data.get("hotkeys", {})
        if isinstance(hotkeys, dict):
            old_defaults = {
                "toggle_metrics": "Ctrl+Alt+M",
                "toggle_preview": "Ctrl+Alt+P",
                "start_stop": "Ctrl+Alt+Space",
                "lock_overlay": "Ctrl+Alt+L",
                "toggle_all": "Ctrl+Alt+H",
                "toggle_recording": "Ctrl+Alt+R",
            }
            new_defaults = HotkeyConfig()

            def pick(key: str, fallback: str) -> str:
                val = hotkeys.get(key, fallback)
                if val == old_defaults.get(key):
                    return getattr(new_defaults, key)
                return val

            self._hotkeys = HotkeyConfig(
                toggle_metrics=pick("toggle_metrics", new_defaults.toggle_metrics),
                toggle_preview=pick("toggle_preview", new_defaults.toggle_preview),
                start_stop=pick("start_stop", new_defaults.start_stop),
                lock_overlay=pick("lock_overlay", new_defaults.lock_overlay),
                toggle_all=pick("toggle_all", new_defaults.toggle_all),
                toggle_recording=pick("toggle_recording", new_defaults.toggle_recording),
            )

        user = data.get("user", {})
        if isinstance(user, dict):
            self._user = UserProfile(
                age=int(user.get("age", self._user.age)),
                height_cm=int(user.get("height_cm", self._user.height_cm)),
                weight_kg=float(user.get("weight_kg", self._user.weight_kg)),
            )

        camera = data.get("camera", {})
        if isinstance(camera, dict):
            resolution = camera.get("resolution")
            fps = camera.get("fps")
            backend = camera.get("backend")
            cam_idx = camera.get("index")
            horizontal_flip = camera.get("horizontal_flip")

            for key, value in (
                ("resolution", resolution),
                ("fps", fps),
                ("backend", backend),
            ):
                if isinstance(value, str):
                    try:
                        self._engine_controller.configure_camera(**{key: value})
                    except ValueError:
                        pass
            if isinstance(horizontal_flip, bool):
                self._engine_controller.configure_camera(horizontal_flip=horizontal_flip)
            if isinstance(cam_idx, int):
                self._engine_controller.restore_camera(cam_idx)

        toggles = data.get("toggles", {})
        if isinstance(toggles, dict):
            self._capture_preferences.load(toggles=toggles)
            current_analysis = self._engine_controller.analysis_snapshot()
            behavior_enabled = toggles.get("behavior")
            rppg_enabled = toggles.get("stress")
            self._engine_controller.configure_analysis(
                fatigue_enabled=(
                    behavior_enabled
                    if isinstance(behavior_enabled, bool)
                    else current_analysis.fatigue_enabled
                ),
                rppg_enabled=(
                    rppg_enabled
                    if isinstance(rppg_enabled, bool)
                    else current_analysis.rppg_enabled
                ),
            )

        self._overlay_state.load(toggles=toggles, overlay=overlay)

        self._web_preferences.load(web=data.get("web", {}))

        alarm = data.get("alarm", {})
        if isinstance(alarm, dict):
            self._alarm_config = AlarmConfig.from_dict(alarm)

    def _save_settings(self) -> Path:
        path = self._settings_path()
        camera = self._engine_controller.camera_snapshot()
        analysis = self._engine_controller.analysis_snapshot()
        overlay_state = self._overlay_state.to_settings()
        capture_toggles = self._capture_preferences.to_settings_toggles()
        data = {
            "window": dict(self._legacy_window_settings),
            "overlay": {
                "geometry": overlay_state["overlay"]["geometry"],
                "opacity": overlay_state["overlay"]["opacity"],
            },
            "camera": {
                "index": camera.selected_index,
                "resolution": camera.resolution,
                "fps": camera.fps,
                "backend": camera.backend,
                "horizontal_flip": camera.horizontal_flip,
            },
            "toggles": {
                **overlay_state["toggles"],
                "behavior": analysis.fatigue_enabled,
                "stress": analysis.rppg_enabled,
                **capture_toggles,
            },
            "hotkeys": {
                "toggle_metrics": self._hotkeys.toggle_metrics,
                "toggle_preview": self._hotkeys.toggle_preview,
                "start_stop": self._hotkeys.start_stop,
                "lock_overlay": self._hotkeys.lock_overlay,
                "toggle_all": self._hotkeys.toggle_all,
                "toggle_recording": self._hotkeys.toggle_recording,
            },
            "user": {
                "age": self._user.age,
                "height_cm": self._user.height_cm,
                "weight_kg": self._user.weight_kg,
            },
            "web": {
                **self._web_preferences.to_settings(),
            },
            "alarm": self._alarm_config.to_dict(),
        }
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(data, temp_file, ensure_ascii=True, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(path)
        except OSError as exc:
            raise SettingsWriteError(
                f"Unable to write settings file {path}: {exc}",
                path=str(path),
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    logger.warning(
                        "設定暫存檔清理失敗：%s: %s",
                        temp_path,
                        cleanup_exc,
                    )
        self._settings_dirty = False
        return path

    def _start_camera_scan(self) -> None:
        if self._runtime_cleanup_in_progress or self._runtime_cleanup_complete:
            return
        if self._engine_runtime.worker("camera_scan") is not None:
            return
        pipeline = self._engine_controller.pipeline_snapshot()
        if pipeline.running:
            raise BusyError("Stop the pipeline before refreshing cameras")
        if pipeline.cleanup_pending:
            raise BusyError("Live pipeline adapter cleanup is still pending")
        worker = CameraScanWorker()

        def connect(current: object) -> None:
            scan = cast(CameraScanWorker, current)
            scan.succeeded.connect(self._on_camera_scan_succeeded, Qt.ConnectionType.QueuedConnection)
            scan.failed.connect(self._on_camera_scan_failed, Qt.ConnectionType.QueuedConnection)

        try:
            self._engine_runtime.start_adapter("camera_scan", worker, connect=connect)
        except Exception as exc:
            logger.exception("攝影機列舉無法啟動")
            self._publish_desktop_notice(f"攝影機列舉失敗：{exc}")

    def _camera_scan_result_is_current(self, worker: object) -> bool:
        return (
            self._engine_runtime.worker("camera_scan") is worker
            and not self._runtime_cleanup_in_progress
            and not self._runtime_cleanup_complete
            and not cast(CameraScanWorker, worker).stopped
        )

    @Slot(object, object)
    def _on_camera_scan_succeeded(self, worker: object, dev_list: object) -> None:
        if self._camera_scan_result_is_current(worker):
            self._finish_camera_scan_ui(cast(list[tuple[int, str]], dev_list))

    @Slot(object, str)
    def _on_camera_scan_failed(self, worker: object, message: str) -> None:
        if self._camera_scan_result_is_current(worker):
            logger.warning("攝影機列舉失敗：%s", message)
            self._publish_desktop_notice(f"攝影機列舉失敗：{message}")

    def _finish_camera_scan_ui(self, dev_list: list[tuple[int, str]]) -> None:
        self._engine_controller.replace_cameras(
            CameraDevice(index, f"[{index}] {name}") for index, name in dev_list
        )
        if dev_list:
            logger.info("Camera list updated: %d device(s)", len(dev_list))
        else:
            logger.warning("No camera devices detected")

    def _apply_hotkey_shortcuts(self) -> None:
        hk = self._hotkeys
        fields = (
            "toggle_metrics",
            "toggle_preview",
            "start_stop",
            "lock_overlay",
            "toggle_all",
            "toggle_recording",
        )
        keys = (
            hk.toggle_metrics,
            hk.toggle_preview,
            hk.start_stop,
            hk.lock_overlay,
            hk.toggle_all,
            hk.toggle_recording,
        )
        callbacks = (
            lambda: self._toggle_overlay_preference("metrics"),
            lambda: self._toggle_overlay_preference("preview"),
            self._toggle_pipeline,
            lambda: self._toggle_overlay_preference("locked"),
            lambda: self._toggle_overlay_preference("all_enabled"),
            self._toggle_recording,
        )
        self._global_hotkey_bindings = {
            index: _GlobalHotkeyBinding(field, sequence, callback)
            for index, (field, sequence, callback) in enumerate(
                zip(fields, keys, callbacks, strict=True),
                start=1,
            )
        }
        self._register_global_hotkeys()

    def _recordings_dir(self) -> Path:
        rec = data_path("recordings")
        rec.mkdir(parents=True, exist_ok=True)
        return rec

    def _web_allow_lan_enabled(self) -> bool:
        return self._web_preferences.snapshot().allow_lan

    def _web_bind_host(self) -> str:
        return "0.0.0.0" if self._web_allow_lan_enabled() else "127.0.0.1"

    def _web_access_token(self) -> str | None:
        """目前 Web 伺服器的 LAN shared-token（單機模式或伺服器未啟動時為 None）。"""
        return getattr(self._web_server, "access_token", None) if self._web_server is not None else None

    def _web_dashboard_urls(self) -> list[str]:
        urls = format_web_dashboard_urls(
            WEB_DASHBOARD_DEFAULT_PORT,
            allow_lan=self._web_allow_lan_enabled(),
        )
        token = self._web_access_token()
        if token:
            urls = [f"{url}?token={token}" for url in urls]
        return urls

    def _format_web_dashboard_message(self, *, include_lan_hint: bool = False) -> str:
        lines = self._web_dashboard_urls()
        if self._web_allow_lan_enabled() and len(lines) == 1:
            lines.append("（區域網已啟用，但未能偵測到區域網 IP）")
        message = "\n".join(lines)
        if include_lan_hint and self._web_allow_lan_enabled():
            message += (
                "\n\n其他裝置請使用上方區域網網址。"
                "若無法連線，請確認防火牆是否放行 TCP "
                f"{WEB_DASHBOARD_DEFAULT_PORT}。"
            )
        return message

    def _start_web_server(self) -> None:
        if self._web_server is not None:
            return
        try:
            playback_manager = PlaybackManager(self._recordings_dir())
            host = self._web_bind_host()
            self._web_server = WebServerThread(
                self._web_metrics_buffer,
                playback_manager,
                get_latest_packet=self._build_web_metrics,
                host=host,
                port=WEB_DASHBOARD_DEFAULT_PORT,
                control_handler=self._desktop_control_broker.submit,
            )
            self._web_server.start()
            self._emit_web_metrics(force=True)
            lan_state = "區域網已啟用" if self._web_allow_lan_enabled() else "僅本機"
            self._append_log(
                f"🌐 Web 儀表板啟動（{lan_state}）：{self._format_web_dashboard_message()}"
            )
        except Exception as exc:
            self._append_log(f"⚠ Web 儀表板啟動失敗：{exc}")
            self._web_server = None

    def _schedule_web_server_restart(self) -> None:
        if self._web_restart_shutdown or self._web_restart_scheduled or self._web_restart_in_progress:
            return
        self._web_restart_scheduled = True
        QTimer.singleShot(0, self._begin_web_server_restart)

    def _begin_web_server_restart(self) -> None:
        self._web_restart_scheduled = False
        if self._web_restart_shutdown or self._web_restart_in_progress:
            return
        server = self._web_server
        if server is None:
            self._start_web_server()
            return
        self._web_server = None
        self._web_restart_stopping_server = server
        self._web_restart_in_progress = True
        server.request_stop()
        self._ensure_web_finalization_timer()

    def _ensure_web_finalization_timer(self) -> None:
        self._poll_web_finalization()
        if (
            (self._web_restart_stopping_server is not None or self._web_finalizing_servers)
            and not self._engine_runtime.timer_active("web_finalize")
        ):
            self._engine_runtime.start_periodic_timer("web_finalize", 50, self._poll_web_finalization)

    def _retry_web_finalization(self, server: WebServerThread) -> bool:
        if server.finalization_failed and server not in self._web_finalization_retried:
            self._web_finalization_retried.add(server)
            logger.warning("Retrying incomplete Web server cleanup")
            server.request_stop()
            return True
        return False

    def _poll_web_finalization(self, *, retry_failed: bool = True) -> None:
        server = self._web_restart_stopping_server
        if retry_failed:
            pending = self._web_finalizing_servers | ({server} if server is not None else set())
            for current in pending:
                if not current.is_finalized:
                    self._retry_web_finalization(current)
        if server is not None and server.is_finalized:
            self._web_restart_stopping_server = None
            self._web_restart_in_progress = False
            self._web_finalization_retried.discard(server)
            if not self._web_restart_shutdown:
                self._start_web_server()
        finalized = {
            server for server in tuple(self._web_finalizing_servers) if server.is_finalized
        }
        self._web_finalizing_servers.difference_update(finalized)
        self._web_finalization_retried.difference_update(finalized)
        if self._web_restart_stopping_server is None and not self._web_finalizing_servers:
            self._engine_runtime.cancel_timer("web_finalize")
            if self._runtime_shutdown_waiting_for_adapters:
                self._engine_runtime.defer(0, self._shutdown_engine)

    def _stop_web_server(self) -> None:
        servers = [
            server
            for server in (self._web_server, self._web_restart_stopping_server)
            if server is not None
        ]
        if not servers:
            return
        self._web_server = None
        self._web_restart_stopping_server = None
        self._web_restart_in_progress = False
        for server in dict.fromkeys(servers):
            self._web_finalizing_servers.add(server)
            server.request_stop()
        self._ensure_web_finalization_timer()

    def _build_web_metrics(self) -> dict:
        pipeline = self._engine_controller.pipeline_snapshot()
        pipeline_running = pipeline.running
        analysis = self._engine_controller.analysis_snapshot()
        stress_enabled = analysis.rppg_enabled
        behavior_enabled = analysis.fatigue_enabled
        r = self._latest_rppg_metrics if pipeline_running and stress_enabled else None
        f = self._latest_fatigue_metrics if pipeline_running and behavior_enabled else None
        fusion_on = behavior_enabled and stress_enabled
        z = self._latest_fused_score if pipeline_running and fusion_on else None
        info = self._last_camera_info

        face_r = bool(getattr(r, "face_detected", False)) if r else False
        face_f = bool(getattr(f, "face_detected", False)) if f else False
        calib_progress = float(getattr(f, "calib_progress", 0.0) or 0.0) if f else 0.0
        calib_target = 100
        calib_samples = int(round(calib_progress * calib_target)) if f else 0
        warmup_progress = float(getattr(r, "warmup_progress", 0.0) or 0.0) if r else 0.0
        perclos_pct = float(getattr(f, "perclos", 0.0) or 0.0) * 100.0 if f else 0.0
        belt_st = self._engine_controller.belt_status() if self._engine_controller.belt_running else None
        # 校準資訊僅在心跳帶已連線時視為 active（與 GUI 狀態列一致，避免掃描中
        # 就顯示「校正 +0.0｜0 配對」）。
        belt_connected = belt_st is not None and belt_st.state == "connected"
        belt_signal_age = (
            max(0.0, time.time() - float(belt_st.last_sample_at))
            if belt_st is not None and belt_st.last_sample_at is not None
            else -1.0
        )
        belt_connected_duration = (
            max(0.0, time.time() - float(belt_st.connected_since))
            if belt_st is not None and belt_st.connected_since is not None
            else -1.0
        )
        belt_physio = None
        if belt_st is not None:
            try:
                belt_physio = compute_watch_physio(self._engine_controller.belt_samples())
            except Exception:
                belt_physio = None
        calib = (
            self._belt_calibrator.state()
            if self._belt_calibrator is not None and belt_connected
            else None
        )

        return {
            "timestamp": time.time(),
            "pipeline_running": pipeline_running,
            "camera_running": bool(self._cam_worker is not None),
            "recording": pipeline.recording,
            "recording_finalizing": not pipeline.recording and (
                self._video_thread is not None
                or self._video_worker is not None
                or self._finalizing_metrics_recorder is not None
            ),
            "fps": float(self._last_fps or 0.0),
            "camera_label": self._engine_controller.selected_camera_label(),
            "camera_codec": str(info.get("codec") or ""),
            "camera_width": int(info.get("width") or 0),
            "camera_height": int(info.get("height") or 0),
            "frame_source": str(self._frame_source or ""),
            "record_source": str(self._record_source or ""),
            "behavior_enabled": behavior_enabled,
            "face_detected": face_r or face_f,
            "calibrated": bool(getattr(f, "calibrated", False)) if f else False,
            "calib_samples": calib_samples,
            "calib_target": calib_target if f else 0,
            "ear": float(getattr(f, "ear", 0.0) or 0.0),
            "perclos": perclos_pct,
            "blink_count": int(getattr(f, "blink_count", 0) or 0),
            "status": str(getattr(f, "status", "NO_FACE") or "NO_FACE"),
            "stress_bpm": effective_bpm(r) if r else 0.0,
            "stress_bpm_raw": float(getattr(r, "bpm", 0.0) or 0.0) if r else 0.0,
            "stress_bpm_calibrated": float(getattr(r, "bpm_calibrated", 0.0) or 0.0) if r else 0.0,
            "calibration_version_id": str(getattr(r, "calibration_version_id", "") or "") if r else "",
            "stress_raw_bpm": float(getattr(r, "raw_bpm", 0.0) or 0.0) if r else 0.0,
            "stress_bpm_delta": float(getattr(r, "bpm_delta", 0.0) or 0.0) if r else 0.0,
            "stress_bpm_guarded": bool(getattr(r, "bpm_guarded", False)) if r else False,
            "stress_bpm_guard_reason": str(getattr(r, "bpm_guard_reason", "") or "") if r else "",
            "stress_rmssd": float(getattr(r, "rmssd", 0.0) or 0.0) if r else 0.0,
            "stress_sdnn": float(getattr(r, "sdnn", 0.0) or 0.0) if r else 0.0,
            "stress_lf_hf": float(getattr(r, "lf_hf", 0.0) or 0.0) if r else 0.0,
            "stress_sqi": float(getattr(r, "sqi", 0.0) or 0.0) if r else 0.0,
            "stress_quality_score": float(getattr(r, "quality_score", 0.0) or 0.0) if r else 0.0,
            "stress_pose_roll_deg": float(getattr(r, "pose_roll_deg", 0.0) or 0.0),
            "stress_pose_yaw_deg": float(getattr(r, "pose_yaw_deg", 0.0) or 0.0),
            "stress_pose_pitch_deg": float(getattr(r, "pose_pitch_deg", 0.0) or 0.0),
            "stress_roi_valid_count": int(getattr(r, "roi_valid_count", 0) or 0),
            "stress_roi_weight_forehead": float(getattr(r, "roi_weight_forehead", 0.0) or 0.0),
            "stress_roi_weight_l_cheek": float(getattr(r, "roi_weight_l_cheek", 0.0) or 0.0),
            "stress_roi_weight_r_cheek": float(getattr(r, "roi_weight_r_cheek", 0.0) or 0.0),
            "stress_roi_weight_glabella": float(getattr(r, "roi_weight_glabella", 0.0) or 0.0),
            "stress_landmark_jitter_norm": float(getattr(r, "landmark_jitter_norm", 0.0) or 0.0),
            "stress_roi_area_stability": float(getattr(r, "roi_area_stability", 0.0) or 0.0),
            "stress_roi_area_jitter_ratio": float(getattr(r, "roi_area_jitter_ratio", 0.0) or 0.0),
            "stress_roi_smoothing_applied": bool(getattr(r, "roi_smoothing_applied", False)) if r else False,
            "stress_canonical_roi_warp_used": bool(getattr(r, "canonical_roi_warp_used", False)) if r else False,
            "stress_peak_freq": float(getattr(r, "peak_freq_hz", 0.0) or 0.0),
            "stress_hrv_confidence": str(getattr(r, "hrv_confidence", "") or "") if r else "",
            "stress_ibi_artifact_ratio": float(getattr(r, "ibi_artifact_ratio", 0.0) or 0.0) if r else 0.0,
            "stress_prob": float(getattr(r, "stress_prob", 0.0) or 0.0) if r else 0.0,
            "stress_waveform": list(getattr(r, "waveform", []) or []) if r else [],
            "stress_psd_freqs": list(getattr(r, "psd_freqs", []) or []) if r else [],
            "stress_psd_values": list(getattr(r, "psd_vals", []) or []) if r else [],
            "stress_lf_hf_window_ok": bool(
                getattr(r, "lf_hf", 0.0) and getattr(r, "warmup_progress", 0.0) >= 0.99
            ) if r else False,
            "stress_enabled": stress_enabled,
            "stress_has_face": face_r,
            "stress_warmup_progress": warmup_progress,
            "stress_warmup_done": warmup_progress >= 0.99,
            "physio_source": "rppg",
            "belt_enabled": belt_st is not None,
            "belt_state": str(belt_st.state) if belt_st else "",
            "belt_device_name": str(belt_st.device_name) if belt_st else "",
            "belt_device_address": str(belt_st.device_address) if belt_st else "",
            "belt_rssi": float(belt_st.rssi) if belt_st else 0.0,
            "belt_battery": int(belt_st.battery_level) if belt_st and belt_st.battery_level is not None else -1,
            "belt_bpm": int(belt_st.bpm) if belt_st else 0,
            "belt_rr_count": int(belt_st.rr_count) if belt_st else 0,
            "belt_notifications": int(belt_st.notifications) if belt_st else 0,
            "belt_sensor_location": str(belt_st.sensor_location) if belt_st else "",
            "belt_contact_supported": bool(belt_st.sensor_contact_supported) if belt_st else False,
            "belt_contact_detected": bool(belt_st.sensor_contact_detected) if belt_st else False,
            "belt_contact_ok": bool(
                belt_st.sensor_contact_detected or not belt_st.sensor_contact_supported
            ) if belt_st else False,
            "belt_stale": bool(hr_is_stale(belt_st)) if belt_st else False,
            "belt_signal_age_sec": belt_signal_age,
            "belt_connected_duration_sec": belt_connected_duration,
            "belt_last_error": str(belt_st.last_error) if belt_st else "",
            "belt_hrv_rmssd": float(getattr(belt_physio, "rmssd", 0.0) or 0.0),
            "belt_hrv_sdnn": float(getattr(belt_physio, "sdnn", 0.0) or 0.0),
            "belt_hrv_lf_hf": float(getattr(belt_physio, "lf_hf", 0.0) or 0.0),
            "belt_hrv_confidence": str(getattr(belt_physio, "hrv_confidence", "") or ""),
            "belt_hrv_warmup": float(getattr(belt_physio, "warmup_progress", 0.0) or 0.0),
            "calib_active": calib is not None,
            "calib_offset_bpm": float(calib.offset_bpm) if calib else 0.0,
            "calib_raw_residual_bpm": float(calib.raw_residual_bpm) if calib else 0.0,
            "calib_residual_bpm": float(calib.corrected_residual_bpm) if calib else 0.0,
            "calib_pairs_used": int(calib.pairs_used) if calib else 0,
            "calib_confidence": str(calib.confidence) if calib else "",
            "calib_converged": bool(calib.converged) if calib else False,
            "calib_diverged": bool(calib.diverged) if calib else False,
            "fusion_state_zh": str(getattr(z, "level", "") or ""),
            "fusion_confidence": float(getattr(z, "score", 0.0) or 0.0),
            "head_pitch": float(getattr(f, "head_pitch", 0.0) or 0.0),
            "head_yaw": float(getattr(f, "head_yaw", 0.0) or 0.0),
            "head_roll": float(getattr(f, "head_roll", 0.0) or 0.0),
            "fatigue_quality_score": float(getattr(f, "quality_score", 0.0) or 0.0),
            "fatigue_blend_calib_progress": float(getattr(f, "blend_calib_progress", 0.0) or 0.0),
            "early_warning": bool(getattr(f, "early_warning", False)) if f else False,
            "blink_rate_pm": float(getattr(f, "blink_rate_pm", 0.0) or 0.0),
            "blink_duration_sec": float(getattr(f, "blink_duration_sec", 0.0) or 0.0),
            "blink_duration_mean_sec": float(getattr(f, "blink_duration_mean_sec", 0.0) or 0.0),
            "blink_duration_z": float(getattr(f, "blink_duration_z", 0.0) or 0.0),
            "blink_amplitude": float(getattr(f, "blink_amplitude", 0.0) or 0.0),
            "blink_opening_velocity": float(getattr(f, "blink_opening_velocity", 0.0) or 0.0),
            "blink_opening_velocity_z": float(getattr(f, "blink_opening_velocity_z", 0.0) or 0.0),
            "blink_temporal_score": float(getattr(f, "blink_temporal_score", 0.0) or 0.0),
            "is_squinting": bool(getattr(f, "is_squinting", False)) if f else False,
            "is_frowning": bool(getattr(f, "is_frowning", False)) if f else False,
            "iris_ratio_trend": float(getattr(f, "iris_ratio_trend", 0.0) or 0.0),
            "fixation_duration": float(getattr(f, "fixation_duration", 0.0) or 0.0),
            "saccade_freq_pm": float(getattr(f, "saccade_freq_pm", 0.0) or 0.0),
            "microsleep_alert": bool(getattr(f, "microsleep_alert", False)) if f else False,
            "microsleep_count": int(getattr(f, "microsleep_count", 0) or 0),
            "yawn_count": int(getattr(f, "yawn_count", 0) or 0),
            "mar": float(getattr(f, "mar", 0.0) or 0.0),
            "gaze_stability_index": float(getattr(f, "gaze_stability_index", 0.0) or 0.0),
            "gaze_mental_fatigue": bool(getattr(f, "gaze_mental_fatigue", False)) if f else False,
            "dl_available": False,
            "dl_bpm": 0.0,
            "dl_confidence": 0.0,
            "dl_status": "",
        }

    def _drain_desktop_commands(self) -> None:
        self._desktop_control_broker.process_pending(self._handle_desktop_command)

    @staticmethod
    def _require_bool(args: dict[str, Any], key: str) -> bool:
        value = args.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        return value

    @staticmethod
    def _parse_hotkey_config(args: dict[str, Any]) -> HotkeyConfig:
        if set(args) != {"hotkeys"} or not isinstance(args.get("hotkeys"), dict):
            raise ValueError("hotkeys must be the only argument and must be an object")
        raw = args["hotkeys"]
        fields = (
            "toggle_metrics",
            "toggle_preview",
            "start_stop",
            "lock_overlay",
            "toggle_all",
            "toggle_recording",
        )
        if set(raw) != set(fields):
            raise ValueError("hotkeys must contain all six supported shortcut keys")

        values: dict[str, str] = {}
        for key in fields:
            value = raw[key]
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError(f"hotkeys.{key} must be a string up to 64 characters")
            if value:
                sequence = QKeySequence(value)
                if sequence.isEmpty() or sequence.count() != 1:
                    raise ValueError(f"hotkeys.{key} must be a valid single shortcut")
            values[key] = value
        return HotkeyConfig(**values)

    @staticmethod
    def _parse_user_profile(args: dict[str, Any]) -> UserProfile:
        age, height_cm, weight_kg = parse_user_profile(args)
        return UserProfile(age=age, height_cm=height_cm, weight_kg=weight_kg)

    @staticmethod
    def _parse_alarm_config(args: dict[str, Any]) -> AlarmConfig:
        return parse_alarm_config(args)

    @staticmethod
    def _parse_settings_reset_sections(args: dict[str, Any]) -> list[str]:
        return parse_settings_reset_sections(args)

    def _reset_settings_sections(self, sections: list[str]) -> None:
        selected = set(sections)
        if (
            self._engine_controller.pipeline_snapshot().running
            or self._engine_controller.replay_snapshot().running
        ) and selected.intersection(
            {"camera", "toggles", "replay"}
        ):
            raise BusyError("Stop the pipeline and replay before resetting runtime settings")

        if "hotkeys" in selected:
            self._hotkeys = HotkeyConfig()
            self._apply_hotkey_shortcuts()
        if "user_profile" in selected:
            self._user = UserProfile()
        if "alarm" in selected:
            self._alarm_config = AlarmConfig.defaults()
            self._engine_runtime.configure_alarm(self._alarm_config)
        if "camera" in selected:
            self._engine_controller.reset_camera_settings()
        overlay_changes: dict[str, object] = {}
        if "toggles" in selected:
            self._configure_capture_preferences(
                mark_dirty=False,
                auto_record=False,
                belt_calibration=False,
            )
            overlay_changes.update(
                all_enabled=True,
                preview=False,
                metrics=True,
                locked=True,
            )
            self._configure_analysis(
                behavior_enabled=True,
                rppg_enabled=False,
            )
        if "overlay" in selected:
            overlay_changes["opacity"] = 55
            overlay_changes["geometry"] = None
        if overlay_changes:
            self._configure_overlay(**overlay_changes)
        if "web" in selected:
            self._configure_web_preferences(allow_lan=False, mark_dirty=False)
        if "replay" in selected:
            self._replay_state.reset_configuration()
        self._settings_dirty = True

    def _desktop_control_state(self) -> dict[str, Any]:
        camera = self._engine_controller.camera_snapshot()
        analysis = self._engine_controller.analysis_snapshot()
        pipeline = self._engine_controller.pipeline_snapshot()
        replay = self._engine_controller.replay_snapshot()
        cameras = [
            {
                "index": device.index,
                "label": device.label,
            }
            for device in camera.devices
        ]
        state = {
            "desktop_api_version": DESKTOP_CONTROL_API_VERSION,
            "engine_mode": self._engine_mode,
            "pipeline_running": pipeline.running,
            "recording": pipeline.recording,
            "recording_finalizing": not pipeline.recording and (
                self._video_thread is not None
                or self._video_worker is not None
                or self._finalizing_metrics_recorder is not None
            ),
            "recording_path": str(self._recording_db_path or ""),
            "auto_capture_active": self._engine_runtime.timer_active("auto_capture"),
            "monitor_focus": bool(getattr(self, "_monitor_focus", False)),
            "selected_camera_index": camera.selected_index,
            "camera_scanning": self._engine_runtime.worker("camera_scan") is not None,
            "cameras": cameras,
            "behavior_enabled": analysis.fatigue_enabled,
            "rppg_enabled": analysis.rppg_enabled,
            "horizontal_flip": camera.horizontal_flip,
            "resolution": camera.resolution,
            "fps": camera.fps,
            "backend": camera.backend,
            **self._web_preferences.to_desktop_state(),
            "hotkeys": {
                "toggle_metrics": self._hotkeys.toggle_metrics,
                "toggle_preview": self._hotkeys.toggle_preview,
                "start_stop": self._hotkeys.start_stop,
                "lock_overlay": self._hotkeys.lock_overlay,
                "toggle_all": self._hotkeys.toggle_all,
                "toggle_recording": self._hotkeys.toggle_recording,
            },
            "hotkey_registration": {
                "supported": self._global_hotkey_runtime.supported,
                "failures": list(self._hotkey_registration_failures),
            },
            "user_profile": {
                "age": self._user.age,
                "height_cm": self._user.height_cm,
                "weight_kg": self._user.weight_kg,
                "bmi": round(
                    self._user.weight_kg / ((self._user.height_cm / 100.0) ** 2),
                    1,
                ),
            },
            "alarm": self._alarm_config.to_dict(),
            "settings_dirty": bool(self._settings_dirty),
            "desktop_notice": self._desktop_notice,
            "profile_loaded": self._personal_profile is not None,
            "profile_status": self._profile_status,
            "replay_running": replay.running,
            "replay_stopping": replay.stopping,
            "belt_config": {
                "name_prefix": self._belt_cfg.name_prefix if self._belt_cfg else "",
                "address": self._belt_cfg.address if self._belt_cfg else "",
                "rppg_param_tuning_enabled": bool(self._belt_cfg.rppg_param_tuning_enabled) if self._belt_cfg else False,
                "capture_enabled": bool(self._belt_cfg.capture_enabled) if self._belt_cfg else False,
            },
        }
        state.update(self._overlay_state.to_desktop_state())
        state.update(self._replay_state.to_desktop_state())
        state.update(self._capture_preferences.to_desktop_state())
        return state

    def _handle_desktop_command(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if command == "state.get":
            return self._desktop_control_state()

        if command == "pipeline.set":
            enabled = self._require_bool(args, "enabled")
            if enabled and self._engine_runtime.worker("camera_scan") is not None:
                raise BusyError("Wait for camera discovery before starting the pipeline")
            if enabled and self.selected_camera_index is None:
                raise ValueError("Select a camera before starting the pipeline")
            pipeline = self._engine_controller.pipeline_snapshot()
            if pipeline.cleanup_pending:
                self._fail_closed_pipeline_adapters()
                pipeline = self._engine_controller.pipeline_snapshot()
                if pipeline.cleanup_pending:
                    raise BusyError("Live pipeline adapter cleanup is still pending")
            if enabled and self._engine_controller.replay_snapshot().running:
                raise BusyError("Stop replay before starting the live pipeline")
            if enabled != pipeline.running:
                self._pipeline_running = pipeline.running
                self._toggle_pipeline()

        elif command == "recording.set":
            enabled = self._require_bool(args, "enabled")
            pipeline = self._engine_controller.pipeline_snapshot()
            if enabled and not pipeline.running:
                raise ValueError("Start the pipeline before recording")
            if enabled and not pipeline.recording and (
                self._finalizing_metrics_recorder is not None
                or self._video_thread is not None
                or self._video_worker is not None
            ):
                raise BusyError("Previous recorder cleanup is still pending")
            if enabled != pipeline.recording:
                self._pipeline_running = pipeline.running
                self._recording = pipeline.recording
                self._toggle_recording()

        elif command == "camera.select":
            if self._engine_controller.pipeline_snapshot().running:
                raise BusyError("Stop the pipeline before changing camera")
            raw_index = args.get("index")
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ValueError("index must be an integer")
            self._engine_controller.select_camera(raw_index)
            self._settings_dirty = True

        elif command == "camera.refresh":
            if self._engine_controller.pipeline_snapshot().running:
                raise BusyError("Stop the pipeline before refreshing cameras")
            self._start_camera_scan()

        elif command == "camera.configure":
            if self._engine_controller.pipeline_snapshot().running:
                raise BusyError("Stop the pipeline before changing camera settings")
            camera_args: dict[str, object] = {
                key: args[key]
                for key in ("resolution", "fps", "backend")
                if key in args
            }
            if "horizontal_flip" in args:
                camera_args["horizontal_flip"] = self._require_bool(args, "horizontal_flip")
            self._engine_controller.configure_camera(**camera_args)
            self._settings_dirty = True

        elif command == "analysis.configure":
            current_analysis = self._engine_controller.analysis_snapshot()
            behavior_enabled = (
                self._require_bool(args, "behavior_enabled")
                if "behavior_enabled" in args
                else current_analysis.fatigue_enabled
            )
            rppg_enabled = (
                self._require_bool(args, "rppg_enabled")
                if "rppg_enabled" in args
                else current_analysis.rppg_enabled
            )
            self._configure_analysis(
                behavior_enabled=behavior_enabled,
                rppg_enabled=rppg_enabled,
            )
            self._settings_dirty = True

        elif command == "preferences.configure":
            capture_changes: dict[str, object] = {}
            for key in ("auto_record", "belt_calibration"):
                if key in args:
                    capture_changes[key] = self._require_bool(args, key)
            overlay_changes: dict[str, object] = {}
            for key, field in (
                ("overlay_preview", "preview"),
                ("overlay_metrics", "metrics"),
                ("overlay_locked", "locked"),
            ):
                if key in args:
                    overlay_changes[field] = self._require_bool(args, key)
            if capture_changes:
                self._configure_capture_preferences(**capture_changes)
            if overlay_changes:
                self._configure_overlay(**overlay_changes)

        elif command == "auto_capture.set":
            enabled = self._require_bool(args, "enabled")
            if enabled:
                if self._engine_runtime.worker("camera_scan") is not None:
                    raise BusyError("Wait for camera discovery before starting capture")
                capture = self._capture_preferences.snapshot()
                duration = args.get("duration_seconds", capture.auto_capture_seconds)
                if isinstance(duration, bool) or not isinstance(duration, int) or not 10 <= duration <= 600:
                    raise ValueError("duration_seconds must be between 10 and 600")
                include_belt = (
                    self._require_bool(args, "include_belt")
                    if "include_belt" in args
                    else False
                )
                if not self._engine_runtime.timer_active("auto_capture"):
                    self._configure_capture_preferences(
                        auto_capture_seconds=duration,
                        auto_capture_include_belt=include_belt,
                    )
                    self._on_auto_capture_clicked()
            elif self._engine_runtime.timer_active("auto_capture"):
                self._on_auto_capture_clicked()

        elif command == "auto_capture.configure":
            capture = self._capture_preferences.snapshot()
            duration = args.get("duration_seconds", capture.auto_capture_seconds)
            if isinstance(duration, bool) or not isinstance(duration, int) or not 10 <= duration <= 600:
                raise ValueError("duration_seconds must be between 10 and 600")
            capture_changes = {"auto_capture_seconds": duration}
            if "include_belt" in args:
                capture_changes["auto_capture_include_belt"] = self._require_bool(
                    args, "include_belt"
                )
            self._configure_capture_preferences(**capture_changes)

        elif command == "monitor.layout":
            self._set_monitor_layout(self._require_bool(args, "focus"))

        elif command == "overlay.configure":
            overlay_changes = {}
            if "all" in args:
                overlay_changes["all_enabled"] = self._require_bool(args, "all")
            if "opacity" in args:
                opacity = args["opacity"]
                if isinstance(opacity, bool) or not isinstance(opacity, int) or not 0 <= opacity <= 100:
                    raise ValueError("opacity must be between 0 and 100")
                overlay_changes["opacity"] = opacity
            if "geometry" in args:
                overlay_changes["geometry"] = args["geometry"]
            if overlay_changes:
                self._configure_overlay(**overlay_changes)

        elif command == "replay.configure":
            replay = self._engine_controller.replay_snapshot()
            if replay.running or self._replay_thread is not None:
                raise BusyError("Stop the replay before changing replay settings")
            replay_changes: dict[str, object] = {}
            if "path" in args:
                raw_path = args.get("path")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError("path must be a non-empty string")
                selected = Path(raw_path).expanduser()
                if not selected.exists() or not selected.is_dir():
                    raise ValueError(f"Replay folder is unavailable: {selected}")
                replay_changes["dataset_dir"] = selected
            if "jobs" in args:
                jobs = args.get("jobs")
                if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 4:
                    raise ValueError("jobs must be between 1 and 4")
                replay_changes["jobs"] = jobs
            if "annotated" in args:
                replay_changes["annotated"] = self._require_bool(args, "annotated")
            if replay_changes:
                self._configure_replay(**replay_changes)

        elif command == "replay.set":
            enabled = self._require_bool(args, "enabled")
            replay = self._engine_controller.replay_snapshot()
            if not enabled:
                self._stop_replay()
            elif not replay.running and self._replay_thread is None:
                pipeline = self._engine_controller.pipeline_snapshot()
                if pipeline.running or pipeline.recording:
                    raise BusyError("Stop the live pipeline and recording before replay")
                if self._replay_state.snapshot().dataset_dir is None:
                    raise ValueError("Choose a replay folder before starting replay")
                mode = str(args.get("mode", "single"))
                if mode == "parallel":
                    self._start_replay_parallel(notify=False)
                elif mode == "single":
                    self._start_replay()
                else:
                    raise ValueError("mode must be single or parallel")
            elif not replay.running:
                raise BusyError("Replay adapter is still shutting down")

        elif command == "hotkeys.configure":
            previous_hotkeys = self._hotkeys
            self._hotkeys = self._parse_hotkey_config(args)
            try:
                self._apply_hotkey_shortcuts()
            except Exception as exc:
                self._hotkeys = previous_hotkeys
                try:
                    self._apply_hotkey_shortcuts()
                except Exception:
                    logger.exception("回復舊快捷鍵時發生錯誤")
                raise HotkeyApplyError(f"Failed to apply hotkeys: {exc}") from exc
            self._settings_dirty = True

        elif command == "user_profile.configure":
            self._user = self._parse_user_profile(args)
            self._settings_dirty = True

        elif command == "alarm.configure":
            self._alarm_config = self._parse_alarm_config(args)
            self._engine_runtime.configure_alarm(self._alarm_config)
            self._settings_dirty = True

        elif command == "alarm.test":
            if not set(args).issubset({"scenario", "alarm"}) or "scenario" not in args:
                raise ValueError("alarm.test accepts scenario and an optional alarm draft")
            scenario = args["scenario"]
            if not isinstance(scenario, str) or scenario not in ALARM_SCENARIO_KEYS:
                raise ValueError("scenario must be a supported alarm scenario")
            preview_config = (
                self._parse_alarm_config({"alarm": args["alarm"]})
                if "alarm" in args
                else self._alarm_config
            )
            source = self._engine_runtime.preview_alarm(
                scenario,
                config=preview_config,
            )
            if source is None:
                raise AlarmUnplayableError("alarm sound could not be played")
            state = self._desktop_control_state()
            state["command_result"] = {
                "command": "alarm.test",
                "scenario": scenario,
                "dispatched": True,
                "source": source,
            }
            return state

        elif command == "settings.reset":
            self._reset_settings_sections(self._parse_settings_reset_sections(args))

        elif command == "settings.action":
            action = str(args.get("action", ""))
            if action == "web_lan":
                enabled = self._require_bool(args, "enabled")
                self._configure_web_preferences(allow_lan=enabled)
            elif action == "recordings":
                state = self._desktop_control_state()
                state["command_result"] = {
                    "command": "settings.action",
                    "action": action,
                    "shell_action": {
                        "kind": "open_path",
                        "target": str(self._recordings_dir()),
                    },
                }
                return state
            elif action == "save":
                self._on_save_layout()
            elif action == "web":
                url = self._on_web_info()
                state = self._desktop_control_state()
                state["command_result"] = {
                    "command": "settings.action",
                    "action": action,
                    "shell_action": {
                        "kind": "open_url",
                        "target": url,
                    },
                }
                return state
            else:
                raise ValueError(f"Unsupported settings action: {action}")

        elif command == "baseline.start":
            analysis = self._engine_controller.analysis_snapshot()
            if (
                not self._engine_controller.pipeline_snapshot().running
                or not analysis.fatigue_enabled
            ):
                raise ValueError("Behavior analysis must be running before baseline capture")
            self._on_record_baseline_clicked()

        elif command == "settings.save":
            if args:
                raise ValueError("settings.save does not accept arguments")
            path = self._save_settings()
            state = self._desktop_control_state()
            state["command_result"] = {
                "command": "settings.save",
                "path": str(path),
            }
            return state

        elif command == "app.shutdown":
            self._engine_runtime.defer(0, self._shutdown_engine)

        else:
            raise ValueError(f"Unsupported desktop command: {command}")

        return self._desktop_control_state()

    def _shutdown_engine(self) -> None:
        if self._engine_controller.request_shutdown() == "stop_replay":
            self._stop_replay()
            return
        if self._runtime_cleanup_retry_scheduled:
            return
        if not self._cleanup_runtime():
            if (
                not self._runtime_adapter_threads_stopped()
                or self._finalizing_metrics_recorder is not None
                or self._web_finalizing_servers
                or self._engine_controller.belt_running
            ):
                self._runtime_shutdown_waiting_for_adapters = True
                return
            if not self._runtime_cleanup_retry_attempted:
                self._runtime_cleanup_retry_attempted = True
                self._runtime_cleanup_retry_scheduled = True
                self._engine_runtime.defer(100, self._retry_runtime_shutdown)
                return
            logger.error("Engine runtime cleanup remained incomplete after retry")
        self._runtime_shutdown_waiting_for_adapters = False
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _retry_runtime_shutdown(self) -> None:
        self._runtime_cleanup_retry_scheduled = False
        self._shutdown_engine()

    def close_runtime(self) -> bool:
        """Drain remaining data after the application event loop has returned."""
        self._runtime_shutdown_waiting_for_adapters = False
        self._stop_replay()
        self._cleanup_runtime()
        drains: list[tuple[str, Callable[[], bool]]] = []
        recorder = self._finalizing_metrics_recorder
        if recorder is not None:
            drains.append(("metrics", lambda: recorder.wait_closed(timeout_seconds=None)))
        for server in tuple(self._web_finalizing_servers):
            drains.append(("web server", lambda current=server: self._drain_web_server(current)))
        if self._engine_controller.belt_running:
            drains.append(("belt", lambda: self._engine_controller.stop_belt(join_timeout=None)))
        drains.append(("adapters", self._engine_runtime.close_adapters))
        drained = True
        for label, action in drains:
            try:
                if action() is False:
                    drained = False
            except Exception:
                drained = False
                logger.exception("Engine final drain failed: %s", label)
        self._poll_metrics_finalization()
        self._poll_web_finalization(retry_failed=False)
        if self._engine_runtime.timer_active("belt_finalize"):
            self._poll_belt_finalization()
        return self._cleanup_runtime() and drained

    def _drain_web_server(self, server: WebServerThread) -> bool:
        if server.stop(join_timeout=None):
            return True
        if self._retry_web_finalization(server):
            return server.stop(join_timeout=None)
        return False

    def _cleanup_runtime(self) -> bool:
        if self._runtime_cleanup_complete:
            return True
        if self._runtime_cleanup_in_progress:
            return False
        self._runtime_cleanup_in_progress = True
        had_error = False

        def cleanup_step(label: str, action: Callable[[], Any]) -> Any | None:
            nonlocal had_error
            try:
                return action()
            except Exception:
                had_error = True
                logger.exception("Engine runtime cleanup step failed: %s", label)
                return None

        try:
            cleanup_step(
                "desktop command timer",
                lambda: self._engine_runtime.cancel_timer("desktop_command"),
            )
            cleanup_step("global hotkeys", self._unregister_global_hotkeys)
            cleanup_step("auto-capture timer", self._cancel_pending_auto_capture_timer)
            if self._belt_calibrator is not None:
                cleanup_step(
                    "belt calibration",
                    self._stop_belt_calibration,  # 存本次 session 校準版本
                )
            cleanup_step(
                "belt timer",
                lambda: self._engine_runtime.cancel_timer("belt_tick"),
            )
            cleanup_step("belt runtime", self._stop_belt_runtime)
            cleanup_step(
                "camera discovery", lambda: self._engine_runtime.stop_adapter("camera_scan", 0)
            )
            self._web_restart_shutdown = True
            self._web_restart_scheduled = False
            cleanup_step("web server", self._stop_web_server)
            cleanup_step("recording", self._stop_recording)
            cleanup_step("camera and analysis adapters", self._stop_camera_worker)
            cleanup_step("alarm", self._engine_runtime.close_alarm)
            adapters_stopped = self._runtime_adapter_threads_stopped()
            self._runtime_cleanup_complete = (
                not had_error
                and adapters_stopped
                and self._finalizing_metrics_recorder is None
                and not self._web_finalizing_servers
                and not self._engine_controller.belt_running
            )
            return self._runtime_cleanup_complete
        finally:
            self._runtime_cleanup_in_progress = False

    def _runtime_adapter_threads_stopped(self) -> bool:
        return self._engine_runtime.all_stopped()

    def _emit_web_metrics(self, *, force: bool = False) -> None:
        if self._web_server is None:
            return
        now = time.perf_counter()
        if not force and now - self._web_last_emit < self._web_emit_interval:
            return
        metrics = self._build_web_metrics()
        self._web_metrics_buffer.append(metrics)
        self._web_server.broadcast_metrics(metrics)
        self._web_last_emit = now

    @staticmethod
    def _encode_frame_jpeg(image: QImage, *, max_width: int = 640, quality: int = 70) -> str | None:
        if image is None:
            return None
        if image.width() > max_width:
            image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        if image.format() != QImage.Format.Format_RGB888:
            image = image.convertToFormat(QImage.Format.Format_RGB888)
        buffer = QByteArray()
        qbuffer = QBuffer(buffer)
        if not qbuffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        writer = QImageWriter(qbuffer, b"JPEG")
        writer.setQuality(quality)
        ok = writer.write(image)
        qbuffer.close()
        if not ok:
            return None
        return bytes(cast(Any, buffer.toBase64())).decode("ascii")

    def _emit_web_frame(self, image: QImage) -> None:
        if self._web_server is None or self._web_server.client_count == 0:
            return
        now = time.perf_counter()
        if now - self._web_last_frame_emit < self._web_frame_interval:
            return
        try:
            b64 = self._encode_frame_jpeg(image)
        except Exception as exc:
            if not getattr(self, "_web_frame_encode_err_logged", False):
                self._append_log(f"⚠ Web 預覽影格編碼失敗：{exc}")
                self._web_frame_encode_err_logged = True
            return
        if not b64:
            return
        self._web_server.broadcast_frame(b64)
        self._web_last_frame_emit = now

    def _start_recording(self) -> None:
        if self._video_thread is not None or self._video_worker is not None:
            raise RuntimeError("Previous video recorder cleanup is still pending")
        if self._finalizing_metrics_recorder is not None:
            raise RuntimeError("Previous metrics recorder cleanup is still pending")
        if self._metrics_recorder is not None:
            return
        rec_dir = self._recordings_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        db_path = rec_dir / f"metrics_{stamp}.db"
        self._metrics_recorder = MetricsRecorder(str(db_path))
        self._recording_db_path = db_path
        self._recording_started_at = time.time()
        self._recording_count = 0

        self._video_queue = queue.Queue(maxsize=8)
        video_path = rec_dir / f"video_{stamp}.mp4"
        self._recording_video_path = video_path
        worker = VideoRecorderWorker(self._video_queue, video_path, fps=self._last_fps or 30.0)
        self._engine_runtime.start_adapter(
            "video",
            worker,
            connect=lambda current: (
                current.started.connect(self._on_video_recording_started),
                current.warning.connect(self._on_video_recording_warning),
                current.failed.connect(self._on_video_recording_failed),
            ),
        )
        self._update_recording_routing()

    def _stop_recording(self) -> bool:
        self._engine_controller.stop_recording()
        self._recording = False
        if self._metrics_recorder is not None:
            self._metrics_recorder.request_close()
            self._finalizing_metrics_recorder = self._metrics_recorder
            self._metrics_recorder = None
        self._poll_metrics_finalization()
        if (
            self._finalizing_metrics_recorder is not None
            and not self._engine_runtime.timer_active("metrics_finalize")
        ):
            self._engine_runtime.start_periodic_timer(
                "metrics_finalize", 50, self._poll_metrics_finalization
            )
        if self._video_worker is not None:
            try:
                self._engine_runtime.request_adapter_stop("video")
            except Exception as exc:
                logger.warning("停止影片記錄器失敗：%s", exc)
        stopped = True
        if self._video_thread is not None:
            try:
                stopped = self._engine_runtime.join_adapter("video", 0)
            except Exception as exc:
                stopped = False
                logger.warning("等待影片記錄執行緒結束失敗：%s", exc)
        self._recording_db_path = None
        self._recording_started_at = None
        if stopped:
            self._video_queue = None
            self._recording_video_path = None
        self._update_recording_routing()
        return stopped

    def _poll_metrics_finalization(self) -> None:
        recorder = self._finalizing_metrics_recorder
        if recorder is None or not recorder.wait_closed(timeout_seconds=0):
            return
        self._finalizing_metrics_recorder = None
        self._engine_runtime.cancel_timer("metrics_finalize")
        self._emit_web_metrics(force=True)
        if self._runtime_shutdown_waiting_for_adapters:
            self._engine_runtime.defer(0, self._shutdown_engine)

    def _build_record_payload(self) -> dict:
        r = self._latest_rppg_metrics
        f = self._latest_fatigue_metrics
        z = self._latest_fused_score
        info = self._last_camera_info

        return {
            "timestamp": time.time(),
            "fps": float(self._last_fps or 0.0),
            "frame_width": int(info.get("width") or 0),
            "frame_height": int(info.get("height") or 0),
            "codec": str(info.get("codec") or ""),
            "camera_label": self._engine_controller.selected_camera_label(),
            "rppg_face_detected": 1 if getattr(r, "face_detected", False) else 0,
            "bpm": float(getattr(r, "bpm", 0.0) or 0.0),
            "bpm_calibrated": float(getattr(r, "bpm_calibrated", 0.0) or 0.0),
            "calibration_version_id": str(getattr(r, "calibration_version_id", "") or ""),
            "peak_freq_hz_calibrated": float(getattr(r, "peak_freq_hz_calibrated", 0.0) or 0.0),
            "raw_bpm": float(getattr(r, "raw_bpm", 0.0) or 0.0),
            "bpm_delta": float(getattr(r, "bpm_delta", 0.0) or 0.0),
            "bpm_guarded": 1 if getattr(r, "bpm_guarded", False) else 0,
            "bpm_guard_reason": str(getattr(r, "bpm_guard_reason", "") or ""),
            "rmssd": float(getattr(r, "rmssd", 0.0) or 0.0),
            "sdnn": float(getattr(r, "sdnn", 0.0) or 0.0),
            "lf_hf": float(getattr(r, "lf_hf", 0.0) or 0.0),
            "sqi": float(getattr(r, "sqi", 0.0) or 0.0),
            "rppg_quality_score": float(getattr(r, "quality_score", 0.0) or 0.0),
            "rppg_pose_roll_deg": float(getattr(r, "pose_roll_deg", 0.0) or 0.0),
            "rppg_pose_yaw_deg": float(getattr(r, "pose_yaw_deg", 0.0) or 0.0),
            "rppg_pose_pitch_deg": float(getattr(r, "pose_pitch_deg", 0.0) or 0.0),
            "rppg_roi_valid_count": int(getattr(r, "roi_valid_count", 0) or 0),
            "rppg_roi_weight_forehead": float(getattr(r, "roi_weight_forehead", 0.0) or 0.0),
            "rppg_roi_weight_l_cheek": float(getattr(r, "roi_weight_l_cheek", 0.0) or 0.0),
            "rppg_roi_weight_r_cheek": float(getattr(r, "roi_weight_r_cheek", 0.0) or 0.0),
            "rppg_roi_weight_glabella": float(getattr(r, "roi_weight_glabella", 0.0) or 0.0),
            "rppg_landmark_jitter_norm": float(getattr(r, "landmark_jitter_norm", 0.0) or 0.0),
            "rppg_roi_area_stability": float(getattr(r, "roi_area_stability", 0.0) or 0.0),
            "rppg_roi_area_jitter_ratio": float(getattr(r, "roi_area_jitter_ratio", 0.0) or 0.0),
            "rppg_roi_smoothing_applied": 1 if getattr(r, "roi_smoothing_applied", False) else 0,
            "rppg_canonical_roi_warp_used": 1 if getattr(r, "canonical_roi_warp_used", False) else 0,
            "stress_prob": float(getattr(r, "stress_prob", 0.0) or 0.0),
            "stress_status": str(getattr(r, "stress_status", "") or ""),
            "hrv_confidence": str(getattr(r, "hrv_confidence", "") or ""),
            "ibi_artifact_ratio": float(getattr(r, "ibi_artifact_ratio", 0.0) or 0.0),
            "peak_freq_hz": float(getattr(r, "peak_freq_hz", 0.0) or 0.0),
            "frame_brightness": float(getattr(r, "frame_brightness", 0.0) or 0.0),
            "warmup_progress": float(getattr(r, "warmup_progress", 0.0) or 0.0),
            "fatigue_face_detected": 1 if getattr(f, "face_detected", False) else 0,
            "calibrated": 1 if getattr(f, "calibrated", False) else 0,
            "status": str(getattr(f, "status", "") or ""),
            "fatigue_level": float(getattr(f, "fatigue_level", 0.0) or 0.0),
            "fatigue_quality_score": float(getattr(f, "quality_score", 0.0) or 0.0),
            "fatigue_blend_calib_progress": float(getattr(f, "blend_calib_progress", 0.0) or 0.0),
            "early_warning": 1 if getattr(f, "early_warning", False) else 0,
            "ear": float(getattr(f, "ear", 0.0) or 0.0),
            "ear_smooth": float(getattr(f, "ear_smooth", 0.0) or 0.0),
            "blink_count": int(getattr(f, "blink_count", 0) or 0),
            "perclos": float(getattr(f, "perclos", 0.0) or 0.0),
            "blink_rate_pm": float(getattr(f, "blink_rate_pm", 0.0) or 0.0),
            "blink_duration_sec": float(getattr(f, "blink_duration_sec", 0.0) or 0.0),
            "blink_duration_mean_sec": float(getattr(f, "blink_duration_mean_sec", 0.0) or 0.0),
            "blink_duration_z": float(getattr(f, "blink_duration_z", 0.0) or 0.0),
            "blink_amplitude": float(getattr(f, "blink_amplitude", 0.0) or 0.0),
            "blink_opening_velocity": float(getattr(f, "blink_opening_velocity", 0.0) or 0.0),
            "blink_opening_velocity_z": float(getattr(f, "blink_opening_velocity_z", 0.0) or 0.0),
            "blink_temporal_score": float(getattr(f, "blink_temporal_score", 0.0) or 0.0),
            "is_squinting": 1 if getattr(f, "is_squinting", False) else 0,
            "squint_duration": float(getattr(f, "squint_duration", 0.0) or 0.0),
            "is_frowning": 1 if getattr(f, "is_frowning", False) else 0,
            "brow_dist_norm": float(getattr(f, "brow_dist_norm", 0.0) or 0.0),
            "iris_ratio": float(getattr(f, "iris_ratio", 0.0) or 0.0),
            "iris_ratio_trend": float(getattr(f, "iris_ratio_trend", 0.0) or 0.0),
            "gaze_x": float(getattr(f, "gaze_x", 0.0) or 0.0),
            "gaze_y": float(getattr(f, "gaze_y", 0.0) or 0.0),
            "gaze_stability_index": float(getattr(f, "gaze_stability_index", 0.0) or 0.0),
            "gaze_mental_fatigue": 1 if getattr(f, "gaze_mental_fatigue", False) else 0,
            "saccadic_velocity": float(getattr(f, "saccadic_velocity", 0.0) or 0.0),
            "is_saccade": 1 if getattr(f, "is_saccade", False) else 0,
            "fixation_duration": float(getattr(f, "fixation_duration", 0.0) or 0.0),
            "saccade_freq_pm": float(getattr(f, "saccade_freq_pm", 0.0) or 0.0),
            "head_pitch": float(getattr(f, "head_pitch", 0.0) or 0.0),
            "head_yaw": float(getattr(f, "head_yaw", 0.0) or 0.0),
            "head_roll": float(getattr(f, "head_roll", 0.0) or 0.0),
            "microsleep_alert": 1 if getattr(f, "microsleep_alert", False) else 0,
            "microsleep_count": int(getattr(f, "microsleep_count", 0) or 0),
            "mar": float(getattr(f, "mar", 0.0) or 0.0),
            "yawn_detected": 1 if getattr(f, "yawn_detected", False) else 0,
            "yawn_count": int(getattr(f, "yawn_count", 0) or 0),
            "has_iris": 1 if getattr(f, "has_iris", False) else 0,
            "calib_progress": float(getattr(f, "calib_progress", 0.0) or 0.0),
            "fused_score": float(getattr(z, "score", 0.0) or 0.0),
            "fused_level": str(getattr(z, "level", "") or ""),
            "fused_level_en": str(getattr(z, "level_en", "") or ""),
            "fused_rppg_sub": float(getattr(z, "rppg_sub", 0.0) or 0.0),
            "fused_behavior_sub": float(getattr(z, "behavior_sub", 0.0) or 0.0),
            "fused_rppg_weight_eff": float(getattr(z, "rppg_weight_eff", 0.0) or 0.0),
            "fused_behavior_weight_eff": float(getattr(z, "behavior_weight_eff", 0.0) or 0.0),
            "fused_trend": float(getattr(z, "trend", 0.0) or 0.0),
            "fused_trend_symbol": str(getattr(z, "trend_symbol", "") or ""),
            "fused_rppg_available": 1 if getattr(z, "rppg_available", False) else 0,
            "fused_behavior_available": 1 if getattr(z, "behavior_available", False) else 0,
            "fused_rppg_stress_score": float(getattr(z, "rppg_stress_score", 0.0) or 0.0),
            "fused_rppg_bpm_score": float(getattr(z, "rppg_bpm_score", 0.0) or 0.0),
            "fused_beh_perclos_score": float(getattr(z, "beh_perclos_score", 0.0) or 0.0),
            "fused_beh_blink_temporal_score": float(getattr(z, "beh_blink_temporal_score", 0.0) or 0.0),
            "fused_beh_squint_score": float(getattr(z, "beh_squint_score", 0.0) or 0.0),
            "fused_beh_microsleep_score": float(getattr(z, "beh_microsleep_score", 0.0) or 0.0),
            "fused_beh_gaze_score": float(getattr(z, "beh_gaze_score", 0.0) or 0.0),
            "fused_beh_frown_score": float(getattr(z, "beh_frown_score", 0.0) or 0.0),
            "fused_beh_yawn_score": float(getattr(z, "beh_yawn_score", 0.0) or 0.0),
        }

    def _record_metrics(self) -> None:
        if self._metrics_recorder is None:
            return
        payload = self._build_record_payload()
        self._metrics_recorder.record(payload)
        self._recording_count += 1

    def _on_video_recording_started(self, path: str) -> None:
        try:
            self._recording_video_path = Path(path)
        except Exception:
            self._recording_video_path = None
        if self._recording_video_path is not None:
            self._append_log(f"● 影片錄製 → {self._recording_video_path}")

    def _on_video_recording_warning(self, msg: str) -> None:
        self._append_log(f"⚠ {msg}")
        self._notify_user("影片錄製", msg)

    def _on_video_recording_failed(self, msg: str) -> None:
        self._append_log(f"✗ 影片錄製失敗：{msg}")
        self._recording = False
        self._stop_recording()
        self._notify_user("影片錄製", msg)

    def _append_log(self, msg: str) -> None:
        severity = _classify_log_message(msg, warning_priority=True)
        if severity == "error":
            logger.error("%s", msg)
        elif severity == "warning":
            logger.warning("%s", msg)
        else:
            logger.info("%s", msg)

    def _publish_desktop_notice(self, message: str, *, level: str = "error") -> None:
        """Publish a one-shot UI notice for the Flutter/Tauri shell."""
        self._desktop_notice_seq += 1
        self._desktop_notice = {
            "id": self._desktop_notice_seq,
            "level": level,
            "message": str(message),
        }

    def _notify_user(self, title: str, message: str, *, level: str = "error") -> None:
        self._publish_desktop_notice(f"{title}：{message}", level=level)

    def _start_replay(self) -> None:
        self._start_replay_run(jobs=1, preview_enabled=True, mode_label="回放中")

    def _start_replay_parallel(self, *, notify: bool = True) -> None:
        replay_state = self._replay_state.snapshot()
        jobs = replay_state.jobs
        if replay_state.annotated:
            self._configure_replay(annotated=False)
            self._append_log("[影片回測] 平行驗證已自動關閉輸出標註影片；需要標註畫面請用「開始批次」單工模式")
            if notify:
                self._notify_user(
                    "影片回測平行驗證",
                    "平行驗證會同時啟動多個 MediaPipe/影片解碼流程。為避免子行程崩潰，已自動關閉「輸出標註影片」。\n\n"
                    "需要標註影片時，請改用「開始批次」單工模式。正式大量驗證建議平行數 2-4。",
                    level="info",
                )
        self._start_replay_run(jobs=jobs, preview_enabled=False, mode_label=f"平行驗證中 x{jobs}")

    def _start_replay_run(self, *, jobs: int, preview_enabled: bool, mode_label: str) -> None:
        replay = self._engine_controller.replay_snapshot()
        if replay.running or self._replay_thread is not None:
            return
        pipeline = self._engine_controller.pipeline_snapshot()
        if pipeline.running or pipeline.recording:
            self._notify_user("影片回測", "請先停止即時攝影機流程與錄影，再啟動影片批次測試。", level="info")
            return
        replay_state = self._replay_state.snapshot()
        if replay_state.dataset_dir is None:
            self._append_log("[影片回測] 尚未由正式桌面面板設定資料夾")
            return
        if not replay_state.dataset_dir.exists():
            self._notify_user("影片回測", f"找不到資料夾：\n{replay_state.dataset_dir}")
            return

        previous_replay_state = self._replay_state.snapshot()
        self._engine_controller.start_replay()
        try:
            worker = VideoReplayWorker(
                replay_state.dataset_dir,
                write_annotated_video=replay_state.annotated,
                jobs=jobs,
                preview_enabled=preview_enabled,
            )
            self._replay_stopping = False
            self._replay_state.begin(
                mode_label=mode_label,
                parallel_status_text=(
                    "處理清單：等待第一支影片"
                    if preview_enabled
                    else "處理清單：平行驗證等待工作派發"
                ),
            )
            self._replay_active_videos.clear()
            self._replay_recent_done.clear()
            self._append_log(
                f"[影片回測] 開始{mode_label}：{replay_state.dataset_dir} "
                f"(jobs={jobs}, preview={'on' if preview_enabled else 'off'})"
            )
            self._engine_runtime.start_adapter(
                "replay",
                worker,
                connect=lambda current: (
                    current.progress.connect(self._on_replay_progress),
                    current.finished_ok.connect(self._on_replay_finished_ok),
                    current.failed.connect(self._on_replay_failed),
                ),
            )
        except Exception:
            self._replay_state.restore(previous_replay_state)
            self._engine_controller.finish_replay()
            raise

    def _stop_replay(self) -> None:
        if self._replay_worker is None:
            return
        self._engine_controller.request_replay_stop()
        self._replay_stopping = True
        self._engine_runtime.request_adapter_stop("replay")
        self._update_replay_presentation(
            current_text="目前影片：正在停止，請稍候",
            parallel_status_text="處理清單：正在停止，已派發的影片會安全收尾",
        )
        self._append_log("[影片回測] 已送出停止請求，等待目前 frame 安全收尾")

    def _on_replay_progress(
        self,
        event: str,
        current: int,
        total: int,
        summary: ReplayVideoSummary | None,
    ) -> None:
        replay_state = self._replay_state.snapshot()
        total_count = max(replay_state.total_count, total)
        self._update_replay_presentation(total_count=total_count)
        if event == "video_start":
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos[key] = summary
                self._update_replay_presentation(
                    current_text=(
                        f"目前影片：派發 {current}/{total}，正在跑 "
                        f"{len(self._replay_active_videos)} 支"
                    )
                )
            else:
                self._update_replay_presentation(
                    current_text=f"目前影片：{current}/{total}"
                )
            self._refresh_replay_parallel_status()
        elif event == "video_done":
            done_count = max(self._replay_state.snapshot().done_count, current)
            self._update_replay_presentation(done_count=done_count)
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos.pop(key, None)
                self._replay_completed_summaries.append(summary)
                self._replay_recent_done.insert(0, self._format_replay_video_label(summary, include_status=True))
                self._replay_recent_done = self._replay_recent_done[:3]
                failed_text = "，此支失敗" if summary.status == "failed" else ""
                self._update_replay_presentation(
                    current_text=(
                        f"目前影片：已完成 {done_count}/{max(total, 1)}{failed_text}"
                    )
                )
                self._append_log(
                    "[影片回測] 完成 "
                    f"subject {summary.subject} label {summary.label} "
                    f"frames={summary.frames} face_rate={summary.face_rate:.2%} status={summary.status}"
                )
            self._refresh_replay_parallel_status()
        elif event == "frame" and summary is not None:
            key = self._replay_video_key(summary)
            self._replay_active_videos[key] = summary
            if total > 0:
                current_text = (
                    f"目前影片：subject {summary.subject} / label {summary.label} "
                    f"{summary.frames}/{total} frames"
                )
            else:
                current_text = (
                    f"目前影片：subject {summary.subject} / label {summary.label} "
                    f"{summary.frames} frames"
                )
            self._update_replay_presentation(current_text=current_text)
            self._refresh_replay_parallel_status()

    def _replay_video_key(self, summary: ReplayVideoSummary) -> str:
        return f"{summary.subject}:{summary.label}:{summary.video_path}"

    def _format_replay_video_label(self, summary: ReplayVideoSummary, *, include_status: bool = False) -> str:
        label = f"S{summary.subject}/L{summary.label} {summary.label_name}"
        if summary.frames > 0:
            label += f" {summary.frames}f"
        if include_status:
            if summary.status == "failed":
                label += " failed"
            elif summary.status == "stopped":
                label += " stopped"
            elif summary.status:
                label += f" {summary.status}"
            if summary.face_rate > 0:
                label += f" face={summary.face_rate:.0%}"
        return label

    def _refresh_replay_parallel_status(self) -> None:
        active = [self._format_replay_video_label(summary) for summary in self._replay_active_videos.values()]
        active_preview = active[:4]
        if len(active) > len(active_preview):
            active_preview.append(f"另 {len(active) - len(active_preview)} 支")
        active_text = "、".join(active_preview) if active_preview else "無"
        recent_text = "、".join(self._replay_recent_done) if self._replay_recent_done else "尚無"
        replay_state = self._replay_state.snapshot()
        total_text = str(replay_state.total_count) if replay_state.total_count > 0 else "?"
        self._update_replay_presentation(
            parallel_status_text=(
                f"進行中：{active_text}\n"
                f"已完成：{replay_state.done_count}/{total_text}；最近完成：{recent_text}"
            )
        )

    def _on_replay_finished_ok(self, result: ReplayBatchResult) -> None:
        stopped = any(summary.status == "stopped" for summary in result.summaries)
        if stopped or self._replay_stopping:
            state = "已停止"
        elif result.videos_failed > 0:
            state = "完成但有失敗"
        else:
            state = "完成"
        self._update_replay_presentation(
            current_text=f"目前影片：{state}",
            result_text=(
                f"摘要檔：{result.summary_csv}\n"
                f"驗證報表：{result.validation_report_csv}\n"
                f"完整欄位：{result.full_summary_csv}"
            ),
            done_count=result.videos_done + result.videos_failed,
            total_count=result.videos_total,
        )
        self._replay_active_videos.clear()
        if result.summaries and not self._replay_recent_done:
            self._replay_recent_done = [
                self._format_replay_video_label(summary, include_status=True)
                for summary in reversed(result.summaries[-3:])
            ]
        self._refresh_replay_parallel_status()
        self._append_log(
            f"[影片回測] {state}，完成 {result.videos_done} 支，失敗 {result.videos_failed} 支，"
            f"摘要：{result.summary_csv}"
        )

    def _on_replay_failed(self, msg: str) -> None:
        replay_state = self._replay_state.snapshot()
        total_text = str(replay_state.total_count) if replay_state.total_count > 0 else "?"
        self._update_replay_presentation(
            current_text="目前影片：批次失敗",
            parallel_status_text=(
                f"處理清單：批次失敗；已完成 {replay_state.done_count}/{total_text}"
            ),
        )
        self._append_log(f"[影片回測] 批次失敗：{msg}")
        self._notify_user("影片回測", msg)

    def _on_replay_thread_finished(self) -> None:
        self._replay_stopping = False
        self._replay_state.finish_thread()
        if self._engine_controller.finish_replay():
            self._shutdown_engine()

    # ── Camera worker ─────────────────────────────────────────────────────────

    def _start_camera_worker(self) -> None:
        cam_idx = self.selected_camera_index
        if cam_idx is None:
            self._append_log("⚠ 請先選擇攝影機再開始。")
            self._pipeline_running = False
            self._engine_controller.stop_pipeline()
            return

        spec = self._engine_controller.camera_start_spec()
        cam_idx = spec.index
        w, h = spec.width, spec.height
        target_fps = spec.target_fps
        backend = spec.backend
        backend_label = backend.upper()
        horizontal_flip = spec.horizontal_flip
        self._fps_measurement_samples = 0
        self._camera_fps_warning_sent = False

        worker = CameraStreamWorker(cam_idx, width=w, height=h,
                                    target_fps=target_fps, backend=backend,
                                    horizontal_flip=horizontal_flip)
        self._engine_runtime.start_adapter(
            "camera",
            worker,
            connect=lambda current: (
                current.camera_info.connect(self._on_camera_info),
                current.diagnostic_ready.connect(self._append_log),
                current.fps_ready.connect(self._on_fps),
                current.failed.connect(self._on_camera_failed),
            ),
        )
        # Initial frame routing (camera → overlay); may be overridden when
        # rPPG / fatigue workers start and call _update_frame_routing().
        self._update_frame_routing()
        self._append_log(
            f"▶ 相機 [{cam_idx}] 開啟（{backend_label}  {w}×{h} @ {target_fps} fps"
            f"{'，水平翻轉' if horizontal_flip else ''}）"
        )

    def _stop_camera_worker(self) -> bool:
        self._engine_controller.mark_pipeline_cleanup_pending()
        self._fail_closed_pipeline_adapters()
        return self._runtime_adapter_threads_stopped()

    def _fail_closed_pipeline_adapters(self) -> None:
        """Best-effort cleanup after controller can no longer restore live topology."""
        if self._adapter_cleanup_in_progress:
            return
        self._adapter_cleanup_in_progress = True
        try:
            self._fail_closed_pipeline_adapters_impl()
        finally:
            self._adapter_cleanup_in_progress = False

    def _fail_closed_pipeline_adapters_impl(self) -> None:
        """Run fail-closed cleanup once; nested release signals are ignored by the guard."""
        all_stopped = True
        cleanup_steps = [("recording", self._stop_recording)]
        if self._combined_worker is not None or self._combined_thread is not None:
            cleanup_steps.append(("combined", self._stop_combined_worker))
        if self._rppg_worker is not None or self._rppg_thread is not None:
            cleanup_steps.append(("rppg", self._stop_rppg_worker))
        if self._fatigue_worker is not None or self._fatigue_thread is not None:
            cleanup_steps.append(("fatigue", self._stop_fatigue_worker))
        for label, cleanup in cleanup_steps:
            try:
                if cleanup() is False:
                    all_stopped = False
            except Exception as exc:
                all_stopped = False
                logger.warning("fail-closed %s cleanup failed: %s", label, exc)
        camera_steps = [
            ("record route", lambda: self._set_record_source(None)),
            ("frame route", lambda: self._set_frame_source(None)),
        ]
        if self._cam_worker is not None:
            camera_steps.extend(
                (
                    ("camera queues", self._cam_worker.detach_bgr_queue),
                )
            )
        if self._cam_thread is not None:
            camera_steps.append(
                ("camera thread stop", lambda: self._engine_runtime.stop_adapter("camera", 3000))
            )
        camera_thread_stopped = self._cam_thread is None
        for label, cleanup in camera_steps:
            try:
                result = cleanup()
                if label == "camera thread stop":
                    camera_thread_stopped = result is not False
            except Exception as exc:
                all_stopped = False
                logger.warning("fail-closed %s cleanup failed: %s", label, exc)
        if not camera_thread_stopped:
            all_stopped = False
        self._pipeline_running = False
        self._recording = False
        if all_stopped:
            self._engine_controller.finish_pipeline_cleanup()
        else:
            self._engine_controller.mark_pipeline_cleanup_pending()

    def _on_adapter_released(self, kind: str, _thread: object) -> None:
        """Apply adapter queue and shutdown side effects after runtime release."""
        if kind == "camera_scan":
            self._emit_web_metrics(force=True)
        elif kind == "camera":
            pass
        elif kind == "combined":
            self._combined_queue = None
        elif kind == "rppg":
            self._bgr_queue = None
        elif kind == "fatigue":
            self._fatigue_queue = None
        elif kind == "video":
            self._video_queue = None
            self._recording_video_path = None
            self._emit_web_metrics(force=True)
        elif kind == "replay":
            self._on_replay_thread_finished()
            return
        else:
            return
        if (
            self._engine_controller.pipeline_snapshot().cleanup_pending
            and not self._adapter_cleanup_in_progress
        ):
            self._fail_closed_pipeline_adapters()
        if self._runtime_shutdown_waiting_for_adapters:
            self._engine_runtime.defer(0, self._shutdown_engine)

    # ── Frame routing ─────────────────────────────────────────────────────────

    def _update_frame_routing(self) -> None:
        """Ensure exactly ONE frame source drives the overlay (no flicker).

        Priority: combined > rPPG-only > fatigue-only > raw camera.
        """
        if self._combined_worker is not None:
            self._set_frame_source("combined")
        elif self._rppg_worker is not None:
            self._set_frame_source("rppg")
        elif self._fatigue_worker is not None:
            self._set_frame_source("fatigue")
        elif self._cam_worker is not None:
            self._set_frame_source("camera")
        else:
            self._set_frame_source(None)

        if self._recording and self._video_queue is not None:
            self._update_recording_routing()

    def _update_recording_routing(self) -> None:
        """Route recording frames from the same annotated source when possible."""
        if not self._recording or self._video_queue is None:
            self._set_record_source(None)
            return

        if self._combined_worker is not None:
            self._set_record_source("combined")
        elif self._rppg_worker is not None:
            self._set_record_source("rppg")
        elif self._fatigue_worker is not None:
            self._set_record_source("fatigue")
        elif self._cam_worker is not None:
            self._set_record_source("camera")
        else:
            self._set_record_source(None)

    def _set_frame_source(self, source: str | None) -> None:
        if self._frame_source == source:
            return
        self._disconnect_source(self._frame_source, self._on_frame)
        self._connect_source(source, self._on_frame)
        self._frame_source = source

    def _set_record_source(self, source: str | None) -> None:
        if self._record_source == source:
            return
        self._disconnect_source(self._record_source, self._on_record_frame)
        self._connect_source(source, self._on_record_frame)
        self._record_source = source

    def _connect_source(self, source: str | None, handler) -> None:
        if source == "combined" and self._combined_worker is not None:
            self._combined_worker.frame_annotated.connect(handler)
        elif source == "rppg" and self._rppg_worker is not None:
            self._rppg_worker.frame_annotated.connect(handler)
        elif source == "fatigue" and self._fatigue_worker is not None:
            self._fatigue_worker.frame_annotated.connect(handler)
        elif source == "camera" and self._cam_worker is not None:
            self._cam_worker.frame_ready.connect(handler)

    def _disconnect_source(self, source: str | None, handler) -> None:
        try:
            if source == "combined" and self._combined_worker is not None:
                self._combined_worker.frame_annotated.disconnect(handler)
            elif source == "rppg" and self._rppg_worker is not None:
                self._rppg_worker.frame_annotated.disconnect(handler)
            elif source == "fatigue" and self._fatigue_worker is not None:
                self._fatigue_worker.frame_annotated.disconnect(handler)
            elif source == "camera" and self._cam_worker is not None:
                self._cam_worker.frame_ready.disconnect(handler)
        except (TypeError, RuntimeError):
            pass

    # ── Analysis workers (rPPG / fatigue / combined) ──────────────────────────

    # ── 心跳帶真值校準（背景參考，不進疲勞分數）─────────────────────────────

    def _rppg_active(self) -> bool:
        """rPPG 是否正在產生 BPM（心跳帶校準的比對前提）。"""
        pipeline = self._engine_controller.pipeline_snapshot()
        return pipeline.running and pipeline.analysis.rppg_enabled

    def _on_belt_calib_toggled(self, checked: bool) -> None:
        self._append_log(f"[UI] 心跳帶真值校準 → {'開啟' if checked else '關閉'}")
        if (
            checked
            and self._engine_controller.pipeline_snapshot().running
            and not self._rppg_active()
        ):
            self._append_log(
                "⚠ 心跳帶校準需要 rPPG：請勾選「壓力／HRV（心率估測）」，rPPG 啟用後才會開始比對。"
            )
        self._ensure_belt_calibration()

    def _ensure_belt_calibration(self) -> None:
        """依勾選狀態與 rPPG 是否運行，啟停背景心跳帶校準。"""
        want = (
            self._engine_controller.pipeline_snapshot().running
            and self._capture_preferences.snapshot().belt_calibration
            and self._rppg_active()
        )
        if want and self._belt_calibrator is None:
            self._start_belt_calibration()
        elif not want and self._belt_calibrator is not None:
            self._stop_belt_calibration()

    def _start_belt_calibration(self) -> None:
        belt_cfg = load_hr_belt_config()
        self._belt_cfg = belt_cfg
        belt_was_running = self._engine_controller.belt_running
        if not belt_was_running:
            self._engine_controller.clear_belt_samples()
        err = self._engine_controller.start_belt(belt_cfg)
        if err:
            self._append_log(f"⚠ 心跳帶校準啟動失敗：{err}")
            self._capture_preferences.configure(belt_calibration=False)
            return
        if not belt_was_running:
            target = (
                f"位址 {belt_cfg.address}" if belt_cfg.address
                else f"名稱前綴「{belt_cfg.name_prefix}」" if belt_cfg.name_prefix
                else "任何 Heart Rate Service 裝置"
            )
            self._append_log(f"▶ 心跳帶 BLE 啟動（掃描 {target}）")
        # 以目前 active 校準版本的 offset 為起點，跨 session 持續改善。
        # 本階段只做 offset-only 自適應（scale 固定 1.0，與既有手動校準流程一致）；
        # 若日後支援 scale 校準，此 seed 邏輯需一併重新設計。
        try:
            base = self._rppg_calibration_store.get_active_version()
            seed = float(base.params.bpm_offset) if base.model == "bias" else 0.0
        except Exception:
            seed = 0.0
        self._last_calib_fed_metrics = None
        self._belt_calibrator = OnlineBpmCalibrator(initial_offset=seed)
        self._engine_runtime.start_periodic_timer(
            "belt_tick",
            1000,
            self._tick_belt_calibration,
        )
        self._append_log(f"▶ 心跳帶真值校準啟動（背景參考，起始 offset {seed:+.1f} BPM）")
        # P6b-3b：協調層開關（預設 False）。開啟時才建立協調層並記錄目前生效
        # 的 ROI 權重作為 A/B 的「現行」基準；關閉時協調層維持 None，
        # _tick_rppg_param_coordinator / worker 候選重算全部 early-return。
        if belt_cfg.rppg_param_tuning_enabled:
            self._rppg_param_coordinator = RppgParamCoordinator()
            self._rppg_param_current_weights = self._resolve_current_roi_weights()
            self._append_log("▶ rPPG 參數線上協調層已啟用（P6b-3b，實驗性）")
        else:
            self._rppg_param_coordinator = None
        # P6b-4：belt-truth 同步錄製（預設 OFF，見 HrBeltConfig.capture_enabled）。
        # 開啟時建立 writer 並下發給目前運行中的 worker；關閉時維持 None，
        # worker 的 _maybe_capture_belt_truth 全部 early-return。
        if belt_cfg.capture_enabled:
            try:
                writer = self._engine_controller.create_belt_truth_capture_writer()
            except OSError as exc:
                self._belt_truth_capture = None
                self._append_log(f"⚠ belt-truth 錄製檔建立失敗，本次停用錄製：{exc}")
            else:
                self._belt_truth_capture = writer
                self._dispatch_belt_truth_capture(writer)
                self._append_log(f"▶ belt-truth 同步錄製已啟用 → {writer.path}")
        else:
            self._belt_truth_capture = None

    def _dispatch_belt_truth_capture(self, writer: BeltTruthCaptureWriter | None) -> None:
        """把 belt-truth 錄製 writer（或 None＝停用）下發給目前運行中的 worker。"""
        if self._combined_worker is not None:
            self._combined_worker.set_belt_truth_capture(writer)
        if self._rppg_worker is not None:
            self._rppg_worker.set_belt_truth_capture(writer)

    def _rollback_failed_belt_calibration_start(self, *, stop_belt: bool) -> None:
        """Best-effort cleanup for an incomplete calibration start transaction."""
        writer = self._belt_truth_capture
        self._belt_truth_capture = None
        if writer is not None:
            try:
                self._dispatch_belt_truth_capture(None)
            except Exception:
                logger.exception("心跳帶校準啟動回滾時解除錄製 writer 失敗")
            try:
                writer.close()
            except Exception:
                logger.exception("心跳帶校準啟動回滾時關閉錄製 writer 失敗")
        try:
            self._engine_runtime.cancel_timer("belt_tick")
        except Exception:
            logger.exception("心跳帶校準啟動回滾時停止計時器失敗")
        self._rppg_param_coordinator = None
        self._belt_calibrator = None
        self._last_calib_fed_metrics = None
        if stop_belt and self._engine_controller.belt_running:
            try:
                self._stop_belt_runtime()
            except Exception:
                logger.exception("心跳帶校準啟動回滾時停止 BLE 失敗")

    def _resolve_current_roi_weights(self) -> dict[str, float]:
        """P6b-3b：取得目前生效的 ROI base_weights，作為協調層 A/B 的「現行」基準。

        優先讀取目前 active 校準版本的 ``rppg_params.roi_weights``（P6b-2 覆寫，
        經 :func:`resolve_roi_weights_override` 驗證/clamp/正規化）；無覆寫或載入
        失敗一律回退預設 :data:`ROI_BASE_WEIGHTS`（不丟例外）。
        """
        try:
            version = self._rppg_calibration_store.get_active_version()
            override = resolve_roi_weights_override(getattr(version.params, "rppg_params", None))
        except Exception:
            override = None
        return dict(override) if override is not None else dict(ROI_BASE_WEIGHTS)

    def _stop_belt_calibration(self) -> None:
        self._engine_runtime.cancel_timer("belt_tick")
        self._persist_belt_calibration()
        self._belt_calibrator = None
        # P6b-3b：協調層與任何已下發的候選一併清除，避免停止後 worker 仍持續
        # 低頻重算一個不再被追蹤的候選（功能上無害——_on_candidate_bpm_ready
        # 會因 self._rppg_param_coordinator is None 而 no-op——但屬多餘 CPU 成本）。
        self._rppg_param_coordinator = None
        self._clear_candidate_roi_weights()
        # P6b-4：停用錄製並關檔（None 時 dispatch/close 皆為 no-op，行為與現況相同）。
        if self._belt_truth_capture is not None:
            self._dispatch_belt_truth_capture(None)
            writer = self._belt_truth_capture
            self._belt_truth_capture = None
            count = writer.record_count
            writer.close()
            self._append_log(f"■ belt-truth 同步錄製已停止（{count} 筆）→ {writer.path}")
        if self._engine_controller.belt_running:
            self._stop_belt_runtime()
        self._append_log("■ 心跳帶真值校準停止。")

    def _stop_belt_runtime(self) -> bool:
        stopped = self._engine_controller.stop_belt()
        if stopped:
            if self._engine_runtime.timer_active("belt_finalize"):
                self._engine_runtime.cancel_timer("belt_finalize")
        elif not self._engine_runtime.timer_active("belt_finalize"):
            self._engine_runtime.start_periodic_timer("belt_finalize", 50, self._poll_belt_finalization)
        return stopped

    def _poll_belt_finalization(self) -> None:
        if self._stop_belt_runtime():
            self._emit_web_metrics(force=True)
            if self._runtime_shutdown_waiting_for_adapters:
                self._engine_runtime.defer(0, self._shutdown_engine)

    def _persist_belt_calibration(self) -> None:
        """把本次收斂的 offset 存成新的自適應校準版本（信心足夠時）。"""
        cal = self._belt_calibrator
        if cal is None:
            return
        st = cal.state()
        if st.confidence == CONF_LOW or st.accepted_observations < 12:
            self._append_log("○ 心跳帶校準樣本不足或信心低，未存成校準版本。")
            return
        # 使用者裁決 2：carry-forward 現行 active 版本已 adopt 的 rppg_params，避免
        # 同 session 內先 adopt ROI 權重、後停止校準時被本 offset-only 新版本覆蓋遺失。
        # 只在現行 active 版本確實帶 rppg_params 時帶入；沒有就維持只存 offset
        # （OFF 路徑的 active 版本永遠無 rppg_params，故 carried=None、逐位元不變）。
        carried_rppg_params = None
        try:
            active = self._rppg_calibration_store.get_active_version()
            carried_rppg_params = getattr(active.params, "rppg_params", None)
        except Exception:
            carried_rppg_params = None
        try:
            version = self._rppg_calibration_store.save_new_version(
                name=f"自適應校準 {time.strftime('%m-%d %H:%M')}",
                offset_bpm=float(st.offset_bpm),
                rppg_params=carried_rppg_params,
                note=(
                    f"心跳帶真值線上自適應；剩餘殘差 {st.corrected_residual_bpm:+.1f} BPM，"
                    f"信心 {st.confidence}，配對 {st.pairs_used}"
                    + ("；保留已採用的 ROI 權重" if carried_rppg_params else "")
                ),
                session={
                    "source": "hr_belt_adaptive",
                    "pairs_used": int(st.pairs_used),
                    "accepted_observations": int(st.accepted_observations),
                },
                metrics={
                    "offset_bpm": float(st.offset_bpm),
                    "raw_residual_bpm": float(st.raw_residual_bpm),
                    "corrected_residual_bpm": float(st.corrected_residual_bpm),
                    "confidence": st.confidence,
                },
            )
            self._append_log(
                f"✓ 已存自適應校準版本 {version.id}（offset {st.offset_bpm:+.1f} BPM，已設為使用中）"
            )
        except Exception as exc:
            self._append_log(f"⚠ 儲存自適應校準版本失敗：{exc}")

    def _tick_belt_calibration(self) -> None:
        """QTimer 每秒：餵一筆配對觀測給校正器並更新狀態列。"""
        cal = self._belt_calibrator
        st = self._engine_controller.belt_status()
        if cal is not None and st is not None and st.state == "connected" and st.bpm > 0:
            r = self._latest_rppg_metrics
            # 只在 rPPG 產出「新」樣本時餵入：物件相同代表 rPPG 這秒沒更新
            # （凍結或無臉），重複計入會人為放大該筆在殘差中的權重。
            if r is not None and r is not self._last_calib_fed_metrics:
                contact_ok = st.sensor_contact_detected or not st.sensor_contact_supported
                fresh = not hr_is_stale(st)
                cal.observe(time.time(), float(st.bpm), contact_ok, fresh, metrics_to_feed_dict(r))
                self._last_calib_fed_metrics = r
        self._tick_rppg_param_coordinator(cal)

    # ── P6b-3b：rPPG 參數線上協調層（GUI 薄接線）───────────────────────────────

    def _tick_rppg_param_coordinator(self, cal: OnlineBpmCalibrator | None) -> None:
        """OFF（協調層未建立，即 rppg_param_tuning_enabled=False 或未啟動心跳帶
        校準）時立即返回，不動作——維持與現況逐位元相同。ON 時每秒推進一次協調層
        狀態機；產生新候選時下發給 worker。

        已知限制（**待使用者裁決**）：目前未提供逐 ROI 對心跳帶真值的殘差提示
        （``per_roi_residual_hint``），一律傳空字典——見
        :func:`rppg.adaptive_calibration.propose_roi_weight_candidate` 文件字串
        「已知限制」段落。候選**方向**為啟發式（挑目前權重最小者探索），但
        adopt/rollback 仍由心跳帶真值 A/B 決定，護欄未被繞過。
        """
        coord = self._rppg_param_coordinator
        if coord is None or cal is None:
            return
        candidate = coord.tick(time.time(), cal.state(), self._rppg_param_current_weights)
        if candidate is not None:
            self._dispatch_candidate_roi_weights(candidate)
            self._append_log(f"○ rPPG 參數候選已下發，等待心跳帶真值 A/B：{candidate}")

    def _dispatch_candidate_roi_weights(self, weights: dict[str, float] | None) -> None:
        """把候選 ROI 權重（或 None＝清除）下發給目前運行中的 worker。"""
        if self._combined_worker is not None:
            self._combined_worker.set_candidate_roi_weights(weights)
        if self._rppg_worker is not None:
            self._rppg_worker.set_candidate_roi_weights(weights)

    def _clear_candidate_roi_weights(self) -> None:
        self._dispatch_candidate_roi_weights(None)

    def _on_candidate_bpm_ready(self, t_now: float, cur_bpm: float, cand_bpm: float) -> None:
        """接收 worker 低頻重算的 current/candidate raw BPM，餵協調層做 A/B。

        協調層為 None（OFF）時直接返回；心跳帶未連線或 BPM 無效時也不觀測
        （A/B 的真值必須是有效心跳帶讀數）。NaN（重算資料不足）以 ``!= self``
        判斷並跳過本筆，不計入配對。
        """
        coord = self._rppg_param_coordinator
        if coord is None:
            return
        st = self._engine_controller.belt_status()
        if st is None or st.state != "connected" or st.bpm <= 0:
            return
        if cur_bpm != cur_bpm or cand_bpm != cand_bpm:  # NaN 檢查（NaN != NaN）
            return
        verdict = coord.observe_ab(t_now, float(st.bpm), float(cur_bpm), float(cand_bpm))
        if verdict is None:
            return
        if verdict.verdict == "adopt":
            self._adopt_rppg_param_candidate()
        elif verdict.verdict == "rollback":
            self._append_log(
                f"○ rPPG 參數候選未通過心跳帶真值 A/B，已回退（現行殘差 "
                f"{verdict.current_residual_bpm:.1f}，候選殘差 {verdict.candidate_residual_bpm:.1f}）"
            )
            self._clear_candidate_roi_weights()

    def _adopt_rppg_param_candidate(self) -> None:
        """A/B 判 adopt：把候選 ROI 權重與目前 offset 一併存成新校準版本
        （自動設為 active，下次啟動生效），並更新協調層下一輪的「現行」基準。
        """
        coord = self._rppg_param_coordinator
        if coord is None:
            return
        weights = coord.state().adopted_roi_weights
        if not weights:
            self._clear_candidate_roi_weights()
            return
        cal = self._belt_calibrator
        offset = float(cal.state().offset_bpm) if cal is not None else 0.0
        try:
            version = self._rppg_calibration_store.save_new_version(
                name=f"rPPG 參數自適應 {time.strftime('%m-%d %H:%M')}",
                offset_bpm=offset,
                rppg_params={"roi_weights": dict(weights)},
                note="rPPG ROI 權重線上自適應（P6b-3b）：心跳帶真值 A/B 證實優於現行參數。",
            )
            self._rppg_param_current_weights = dict(weights)
            self._append_log(
                f"✓ rPPG 參數候選已採用，存為校準版本 {version.id}（下次啟動生效，已設為使用中）"
            )
        except Exception as exc:
            self._append_log(f"⚠ 儲存 rPPG 參數候選失敗：{exc}")
        self._clear_candidate_roi_weights()

    def _analysis_lifecycle_ports(self) -> AnalysisLifecyclePorts:
        return AnalysisLifecyclePorts(
            stop_all=self._stop_analysis_workers,
            start_combined=lambda: self._start_combined_worker(enable_rppg=True),
            start_rppg=self._start_rppg_worker,
            start_fatigue=self._start_fatigue_worker,
            restore_raw_routing=self._update_frame_routing,
        )

    def _stop_analysis_workers(self) -> None:
        """Stop ALL analysis workers in the correct order."""
        failures = []
        for label, stop in (
            ("combined", self._stop_combined_worker),
            ("rppg", self._stop_rppg_worker),
            ("fatigue", self._stop_fatigue_worker),
        ):
            try:
                if stop() is False:
                    failures.append(f"{label} timeout")
            except Exception as exc:
                failures.append(f"{label}: {exc}")
        if failures:
            raise RuntimeError("Analysis cleanup failed: " + "; ".join(failures))

    # ── Combined worker ───────────────────────────────────────────────────────

    def _start_combined_worker(self, enable_rppg: bool = True) -> None:
        if self._combined_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線。")
            return

        self._combined_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._combined_queue)

        worker = CombinedWorker(
            self._combined_queue,
            enable_rppg=enable_rppg, enable_fatigue=True,
            target_fps=30.0, buffer_sec=12.0,
            calibration_loader=self._load_rppg_calibration_version,
            live_feed_writer=write_live_feed,
            fuser_config=FuserConfig.for_rppg(),
            personal_profile=self._personal_profile,
        )
        self._engine_runtime.start_adapter(
            "combined",
            worker,
            connect=lambda current: (
                current.rppg_metrics_ready.connect(self._on_rppg_metrics),
                current.fatigue_metrics_ready.connect(self._on_fatigue_metrics),
                current.fused_score_ready.connect(self._on_fused_score),
                current.failed.connect(self._on_combined_failed),
                current.candidate_bpm_ready.connect(self._on_candidate_bpm_ready),
            ),
        )

        self._begin_auto_baseline()
        self._update_frame_routing()
        self._append_log("▶ 合併引擎啟動（rPPG + 行為警覺，單 MediaPipe 實例）")

    def _stop_combined_worker(self) -> bool:
        combined_queue = self._combined_queue
        camera_worker = self._cam_worker
        stopped = self._engine_runtime.stop_adapter("combined", 5000)
        if not stopped:
            return False
        self._end_baseline_collection()
        if combined_queue is not None and camera_worker is not None:
            camera_worker.detach_bgr_queue(combined_queue)
        self._combined_queue = None
        self._update_frame_routing()
        return True

    def _on_fused_score(self, score: object) -> None:
        self._latest_fused_score = score
        self._record_metrics()
        self._emit_web_metrics()

    def _on_combined_failed(self, msg: str) -> None:
        self._append_log(f"✗ 合併引擎錯誤：{msg}")
        self._stop_combined_worker()
        self._configure_analysis(
            behavior_enabled=False,
            rppg_enabled=False,
        )
        self._notify_user("引擎錯誤", msg)

    # ── rPPG worker (solo — only when fatigue is OFF) ─────────────────────────

    def _start_rppg_worker(self) -> None:
        if self._rppg_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線再開啟 rPPG。")
            return

        self._bgr_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._bgr_queue)

        worker = RppgWorker(
            self._bgr_queue, target_fps=30.0, buffer_sec=12.0,
            calibration_loader=self._load_rppg_calibration_version,
        )
        self._engine_runtime.start_adapter(
            "rppg",
            worker,
            connect=lambda current: (
                current.metrics_ready.connect(self._on_rppg_metrics),
                current.failed.connect(self._on_rppg_failed),
                current.candidate_bpm_ready.connect(self._on_candidate_bpm_ready),
            ),
        )

        self._update_frame_routing()
        self._append_log("▶ rPPG 引擎啟動（MediaPipe Face Landmarker + POS）")

    def _stop_rppg_worker(self) -> bool:
        bgr_queue = self._bgr_queue
        camera_worker = self._cam_worker
        stopped = self._engine_runtime.stop_adapter("rppg", 4000)
        if not stopped:
            return False
        if bgr_queue is not None and camera_worker is not None:
            camera_worker.detach_bgr_queue(bgr_queue)
        self._bgr_queue = None
        self._update_frame_routing()
        return True

    def _on_stress_toggled(self, checked: bool) -> None:
        analysis = self._engine_controller.analysis_snapshot()
        self._configure_analysis(
            behavior_enabled=analysis.fatigue_enabled,
            rppg_enabled=checked,
        )

    def _load_rppg_calibration_version(self):
        # 背景心跳帶校準運行時，回傳即時微調的 offset 版本，讓 rPPG worker
        # 每幀自動套用最新校正（比對用的是 rPPG 原始 BPM，不會自我回饋）。
        cal = self._belt_calibrator
        if cal is not None:
            return cal.live_version()
        self._rppg_calibration_store.reload()
        return self._rppg_calibration_store.get_active_version()

    def _apply_rppg_calibration(self, metrics: object) -> object:
        if metrics is None:
            return metrics
        version = self._load_rppg_calibration_version()
        return apply_calibration_to_metrics(metrics, version)

    def _on_rppg_metrics(self, metrics: object) -> None:
        if self._combined_worker is None:
            write_live_feed(metrics)  # type: ignore[arg-type]
            metrics = self._apply_rppg_calibration(metrics)
        self._latest_rppg_metrics = metrics
        self._record_metrics()
        self._emit_web_metrics()

    def _on_rppg_failed(self, msg: str) -> None:
        self._append_log(f"✗ rPPG 錯誤：{msg}")
        self._stop_rppg_worker()
        analysis = self._engine_controller.analysis_snapshot()
        self._configure_analysis(
            behavior_enabled=analysis.fatigue_enabled,
            rppg_enabled=False,
        )
        self._notify_user("rPPG 錯誤", msg)

    # ── Fatigue / Behaviour Alertness worker ──────────────────────────────────

    def _start_fatigue_worker(self) -> None:
        if self._fatigue_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線再開啟行為警覺。")
            return

        self._fatigue_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._fatigue_queue)

        worker = FatigueWorker(self._fatigue_queue, target_fps=30.0,
                               personal_profile=self._personal_profile)
        self._engine_runtime.start_adapter(
            "fatigue",
            worker,
            connect=lambda current: (
                current.metrics_ready.connect(self._on_fatigue_metrics),
                current.failed.connect(self._on_fatigue_failed),
            ),
        )

        self._begin_auto_baseline()
        self._update_frame_routing()
        self._append_log("▶ 行為警覺引擎啟動（V2：EAR + 瞳孔 + 注視 + 頭部）")

    def _stop_fatigue_worker(self) -> bool:
        fatigue_queue = self._fatigue_queue
        camera_worker = self._cam_worker
        stopped = self._engine_runtime.stop_adapter("fatigue", 4000)
        if not stopped:
            return False
        self._end_baseline_collection()
        if fatigue_queue is not None and camera_worker is not None:
            camera_worker.detach_bgr_queue(fatigue_queue)
        self._fatigue_queue = None
        self._update_frame_routing()
        return True

    def _on_behavior_toggled(self, checked: bool) -> None:
        analysis = self._engine_controller.analysis_snapshot()
        self._configure_analysis(
            behavior_enabled=checked,
            rppg_enabled=analysis.rppg_enabled,
        )

    def _on_fatigue_metrics(self, metrics: object) -> None:
        self._latest_fatigue_metrics = metrics
        self._engine_runtime.handle_alarm_metrics(metrics)
        self._feed_baseline_collectors(metrics)
        self._record_metrics()
        self._emit_web_metrics()

    # ── 個人清醒基線：自動蒐集 + 手動記錄 + 熱換 ────────────────────────────
    def _active_fatigue_worker(self) -> object | None:
        """回傳目前持有 FatigueEngine、可接受 set_personal_profile 的 worker（或 None）。"""
        if self._combined_worker is not None:
            return self._combined_worker
        if self._fatigue_worker is not None:
            return self._fatigue_worker
        return None

    def _begin_auto_baseline(self) -> None:
        """worker 啟動時開始蒐集暫定清醒基線（前 ~75s）。已有 manual profile 則不覆蓋使用中值，
        但仍蒐集以便必要時觀察；手動記錄永遠優先。"""
        self._auto_baseline_collector = PersonalBaselineCollector(
            window_sec=75.0, now_iso=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if self._personal_profile is None:
            self._set_profile_status("個人基線：自動校準中…")

    def _end_baseline_collection(self) -> None:
        self._auto_baseline_collector = None
        self._manual_baseline_collector = None

    def _feed_baseline_collectors(self, metrics: object) -> None:
        t = time.perf_counter()
        manual = self._manual_baseline_collector
        if manual is not None:
            manual.observe(metrics, t)  # type: ignore[arg-type]
            self._set_profile_status(f"記錄清醒基線中… {manual.progress * 100:.0f}%")
            if manual.is_full():
                self._manual_baseline_collector = None
                self._finalize_manual_baseline(manual)
            return
        auto = self._auto_baseline_collector
        if auto is not None:
            auto.observe(metrics, t)  # type: ignore[arg-type]
            if auto.is_full():
                self._auto_baseline_collector = None
                self._finalize_auto_baseline(auto)

    def _finalize_auto_baseline(self, collector: PersonalBaselineCollector) -> None:
        prof = collector.finalize(source="auto")
        # 自動基線只在「尚無 valid manual profile」時作為本 session 暫定值套用，不落檔。
        # 採用哪個 profile 的裁決唯一交給 resolve_active_baseline（manual 需 valid 才優先）。
        manual = (
            self._personal_profile
            if self._personal_profile is not None and self._personal_profile.source == "manual"
            else None
        )
        resolved = resolve_active_baseline(manual, prof)
        if resolved is manual:
            return
        if resolved is None:
            self._set_profile_status("個人基線：自動校準樣本不足，沿用預設")
            return
        self._hot_swap_profile(resolved)
        self._set_profile_status("個人基線：自動（暫定，未儲存）")
        self._append_log("[基線] 自動清醒基線已建立（本 session 暫定，未落檔）")

    def _finalize_manual_baseline(self, collector: PersonalBaselineCollector) -> None:
        prof = collector.finalize(source="manual")
        if not prof.valid:
            self._set_profile_status("個人基線：樣本不足，請保持臉部在畫面內重試")
            self._append_log("[基線] 手動記錄樣本不足，未儲存")
            return
        self._personal_profile_store.save(prof)
        self._personal_profile = prof
        self._hot_swap_profile(prof)
        self._set_profile_status("個人基線：已記錄並儲存 ✓")
        self._append_log("[基線] 手動清醒基線已記錄、儲存並即時套用，下次開機自動載入")

    def _hot_swap_profile(self, prof: object) -> None:
        worker = self._active_fatigue_worker()
        if worker is not None:
            worker.set_personal_profile(prof)  # type: ignore[attr-defined]

    def _set_profile_status(self, text: str) -> None:
        self._profile_status = str(text)

    def _on_record_baseline_clicked(self) -> None:
        if self._active_fatigue_worker() is None:
            self._set_profile_status("個人基線：請先按「開始」啟動偵測")
            return
        self._manual_baseline_collector = PersonalBaselineCollector(
            window_sec=60.0, now_iso=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._set_profile_status("記錄清醒基線中… 0%")
        self._append_log("[基線] 開始手動記錄清醒基線（約 60 秒，請保持清醒自然狀態）")

    def _on_fatigue_failed(self, msg: str) -> None:
        self._append_log(f"✗ 行為警覺錯誤：{msg}")
        self._stop_fatigue_worker()
        analysis = self._engine_controller.analysis_snapshot()
        self._configure_analysis(
            behavior_enabled=False,
            rppg_enabled=analysis.rppg_enabled,
        )
        self._notify_user("行為警覺錯誤", msg)

    def _on_camera_info(self, codec: str, w: int, h: int, fps: float) -> None:
        """Called after camera opens — shows backend-reported negotiated settings."""
        fps_str = f"{fps:.0f}" if fps > 0 else "—"
        self._last_camera_info = {"codec": codec, "width": w, "height": h}
        self._append_log(
            f"[相機] 後端回報格式 → 編碼：{codec}  解析度：{w}×{h}  FPS：{fps_str}"
        )
        self._emit_web_metrics(force=True)

    def _on_frame(self, image) -> None:
        self._emit_web_frame(image)

    def _on_record_frame(self, image) -> None:
        if self._video_queue is None:
            return
        try:
            self._video_queue.put_nowait((time.perf_counter(), image))
        except queue.Full:
            pass

    def _on_fps(self, fps: float) -> None:
        self._last_fps = float(fps)
        self._fps_measurement_samples += 1
        requested_fps = float(self._engine_controller.camera_snapshot().fps)
        if (
            not self._camera_fps_warning_sent
            and self._fps_measurement_samples >= 15
            and fps > 0
            and fps + 1.0 < requested_fps
        ):
            self._camera_fps_warning_sent = True
            self._append_log(
                f"⚠ 相機要求 {requested_fps:.0f} FPS，但目前實測約 {fps:.1f} FPS；"
                "請用 scripts/diagnose_camera.py 確認相機格式與系統負載。"
            )
        self._emit_web_metrics()

    def _on_camera_failed(self, msg: str) -> None:
        self._append_log(f"✗ 相機錯誤：{msg}")
        self._cancel_pending_auto_capture_timer()
        self._rollback_auto_capture_toggles()
        if self._belt_calibrator is not None:
            self._stop_belt_calibration()
        self._stop_analysis_workers()
        if (
            self._recording
            or self._metrics_recorder is not None
            or self._video_worker is not None
        ):
            self._recording = False
            self._stop_recording()
            self._append_log("○ 相機中斷，已一併結束記錄。")
        self._set_record_source(None)
        self._set_frame_source(None)
        camera_stopped = self._engine_runtime.stop_adapter("camera", 3000)
        self._pipeline_running = False
        if camera_stopped:
            self._engine_controller.stop_pipeline()
        else:
            self._engine_controller.mark_pipeline_cleanup_pending()
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        self._last_fps = 0.0
        self._last_camera_info = {"codec": "", "width": 0, "height": 0}
        self._emit_web_metrics(force=True)
        self._publish_desktop_notice(f"攝影機錯誤：{msg}")

    # ── Pipeline toggle ───────────────────────────────────────────────────────

    def _toggle_pipeline(self) -> None:
        pipeline_running = self._engine_controller.pipeline_snapshot().running
        if not pipeline_running:
            if self._engine_runtime.worker("camera_scan") is not None:
                self._publish_desktop_notice("正在搜尋攝影機，請稍候再啟動監測。")
                return
            self._latest_rppg_metrics = None
            self._latest_fatigue_metrics = None
            self._latest_fused_score = None
            try:
                self._engine_controller.start_pipeline()
            except (ValueError, RuntimeError):
                self._pipeline_running = False
                self._engine_controller.stop_pipeline()
                self._emit_web_metrics(force=True)
                return
            self._pipeline_running = True
            try:
                self._start_camera_worker()
                self._engine_controller.activate_current_analysis(
                    self._analysis_lifecycle_ports()
                )
            except Exception as exc:
                logger.exception("管線 adapter 啟動失敗")
                try:
                    self._stop_camera_worker()
                except Exception as cleanup_exc:
                    logger.warning("管線啟動失敗後清理資源失敗：%s", cleanup_exc)
                self._engine_controller.stop_pipeline()
                self._pipeline_running = False
                self._notify_user("管線", f"無法啟動分析管線：{exc}")
                self._emit_web_metrics(force=True)
                return
            self._ensure_belt_calibration()   # rPPG 運行時視勾選啟動背景校準
            if self._capture_preferences.snapshot().auto_record and not self._recording:
                self._toggle_recording()
            self._emit_web_metrics(force=True)
        else:
            self._engine_controller.stop_pipeline()
            self._pipeline_running = False
            self._cancel_pending_auto_capture_timer()
            self._rollback_auto_capture_toggles()
            self._latest_rppg_metrics = None
            self._latest_fatigue_metrics = None
            self._latest_fused_score = None
            self._last_fps = 0.0
            self._last_camera_info = {"codec": "", "width": 0, "height": 0}
            if self._belt_calibrator is not None:
                self._stop_belt_calibration()   # 停止前先存本次 session 校準版本
            self._stop_camera_worker()
            self._append_log("■ 管線停止。")
            if self._recording:
                self._recording = False
                self._stop_recording()
                self._append_log("○ 管線停止，已一併結束記錄。")
            self._emit_web_metrics(force=True)

    def _toggle_recording(self) -> None:
        pipeline = self._engine_controller.pipeline_snapshot()
        if not pipeline.running and not pipeline.recording:
            self._notify_user("記錄", "請先啟動管線再開始記錄（示範規則）。", level="info")
            return
        if not pipeline.recording:
            try:
                self._engine_controller.start_recording()
                self._recording = True
                self._start_recording()
            except Exception as exc:
                self._recording = False
                self._engine_controller.stop_recording()
                try:
                    self._stop_recording()
                except Exception as cleanup_exc:
                    logger.warning("記錄啟動失敗後清理資源失敗：%s", cleanup_exc)
                self._notify_user("記錄", f"無法啟動記錄：{exc}")
                return
            if self._recording_db_path is not None:
                self._append_log(f"● 記錄開始 → {self._recording_db_path}")
            else:
                self._append_log("● 記錄開始 → recordings/")
            self._emit_web_metrics(force=True)
        else:
            self._recording = False
            self._engine_controller.stop_recording()
            self._cancel_pending_auto_capture_timer()
            self._rollback_auto_capture_toggles()
            self._stop_recording()
            self._append_log("○ 記錄停止。")
            self._emit_web_metrics(force=True)

    def _cancel_pending_auto_capture_timer(self) -> None:
        """停止自動採集倒數，避免後續誤停不相關的新錄製。"""
        self._engine_runtime.cancel_timer("auto_capture")

    def _rollback_auto_capture_toggles(self) -> None:
        """回滾本次自動採集自己強制勾選的核取方塊，且只在目前仍是勾選狀態才動，
        避免覆蓋使用者在期間手動做的操作。"""
        if (
            self._auto_capture_started_belt_calib
            and self._capture_preferences.snapshot().belt_calibration
        ):
            self._configure_capture_preferences(
                mark_dirty=False,
                belt_calibration=False,
            )
        self._auto_capture_started_belt_calib = False
        analysis = self._engine_controller.analysis_snapshot()
        if self._auto_capture_started_stress and analysis.rppg_enabled:
            self._configure_analysis(
                behavior_enabled=analysis.fatigue_enabled,
                rppg_enabled=False,
            )
        self._auto_capture_started_stress = False

    def _on_auto_capture_clicked(self) -> None:
        """一鍵自動採集：只串接既有偏好入口、_toggle_pipeline 與 _toggle_recording，
        不重寫任何 worker 啟停、記錄或心跳帶校準邏輯本身。"""
        if self._engine_runtime.timer_active("auto_capture"):
            # 倒數中再按一次 → 提前停止。
            self._append_log("■ 自動採集：使用者提前按下停止。")
            self._finish_auto_capture(early=True)
            return

        if self._engine_runtime.worker("camera_scan") is not None:
            self._publish_desktop_notice("正在搜尋攝影機，請稍候再啟動採集。")
            return

        capture = self._capture_preferences.snapshot()
        include_belt = capture.auto_capture_include_belt
        self._auto_capture_started_belt_calib = False
        self._auto_capture_started_stress = False
        self._auto_capture_started_recording = False
        if include_belt:
            analysis = self._engine_controller.analysis_snapshot()
            if not analysis.rppg_enabled:
                self._configure_analysis(
                    behavior_enabled=analysis.fatigue_enabled,
                    rppg_enabled=True,
                )
                self._auto_capture_started_stress = True
            if not self._capture_preferences.snapshot().belt_calibration:
                self._configure_capture_preferences(
                    mark_dirty=False,
                    belt_calibration=True,
                )
                self._auto_capture_started_belt_calib = (
                    self._capture_preferences.snapshot().belt_calibration
                )

        pipeline_started_by_this_call = False
        if not self._engine_controller.pipeline_snapshot().running:
            self._toggle_pipeline()
            if not self._engine_controller.pipeline_snapshot().running:
                message = "自動採集：管線未能啟動，已中止（請先選擇攝影機）。"
                self._append_log(f"⚠ {message}")
                self._notify_user("自動採集", message)
                self._rollback_auto_capture_toggles()
                return
            pipeline_started_by_this_call = True

        if not self._engine_controller.pipeline_snapshot().recording:
            self._toggle_recording()
            if not self._engine_controller.pipeline_snapshot().recording:
                self._append_log("⚠ 自動採集：記錄未能啟動，已中止。")
                self._rollback_auto_capture_toggles()
                if pipeline_started_by_this_call:
                    # 設計取捨：這裡不對稱關閉管線，保留運作中狀態讓使用者自行決定
                    # 是否繼續（不強制連帶停掉一個可能還有用的管線）。
                    self._append_log("　（本次自動採集啟動的管線維持運作中，未一併關閉。）")
                return
            # 這段記錄是自動採集自己啟動的，收尾時才由自動採集負責停止；若記錄
            # 在按下按鈕前已在跑（下方 if 不成立），維持 False，沿用不停止。
            self._auto_capture_started_recording = True

        self._auto_capture_belt_path = (
            self._belt_truth_capture.path if self._belt_truth_capture is not None else None
        )
        self._auto_capture_expected_db_path = self._recording_db_path

        duration_s = self._capture_preferences.snapshot().auto_capture_seconds
        self._append_log(
            f"▶ 自動採集開始（{duration_s}s，{'含心跳帶' if include_belt else '僅記錄'}）"
        )
        self._engine_runtime.schedule_timer(
            "auto_capture",
            duration_s * 1000,
            lambda: self._finish_auto_capture(early=False),
        )

    def _finish_auto_capture(self, early: bool) -> None:
        """自動採集收尾：只呼叫既有停止觸發點，belt-truth capture writer 的關閉交給
        既有 `_stop_belt_calibration`（經由 capture preference 回滾觸發）自行處理。
        停止記錄需同時滿足兩個條件才會呼叫 _toggle_recording()：
        (1) `_auto_capture_started_recording` 為 True——這段記錄是本次自動採集自己
            啟動的，而非使用者按下「自動採集」前就已手動開始、自動採集只是沿用；
        (2) session token（`_auto_capture_expected_db_path`）仍與目前 `_recording_db_path`
            相符——避免使用者在倒數期間另行結束/替換掉這段錄製後被誤停。
        任一條件不成立都跳過停止，避免誤停一段與本次自動採集無關的錄製。"""
        self._cancel_pending_auto_capture_timer()

        # 讀 belt-truth writer 的即時路徑（若倒數期間使用者手動取消再重新勾選過
        # 心跳帶校準，_belt_truth_capture 會是新建的 writer，路徑與啟動當下快照的
        # _auto_capture_belt_path 不同）。必須在下面任何可能經由 unchecked
        # belt calibration preference 觸發 _stop_belt_calibration（把 _belt_truth_capture 設回
        # None）的動作——包含 _toggle_recording() 內部現在也會呼叫
        # _rollback_auto_capture_toggles()——發生之前先讀取，否則會讀到 None。
        live_belt_path = (
            self._belt_truth_capture.path if self._belt_truth_capture is not None else None
        )

        expected_db_path = self._auto_capture_expected_db_path
        self._auto_capture_expected_db_path = None
        db_path = expected_db_path
        started_recording = self._auto_capture_started_recording
        self._auto_capture_started_recording = False
        if (
            started_recording
            and self._engine_controller.pipeline_snapshot().recording
            and self._recording_db_path == expected_db_path
        ):
            self._toggle_recording()
        elif not started_recording:
            self._append_log("⚠ 自動採集：錄製非本次自動採集啟動，自動採集跳過停止。")
        else:
            self._append_log(
                "⚠ 自動採集：錄製已被其他操作結束或替換，自動採集跳過停止（未變更目前錄製狀態）。"
            )

        self._rollback_auto_capture_toggles()

        belt_path = live_belt_path if live_belt_path is not None else self._auto_capture_belt_path
        self._auto_capture_belt_path = None

        lines = [f"自動採集{'（提前停止）' if early else '（時間到）'}已完成。"]
        if db_path is not None:
            lines.append(f"metrics 記錄 → {db_path}")
        else:
            lines.append("metrics 記錄：未取得路徑（記錄可能未成功啟動）。")
        if belt_path is not None:
            lines.append(f"心跳帶 belt-truth capture → {belt_path}")
        self._append_log("● " + "  ".join(lines))
        self._notify_user("自動採集完成", "\n".join(lines), level="info")

    @property
    def selected_camera_index(self) -> int | None:
        """OpenCV device index owned by the headless engine controller."""
        return self._engine_controller.camera_snapshot().selected_index

    def _on_save_layout(self) -> None:
        path = self._save_settings()
        self._append_log(f"💾 已保存配置與布局 → {path}")

    def _web_dashboard_url_labels(self) -> list[tuple[str, str]]:
        """回傳 (顯示標籤, 網址) 清單。"""
        labels: list[tuple[str, str]] = []
        for url in self._web_dashboard_urls():
            if url.startswith("http://127.0.0.1"):
                labels.append((f"本機 — {url}", url))
            else:
                labels.append((f"區域網 — {url}", url))
        return labels

    def _pick_web_dashboard_url(self) -> str | None:
        options = self._web_dashboard_url_labels()
        if not options:
            return None
        return options[0][1]

    def _on_web_info(self) -> str:
        """Ensure the diagnostics server is ready and return its URL.

        Opening the URL belongs to the Tauri shell; the engine only supplies
        the validated dashboard endpoint to the desktop command response.
        """
        if self._web_server is None:
            self._start_web_server()
        if self._web_server is None:
            raise RuntimeError("Web dashboard failed to start")
        url_str = self._pick_web_dashboard_url()
        if url_str is None:
            raise RuntimeError("Web dashboard URL is unavailable")
        return url_str
