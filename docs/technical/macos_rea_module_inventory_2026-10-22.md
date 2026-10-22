# 模組、符號與資料契約清冊

日期：2026-10-22。對應 [macOS REA 審核與決策](macos_rea_audit_2026-10-22.md)。

本清冊由 Python AST 與其他語言宣告擷取，包含私有方法，供逐項追查；不執行模組、不讀取 .env，不等同分支覆蓋率或執行時呼叫圖。來源為權威，之後改碼應重新核對行號與預設值。

## 1. Python 模組與函式介面

### `gui/__init__.py`

[原始碼](../../gui/__init__.py)；10 行。Headless PySide6 runtime adapters for the desktop engine.

本地直接依賴：`gui.main_window`。

- [L5](../../gui/__init__.py#L5) `__getattr__(name: str)`

### `gui/alarm_config.py`

[原始碼](../../gui/alarm_config.py)；172 行。疲勞警報器設定資料結構與預設音效路徑。

本地直接依賴：`gui.runtime_paths`。

- [L49](../../gui/alarm_config.py#L49) `project_root() -> Path`
- [L53](../../gui/alarm_config.py#L53) `default_alerts_dir() -> Path`
- [L57](../../gui/alarm_config.py#L57) `default_sound_path(scenario: str) -> str`
- 類別 [AlarmScenarioConfig](../../gui/alarm_config.py#L63)
- [L67](../../gui/alarm_config.py#L67) `AlarmScenarioConfig.to_dict(self) -> dict[str, Any]`
- [L74](../../gui/alarm_config.py#L74) `AlarmScenarioConfig.from_dict(cls, data: dict[str, Any] | None, *, scenario: str) -> AlarmScenarioConfig`
- [L87](../../gui/alarm_config.py#L87) `default_scenario_config(scenario: str) -> AlarmScenarioConfig`
- 類別 [AlarmConfig](../../gui/alarm_config.py#L95)
- [L104](../../gui/alarm_config.py#L104) `AlarmConfig.__post_init__(self) -> None`
- [L112](../../gui/alarm_config.py#L112) `AlarmConfig.defaults(cls) -> AlarmConfig`
- [L120](../../gui/alarm_config.py#L120) `AlarmConfig.to_dict(self) -> dict[str, Any]`
- [L136](../../gui/alarm_config.py#L136) `AlarmConfig.from_dict(cls, data: dict[str, Any] | None) -> AlarmConfig`
- [L171](../../gui/alarm_config.py#L171) `AlarmConfig.scenario_for_status(self, status: str) -> str | None`

### `gui/alarm_player.py`

[原始碼](../../gui/alarm_player.py)；267 行。疲勞警報播放與觸發狀態機。

本地直接依賴：`gui.alarm_config`。

- 類別 [AlarmPlaybackBackend](../../gui/alarm_player.py#L39)
- [L40](../../gui/alarm_player.py#L40) `AlarmPlaybackBackend.play_file(self, path: str, *, volume: float) -> bool`
- [L43](../../gui/alarm_player.py#L43) `AlarmPlaybackBackend.play_builtin(self, scenario: str) -> None`
- [L46](../../gui/alarm_player.py#L46) `AlarmPlaybackBackend.close(self) -> None`
- 類別 [AlarmTriggerState](../../gui/alarm_player.py#L51)
- [L59](../../gui/alarm_player.py#L59) `decide_alarm_trigger(*, config: AlarmConfig, state: AlarmTriggerState, status: str, calibrated: bool, now: float) -> str | None`
- [L118](../../gui/alarm_player.py#L118) `mark_alarm_played(state: AlarmTriggerState, scenario: str, *, now: float) -> None`
- 類別 [QtAlarmPlaybackBackend](../../gui/alarm_player.py#L124)
- [L127](../../gui/alarm_player.py#L127) `QtAlarmPlaybackBackend.__init__(self, parent: QObject | None=None) -> None`
- [L133](../../gui/alarm_player.py#L133) `QtAlarmPlaybackBackend.play_file(self, path: str, *, volume: float) -> bool`
- [L142](../../gui/alarm_player.py#L142) `QtAlarmPlaybackBackend.play_builtin(self, scenario: str) -> None`
- [L169](../../gui/alarm_player.py#L169) `QtAlarmPlaybackBackend.close(self) -> None`
- 類別 [FatigueAlarmController](../../gui/alarm_player.py#L173)
- [L176](../../gui/alarm_player.py#L176) `FatigueAlarmController.__init__(self, config: AlarmConfig, parent: QObject | None=None, *, playback: AlarmPlaybackBackend | None=None, monotonic: Callable[[], float] | None=None) -> None`
- [L191](../../gui/alarm_player.py#L191) `FatigueAlarmController.config(self) -> AlarmConfig`
- [L194](../../gui/alarm_player.py#L194) `FatigueAlarmController.set_config(self, config: AlarmConfig) -> None`
- [L198](../../gui/alarm_player.py#L198) `FatigueAlarmController.reset_state(self) -> None`
- [L201](../../gui/alarm_player.py#L201) `FatigueAlarmController.on_metrics(self, metrics: Any) -> None`
- [L230](../../gui/alarm_player.py#L230) `FatigueAlarmController.preview_scenario(self, scenario: str, *, config: AlarmConfig | None=None) -> str | None`
- [L240](../../gui/alarm_player.py#L240) `FatigueAlarmController._play_scenario(self, scenario: str, scenario_cfg: AlarmScenarioConfig, *, config: AlarmConfig | None=None) -> str | None`
- [L261](../../gui/alarm_player.py#L261) `FatigueAlarmController.close(self) -> None`

### `gui/belt_runtime.py`

[原始碼](../../gui/belt_runtime.py)；90 行。Background BLE heart-rate belt runtime for rPPG truth calibration.

本地直接依賴：`rppg.belt_truth_capture`, `rppg.calibration_watch`, `rppg.hr_belt_ble`。

- 類別 [BeltRuntime](../../gui/belt_runtime.py#L21)
- [L28](../../gui/belt_runtime.py#L28) `BeltRuntime.__init__(self) -> None`
- [L33](../../gui/belt_runtime.py#L33) `BeltRuntime.belt_running(self) -> bool`
- [L36](../../gui/belt_runtime.py#L36) `BeltRuntime.start_belt(self, config: HrBeltConfig | None=None) -> str`
- [L56](../../gui/belt_runtime.py#L56) `BeltRuntime.stop_belt(self) -> None`
- [L64](../../gui/belt_runtime.py#L64) `BeltRuntime.belt_status(self) -> HrBeltStatus | None`
- [L69](../../gui/belt_runtime.py#L69) `BeltRuntime.create_truth_capture_writer(self, path: str | Path | None=None) -> BeltTruthCaptureWriter`

### `gui/camera_devices.py`

[原始碼](../../gui/camera_devices.py)；365 行。Enumerate cameras across Windows, macOS, and Linux backends.

本地直接依賴：`gui.platforms`。

- [L35](../../gui/camera_devices.py#L35) `_list_windows_dshow_device_names() -> list[str]`
- [L48](../../gui/camera_devices.py#L48) `_list_linux_v4l2_device_names() -> dict[int, str]`
- [L72](../../gui/camera_devices.py#L72) `_list_linux_video_indices() -> list[int]`
- [L91](../../gui/camera_devices.py#L91) `_is_linux_video_capture_node(path: str) -> bool`
- [L127](../../gui/camera_devices.py#L127) `_build_api_preferences(api_preferences: Sequence[int] | None) -> list[int]`
- [L140](../../gui/camera_devices.py#L140) `_selected_platform_name() -> str`
- [L151](../../gui/camera_devices.py#L151) `_probe_camera_index(index: int, warmup_read: bool, api_preferences: Sequence[int]) -> bool`
- [L174](../../gui/camera_devices.py#L174) `list_camera_devices(*, max_index: int=20, warmup_read: bool=True) -> list[tuple[int, str]]`
- [L211](../../gui/camera_devices.py#L211) `_apply_msmf_io_timeouts(cap: Optional[Any]) -> None`
- [L236](../../gui/camera_devices.py#L236) `open_camera_capture(index: int, backend: str='auto')`
- [L335](../../gui/camera_devices.py#L335) `configure_camera_capture(cap: Any, *, width: int, height: int, target_fps: float, prefer_mjpg: bool=True, apply_format: bool=True) -> None`

### `gui/camera_stream_worker.py`

[原始碼](../../gui/camera_stream_worker.py)；289 行。Background camera capture for overlay preview (OpenCV only; no MediaPipe).

本地直接依賴：`gui.camera_devices`, `gui.frame_queue`。

- 類別 [CameraStreamWorker](../../gui/camera_stream_worker.py#L35)
- [L56](../../gui/camera_stream_worker.py#L56) `CameraStreamWorker.__init__(self, camera_index: int, width: int=1280, height: int=720, target_fps: int=30, backend: str='ffmpeg', horizontal_flip: bool=False) -> None`
- [L75](../../gui/camera_stream_worker.py#L75) `CameraStreamWorker.attach_bgr_queue(self, q: 'queue.Queue[tuple[float, np.ndarray]]') -> None`
- [L81](../../gui/camera_stream_worker.py#L81) `CameraStreamWorker.detach_bgr_queue(self, q: 'Optional[queue.Queue]'=None) -> None`
- [L88](../../gui/camera_stream_worker.py#L88) `CameraStreamWorker.request_stop(self) -> None`
- [L92](../../gui/camera_stream_worker.py#L92) `CameraStreamWorker._fourcc_to_str(raw: int) -> str`
- [L97](../../gui/camera_stream_worker.py#L97) `CameraStreamWorker._read_cap_info(self, cap) -> tuple[str, int, int, float]`
- [L105](../../gui/camera_stream_worker.py#L105) `CameraStreamWorker._frame_stats(frame: np.ndarray) -> tuple[float, float]`
- [L113](../../gui/camera_stream_worker.py#L113) `CameraStreamWorker._is_diagnostic_black_frame(self, frame: np.ndarray) -> bool`
- [L117](../../gui/camera_stream_worker.py#L117) `CameraStreamWorker._format_capture_context(self, codec: str, width: int, height: int, fps: float) -> str`
- [L125](../../gui/camera_stream_worker.py#L125) `CameraStreamWorker.run(self) -> None`

### `gui/capture_preferences_state.py`

[原始碼](../../gui/capture_preferences_state.py)；99 行。套件／工具入口

- 類別 [CapturePreferencesSnapshot](../../gui/capture_preferences_state.py#L11)
- 類別 [CapturePreferencesState](../../gui/capture_preferences_state.py#L18)
- [L21](../../gui/capture_preferences_state.py#L21) `CapturePreferencesState.__init__(self) -> None`
- [L24](../../gui/capture_preferences_state.py#L24) `CapturePreferencesState.snapshot(self) -> CapturePreferencesSnapshot`
- [L27](../../gui/capture_preferences_state.py#L27) `CapturePreferencesState.restore(self, snapshot: CapturePreferencesSnapshot) -> CapturePreferencesSnapshot`
- [L35](../../gui/capture_preferences_state.py#L35) `CapturePreferencesState.configure(self, *, auto_record: object=_UNSET, belt_calibration: object=_UNSET, auto_capture_seconds: object=_UNSET, auto_capture_include_belt: object=_UNSET) -> CapturePreferencesSnapshot`
- [L63](../../gui/capture_preferences_state.py#L63) `CapturePreferencesState.load(self, *, toggles: object) -> CapturePreferencesSnapshot`
- [L77](../../gui/capture_preferences_state.py#L77) `CapturePreferencesState.reset_persisted(self) -> CapturePreferencesSnapshot`
- [L85](../../gui/capture_preferences_state.py#L85) `CapturePreferencesState.to_desktop_state(self) -> dict[str, object]`
- [L94](../../gui/capture_preferences_state.py#L94) `CapturePreferencesState.to_settings_toggles(self) -> dict[str, bool]`

### `gui/combined_worker.py`

[原始碼](../../gui/combined_worker.py)；466 行。Combined Face Worker — single MediaPipe instance drives both rPPG and Fatigue.

本地直接依賴：`gui.fatigue_engine`, `gui.fatigue_scorer`, `gui.fatigue_worker`, `gui.frame_queue`, `gui.mediapipe_tuning`, `gui.personal_profile`, `gui.platforms`, `gui.worker_safety`, `rppg.adaptive_calibration`, `rppg.belt_truth_capture`, `rppg.calibration`, `rppg.rppg_worker`。

- 類別 [CombinedWorker](../../gui/combined_worker.py#L63)
- [L109](../../gui/combined_worker.py#L109) `CombinedWorker.__init__(self, frame_queue: 'queue.Queue[tuple[float, np.ndarray]]', enable_rppg: bool=True, enable_fatigue: bool=True, target_fps: float=30.0, buffer_sec: float=12.0, fatigue_params: Optional[FatigueParams]=None, calibration_loader: Optional[Callable[[], object]]=None, live_feed_writer: Optional[Callable[[RppgMetrics], None]]=None, fuser_config: Optional[FuserConfig]=None, personal_profile: Optional[PersonalProfile]=None) -> None`
- [L149](../../gui/combined_worker.py#L149) `CombinedWorker.request_stop(self) -> None`
- [L152](../../gui/combined_worker.py#L152) `CombinedWorker.set_roi_base_weights_override(self, weights: Optional[dict[str, float]]) -> None`
- [L158](../../gui/combined_worker.py#L158) `CombinedWorker.set_candidate_roi_weights(self, weights: Optional[dict[str, float]]) -> None`
- [L167](../../gui/combined_worker.py#L167) `CombinedWorker.set_belt_truth_capture(self, writer: Optional[BeltTruthCaptureWriter]) -> None`
- [L176](../../gui/combined_worker.py#L176) `CombinedWorker._maybe_capture_belt_truth(self, ts: float, per_roi_means: dict[str, tuple[float, float, float]]) -> None`
- [L188](../../gui/combined_worker.py#L188) `CombinedWorker._maybe_emit_candidate_bpm(self, rppg_engine: Optional['RppgEngine'], rppg_tuning, t_now: float) -> None`
- [L222](../../gui/combined_worker.py#L222) `CombinedWorker.set_personal_profile(self, profile: Optional[PersonalProfile]) -> None`
- [L229](../../gui/combined_worker.py#L229) `CombinedWorker.run(self) -> None`
- [L449](../../gui/combined_worker.py#L449) `CombinedWorker._emit_status(self, fm: Optional[FatigueMetrics], rm: Optional['RppgMetrics']) -> None`

### `gui/desktop_control.py`

[原始碼](../../gui/desktop_control.py)；124 行。Thread-safe command handoff from Flask workers to the Qt GUI thread.

- 類別 [DesktopControlError](../../gui/desktop_control.py#L15)
- [L18](../../gui/desktop_control.py#L18) `DesktopControlError.__init__(self, code: str, message: str, *, status_code: int, field: str | None=None, path: str | None=None) -> None`
- [L33](../../gui/desktop_control.py#L33) `DesktopControlError.to_payload(self) -> dict[str, str]`
- 類別 [BusyError](../../gui/desktop_control.py#L42)
- [L43](../../gui/desktop_control.py#L43) `BusyError.__init__(self, message: str) -> None`
- 類別 [SettingsWriteError](../../gui/desktop_control.py#L47)
- [L48](../../gui/desktop_control.py#L48) `SettingsWriteError.__init__(self, message: str, *, path: str) -> None`
- 類別 [AlarmUnplayableError](../../gui/desktop_control.py#L57)
- [L58](../../gui/desktop_control.py#L58) `AlarmUnplayableError.__init__(self, message: str) -> None`
- 類別 [HotkeyApplyError](../../gui/desktop_control.py#L62)
- [L63](../../gui/desktop_control.py#L63) `HotkeyApplyError.__init__(self, message: str) -> None`
- [L67](../../gui/desktop_control.py#L67) `desktop_dialog_parent(window: Any, *, engine_mode: bool) -> Any | None`
- 類別 [_PendingCommand](../../gui/desktop_control.py#L75)
- 類別 [DesktopCommandBroker](../../gui/desktop_control.py#L84)
- [L87](../../gui/desktop_control.py#L87) `DesktopCommandBroker.__init__(self, *, timeout_seconds: float=10.0) -> None`
- [L92](../../gui/desktop_control.py#L92) `DesktopCommandBroker.pending_count(self) -> int`
- [L95](../../gui/desktop_control.py#L95) `DesktopCommandBroker.submit(self, name: str, args: dict[str, Any] | None=None) -> dict[str, Any]`
- [L105](../../gui/desktop_control.py#L105) `DesktopCommandBroker.process_pending(self, handler: ControlHandler, *, max_items: int=16) -> int`

### `gui/desktop_models.py`

[原始碼](../../gui/desktop_models.py)；22 行。Qt-free data models shared by the desktop engine and Flutter control API.

- 類別 [HotkeyConfig](../../gui/desktop_models.py#L9)
- 類別 [UserProfile](../../gui/desktop_models.py#L19)

### `gui/desktop_settings_contract.py`

[原始碼](../../gui/desktop_settings_contract.py)；141 行。Qt-free desktop settings command validation.

本地直接依賴：`gui.alarm_config`。

- [L31](../../gui/desktop_settings_contract.py#L31) `parse_user_profile(args: dict[str, Any]) -> tuple[int, int, float]`
- [L59](../../gui/desktop_settings_contract.py#L59) `parse_alarm_config(args: dict[str, Any]) -> AlarmConfig`
- [L131](../../gui/desktop_settings_contract.py#L131) `parse_settings_reset_sections(args: dict[str, Any]) -> list[str]`

### `gui/engine_controller.py`

[原始碼](../../gui/engine_controller.py)；401 行。Headless ownership for engine configuration and runtime inputs.

本地直接依賴：`rppg.belt_truth_capture`, `rppg.calibration_watch`, `rppg.hr_belt_ble`。

- 類別 [BeltRuntimePort](../../gui/engine_controller.py#L35)
- [L39](../../gui/engine_controller.py#L39) `BeltRuntimePort.belt_running(self) -> bool`
- [L42](../../gui/engine_controller.py#L42) `BeltRuntimePort.start_belt(self, config: HrBeltConfig | None=None) -> str`
- [L45](../../gui/engine_controller.py#L45) `BeltRuntimePort.stop_belt(self) -> None`
- [L48](../../gui/engine_controller.py#L48) `BeltRuntimePort.belt_status(self) -> HrBeltStatus | None`
- [L51](../../gui/engine_controller.py#L51) `BeltRuntimePort.create_truth_capture_writer(self, path: str | Path | None=None) -> BeltTruthCaptureWriter`
- 類別 [CameraDevice](../../gui/engine_controller.py#L58)
- 類別 [CameraConfig](../../gui/engine_controller.py#L64)
- 類別 [CameraStartSpec](../../gui/engine_controller.py#L74)
- 類別 [AnalysisPlan](../../gui/engine_controller.py#L85)
- 類別 [PipelineSnapshot](../../gui/engine_controller.py#L94)
- 類別 [AnalysisLifecyclePorts](../../gui/engine_controller.py#L104)
- 類別 [ReplayLifecycleSnapshot](../../gui/engine_controller.py#L115)
- 類別 [EngineController](../../gui/engine_controller.py#L121)
- [L124](../../gui/engine_controller.py#L124) `EngineController.__init__(self, *, belt_runtime: BeltRuntimePort | None=None) -> None`
- [L133](../../gui/engine_controller.py#L133) `EngineController.belt_runtime(self) -> BeltRuntimePort`
- [L139](../../gui/engine_controller.py#L139) `EngineController.belt_running(self) -> bool`
- [L142](../../gui/engine_controller.py#L142) `EngineController.start_belt(self, config: HrBeltConfig | None=None) -> str`
- [L145](../../gui/engine_controller.py#L145) `EngineController.stop_belt(self) -> None`
- [L149](../../gui/engine_controller.py#L149) `EngineController.belt_status(self) -> HrBeltStatus | None`
- [L152](../../gui/engine_controller.py#L152) `EngineController.clear_belt_samples(self) -> None`
- [L155](../../gui/engine_controller.py#L155) `EngineController.belt_samples(self) -> list[Any]`
- [L158](../../gui/engine_controller.py#L158) `EngineController.create_belt_truth_capture_writer(self, path: str | Path | None=None) -> BeltTruthCaptureWriter`
- [L164](../../gui/engine_controller.py#L164) `EngineController.analysis_plan(*, rppg_enabled: bool, fatigue_enabled: bool) -> AnalysisPlan`
- [L180](../../gui/engine_controller.py#L180) `EngineController.pipeline_snapshot(self) -> PipelineSnapshot`
- [L183](../../gui/engine_controller.py#L183) `EngineController.analysis_snapshot(self) -> AnalysisPlan`
- [L186](../../gui/engine_controller.py#L186) `EngineController.start_pipeline(self) -> AnalysisPlan`
- [L196](../../gui/engine_controller.py#L196) `EngineController.stop_pipeline(self) -> None`
- [L199](../../gui/engine_controller.py#L199) `EngineController.mark_pipeline_cleanup_pending(self) -> None`
- [L202](../../gui/engine_controller.py#L202) `EngineController.finish_pipeline_cleanup(self) -> None`
- [L205](../../gui/engine_controller.py#L205) `EngineController.start_recording(self) -> None`
- [L210](../../gui/engine_controller.py#L210) `EngineController.stop_recording(self) -> None`
- [L214](../../gui/engine_controller.py#L214) `EngineController.replay_snapshot(self) -> ReplayLifecycleSnapshot`
- [L217](../../gui/engine_controller.py#L217) `EngineController.start_replay(self) -> None`
- [L226](../../gui/engine_controller.py#L226) `EngineController.request_replay_stop(self) -> None`
- [L230](../../gui/engine_controller.py#L230) `EngineController.request_shutdown(self) -> str`
- [L240](../../gui/engine_controller.py#L240) `EngineController.finish_replay(self) -> bool`
- [L245](../../gui/engine_controller.py#L245) `EngineController.configure_analysis(self, *, rppg_enabled: bool, fatigue_enabled: bool, ports: AnalysisLifecyclePorts | None=None) -> AnalysisPlan`
- [L283](../../gui/engine_controller.py#L283) `EngineController._activate_analysis(plan: AnalysisPlan, ports: AnalysisLifecyclePorts) -> None`
- [L293](../../gui/engine_controller.py#L293) `EngineController.activate_current_analysis(self, ports: AnalysisLifecyclePorts) -> AnalysisPlan`
- [L300](../../gui/engine_controller.py#L300) `EngineController.replace_cameras(self, devices: Iterable[CameraDevice]) -> None`
- [L312](../../gui/engine_controller.py#L312) `EngineController.select_camera(self, index: int | None) -> None`
- [L324](../../gui/engine_controller.py#L324) `EngineController.restore_camera(self, index: int) -> None`
- [L332](../../gui/engine_controller.py#L332) `EngineController.configure_camera(self, *, resolution: object=_UNSET, fps: object=_UNSET, backend: object=_UNSET, horizontal_flip: object=_UNSET) -> None`
- [L362](../../gui/engine_controller.py#L362) `EngineController.camera_snapshot(self) -> CameraConfig`
- [L365](../../gui/engine_controller.py#L365) `EngineController.reset_camera_settings(self) -> None`
- [L375](../../gui/engine_controller.py#L375) `EngineController.selected_camera_label(self) -> str`
- [L382](../../gui/engine_controller.py#L382) `EngineController.camera_start_spec(self) -> CameraStartSpec`

### `gui/engine_runtime.py`

[原始碼](../../gui/engine_runtime.py)；333 行。Qt adapter lifetime owner for the headless desktop engine.

本地直接依賴：`gui.alarm_config`, `gui.alarm_player`。

- 類別 [EngineRuntime](../../gui/engine_runtime.py#L23)
- [L29](../../gui/engine_runtime.py#L29) `EngineRuntime.__init__(self, parent: QObject, *, thread_factory: ThreadFactory=QThread, timer_factory: TimerFactory=QTimer, alarm_controller_factory: AlarmControllerFactory=FatigueAlarmController) -> None`
- [L50](../../gui/engine_runtime.py#L50) `EngineRuntime.alarm_controller(self) -> FatigueAlarmController | None`
- [L53](../../gui/engine_runtime.py#L53) `EngineRuntime.initialize_alarm(self, config: AlarmConfig) -> FatigueAlarmController`
- [L61](../../gui/engine_runtime.py#L61) `EngineRuntime.replace_alarm_controller(self, controller: FatigueAlarmController) -> None`
- [L68](../../gui/engine_runtime.py#L68) `EngineRuntime.configure_alarm(self, config: AlarmConfig) -> None`
- [L74](../../gui/engine_runtime.py#L74) `EngineRuntime.preview_alarm(self, scenario: str, *, config: AlarmConfig | None=None) -> str | None`
- [L85](../../gui/engine_runtime.py#L85) `EngineRuntime.handle_alarm_metrics(self, metrics: object) -> None`
- [L90](../../gui/engine_runtime.py#L90) `EngineRuntime.close_alarm(self) -> bool`
- [L101](../../gui/engine_runtime.py#L101) `EngineRuntime.start_periodic_timer(self, kind: str, interval_ms: int, callback: TimerCallback) -> QTimer`
- [L122](../../gui/engine_runtime.py#L122) `EngineRuntime.schedule_timer(self, kind: str, delay_ms: int, callback: TimerCallback) -> QTimer`
- [L155](../../gui/engine_runtime.py#L155) `EngineRuntime.cancel_timer(self, kind: str) -> bool`
- [L163](../../gui/engine_runtime.py#L163) `EngineRuntime.timer_active(self, kind: str) -> bool`
- [L167](../../gui/engine_runtime.py#L167) `EngineRuntime.defer(self, delay_ms: int, callback: TimerCallback) -> QTimer`
- [L190](../../gui/engine_runtime.py#L190) `EngineRuntime._dispose_timer(timer: QTimer) -> None`
- [L194](../../gui/engine_runtime.py#L194) `EngineRuntime._release_deferred_timer(self, timer: QTimer) -> bool`
- [L201](../../gui/engine_runtime.py#L201) `EngineRuntime.start_adapter(self, kind: str, worker: object, *, connect: AdapterConnect | None=None) -> QThread`
- [L249](../../gui/engine_runtime.py#L249) `EngineRuntime.request_adapter_stop(self, kind: str) -> bool`
- [L258](../../gui/engine_runtime.py#L258) `EngineRuntime.join_adapter(self, kind: str, timeout_ms: int) -> bool`
- [L275](../../gui/engine_runtime.py#L275) `EngineRuntime.stop_adapter(self, kind: str, timeout_ms: int) -> bool`
- [L281](../../gui/engine_runtime.py#L281) `EngineRuntime.release_adapter(self, kind: str, expected_thread: QThread | object | None=None) -> bool`
- [L300](../../gui/engine_runtime.py#L300) `EngineRuntime._on_adapter_finished(self, kind: str, thread: object) -> None`
- [L308](../../gui/engine_runtime.py#L308) `EngineRuntime._drain_finished_adapters(self) -> None`
- [L320](../../gui/engine_runtime.py#L320) `EngineRuntime._release_joined_adapter(self, kind: str, thread: object) -> None`
- [L324](../../gui/engine_runtime.py#L324) `EngineRuntime.worker(self, kind: str) -> object | None`
- [L328](../../gui/engine_runtime.py#L328) `EngineRuntime.thread(self, kind: str) -> QThread | None`
- [L332](../../gui/engine_runtime.py#L332) `EngineRuntime.all_stopped(self) -> bool`

### `gui/fatigue_engine.py`

[原始碼](../../gui/fatigue_engine.py)；1673 行。V2 Behavior Alertness Engine — pure computation, no UI code.

本地直接依賴：`gui.fatigue_scorer`, `gui.mediapipe_tuning`, `gui.personal_profile`。

- [L101](../../gui/fatigue_engine.py#L101) `_dist(p1: tuple, p2: tuple) -> float`
- [L105](../../gui/fatigue_engine.py#L105) `_p(lm: Any, w: int, h: int, idx: int) -> tuple[int, int]`
- [L109](../../gui/fatigue_engine.py#L109) `_pf(lm: Any, idx: int) -> tuple[float, float]`
- [L114](../../gui/fatigue_engine.py#L114) `_mean_pf(lm: Any, idxs: list[int]) -> tuple[float, float]`
- [L124](../../gui/fatigue_engine.py#L124) `_mean_p(lm: Any, w: int, h: int, idxs: list[int]) -> tuple[float, float]`
- [L131](../../gui/fatigue_engine.py#L131) `_blendshape_map(blendshapes: Any | None) -> dict[str, float]`
- [L162](../../gui/fatigue_engine.py#L162) `_bs(bs: dict[str, float], *names: str) -> float`
- [L166](../../gui/fatigue_engine.py#L166) `_norm_blend(raw: float, base: float) -> float`
- [L173](../../gui/fatigue_engine.py#L173) `_clamp(x: float, a: float, b: float) -> float`
- [L177](../../gui/fatigue_engine.py#L177) `eye_aspect_ratio(pts6: list[tuple[int, int]]) -> float`
- [L185](../../gui/fatigue_engine.py#L185) `mouth_aspect_ratio(pts8: list[tuple[int, int]]) -> float`
- [L193](../../gui/fatigue_engine.py#L193) `solve_head_pose(lm: Any, w: int, h: int) -> Optional[tuple[float, float, float]]`
- 類別 [FatigueParams](../../gui/fatigue_engine.py#L229)
- 類別 [FatigueMetrics](../../gui/fatigue_engine.py#L352)
- 類別 [EyeCognitiveModule](../../gui/fatigue_engine.py#L438)
- [L441](../../gui/fatigue_engine.py#L441) `EyeCognitiveModule.__init__(self, p: FatigueParams) -> None`
- [L445](../../gui/fatigue_engine.py#L445) `EyeCognitiveModule.reset(self, *, full: bool=True) -> None`
- [L529](../../gui/fatigue_engine.py#L529) `EyeCognitiveModule.seed_brow_baseline(self, value: float) -> None`
- [L534](../../gui/fatigue_engine.py#L534) `EyeCognitiveModule.seed_blink_feature_baseline(self, baseline: dict[str, tuple[float, float]]) -> None`
- [L541](../../gui/fatigue_engine.py#L541) `EyeCognitiveModule._open_interval(self, t: float, q: float) -> None`
- [L546](../../gui/fatigue_engine.py#L546) `EyeCognitiveModule._close_interval(self, t: float) -> None`
- [L551](../../gui/fatigue_engine.py#L551) `EyeCognitiveModule._perclos(self, t_now: float) -> float`
- [L579](../../gui/fatigue_engine.py#L579) `EyeCognitiveModule._z_from_baseline(self, key: str, value: float) -> float`
- [L587](../../gui/fatigue_engine.py#L587) `EyeCognitiveModule._update_blink_features(self, *, duration: float, ear_start: float, ear_bottom: float, ear_end: float, bottom_to_end_sec: float) -> None`
- [L633](../../gui/fatigue_engine.py#L633) `EyeCognitiveModule.step(self, lm: Any, w: int, h: int, t_now: float, blink_ok: bool, fatigue_ok: bool, fatigue_quality: float, blendshapes: Any | None=None, run_brow: bool=True) -> None`
- 類別 [GazeTrackingModule](../../gui/fatigue_engine.py#L913)
- [L916](../../gui/fatigue_engine.py#L916) `GazeTrackingModule.__init__(self, p: FatigueParams) -> None`
- [L920](../../gui/fatigue_engine.py#L920) `GazeTrackingModule.reset(self) -> None`
- [L944](../../gui/fatigue_engine.py#L944) `GazeTrackingModule.step(self, lm: Any, t_now: float, has_iris: bool, eyes_closed: bool=False) -> None`
- 類別 [HeadMouthModule](../../gui/fatigue_engine.py#L1052)
- [L1055](../../gui/fatigue_engine.py#L1055) `HeadMouthModule.__init__(self, p: FatigueParams) -> None`
- [L1059](../../gui/fatigue_engine.py#L1059) `HeadMouthModule.reset(self, *, full: bool=True) -> None`
- [L1086](../../gui/fatigue_engine.py#L1086) `HeadMouthModule.step(self, lm: Any, w: int, h: int, t_now: float, blendshapes: Any | None=None, fatigue_quality: float=1.0, blend_calib_progress: float=0.0, run_pose: bool=True) -> tuple[bool, bool]`
- 類別 [FatigueEngine](../../gui/fatigue_engine.py#L1212)
- [L1219](../../gui/fatigue_engine.py#L1219) `FatigueEngine.__init__(self, params: Optional[FatigueParams]=None, personal_profile: Optional[PersonalProfile]=None) -> None`
- [L1248](../../gui/fatigue_engine.py#L1248) `FatigueEngine.reset(self) -> None`
- [L1261](../../gui/fatigue_engine.py#L1261) `FatigueEngine.set_personal_profile(self, profile: Optional[PersonalProfile]) -> None`
- [L1266](../../gui/fatigue_engine.py#L1266) `FatigueEngine._seed_from_profile(self) -> None`
- [L1282](../../gui/fatigue_engine.py#L1282) `FatigueEngine._load_persisted_calibration(self) -> None`
- [L1294](../../gui/fatigue_engine.py#L1294) `FatigueEngine._save_persisted_calibration(self) -> None`
- [L1310](../../gui/fatigue_engine.py#L1310) `FatigueEngine.on_no_face(self, t_now: Optional[float]=None) -> FatigueMetrics`
- [L1341](../../gui/fatigue_engine.py#L1341) `FatigueEngine.step(self, lm: Any, w: int, h: int, t_now: float, blendshapes: Any | None=None) -> FatigueMetrics`

### `gui/fatigue_scorer.py`

[原始碼](../../gui/fatigue_scorer.py)；458 行。Fused Fatigue Scorer — combines rPPG (15 %) and behaviour alertness (85 %).

本地直接依賴：`gui.fatigue_engine`, `rppg.rppg_worker`。

- [L37](../../gui/fatigue_scorer.py#L37) `_clamp(x: float, lo: float=0.0, hi: float=1.0) -> float`
- [L52](../../gui/fatigue_scorer.py#L52) `compute_closure_s(eye_closure_sec: float, onset_sec: float, full_sec: float) -> float`
- 類別 [FuserConfig](../../gui/fatigue_scorer.py#L67)
- [L147](../../gui/fatigue_scorer.py#L147) `FuserConfig.for_rppg(cls) -> 'FuserConfig'`
- 類別 [FusedFatigueScore](../../gui/fatigue_scorer.py#L154)
- [L204](../../gui/fatigue_scorer.py#L204) `_score_to_level(s: float) -> tuple[str, str, tuple]`
- 類別 [FatigueFuser](../../gui/fatigue_scorer.py#L213)
- [L220](../../gui/fatigue_scorer.py#L220) `FatigueFuser.__init__(self, config: Optional[FuserConfig]=None) -> None`
- [L225](../../gui/fatigue_scorer.py#L225) `FatigueFuser._level_with_hysteresis(self, s: float) -> tuple[str, str, tuple]`
- [L243](../../gui/fatigue_scorer.py#L243) `FatigueFuser._rppg_sub_score(self, r: 'RppgMetrics') -> tuple[float, float, float, float]`
- [L286](../../gui/fatigue_scorer.py#L286) `FatigueFuser._behavior_sub_score(self, f: 'FatigueMetrics') -> tuple[float, ...]`
- [L364](../../gui/fatigue_scorer.py#L364) `FatigueFuser.update(self, rppg: 'Optional[RppgMetrics]'=None, fatigue: 'Optional[FatigueMetrics]'=None) -> FusedFatigueScore`

### `gui/fatigue_worker.py`

[原始碼](../../gui/fatigue_worker.py)；730 行。V2 Behavior Alertness Worker — QObject that runs in its own QThread.

本地直接依賴：`gui.fatigue_engine`, `gui.frame_queue`, `gui.mediapipe_tuning`, `gui.personal_profile`, `gui.platforms`, `gui.worker_safety`, `rppg.rppg_worker`。

- [L139](../../gui/fatigue_worker.py#L139) `_lm_px(lm, w: int, h: int, idx: int) -> tuple[int, int]`
- [L143](../../gui/fatigue_worker.py#L143) `_lm_mean_px(lm, w: int, h: int, idxs: list[int]) -> tuple[int, int]`
- [L148](../../gui/fatigue_worker.py#L148) `_draw_head_pose_axes(out: np.ndarray, nose_px: tuple[int, int], pitch_deg: float, yaw_deg: float, roll_deg: float, scale: int) -> None`
- [L220](../../gui/fatigue_worker.py#L220) `_cjk_font_path() -> Optional[str]`
- [L229](../../gui/fatigue_worker.py#L229) `_resolve_cjk_font(size: int)`
- [L245](../../gui/fatigue_worker.py#L245) `_put_outlined_text(text_queue: list, text: str, org: tuple[int, int], font: int, scale: float, color: tuple, thickness: int=1, outline_thickness: int=3, outline_color: tuple=(0, 0, 0)) -> None`
- [L266](../../gui/fatigue_worker.py#L266) `_flush_text_queue(out: np.ndarray, text_queue: list) -> np.ndarray`
- [L296](../../gui/fatigue_worker.py#L296) `_pil_text_size(text: str, scale: float) -> tuple[int, int]`
- [L316](../../gui/fatigue_worker.py#L316) `draw_fatigue_annotations(frame: np.ndarray, lm: list, metrics: FatigueMetrics) -> np.ndarray`
- 類別 [FatigueWorker](../../gui/fatigue_worker.py#L557)
- [L578](../../gui/fatigue_worker.py#L578) `FatigueWorker.__init__(self, frame_queue: 'queue.Queue[tuple[float, np.ndarray]]', target_fps: float=30.0, params: Optional[FatigueParams]=None, personal_profile: Optional[PersonalProfile]=None) -> None`
- [L596](../../gui/fatigue_worker.py#L596) `FatigueWorker.request_stop(self) -> None`
- [L599](../../gui/fatigue_worker.py#L599) `FatigueWorker.set_personal_profile(self, profile: Optional[PersonalProfile]) -> None`
- [L606](../../gui/fatigue_worker.py#L606) `FatigueWorker.run(self) -> None`

### `gui/file_browser_client.py`

[原始碼](../../gui/file_browser_client.py)；242 行。File Browser API client.

- 類別 [FileBrowserClient](../../gui/file_browser_client.py#L19)
- [L20](../../gui/file_browser_client.py#L20) `FileBrowserClient.__init__(self) -> None`
- [L31](../../gui/file_browser_client.py#L31) `FileBrowserClient.configure(self, base_url: str, username: str, password: str) -> bool`
- [L45](../../gui/file_browser_client.py#L45) `FileBrowserClient.is_authenticated(self) -> bool`
- [L48](../../gui/file_browser_client.py#L48) `FileBrowserClient.get_info(self) -> dict`
- [L54](../../gui/file_browser_client.py#L54) `FileBrowserClient.logout(self) -> None`
- [L63](../../gui/file_browser_client.py#L63) `FileBrowserClient.list_recordings(self) -> list[dict]`
- [L99](../../gui/file_browser_client.py#L99) `FileBrowserClient.download_db(self, remote_path: str, cache_dir: Path) -> Path`
- [L126](../../gui/file_browser_client.py#L126) `FileBrowserClient.stream_video(self, remote_path: str, range_header: Optional[str]=None) -> requests.Response`
- [L135](../../gui/file_browser_client.py#L135) `FileBrowserClient.upload_file(self, local_path: Path, remote_path: str, progress_cb: Optional[Callable[[float], None]]=None) -> None`
- [L167](../../gui/file_browser_client.py#L167) `FileBrowserClient._do_login_locked(self) -> bool`
- [L186](../../gui/file_browser_client.py#L186) `FileBrowserClient._ensure_token(self) -> None`
- [L192](../../gui/file_browser_client.py#L192) `FileBrowserClient._auth_headers(self) -> dict`
- [L196](../../gui/file_browser_client.py#L196) `FileBrowserClient._request(self, method: str, path: str, *, data_factory: Optional[Callable]=None, **kwargs) -> requests.Response`
- [L224](../../gui/file_browser_client.py#L224) `FileBrowserClient._heartbeat_loop(self) -> None`
- [L231](../../gui/file_browser_client.py#L231) `FileBrowserClient._start_heartbeat(self) -> None`
- [L238](../../gui/file_browser_client.py#L238) `FileBrowserClient._stop_heartbeat(self) -> None`

### `gui/frame_queue.py`

[原始碼](../../gui/frame_queue.py)；37 行。低延遲影像佇列工具。

- [L11](../../gui/frame_queue.py#L11) `put_latest(q: 'queue.Queue[T]', item: T) -> None`
- [L30](../../gui/frame_queue.py#L30) `get_latest(q: 'queue.Queue[T]', timeout: float) -> T`

### `gui/global_hotkeys.py`

[原始碼](../../gui/global_hotkeys.py)；166 行。套件／工具入口

- 類別 [HotkeyRegistrationFailure](../../gui/global_hotkeys.py#L23)
- 類別 [HotkeyUnregistrationFailure](../../gui/global_hotkeys.py#L30)
- 類別 [GlobalHotkeyRuntime](../../gui/global_hotkeys.py#L36)
- [L39](../../gui/global_hotkeys.py#L39) `GlobalHotkeyRuntime.__init__(self, dispatch: Callable[[int], None], *, supported: bool | None=None, application: Any | None=None, user32: Any | None=None, get_last_error: Callable[[], int] | None=None) -> None`
- [L62](../../gui/global_hotkeys.py#L62) `GlobalHotkeyRuntime.supported(self) -> bool`
- [L65](../../gui/global_hotkeys.py#L65) `GlobalHotkeyRuntime.register(self, bindings: Mapping[int, tuple[int, int]]) -> tuple[HotkeyRegistrationFailure, ...]`
- [L119](../../gui/global_hotkeys.py#L119) `GlobalHotkeyRuntime.unregister(self) -> tuple[HotkeyUnregistrationFailure, ...]`
- [L139](../../gui/global_hotkeys.py#L139) `GlobalHotkeyRuntime.nativeEventFilter(self, event_type: object, message: int) -> tuple[bool, int]`
- [L152](../../gui/global_hotkeys.py#L152) `GlobalHotkeyRuntime._resolve_user32(self) -> Any`
- [L157](../../gui/global_hotkeys.py#L157) `GlobalHotkeyRuntime._remove_filter_if_idle(self) -> None`
- [L163](../../gui/global_hotkeys.py#L163) `GlobalHotkeyRuntime._require_application_thread(application: Any) -> None`

### `gui/main_window.py`

[原始碼](../../gui/main_window.py)；3296 行。套件／工具入口

本地直接依賴：`gui.alarm_config`, `gui.belt_runtime`, `gui.camera_devices`, `gui.camera_stream_worker`, `gui.capture_preferences_state`, `gui.combined_worker`, `gui.desktop_control`, `gui.desktop_models`, `gui.desktop_settings_contract`, `gui.engine_controller`, `gui.engine_runtime`, `gui.fatigue_scorer`, `gui.fatigue_worker`, `gui.global_hotkeys`, `gui.metrics_recorder`, `gui.overlay_runtime_state`, `gui.personal_profile`, `gui.replay_runtime_state`, `gui.runtime_paths`, `gui.video_recorder`, `gui.video_replay`, `gui.web_preferences_state`, `gui.web_server`, `rppg.adaptive_calibration`, `rppg.belt_truth_capture`, `rppg.calibration`, `rppg.hr_belt_ble`, `rppg.rppg_worker`, `rppg.watch_physio`。

- [L92](../../gui/main_window.py#L92) `_classify_log_message(message: str, *, warning_priority: bool=False) -> str`
- 類別 [_WebRestartBridge](../../gui/main_window.py#L109)
- 類別 [_GlobalHotkeyBinding](../../gui/main_window.py#L114)
- 類別 [EngineApplication](../../gui/main_window.py#L123)
- [L126](../../gui/main_window.py#L126) `EngineApplication.__init__(self, *, engine_mode: bool=True) -> None`
- [L257](../../gui/main_window.py#L257) `EngineApplication._cam_thread(self) -> QThread | None`
- [L261](../../gui/main_window.py#L261) `EngineApplication._cam_worker(self) -> CameraStreamWorker | None`
- [L265](../../gui/main_window.py#L265) `EngineApplication._combined_thread(self) -> QThread | None`
- [L269](../../gui/main_window.py#L269) `EngineApplication._combined_worker(self) -> CombinedWorker | None`
- [L273](../../gui/main_window.py#L273) `EngineApplication._rppg_thread(self) -> QThread | None`
- [L277](../../gui/main_window.py#L277) `EngineApplication._rppg_worker(self) -> RppgWorker | None`
- [L281](../../gui/main_window.py#L281) `EngineApplication._fatigue_thread(self) -> QThread | None`
- [L285](../../gui/main_window.py#L285) `EngineApplication._fatigue_worker(self) -> FatigueWorker | None`
- [L289](../../gui/main_window.py#L289) `EngineApplication._video_thread(self) -> QThread | None`
- [L293](../../gui/main_window.py#L293) `EngineApplication._video_worker(self) -> VideoRecorderWorker | None`
- [L297](../../gui/main_window.py#L297) `EngineApplication._replay_thread(self) -> QThread | None`
- [L301](../../gui/main_window.py#L301) `EngineApplication._replay_worker(self) -> VideoReplayWorker | None`
- [L304](../../gui/main_window.py#L304) `EngineApplication._toggle_overlay_preference(self, field: str) -> None`
- [L309](../../gui/main_window.py#L309) `EngineApplication._set_monitor_layout(self, focus: bool) -> None`
- [L313](../../gui/main_window.py#L313) `EngineApplication._configure_overlay(self, **changes: object) -> None`
- [L320](../../gui/main_window.py#L320) `EngineApplication._configure_replay(self, **changes: object) -> None`
- [L323](../../gui/main_window.py#L323) `EngineApplication._update_replay_presentation(self, **changes: object) -> None`
- [L326](../../gui/main_window.py#L326) `EngineApplication._configure_web_preferences(self, *, allow_lan: bool, mark_dirty: bool=True, restart_server: bool=True) -> None`
- [L339](../../gui/main_window.py#L339) `EngineApplication._configure_capture_preferences(self, *, mark_dirty: bool=True, **changes: object) -> None`
- [L372](../../gui/main_window.py#L372) `EngineApplication._configure_analysis(self, *, behavior_enabled: bool, rppg_enabled: bool) -> None`
- [L410](../../gui/main_window.py#L410) `EngineApplication._qt_key_to_vk(self, qt_key: int) -> int | None`
- [L429](../../gui/main_window.py#L429) `EngineApplication._parse_hotkey(self, seq_text: str) -> tuple[int, int] | None`
- [L475](../../gui/main_window.py#L475) `EngineApplication._qt_enum_int(value: object) -> int`
- [L478](../../gui/main_window.py#L478) `EngineApplication._register_global_hotkeys(self) -> None`
- [L522](../../gui/main_window.py#L522) `EngineApplication._unregister_global_hotkeys(self) -> None`
- [L530](../../gui/main_window.py#L530) `EngineApplication._on_global_hotkey(self, hotkey_id: int) -> None`
- [L536](../../gui/main_window.py#L536) `EngineApplication._settings_path(self) -> Path`
- [L539](../../gui/main_window.py#L539) `EngineApplication._on_camera_config_changed(self, **changes: object) -> None`
- [L542](../../gui/main_window.py#L542) `EngineApplication._load_settings(self) -> None`
- [L647](../../gui/main_window.py#L647) `EngineApplication._save_settings(self) -> Path`
- [L724](../../gui/main_window.py#L724) `EngineApplication._start_camera_scan(self) -> None`
- [L736](../../gui/main_window.py#L736) `EngineApplication._finish_camera_scan_ui(self, dev_list: list[tuple[int, str]]) -> None`
- [L745](../../gui/main_window.py#L745) `EngineApplication._apply_hotkey_shortcuts(self) -> None`
- [L780](../../gui/main_window.py#L780) `EngineApplication._recordings_dir(self) -> Path`
- [L785](../../gui/main_window.py#L785) `EngineApplication._web_allow_lan_enabled(self) -> bool`
- [L788](../../gui/main_window.py#L788) `EngineApplication._web_bind_host(self) -> str`
- [L791](../../gui/main_window.py#L791) `EngineApplication._web_access_token(self) -> str | None`
- [L795](../../gui/main_window.py#L795) `EngineApplication._web_dashboard_urls(self) -> list[str]`
- [L805](../../gui/main_window.py#L805) `EngineApplication._format_web_dashboard_message(self, *, include_lan_hint: bool=False) -> str`
- [L818](../../gui/main_window.py#L818) `EngineApplication._start_web_server(self) -> None`
- [L842](../../gui/main_window.py#L842) `EngineApplication._schedule_web_server_restart(self) -> None`
- [L848](../../gui/main_window.py#L848) `EngineApplication._begin_web_server_restart(self) -> None`
- [L871](../../gui/main_window.py#L871) `EngineApplication._on_web_restart_stopped(self, _stopped: bool, still_alive: bool) -> None`
- [L885](../../gui/main_window.py#L885) `EngineApplication._stop_web_server(self) -> None`
- [L902](../../gui/main_window.py#L902) `EngineApplication._build_web_metrics(self) -> dict`
- [L1077](../../gui/main_window.py#L1077) `EngineApplication._drain_desktop_commands(self) -> None`
- [L1081](../../gui/main_window.py#L1081) `EngineApplication._require_bool(args: dict[str, Any], key: str) -> bool`
- [L1088](../../gui/main_window.py#L1088) `EngineApplication._parse_hotkey_config(args: dict[str, Any]) -> HotkeyConfig`
- [L1116](../../gui/main_window.py#L1116) `EngineApplication._parse_user_profile(args: dict[str, Any]) -> UserProfile`
- [L1121](../../gui/main_window.py#L1121) `EngineApplication._parse_alarm_config(args: dict[str, Any]) -> AlarmConfig`
- [L1125](../../gui/main_window.py#L1125) `EngineApplication._parse_settings_reset_sections(args: dict[str, Any]) -> list[str]`
- [L1128](../../gui/main_window.py#L1128) `EngineApplication._reset_settings_sections(self, sections: list[str]) -> None`
- [L1176](../../gui/main_window.py#L1176) `EngineApplication._desktop_control_state(self) -> dict[str, Any]`
- [L1245](../../gui/main_window.py#L1245) `EngineApplication._handle_desktop_command(self, command: str, args: dict[str, Any]) -> dict[str, Any]`
- [L1545](../../gui/main_window.py#L1545) `EngineApplication._shutdown_engine(self) -> None`
- [L1566](../../gui/main_window.py#L1566) `EngineApplication._retry_runtime_shutdown(self) -> None`
- [L1570](../../gui/main_window.py#L1570) `EngineApplication.close_runtime(self) -> bool`
- [L1574](../../gui/main_window.py#L1574) `EngineApplication._cleanup_runtime(self) -> bool`
- [L1620](../../gui/main_window.py#L1620) `EngineApplication._runtime_adapter_threads_stopped(self) -> bool`
- [L1623](../../gui/main_window.py#L1623) `EngineApplication._emit_web_metrics(self, *, force: bool=False) -> None`
- [L1635](../../gui/main_window.py#L1635) `EngineApplication._encode_frame_jpeg(image: QImage, *, max_width: int=640, quality: int=70) -> str | None`
- [L1654](../../gui/main_window.py#L1654) `EngineApplication._emit_web_frame(self, image: QImage) -> None`
- [L1672](../../gui/main_window.py#L1672) `EngineApplication._start_recording(self) -> None`
- [L1700](../../gui/main_window.py#L1700) `EngineApplication._stop_recording(self) -> bool`
- [L1730](../../gui/main_window.py#L1730) `EngineApplication._build_record_payload(self) -> dict`
- [L1842](../../gui/main_window.py#L1842) `EngineApplication._record_metrics(self) -> None`
- [L1849](../../gui/main_window.py#L1849) `EngineApplication._on_video_recording_started(self, path: str) -> None`
- [L1857](../../gui/main_window.py#L1857) `EngineApplication._on_video_recording_warning(self, msg: str) -> None`
- [L1861](../../gui/main_window.py#L1861) `EngineApplication._on_video_recording_failed(self, msg: str) -> None`
- [L1867](../../gui/main_window.py#L1867) `EngineApplication._append_log(self, msg: str) -> None`
- [L1876](../../gui/main_window.py#L1876) `EngineApplication._publish_desktop_notice(self, message: str, *, level: str='error') -> None`
- [L1885](../../gui/main_window.py#L1885) `EngineApplication._notify_user(self, title: str, message: str, *, level: str='error') -> None`
- [L1888](../../gui/main_window.py#L1888) `EngineApplication._start_replay(self) -> None`
- [L1891](../../gui/main_window.py#L1891) `EngineApplication._start_replay_parallel(self, *, notify: bool=True) -> None`
- [L1906](../../gui/main_window.py#L1906) `EngineApplication._start_replay_run(self, *, jobs: int, preview_enabled: bool, mode_label: str) -> None`
- [L1960](../../gui/main_window.py#L1960) `EngineApplication._stop_replay(self) -> None`
- [L1972](../../gui/main_window.py#L1972) `EngineApplication._on_replay_progress(self, event: str, current: int, total: int, summary: ReplayVideoSummary | None) -> None`
- [L2034](../../gui/main_window.py#L2034) `EngineApplication._replay_video_key(self, summary: ReplayVideoSummary) -> str`
- [L2037](../../gui/main_window.py#L2037) `EngineApplication._format_replay_video_label(self, summary: ReplayVideoSummary, *, include_status: bool=False) -> str`
- [L2052](../../gui/main_window.py#L2052) `EngineApplication._refresh_replay_parallel_status(self) -> None`
- [L2068](../../gui/main_window.py#L2068) `EngineApplication._on_replay_finished_ok(self, result: ReplayBatchResult) -> None`
- [L2098](../../gui/main_window.py#L2098) `EngineApplication._on_replay_failed(self, msg: str) -> None`
- [L2110](../../gui/main_window.py#L2110) `EngineApplication._on_replay_thread_finished(self) -> None`
- [L2118](../../gui/main_window.py#L2118) `EngineApplication._start_camera_worker(self) -> None`
- [L2157](../../gui/main_window.py#L2157) `EngineApplication._stop_camera_worker(self) -> bool`
- [L2162](../../gui/main_window.py#L2162) `EngineApplication._fail_closed_pipeline_adapters(self) -> None`
- [L2172](../../gui/main_window.py#L2172) `EngineApplication._fail_closed_pipeline_adapters_impl(self) -> None`
- [L2221](../../gui/main_window.py#L2221) `EngineApplication._on_adapter_released(self, kind: str, _thread: object) -> None`
- [L2249](../../gui/main_window.py#L2249) `EngineApplication._update_frame_routing(self) -> None`
- [L2268](../../gui/main_window.py#L2268) `EngineApplication._update_recording_routing(self) -> None`
- [L2285](../../gui/main_window.py#L2285) `EngineApplication._set_frame_source(self, source: str | None) -> None`
- [L2292](../../gui/main_window.py#L2292) `EngineApplication._set_record_source(self, source: str | None) -> None`
- [L2299](../../gui/main_window.py#L2299) `EngineApplication._connect_source(self, source: str | None, handler) -> None`
- [L2309](../../gui/main_window.py#L2309) `EngineApplication._disconnect_source(self, source: str | None, handler) -> None`
- [L2326](../../gui/main_window.py#L2326) `EngineApplication._rppg_active(self) -> bool`
- [L2331](../../gui/main_window.py#L2331) `EngineApplication._on_belt_calib_toggled(self, checked: bool) -> None`
- [L2343](../../gui/main_window.py#L2343) `EngineApplication._ensure_belt_calibration(self) -> None`
- [L2355](../../gui/main_window.py#L2355) `EngineApplication._start_belt_calibration(self) -> None`
- [L2414](../../gui/main_window.py#L2414) `EngineApplication._dispatch_belt_truth_capture(self, writer: BeltTruthCaptureWriter | None) -> None`
- [L2421](../../gui/main_window.py#L2421) `EngineApplication._rollback_failed_belt_calibration_start(self, *, stop_belt: bool) -> None`
- [L2447](../../gui/main_window.py#L2447) `EngineApplication._resolve_current_roi_weights(self) -> dict[str, float]`
- [L2461](../../gui/main_window.py#L2461) `EngineApplication._stop_belt_calibration(self) -> None`
- [L2482](../../gui/main_window.py#L2482) `EngineApplication._persist_belt_calibration(self) -> None`
- [L2529](../../gui/main_window.py#L2529) `EngineApplication._tick_belt_calibration(self) -> None`
- [L2546](../../gui/main_window.py#L2546) `EngineApplication._tick_rppg_param_coordinator(self, cal: OnlineBpmCalibrator | None) -> None`
- [L2565](../../gui/main_window.py#L2565) `EngineApplication._dispatch_candidate_roi_weights(self, weights: dict[str, float] | None) -> None`
- [L2572](../../gui/main_window.py#L2572) `EngineApplication._clear_candidate_roi_weights(self) -> None`
- [L2575](../../gui/main_window.py#L2575) `EngineApplication._on_candidate_bpm_ready(self, t_now: float, cur_bpm: float, cand_bpm: float) -> None`
- [L2602](../../gui/main_window.py#L2602) `EngineApplication._adopt_rppg_param_candidate(self) -> None`
- [L2630](../../gui/main_window.py#L2630) `EngineApplication._analysis_lifecycle_ports(self) -> AnalysisLifecyclePorts`
- [L2639](../../gui/main_window.py#L2639) `EngineApplication._stop_analysis_workers(self) -> None`
- [L2657](../../gui/main_window.py#L2657) `EngineApplication._start_combined_worker(self, enable_rppg: bool=True) -> None`
- [L2692](../../gui/main_window.py#L2692) `EngineApplication._stop_combined_worker(self) -> bool`
- [L2705](../../gui/main_window.py#L2705) `EngineApplication._on_fused_score(self, score: object) -> None`
- [L2710](../../gui/main_window.py#L2710) `EngineApplication._on_combined_failed(self, msg: str) -> None`
- [L2721](../../gui/main_window.py#L2721) `EngineApplication._start_rppg_worker(self) -> None`
- [L2748](../../gui/main_window.py#L2748) `EngineApplication._stop_rppg_worker(self) -> bool`
- [L2760](../../gui/main_window.py#L2760) `EngineApplication._on_stress_toggled(self, checked: bool) -> None`
- [L2767](../../gui/main_window.py#L2767) `EngineApplication._load_rppg_calibration_version(self)`
- [L2776](../../gui/main_window.py#L2776) `EngineApplication._apply_rppg_calibration(self, metrics: object) -> object`
- [L2782](../../gui/main_window.py#L2782) `EngineApplication._on_rppg_metrics(self, metrics: object) -> None`
- [L2790](../../gui/main_window.py#L2790) `EngineApplication._on_rppg_failed(self, msg: str) -> None`
- [L2802](../../gui/main_window.py#L2802) `EngineApplication._start_fatigue_worker(self) -> None`
- [L2827](../../gui/main_window.py#L2827) `EngineApplication._stop_fatigue_worker(self) -> bool`
- [L2840](../../gui/main_window.py#L2840) `EngineApplication._on_behavior_toggled(self, checked: bool) -> None`
- [L2847](../../gui/main_window.py#L2847) `EngineApplication._on_fatigue_metrics(self, metrics: object) -> None`
- [L2855](../../gui/main_window.py#L2855) `EngineApplication._active_fatigue_worker(self) -> object | None`
- [L2863](../../gui/main_window.py#L2863) `EngineApplication._begin_auto_baseline(self) -> None`
- [L2871](../../gui/main_window.py#L2871) `EngineApplication._end_baseline_collection(self) -> None`
- [L2875](../../gui/main_window.py#L2875) `EngineApplication._feed_baseline_collectors(self, metrics: object) -> None`
- [L2892](../../gui/main_window.py#L2892) `EngineApplication._finalize_auto_baseline(self, collector: PersonalBaselineCollector) -> None`
- [L2911](../../gui/main_window.py#L2911) `EngineApplication._finalize_manual_baseline(self, collector: PersonalBaselineCollector) -> None`
- [L2923](../../gui/main_window.py#L2923) `EngineApplication._hot_swap_profile(self, prof: object) -> None`
- [L2928](../../gui/main_window.py#L2928) `EngineApplication._set_profile_status(self, text: str) -> None`
- [L2931](../../gui/main_window.py#L2931) `EngineApplication._on_record_baseline_clicked(self) -> None`
- [L2940](../../gui/main_window.py#L2940) `EngineApplication._on_fatigue_failed(self, msg: str) -> None`
- [L2950](../../gui/main_window.py#L2950) `EngineApplication._on_camera_info(self, codec: str, w: int, h: int, fps: float) -> None`
- [L2959](../../gui/main_window.py#L2959) `EngineApplication._on_frame(self, image) -> None`
- [L2962](../../gui/main_window.py#L2962) `EngineApplication._on_record_frame(self, image) -> None`
- [L2970](../../gui/main_window.py#L2970) `EngineApplication._on_fps(self, fps: float) -> None`
- [L2987](../../gui/main_window.py#L2987) `EngineApplication._on_camera_failed(self, msg: str) -> None`
- [L3020](../../gui/main_window.py#L3020) `EngineApplication._toggle_pipeline(self) -> None`
- [L3074](../../gui/main_window.py#L3074) `EngineApplication._toggle_recording(self) -> None`
- [L3109](../../gui/main_window.py#L3109) `EngineApplication._cancel_pending_auto_capture_timer(self) -> None`
- [L3113](../../gui/main_window.py#L3113) `EngineApplication._rollback_auto_capture_toggles(self) -> None`
- [L3133](../../gui/main_window.py#L3133) `EngineApplication._on_auto_capture_clicked(self) -> None`
- [L3204](../../gui/main_window.py#L3204) `EngineApplication._finish_auto_capture(self, early: bool) -> None`
- [L3259](../../gui/main_window.py#L3259) `EngineApplication.selected_camera_index(self) -> int | None`
- [L3263](../../gui/main_window.py#L3263) `EngineApplication._on_save_layout(self) -> None`
- [L3267](../../gui/main_window.py#L3267) `EngineApplication._web_dashboard_url_labels(self) -> list[tuple[str, str]]`
- [L3277](../../gui/main_window.py#L3277) `EngineApplication._pick_web_dashboard_url(self) -> str | None`
- [L3283](../../gui/main_window.py#L3283) `EngineApplication._on_web_info(self) -> str`

### `gui/mediapipe_tuning.py`

[原始碼](../../gui/mediapipe_tuning.py)；179 行。MediaPipe tuning configuration and persisted calibration helpers.

本地直接依賴：`gui.runtime_paths`。

- 類別 [FaceLandmarkerTuning](../../gui/mediapipe_tuning.py#L24)
- 類別 [RppgRoiTuning](../../gui/mediapipe_tuning.py#L32)
- 類別 [QualityTuning](../../gui/mediapipe_tuning.py#L58)
- 類別 [BlendshapeTuning](../../gui/mediapipe_tuning.py#L68)
- 類別 [MediaPipeTuning](../../gui/mediapipe_tuning.py#L79)
- [L88](../../gui/mediapipe_tuning.py#L88) `_deep_update(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]`
- [L97](../../gui/mediapipe_tuning.py#L97) `load_mediapipe_tuning(path: Path | None=None) -> MediaPipeTuning`
- 類別 [CalibrationStore](../../gui/mediapipe_tuning.py#L144)
- [L147](../../gui/mediapipe_tuning.py#L147) `CalibrationStore.__init__(self, path: Path | None=None) -> None`
- [L152](../../gui/mediapipe_tuning.py#L152) `CalibrationStore.load(self) -> None`
- [L163](../../gui/mediapipe_tuning.py#L163) `CalibrationStore.save(self) -> None`
- [L173](../../gui/mediapipe_tuning.py#L173) `CalibrationStore.get_section(self, name: str) -> dict[str, Any]`
- [L177](../../gui/mediapipe_tuning.py#L177) `CalibrationStore.set_section(self, name: str, value: dict[str, Any]) -> None`

### `gui/metrics_recorder.py`

[原始碼](../../gui/metrics_recorder.py)；555 行。SQLite metrics recorder for V2 fatigue + rPPG + fused scores.

- 類別 [MetricsRecorder](../../gui/metrics_recorder.py#L30)
- [L258](../../gui/metrics_recorder.py#L258) `MetricsRecorder.__init__(self, db_path: str) -> None`
- [L295](../../gui/metrics_recorder.py#L295) `MetricsRecorder._b(value: Any) -> int`
- [L298](../../gui/metrics_recorder.py#L298) `MetricsRecorder._migrate_schema(self, conn: sqlite3.Connection) -> None`
- [L347](../../gui/metrics_recorder.py#L347) `MetricsRecorder.record(self, data: dict) -> None`
- [L383](../../gui/metrics_recorder.py#L383) `MetricsRecorder.close(self) -> None`
- [L409](../../gui/metrics_recorder.py#L409) `MetricsRecorder._cleanup(self) -> None`
- [L418](../../gui/metrics_recorder.py#L418) `MetricsRecorder.get_recording_stats(self) -> tuple[int, float | None, float | None]`
- [L431](../../gui/metrics_recorder.py#L431) `MetricsRecorder.__del__(self) -> None`
- [L441](../../gui/metrics_recorder.py#L441) `MetricsRecorder._writer_main(self) -> None`
- [L534](../../gui/metrics_recorder.py#L534) `MetricsRecorder._write_meta_sidecar(self, rows: int, ts_min: float | None, ts_max: float | None) -> None`

### `gui/model_assets.py`

[原始碼](../../gui/model_assets.py)；41 行。Face Landmarker 模型的固定來源與安全下載。

- [L21](../../gui/model_assets.py#L21) `download_face_model(target: Path) -> Path`

### `gui/overlay_runtime_state.py`

[原始碼](../../gui/overlay_runtime_state.py)；165 行。套件／工具入口

- 類別 [OverlayGeometry](../../gui/overlay_runtime_state.py#L11)
- [L17](../../gui/overlay_runtime_state.py#L17) `OverlayGeometry.to_dict(self) -> dict[str, int]`
- 類別 [OverlaySnapshot](../../gui/overlay_runtime_state.py#L27)
- 類別 [OverlayRuntimeState](../../gui/overlay_runtime_state.py#L36)
- [L39](../../gui/overlay_runtime_state.py#L39) `OverlayRuntimeState.__init__(self) -> None`
- [L42](../../gui/overlay_runtime_state.py#L42) `OverlayRuntimeState.snapshot(self) -> OverlaySnapshot`
- [L46](../../gui/overlay_runtime_state.py#L46) `OverlayRuntimeState._validate_bool(name: str, value: object) -> bool`
- [L52](../../gui/overlay_runtime_state.py#L52) `OverlayRuntimeState._validate_opacity(value: object) -> int`
- [L58](../../gui/overlay_runtime_state.py#L58) `OverlayRuntimeState._validate_geometry(value: object) -> OverlayGeometry | None`
- [L75](../../gui/overlay_runtime_state.py#L75) `OverlayRuntimeState.configure(self, *, all_enabled: object=_UNSET, preview: object=_UNSET, metrics: object=_UNSET, locked: object=_UNSET, opacity: object=_UNSET, geometry: object=_UNSET) -> OverlaySnapshot`
- [L107](../../gui/overlay_runtime_state.py#L107) `OverlayRuntimeState.load(self, *, toggles: object, overlay: object) -> OverlaySnapshot`
- [L133](../../gui/overlay_runtime_state.py#L133) `OverlayRuntimeState.reset(self) -> OverlaySnapshot`
- [L137](../../gui/overlay_runtime_state.py#L137) `OverlayRuntimeState.to_desktop_state(self) -> dict[str, object]`
- [L150](../../gui/overlay_runtime_state.py#L150) `OverlayRuntimeState.to_settings(self) -> dict[str, dict[str, object]]`

### `gui/personal_profile.py`

[原始碼](../../gui/personal_profile.py)；385 行。個人清醒基線 profile（純運算層，無 Qt / 無 thread）。

本地直接依賴：`gui.fatigue_engine`, `gui.runtime_paths`。

- [L56](../../gui/personal_profile.py#L56) `_clamp(value: float, lo: float, hi: float) -> float`
- [L62](../../gui/personal_profile.py#L62) `_percentile(values: list[float], q: float) -> Optional[float]`
- [L78](../../gui/personal_profile.py#L78) `_median_or_none(values: list[float]) -> Optional[float]`
- [L84](../../gui/personal_profile.py#L84) `_mean_std(values: list[float]) -> tuple[Optional[float], Optional[float]]`
- 類別 [PersonalProfile](../../gui/personal_profile.py#L94)
- [L122](../../gui/personal_profile.py#L122) `PersonalProfile._resolve(self, value: Optional[float], fallback: float) -> float`
- [L129](../../gui/personal_profile.py#L129) `PersonalProfile.perclos_low_th(self, fallback: float) -> float`
- [L135](../../gui/personal_profile.py#L135) `PersonalProfile.perclos_tired_th(self, fallback: float) -> float`
- [L141](../../gui/personal_profile.py#L141) `PersonalProfile.perclos_composite_full(self, fallback: float) -> float`
- [L148](../../gui/personal_profile.py#L148) `PersonalProfile.perclos_score_mild_th(self, fallback: float) -> float`
- [L155](../../gui/personal_profile.py#L155) `PersonalProfile.perclos_score_high_th(self, fallback: float) -> float`
- [L163](../../gui/personal_profile.py#L163) `PersonalProfile.gaze_fixed_std_th(self, fallback: float) -> float`
- [L169](../../gui/personal_profile.py#L169) `PersonalProfile.saccade_low_pm(self, fallback: float) -> float`
- [L175](../../gui/personal_profile.py#L175) `PersonalProfile.mouth_open_yawn_th(self, fallback: float) -> float`
- [L183](../../gui/personal_profile.py#L183) `PersonalProfile.brow_baseline(self) -> Optional[float]`
- [L189](../../gui/personal_profile.py#L189) `PersonalProfile.blink_feature_baseline(self) -> Optional[dict[str, tuple[float, float]]]`
- [L205](../../gui/personal_profile.py#L205) `PersonalProfile.to_dict(self) -> dict[str, Any]`
- [L209](../../gui/personal_profile.py#L209) `PersonalProfile.from_dict(cls, data: dict[str, Any]) -> 'PersonalProfile'`
- 類別 [PersonalProfileStore](../../gui/personal_profile.py#L215)
- [L221](../../gui/personal_profile.py#L221) `PersonalProfileStore.__init__(self, path: Path | None=None) -> None`
- [L226](../../gui/personal_profile.py#L226) `PersonalProfileStore.load(self) -> Optional[PersonalProfile]`
- [L238](../../gui/personal_profile.py#L238) `PersonalProfileStore.save(self, profile: PersonalProfile) -> None`
- [L248](../../gui/personal_profile.py#L248) `PersonalProfileStore.factory_reset(self) -> None`
- 類別 [PersonalBaselineCollector](../../gui/personal_profile.py#L257)
- [L264](../../gui/personal_profile.py#L264) `PersonalBaselineCollector.__init__(self, *, window_sec: float=DEFAULT_WINDOW_SEC_AUTO, min_frames: int=DEFAULT_MIN_FRAMES, now_iso: str='') -> None`
- [L291](../../gui/personal_profile.py#L291) `PersonalBaselineCollector.elapsed_sec(self) -> float`
- [L297](../../gui/personal_profile.py#L297) `PersonalBaselineCollector.progress(self) -> float`
- [L302](../../gui/personal_profile.py#L302) `PersonalBaselineCollector.is_full(self) -> bool`
- [L305](../../gui/personal_profile.py#L305) `PersonalBaselineCollector.observe(self, metrics: 'FatigueMetrics', t_now: float) -> None`
- [L334](../../gui/personal_profile.py#L334) `PersonalBaselineCollector.finalize(self, source: str='auto', profile_id: str='default') -> PersonalProfile`
- [L373](../../gui/personal_profile.py#L373) `resolve_active_baseline(manual: Optional[PersonalProfile], auto_finalized: Optional[PersonalProfile]) -> Optional[PersonalProfile]`

### `gui/platforms/__init__.py`

[原始碼](../../gui/platforms/__init__.py)；104 行。選擇作業系統整合層，不接觸共用分析程式。

本地直接依賴：`gui.platforms.base`, `gui.platforms.generic`, `gui.platforms.linux`, `gui.platforms.macos`, `gui.platforms.registry`, `gui.platforms.windows`。

- [L33](../../gui/platforms/__init__.py#L33) `get_desktop_platform_runtime(platform_name: str | None=None) -> DesktopPlatformRuntime`
- [L48](../../gui/platforms/__init__.py#L48) `installed_mediapipe_version() -> str`
- [L57](../../gui/platforms/__init__.py#L57) `validate_mediapipe_runtime(*, platform_name: str | None=None, version: str | None=None) -> str`
- [L67](../../gui/platforms/__init__.py#L67) `create_face_landmarker_base_options(mp_python: Any, model_path: str | Path, *, platform_name: str | None=None, version: str | None=None) -> Any`

### `gui/platforms/base.py`

[原始碼](../../gui/platforms/base.py)；35 行。硬體 adapter 共用的桌面平台 runtime 契約。

- 類別 [DesktopPlatformRuntime](../../gui/platforms/base.py#L17)
- [L27](../../gui/platforms/base.py#L27) `DesktopPlatformRuntime.validate_mediapipe_version(self, version: str) -> None`

### `gui/platforms/generic.py`

[原始碼](../../gui/platforms/generic.py)；12 行。未知桌面平台使用的保守 runtime fallback。

本地直接依賴：`gui.platforms.base`。


### `gui/platforms/linux.py`

[原始碼](../../gui/platforms/linux.py)；12 行。保留 Ubuntu 支援所需的 Linux runtime fallback。

本地直接依賴：`gui.platforms.base`。


### `gui/platforms/macos.py`

[原始碼](../../gui/platforms/macos.py)；19 行。macOS 專用桌面 runtime 整合設定。

本地直接依賴：`gui.platforms.base`。


### `gui/platforms/registry.py`

[原始碼](../../gui/platforms/registry.py)；127 行。五平台共用的能力與 artifact 契約。

- 類別 [UnsupportedDesktopEngineError](../../gui/platforms/registry.py#L31)
- 類別 [PlatformDescriptor](../../gui/platforms/registry.py#L36)
- [L92](../../gui/platforms/registry.py#L92) `normalize_platform_name(platform_name: str | None=None) -> str`
- [L106](../../gui/platforms/registry.py#L106) `get_platform_descriptor(platform_name: str | None=None) -> PlatformDescriptor`
- [L111](../../gui/platforms/registry.py#L111) `require_desktop_engine_support(platform_name: str | None=None) -> PlatformDescriptor`

### `gui/platforms/windows.py`

[原始碼](../../gui/platforms/windows.py)；14 行。Windows 專用桌面 runtime 整合設定。

本地直接依賴：`gui.platforms.base`。


### `gui/replay_runtime_state.py`

[原始碼](../../gui/replay_runtime_state.py)；132 行。套件／工具入口

- 類別 [ReplayRuntimeSnapshot](../../gui/replay_runtime_state.py#L12)
- 類別 [ReplayRuntimeState](../../gui/replay_runtime_state.py#L24)
- [L27](../../gui/replay_runtime_state.py#L27) `ReplayRuntimeState.__init__(self) -> None`
- [L30](../../gui/replay_runtime_state.py#L30) `ReplayRuntimeState.snapshot(self) -> ReplayRuntimeSnapshot`
- [L33](../../gui/replay_runtime_state.py#L33) `ReplayRuntimeState.restore(self, snapshot: ReplayRuntimeSnapshot) -> ReplayRuntimeSnapshot`
- [L39](../../gui/replay_runtime_state.py#L39) `ReplayRuntimeState.configure(self, *, dataset_dir: object=_UNSET, jobs: object=_UNSET, annotated: object=_UNSET) -> ReplayRuntimeSnapshot`
- [L63](../../gui/replay_runtime_state.py#L63) `ReplayRuntimeState.update_presentation(self, *, mode_label: object=_UNSET, total_count: object=_UNSET, done_count: object=_UNSET, current_text: object=_UNSET, result_text: object=_UNSET, parallel_status_text: object=_UNSET) -> ReplayRuntimeSnapshot`
- [L98](../../gui/replay_runtime_state.py#L98) `ReplayRuntimeState.begin(self, *, mode_label: str, parallel_status_text: str) -> ReplayRuntimeSnapshot`
- [L108](../../gui/replay_runtime_state.py#L108) `ReplayRuntimeState.finish_thread(self) -> ReplayRuntimeSnapshot`
- [L111](../../gui/replay_runtime_state.py#L111) `ReplayRuntimeState.reset_configuration(self) -> ReplayRuntimeSnapshot`
- [L120](../../gui/replay_runtime_state.py#L120) `ReplayRuntimeState.to_desktop_state(self) -> dict[str, object]`

### `gui/runtime_paths.py`

[原始碼](../../gui/runtime_paths.py)；104 行。解析唯讀資源與使用者可寫 runtime 資料的位置。

- [L17](../../gui/runtime_paths.py#L17) `resource_root(*, env: Mapping[str, str] | None=None, frozen: bool | None=None, meipass: PathInput | None=None, module_file: PathInput | None=None) -> Path`
- [L44](../../gui/runtime_paths.py#L44) `data_root(*, env: Mapping[str, str] | None=None, frozen: bool | None=None, platform: str | None=None, home: PathInput | None=None, module_file: PathInput | None=None) -> Path`
- [L78](../../gui/runtime_paths.py#L78) `resource_path(*parts: PathInput, **context: object) -> Path`
- [L83](../../gui/runtime_paths.py#L83) `data_path(*parts: PathInput, **context: object) -> Path`
- [L88](../../gui/runtime_paths.py#L88) `_path(value: PathInput) -> Path`
- [L92](../../gui/runtime_paths.py#L92) `_join_under_root(root: Path, parts: tuple[PathInput, ...]) -> Path`

### `gui/video_recorder.py`

[原始碼](../../gui/video_recorder.py)；219 行。Background video recorder for raw camera frames.

- 類別 [VideoRecorderWorker](../../gui/video_recorder.py#L18)
- [L24](../../gui/video_recorder.py#L24) `VideoRecorderWorker.__init__(self, frame_queue: 'queue.Queue[tuple[float, object]]', output_path: Path, fps: float=30.0) -> None`
- [L41](../../gui/video_recorder.py#L41) `VideoRecorderWorker.request_stop(self) -> None`
- [L45](../../gui/video_recorder.py#L45) `VideoRecorderWorker._find_ffmpeg() -> Optional[str]`
- [L56](../../gui/video_recorder.py#L56) `VideoRecorderWorker._start_ffmpeg(self, width: int, height: int, codec: str) -> Optional[subprocess.Popen]`
- [L94](../../gui/video_recorder.py#L94) `VideoRecorderWorker._start_opencv_writer(self, width: int, height: int) -> Optional[object]`
- [L111](../../gui/video_recorder.py#L111) `VideoRecorderWorker.run(self) -> None`
- [L120](../../gui/video_recorder.py#L120) `VideoRecorderWorker._record_frames(self) -> None`
- [L202](../../gui/video_recorder.py#L202) `VideoRecorderWorker._release_encoders(self) -> None`

### `gui/video_replay.py`

[原始碼](../../gui/video_replay.py)；1710 行。Video replay analysis (generic, with a UTA-RLDD dataset preset).

本地直接依賴：`gui.fatigue_engine`, `gui.fatigue_scorer`, `gui.fatigue_worker`, `gui.mediapipe_tuning`, `gui.metrics_recorder`, `gui.platforms`, `gui.runtime_paths`, `rppg.rppg_worker`。

- 類別 [ReplayVideo](../../gui/video_replay.py#L65)
- 類別 [ReplayVideoSummary](../../gui/video_replay.py#L73)
- 類別 [ReplayBatchResult](../../gui/video_replay.py#L126)
- [L150](../../gui/video_replay.py#L150) `parse_utarldd_label(path: Path) -> tuple[str, str]`
- [L157](../../gui/video_replay.py#L157) `discover_utarldd_videos(root: Path, *, subjects: Iterable[str] | None=None, labels: Iterable[str] | None=None) -> list[ReplayVideo]`
- [L187](../../gui/video_replay.py#L187) `_infer_label(path: Path) -> tuple[str, str]`
- [L195](../../gui/video_replay.py#L195) `discover_replay_videos(root: Path, *, subjects: Iterable[str] | None=None, labels: Iterable[str] | None=None) -> list[ReplayVideo]`
- [L242](../../gui/video_replay.py#L242) `_safe_avg(values: list[float]) -> float`
- [L246](../../gui/video_replay.py#L246) `_safe_percentile(values: list[float], percentile: float) -> float`
- [L250](../../gui/video_replay.py#L250) `_fourcc_to_str(raw: int) -> str`
- [L254](../../gui/video_replay.py#L254) `_make_camera_label(video: ReplayVideo, labeled: bool) -> str`
- [L262](../../gui/video_replay.py#L262) `_make_record_payload(*, video: ReplayVideo, timestamp: float, fps: float, width: int, height: int, codec: str, r: Any, f: Any, z: Any, labeled: bool=True) -> dict[str, Any]`
- [L379](../../gui/video_replay.py#L379) `_writer_for(path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter`
- [L385](../../gui/video_replay.py#L385) `_bgr_to_qimage(bgr: np.ndarray, *, max_width: int=0, max_height: int=0) -> QImage`
- [L410](../../gui/video_replay.py#L410) `run_replay_video(video: ReplayVideo, output_dir: Path, run_stamp: str, *, max_frames: int=0, write_annotated_video: bool=False, progress_cb: ProgressCallback | None=None, preview_frame_cb: PreviewFrameCallback | None=None, stop_requested: Callable[[], bool] | None=None, labeled: bool=True) -> ReplayVideoSummary`
- [L644](../../gui/video_replay.py#L644) `_run_replay_video_process_job(args: tuple[ReplayVideo, str, str, int, bool, bool]) -> ReplayVideoSummary`
- [L658](../../gui/video_replay.py#L658) `_failed_replay_summary(video: ReplayVideo, error: str) -> ReplayVideoSummary`
- [L669](../../gui/video_replay.py#L669) `_broken_pool_error(exc: BaseException) -> str`
- [L676](../../gui/video_replay.py#L676) `_pct(value: float) -> float`
- [L680](../../gui/video_replay.py#L680) `_num(value: float, digits: int=3) -> float`
- [L684](../../gui/video_replay.py#L684) `_rate(count: int, total: int) -> float`
- [L688](../../gui/video_replay.py#L688) `_evidence_items(summary: ReplayVideoSummary) -> list[tuple[str, float]]`
- [L704](../../gui/video_replay.py#L704) `_primary_evidence(summary: ReplayVideoSummary) -> str`
- [L718](../../gui/video_replay.py#L718) `_summary_flags(summary: ReplayVideoSummary) -> list[str]`
- [L748](../../gui/video_replay.py#L748) `_label_alignment(summary: ReplayVideoSummary, flags: list[str]) -> str`
- [L775](../../gui/video_replay.py#L775) `_recommended_action(summary: ReplayVideoSummary, flags: list[str]) -> str`
- [L800](../../gui/video_replay.py#L800) `_update_summary_diagnostics(summary: ReplayVideoSummary) -> None`
- [L808](../../gui/video_replay.py#L808) `_quick_reading(summary: ReplayVideoSummary) -> str`
- [L830](../../gui/video_replay.py#L830) `write_summary_csv(path: Path, summaries: list[ReplayVideoSummary]) -> None`
- [L948](../../gui/video_replay.py#L948) `write_full_summary_csv(path: Path, summaries: list[ReplayVideoSummary]) -> None`
- [L960](../../gui/video_replay.py#L960) `_ratio(numerator: int | float, denominator: int | float) -> float`
- [L964](../../gui/video_replay.py#L964) `_mean(values: list[float]) -> float`
- [L968](../../gui/video_replay.py#L968) `_validation_score(summary: ReplayVideoSummary) -> float`
- [L983](../../gui/video_replay.py#L983) `_trend_label(v0: float, v5: float, v10: float, *, epsilon: float) -> str`
- [L993](../../gui/video_replay.py#L993) `_validation_conclusion(rows_done: int, rows_failed: int, monotonic_rate: float, drowsy_gt_alert_rate: float) -> str`
- [L1007](../../gui/video_replay.py#L1007) `write_validation_report_csv(path: Path, summaries: list[ReplayVideoSummary]) -> None`
- [L1131](../../gui/video_replay.py#L1131) `_fmt_percent(value: float) -> str`
- [L1135](../../gui/video_replay.py#L1135) `_escape(value: object) -> str`
- [L1139](../../gui/video_replay.py#L1139) `_bar(label: str, value: float, *, max_value: float=1.0, color: str='#2563eb') -> str`
- [L1152](../../gui/video_replay.py#L1152) `_mean_float(values: list[float]) -> float`
- [L1156](../../gui/video_replay.py#L1156) `_row_float(row: dict[str, object], key: str, default: float=0.0) -> float`
- [L1168](../../gui/video_replay.py#L1168) `_flag_count(rows: list[dict[str, object]], flag: str) -> int`
- [L1177](../../gui/video_replay.py#L1177) `_summary_visual_rows(summaries: list[ReplayVideoSummary]) -> list[dict[str, object]]`
- [L1210](../../gui/video_replay.py#L1210) `_read_summary_visual_rows(summary_csv: Path) -> list[dict[str, object]]`
- [L1244](../../gui/video_replay.py#L1244) `_label_aggregates(rows: list[dict[str, object]]) -> dict[str, dict[str, float]]`
- [L1262](../../gui/video_replay.py#L1262) `_row_metrics(row: dict[str, object]) -> dict[str, float]`
- [L1276](../../gui/video_replay.py#L1276) `_render_visual_report(rows: list[dict[str, object]], *, title: str, subtitle: str='由 UTA-RLDD replay summary CSV 產生；用途是判斷目前門檻支持度、誤報/漏報風險與下一步優化方向。', labeled: bool=True) -> str`
- [L1407](../../gui/video_replay.py#L1407) `write_visual_report_html(path: Path, summaries: list[ReplayVideoSummary], *, labeled: bool=True) -> None`
- [L1425](../../gui/video_replay.py#L1425) `write_visual_report_html_from_csv(summary_csv: Path, target: Path) -> None`
- [L1436](../../gui/video_replay.py#L1436) `run_replay_batch(root: Path, *, output_dir: Path | None=None, max_videos: int=0, max_frames: int=0, subjects: Iterable[str] | None=None, labels: Iterable[str] | None=None, write_annotated_video: bool=False, jobs: int=1, progress_cb: ProgressCallback | None=None, preview_frame_cb: PreviewFrameCallback | None=None, stop_requested: Callable[[], bool] | None=None, labeled: bool=True) -> ReplayBatchResult`
- 類別 [VideoReplayWorker](../../gui/video_replay.py#L1655)
- [L1662](../../gui/video_replay.py#L1662) `VideoReplayWorker.__init__(self, dataset_root: Path, *, output_dir: Path | None=None, max_videos: int=0, max_frames: int=0, write_annotated_video: bool=False, jobs: int=1, preview_enabled: bool=True) -> None`
- [L1683](../../gui/video_replay.py#L1683) `VideoReplayWorker.request_stop(self) -> None`
- [L1686](../../gui/video_replay.py#L1686) `VideoReplayWorker._progress_cb(self, event: str, current: int, total: int, summary: ReplayVideoSummary | None) -> None`
- [L1689](../../gui/video_replay.py#L1689) `VideoReplayWorker._preview_frame_cb(self, image: QImage) -> None`
- [L1693](../../gui/video_replay.py#L1693) `VideoReplayWorker.run(self) -> None`

### `gui/web_preferences_state.py`

[原始碼](../../gui/web_preferences_state.py)；41 行。套件／工具入口

- 類別 [WebPreferencesSnapshot](../../gui/web_preferences_state.py#L7)
- 類別 [WebPreferencesState](../../gui/web_preferences_state.py#L11)
- [L14](../../gui/web_preferences_state.py#L14) `WebPreferencesState.__init__(self) -> None`
- [L17](../../gui/web_preferences_state.py#L17) `WebPreferencesState.snapshot(self) -> WebPreferencesSnapshot`
- [L20](../../gui/web_preferences_state.py#L20) `WebPreferencesState.configure(self, *, allow_lan: object) -> WebPreferencesSnapshot`
- [L26](../../gui/web_preferences_state.py#L26) `WebPreferencesState.load(self, *, web: object) -> WebPreferencesSnapshot`
- [L33](../../gui/web_preferences_state.py#L33) `WebPreferencesState.reset(self) -> WebPreferencesSnapshot`
- [L37](../../gui/web_preferences_state.py#L37) `WebPreferencesState.to_desktop_state(self) -> dict[str, bool]`
- [L40](../../gui/web_preferences_state.py#L40) `WebPreferencesState.to_settings(self) -> dict[str, bool]`

### `gui/web_server.py`

[原始碼](../../gui/web_server.py)；1113 行。Flask + Socket.IO Web Server for real-time metrics and playback.

本地直接依賴：`gui.desktop_control`, `gui.file_browser_client`。

- [L50](../../gui/web_server.py#L50) `_configured_port() -> int`
- [L62](../../gui/web_server.py#L62) `get_lan_ipv4_addresses() -> list[str]`
- [L91](../../gui/web_server.py#L91) `format_web_dashboard_urls(port: int=WEB_DASHBOARD_DEFAULT_PORT, *, allow_lan: bool=False) -> list[str]`
- [L102](../../gui/web_server.py#L102) `_build_allowed_origins(host: str, port: int) -> list[str]`
- [L119](../../gui/web_server.py#L119) `_is_local_request() -> bool`
- [L128](../../gui/web_server.py#L128) `_is_relative_to(path: Path, parent: Path) -> bool`
- [L136](../../gui/web_server.py#L136) `_parse_pagination_args(default_limit: int=_PLAYBACK_DEFAULT_LIMIT, max_limit: int=_PLAYBACK_MAX_LIMIT) -> tuple[Optional[tuple[int, int]], Optional[Any]]`
- [L161](../../gui/web_server.py#L161) `_row_get(row: dict[str, Any], columns: set[str], key: str, default: Any=None) -> Any`
- 類別 [MetricsBuffer](../../gui/web_server.py#L167)
- [L168](../../gui/web_server.py#L168) `MetricsBuffer.__init__(self, maxsize: int=300)`
- [L173](../../gui/web_server.py#L173) `MetricsBuffer.append(self, metrics: dict) -> None`
- [L177](../../gui/web_server.py#L177) `MetricsBuffer.get_all(self) -> list`
- 類別 [PlaybackManager](../../gui/web_server.py#L181)
- [L182](../../gui/web_server.py#L182) `PlaybackManager.__init__(self, recordings_dir: str | Path) -> None`
- [L192](../../gui/web_server.py#L192) `PlaybackManager._candidate_recording_dbs(self) -> list[Path]`
- [L197](../../gui/web_server.py#L197) `PlaybackManager._recordings_mtime_marker(self) -> float`
- [L213](../../gui/web_server.py#L213) `PlaybackManager._parse_filename_datetime(filename: str) -> Optional[datetime]`
- [L223](../../gui/web_server.py#L223) `PlaybackManager._read_sidecar_meta(db_file: Path) -> Optional[tuple[int, Any, Any]]`
- [L247](../../gui/web_server.py#L247) `PlaybackManager.list_recordings(self) -> list[dict]`
- [L320](../../gui/web_server.py#L320) `PlaybackManager._fmt_duration(sec: float) -> str`
- [L329](../../gui/web_server.py#L329) `PlaybackManager.get_recording_data(self, db_path: str, offset: int=0, limit: int=100) -> dict`
- [L365](../../gui/web_server.py#L365) `_safe_float(value: object) -> float`
- [L375](../../gui/web_server.py#L375) `create_app(metrics_buffer: MetricsBuffer, playback_manager: PlaybackManager, recording_manager: Optional[Any]=None, get_latest_packet: Optional[Callable]=None, allowed_origins: Optional[list[str]]=None, access_token: Optional[str]=None, control_handler: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]]=None) -> tuple[Flask, SocketIO]`
- 類別 [WebServerThread](../../gui/web_server.py#L1010)
- [L1011](../../gui/web_server.py#L1011) `WebServerThread.__init__(self, metrics_buffer: MetricsBuffer, playback_manager: PlaybackManager, recording_manager: Optional[Any]=None, get_latest_packet: Optional[Callable]=None, host: str='0.0.0.0', port: int=5000, debug: bool=False, access_token: Optional[str]=None, control_handler: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]]=None)`
- [L1059](../../gui/web_server.py#L1059) `WebServerThread.run(self) -> None`
- [L1079](../../gui/web_server.py#L1079) `WebServerThread.stop(self, *, join_timeout: float=5.0) -> bool`
- [L1085](../../gui/web_server.py#L1085) `WebServerThread.broadcast_metrics(self, metrics: dict) -> None`
- [L1099](../../gui/web_server.py#L1099) `WebServerThread.client_count(self) -> int`
- [L1102](../../gui/web_server.py#L1102) `WebServerThread.broadcast_frame(self, frame_b64: str) -> None`

### `gui/worker_safety.py`

[原始碼](../../gui/worker_safety.py)；30 行。分析 worker 共用的 fail-closed 邊界。

- [L14](../../gui/worker_safety.py#L14) `fail_closed_worker(label: str, logger: logging.Logger) -> Callable[[_F], _F]`

### `main.py`

[原始碼](../../main.py)；191 行。Launch the Tauri/Flutter shell or its hidden Python engine.

本地直接依賴：`gui.main_window`, `gui.platforms`, `gui.runtime_paths`, `gui.web_server`, `scripts.runtime_preflight`。

- [L35](../../main.py#L35) `_prefer_pyside6_qt_plugins() -> None`
- [L46](../../main.py#L46) `_missing_linux_qt_runtime_libraries() -> list[str]`
- [L62](../../main.py#L62) `_print_linux_qt_runtime_help(missing_packages: list[str]) -> None`
- [L83](../../main.py#L83) `_legacy_ui_requested() -> bool`
- [L87](../../main.py#L87) `_should_launch_tauri() -> bool`
- [L91](../../main.py#L91) `_face_landmarker_preflight_requested() -> bool`
- [L95](../../main.py#L95) `_runtime_preflight_requested() -> bool`
- [L99](../../main.py#L99) `_run_face_landmarker_preflight() -> int`
- [L125](../../main.py#L125) `_launch_tauri() -> int`
- [L142](../../main.py#L142) `main() -> int`

### `rppg/__init__.py`

[原始碼](../../rppg/__init__.py)；31 行。rPPG signal-processing package for the MediaPipe system.

本地直接依賴：`rppg.rppg_worker`。


### `rppg/adaptive_calibration.py`

[原始碼](../../rppg/adaptive_calibration.py)；821 行。線上自適應 rPPG BPM 校正：以心跳帶真值為參考，持續微調 rPPG 的 BPM offset。

本地直接依賴：`rppg.calibration`, `rppg.rppg_worker`。

- 類別 [AdaptiveCalibState](../../rppg/adaptive_calibration.py#L52)
- 類別 [OnlineBpmCalibrator](../../rppg/adaptive_calibration.py#L67)
- [L85](../../rppg/adaptive_calibration.py#L85) `OnlineBpmCalibrator.__init__(self, *, initial_offset: float=0.0, alpha: float=0.08, window_sec: float=45.0, min_pairs: int=6, max_abs_offset_bpm: float=25.0, update_min_interval_sec: float=2.0, converge_residual_bpm: float=3.0, diverge_residual_bpm: float=8.0, max_pair_bpm_gap: float=40.0, quality_gates: Mapping[str, Any] | None=None) -> None`
- [L118](../../rppg/adaptive_calibration.py#L118) `OnlineBpmCalibrator.observe(self, now: float, belt_bpm: float, belt_contact_ok: bool, belt_fresh: bool, rppg_sample: Mapping[str, Any]) -> bool`
- [L155](../../rppg/adaptive_calibration.py#L155) `OnlineBpmCalibrator._prune(self, now: float) -> None`
- [L160](../../rppg/adaptive_calibration.py#L160) `OnlineBpmCalibrator._maybe_update(self, now: float) -> bool`
- [L175](../../rppg/adaptive_calibration.py#L175) `OnlineBpmCalibrator._raw_residual(self) -> float`
- [L180](../../rppg/adaptive_calibration.py#L180) `OnlineBpmCalibrator._corrected_residual(self) -> float`
- [L187](../../rppg/adaptive_calibration.py#L187) `OnlineBpmCalibrator._confidence(self) -> str`
- [L203](../../rppg/adaptive_calibration.py#L203) `OnlineBpmCalibrator.offset(self) -> float`
- [L206](../../rppg/adaptive_calibration.py#L206) `OnlineBpmCalibrator.state(self) -> AdaptiveCalibState`
- [L236](../../rppg/adaptive_calibration.py#L236) `OnlineBpmCalibrator.live_version(self, version_id: str='v_adaptive_live', name: str='自適應校準（即時）') -> CalibrationVersion`
- [L251](../../rppg/adaptive_calibration.py#L251) `_clamp_abs(value: float, limit: float) -> float`
- 類別 [RppgParamAbVerdict](../../rppg/adaptive_calibration.py#L262)
- 類別 [RppgParamAbEvaluator](../../rppg/adaptive_calibration.py#L273)
- [L288](../../rppg/adaptive_calibration.py#L288) `RppgParamAbEvaluator.__init__(self, *, window_sec: float=45.0, min_pairs: int=6, improve_margin_bpm: float=1.5, worsen_margin_bpm: float=2.0, confirm_windows: int=3, max_pair_bpm_gap: float=40.0) -> None`
- [L309](../../rppg/adaptive_calibration.py#L309) `RppgParamAbEvaluator.observe(self, t_now: float, belt_bpm: float, rppg_current_bpm: float, rppg_candidate_bpm: float) -> None`
- [L329](../../rppg/adaptive_calibration.py#L329) `RppgParamAbEvaluator.evaluate(self) -> RppgParamAbVerdict`
- [L362](../../rppg/adaptive_calibration.py#L362) `RppgParamAbEvaluator.reset(self) -> None`
- [L371](../../rppg/adaptive_calibration.py#L371) `recompute_raw_bpm_from_roi_windows(roi_windows: Mapping[str, RoiWindow], roi_weights: Mapping[str, float], *, min_samples: int=64, min_duration_sec: float=6.0) -> float | None`
- 類別 [RppgParamCoordinatorState](../../rppg/adaptive_calibration.py#L530)
- [L541](../../rppg/adaptive_calibration.py#L541) `propose_roi_weight_candidate(current_weights: Mapping[str, float], per_roi_residual_hint: Mapping[str, float], *, step: float=0.05) -> dict[str, float]`
- 類別 [RppgParamCoordinator](../../rppg/adaptive_calibration.py#L638)
- [L683](../../rppg/adaptive_calibration.py#L683) `RppgParamCoordinator.__init__(self, *, evaluator: Optional[RppgParamAbEvaluator]=None, step_size: float=0.05, cooldown_sec: float=120.0) -> None`
- [L701](../../rppg/adaptive_calibration.py#L701) `RppgParamCoordinator.phase(self) -> str`
- [L705](../../rppg/adaptive_calibration.py#L705) `RppgParamCoordinator.candidate_roi_weights(self) -> Optional[dict[str, float]]`
- [L708](../../rppg/adaptive_calibration.py#L708) `RppgParamCoordinator.state(self) -> RppgParamCoordinatorState`
- [L718](../../rppg/adaptive_calibration.py#L718) `RppgParamCoordinator.tick(self, t_now: float, calib_state: AdaptiveCalibState, current_roi_weights: Mapping[str, float], per_roi_residual_hint: Optional[Mapping[str, float]]=None) -> Optional[dict[str, float]]`
- [L762](../../rppg/adaptive_calibration.py#L762) `RppgParamCoordinator.observe_ab(self, t_now: float, belt_bpm: float, rppg_current_bpm: float, rppg_candidate_bpm: float) -> Optional[RppgParamAbVerdict]`
- [L787](../../rppg/adaptive_calibration.py#L787) `RppgParamCoordinator._enter_cooldown(self, t_now: float) -> None`
- [L793](../../rppg/adaptive_calibration.py#L793) `RppgParamCoordinator.reset(self) -> None`

### `rppg/belt_truth_capture.py`

[原始碼](../../rppg/belt_truth_capture.py)；224 行。belt-truth 同步錄製（P6b-4）：離線驗證 rPPG ROI 權重候選的錄製格式與 I/O。

本地直接依賴：`gui.runtime_paths`。

- 類別 [BeltTruthCaptureRecord](../../rppg/belt_truth_capture.py#L54)
- 類別 [BeltTruthCaptureWriter](../../rppg/belt_truth_capture.py#L68)
- [L77](../../rppg/belt_truth_capture.py#L77) `BeltTruthCaptureWriter.__init__(self, path: str | Path, belt_bpm_provider: Optional[Callable[[], Optional[float]]]=None) -> None`
- [L90](../../rppg/belt_truth_capture.py#L90) `BeltTruthCaptureWriter.path(self) -> Path`
- [L94](../../rppg/belt_truth_capture.py#L94) `BeltTruthCaptureWriter.record_count(self) -> int`
- [L97](../../rppg/belt_truth_capture.py#L97) `BeltTruthCaptureWriter._sample_belt_bpm(self) -> Optional[float]`
- [L115](../../rppg/belt_truth_capture.py#L115) `BeltTruthCaptureWriter.record(self, t: float, roi_means: Mapping[str, Sequence[float]]) -> None`
- [L140](../../rppg/belt_truth_capture.py#L140) `BeltTruthCaptureWriter.close(self) -> None`
- [L149](../../rppg/belt_truth_capture.py#L149) `BeltTruthCaptureWriter.__enter__(self) -> 'BeltTruthCaptureWriter'`
- [L152](../../rppg/belt_truth_capture.py#L152) `BeltTruthCaptureWriter.__exit__(self, *exc_info: object) -> None`
- [L156](../../rppg/belt_truth_capture.py#L156) `default_capture_path(base_dir: Optional[str | Path]=None) -> Path`
- [L164](../../rppg/belt_truth_capture.py#L164) `load_belt_truth_capture(path: str | Path) -> list[BeltTruthCaptureRecord]`

### `rppg/calibration.py`

[原始碼](../../rppg/calibration.py)；576 行。rPPG BPM calibration store, live feed, and apply helpers.

本地直接依賴：`gui.runtime_paths`。

- 類別 [CalibrationParams](../../rppg/calibration.py#L54)
- 類別 [CalibrationVersion](../../rppg/calibration.py#L65)
- [L76](../../rppg/calibration.py#L76) `CalibrationVersion.to_dict(self) -> dict[str, Any]`
- [L100](../../rppg/calibration.py#L100) `CalibrationVersion.from_dict(cls, data: Mapping[str, Any]) -> 'CalibrationVersion'`
- [L121](../../rppg/calibration.py#L121) `CalibrationVersion.is_identity(self) -> bool`
- [L130](../../rppg/calibration.py#L130) `origin_version() -> CalibrationVersion`
- [L142](../../rppg/calibration.py#L142) `apply_bpm_calibration(bpm: float, version: CalibrationVersion | Mapping[str, Any] | None) -> float`
- [L155](../../rppg/calibration.py#L155) `apply_calibration_dict(metrics: Mapping[str, Any], version: CalibrationVersion) -> dict[str, Any]`
- [L167](../../rppg/calibration.py#L167) `apply_calibration_to_metrics(metrics: Any, version: CalibrationVersion | None) -> Any`
- [L184](../../rppg/calibration.py#L184) `effective_bpm(metrics: Any) -> float`
- [L194](../../rppg/calibration.py#L194) `calibration_rppg_bpm(sample: Mapping[str, Any]) -> float`
- [L203](../../rppg/calibration.py#L203) `rppg_sample_quality_ok(sample: Mapping[str, Any], gates: Mapping[str, Any] | None=None) -> bool`
- [L219](../../rppg/calibration.py#L219) `compute_offset_from_residuals(residuals: list[float]) -> float`
- [L225](../../rppg/calibration.py#L225) `compute_mae(pairs: list[tuple[float, float]], offset: float=0.0) -> float`
- 類別 [WindowResidual](../../rppg/calibration.py#L233)
- 類別 [CalibrationSessionAnalyzer](../../rppg/calibration.py#L243)
- [L246](../../rppg/calibration.py#L246) `CalibrationSessionAnalyzer.__init__(self, window_sec: float=30.0, warmup_sec: float=30.0, quality_gates: Mapping[str, Any] | None=None) -> None`
- [L262](../../rppg/calibration.py#L262) `CalibrationSessionAnalyzer.watch_sample_count(self) -> int`
- [L265](../../rppg/calibration.py#L265) `CalibrationSessionAnalyzer.watch_time_range(self) -> tuple[float | None, float | None]`
- [L271](../../rppg/calibration.py#L271) `CalibrationSessionAnalyzer.add_watch(self, received_at: float, bpm: float) -> None`
- [L275](../../rppg/calibration.py#L275) `CalibrationSessionAnalyzer.add_rppg(self, received_at: float, sample: Mapping[str, Any]) -> None`
- [L280](../../rppg/calibration.py#L280) `CalibrationSessionAnalyzer._median_watch(self, start: float, end: float) -> float | None`
- [L284](../../rppg/calibration.py#L284) `CalibrationSessionAnalyzer._median_rppg(self, start: float, end: float) -> tuple[float | None, dict[str, Any] | None, str]`
- [L296](../../rppg/calibration.py#L296) `CalibrationSessionAnalyzer.analyze(self, start_ts: float, end_ts: float) -> list[WindowResidual]`
- [L325](../../rppg/calibration.py#L325) `CalibrationSessionAnalyzer.estimate(self, start_ts: float, end_ts: float) -> dict[str, Any]`
- 類別 [CalibrationVersionStore](../../rppg/calibration.py#L343)
- [L346](../../rppg/calibration.py#L346) `CalibrationVersionStore.__init__(self, root: Path | None=None) -> None`
- [L354](../../rppg/calibration.py#L354) `CalibrationVersionStore.ensure_layout(self) -> None`
- [L375](../../rppg/calibration.py#L375) `CalibrationVersionStore.reload(self) -> None`
- [L385](../../rppg/calibration.py#L385) `CalibrationVersionStore.list_versions(self) -> list[dict[str, Any]]`
- [L390](../../rppg/calibration.py#L390) `CalibrationVersionStore.get_active_version_id(self) -> str`
- [L394](../../rppg/calibration.py#L394) `CalibrationVersionStore.get_version(self, version_id: str | None=None) -> CalibrationVersion`
- [L411](../../rppg/calibration.py#L411) `CalibrationVersionStore.get_active_version(self) -> CalibrationVersion`
- [L414](../../rppg/calibration.py#L414) `CalibrationVersionStore.set_active_version(self, version_id: str) -> CalibrationVersion`
- [L424](../../rppg/calibration.py#L424) `CalibrationVersionStore.save_new_version(self, name: str, offset_bpm: float, *, note: str='', session: Mapping[str, Any] | None=None, metrics: Mapping[str, Any] | None=None, scale: float=1.0, rppg_params: Mapping[str, Any] | None=None) -> CalibrationVersion`
- [L461](../../rppg/calibration.py#L461) `CalibrationVersionStore.delete_version(self, version_id: str) -> None`
- [L482](../../rppg/calibration.py#L482) `CalibrationVersionStore._find_entry(self, version_id: str) -> dict[str, Any] | None`
- [L489](../../rppg/calibration.py#L489) `CalibrationVersionStore._read_json(path: Path) -> dict[str, Any]`
- [L494](../../rppg/calibration.py#L494) `CalibrationVersionStore._write_json(path: Path, data: Mapping[str, Any]) -> None`
- [L511](../../rppg/calibration.py#L511) `write_live_feed(metrics: Any, *, enabled: bool | None=None) -> None`
- [L533](../../rppg/calibration.py#L533) `read_live_feed(max_age_sec: float=5.0) -> dict[str, Any] | None`
- [L549](../../rppg/calibration.py#L549) `set_live_feed_enabled(enabled: bool) -> None`
- [L558](../../rppg/calibration.py#L558) `is_live_feed_enabled() -> bool`
- [L562](../../rppg/calibration.py#L562) `metrics_to_feed_dict(metrics: Any) -> dict[str, Any]`
- [L570](../../rppg/calibration.py#L570) `_now_iso() -> str`
- [L574](../../rppg/calibration.py#L574) `_new_version_id() -> str`

### `rppg/calibration_watch.py`

[原始碼](../../rppg/calibration_watch.py)；94 行。心率參考樣本容器：BLE 心跳帶樣本的執行緒安全 hub 與樣本型別。

- 類別 [WatchSample](../../rppg/calibration_watch.py#L15)
- [L28](../../rppg/calibration_watch.py#L28) `WatchSample.__init__(self, received_at: float, bpm: int, ts_ms: int, interval_ms: int, ax: float | None=None, ay: float | None=None, az: float | None=None, motion_level: float | None=None, rr_intervals_ms: 'tuple[float, ...] | list[float] | None'=None) -> None`
- [L52](../../rppg/calibration_watch.py#L52) `WatchSample.has_imu(self) -> bool`
- [L56](../../rppg/calibration_watch.py#L56) `WatchSample.has_rr(self) -> bool`
- 類別 [WatchHrHub](../../rppg/calibration_watch.py#L60)
- [L63](../../rppg/calibration_watch.py#L63) `WatchHrHub.__init__(self) -> None`
- [L69](../../rppg/calibration_watch.py#L69) `WatchHrHub.add(self, sample: WatchSample) -> None`
- [L75](../../rppg/calibration_watch.py#L75) `WatchHrHub.latest(self) -> WatchSample | None`
- [L79](../../rppg/calibration_watch.py#L79) `WatchHrHub.snapshot(self) -> list[WatchSample]`
- [L83](../../rppg/calibration_watch.py#L83) `WatchHrHub.clear(self) -> None`
- [L89](../../rppg/calibration_watch.py#L89) `WatchHrHub.is_connected(self, stale_multiplier: float=6.0) -> bool`

### `rppg/demo_rppg_live.py`

[原始碼](../../rppg/demo_rppg_live.py)；874 行。Live rPPG demo: MediaPipe Face Landmarker ROIs + POS pulse + HRV-style metrics.

本地直接依賴：`gui.mediapipe_tuning`, `gui.platforms`, `rppg.rppg_worker`。

- [L75](../../rppg/demo_rppg_live.py#L75) `_video_capture_single(index: int, backend: str) -> tuple[Optional[Any], str]`
- [L93](../../rppg/demo_rppg_live.py#L93) `open_video_capture(index: int, backend: str='auto') -> tuple[Optional[Any], str]`
- [L118](../../rppg/demo_rppg_live.py#L118) `_dshow_names_pygrabber() -> list[str]`
- [L130](../../rppg/demo_rppg_live.py#L130) `list_camera_devices(backend: str='auto') -> list[tuple[int, str]]`
- [L155](../../rppg/demo_rppg_live.py#L155) `resolve_camera_label(index: int, devices: Optional[list[tuple[int, str]]]=None, backend: str='auto') -> str`
- [L168](../../rppg/demo_rppg_live.py#L168) `print_camera_list(backend: str='auto') -> None`
- [L181](../../rppg/demo_rppg_live.py#L181) `pick_camera_interactive(backend: str='auto') -> int`
- [L207](../../rppg/demo_rppg_live.py#L207) `_landmark_xy(lm: Any, idx: int, w: int, h: int) -> tuple[int, int]`
- [L214](../../rppg/demo_rppg_live.py#L214) `roi_mean_bgr(frame_bgr: np.ndarray, lm: Any, indices: list[int], blur_ksize: int=5, transform_matrix: Any | None=None) -> Optional[tuple[float, float, float]]`
- [L239](../../rppg/demo_rppg_live.py#L239) `pos_pulse(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray`
- [L253](../../rppg/demo_rppg_live.py#L253) `butter_bandpass(sig: np.ndarray, fs: float, low: float, high: float, order: int=3)`
- [L268](../../rppg/demo_rppg_live.py#L268) `welch_peak_hz(sig: np.ndarray, fs: float) -> tuple[float, np.ndarray, np.ndarray]`
- [L285](../../rppg/demo_rppg_live.py#L285) `compute_sqi(sig: np.ndarray, fs: float) -> float`
- [L302](../../rppg/demo_rppg_live.py#L302) `ibi_from_peaks(sig: np.ndarray, fs: float) -> np.ndarray`
- [L313](../../rppg/demo_rppg_live.py#L313) `hrv_time_domain(ibis_ms: np.ndarray) -> tuple[float, float]`
- [L322](../../rppg/demo_rppg_live.py#L322) `ibi_artifact_ratio(ibis_ms: np.ndarray) -> float`
- [L329](../../rppg/demo_rppg_live.py#L329) `lf_hf_from_tachogram(ibis_ms: np.ndarray, fs_resample: float=4.0) -> float`
- [L358](../../rppg/demo_rppg_live.py#L358) `_safe_welch_params(n: int, *, max_nperseg: int, min_nperseg: int=32) -> tuple[int, int] | None`
- [L368](../../rppg/demo_rppg_live.py#L368) `stress_heuristic(lf_hf: float, rmssd: float) -> tuple[float, str]`
- [L385](../../rppg/demo_rppg_live.py#L385) `hrv_confidence(n_ibis: int, sqi: float, art_ratio: float) -> str`
- 類別 [Metrics](../../rppg/demo_rppg_live.py#L394)
- 類別 [RppgDemo](../../rppg/demo_rppg_live.py#L417)
- [L418](../../rppg/demo_rppg_live.py#L418) `RppgDemo.__init__(self, buffer_sec: float=12.0, target_fps: float=30.0, hrv_window_sec: float=30.0)`
- [L436](../../rppg/demo_rppg_live.py#L436) `RppgDemo.reset(self) -> None`
- [L445](../../rppg/demo_rppg_live.py#L445) `RppgDemo.push(self, t: float, r: float, g: float, b: float) -> None`
- [L451](../../rppg/demo_rppg_live.py#L451) `RppgDemo._trim_buffer(self, t_now: float) -> None`
- [L460](../../rppg/demo_rppg_live.py#L460) `RppgDemo.estimate_fs(self) -> float`
- [L470](../../rppg/demo_rppg_live.py#L470) `RppgDemo.compute(self, t_now: float, frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None=None, roi_valid_count: int | None=None) -> Metrics`
- [L596](../../rppg/demo_rppg_live.py#L596) `draw_metrics_panel(canvas: np.ndarray, m: Metrics, x0: int, panel_w: int, *, fps_live: float=0.0, fps_nominal: float=0.0, camera_idx: int=0, camera_name: str='') -> None`
- [L663](../../rppg/demo_rppg_live.py#L663) `draw_rois(frame: np.ndarray, lm: Any, transform_matrix: Any | None=None) -> None`
- [L676](../../rppg/demo_rppg_live.py#L676) `draw_capture_overlay(frame: np.ndarray, *, camera_idx: int, camera_name: str, fps_live: float, fps_nominal: float) -> None`
- [L699](../../rppg/demo_rppg_live.py#L699) `run(camera_id: int, camera_label: str, backend: str='auto') -> None`
- [L827](../../rppg/demo_rppg_live.py#L827) `main() -> None`

### `rppg/hr_belt_ble.py`

[原始碼](../../rppg/hr_belt_ble.py)；670 行。BLE 心跳帶（R+2.0 等標準 Heart Rate Service 裝置）協定解析與連線管理。

本地直接依賴：`gui.runtime_paths`, `rppg.calibration_watch`。

- 類別 [HrBeltConfig](../../rppg/hr_belt_ble.py#L75)
- [L94](../../rppg/hr_belt_ble.py#L94) `_validated_float(value: Any, default: float, lo: float, hi: float, label: str) -> float`
- [L106](../../rppg/hr_belt_ble.py#L106) `_validated_bool(value: Any, default: bool, label: str) -> bool`
- [L114](../../rppg/hr_belt_ble.py#L114) `load_hr_belt_config(path: Path | str | None=None) -> HrBeltConfig`
- 類別 [HeartRateMeasurement](../../rppg/hr_belt_ble.py#L167)
- [L178](../../rppg/hr_belt_ble.py#L178) `parse_heart_rate_measurement(data: bytes | bytearray | memoryview) -> HeartRateMeasurement`
- [L231](../../rppg/hr_belt_ble.py#L231) `parse_battery_level(data: bytes | bytearray | memoryview) -> int | None`
- [L242](../../rppg/hr_belt_ble.py#L242) `body_sensor_location_label(data: bytes | bytearray | memoryview) -> str`
- [L250](../../rppg/hr_belt_ble.py#L250) `measurement_to_watch_sample(measurement: HeartRateMeasurement, received_at: float | None=None) -> WatchSample | None`
- [L276](../../rppg/hr_belt_ble.py#L276) `pick_heart_rate_device(candidates: Iterable[tuple[Any, Any]], *, name_prefix: str=DEFAULT_NAME_PREFIX, address: str='') -> Any | None`
- 類別 [HrBeltStatus](../../rppg/hr_belt_ble.py#L316)
- [L336](../../rppg/hr_belt_ble.py#L336) `hr_is_stale(status: HrBeltStatus, now: float | None=None, max_age_sec: float=HR_STALE_AFTER_SEC) -> bool`
- 類別 [HrBeltBleClient](../../rppg/hr_belt_ble.py#L352)
- [L360](../../rppg/hr_belt_ble.py#L360) `HrBeltBleClient.__init__(self, hub: WatchHrHub, *, name_prefix: str=DEFAULT_NAME_PREFIX, address: str='', scan_timeout: float=6.0, reconnect_delay: float=3.0, on_sample: Callable[[WatchSample], None] | None=None) -> None`
- [L388](../../rppg/hr_belt_ble.py#L388) `HrBeltBleClient.running(self) -> bool`
- [L391](../../rppg/hr_belt_ble.py#L391) `HrBeltBleClient.status(self) -> HrBeltStatus`
- [L395](../../rppg/hr_belt_ble.py#L395) `HrBeltBleClient.start(self) -> str`
- [L413](../../rppg/hr_belt_ble.py#L413) `HrBeltBleClient.stop(self, join_timeout: float=5.0) -> None`
- [L449](../../rppg/hr_belt_ble.py#L449) `HrBeltBleClient._set_status(self, **changes: Any) -> None`
- [L455](../../rppg/hr_belt_ble.py#L455) `HrBeltBleClient._run(self) -> None`
- [L478](../../rppg/hr_belt_ble.py#L478) `HrBeltBleClient._wait_stop(self, timeout: float) -> bool`
- [L487](../../rppg/hr_belt_ble.py#L487) `HrBeltBleClient._main(self) -> None`
- [L547](../../rppg/hr_belt_ble.py#L547) `HrBeltBleClient._discover(self, scanner_cls: Any) -> Any | None`
- [L579](../../rppg/hr_belt_ble.py#L579) `HrBeltBleClient._prime_connection(self, client: Any) -> None`
- [L609](../../rppg/hr_belt_ble.py#L609) `HrBeltBleClient._on_hr_notification(self, _characteristic: Any, data: bytearray) -> None`
- [L641](../../rppg/hr_belt_ble.py#L641) `HrBeltBleClient._on_battery_notification(self, _characteristic: Any, data: bytearray) -> None`

### `rppg/rppg_hrv_engine.py`

[原始碼](../../rppg/rppg_hrv_engine.py)；225 行。Adaptive MAD-based rPPG HRV engine for bandpassed POS pulse waveforms.

- 類別 [RppgHrvResult](../../rppg/rppg_hrv_engine.py#L26)
- [L40](../../rppg/rppg_hrv_engine.py#L40) `_peak_min_distance(fs: float, bpm_hint: float=0.0) -> int`
- [L48](../../rppg/rppg_hrv_engine.py#L48) `_adaptive_peaks(pulse_signal: np.ndarray, fs: float, *, bpm_hint: float=0.0) -> np.ndarray`
- [L67](../../rppg/rppg_hrv_engine.py#L67) `_clean_ibis_mad(ibi_ms: np.ndarray) -> tuple[np.ndarray, float]`
- [L84](../../rppg/rppg_hrv_engine.py#L84) `_lf_hf_from_clean_ibis(clean_ibi_ms: np.ndarray) -> float`
- [L116](../../rppg/rppg_hrv_engine.py#L116) `hrv_confidence_rppg(n_ibis: int, spectral_sqi: float, art_ratio: float, *, rmssd: float=0.0, sdnn: float=0.0, ibi_sqi: float=0.0) -> str`
- [L141](../../rppg/rppg_hrv_engine.py#L141) `compute_rppg_hrv_from_pulse(pulse_signal: np.ndarray, fs: float, *, min_window_sec: float=30.0, bpm_hint: float=0.0, **_kwargs: Any) -> RppgHrvResult`

### `rppg/rppg_worker.py`

[原始碼](../../rppg/rppg_worker.py)；1892 行。Production rPPG engine for rPPG V2 GUI.

本地直接依賴：`gui.frame_queue`, `gui.mediapipe_tuning`, `gui.model_assets`, `gui.platforms`, `gui.runtime_paths`, `gui.worker_safety`, `rppg.adaptive_calibration`, `rppg.belt_truth_capture`, `rppg.rppg_hrv_engine`。

- [L89](../../rppg/rppg_worker.py#L89) `resolve_roi_weights_override(rppg_params: Mapping[str, Any] | None) -> Optional[dict[str, float]]`
- [L155](../../rppg/rppg_worker.py#L155) `_project_fractions_onto_bounds(fractions: dict[str, float], lo: float, hi: float) -> dict[str, float]`
- [L205](../../rppg/rppg_worker.py#L205) `apply_roi_weights_override(tuning: MediaPipeTuning, override: Optional[dict[str, float]]) -> MediaPipeTuning`
- [L221](../../rppg/rppg_worker.py#L221) `resolve_effective_rppg_tuning(tuning: MediaPipeTuning, explicit_override: Optional[dict[str, float]], calibration_loader: Optional[Callable[[], object]]) -> MediaPipeTuning`
- 類別 [RppgMetrics](../../rppg/rppg_worker.py#L275)
- [L320](../../rppg/rppg_worker.py#L320) `_clamp(x: float, a: float=0.0, b: float=1.0) -> float`
- [L324](../../rppg/rppg_worker.py#L324) `_lm_xy(lm: Any, idx: int, w: int, h: int) -> tuple[int, int]`
- [L329](../../rppg/rppg_worker.py#L329) `_dist(p1: tuple[float, float], p2: tuple[float, float]) -> float`
- [L333](../../rppg/rppg_worker.py#L333) `_lm_xyf(lm: Any, idx: int, w: int, h: int) -> tuple[float, float]`
- [L338](../../rppg/rppg_worker.py#L338) `_face_diag_px(lm: Any, w: int, h: int) -> float`
- [L346](../../rppg/rppg_worker.py#L346) `_face_center_px(lm: Any, w: int, h: int) -> tuple[float, float]`
- [L353](../../rppg/rppg_worker.py#L353) `_polygon_area(pts: np.ndarray) -> float`
- [L361](../../rppg/rppg_worker.py#L361) `_rotate_points(pts: np.ndarray, center: tuple[float, float], angle_deg: float) -> np.ndarray`
- [L376](../../rppg/rppg_worker.py#L376) `_pose_normalized_points(pts: np.ndarray, center: tuple[float, float], yaw_deg: float, pitch_deg: float, strength: float) -> np.ndarray`
- 類別 [RoiGeometryTracker](../../rppg/rppg_worker.py#L396)
- [L399](../../rppg/rppg_worker.py#L399) `RoiGeometryTracker.__init__(self) -> None`
- [L410](../../rppg/rppg_worker.py#L410) `RoiGeometryTracker.reset(self) -> None`
- [L421](../../rppg/rppg_worker.py#L421) `RoiGeometryTracker.begin_frame(self) -> None`
- [L426](../../rppg/rppg_worker.py#L426) `RoiGeometryTracker.update_landmarks(self, lm: Any, w: int, h: int) -> None`
- [L435](../../rppg/rppg_worker.py#L435) `RoiGeometryTracker.smooth_roi(self, name: str, pts: np.ndarray, face_diag: float, tuning: MediaPipeTuning) -> np.ndarray`
- [L458](../../rppg/rppg_worker.py#L458) `RoiGeometryTracker.update_roi_area(self, areas_px: list[float], frame_area: float, tuning: MediaPipeTuning) -> None`
- [L469](../../rppg/rppg_worker.py#L469) `roi_points(frame_bgr: np.ndarray, lm: Any, indices: list[int], name: str, transform_matrix: Any | None=None, tracker: RoiGeometryTracker | None=None, tuning: MediaPipeTuning | None=None) -> np.ndarray`
- [L504](../../rppg/rppg_worker.py#L504) `roi_mean_from_points(frame_bgr: np.ndarray, pts: np.ndarray, blur_ksize: int=5) -> Optional[tuple[float, float, float]]`
- [L522](../../rppg/rppg_worker.py#L522) `roi_obstruction_score_from_points(frame_bgr: np.ndarray, pts: np.ndarray, tuning: MediaPipeTuning | None=None) -> float`
- [L546](../../rppg/rppg_worker.py#L546) `collect_rppg_roi_sample(frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None, tracker: RoiGeometryTracker, tuning: MediaPipeTuning) -> tuple[Optional[tuple[float, float, float]], dict[str, float], int]`
- [L590](../../rppg/rppg_worker.py#L590) `collect_rppg_roi_sample_with_means(frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None, tracker: RoiGeometryTracker, tuning: MediaPipeTuning, *, weighted_mix: bool=False) -> tuple[Optional[tuple[float, float, float]], dict[str, float], int, dict[str, tuple[float, float, float]]]`
- [L687](../../rppg/rppg_worker.py#L687) `_pose_from_matrix(transform_matrix: Any | None, lm: Any, w: int, h: int) -> tuple[float, float, float, float]`
- [L733](../../rppg/rppg_worker.py#L733) `_roi_weights_from_pose(roll_deg: float, yaw_deg: float, pitch_deg: float, lm: Any, w: int, h: int, tuning: MediaPipeTuning | None=None) -> dict[str, float]`
- [L772](../../rppg/rppg_worker.py#L772) `_face_quality_from_pose(roll_deg: float, yaw_deg: float, pitch_deg: float, face_area_ratio: float, face_motion_norm: float, roi_valid_ratio: float, tuning: MediaPipeTuning | None=None) -> float`
- [L804](../../rppg/rppg_worker.py#L804) `roi_obstruction_score(frame_bgr: np.ndarray, lm: Any, indices: list[int], tuning: MediaPipeTuning | None=None) -> float`
- [L815](../../rppg/rppg_worker.py#L815) `roi_mean_bgr(frame_bgr: np.ndarray, lm: Any, indices: list[int], blur_ksize: int=5, transform_matrix: Any | None=None, tuning: MediaPipeTuning | None=None) -> Optional[tuple[float, float, float]]`
- [L829](../../rppg/rppg_worker.py#L829) `draw_rois(frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None=None, tracker: RoiGeometryTracker | None=None, tuning: MediaPipeTuning | None=None) -> None`
- [L844](../../rppg/rppg_worker.py#L844) `pos_pulse(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray`
- [L855](../../rppg/rppg_worker.py#L855) `butter_bandpass(sig: np.ndarray, fs: float, low: float=0.65, high: float=3.7, order: int=3) -> np.ndarray`
- [L879](../../rppg/rppg_worker.py#L879) `welch_peak_hz(sig: np.ndarray, fs: float) -> tuple[float, np.ndarray, np.ndarray]`
- [L913](../../rppg/rppg_worker.py#L913) `_safe_welch_params(n: int, *, max_nperseg: int, min_nperseg: int=32) -> tuple[int, int] | None`
- [L924](../../rppg/rppg_worker.py#L924) `compute_sqi(sig: np.ndarray, fs: float) -> float`
- [L943](../../rppg/rppg_worker.py#L943) `ibi_from_peaks(sig: np.ndarray, fs: float, bpm_hint: float=0.0) -> np.ndarray`
- [L962](../../rppg/rppg_worker.py#L962) `validate_ibi_intervals(ibis_ms: np.ndarray) -> np.ndarray`
- [L998](../../rppg/rppg_worker.py#L998) `hrv_time_domain(ibis_ms: np.ndarray) -> tuple[float, float]`
- [L1007](../../rppg/rppg_worker.py#L1007) `ibi_artifact_ratio(ibis_ms: np.ndarray, clean_ibis_ms: Optional[np.ndarray]=None) -> float`
- [L1016](../../rppg/rppg_worker.py#L1016) `lf_hf_from_tachogram(ibis_ms: np.ndarray, fs_resample: float=4.0) -> float`
- [L1040](../../rppg/rppg_worker.py#L1040) `stress_heuristic(lf_hf: float, rmssd: float) -> tuple[float, str]`
- [L1055](../../rppg/rppg_worker.py#L1055) `hrv_confidence(n_ibis: int, sqi: float, art_ratio: float) -> str`
- [L1063](../../rppg/rppg_worker.py#L1063) `resolve_rppg_hrv_metrics(pulse_raw: np.ndarray, filt: np.ndarray, fs: float, sqi: float, *, hrv_window_sec: float=30.0, bpm_hint: float=0.0) -> tuple[float, float, float, float, str]`
- [L1108](../../rppg/rppg_worker.py#L1108) `ensure_face_model(models_dir: Path, status_cb: Optional[Callable[[str], None]]=None) -> Path`
- 類別 [RppgEngine](../../rppg/rppg_worker.py#L1142)
- [L1157](../../rppg/rppg_worker.py#L1157) `RppgEngine.__init__(self, buffer_sec: float=12.0, target_fps: float=30.0, hrv_window_sec: float=30.0) -> None`
- [L1195](../../rppg/rppg_worker.py#L1195) `RppgEngine.reset(self) -> None`
- [L1215](../../rppg/rppg_worker.py#L1215) `RppgEngine.push(self, t: float, r: float, g: float, b: float) -> None`
- [L1219](../../rppg/rppg_worker.py#L1219) `RppgEngine.push_roi_means(self, t: float, roi_means: dict[str, tuple[float, float, float]]) -> None`
- [L1238](../../rppg/rppg_worker.py#L1238) `RppgEngine.get_roi_window(self, name: str, window_sec: float, t_now: float | None=None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]`
- [L1265](../../rppg/rppg_worker.py#L1265) `RppgEngine._trim(self, t_now: float) -> None`
- [L1272](../../rppg/rppg_worker.py#L1272) `RppgEngine._fs(self) -> float`
- [L1281](../../rppg/rppg_worker.py#L1281) `RppgEngine._accept_bpm_candidate(self, t_now: float, raw_bpm: float) -> float`
- [L1330](../../rppg/rppg_worker.py#L1330) `RppgEngine._stabilize_bpm(self, t_now: float, raw_bpm: float) -> float`
- [L1333](../../rppg/rppg_worker.py#L1333) `RppgEngine.compute(self, t_now: float, frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None=None, roi_valid_count: int | None=None, roi_weights: dict[str, float] | None=None, roi_tracker: RoiGeometryTracker | None=None, tuning: MediaPipeTuning | None=None) -> RppgMetrics`
- 類別 [RppgWorker](../../rppg/rppg_worker.py#L1579)
- [L1603](../../rppg/rppg_worker.py#L1603) `RppgWorker.__init__(self, frame_queue: 'queue.Queue[tuple[float, np.ndarray]]', target_fps: float=30.0, buffer_sec: float=12.0, calibration_loader: Optional[Callable[[], object]]=None) -> None`
- [L1632](../../rppg/rppg_worker.py#L1632) `RppgWorker.request_stop(self) -> None`
- [L1635](../../rppg/rppg_worker.py#L1635) `RppgWorker.set_roi_base_weights_override(self, weights: Optional[dict[str, float]]) -> None`
- [L1644](../../rppg/rppg_worker.py#L1644) `RppgWorker.set_candidate_roi_weights(self, weights: Optional[dict[str, float]]) -> None`
- [L1655](../../rppg/rppg_worker.py#L1655) `RppgWorker.set_belt_truth_capture(self, writer: Optional[BeltTruthCaptureWriter]) -> None`
- [L1664](../../rppg/rppg_worker.py#L1664) `RppgWorker._maybe_capture_belt_truth(self, ts: float, per_roi_means: dict[str, tuple[float, float, float]]) -> None`
- [L1676](../../rppg/rppg_worker.py#L1676) `RppgWorker._maybe_emit_candidate_bpm(self, engine: 'RppgEngine', rppg_tuning: MediaPipeTuning, t_now: float) -> None`
- [L1710](../../rppg/rppg_worker.py#L1710) `RppgWorker.run(self) -> None`

### `rppg/watch_physio.py`

[原始碼](../../rppg/watch_physio.py)；311 行。Extended watch physiology: HRV, waveform, PSD, quality, BPM guard.

本地直接依賴：`rppg.calibration_watch`, `rppg.rppg_worker`。

- 類別 [WatchPhysioState](../../rppg/watch_physio.py#L27)
- [L56](../../rppg/watch_physio.py#L56) `_clamp(x: float, lo: float=0.0, hi: float=1.0) -> float`
- [L60](../../rppg/watch_physio.py#L60) `ibis_from_watch_samples(samples: list[WatchSample]) -> np.ndarray`
- [L80](../../rppg/watch_physio.py#L80) `pose_from_imu(ax: float | None, ay: float | None, az: float | None) -> tuple[float, float, float]`
- [L88](../../rppg/watch_physio.py#L88) `imu_motion_gate(motion_level: float | None, *, still_max: float=0.35, active_min: float=1.5) -> tuple[float, float]`
- [L106](../../rppg/watch_physio.py#L106) `_hrv_sqi(n_samples: int, motion_level: float | None, *, target_samples: int=24) -> float`
- [L115](../../rppg/watch_physio.py#L115) `_tachogram_series(ibis_ms: np.ndarray, fs_resample: float=4.0) -> tuple[np.ndarray, np.ndarray] | None`
- [L132](../../rppg/watch_physio.py#L132) `_waveform_and_psd(ibis_ms: np.ndarray) -> tuple[list[float], list[float], list[float], bool]`
- [L153](../../rppg/watch_physio.py#L153) `_bpm_guard(current_bpm: int, history: list[int], *, jump_bpm: float=18.0) -> tuple[float, bool, str]`
- [L164](../../rppg/watch_physio.py#L164) `compute_watch_physio(samples: list[WatchSample], *, window_sec: float=90.0, min_samples: int=8, still_motion_max: float=0.35) -> WatchPhysioState`

### `scripts/build_engine_sidecar.py`

[原始碼](../../scripts/build_engine_sidecar.py)；118 行。Build the platform-native PyInstaller engine used by Tauri releases.

本地直接依賴：`scripts.runtime_preflight`。

- [L20](../../scripts/build_engine_sidecar.py#L20) `engine_executable_name(platform_name: str | None=None) -> str`
- [L25](../../scripts/build_engine_sidecar.py#L25) `add_data_argument(source: Path, destination: str) -> str`
- [L29](../../scripts/build_engine_sidecar.py#L29) `build_command(python_executable: str | Path=sys.executable) -> list[str]`
- [L73](../../scripts/build_engine_sidecar.py#L73) `_run_checked(command: list[str]) -> None`
- [L77](../../scripts/build_engine_sidecar.py#L77) `validate_source_runtime() -> None`
- [L88](../../scripts/build_engine_sidecar.py#L88) `validate_packaged_runtime(engine_executable: Path) -> None`
- [L93](../../scripts/build_engine_sidecar.py#L93) `main() -> int`

### `scripts/build_practical_project_report_pdf.py`

[原始碼](../../scripts/build_practical_project_report_pdf.py)；615 行。Build the formal practical project report as a PDF.

- 類別 [LabelMetrics](../../scripts/build_practical_project_report_pdf.py#L55)
- [L71](../../scripts/build_practical_project_report_pdf.py#L71) `register_fonts() -> None`
- [L90](../../scripts/build_practical_project_report_pdf.py#L90) `make_styles() -> dict[str, ParagraphStyle]`
- [L183](../../scripts/build_practical_project_report_pdf.py#L183) `p(text: str, styles: dict[str, ParagraphStyle], style: str='body') -> Paragraph`
- [L187](../../scripts/build_practical_project_report_pdf.py#L187) `heading(text: str, styles: dict[str, ParagraphStyle], level: int=1) -> Paragraph`
- [L191](../../scripts/build_practical_project_report_pdf.py#L191) `bullet_list(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable`
- [L201](../../scripts/build_practical_project_report_pdf.py#L201) `numbered_list(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable`
- [L211](../../scripts/build_practical_project_report_pdf.py#L211) `table(data: list[list[Any]], col_widths: list[float] | None=None, font_size: float=9.5) -> Table`
- 類別 [ProjectDocTemplate](../../scripts/build_practical_project_report_pdf.py#L239)
- [L240](../../scripts/build_practical_project_report_pdf.py#L240) `ProjectDocTemplate.__init__(self, filename: str) -> None`
- [L254](../../scripts/build_practical_project_report_pdf.py#L254) `ProjectDocTemplate.draw_footer(self, canvas, doc) -> None`
- [L262](../../scripts/build_practical_project_report_pdf.py#L262) `read_validation_metrics() -> tuple[list[LabelMetrics], str]`
- [L301](../../scripts/build_practical_project_report_pdf.py#L301) `add_bar_table(story: list[Any], styles: dict[str, ParagraphStyle], metrics: list[LabelMetrics], title: str) -> None`
- [L319](../../scripts/build_practical_project_report_pdf.py#L319) `add_cover_and_front_matter(story: list[Any], styles: dict[str, ParagraphStyle]) -> None`
- [L374](../../scripts/build_practical_project_report_pdf.py#L374) `add_main_content(story: list[Any], styles: dict[str, ParagraphStyle], metrics: list[LabelMetrics], run_summary: str) -> None`
- [L601](../../scripts/build_practical_project_report_pdf.py#L601) `build_pdf() -> Path`

### `scripts/build_rppg_pdf.py`

[原始碼](../../scripts/build_rppg_pdf.py)；212 行。套件／工具入口

- [L28](../../scripts/build_rppg_pdf.py#L28) `_font_properties(size: float) -> font_manager.FontProperties`
- [L42](../../scripts/build_rppg_pdf.py#L42) `_clean_inline(text: str) -> str`
- [L49](../../scripts/build_rppg_pdf.py#L49) `_wrap(text: str, width: int) -> list[str]`
- [L60](../../scripts/build_rppg_pdf.py#L60) `_parse_markdown(md: str) -> list[tuple[str, str]]`
- [L114](../../scripts/build_rppg_pdf.py#L114) `_new_page(pdf: PdfPages, page_no: int) -> tuple[Figure, Axes, float]`
- [L130](../../scripts/build_rppg_pdf.py#L130) `_save_page(pdf: PdfPages, fig: Figure) -> None`
- [L134](../../scripts/build_rppg_pdf.py#L134) `build_pdf() -> None`

### `scripts/build_technical_report_pdfs.py`

[原始碼](../../scripts/build_technical_report_pdfs.py)；265 行。套件／工具入口

- [L59](../../scripts/build_technical_report_pdfs.py#L59) `_font_properties(size: float) -> font_manager.FontProperties`
- [L74](../../scripts/build_technical_report_pdfs.py#L74) `_clean_inline(text: str) -> str`
- [L81](../../scripts/build_technical_report_pdfs.py#L81) `_wrap(text: str, width: int, *, break_long_words: bool=False) -> list[str]`
- [L93](../../scripts/build_technical_report_pdfs.py#L93) `_parse_markdown(md: str) -> list[tuple[str, str]]`
- [L170](../../scripts/build_technical_report_pdfs.py#L170) `_new_page(pdf: PdfPages, page_no: int, footer: str) -> tuple[Figure, Axes, float]`
- [L186](../../scripts/build_technical_report_pdfs.py#L186) `_block_style(kind: str) -> tuple[font_manager.FontProperties, float, float, int, str, float, bool]`
- [L206](../../scripts/build_technical_report_pdfs.py#L206) `build_pdf(source: Path, target: Path, footer: str) -> None`
- [L246](../../scripts/build_technical_report_pdfs.py#L246) `main() -> None`

### `scripts/camera_backend_benchmark.py`

[原始碼](../../scripts/camera_backend_benchmark.py)；125 行。比較本機相機 backend 的實際幀率、抖動與 CPU 成本。

本地直接依賴：`gui.camera_devices`。

- [L19](../../scripts/camera_backend_benchmark.py#L19) `_percentile(values: list[float], fraction: float) -> float`
- [L26](../../scripts/camera_backend_benchmark.py#L26) `_measure_backend(camera: int, backend: str, seconds: float, width: int, height: int, target_fps: float) -> dict[str, Any]`
- [L86](../../scripts/camera_backend_benchmark.py#L86) `main(argv: list[str] | None=None) -> int`

### `scripts/check_repository_hygiene.py`

[原始碼](../../scripts/check_repository_hygiene.py)；25 行。拒絕將 .gitignore 指定的本機檔案納入版本控制。

- [L9](../../scripts/check_repository_hygiene.py#L9) `main() -> int`

### `scripts/desktop_engine_benchmark.py`

[原始碼](../../scripts/desktop_engine_benchmark.py)；321 行。Repeatable desktop engine and preview transport microbenchmark.

本地直接依賴：`gui.main_window`, `gui.web_server`, `scripts.desktop_engine_client`。

- [L35](../../scripts/desktop_engine_benchmark.py#L35) `_expand_process_tree(root_pid: int, parent_by_pid: dict[int, int]) -> list[int]`
- [L49](../../scripts/desktop_engine_benchmark.py#L49) `_windows_process_parent_map() -> dict[int, int]`
- [L100](../../scripts/desktop_engine_benchmark.py#L100) `_process_tree_pids(root_pid: int) -> list[int]`
- [L112](../../scripts/desktop_engine_benchmark.py#L112) `_distribution(values: list[float]) -> dict[str, float]`
- [L130](../../scripts/desktop_engine_benchmark.py#L130) `_rss_bytes(pid: int) -> int | None`
- [L185](../../scripts/desktop_engine_benchmark.py#L185) `_process_tree_rss_bytes(root_pid: int) -> tuple[list[int], int | None]`
- [L192](../../scripts/desktop_engine_benchmark.py#L192) `_benchmark_commands(*, host: str, port: int, warmup: int, samples: int) -> dict[str, Any]`
- [L206](../../scripts/desktop_engine_benchmark.py#L206) `_synthetic_image(width: int=640, height: int=360)`
- [L221](../../scripts/desktop_engine_benchmark.py#L221) `_benchmark_synthetic_preview(*, warmup: int, samples: int) -> dict[str, Any]`
- [L267](../../scripts/desktop_engine_benchmark.py#L267) `_parse_args(argv: list[str] | None=None) -> argparse.Namespace`
- [L278](../../scripts/desktop_engine_benchmark.py#L278) `main(argv: list[str] | None=None) -> int`

### `scripts/desktop_engine_client.py`

[原始碼](../../scripts/desktop_engine_client.py)；120 行。Shared localhost client and source-engine lifecycle helpers for desktop smoke tools.

- [L21](../../scripts/desktop_engine_client.py#L21) `request_json(method: str, path: str, *, host: str=DEFAULT_HOST, port: int=DEFAULT_PORT, body: dict[str, Any] | None=None, timeout: float=2.0) -> dict[str, Any]`
- [L46](../../scripts/desktop_engine_client.py#L46) `control_state(*, host: str, port: int, timeout: float=2.0) -> dict[str, Any]`
- [L56](../../scripts/desktop_engine_client.py#L56) `port_in_use(*, host: str, port: int) -> bool`
- [L65](../../scripts/desktop_engine_client.py#L65) `start_source_engine(*, host: str, port: int, timeout: float) -> tuple[subprocess.Popen[bytes], float]`
- [L100](../../scripts/desktop_engine_client.py#L100) `stop_engine(process: subprocess.Popen[bytes], *, host: str, port: int) -> None`

### `scripts/desktop_hardware_smoke.py`

[原始碼](../../scripts/desktop_hardware_smoke.py)；242 行。Exercise the source engine camera path through desktop API v2.

本地直接依賴：`scripts.desktop_engine_client`。

- [L41](../../scripts/desktop_hardware_smoke.py#L41) `_command(*, host: str, port: int, command: str, args: dict[str, Any]) -> dict[str, Any]`
- [L58](../../scripts/desktop_hardware_smoke.py#L58) `_choose_camera(cameras: list[dict[str, Any]], requested: int | None) -> dict[str, Any]`
- [L72](../../scripts/desktop_hardware_smoke.py#L72) `_metrics_ready(metrics: dict[str, Any], *, expected_frame_source: str | None=None) -> bool`
- [L86](../../scripts/desktop_hardware_smoke.py#L86) `_analysis_flags(mode: str) -> tuple[bool, bool]`
- [L98](../../scripts/desktop_hardware_smoke.py#L98) `_expected_frame_source(mode: str) -> str`
- [L104](../../scripts/desktop_hardware_smoke.py#L104) `run_smoke(*, host: str='127.0.0.1', port: int=5012, camera_index: int | None=None, analysis_mode: str='raw', timeout: float=15.0) -> dict[str, Any]`
- [L211](../../scripts/desktop_hardware_smoke.py#L211) `_parse_args(argv: list[str] | None=None) -> argparse.Namespace`
- [L221](../../scripts/desktop_hardware_smoke.py#L221) `main(argv: list[str] | None=None) -> int`

### `scripts/diagnose_camera.py`

[原始碼](../../scripts/diagnose_camera.py)；248 行。跨平台相機、權限與黑屏診斷。

本地直接依賴：`gui.camera_devices`。

- [L30](../../scripts/diagnose_camera.py#L30) `_run(command: list[str]) -> tuple[int, str]`
- [L47](../../scripts/diagnose_camera.py#L47) `_print_command(command: list[str]) -> None`
- [L55](../../scripts/diagnose_camera.py#L55) `_frame_stats(frame: np.ndarray) -> tuple[float, float]`
- [L62](../../scripts/diagnose_camera.py#L62) `_measured_fps(first_frame_at: float | None, last_frame_at: float | None, frames: int) -> float`
- [L72](../../scripts/diagnose_camera.py#L72) `_read_probe(index: int, backend: str, seconds: float, *, width: int, height: int, target_fps: float, prefer_mjpg: bool) -> dict[str, Any]`
- [L128](../../scripts/diagnose_camera.py#L128) `_fourcc_to_str(raw: int) -> str`
- [L132](../../scripts/diagnose_camera.py#L132) `main() -> int`

### `scripts/hr_belt_monitor.py`

[原始碼](../../scripts/hr_belt_monitor.py)；169 行。BLE 心跳帶免 GUI 診斷工具：掃描 → 連線 → 即時列印 BPM / RR / 電量 / 狀態。

本地直接依賴：`rppg.calibration_watch`, `rppg.hr_belt_ble`。

- [L51](../../scripts/hr_belt_monitor.py#L51) `_parse_args(argv: list[str] | None=None) -> argparse.Namespace`
- [L71](../../scripts/hr_belt_monitor.py#L71) `_resolve_config(args: argparse.Namespace) -> HrBeltConfig`
- [L83](../../scripts/hr_belt_monitor.py#L83) `_print_sample(sample: WatchSample) -> None`
- [L92](../../scripts/hr_belt_monitor.py#L92) `main(argv: list[str] | None=None) -> int`

### `scripts/installed_desktop_smoke.py`

[原始碼](../../scripts/installed_desktop_smoke.py)；311 行。Exercise an isolated NSIS install, engine shutdown, and shell close.

本地直接依賴：`scripts.desktop_engine_client`。

- [L29](../../scripts/installed_desktop_smoke.py#L29) `_wait_for_state(*, port: int, process: subprocess.Popen[bytes], timeout: float) -> dict[str, Any]`
- [L43](../../scripts/installed_desktop_smoke.py#L43) `_desktop_command(port: int, command: str, args: dict[str, object]) -> dict[str, object]`
- [L60](../../scripts/installed_desktop_smoke.py#L60) `_camera_metrics_ready(metrics: object) -> bool`
- [L75](../../scripts/installed_desktop_smoke.py#L75) `_windows_for_pid(pid: int) -> list[dict[str, Any]]`
- [L106](../../scripts/installed_desktop_smoke.py#L106) `_select_main_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]`
- [L117](../../scripts/installed_desktop_smoke.py#L117) `_close_shell_windows(pid: int) -> list[dict[str, Any]]`
- [L127](../../scripts/installed_desktop_smoke.py#L127) `_resolve_installer(root: Path, explicit: Path | None) -> Path`
- [L142](../../scripts/installed_desktop_smoke.py#L142) `run_smoke(*, installer: Path, port: int, timeout: float, install_timeout: float) -> dict[str, Any]`
- [L292](../../scripts/installed_desktop_smoke.py#L292) `main() -> int`

### `scripts/installed_desktop_smoke_linux.py`

[原始碼](../../scripts/installed_desktop_smoke_linux.py)；203 行。Smoke-test a bundled Linux AppImage and its packaged Python engine.

本地直接依賴：`scripts.desktop_engine_client`。

- [L26](../../scripts/installed_desktop_smoke_linux.py#L26) `_resolve_appimage(explicit: Path | None) -> Path`
- [L40](../../scripts/installed_desktop_smoke_linux.py#L40) `_desktop_command(port: int, command: str, args: dict[str, object]) -> dict[str, object]`
- [L57](../../scripts/installed_desktop_smoke_linux.py#L57) `_camera_metrics_ready(metrics: object) -> bool`
- [L72](../../scripts/installed_desktop_smoke_linux.py#L72) `run_smoke(*, artifact: Path, port: int, timeout: float) -> dict[str, object]`
- [L187](../../scripts/installed_desktop_smoke_linux.py#L187) `main() -> int`

### `scripts/installed_desktop_smoke_macos.py`

[原始碼](../../scripts/installed_desktop_smoke_macos.py)；241 行。Smoke-test the bundled macOS app and its packaged Python engine.

本地直接依賴：`scripts.desktop_engine_client`。

- [L35](../../scripts/installed_desktop_smoke_macos.py#L35) `_request_shell_quit() -> None`
- [L49](../../scripts/installed_desktop_smoke_macos.py#L49) `_wait_for_shell_exit(process: subprocess.Popen[bytes], timeout: float) -> int`
- [L58](../../scripts/installed_desktop_smoke_macos.py#L58) `_desktop_command(port: int, command: str, args: dict[str, object]) -> dict[str, object]`
- [L75](../../scripts/installed_desktop_smoke_macos.py#L75) `_camera_metrics_ready(metrics: object) -> bool`
- [L90](../../scripts/installed_desktop_smoke_macos.py#L90) `main() -> int`

### `scripts/mediapipe_profile_sweep.py`

[原始碼](../../scripts/mediapipe_profile_sweep.py)；177 行。套件／工具入口

本地直接依賴：`gui.mediapipe_tuning`, `gui.platforms`, `rppg.rppg_worker`。

- [L42](../../scripts/mediapipe_profile_sweep.py#L42) `_load_profile_tuning(profile: str, config_path: Path=CONFIG_PATH) -> MediaPipeTuning`
- [L65](../../scripts/mediapipe_profile_sweep.py#L65) `_profiles_from_config(config_path: Path) -> list[str]`
- [L76](../../scripts/mediapipe_profile_sweep.py#L76) `run_profile(video_path: Path, profile: str, max_frames: int, stride: int) -> dict[str, Any]`
- [L150](../../scripts/mediapipe_profile_sweep.py#L150) `main() -> None`

### `scripts/prepare_local_assets.py`

[原始碼](../../scripts/prepare_local_assets.py)；85 行。在本機補齊封裝圖示；模型僅於明確指定 --download-model 時下載。

本地直接依賴：`gui.model_assets`。

- [L17](../../scripts/prepare_local_assets.py#L17) `prepare_icons(root: Path=ROOT) -> list[Path]`
- [L70](../../scripts/prepare_local_assets.py#L70) `main() -> int`

### `scripts/replay_calibration_summary.py`

[原始碼](../../scripts/replay_calibration_summary.py)；75 行。套件／工具入口

- [L8](../../scripts/replay_calibration_summary.py#L8) `summarize(db_path: Path) -> None`
- [L67](../../scripts/replay_calibration_summary.py#L67) `main() -> None`

### `scripts/rppg_param_replay.py`

[原始碼](../../scripts/rppg_param_replay.py)；393 行。比較不同 rPPG ROI 權重方案對心跳帶真值的擬合優劣（P6b-4 離線驗證工具）。

本地直接依賴：`rppg.adaptive_calibration`, `rppg.belt_truth_capture`, `rppg.rppg_worker`。

- 類別 [WindowResult](../../scripts/rppg_param_replay.py#L54)
- 類別 [ReplayComparisonResult](../../scripts/rppg_param_replay.py#L67)
- [L84](../../scripts/rppg_param_replay.py#L84) `_slice_records(records: Sequence[BeltTruthCaptureRecord], start: float, end: float) -> list[BeltTruthCaptureRecord]`
- [L90](../../scripts/rppg_param_replay.py#L90) `_build_roi_windows(records: Sequence[BeltTruthCaptureRecord]) -> dict[str, RoiWindowSeries]`
- [L117](../../scripts/rppg_param_replay.py#L117) `_belt_ground_truth(records: Sequence[BeltTruthCaptureRecord]) -> Optional[float]`
- [L124](../../scripts/rppg_param_replay.py#L124) `compare_roi_weights(records: Sequence[BeltTruthCaptureRecord], current_weights: Mapping[str, float], candidate_weights: Mapping[str, float], *, window_sec: float=DEFAULT_WINDOW_SEC, step_sec: float=DEFAULT_STEP_SEC, min_samples: int=DEFAULT_MIN_SAMPLES, min_duration_sec: float=DEFAULT_MIN_DURATION_SEC, improve_margin_bpm: float=DEFAULT_IMPROVE_MARGIN_BPM) -> ReplayComparisonResult`
- [L218](../../scripts/rppg_param_replay.py#L218) `format_report(result: ReplayComparisonResult, current_weights: Mapping[str, float], candidate_weights: Mapping[str, float], capture_path: Path | str) -> str`
- [L249](../../scripts/rppg_param_replay.py#L249) `_default_current_weights() -> dict[str, float]`
- [L257](../../scripts/rppg_param_replay.py#L257) `_parse_weights_arg(raw: str, label: str) -> dict[str, float]`
- [L273](../../scripts/rppg_param_replay.py#L273) `_write_json_report(path: Path, result: ReplayComparisonResult, current_weights: Mapping[str, float], candidate_weights: Mapping[str, float]) -> None`
- [L294](../../scripts/rppg_param_replay.py#L294) `_parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace`
- [L321](../../scripts/rppg_param_replay.py#L321) `main(argv: Optional[Sequence[str]]=None) -> int`

### `scripts/runtime_preflight.py`

[原始碼](../../scripts/runtime_preflight.py)；136 行。檢查桌面 engine 啟動所需的關鍵 Python runtime 與平台後端。

本地直接依賴：`gui.platforms`。

- [L23](../../scripts/runtime_preflight.py#L23) `installed_opencv_distributions() -> dict[str, str]`
- [L38](../../scripts/runtime_preflight.py#L38) `check_runtime() -> list[str]`
- [L94](../../scripts/runtime_preflight.py#L94) `run_face_landmarker_smoke() -> str | None`
- [L119](../../scripts/runtime_preflight.py#L119) `main() -> int`

### `scripts/utarldd_accuracy.py`

[原始碼](../../scripts/utarldd_accuracy.py)；316 行。UTA-RLDD 疲勞判斷準確度量測工具。

本地直接依賴：`gui.video_replay`。

- [L43](../../scripts/utarldd_accuracy.py#L43) `_rank(values: np.ndarray) -> np.ndarray`
- [L56](../../scripts/utarldd_accuracy.py#L56) `spearman_rho(labels: list[float], scores: list[float]) -> float`
- [L67](../../scripts/utarldd_accuracy.py#L67) `pairwise_auc(scores_pos: list[float], scores_neg: list[float]) -> float`
- [L82](../../scripts/utarldd_accuracy.py#L82) `auc_bootstrap_ci(scores_pos: list[float], scores_neg: list[float], n_boot: int=2000, seed: int=0, alpha: float=0.05) -> tuple[float, float]`
- [L104](../../scripts/utarldd_accuracy.py#L104) `label_score_stats(pairs: list[tuple[float, float]]) -> dict`
- [L122](../../scripts/utarldd_accuracy.py#L122) `is_monotonic_increasing(stats: dict, key: str='mean') -> bool`
- [L129](../../scripts/utarldd_accuracy.py#L129) `collapse_fraction(pairs: list[tuple[float, float]], drowsy_label: float, threshold: float) -> float`
- [L139](../../scripts/utarldd_accuracy.py#L139) `compute_accuracy_report(summaries: list[dict], score_fields: list[str]) -> dict`
- [L172](../../scripts/utarldd_accuracy.py#L172) `format_report(report: dict) -> str`
- [L203](../../scripts/utarldd_accuracy.py#L203) `status_active_fraction(summary: dict) -> float`
- [L221](../../scripts/utarldd_accuracy.py#L221) `build_status_active_report(summaries: list[dict], labels_present: list[float]) -> dict`
- [L238](../../scripts/utarldd_accuracy.py#L238) `_run_batch(dataset_root: Path, subjects, labels, max_frames, jobs, output_dir)`
- [L258](../../scripts/utarldd_accuracy.py#L258) `main(argv=None) -> int`

### `scripts/utarldd_csv_report.py`

[原始碼](../../scripts/utarldd_csv_report.py)；35 行。套件／工具入口

本地直接依賴：`gui.video_replay`。

- [L14](../../scripts/utarldd_csv_report.py#L14) `_default_output(summary_csv: Path) -> Path`
- [L22](../../scripts/utarldd_csv_report.py#L22) `main() -> None`

### `scripts/utarldd_golden.py`

[原始碼](../../scripts/utarldd_golden.py)；232 行。UTA-RLDD golden-output 回歸基準工具。

本地直接依賴：`gui.video_replay`。

- 類別 [GoldenDiff](../../scripts/utarldd_golden.py#L33)
- [L44](../../scripts/utarldd_golden.py#L44) `load_golden_config(path: Path) -> dict`
- [L57](../../scripts/utarldd_golden.py#L57) `extract_golden_fields(summary: dict, field_names) -> dict`
- [L65](../../scripts/utarldd_golden.py#L65) `summaries_to_videos(summaries: list, field_names) -> tuple[dict, list[GoldenDiff]]`
- [L85](../../scripts/utarldd_golden.py#L85) `compare_videos(baseline_videos: dict, current_videos: dict, field_specs: dict) -> list[GoldenDiff]`
- [L118](../../scripts/utarldd_golden.py#L118) `format_report(diffs: list[GoldenDiff]) -> str`
- [L143](../../scripts/utarldd_golden.py#L143) `_run_subset(dataset_root: Path, config: dict, output_dir: Path | None)`
- [L164](../../scripts/utarldd_golden.py#L164) `_cmd_create(args, config: dict) -> int`
- [L186](../../scripts/utarldd_golden.py#L186) `_cmd_check(args, config: dict) -> int`
- [L206](../../scripts/utarldd_golden.py#L206) `main(argv=None) -> int`

### `scripts/utarldd_replay.py`

[原始碼](../../scripts/utarldd_replay.py)；70 行。套件／工具入口

本地直接依賴：`gui.video_replay`。

- [L9](../../scripts/utarldd_replay.py#L9) `_split_csv(values: list[str] | None) -> list[str] | None`
- [L18](../../scripts/utarldd_replay.py#L18) `main() -> None`

### `scripts/video_replay.py`

[原始碼](../../scripts/video_replay.py)；68 行。通用影片回放：把任意影片檔或影片資料夾當離線鏡頭，餵進疲勞/rPPG 引擎。

本地直接依賴：`gui.video_replay`。

- [L15](../../scripts/video_replay.py#L15) `main() -> None`

## 2. Dataclass 欄位、型別與宣告預設值

以下保留 field()、匯入常數與運算式；實際值可能再受 profile／使用者設定／品質 gate 調整。這些不是新增管理選項。

### `AlarmScenarioConfig` — `gui/alarm_config.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `enabled` | `bool` | `True` |
| `sound_path` | `str` | `''` |

### `AlarmConfig` — `gui/alarm_config.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `enabled` | `bool` | `False` |
| `volume` | `int` | `70` |
| `trigger_delay_sec` | `float` | `2.0` |
| `repeat_interval_sec` | `float` | `30.0` |
| `repeat_while_critical` | `bool` | `True` |
| `use_builtin_fallback` | `bool` | `True` |
| `scenarios` | `dict[str, AlarmScenarioConfig]` | `field(default_factory=dict)` |

### `AlarmTriggerState` — `gui/alarm_player.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `last_status` | `str \| None` | `None` |
| `status_since` | `float \| None` | `None` |
| `played_for_entry` | `bool` | `False` |
| `last_played_scenario` | `str \| None` | `None` |
| `last_play_monotonic` | `dict[str, float]` | `field(default_factory=dict)` |

### `CapturePreferencesSnapshot` — `gui/capture_preferences_state.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `auto_record` | `bool` | `False` |
| `belt_calibration` | `bool` | `False` |
| `auto_capture_seconds` | `int` | `60` |
| `auto_capture_include_belt` | `bool` | `False` |

### `_PendingCommand` — `gui/desktop_control.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `name` | `str` | `必填` |
| `args` | `dict[str, Any]` | `必填` |
| `completed` | `threading.Event` | `field(default_factory=threading.Event)` |
| `result` | `dict[str, Any] \| None` | `None` |
| `error` | `Exception \| None` | `None` |
| `cancelled` | `bool` | `False` |

### `HotkeyConfig` — `gui/desktop_models.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `toggle_metrics` | `str` | `'Ctrl+Alt+O'` |
| `toggle_preview` | `str` | `'Ctrl+Alt+P'` |
| `start_stop` | `str` | `'Ctrl+Alt+S'` |
| `lock_overlay` | `str` | `'Ctrl+Alt+F8'` |
| `toggle_all` | `str` | `'Ctrl+Alt+A'` |
| `toggle_recording` | `str` | `'Ctrl+Alt+F9'` |

### `UserProfile` — `gui/desktop_models.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `age` | `int` | `28` |
| `height_cm` | `int` | `170` |
| `weight_kg` | `float` | `65.0` |

### `CameraDevice` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `index` | `int` | `必填` |
| `label` | `str` | `必填` |

### `CameraConfig` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `devices` | `tuple[CameraDevice, ...]` | `()` |
| `selected_index` | `int \| None` | `None` |
| `resolution` | `str` | `'1280×720（720p）'` |
| `fps` | `str` | `CAMERA_FIXED_FPS` |
| `backend` | `str` | `'ffmpeg'` |
| `horizontal_flip` | `bool` | `True` |

### `CameraStartSpec` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `index` | `int` | `必填` |
| `width` | `int` | `必填` |
| `height` | `int` | `必填` |
| `target_fps` | `int` | `必填` |
| `backend` | `str` | `必填` |
| `horizontal_flip` | `bool` | `必填` |
| `camera_label` | `str` | `必填` |

### `AnalysisPlan` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `worker` | `str` | `必填` |
| `rppg_enabled` | `bool` | `必填` |
| `fatigue_enabled` | `bool` | `必填` |

### `PipelineSnapshot` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `running` | `bool` | `False` |
| `analysis` | `AnalysisPlan` | `AnalysisPlan('none', False, False)` |
| `recording` | `bool` | `False` |
| `cleanup_pending` | `bool` | `False` |

### `AnalysisLifecyclePorts` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `stop_all` | `Callable[[], None]` | `必填` |
| `start_combined` | `Callable[[], None]` | `必填` |
| `start_rppg` | `Callable[[], None]` | `必填` |
| `start_fatigue` | `Callable[[], None]` | `必填` |
| `restore_raw_routing` | `Callable[[], None]` | `必填` |

### `ReplayLifecycleSnapshot` — `gui/engine_controller.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `running` | `bool` | `False` |
| `stopping` | `bool` | `False` |
| `shutdown_pending` | `bool` | `False` |

### `FatigueParams` — `gui/fatigue_engine.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `pose_stride` | `int` | `3` |
| `brow_stride` | `int` | `3` |
| `calib_sec` | `float` | `5.0` |
| `min_calib_samples` | `int` | `20` |
| `ear_ema_alpha` | `float` | `0.4` |
| `thresh_ratio` | `float` | `0.75` |
| `base_th_default` | `float` | `0.18` |
| `calib_ear_min` | `float` | `0.15` |
| `calib_ear_sane_min` | `float` | `0.2` |
| `closed_open_hyst` | `float` | `1.06` |
| `no_face_reset_sec` | `float` | `1.0` |
| `blink_min_sec` | `float` | `0.08` |
| `blink_max_sec` | `float` | `0.45` |
| `blink_grace_frames` | `int` | `3` |
| `min_face_area_ratio_blink` | `float` | `0.03` |
| `roll_limit_blink` | `float` | `40.0` |
| `min_face_area_ratio_fatigue` | `float` | `0.06` |
| `roll_limit_fatigue` | `float` | `25.0` |
| `yaw_ratio_limit_fatigue` | `float` | `1.45` |
| `nose_speed_limit_fatigue` | `float` | `240.0` |
| `perclos_window_sec` | `float` | `60.0` |
| `perclos_denom_floor_sec` | `float` | `5.0` |
| `low_vigilance_perclos_th` | `float` | `0.02` |
| `tired_perclos_th` | `float` | `0.05` |
| `perclos_composite_full` | `float` | `0.05` |
| `long_closed_sec` | `float` | `1.5` |
| `use_stable_face_area` | `bool` | `True` |
| `tighten_strength_fatigue` | `float` | `0.25` |
| `min_th_factor_fatigue` | `float` | `0.6` |
| `pitch_eye_gate_deg` | `float` | `10.0` |
| `pitch_up_deg` | `float` | `22.0` |
| `pitch_up_sustained_sec` | `float` | `1.0` |
| `head_pitch_down_th` | `float` | `-15.0` |
| `head_microsleep_sec` | `float` | `1.5` |
| `dz_ref_ema_alpha` | `float` | `0.005` |
| `pitch_offset_sane_deg` | `float` | `20.0` |
| `pose_stale_max_sec` | `float` | `0.75` |
| `mar_yawn_th` | `float` | `0.6` |
| `mar_yawn_dur_sec` | `float` | `1.5` |
| `mouth_open_yawn_th` | `float` | `0.24` |
| `mouth_open_noise_th` | `float` | `0.3` |
| `gaze_warmup_sec` | `float` | `5.0` |
| `gaze_window_sec` | `float` | `3.0` |
| `gaze_fixed_std_th` | `float` | `0.015` |
| `gaze_fixed_alert_sec` | `float` | `5.0` |
| `saccade_velocity_th` | `float` | `0.08` |
| `saccade_window_sec` | `float` | `60.0` |
| `squint_ear_ratio` | `float` | `1.35` |
| `squint_min_sec` | `float` | `3.0` |
| `lid_balance_gate_th` | `float` | `0.35` |
| `brow_furrow_ratio` | `float` | `0.85` |
| `brow_calib_frames` | `int` | `120` |
| `iris_ratio_ema_alpha` | `float` | `0.1` |
| `blend_calib_sec` | `float` | `4.0` |
| `blend_min_samples` | `int` | `24` |
| `blend_ema_alpha` | `float` | `0.22` |
| `blend_blink_gate` | `float` | `0.2` |
| `blend_squint_gate` | `float` | `0.18` |
| `blend_brow_gate` | `float` | `0.18` |
| `blend_jaw_gate` | `float` | `0.2` |
| `blink_feature_calib_count` | `int` | `12` |
| `blink_duration_warn_z` | `float` | `1.5` |
| `blink_opening_velocity_warn_z` | `float` | `-1.5` |
| `closure_onset_sec` | `float` | `CLOSURE_ONSET_SEC` |
| `closure_full_sec` | `float` | `CLOSURE_FULL_SEC` |
| `w_engine_closure` | `float` | `0.35` |
| `downgaze_gy_th` | `float` | `0.12` |
| `downgaze_ear_floor` | `float` | `0.45` |
| `downgaze_ear_hi` | `float` | `1.1` |
| `downgaze_enter_sec` | `float` | `0.3` |
| `downgaze_exit_sec` | `float` | `0.3` |

### `FatigueMetrics` — `gui/fatigue_engine.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `face_detected` | `bool` | `False` |
| `calibrated` | `bool` | `False` |
| `status` | `str` | `'NO_FACE'` |
| `fatigue_level` | `float` | `0.0` |
| `early_warning` | `bool` | `False` |
| `ear` | `float` | `0.0` |
| `ear_smooth` | `float` | `0.0` |
| `blink_count` | `int` | `0` |
| `perclos` | `float` | `0.0` |
| `perclos_mild_th_eff` | `float` | `-1.0` |
| `perclos_high_th_eff` | `float` | `-1.0` |
| `blink_rate_pm` | `float` | `0.0` |
| `blink_duration_sec` | `float` | `0.0` |
| `blink_duration_mean_sec` | `float` | `0.0` |
| `blink_duration_z` | `float` | `0.0` |
| `blink_amplitude` | `float` | `0.0` |
| `blink_opening_velocity` | `float` | `0.0` |
| `blink_opening_velocity_z` | `float` | `0.0` |
| `blink_temporal_score` | `float` | `0.0` |
| `eye_closure_sec` | `float` | `0.0` |
| `is_squinting` | `bool` | `False` |
| `squint_duration` | `float` | `0.0` |
| `is_frowning` | `bool` | `False` |
| `brow_dist_norm` | `float` | `1.0` |
| `lid_open_left` | `float` | `0.0` |
| `lid_open_right` | `float` | `0.0` |
| `lid_balance` | `float` | `0.0` |
| `iris_ratio` | `float` | `0.0` |
| `iris_ratio_trend` | `float` | `0.0` |
| `nose_speed` | `float` | `0.0` |
| `blend_eye_blink` | `float` | `0.0` |
| `blend_eye_squint` | `float` | `0.0` |
| `blend_brow_down` | `float` | `0.0` |
| `blend_jaw_open` | `float` | `0.0` |
| `gaze_x` | `float` | `0.0` |
| `gaze_y` | `float` | `0.0` |
| `gaze_stability_index` | `float` | `0.0` |
| `gaze_mental_fatigue` | `bool` | `False` |
| `saccadic_velocity` | `float` | `0.0` |
| `is_saccade` | `bool` | `False` |
| `fixation_duration` | `float` | `0.0` |
| `saccade_freq_pm` | `float` | `0.0` |
| `saccade_window_ready` | `bool` | `False` |
| `head_pitch` | `float` | `0.0` |
| `head_yaw` | `float` | `0.0` |
| `head_roll` | `float` | `0.0` |
| `microsleep_alert` | `bool` | `False` |
| `microsleep_count` | `int` | `0` |
| `mar` | `float` | `0.0` |
| `yawn_detected` | `bool` | `False` |
| `yawn_count` | `int` | `0` |
| `mouth_open_ratio` | `float` | `0.0` |
| `mouth_blend_stretch` | `float` | `0.0` |
| `quality_score` | `float` | `0.0` |
| `blend_calib_progress` | `float` | `0.0` |
| `has_iris` | `bool` | `False` |
| `calib_progress` | `float` | `0.0` |
| `down_gaze_active` | `bool` | `False` |

### `FuserConfig` — `gui/fatigue_scorer.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `rppg_weight` | `float` | `0.15` |
| `behavior_weight` | `float` | `0.85` |
| `rppg_w_stress` | `float` | `0.6` |
| `rppg_w_bpm` | `float` | `0.3` |
| `rppg_w_lfhf` | `float` | `0.1` |
| `bpm_normal_lo` | `float` | `60.0` |
| `bpm_normal_hi` | `float` | `100.0` |
| `bpm_max_dev` | `float` | `40.0` |
| `lfhf_neutral` | `float` | `1.5` |
| `lfhf_max` | `float` | `4.0` |
| `sqi_min_reliable` | `float` | `0.45` |
| `rppg_min_quality` | `float` | `0.55` |
| `rppg_min_roi_valid` | `int` | `3` |
| `beh_w_perclos` | `float` | `0.55` |
| `beh_w_blink_temporal` | `float` | `0.12` |
| `beh_w_microsleep` | `float` | `0.1` |
| `beh_w_gaze` | `float` | `0.08` |
| `beh_w_squint` | `float` | `0.05` |
| `beh_w_yawn` | `float` | `0.05` |
| `beh_w_frown` | `float` | `0.05` |
| `closure_onset_sec` | `float` | `CLOSURE_ONSET_SEC` |
| `closure_full_sec` | `float` | `CLOSURE_FULL_SEC` |
| `beh_w_eye_closure` | `float` | `0.3` |
| `perclos_mild_th` | `float` | `PERCLOS_MILD_TH_DEFAULT` |
| `perclos_high_th` | `float` | `PERCLOS_HIGH_TH_DEFAULT` |
| `squint_full_sec` | `float` | `30.0` |
| `microsleep_per_event` | `float` | `0.35` |
| `gaze_fix_full_sec` | `float` | `20.0` |
| `gaze_saccade_low_pm` | `float` | `3.0` |
| `frown_full_ratio` | `float` | `0.75` |
| `yawn_full_count` | `int` | `5` |
| `trend_window_sec` | `float` | `30.0` |
| `level_hysteresis` | `float` | `0.03` |

### `FusedFatigueScore` — `gui/fatigue_scorer.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `score` | `float` | `0.0` |
| `level` | `str` | `'清醒'` |
| `level_en` | `str` | `'Alert'` |
| `color_bgr` | `tuple` | `(0, 200, 0)` |
| `rppg_sub` | `float` | `0.0` |
| `behavior_sub` | `float` | `0.0` |
| `rppg_weight_eff` | `float` | `0.15` |
| `behavior_weight_eff` | `float` | `0.85` |
| `trend` | `float` | `0.0` |
| `trend_symbol` | `str` | `'→'` |
| `rppg_available` | `bool` | `False` |
| `behavior_available` | `bool` | `False` |
| `rppg_stress_score` | `float` | `0.0` |
| `rppg_bpm_score` | `float` | `0.0` |
| `beh_perclos_score` | `float` | `0.0` |
| `beh_blink_temporal_score` | `float` | `0.0` |
| `beh_squint_score` | `float` | `0.0` |
| `beh_microsleep_score` | `float` | `0.0` |
| `beh_gaze_score` | `float` | `0.0` |
| `beh_frown_score` | `float` | `0.0` |
| `beh_yawn_score` | `float` | `0.0` |
| `beh_eye_closure_score` | `float` | `0.0` |
| `timestamp` | `float` | `field(default_factory=time.perf_counter)` |

### `HotkeyRegistrationFailure` — `gui/global_hotkeys.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `hotkey_id` | `int` | `必填` |
| `code` | `int` | `必填` |
| `reason` | `str` | `必填` |

### `HotkeyUnregistrationFailure` — `gui/global_hotkeys.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `hotkey_id` | `int` | `必填` |
| `code` | `int` | `必填` |
| `reason` | `str` | `'unregistration_failed'` |

### `_GlobalHotkeyBinding` — `gui/main_window.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `field` | `str` | `必填` |
| `sequence` | `str` | `必填` |
| `callback` | `Callable[[], None]` | `必填` |

### `FaceLandmarkerTuning` — `gui/mediapipe_tuning.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `min_face_detection_confidence` | `float` | `0.55` |
| `min_face_presence_confidence` | `float` | `0.55` |
| `min_tracking_confidence` | `float` | `0.6` |
| `num_faces` | `int` | `1` |

### `RppgRoiTuning` — `gui/mediapipe_tuning.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `base_weights` | `dict[str, float]` | `field(default_factory=lambda: {'forehead': 0.34, 'L_cheek': 0.25, 'R_cheek': 0.25, 'glabella': 0.16})` |
| `roll_full_penalty_deg` | `float` | `42.0` |
| `yaw_full_penalty_deg` | `float` | `42.0` |
| `pitch_free_deg` | `float` | `8.0` |
| `pitch_full_penalty_deg` | `float` | `34.0` |
| `obstruction_dark_luma` | `float` | `35.0` |
| `obstruction_bright_luma` | `float` | `232.0` |
| `obstruction_low_chroma` | `float` | `2.5` |
| `obstruction_high_chroma` | `float` | `48.0` |
| `min_roi_weight` | `float` | `0.04` |
| `roi_smoothing_enabled` | `bool` | `True` |
| `roi_smoothing_alpha` | `float` | `0.35` |
| `roi_smoothing_max_shift_ratio` | `float` | `0.12` |
| `landmark_jitter_full_norm` | `float` | `0.02` |
| `roi_area_jitter_full_ratio` | `float` | `0.25` |
| `canonical_roi_warp_enabled` | `bool` | `False` |
| `canonical_roi_warp_strength` | `float` | `0.35` |

### `QualityTuning` — `gui/mediapipe_tuning.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `pose_weight` | `float` | `0.3` |
| `motion_weight` | `float` | `0.25` |
| `coverage_weight` | `float` | `0.25` |
| `roi_weight` | `float` | `0.2` |
| `signal_weight` | `float` | `0.45` |
| `face_weight` | `float` | `0.55` |

### `BlendshapeTuning` — `gui/mediapipe_tuning.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `calib_sec` | `float` | `4.0` |
| `min_samples` | `int` | `24` |
| `ema_alpha` | `float` | `0.22` |
| `blink_gate` | `float` | `0.2` |
| `squint_gate` | `float` | `0.18` |
| `brow_gate` | `float` | `0.18` |
| `jaw_gate` | `float` | `0.2` |

### `MediaPipeTuning` — `gui/mediapipe_tuning.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `active_profile` | `str` | `'default'` |
| `face_landmarker` | `FaceLandmarkerTuning` | `field(default_factory=FaceLandmarkerTuning)` |
| `rppg_roi` | `RppgRoiTuning` | `field(default_factory=RppgRoiTuning)` |
| `quality` | `QualityTuning` | `field(default_factory=QualityTuning)` |
| `blendshape` | `BlendshapeTuning` | `field(default_factory=BlendshapeTuning)` |
| `profiles` | `dict[str, dict[str, Any]]` | `field(default_factory=dict)` |

### `OverlayGeometry` — `gui/overlay_runtime_state.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `x` | `int` | `必填` |
| `y` | `int` | `必填` |
| `width` | `int` | `必填` |
| `height` | `int` | `必填` |

### `OverlaySnapshot` — `gui/overlay_runtime_state.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `all_enabled` | `bool` | `True` |
| `preview` | `bool` | `False` |
| `metrics` | `bool` | `True` |
| `locked` | `bool` | `True` |
| `opacity` | `int` | `55` |
| `geometry` | `OverlayGeometry \| None` | `None` |

### `PersonalProfile` — `gui/personal_profile.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `profile_id` | `str` | `'default'` |
| `schema_version` | `int` | `SCHEMA_VERSION` |
| `created_at` | `str` | `''` |
| `updated_at` | `str` | `''` |
| `source` | `str` | `'auto'` |
| `sample_sec` | `float` | `0.0` |
| `n_frames` | `int` | `0` |
| `valid` | `bool` | `False` |
| `perclos_awake_median` | `Optional[float]` | `None` |
| `perclos_awake_p90` | `Optional[float]` | `None` |
| `gaze_fix_std_awake` | `Optional[float]` | `None` |
| `saccade_freq_awake_pm` | `Optional[float]` | `None` |
| `fixation_dur_awake` | `Optional[float]` | `None` |
| `brow_dist_norm_awake` | `Optional[float]` | `None` |
| `mouth_open_awake` | `Optional[float]` | `None` |
| `blink_dur_mean` | `Optional[float]` | `None` |
| `blink_dur_std` | `Optional[float]` | `None` |
| `blink_amp_mean` | `Optional[float]` | `None` |
| `blink_amp_std` | `Optional[float]` | `None` |
| `blink_openvel_mean` | `Optional[float]` | `None` |
| `blink_openvel_std` | `Optional[float]` | `None` |

### `DesktopPlatformRuntime` — `gui/platforms/base.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `key` | `str` | `必填` |
| `preferred_camera_api_names` | `tuple[str, ...]` | `必填` |
| `ffmpeg_fallback_api_names` | `tuple[str, ...]` | `必填` |
| `camera_probe_limit` | `int \| None` | `None` |
| `force_mediapipe_cpu_delegate` | `bool` | `False` |
| `verify_camera_first_frame_on_fallback` | `bool` | `False` |

### `PlatformDescriptor` — `gui/platforms/registry.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `key` | `str` | `必填` |
| `family` | `str` | `必填` |
| `runtime_type` | `str` | `必填` |
| `status` | `str` | `必填` |
| `desktop_engine_supported` | `bool` | `必填` |
| `native_inference_ready` | `bool` | `必填` |
| `capabilities` | `frozenset[str]` | `必填` |
| `artifact_types` | `tuple[str, ...]` | `必填` |

### `ReplayRuntimeSnapshot` — `gui/replay_runtime_state.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `dataset_dir` | `Path \| None` | `None` |
| `jobs` | `int` | `2` |
| `annotated` | `bool` | `False` |
| `mode_label` | `str` | `'回放中'` |
| `total_count` | `int` | `0` |
| `done_count` | `int` | `0` |
| `current_text` | `str` | `'目前影片：--'` |
| `result_text` | `str` | `'摘要檔：--'` |
| `parallel_status_text` | `str` | `'處理清單：--'` |

### `ReplayVideo` — `gui/video_replay.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `subject` | `str` | `必填` |
| `label` | `str` | `必填` |
| `label_name` | `str` | `必填` |
| `path` | `Path` | `必填` |

### `ReplayVideoSummary` — `gui/video_replay.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `subject` | `str` | `必填` |
| `label` | `str` | `必填` |
| `label_name` | `str` | `必填` |
| `video_path` | `str` | `必填` |
| `db_path` | `str` | `''` |
| `annotated_video_path` | `str` | `''` |
| `status` | `str` | `'pending'` |
| `error` | `str` | `''` |
| `frames` | `int` | `0` |
| `face_frames` | `int` | `0` |
| `face_rate` | `float` | `0.0` |
| `duration_sec` | `float` | `0.0` |
| `fps` | `float` | `0.0` |
| `width` | `int` | `0` |
| `height` | `int` | `0` |
| `avg_fatigue_score` | `float` | `0.0` |
| `p95_fatigue_score` | `float` | `0.0` |
| `avg_fused_score` | `float` | `0.0` |
| `p95_fused_score` | `float` | `0.0` |
| `avg_perclos` | `float` | `0.0` |
| `max_perclos` | `float` | `0.0` |
| `avg_blink_temporal` | `float` | `0.0` |
| `max_blink_temporal` | `float` | `0.0` |
| `avg_rppg_quality` | `float` | `0.0` |
| `avg_sqi` | `float` | `0.0` |
| `avg_bpm` | `float` | `0.0` |
| `bpm_guard_count` | `int` | `0` |
| `low_vigilance_frames` | `int` | `0` |
| `drowsy_frames` | `int` | `0` |
| `critical_frames` | `int` | `0` |
| `microsleep_frames` | `int` | `0` |
| `no_face_frames` | `int` | `0` |
| `ok_frames` | `int` | `0` |
| `calibrating_frames` | `int` | `0` |
| `post_calibration_frames` | `int` | `0` |
| `behavior_available_frames` | `int` | `0` |
| `rppg_available_frames` | `int` | `0` |
| `low_quality_frames` | `int` | `0` |
| `perclos_low_frames` | `int` | `0` |
| `perclos_drowsy_frames` | `int` | `0` |
| `blink_temporal_warn_frames` | `int` | `0` |
| `squint_frames` | `int` | `0` |
| `gaze_fatigue_frames` | `int` | `0` |
| `yawn_frames` | `int` | `0` |
| `label_alignment` | `str` | `''` |
| `primary_fatigue_evidence` | `str` | `''` |
| `recommended_next_action` | `str` | `''` |
| `optimization_flags_json` | `str` | `'[]'` |
| `status_counts_json` | `str` | `'{}'` |

### `ReplayBatchResult` — `gui/video_replay.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `output_dir` | `Path` | `必填` |
| `summary_csv` | `Path` | `必填` |
| `full_summary_csv` | `Path` | `必填` |
| `validation_report_csv` | `Path` | `必填` |
| `visual_report_html` | `Path` | `必填` |
| `manifest_path` | `Path` | `必填` |
| `videos_total` | `int` | `必填` |
| `videos_done` | `int` | `必填` |
| `videos_failed` | `int` | `必填` |
| `summaries` | `list[ReplayVideoSummary]` | `field(default_factory=list)` |

### `WebPreferencesSnapshot` — `gui/web_preferences_state.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `allow_lan` | `bool` | `False` |

### `AdaptiveCalibState` — `rppg/adaptive_calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `offset_bpm` | `float` | `0.0` |
| `raw_residual_bpm` | `float` | `0.0` |
| `corrected_residual_bpm` | `float` | `0.0` |
| `pairs_used` | `int` | `0` |
| `total_observations` | `int` | `0` |
| `accepted_observations` | `int` | `0` |
| `confidence` | `str` | `CONF_LOW` |
| `converged` | `bool` | `False` |
| `diverged` | `bool` | `False` |
| `updated_at` | `float` | `field(default_factory=time.time)` |

### `RppgParamAbVerdict` — `rppg/adaptive_calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `verdict` | `str` | `'pending'` |
| `current_residual_bpm` | `float \| None` | `None` |
| `candidate_residual_bpm` | `float \| None` | `None` |
| `pairs_used` | `int` | `0` |
| `improve_streak` | `int` | `0` |
| `worsen_streak` | `int` | `0` |

### `RppgParamCoordinatorState` — `rppg/adaptive_calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `phase` | `str` | `COORD_IDLE` |
| `candidate_roi_weights` | `Optional[dict[str, float]]` | `None` |
| `verdict` | `Optional[RppgParamAbVerdict]` | `None` |
| `adopted_roi_weights` | `Optional[dict[str, float]]` | `None` |
| `cooldown_until` | `float` | `0.0` |
| `updated_at` | `float` | `field(default_factory=time.time)` |

### `BeltTruthCaptureRecord` — `rppg/belt_truth_capture.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `t` | `float` | `必填` |
| `roi_means` | `dict[str, tuple[float, float, float]]` | `必填` |
| `belt_bpm` | `Optional[float]` | `None` |

### `CalibrationParams` — `rppg/calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `bpm_offset` | `float` | `0.0` |
| `bpm_scale` | `float` | `1.0` |
| `rppg_params` | `dict[str, Any] \| None` | `None` |

### `CalibrationVersion` — `rppg/calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `id` | `str` | `必填` |
| `name` | `str` | `必填` |
| `model` | `str` | `必填` |
| `params` | `CalibrationParams` | `必填` |
| `created_at` | `str` | `''` |
| `builtin` | `bool` | `False` |
| `note` | `str` | `''` |
| `session` | `dict[str, Any] \| None` | `None` |
| `metrics` | `dict[str, Any] \| None` | `None` |

### `WindowResidual` — `rppg/calibration.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `start_ts` | `float` | `必填` |
| `end_ts` | `float` | `必填` |
| `watch_median` | `float` | `必填` |
| `rppg_median` | `float` | `必填` |
| `residual` | `float` | `必填` |
| `accepted` | `bool` | `必填` |
| `reason` | `str` | `''` |

### `Metrics` — `rppg/demo_rppg_live.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `bpm` | `float` | `0.0` |
| `rmssd` | `float` | `0.0` |
| `sdnn` | `float` | `0.0` |
| `lf_hf` | `float` | `0.0` |
| `sqi` | `float` | `0.0` |
| `stress_prob` | `float` | `0.0` |
| `stress_status` | `str` | `'-'` |
| `hrv_confidence` | `str` | `'LOW'` |
| `ibi_artifact_ratio` | `float` | `0.0` |
| `peak_freq_hz` | `float` | `0.0` |
| `frame_brightness` | `float` | `0.0` |
| `warmup_progress` | `float` | `0.0` |
| `quality_score` | `float` | `0.0` |
| `pose_roll_deg` | `float` | `0.0` |
| `pose_yaw_deg` | `float` | `0.0` |
| `pose_pitch_deg` | `float` | `0.0` |
| `roi_valid_count` | `int` | `0` |
| `waveform` | `list[float] \| None` | `None` |
| `psd_freqs` | `list[float] \| None` | `None` |
| `psd_vals` | `list[float] \| None` | `None` |

### `HrBeltConfig` — `rppg/hr_belt_ble.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `name_prefix` | `str` | `DEFAULT_NAME_PREFIX` |
| `address` | `str` | `''` |
| `scan_timeout_sec` | `float` | `6.0` |
| `reconnect_delay_sec` | `float` | `3.0` |
| `rppg_param_tuning_enabled` | `bool` | `False` |
| `capture_enabled` | `bool` | `False` |

### `HeartRateMeasurement` — `rppg/hr_belt_ble.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `bpm` | `int` | `必填` |
| `sensor_contact_supported` | `bool` | `False` |
| `sensor_contact_detected` | `bool` | `False` |
| `energy_expended_kj` | `int \| None` | `None` |
| `rr_intervals_ms` | `tuple[float, ...]` | `()` |
| `flags` | `int` | `0` |

### `HrBeltStatus` — `rppg/hr_belt_ble.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `state` | `str` | `'idle'` |
| `device_name` | `str` | `''` |
| `device_address` | `str` | `''` |
| `rssi` | `float` | `0.0` |
| `battery_level` | `int \| None` | `None` |
| `sensor_location` | `str` | `''` |
| `bpm` | `int` | `0` |
| `rr_count` | `int` | `0` |
| `sensor_contact_supported` | `bool` | `False` |
| `sensor_contact_detected` | `bool` | `False` |
| `notifications` | `int` | `0` |
| `last_error` | `str` | `''` |
| `connected_since` | `float \| None` | `None` |
| `last_sample_at` | `float \| None` | `None` |
| `updated_at` | `float` | `field(default_factory=time.time)` |

### `RppgHrvResult` — `rppg/rppg_hrv_engine.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `status` | `str` | `'BUFFERING'` |
| `rmssd` | `float` | `0.0` |
| `sdnn` | `float` | `0.0` |
| `lf_hf` | `float` | `0.0` |
| `bpm` | `float` | `0.0` |
| `artifact_ratio` | `float` | `1.0` |
| `ibi_sqi` | `float` | `0.0` |
| `n_ibis` | `int` | `0` |
| `n_peaks` | `int` | `0` |
| `progress` | `float` | `0.0` |
| `message` | `str` | `''` |

### `RppgMetrics` — `rppg/rppg_worker.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `bpm` | `float` | `0.0` |
| `raw_bpm` | `float` | `0.0` |
| `bpm_delta` | `float` | `0.0` |
| `bpm_guarded` | `bool` | `False` |
| `bpm_guard_reason` | `str` | `''` |
| `rmssd` | `float` | `0.0` |
| `sdnn` | `float` | `0.0` |
| `lf_hf` | `float` | `0.0` |
| `sqi` | `float` | `0.0` |
| `stress_prob` | `float` | `0.0` |
| `stress_status` | `str` | `'calibrating'` |
| `hrv_confidence` | `str` | `'LOW'` |
| `ibi_artifact_ratio` | `float` | `0.0` |
| `peak_freq_hz` | `float` | `0.0` |
| `frame_brightness` | `float` | `0.0` |
| `warmup_progress` | `float` | `0.0` |
| `quality_score` | `float` | `0.0` |
| `pose_roll_deg` | `float` | `0.0` |
| `pose_yaw_deg` | `float` | `0.0` |
| `pose_pitch_deg` | `float` | `0.0` |
| `roi_valid_count` | `int` | `0` |
| `roi_weight_forehead` | `float` | `0.0` |
| `roi_weight_l_cheek` | `float` | `0.0` |
| `roi_weight_r_cheek` | `float` | `0.0` |
| `roi_weight_glabella` | `float` | `0.0` |
| `landmark_jitter_norm` | `float` | `0.0` |
| `roi_area_stability` | `float` | `1.0` |
| `roi_area_jitter_ratio` | `float` | `0.0` |
| `roi_smoothing_applied` | `bool` | `False` |
| `canonical_roi_warp_used` | `bool` | `False` |
| `face_detected` | `bool` | `False` |
| `bpm_calibrated` | `float` | `0.0` |
| `calibration_version_id` | `str` | `''` |
| `peak_freq_hz_calibrated` | `float` | `0.0` |
| `waveform` | `list[float]` | `field(default_factory=list)` |
| `psd_freqs` | `list[float]` | `field(default_factory=list)` |
| `psd_vals` | `list[float]` | `field(default_factory=list)` |
| `physio_source` | `str` | `'rppg'` |

### `WatchPhysioState` — `rppg/watch_physio.py`

| 欄位 | 型別 | 預設值 |
| --- | --- | --- |
| `rmssd` | `float` | `0.0` |
| `sdnn` | `float` | `0.0` |
| `lf_hf` | `float` | `0.0` |
| `stress_prob` | `float` | `0.0` |
| `stress_status` | `str` | `'calibrating'` |
| `hrv_confidence` | `str` | `'LOW'` |
| `ibi_artifact_ratio` | `float` | `1.0` |
| `hrv_ready` | `bool` | `False` |
| `sample_count` | `int` | `0` |
| `ibi_count` | `int` | `0` |
| `sqi` | `float` | `0.0` |
| `quality_score` | `float` | `0.0` |
| `warmup_progress` | `float` | `0.0` |
| `bpm_delta` | `float` | `0.0` |
| `bpm_guarded` | `bool` | `False` |
| `bpm_guard_reason` | `str` | `''` |
| `peak_freq_hz` | `float` | `0.0` |
| `pose_roll_deg` | `float` | `0.0` |
| `pose_yaw_deg` | `float` | `0.0` |
| `pose_pitch_deg` | `float` | `0.0` |
| `motion_level` | `float \| None` | `None` |
| `imu_gate` | `float` | `1.0` |
| `lf_hf_window_ok` | `bool` | `False` |
| `waveform` | `list[float]` | `field(default_factory=list)` |
| `psd_freqs` | `list[float]` | `field(default_factory=list)` |
| `psd_vals` | `list[float]` | `field(default_factory=list)` |

## 3. Desktop 命令與 Web 入口

字面命令的參數、validation 與副作用，以 handler／strict contract 為準；API v2 控制僅限合法本機來源。

`alarm.configure`, `alarm.test`, `analysis.configure`, `app.shutdown`, `auto_capture.configure`, `auto_capture.set`, `baseline.start`, `camera.configure`, `camera.refresh`, `camera.select`, `hotkeys.configure`, `monitor.layout`, `overlay.configure`, `pipeline.set`, `preferences.configure`, `recording.set`, `replay.configure`, `replay.set`, `settings.action`, `settings.reset`, `settings.save`, `state.get`, `user_profile.configure`

| 路由／事件 | 宣告 | handler |
| --- | --- | --- |
| `/` | `app.route` | `index` |
| `/api/recordings` | `app.route` | `get_recordings` |
| `/api/metrics` | `app.route` | `get_metrics_snapshot` |
| `/api/control/state` | `app.['GET', 'OPTIONS']` | `get_control_state` |
| `/api/control/command` | `app.['POST', 'OPTIONS']` | `run_control_command` |
| `/api/playback` | `app.route` | `playback_data` |
| `/api/playback/full` | `app.route` | `playback_full` |
| `/api/video/<path:filename>` | `app.route` | `serve_video` |
| `/api/fb/login` | `app.['POST']` | `fb_login` |
| `/api/fb/status` | `app.route` | `fb_status` |
| `/api/fb/logout` | `app.['POST']` | `fb_logout` |
| `/api/fb/recordings` | `app.route` | `fb_recordings` |
| `/api/fb/cache-db` | `app.['POST']` | `fb_cache_db` |
| `/api/fb/stream-video` | `app.route` | `fb_stream_video` |
| `/api/fb/upload` | `app.['POST']` | `fb_upload` |
| `/api/fb/delete` | `app.['DELETE']` | `fb_delete` |
| `/api/fb/download` | `app.route` | `fb_download` |
| `connect` | `socketio.on` | `handle_connect` |
| `disconnect` | `socketio.on` | `handle_disconnect` |
| `request_metrics` | `socketio.on` | `handle_metrics_request` |

## 4. 非 Python 程式與部署範圍

其他語言以下列語法標記盤點，不冒充完整型別解析。框架 scaffold 與 mobile stub 也列出，不能當作已完成的 native inference。

| 檔案 | 宣告／範圍 |
| --- | --- |
| [.github/workflows/repository-hygiene.yml](../../.github/workflows/repository-hygiene.yml) | 平台啟動／建置／設定；16 行 |
| [config/mediapipe_tuning.json](../../config/mediapipe_tuning.json) | 平台啟動／建置／設定；89 行 |
| [flutter_app/analysis_options.yaml](../../flutter_app/analysis_options.yaml) | 平台啟動／建置／設定；11 行 |
| [flutter_app/android/app/src/main/kotlin/tw/fatigue_monitor/fatigue_monitor_ui/MainActivity.kt](../../flutter_app/android/app/src/main/kotlin/tw/fatigue_monitor/fatigue_monitor_ui/MainActivity.kt) | `MainActivity`, `configureFlutterEngine` |
| [flutter_app/lib/main.dart](../../flutter_app/lib/main.dart) | `FatigueMonitorApp`, `MobileRuntimeUnavailableShell`, `DesktopNotice`, `MonitorShell`, `_MonitorShellState`, `OverlayShell`, `_OverlayShellState`, `_OverlayMetric`, `AppTitleBar`, `WindowButton`, `_WindowButtonState`, `NavigationRailPanel`, `_NavItem`, `DashboardView`, `_FocusDashboard`, `CameraPreview`, `DesktopControlPanel`, `_ConnectionPill`, `_StatusPanel`, `_SignalPanel`, `ChestBeltView`, `_BeltDetailRow`, `HeartRateBeltPanel`, `_BeltStatusPill`, `_BeltReadout`, `MetricTile`, `_MetricTileState`, `_QualityStrip`, `PlaybackView`, `_ReplayControlPanel`, `_ReplayControlPanelState`, `_PlaybackDetail`, `SettingsView`, `_AlarmDialog`, `_AlarmDialogState`, `_UserProfileDialog`, `_UserProfileDialogState`, `_HotkeysDialog`, `_HotkeysDialogState`, `_OverlayOpacityControl`, `_OverlayOpacityControlState`, `_SettingDropdown`, `_SettingSwitch`, `GlassPanel`, `_InlineNotice`, `EmptyState`, `StatusRingPainter` |
| [flutter_app/lib/models/backend_contract.dart](../../flutter_app/lib/models/backend_contract.dart) | `MetricsSnapshot`, `ControlState`, `RecordingMetadata`, `ApiError` |
| [flutter_app/lib/models/mobile_runtime_contract.dart](../../flutter_app/lib/models/mobile_runtime_contract.dart) | `RuntimePermission`, `PermissionState`, `ForegroundState`, `ModelRuntimeState`, `CameraPixelFormat`, `MobileRuntimeChannelContract`, `CameraConfiguration`, `CameraFrame`, `UnsupportedMobileRuntimeAdapter`, `MobileRuntimeChannelAdapter`, `MobileRuntimeChannelError` |
| [flutter_app/lib/models/platform_contract.dart](../../flutter_app/lib/models/platform_contract.dart) | `AppPlatform`, `PlatformCapabilities`, `PlatformCapabilityNames`, `UnsupportedPlatformRuntimeError` |
| [flutter_app/lib/services/backend_service.dart](../../flutter_app/lib/services/backend_service.dart) | `BackendService` |
| [flutter_app/lib/services/tauri_bridge.dart](../../flutter_app/lib/services/tauri_bridge.dart) | 平台啟動／建置／設定；2 行 |
| [flutter_app/lib/services/tauri_bridge_stub.dart](../../flutter_app/lib/services/tauri_bridge_stub.dart) | `TauriBridge` |
| [flutter_app/lib/services/tauri_bridge_web.dart](../../flutter_app/lib/services/tauri_bridge_web.dart) | `TauriBridge` |
| [flutter_app/native/mobile_runtime/android/MobileRuntimePlugin.kt](../../flutter_app/native/mobile_runtime/android/MobileRuntimePlugin.kt) | `MobileRuntimePlugin`, `onAttachedToEngine`, `onDetachedFromEngine`, `onMethodCall`, `onListen`, `onCancel`, `unavailable` |
| [flutter_app/native/mobile_runtime/ios/MobileRuntimePlugin.swift](../../flutter_app/native/mobile_runtime/ios/MobileRuntimePlugin.swift) | `MobileRuntimePlugin`, `register`, `handle`, `onListen`, `onCancel`, `unavailable` |
| [flutter_app/pubspec.yaml](../../flutter_app/pubspec.yaml) | 平台啟動／建置／設定；21 行 |
| [flutter_app/test/backend_service_test.dart](../../flutter_app/test/backend_service_test.dart) | `_TrackingClient` |
| [flutter_app/test/dashboard_focus_test.dart](../../flutter_app/test/dashboard_focus_test.dart) | 平台啟動／建置／設定；120 行 |
| [flutter_app/test/desktop_notice_test.dart](../../flutter_app/test/desktop_notice_test.dart) | 平台啟動／建置／設定；30 行 |
| [flutter_app/test/mobile_runtime_channel_test.dart](../../flutter_app/test/mobile_runtime_channel_test.dart) | 平台啟動／建置／設定；165 行 |
| [flutter_app/test/overlay_shell_test.dart](../../flutter_app/test/overlay_shell_test.dart) | 平台啟動／建置／設定；186 行 |
| [flutter_app/test/platform_contract_test.dart](../../flutter_app/test/platform_contract_test.dart) | 平台啟動／建置／設定；172 行 |
| [flutter_app/test/replay_view_test.dart](../../flutter_app/test/replay_view_test.dart) | 平台啟動／建置／設定；177 行 |
| [flutter_app/test/settings_view_test.dart](../../flutter_app/test/settings_view_test.dart) | 平台啟動／建置／設定；324 行 |
| [package.json](../../package.json) | 平台啟動／建置／設定；13 行 |
| [pyrightconfig.json](../../pyrightconfig.json) | 平台啟動／建置／設定；7 行 |
| [scripts/build_desktop.ps1](../../scripts/build_desktop.ps1) | 平台啟動／建置／設定；30 行 |
| [scripts/build_desktop_linux.sh](../../scripts/build_desktop_linux.sh) | 平台啟動／建置／設定；18 行 |
| [scripts/build_desktop_macos.sh](../../scripts/build_desktop_macos.sh) | 平台啟動／建置／設定；16 行 |
| [scripts/build_engine_sidecar.ps1](../../scripts/build_engine_sidecar.ps1) | 平台啟動／建置／設定；12 行 |
| [scripts/prepare_engine_sidecar.mjs](../../scripts/prepare_engine_sidecar.mjs) | 平台啟動／建置／設定；32 行 |
| [scripts/setup_ubuntu.sh](../../scripts/setup_ubuntu.sh) | 平台啟動／建置／設定；76 行 |
| [scripts/start_desktop.ps1](../../scripts/start_desktop.ps1) | 平台啟動／建置／設定；53 行 |
| [scripts/start_desktop_linux.sh](../../scripts/start_desktop_linux.sh) | 平台啟動／建置／設定；20 行 |
| [scripts/start_desktop_macos.sh](../../scripts/start_desktop_macos.sh) | 平台啟動／建置／設定；23 行 |
| [src-tauri/Cargo.toml](../../src-tauri/Cargo.toml) | 平台啟動／建置／設定；23 行 |
| [src-tauri/Entitlements.plist](../../src-tauri/Entitlements.plist) | 平台啟動／建置／設定；10 行 |
| [src-tauri/Info.plist](../../src-tauri/Info.plist) | 平台啟動／建置／設定；10 行 |
| [src-tauri/build.rs](../../src-tauri/build.rs) | `main` |
| [src-tauri/capabilities/default.json](../../src-tauri/capabilities/default.json) | 平台啟動／建置／設定；14 行 |
| [src-tauri/capabilities/overlay.json](../../src-tauri/capabilities/overlay.json) | 平台啟動／建置／設定；7 行 |
| [src-tauri/src/main.rs](../../src-tauri/src/main.rs) | `BackendProcess`, `DesktopShutdown`, `SystemInfo`, `OverlayGeometry`, `validate_overlay_geometry`, `read_overlay_geometry`, `get_system_info`, `minimize_window`, `toggle_maximize_window`, `close_window`, `start_dragging`, `toggle_always_on_top`, `validate_external_directory`, `validate_external_url`, `open_external_target`, `open_camera_privacy_settings`, `open_external_path`, `open_external_url`, `path_to_frontend_string`, `pick_replay_folder`, `overlay_url`, `set_overlay_window`, `get_overlay_geometry`, `backend_address`, `backend_available`, `backend_api_version_from_response`, `backend_api_compatible`, `project_root`, `python_executable`, `bundled_engine_path`, `engine_path_for_mode`, `bundled_resource_root`, `hide_backend_console`, `isolate_backend_process_tree`, `kill_backend_process_tree`, `spawn_backend`, `request_backend_shutdown`, `stop_owned_backend`, `begin_desktop_shutdown`, `shutdown_desktop`, `run`, `run_app`, `main` |
| [src-tauri/tauri.conf.json](../../src-tauri/tauri.conf.json) | 平台啟動／建置／設定；57 行 |
| [src-tauri/tauri.linux.conf.json](../../src-tauri/tauri.linux.conf.json) | 平台啟動／建置／設定；20 行 |
| [src-tauri/tauri.macos.conf.json](../../src-tauri/tauri.macos.conf.json) | 平台啟動／建置／設定；27 行 |
| [src-tauri/tauri.windows.conf.json](../../src-tauri/tauri.windows.conf.json) | 平台啟動／建置／設定；12 行 |
| [tools/canva-flowchart/canva-app.json](../../tools/canva-flowchart/canva-app.json) | 平台啟動／建置／設定；21 行 |
| [tools/canva-flowchart/declarations/declarations.d.ts](../../tools/canva-flowchart/declarations/declarations.d.ts) | 平台啟動／建置／設定；29 行 |
| [tools/canva-flowchart/eslint.config.mjs](../../tools/canva-flowchart/eslint.config.mjs) | 平台啟動／建置／設定；14 行 |
| [tools/canva-flowchart/jest.config.mjs](../../tools/canva-flowchart/jest.config.mjs) | 平台啟動／建置／設定；38 行 |
| [tools/canva-flowchart/jest.setup.ts](../../tools/canva-flowchart/jest.setup.ts) | 平台啟動／建置／設定；35 行 |
| [tools/canva-flowchart/package.json](../../tools/canva-flowchart/package.json) | 平台啟動／建置／設定；98 行 |
| [tools/canva-flowchart/scripts/copy_env.ts](../../tools/canva-flowchart/scripts/copy_env.ts) | 平台啟動／建置／設定；13 行 |
| [tools/canva-flowchart/scripts/ssl/ssl.ts](../../tools/canva-flowchart/scripts/ssl/ssl.ts) | 平台啟動／建置／設定；131 行 |
| [tools/canva-flowchart/scripts/start/app_runner.ts](../../tools/canva-flowchart/scripts/start/app_runner.ts) | `getModifierKey`, `AppRunner` |
| [tools/canva-flowchart/scripts/start/context.ts](../../tools/canva-flowchart/scripts/start/context.ts) | `Context` |
| [tools/canva-flowchart/scripts/start/start.ts](../../tools/canva-flowchart/scripts/start/start.ts) | 平台啟動／建置／設定；46 行 |
| [tools/canva-flowchart/scripts/start/tests/start.tests.ts](../../tools/canva-flowchart/scripts/start/tests/start.tests.ts) | 平台啟動／建置／設定；61 行 |
| [tools/canva-flowchart/src/index.tsx](../../tools/canva-flowchart/src/index.tsx) | 平台啟動／建置／設定；4 行 |
| [tools/canva-flowchart/src/intents/design_editor/app.tsx](../../tools/canva-flowchart/src/intents/design_editor/app.tsx) | 平台啟動／建置／設定；262 行 |
| [tools/canva-flowchart/src/intents/design_editor/index.tsx](../../tools/canva-flowchart/src/intents/design_editor/index.tsx) | `render` |
| [tools/canva-flowchart/src/intents/design_editor/tests/app.tests.tsx](../../tools/canva-flowchart/src/intents/design_editor/tests/app.tests.tsx) | `renderInTestProvider` |
| [tools/canva-flowchart/test_mocks/fileMock.ts](../../tools/canva-flowchart/test_mocks/fileMock.ts) | 平台啟動／建置／設定；1 行 |
| [tools/canva-flowchart/tsconfig.json](../../tools/canva-flowchart/tsconfig.json) | 平台啟動／建置／設定；56 行 |
| [tools/canva-flowchart/webpack.config.ts](../../tools/canva-flowchart/webpack.config.ts) | `buildConfig`, `buildDevConfig` |

## 5. 調校 JSON 與錄製 schema

active profile 會與父設定合併，有效值以 load_mediapipe_tuning() 為準。機器／個人校準與秘密值不納入。

```json
{
  "active_profile": "stable_indoor",
  "face_landmarker": {
    "min_face_detection_confidence": 0.55,
    "min_face_presence_confidence": 0.55,
    "min_tracking_confidence": 0.6,
    "num_faces": 1
  },
  "rppg_roi": {
    "base_weights": {
      "forehead": 0.34,
      "L_cheek": 0.25,
      "R_cheek": 0.25,
      "glabella": 0.16
    },
    "roll_full_penalty_deg": 42.0,
    "yaw_full_penalty_deg": 42.0,
    "pitch_free_deg": 8.0,
    "pitch_full_penalty_deg": 34.0,
    "obstruction_dark_luma": 35.0,
    "obstruction_bright_luma": 232.0,
    "obstruction_low_chroma": 2.5,
    "obstruction_high_chroma": 48.0,
    "min_roi_weight": 0.04,
    "roi_smoothing_enabled": true,
    "roi_smoothing_alpha": 0.30,
    "roi_smoothing_max_shift_ratio": 0.12,
    "landmark_jitter_full_norm": 0.02,
    "roi_area_jitter_full_ratio": 0.25,
    "canonical_roi_warp_enabled": false,
    "canonical_roi_warp_strength": 0.35
  },
  "quality": {
    "pose_weight": 0.3,
    "motion_weight": 0.25,
    "coverage_weight": 0.25,
    "roi_weight": 0.2,
    "signal_weight": 0.45,
    "face_weight": 0.55
  },
  "blendshape": {
    "calib_sec": 4.0,
    "min_samples": 24,
    "ema_alpha": 0.22,
    "blink_gate": 0.2,
    "squint_gate": 0.18,
    "brow_gate": 0.18,
    "jaw_gate": 0.2
  },
  "profiles": {
    "stable_indoor": {
      "face_landmarker": {
        "min_face_detection_confidence": 0.6,
        "min_face_presence_confidence": 0.6,
        "min_tracking_confidence": 0.7,
        "num_faces": 1
      },
      "rppg_roi": {
        "roi_smoothing_alpha": 0.30,
        "roi_smoothing_max_shift_ratio": 0.10
      }
    },
    "low_light": {
      "face_landmarker": {
        "min_face_detection_confidence": 0.45,
        "min_face_presence_confidence": 0.50,
        "min_tracking_confidence": 0.55,
        "num_faces": 1
      },
      "rppg_roi": {
        "obstruction_dark_luma": 28.0,
        "roi_smoothing_alpha": 0.40
      }
    },
    "high_motion": {
      "face_landmarker": {
        "min_face_detection_confidence": 0.60,
        "min_face_presence_confidence": 0.60,
        "min_tracking_confidence": 0.75,
        "num_faces": 1
      },
      "rppg_roi": {
        "roi_smoothing_alpha": 0.50,
        "roi_smoothing_max_shift_ratio": 0.18,
        "landmark_jitter_full_norm": 0.015
      }
    }
  }
}
```

### SQLite metrics 欄位（103 個）

`timestamp`, `fps`, `frame_width`, `frame_height`, `codec`, `camera_label`, `rppg_face_detected`, `bpm`, `raw_bpm`, `bpm_delta`, `bpm_guarded`, `bpm_guard_reason`, `rmssd`, `sdnn`, `lf_hf`, `sqi`, `rppg_quality_score`, `rppg_pose_roll_deg`, `rppg_pose_yaw_deg`, `rppg_pose_pitch_deg`, `rppg_roi_valid_count`, `rppg_roi_weight_forehead`, `rppg_roi_weight_l_cheek`, `rppg_roi_weight_r_cheek`, `rppg_roi_weight_glabella`, `rppg_landmark_jitter_norm`, `rppg_roi_area_stability`, `rppg_roi_area_jitter_ratio`, `rppg_roi_smoothing_applied`, `rppg_canonical_roi_warp_used`, `stress_prob`, `stress_status`, `hrv_confidence`, `ibi_artifact_ratio`, `peak_freq_hz`, `frame_brightness`, `warmup_progress`, `fatigue_face_detected`, `calibrated`, `status`, `fatigue_level`, `early_warning`, `ear`, `ear_smooth`, `blink_count`, `perclos`, `blink_rate_pm`, `blink_duration_sec`, `blink_duration_mean_sec`, `blink_duration_z`, `blink_amplitude`, `blink_opening_velocity`, `blink_opening_velocity_z`, `blink_temporal_score`, `is_squinting`, `squint_duration`, `is_frowning`, `brow_dist_norm`, `iris_ratio`, `iris_ratio_trend`, `gaze_x`, `gaze_y`, `gaze_stability_index`, `gaze_mental_fatigue`, `saccadic_velocity`, `is_saccade`, `fixation_duration`, `saccade_freq_pm`, `head_pitch`, `head_yaw`, `head_roll`, `fatigue_quality_score`, `fatigue_blend_calib_progress`, `microsleep_alert`, `microsleep_count`, `mar`, `yawn_detected`, `yawn_count`, `has_iris`, `calib_progress`, `fused_score`, `fused_level`, `fused_level_en`, `fused_rppg_sub`, `fused_behavior_sub`, `fused_rppg_weight_eff`, `fused_behavior_weight_eff`, `fused_trend`, `fused_trend_symbol`, `fused_rppg_available`, `fused_behavior_available`, `fused_rppg_stress_score`, `fused_rppg_bpm_score`, `fused_beh_perclos_score`, `fused_beh_blink_temporal_score`, `fused_beh_squint_score`, `fused_beh_microsleep_score`, `fused_beh_gaze_score`, `fused_beh_frown_score`, `fused_beh_yawn_score`, `bpm_calibrated`, `calibration_version_id`, `peak_freq_hz_calibrated`

id 為自動主鍵；timestamp 索引、WAL、batch、meta 契約見 MetricsRecorder。live API 的 percent／名稱投影不等同 DB 欄位。

## 6. 測試入口

函式宣告數不等於 parametrized case 數或 coverage 百分比。

| 檔案 | 測試函式宣告數 |
| --- | --- |
| [flutter_app/test/backend_service_test.dart](../../flutter_app/test/backend_service_test.dart) | 6 |
| [flutter_app/test/dashboard_focus_test.dart](../../flutter_app/test/dashboard_focus_test.dart) | 4 |
| [flutter_app/test/desktop_notice_test.dart](../../flutter_app/test/desktop_notice_test.dart) | 3 |
| [flutter_app/test/mobile_runtime_channel_test.dart](../../flutter_app/test/mobile_runtime_channel_test.dart) | 4 |
| [flutter_app/test/overlay_shell_test.dart](../../flutter_app/test/overlay_shell_test.dart) | 10 |
| [flutter_app/test/platform_contract_test.dart](../../flutter_app/test/platform_contract_test.dart) | 8 |
| [flutter_app/test/replay_view_test.dart](../../flutter_app/test/replay_view_test.dart) | 5 |
| [flutter_app/test/settings_view_test.dart](../../flutter_app/test/settings_view_test.dart) | 9 |
| [tests/test_adaptive_calibration.py](../../tests/test_adaptive_calibration.py) | 51 |
| [tests/test_alarm_controller.py](../../tests/test_alarm_controller.py) | 11 |
| [tests/test_belt_truth_capture.py](../../tests/test_belt_truth_capture.py) | 31 |
| [tests/test_camera_backend_benchmark.py](../../tests/test_camera_backend_benchmark.py) | 1 |
| [tests/test_camera_diagnostics.py](../../tests/test_camera_diagnostics.py) | 1 |
| [tests/test_capture_preferences_state.py](../../tests/test_capture_preferences_state.py) | 6 |
| [tests/test_desktop_control_api.py](../../tests/test_desktop_control_api.py) | 13 |
| [tests/test_desktop_engine_benchmark.py](../../tests/test_desktop_engine_benchmark.py) | 4 |
| [tests/test_desktop_hardware_smoke.py](../../tests/test_desktop_hardware_smoke.py) | 9 |
| [tests/test_desktop_settings_api.py](../../tests/test_desktop_settings_api.py) | 105 |
| [tests/test_desktop_shell_config.py](../../tests/test_desktop_shell_config.py) | 17 |
| [tests/test_downgaze_gate.py](../../tests/test_downgaze_gate.py) | 14 |
| [tests/test_engine_controller_camera.py](../../tests/test_engine_controller_camera.py) | 6 |
| [tests/test_engine_controller_lifecycle.py](../../tests/test_engine_controller_lifecycle.py) | 13 |
| [tests/test_engine_runtime.py](../../tests/test_engine_runtime.py) | 15 |
| [tests/test_engine_sidecar_build.py](../../tests/test_engine_sidecar_build.py) | 3 |
| [tests/test_eye_closure_channel.py](../../tests/test_eye_closure_channel.py) | 8 |
| [tests/test_fatigue_engine_behavior.py](../../tests/test_fatigue_engine_behavior.py) | 15 |
| [tests/test_fatigue_scorer.py](../../tests/test_fatigue_scorer.py) | 10 |
| [tests/test_file_browser_client.py](../../tests/test_file_browser_client.py) | 2 |
| [tests/test_flutter_command_contract.py](../../tests/test_flutter_command_contract.py) | 1 |
| [tests/test_global_hotkeys.py](../../tests/test_global_hotkeys.py) | 8 |
| [tests/test_hr_belt_ble.py](../../tests/test_hr_belt_ble.py) | 47 |
| [tests/test_installed_desktop_smoke.py](../../tests/test_installed_desktop_smoke.py) | 6 |
| [tests/test_launcher.py](../../tests/test_launcher.py) | 3 |
| [tests/test_macos_camera_support.py](../../tests/test_macos_camera_support.py) | 6 |
| [tests/test_main_window_camera_controller.py](../../tests/test_main_window_camera_controller.py) | 3 |
| [tests/test_mediapipe_enhancements.py](../../tests/test_mediapipe_enhancements.py) | 11 |
| [tests/test_metrics_recorder.py](../../tests/test_metrics_recorder.py) | 7 |
| [tests/test_model_assets.py](../../tests/test_model_assets.py) | 6 |
| [tests/test_overlay_runtime_state.py](../../tests/test_overlay_runtime_state.py) | 9 |
| [tests/test_packaged_runtime_consumers.py](../../tests/test_packaged_runtime_consumers.py) | 6 |
| [tests/test_personal_baseline_worker.py](../../tests/test_personal_baseline_worker.py) | 2 |
| [tests/test_personal_profile.py](../../tests/test_personal_profile.py) | 19 |
| [tests/test_platform_runtime.py](../../tests/test_platform_runtime.py) | 15 |
| [tests/test_prepare_local_assets.py](../../tests/test_prepare_local_assets.py) | 3 |
| [tests/test_replay_runtime_state.py](../../tests/test_replay_runtime_state.py) | 7 |
| [tests/test_repository_hygiene.py](../../tests/test_repository_hygiene.py) | 3 |
| [tests/test_rppg_calibration.py](../../tests/test_rppg_calibration.py) | 17 |
| [tests/test_rppg_param_coordinator_wiring.py](../../tests/test_rppg_param_coordinator_wiring.py) | 24 |
| [tests/test_rppg_param_replay.py](../../tests/test_rppg_param_replay.py) | 18 |
| [tests/test_rppg_params_apply.py](../../tests/test_rppg_params_apply.py) | 28 |
| [tests/test_rppg_signal_processing.py](../../tests/test_rppg_signal_processing.py) | 20 |
| [tests/test_rppg_worker_roi_buffer.py](../../tests/test_rppg_worker_roi_buffer.py) | 9 |
| [tests/test_runtime_paths.py](../../tests/test_runtime_paths.py) | 10 |
| [tests/test_ubuntu_camera_support.py](../../tests/test_ubuntu_camera_support.py) | 11 |
| [tests/test_utarldd_accuracy.py](../../tests/test_utarldd_accuracy.py) | 20 |
| [tests/test_utarldd_golden.py](../../tests/test_utarldd_golden.py) | 14 |
| [tests/test_utarldd_replay.py](../../tests/test_utarldd_replay.py) | 21 |
| [tests/test_video_recorder_lifecycle.py](../../tests/test_video_recorder_lifecycle.py) | 2 |
| [tests/test_watch_metrics.py](../../tests/test_watch_metrics.py) | 4 |
| [tests/test_web_playback_utarldd.py](../../tests/test_web_playback_utarldd.py) | 10 |
| [tests/test_web_preferences_state.py](../../tests/test_web_preferences_state.py) | 4 |
| [tests/test_web_socketio_dashboard.py](../../tests/test_web_socketio_dashboard.py) | 25 |

本次清冊數量：{"python_files": 74, "functions": 934, "dataclass_fields": 581, "other_files": 64, "test_files": 62}。第三方套件、虛擬環境、快取、產出物與機密檔不納入。

## 7. 其他建置資產與輔助檔

補列 HTML／CSS、Android manifest／Gradle、型別 stub、lockfile、測試與 Git 設定。僅列路徑及責任範圍，不讀取環境檔內容；binary Gradle wrapper 不作原始碼宣告分析。

- [.gitattributes](../../.gitattributes)
- [.gitignore](../../.gitignore)
- [README.md](../../README.md)
- [assets/alerts/.gitkeep](../../assets/alerts/.gitkeep)
- [flutter_app/.gitignore](../../flutter_app/.gitignore)
- [flutter_app/.metadata](../../flutter_app/.metadata)
- [flutter_app/README.md](../../flutter_app/README.md)
- [flutter_app/android/.gitignore](../../flutter_app/android/.gitignore)
- [flutter_app/android/app/build.gradle.kts](../../flutter_app/android/app/build.gradle.kts)
- [flutter_app/android/app/src/debug/AndroidManifest.xml](../../flutter_app/android/app/src/debug/AndroidManifest.xml)
- [flutter_app/android/app/src/main/AndroidManifest.xml](../../flutter_app/android/app/src/main/AndroidManifest.xml)
- [flutter_app/android/app/src/main/res/drawable-v21/launch_background.xml](../../flutter_app/android/app/src/main/res/drawable-v21/launch_background.xml)
- [flutter_app/android/app/src/main/res/drawable/launch_background.xml](../../flutter_app/android/app/src/main/res/drawable/launch_background.xml)
- [flutter_app/android/app/src/main/res/values-night/styles.xml](../../flutter_app/android/app/src/main/res/values-night/styles.xml)
- [flutter_app/android/app/src/main/res/values/styles.xml](../../flutter_app/android/app/src/main/res/values/styles.xml)
- [flutter_app/android/app/src/profile/AndroidManifest.xml](../../flutter_app/android/app/src/profile/AndroidManifest.xml)
- [flutter_app/android/build.gradle.kts](../../flutter_app/android/build.gradle.kts)
- [flutter_app/android/gradle.properties](../../flutter_app/android/gradle.properties)
- [flutter_app/android/gradle/wrapper/gradle-wrapper.jar](../../flutter_app/android/gradle/wrapper/gradle-wrapper.jar)
- [flutter_app/android/gradle/wrapper/gradle-wrapper.properties](../../flutter_app/android/gradle/wrapper/gradle-wrapper.properties)
- [flutter_app/android/gradlew](../../flutter_app/android/gradlew)
- [flutter_app/android/gradlew.bat](../../flutter_app/android/gradlew.bat)
- [flutter_app/android/settings.gradle.kts](../../flutter_app/android/settings.gradle.kts)
- [flutter_app/native/mobile_runtime/README.md](../../flutter_app/native/mobile_runtime/README.md)
- [flutter_app/pubspec.lock](../../flutter_app/pubspec.lock)
- [flutter_app/web/index.html](../../flutter_app/web/index.html)
- [package-lock.json](../../package-lock.json)
- [pytest.ini](../../pytest.ini)
- [requirements-dev.txt](../../requirements-dev.txt)
- [requirements.txt](../../requirements.txt)
- [src-tauri/Cargo.lock](../../src-tauri/Cargo.lock)
- [tools/canva-flowchart/.env.template](../../tools/canva-flowchart/.env.template)
- [tools/canva-flowchart/.gitignore](../../tools/canva-flowchart/.gitignore)
- [tools/canva-flowchart/.npmrc](../../tools/canva-flowchart/.npmrc)
- [tools/canva-flowchart/.nvmrc](../../tools/canva-flowchart/.nvmrc)
- [tools/canva-flowchart/.prettierrc](../../tools/canva-flowchart/.prettierrc)
- [tools/canva-flowchart/LICENSE.md](../../tools/canva-flowchart/LICENSE.md)
- [tools/canva-flowchart/README.md](../../tools/canva-flowchart/README.md)
- [tools/canva-flowchart/package-lock.json](../../tools/canva-flowchart/package-lock.json)
- [tools/canva-flowchart/src/intents/design_editor/tests/__snapshots__/app.tests.tsx.snap](../../tools/canva-flowchart/src/intents/design_editor/tests/__snapshots__/app.tests.tsx.snap)
- [tools/canva-flowchart/styles/components.css](../../tools/canva-flowchart/styles/components.css)
- [typings/pygrabber/__init__.pyi](../../typings/pygrabber/__init__.pyi)
- [typings/pygrabber/dshow_graph.pyi](../../typings/pygrabber/dshow_graph.pyi)
