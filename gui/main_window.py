from __future__ import annotations

import json
import queue
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QImageWriter, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.alarm_config import AlarmConfig
from gui.alarm_dialog import AlarmSettingsDialog
from gui.alarm_player import FatigueAlarmController
from gui.camera_stream_worker import CameraStreamWorker
from gui.combined_worker import CombinedWorker
from gui.dialogs import HotkeyConfig, HotkeySettingsDialog, UserProfile, UserProfileDialog
from gui.fatigue_scorer import FuserConfig
from gui.fatigue_worker import FatigueWorker
from gui.metrics_recorder import MetricsRecorder
from gui.belt_runtime import BeltRuntime
from gui.personal_profile import PersonalBaselineCollector, PersonalProfileStore
from gui.preview_overlay_window import PreviewOverlayWindow
from gui.video_replay import ReplayBatchResult, VideoReplayWorker, ReplayVideoSummary
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


def application_stylesheet() -> str:
    # 深色監控風視覺 token（僅視覺，不影響任何 signal/slot 或數值行為）：
    #   背景：#0d1117 最底 / #161b22 視窗 / #1c2128 卡片 / #21262d 輸入元件
    #   邊框：#30363d 一般 / #444c56 強調
    #   文字：#e6edf3 主 / #8b949e 次 / #6e7681 弱
    #   主色：#388bfd（hover #58a6ff）
    return """
    QWidget {
        background-color: #161b22;
        color: #e6edf3;
        font-size: 13px;
        font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
    }
    QMainWindow, QDialog {
        background-color: #0d1117;
    }
    QGroupBox {
        font-weight: 600;
        font-size: 13px;
        border: 1px solid #30363d;
        border-radius: 10px;
        margin-top: 14px;
        padding: 16px 14px 14px 14px;
        background-color: #1c2128;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: #8b949e;
    }
    QLabel#titleLabel {
        font-size: 24px;
        font-weight: 700;
        color: #e6edf3;
        letter-spacing: 0.5px;
    }
    QLabel#subtitleLabel {
        font-size: 12px;
        font-weight: 500;
        color: #8b949e;
        margin-bottom: 4px;
    }
    QLabel#hintLabel {
        color: #8b949e;
        font-size: 12px;
        font-weight: 500;
    }
    QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #21262d;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 6px 10px;
        min-height: 22px;
        font-size: 13px;
    }
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: #388bfd;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QPushButton {
        background-color: #21262d;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 8px 16px;
        min-height: 20px;
        font-weight: 500;
    }
    QPushButton:hover {
        background-color: #262c36;
        border-color: #444c56;
    }
    QPushButton:pressed {
        background-color: #1c2128;
    }
    QPushButton#primaryButton {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #388bfd, stop:1 #1f6feb);
        border: 1px solid #58a6ff;
        color: #ffffff;
        font-weight: 600;
        padding: 10px 22px;
    }
    QPushButton#primaryButton:hover {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #58a6ff, stop:1 #388bfd);
    }
    QPushButton#dangerButton {
        background-color: #2d1618;
        border-color: #da3633;
        color: #ffa198;
    }
    QCheckBox {
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid #444c56;
        background-color: #21262d;
    }
    QCheckBox::indicator:checked {
        background-color: #388bfd;
        border-color: #58a6ff;
    }
    QSlider::groove:horizontal {
        height: 6px;
        background: #21262d;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        width: 16px;
        margin: -6px 0;
        border-radius: 8px;
        background: #388bfd;
        border: 2px solid #58a6ff;
    }
    QScrollArea {
        border: none;
        background: transparent;
    }
    QFrame#statusBarFrame {
        background-color: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 13px;
    }
    QTextEdit, QPlainTextEdit {
        background-color: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 8px;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
    }
    QMenuBar {
        background-color: #0d1117;
        border-bottom: 1px solid #30363d;
        padding: 2px;
    }
    QMenuBar::item:selected {
        background-color: #21262d;
        border-radius: 4px;
    }
    QMenu {
        background-color: #1c2128;
        border: 1px solid #30363d;
        padding: 4px;
    }
    QMenu::item:selected {
        background-color: #388bfd;
        color: #ffffff;
    }
    QStatusBar {
        background-color: #0d1117;
        border-top: 1px solid #30363d;
        color: #8b949e;
    }
    """


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("rPPG 疲勞／生理訊號控制台")
        self.resize(1040, 720)
        self.setMinimumSize(880, 600)

        self._pipeline_running = False
        self._recording = False
        self._benchmark_active = False
        self._hotkeys = HotkeyConfig()
        self._user = UserProfile()

        self._preview_overlay = PreviewOverlayWindow()
        self._preview_overlay.move(100, 100)
        self._cam_thread: QThread | None = None
        self._cam_worker: CameraStreamWorker | None = None
        self._rppg_thread: QThread | None = None
        self._rppg_worker: RppgWorker | None = None
        self._bgr_queue: "queue.Queue | None" = None
        self._fatigue_thread: QThread | None = None
        self._fatigue_worker: FatigueWorker | None = None
        self._fatigue_queue: "queue.Queue | None" = None
        self._combined_thread: QThread | None = None
        self._combined_worker: CombinedWorker | None = None
        self._combined_queue: "queue.Queue | None" = None

        self._metrics_recorder: MetricsRecorder | None = None
        self._recording_db_path: Path | None = None
        self._recording_started_at: float | None = None
        self._recording_count: int = 0
        self._recording_video_path: Path | None = None
        self._video_thread: QThread | None = None
        self._video_worker: VideoRecorderWorker | None = None
        self._video_queue: "queue.Queue | None" = None
        self._frame_source: str | None = None
        self._record_source: str | None = None
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        self._last_camera_info = {"codec": "", "width": 0, "height": 0}
        self._last_fps: float = 0.0

        self._global_hotkey_enabled = sys.platform.startswith("win")
        self._global_hotkeys_registered = False
        self._global_hotkey_id_map: dict[int, QAction] = {}
        self._hotkey_failed_once: set[str] = set()
        self._pending_camera_index: int | None = None
        self._web_metrics_buffer = MetricsBuffer(maxsize=300)
        self._web_server: WebServerThread | None = None
        self._web_emit_interval = 0.25
        self._web_frame_interval = 1.0 / WEB_PREVIEW_TARGET_FPS
        self._web_last_emit = 0.0
        self._web_last_frame_emit = 0.0
        self._replay_thread: QThread | None = None
        self._replay_worker: VideoReplayWorker | None = None
        self._replay_dataset_dir: Path | None = None
        self._replay_stopping = False
        self._close_after_replay = False
        self._replay_mode_label = "回放中"
        self._replay_total_count = 0
        self._replay_done_count = 0
        self._replay_active_videos: dict[str, ReplayVideoSummary] = {}
        self._replay_recent_done: list[str] = []
        self._alarm_config = AlarmConfig.defaults()
        self._rppg_calibration_store = CalibrationVersionStore()
        # 個人清醒基線：跨 session 載入上次的 manual profile（無則 None → 行為門檻走預設）。
        self._personal_profile_store = PersonalProfileStore()
        self._personal_profile = self._personal_profile_store.load()
        # 啟動自動蒐集（暫定基線）與手動「記錄清醒基線」按鈕各自的蒐集器。
        self._auto_baseline_collector: PersonalBaselineCollector | None = None
        self._manual_baseline_collector: PersonalBaselineCollector | None = None
        self._belt_runtime = BeltRuntime()
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
        self._belt_ui_timer = QTimer(self)
        self._belt_ui_timer.setInterval(1000)
        self._belt_ui_timer.timeout.connect(self._tick_belt_calibration)
        # 自動採集：一鍵串接既有「開始」/「開始記錄」/「心跳帶真值校準」觸發點，
        # 不重寫任何 worker 啟停或記錄/校準邏輯本身（見 _on_auto_capture_clicked）。
        self._auto_capture_timer: QTimer | None = None
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

        self._build_menu()
        self._build_central()

        self._load_settings()
        self._alarm_controller = FatigueAlarmController(self._alarm_config, self)
        self._apply_hotkey_shortcuts()
        self._apply_overlay_state()
        self._start_web_server()

        self.statusBar().showMessage("就緒 — 選擇攝影機後按「開始」可預覽（無 MediaPipe）")

    def _build_menu(self) -> None:
        act_hotkeys = QAction("快捷鍵設定…", self)
        act_hotkeys.triggered.connect(self._on_hotkeys)

        act_profile = QAction("使用者資料…", self)
        act_profile.triggered.connect(self._on_user_profile)

        act_alarm = QAction("警報器設定…", self)
        act_alarm.triggered.connect(self._on_alarm_settings)

        act_refresh = QAction("刷新攝影機列表", self)
        act_refresh.triggered.connect(self._start_camera_scan)

        act_recordings = QAction("開啟記錄檔目錄", self)
        act_recordings.triggered.connect(self._open_recordings_dir)

        act_save = QAction("保存配置與布局", self)
        act_save.triggered.connect(self._on_save_layout)

        act_reset = QAction("重置至原廠設定", self)
        act_reset.triggered.connect(self._on_reset_layout)

        act_web = QAction("開啟Web 儀表板頁面", self)
        act_web.triggered.connect(self._on_web_info)

        self._act_web_allow_lan = QAction("允許區域網存取 Web 儀表板", self)
        self._act_web_allow_lan.setCheckable(True)
        self._act_web_allow_lan.setToolTip(
            "警告：啟用後將以未加密 HTTP 對區域網路廣播人臉影像與生理數據（以 shared token "
            "驗證存取），僅限受信任網路使用。"
        )
        self._act_web_allow_lan.toggled.connect(self._on_web_allow_lan_toggled)

        m_settings = self.menuBar().addMenu("設定")
        m_settings.addAction(act_hotkeys)
        m_settings.addAction(act_profile)
        m_settings.addAction(act_alarm)
        m_settings.addSeparator()
        m_settings.addAction(act_refresh)
        m_settings.addAction(act_recordings)
        m_settings.addSeparator()
        m_settings.addAction(act_save)
        m_settings.addAction(act_reset)
        m_settings.addSeparator()
        m_settings.addAction(self._act_web_allow_lan)
        m_settings.addAction(act_web)

        act_start = QAction("開始／停止", self)
        act_start.setShortcut(QKeySequence(self._hotkeys.start_stop))
        act_start.triggered.connect(self._toggle_pipeline)

        act_metrics = QAction("切換：數值 Overlay", self)
        act_metrics.setShortcut(QKeySequence(self._hotkeys.toggle_metrics))
        act_metrics.triggered.connect(lambda: self._chk_metrics.setChecked(not self._chk_metrics.isChecked()))

        act_preview = QAction("切換：鏡頭預覽 Overlay", self)
        act_preview.setShortcut(QKeySequence(self._hotkeys.toggle_preview))
        act_preview.triggered.connect(lambda: self._chk_preview.setChecked(not self._chk_preview.isChecked()))

        act_lock = QAction("切換：鎖定 Overlay", self)
        act_lock.setShortcut(QKeySequence(self._hotkeys.lock_overlay))
        act_lock.triggered.connect(lambda: self._chk_lock.setChecked(not self._chk_lock.isChecked()))

        act_all = QAction("切換：全部 Overlay", self)
        act_all.setShortcut(QKeySequence(self._hotkeys.toggle_all))
        act_all.triggered.connect(lambda: self._chk_all.setChecked(not self._chk_all.isChecked()))

        act_rec = QAction("切換：錄影", self)
        act_rec.setShortcut(QKeySequence(self._hotkeys.toggle_recording))
        act_rec.triggered.connect(self._toggle_recording)

        act_quit = QAction("離開", self)
        act_quit.triggered.connect(self.close)

        m_control = self.menuBar().addMenu("控制")
        m_control.addAction(act_start)
        m_control.addSeparator()
        m_control.addAction(act_metrics)
        m_control.addAction(act_preview)
        m_control.addAction(act_lock)
        m_control.addAction(act_all)
        m_control.addAction(act_rec)
        m_control.addSeparator()
        m_control.addAction(act_quit)

        self._menu_actions_hotkeys = (act_metrics, act_preview, act_start, act_lock, act_all, act_rec)

    def _build_central(self) -> None:
        wrap = QWidget()
        self.setCentralWidget(wrap)
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        header = QVBoxLayout()
        t = QLabel("rPPG 疲勞/生理訊號控制台")
        t.setObjectName("titleLabel")
        header.addWidget(t)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)

        # --- Camera (RGB only) ---
        gb_cam = QGroupBox("攝影機（RGB）")
        cam_l = QVBoxLayout(gb_cam)
        row1 = QHBoxLayout()
        self._cmb_camera = QComboBox()
        self._cmb_camera.addItem("── 載入中… ──", None)
        self._cmb_camera.setEnabled(False)
        self._cmb_camera.currentIndexChanged.connect(self._on_camera_combo_changed)
        btn_refresh = QPushButton("刷新列表")
        btn_refresh.clicked.connect(self._start_camera_scan)
        self._lbl_cam_hint = QLabel("載入中…")
        self._lbl_cam_hint.setObjectName("hintLabel")
        row1.addWidget(QLabel("裝置："))
        row1.addWidget(self._cmb_camera, 1)
        row1.addWidget(btn_refresh)
        row1.addWidget(self._lbl_cam_hint)
        cam_l.addLayout(row1)

        row2 = QHBoxLayout()
        self._cmb_resolution = QComboBox()
        self._cmb_resolution.addItems(["640×480", "800×600", "1280×720（720p）", "1280×800", "1920×1080（1080p）"])
        self._cmb_resolution.setCurrentText("1280×720（720p）")
        self._cmb_fps = QComboBox()
        self._cmb_fps.addItems(["15", "24", "30", "60"])
        self._cmb_fps.setCurrentText("30")
        row2.addWidget(QLabel("解析度："))
        row2.addWidget(self._cmb_resolution)
        row2.addSpacing(16)
        row2.addWidget(QLabel("目標 FPS："))
        row2.addWidget(self._cmb_fps)
        row2.addStretch(1)
        cam_l.addLayout(row2)

        row3 = QHBoxLayout()
        self._cmb_backend = QComboBox()
        self._cmb_backend.addItem("自動（平台預設）", "auto")
        if sys.platform.startswith("linux"):
            self._cmb_backend.addItem("V4L2（Linux）", "v4l2")
        self._cmb_backend.addItem("FFMPEG", "ffmpeg")
        if sys.platform.startswith("win"):
            self._cmb_backend.addItem("MSMF（Windows Media Foundation）", "msmf")
            self._cmb_backend.addItem("DSHOW（DirectShow）", "dshow")
        self._cmb_backend.setCurrentIndex(0)
        self._cmb_backend.setToolTip(
            "自動 — 依平台優先選擇可用後端\n"
            "V4L2 — Linux 原生攝影機後端\n"
            "FFMPEG — 嘗試 FFMPEG 後再回退到平台後端\n"
            "MSMF — Windows Media Foundation，可保留原生 MJPG\n"
            "DSHOW — Windows DirectShow，部分虛擬相機較穩定"
        )
        self._chk_horizontal_flip = QCheckBox("水平翻轉（鏡像校正）")
        self._chk_horizontal_flip.setChecked(True)
        self._chk_horizontal_flip.setToolTip("相機畫面左右相反時啟用；預覽、錄影與分析會使用同一個翻轉後畫面。")
        lbl_backend = QLabel("後端：")
        lbl_backend.setObjectName("hintLabel")
        row3.addWidget(lbl_backend)
        row3.addWidget(self._cmb_backend)
        row3.addSpacing(16)
        row3.addWidget(self._chk_horizontal_flip)
        row3.addStretch(1)
        cam_l.addLayout(row3)
        body_layout.addWidget(gb_cam)

        # --- Controls ---
        gb_ctl = QGroupBox("控制")
        ctl = QVBoxLayout(gb_ctl)

        row_a = QHBoxLayout()
        self._btn_start = QPushButton("開始")
        self._btn_start.setObjectName("primaryButton")
        self._btn_start.clicked.connect(self._toggle_pipeline)
        self._chk_all = QCheckBox("顯示／隱藏 全部 Overlay")
        self._chk_all.setChecked(True)
        self._chk_preview = QCheckBox("鏡頭預覽 Overlay（含 MediaPipe）")
        self._chk_metrics = QCheckBox("數值 Overlay")
        self._chk_metrics.setChecked(True)
        row_a.addWidget(self._btn_start)
        row_a.addSpacing(16)
        row_a.addWidget(self._chk_all)
        row_a.addWidget(self._chk_preview)
        row_a.addWidget(self._chk_metrics)
        row_a.addStretch(1)
        ctl.addLayout(row_a)

        row_b = QHBoxLayout()
        self._chk_behavior = QCheckBox("行為警覺（頭部／哈欠／注視）")
        self._chk_behavior.setChecked(True)
        self._chk_stress = QCheckBox("壓力／HRV（心率估測）")
        self._chk_belt_calib = QCheckBox("心跳帶真值校準（背景）")
        self._chk_belt_calib.setToolTip(
            "以 BLE 心跳帶（Scosche Rhythm+ 2.0 等標準 Heart Rate Service 裝置）的實測心率為"
            "「真值參考」，在背景持續比對 rPPG 偵測到的心率，並以低增益慢速微調 rPPG 的 BPM"
            "校正量，讓 rPPG 逐漸趨近真值。\n"
            "心跳帶數值只用於校準與可信度判斷，絕不直接進入疲勞判斷。"
            "需勾選「壓力／HRV（心率估測）」啟用 rPPG 才會開始比對。"
        )
        self._chk_lock = QCheckBox("Overlay 鎖定（穿透點擊）")
        self._chk_lock.setChecked(True)
        row_b.addWidget(self._chk_behavior)
        row_b.addWidget(self._chk_stress)
        row_b.addWidget(self._chk_belt_calib)
        row_b.addWidget(self._chk_lock)
        row_b.addStretch(1)
        ctl.addLayout(row_b)

        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("心跳帶校準："))
        self._lbl_belt_status = QLabel("未啟用")
        self._lbl_belt_status.setObjectName("hintLabel")
        row_mode.addWidget(self._lbl_belt_status)
        row_mode.addStretch(1)
        ctl.addLayout(row_mode)

        row_profile = QHBoxLayout()
        self._btn_record_baseline = QPushButton("記錄清醒基線")
        self._btn_record_baseline.setToolTip(
            "在你精神狀態良好時按下，系統會擷取約 60 秒的清醒基線（PERCLOS／注視／眉距／"
            "眨眼等），把疲勞判斷門檻校準到「你個人的正常範圍」，並存成個人 profile 供下次"
            "開機自動載入。需先按「開始」啟動偵測。\n"
            "心跳帶數值不參與此基線。"
        )
        self._btn_record_baseline.clicked.connect(self._on_record_baseline_clicked)
        self._lbl_profile_status = QLabel(
            "個人基線：已載入" if self._personal_profile is not None else "個人基線：未建立")
        self._lbl_profile_status.setObjectName("hintLabel")
        row_profile.addWidget(self._btn_record_baseline)
        row_profile.addWidget(self._lbl_profile_status)
        row_profile.addStretch(1)
        ctl.addLayout(row_profile)

        row_c = QHBoxLayout()
        self._btn_record = QPushButton("開始記錄")
        self._btn_record.clicked.connect(self._toggle_recording)
        self._chk_auto_record = QCheckBox("按下開始時自動記錄")
        self._lbl_record = QLabel("記錄狀態：未啟動")
        self._lbl_record.setObjectName("hintLabel")
        self._btn_bench = QPushButton("DL 基準測試（120s）")
        self._btn_bench.clicked.connect(self._toggle_benchmark)
        self._lbl_bench = QLabel("")
        self._lbl_bench.setObjectName("hintLabel")
        row_c.addWidget(self._btn_record)
        row_c.addWidget(self._chk_auto_record)
        row_c.addWidget(self._lbl_record)
        row_c.addSpacing(16)
        row_c.addWidget(self._btn_bench)
        row_c.addWidget(self._lbl_bench)
        row_c.addStretch(1)
        ctl.addLayout(row_c)

        row_auto = QHBoxLayout()
        row_auto.addWidget(QLabel("自動採集時長(秒)："))
        self._spn_auto_capture_seconds = QSpinBox()
        self._spn_auto_capture_seconds.setRange(10, 600)
        self._spn_auto_capture_seconds.setValue(60)
        row_auto.addWidget(self._spn_auto_capture_seconds)
        self._btn_auto_capture = QPushButton("自動採集")
        self._btn_auto_capture.setToolTip(
            "一鍵串接既有流程：啟動管線（若未啟動）→ 開始記錄（採集 A）→\n"
            "勾選「自動採集含心跳帶」時，同步勾選「壓力／HRV」與「心跳帶真值校準」（採集 B，"
            "是否實際落檔仍依現有設定與硬體狀態決定）→\n"
            "倒數結束（或再按一次提前停止）時自動停止記錄，並回報 .db／.jsonl 路徑。"
        )
        self._btn_auto_capture.clicked.connect(self._on_auto_capture_clicked)
        self._chk_auto_capture_belt = QCheckBox("自動採集含心跳帶")
        row_auto.addWidget(self._btn_auto_capture)
        row_auto.addWidget(self._chk_auto_capture_belt)
        row_auto.addStretch(1)
        ctl.addLayout(row_auto)

        row_d = QHBoxLayout()
        row_d.addWidget(QLabel("Overlay 透明度："))
        self._sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self._sld_opacity.setRange(0, 100)
        self._sld_opacity.setValue(55)
        self._sld_opacity.valueChanged.connect(self._on_opacity)
        self._lbl_opacity = QLabel("55%")
        self._lbl_opacity.setMinimumWidth(48)
        row_d.addWidget(self._sld_opacity, 1)
        row_d.addWidget(self._lbl_opacity)
        ctl.addLayout(row_d)

        self._chk_all.toggled.connect(self._on_toggle_all)
        self._chk_preview.toggled.connect(self._on_preview_toggled)
        self._chk_metrics.toggled.connect(self._on_metrics_toggled)
        self._chk_lock.toggled.connect(self._on_lock_toggled)
        # Behaviour alertness toggle — functional
        self._chk_behavior.toggled.connect(self._on_behavior_toggled)
        self._chk_auto_record.toggled.connect(
            lambda checked: self._append_log(
                f"[UI] {self._chk_auto_record.text()} → {'開啟' if checked else '關閉'}"
            )
        )
        # rPPG stress/HRV toggle — functional
        self._chk_stress.toggled.connect(self._on_stress_toggled)
        self._chk_belt_calib.toggled.connect(self._on_belt_calib_toggled)

        body_layout.addWidget(gb_ctl)

        # --- 心跳帶（傳輸數值 + 衍生 HRV 專屬區塊） ---
        gb_belt = QGroupBox("心跳帶")
        belt_l = QVBoxLayout(gb_belt)

        def _belt_stat_row(label_text: str) -> QLabel:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setObjectName("hintLabel")
            lbl.setMinimumWidth(90)
            val = QLabel("—")
            val.setStyleSheet("font-size: 15px; font-weight: 600; color: #e6edf3;")
            row.addWidget(lbl)
            row.addWidget(val, 1, Qt.AlignmentFlag.AlignRight)
            belt_l.addLayout(row)
            return val

        belt_sub_realtime = QLabel("即時")
        belt_sub_realtime.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b949e;")
        belt_l.addWidget(belt_sub_realtime)
        self._lbl_belt_bpm = _belt_stat_row("BPM：")
        self._lbl_belt_rr = _belt_stat_row("RR 樣本數：")
        self._lbl_belt_contact = _belt_stat_row("感測器接觸：")
        self._lbl_belt_battery = _belt_stat_row("電量：")
        self._lbl_belt_rssi = _belt_stat_row("RSSI：")
        self._lbl_belt_stale = _belt_stat_row("停滯警告：")

        belt_sub_conn = QLabel("連線")
        belt_sub_conn.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b949e; margin-top: 6px;")
        belt_l.addWidget(belt_sub_conn)
        self._lbl_belt_device = _belt_stat_row("裝置名稱：")
        self._lbl_belt_address = _belt_stat_row("裝置位址：")
        self._lbl_belt_location = _belt_stat_row("配戴位置：")
        self._lbl_belt_connected_since = _belt_stat_row("連線時長：")
        self._lbl_belt_notifications = _belt_stat_row("封包數：")
        self._lbl_belt_last_error = _belt_stat_row("最後錯誤：")

        belt_sub_hrv = QLabel("HRV（僅供顯示，不進疲勞融合）")
        belt_sub_hrv.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b949e; margin-top: 6px;")
        belt_l.addWidget(belt_sub_hrv)
        self._lbl_belt_hrv_rmssd = _belt_stat_row("RMSSD：")
        self._lbl_belt_hrv_sdnn = _belt_stat_row("SDNN：")
        self._lbl_belt_hrv_lfhf = _belt_stat_row("LF/HF：")
        self._lbl_belt_hrv_conf = _belt_stat_row("HRV 信心：")
        self._lbl_belt_hrv_warmup = _belt_stat_row("暖機進度：")

        belt_sub_calib = QLabel("rPPG 校準")
        belt_sub_calib.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b949e; margin-top: 6px;")
        belt_l.addWidget(belt_sub_calib)
        self._lbl_belt_calib_offset = _belt_stat_row("Offset：")
        self._lbl_belt_calib_raw_resid = _belt_stat_row("原始殘差：")
        self._lbl_belt_calib_corr_resid = _belt_stat_row("校正後殘差：")
        self._lbl_belt_calib_confidence = _belt_stat_row("信心：")
        self._lbl_belt_calib_status = _belt_stat_row("狀態：")
        self._lbl_belt_calib_pairs = _belt_stat_row("配對數：")

        body_layout.addWidget(gb_belt)

        # --- 影片回測 ---
        gb_replay = QGroupBox("影片回測")
        replay_l = QVBoxLayout(gb_replay)

        replay_row_a = QHBoxLayout()
        self._btn_replay_choose = QPushButton("選擇資料夾")
        self._btn_replay_choose.clicked.connect(self._choose_replay_dir)
        self._lbl_replay_dir = QLabel("尚未選擇資料夾")
        self._lbl_replay_dir.setObjectName("hintLabel")
        self._lbl_replay_dir.setWordWrap(True)
        replay_row_a.addWidget(self._btn_replay_choose)
        replay_row_a.addWidget(self._lbl_replay_dir, 1)
        replay_l.addLayout(replay_row_a)

        replay_row_b = QHBoxLayout()
        self._btn_replay_start = QPushButton("開始批次")
        self._btn_replay_start.setObjectName("primaryButton")
        self._btn_replay_start.clicked.connect(self._start_replay)
        self._btn_replay_parallel = QPushButton("平行驗證")
        self._btn_replay_parallel.clicked.connect(self._start_replay_parallel)
        self._btn_replay_stop = QPushButton("停止")
        self._btn_replay_stop.setObjectName("dangerButton")
        self._btn_replay_stop.setEnabled(False)
        self._btn_replay_stop.clicked.connect(self._stop_replay)
        self._spn_replay_jobs = QSpinBox()
        self._spn_replay_jobs.setRange(1, 4)
        self._spn_replay_jobs.setValue(2)
        self._spn_replay_jobs.setPrefix("平行數 ")
        self._chk_replay_annotated = QCheckBox("輸出標註影片")
        self._lbl_replay_current = QLabel("目前影片：--")
        self._lbl_replay_current.setObjectName("hintLabel")
        replay_row_b.addWidget(self._btn_replay_start)
        replay_row_b.addWidget(self._btn_replay_parallel)
        replay_row_b.addWidget(self._btn_replay_stop)
        replay_row_b.addWidget(self._spn_replay_jobs)
        replay_row_b.addWidget(self._chk_replay_annotated)
        replay_row_b.addWidget(self._lbl_replay_current, 1)
        replay_l.addLayout(replay_row_b)

        replay_row_c = QHBoxLayout()
        self._bar_replay_progress = QProgressBar()
        self._bar_replay_progress.setRange(0, 1)
        self._bar_replay_progress.setValue(0)
        self._lbl_replay_result = QLabel("摘要檔：--")
        self._lbl_replay_result.setObjectName("hintLabel")
        self._lbl_replay_result.setWordWrap(True)
        replay_row_c.addWidget(self._bar_replay_progress, 1)
        replay_row_c.addWidget(self._lbl_replay_result, 2)
        replay_l.addLayout(replay_row_c)

        self._lbl_replay_parallel_status = QLabel("處理清單：--")
        self._lbl_replay_parallel_status.setObjectName("hintLabel")
        self._lbl_replay_parallel_status.setWordWrap(True)
        replay_l.addWidget(self._lbl_replay_parallel_status)

        self._frame_replay_preview = QFrame()
        self._frame_replay_preview.setFixedHeight(360)
        self._frame_replay_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._frame_replay_preview.setStyleSheet(
            "background-color: #101318; border: 1px solid #2a2f38; border-radius: 8px;"
        )
        replay_preview_layout = QVBoxLayout(self._frame_replay_preview)
        replay_preview_layout.setContentsMargins(0, 0, 0, 0)
        replay_preview_layout.setSpacing(0)
        self._lbl_replay_preview = QLabel("影片預覽")
        self._lbl_replay_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_replay_preview.setScaledContents(False)
        self._lbl_replay_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._lbl_replay_preview.setStyleSheet("background-color: transparent; color: #868e96;")
        replay_preview_layout.addWidget(self._lbl_replay_preview, 1)
        replay_l.addWidget(self._frame_replay_preview)

        body_layout.addWidget(gb_replay)

        # --- Status strip ---
        stat = QFrame()
        stat.setObjectName("statusBarFrame")
        sl = QHBoxLayout(stat)
        sl.setContentsMargins(0, 0, 0, 0)
        self._lbl_pipeline = QLabel("管線：停止")
        self._lbl_camera = QLabel("相機：—")
        self._lbl_face = QLabel("臉部：—")
        self._lbl_fps = QLabel("FPS：—")
        self._lbl_codec = QLabel("編碼：—")
        for lb in (self._lbl_pipeline, self._lbl_camera, self._lbl_face, self._lbl_fps, self._lbl_codec):
            lb.setStyleSheet("color: #ced4da;")
            sl.addWidget(lb)
            sl.addSpacing(20)
        sl.addStretch(1)
        body_layout.addWidget(stat)

        # --- Log ---
        gb_log = QGroupBox("Log")
        log_l = QVBoxLayout(gb_log)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_l.addWidget(self._log)
        body_layout.addWidget(gb_log, 1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._append_log("歡迎使用 rPPG 疲勞/生理訊號偵測 V2 控制台。變更選項僅寫入此視窗日誌。")
        self._start_camera_scan()

        self._db_flush_timer = QTimer(self)
        self._db_flush_timer.setInterval(2000)
        self._db_flush_timer.timeout.connect(self._flush_recorder)
        self._db_flush_timer.start()

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
        if not self._global_hotkey_enabled:
            return
        self._unregister_global_hotkeys()

        user32 = cast(Any, ctypes).WinDLL("user32", use_last_error=True)
        hwnd = int(self.winId())

        for hotkey_id, act in self._global_hotkey_id_map.items():
            seq = act.shortcut().toString()
            parsed = self._parse_hotkey(seq)
            if parsed is None:
                continue
            mod_flags, vk = parsed
            if not user32.RegisterHotKey(hwnd, hotkey_id, mod_flags, vk):
                err = cast(Any, ctypes).get_last_error()
                if seq not in self._hotkey_failed_once:
                    if err == 1409:
                        self._append_log(f"⚠ 全域快捷鍵已被占用：{seq}（錯誤 {err}）")
                    else:
                        self._append_log(f"⚠ 註冊全域快捷鍵失敗：{seq}（錯誤 {err}）")
                    self._hotkey_failed_once.add(seq)
        self._global_hotkeys_registered = True

    def _unregister_global_hotkeys(self) -> None:
        if not self._global_hotkey_enabled:
            return
        if not self._global_hotkeys_registered:
            return
        user32 = cast(Any, ctypes).WinDLL("user32", use_last_error=True)
        hwnd = int(self.winId())
        for hotkey_id in self._global_hotkey_id_map:
            user32.UnregisterHotKey(hwnd, hotkey_id)
        self._global_hotkeys_registered = False

    def _on_global_hotkey(self, hotkey_id: int) -> None:
        act = self._global_hotkey_id_map.get(hotkey_id)
        if act is None:
            return
        act.trigger()

    def _settings_path(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / "settings.json"

    @staticmethod
    def _encode_bytes(data: QByteArray) -> str:
        return bytes(cast(Any, data.toBase64())).decode("ascii")

    @staticmethod
    def _decode_bytes(text: str) -> QByteArray:
        return QByteArray.fromBase64(text.encode("ascii"))

    def _select_combo_by_data(self, combo: QComboBox, value: str) -> bool:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return True
        return False

    def _select_camera_by_index(self, cam_idx: int) -> bool:
        for i in range(self._cmb_camera.count()):
            if self._cmb_camera.itemData(i) == cam_idx:
                self._cmb_camera.setCurrentIndex(i)
                return True
        return False

    def _apply_overlay_state(self) -> None:
        self._preview_overlay.set_opacity(self._sld_opacity.value() / 100.0)
        self._preview_overlay.apply_lock_state(self._chk_lock.isChecked())
        self._preview_overlay.set_preview_visible(self._chk_preview.isChecked())
        self._preview_overlay.set_metrics_visible(self._chk_metrics.isChecked())
        self._sync_overlay_visibility()

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
        geo = win.get("geometry")
        state = win.get("state")
        if isinstance(geo, str):
            self.restoreGeometry(self._decode_bytes(geo))
        if isinstance(state, str):
            self.restoreState(self._decode_bytes(state))

        overlay = data.get("overlay", {})
        overlay_geo = overlay.get("geometry")
        if isinstance(overlay_geo, str):
            self._preview_overlay.restoreGeometry(self._decode_bytes(overlay_geo))

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

            if isinstance(resolution, str):
                self._cmb_resolution.setCurrentText(resolution)
            if isinstance(fps, str):
                self._cmb_fps.setCurrentText(fps)
            if isinstance(backend, str):
                if not self._select_combo_by_data(self._cmb_backend, backend):
                    self._cmb_backend.setCurrentIndex(0)
            if isinstance(horizontal_flip, bool):
                self._chk_horizontal_flip.setChecked(horizontal_flip)
            if isinstance(cam_idx, int):
                if not self._select_camera_by_index(cam_idx):
                    self._pending_camera_index = cam_idx

        toggles = data.get("toggles", {})
        if isinstance(toggles, dict):
            checkboxes = (
                (self._chk_all, toggles.get("all")),
                (self._chk_preview, toggles.get("preview")),
                (self._chk_metrics, toggles.get("metrics")),
                (self._chk_lock, toggles.get("lock")),
                (self._chk_behavior, toggles.get("behavior")),
                (self._chk_stress, toggles.get("stress")),
                (self._chk_belt_calib, toggles.get("belt_calib")),
                (self._chk_auto_record, toggles.get("auto_record")),
            )
            for chk, val in checkboxes:
                if isinstance(val, bool):
                    chk.blockSignals(True)
                    chk.setChecked(val)
                    chk.blockSignals(False)

        opacity = overlay.get("opacity")
        if isinstance(opacity, int):
            self._sld_opacity.setValue(opacity)

        web = data.get("web", {})
        if isinstance(web, dict):
            allow_lan = web.get("allow_lan")
            if isinstance(allow_lan, bool):
                self._act_web_allow_lan.blockSignals(True)
                self._act_web_allow_lan.setChecked(allow_lan)
                self._act_web_allow_lan.blockSignals(False)

        alarm = data.get("alarm", {})
        if isinstance(alarm, dict):
            self._alarm_config = AlarmConfig.from_dict(alarm)

    def _save_settings(self) -> Path:
        path = self._settings_path()
        data = {
            "window": {
                "geometry": self._encode_bytes(self.saveGeometry()),
                "state": self._encode_bytes(self.saveState()),
            },
            "overlay": {
                "geometry": self._encode_bytes(self._preview_overlay.saveGeometry()),
                "opacity": int(self._sld_opacity.value()),
            },
            "camera": {
                "index": self.selected_camera_index,
                "resolution": self._cmb_resolution.currentText(),
                "fps": self._cmb_fps.currentText(),
                "backend": self._cmb_backend.currentData(),
                "horizontal_flip": self._chk_horizontal_flip.isChecked(),
            },
            "toggles": {
                "all": self._chk_all.isChecked(),
                "preview": self._chk_preview.isChecked(),
                "metrics": self._chk_metrics.isChecked(),
                "lock": self._chk_lock.isChecked(),
                "behavior": self._chk_behavior.isChecked(),
                "stress": self._chk_stress.isChecked(),
                "belt_calib": self._chk_belt_calib.isChecked(),
                "auto_record": self._chk_auto_record.isChecked(),
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
                "allow_lan": self._act_web_allow_lan.isChecked(),
            },
            "alarm": self._alarm_config.to_dict(),
        }
        path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        return path

    def _start_camera_scan(self) -> None:
        """Refresh camera list (same strategy as V1: DirectShow names first, no OpenCV open)."""
        self._lbl_cam_hint.setText("載入中…")
        self._cmb_camera.setEnabled(False)
        dev_list: list[tuple[int, str]] = []
        try:
            from gui.camera_devices import list_camera_devices

            dev_list = list_camera_devices(max_index=20, warmup_read=True)
        except Exception as exc:
            self._append_log(f"攝影機列舉失敗：{exc}")
        self._finish_camera_scan_ui(dev_list)

    def _finish_camera_scan_ui(self, dev_list: list[tuple[int, str]]) -> None:
        """Populate combo from scan result (runs on GUI thread)."""
        prev: object | None = None
        self._cmb_camera.blockSignals(True)
        try:
            prev = self._cmb_camera.currentData()
        except Exception:
            prev = None

        self._cmb_camera.clear()
        placeholder = "── 請選擇攝影機 ──"
        self._cmb_camera.addItem(placeholder, None)
        for index, name in dev_list:
            self._cmb_camera.addItem(f"[{index}] {name}", index)

        self._lbl_cam_hint.setText(f"偵測：{len(dev_list)} 台")
        self._cmb_camera.setEnabled(True)

        restored = False
        if prev is not None:
            for i in range(self._cmb_camera.count()):
                if self._cmb_camera.itemData(i) == prev:
                    self._cmb_camera.setCurrentIndex(i)
                    restored = True
                    break
        if not restored:
            if dev_list:
                self._cmb_camera.setCurrentIndex(1)
            else:
                self._cmb_camera.setCurrentIndex(0)

        if self._pending_camera_index is not None:
            if self._select_camera_by_index(self._pending_camera_index):
                self._pending_camera_index = None

        self._cmb_camera.blockSignals(False)
        self._on_camera_combo_changed(self._cmb_camera.currentIndex())

        if dev_list:
            self._append_log(f"攝影機清單已更新：{len(dev_list)} 個項目。")
        else:
            self._append_log(
                "未取得攝影機清單。Linux 請檢查 /dev/video*、video 群組權限，"
                "或執行 scripts/diagnose_camera.py。"
            )

    def _apply_hotkey_shortcuts(self) -> None:
        hk = self._hotkeys
        actions = self._menu_actions_hotkeys
        keys = (
            hk.toggle_metrics,
            hk.toggle_preview,
            hk.start_stop,
            hk.lock_overlay,
            hk.toggle_all,
            hk.toggle_recording,
        )
        for act, k in zip(actions, keys, strict=True):
            act.setShortcut(QKeySequence(k))
        if not self._global_hotkey_id_map:
            self._global_hotkey_id_map = {i + 1: act for i, act in enumerate(actions)}
        self._register_global_hotkeys()

    def _recordings_dir(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        rec = root / "recordings"
        rec.mkdir(exist_ok=True)
        return rec

    def _web_allow_lan_enabled(self) -> bool:
        return self._act_web_allow_lan.isChecked()

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

    def _restart_web_server(self) -> None:
        self._stop_web_server()
        self._start_web_server()

    def _stop_web_server(self) -> None:
        if self._web_server is None:
            return
        thread = self._web_server
        stopped = thread.stop(join_timeout=5.0)
        if not stopped and thread.is_alive():
            self._append_log(
                "⚠ Web 儀表板舊執行緒未能及時結束；若儀表板無法更新，請重新啟動程式。"
            )
        self._web_server = None

    def _build_web_metrics(self) -> dict:
        pipeline_running = bool(self._pipeline_running)
        stress_enabled = self._chk_stress.isChecked()
        behavior_enabled = self._chk_behavior.isChecked()
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
        belt_st = self._belt_runtime.belt_status() if self._belt_runtime.belt_running else None
        # 校準資訊僅在心跳帶已連線時視為 active（與 GUI 狀態列一致，避免掃描中
        # 就顯示「校正 +0.0｜0 配對」）。
        belt_connected = belt_st is not None and belt_st.state == "connected"
        calib = (
            self._belt_calibrator.state()
            if self._belt_calibrator is not None and belt_connected
            else None
        )

        return {
            "timestamp": time.time(),
            "pipeline_running": pipeline_running,
            "camera_running": bool(self._cam_worker is not None),
            "recording": bool(self._recording),
            "fps": float(self._last_fps or 0.0),
            "camera_label": str(self._cmb_camera.currentText() or ""),
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
            "belt_battery": int(belt_st.battery_level) if belt_st and belt_st.battery_level is not None else -1,
            "belt_bpm": int(belt_st.bpm) if belt_st else 0,
            "belt_rr_count": int(belt_st.rr_count) if belt_st else 0,
            "belt_sensor_location": str(belt_st.sensor_location) if belt_st else "",
            "belt_contact_ok": bool(
                belt_st.sensor_contact_detected or not belt_st.sensor_contact_supported
            ) if belt_st else False,
            "belt_stale": bool(hr_is_stale(belt_st)) if belt_st else False,
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
        if self._web_server is None:
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
        if self._metrics_recorder is not None:
            return
        rec_dir = self._recordings_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_path = rec_dir / f"metrics_{stamp}.db"
        self._metrics_recorder = MetricsRecorder(str(db_path))
        self._recording_db_path = db_path
        self._recording_started_at = time.time()
        self._recording_count = 0

        self._video_queue = queue.Queue(maxsize=8)
        video_path = rec_dir / f"video_{stamp}.mp4"
        self._recording_video_path = video_path
        thread = QThread(self)
        worker = VideoRecorderWorker(self._video_queue, video_path, fps=self._last_fps or 30.0)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_video_recording_started)
        worker.failed.connect(self._on_video_recording_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._video_thread = thread
        self._video_worker = worker
        thread.start()
        self._update_recording_routing()

    def _stop_recording(self) -> None:
        if self._metrics_recorder is None:
            return
        try:
            self._metrics_recorder.close()
        finally:
            self._metrics_recorder = None
            self._recording_db_path = None
            self._recording_started_at = None

        if self._video_worker is not None:
            self._video_worker.request_stop()
        if self._video_thread is not None:
            self._video_thread.quit()
            self._video_thread.wait(2000)
        self._video_thread = None
        self._video_worker = None
        self._video_queue = None
        self._recording_video_path = None
        self._update_recording_routing()

    def _flush_recorder(self) -> None:
        if self._metrics_recorder is not None:
            try:
                self._metrics_recorder._flush()
            except Exception:
                pass

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
            "camera_label": str(self._cmb_camera.currentText() or ""),
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
        if self._recording_count % 60 == 0:
            self._lbl_record.setText(f"記錄狀態：進行中（{self._recording_count} 筆）")

    def _on_video_recording_started(self, path: str) -> None:
        try:
            self._recording_video_path = Path(path)
        except Exception:
            self._recording_video_path = None
        if self._recording_video_path is not None:
            self._append_log(f"● 影片錄製 → {self._recording_video_path}")

    def _on_video_recording_failed(self, msg: str) -> None:
        if msg.startswith("mp4v 不可用"):
            self._append_log(f"⚠ {msg}")
        else:
            self._append_log(f"✗ 影片錄製失敗：{msg}")

    def _append_log(self, msg: str) -> None:
        self._log.append(msg)
        self.statusBar().showMessage(msg, 4000)

    def _choose_replay_dir(self) -> None:
        start_dir = Path.home()
        candidate = Path.home() / "Downloads" / "Fold1_part1"
        if self._replay_dataset_dir is not None:
            start_dir = self._replay_dataset_dir
        elif candidate.exists():
            start_dir = candidate

        selected = QFileDialog.getExistingDirectory(self, "選擇影片回測資料夾", str(start_dir))
        if not selected:
            return
        self._replay_dataset_dir = Path(selected)
        self._lbl_replay_dir.setText(str(self._replay_dataset_dir))
        self._append_log(f"[影片回測] 已選擇資料夾：{self._replay_dataset_dir}")

    def _start_replay(self) -> None:
        self._start_replay_run(jobs=1, preview_enabled=True, mode_label="回放中")

    def _start_replay_parallel(self) -> None:
        jobs = max(1, int(self._spn_replay_jobs.value()))
        if jobs > 4:
            jobs = 4
            self._spn_replay_jobs.setValue(jobs)
            self._append_log("[影片回測] 平行數已自動降為 4，避免 Windows 多進程與 MediaPipe/影片編碼器資源壓力過高")
        if self._chk_replay_annotated.isChecked():
            self._chk_replay_annotated.setChecked(False)
            self._append_log("[影片回測] 平行驗證已自動關閉輸出標註影片；需要標註畫面請用「開始批次」單工模式")
            QMessageBox.information(
                self,
                "影片回測平行驗證",
                "平行驗證會同時啟動多個 MediaPipe/影片解碼流程。為避免子行程崩潰，已自動關閉「輸出標註影片」。\n\n"
                "需要標註影片時，請改用「開始批次」單工模式。正式大量驗證建議平行數 2-4。",
            )
        self._start_replay_run(jobs=jobs, preview_enabled=False, mode_label=f"平行驗證中 x{jobs}")

    def _start_replay_run(self, *, jobs: int, preview_enabled: bool, mode_label: str) -> None:
        if self._replay_thread is not None:
            return
        if self._pipeline_running or self._recording:
            QMessageBox.information(self, "影片回測", "請先停止即時攝影機流程與錄影，再啟動影片批次測試。")
            return
        if self._replay_dataset_dir is None:
            self._choose_replay_dir()
            if self._replay_dataset_dir is None:
                return
        if not self._replay_dataset_dir.exists():
            QMessageBox.warning(self, "影片回測", f"找不到資料夾：\n{self._replay_dataset_dir}")
            return

        thread = QThread(self)
        worker = VideoReplayWorker(
            self._replay_dataset_dir,
            write_annotated_video=self._chk_replay_annotated.isChecked(),
            jobs=jobs,
            preview_enabled=preview_enabled,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_replay_progress)
        if preview_enabled:
            worker.preview_frame.connect(self._on_replay_preview_frame)
        worker.finished_ok.connect(self._on_replay_finished_ok)
        worker.failed.connect(self._on_replay_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_replay_thread_finished)

        self._replay_thread = thread
        self._replay_worker = worker
        self._replay_stopping = False
        self._replay_mode_label = mode_label
        self._replay_total_count = 0
        self._replay_done_count = 0
        self._replay_active_videos.clear()
        self._replay_recent_done.clear()
        self._set_replay_controls_running(True)
        self._bar_replay_progress.setRange(0, 0)
        self._lbl_replay_current.setText("目前影片：準備中")
        self._lbl_replay_result.setText("摘要檔：--")
        if preview_enabled:
            self._lbl_replay_parallel_status.setText("處理清單：等待第一支影片")
        else:
            self._lbl_replay_parallel_status.setText("處理清單：平行驗證等待工作派發")
        self._lbl_replay_preview.clear()
        if preview_enabled:
            self._lbl_replay_preview.setText("影片預覽載入中")
        else:
            self._lbl_replay_preview.setText("平行驗證中：預覽停用，以提升批次速度")
        self._lbl_pipeline.setText(f"管線：影片回測 {mode_label}")
        self._lbl_camera.setText("影片：準備中")
        self._lbl_face.setText("臉部：統計中")
        self._lbl_fps.setText("FPS：—")
        self._lbl_codec.setText("解析度：—")
        self._append_log(
            f"[影片回測] 開始{mode_label}：{self._replay_dataset_dir} "
            f"(jobs={jobs}, preview={'on' if preview_enabled else 'off'})"
        )
        thread.start()

    def _stop_replay(self) -> None:
        if self._replay_worker is None:
            return
        self._replay_stopping = True
        self._replay_worker.request_stop()
        self._btn_replay_stop.setEnabled(False)
        self._btn_replay_stop.setText("停止中")
        self._lbl_replay_current.setText("目前影片：正在停止，請稍候")
        self._lbl_replay_parallel_status.setText("處理清單：正在停止，已派發的影片會安全收尾")
        self._lbl_pipeline.setText("管線：影片回測 停止中")
        self._append_log("[影片回測] 已送出停止請求，等待目前 frame 安全收尾")

    def _set_replay_controls_running(self, running: bool) -> None:
        self._btn_replay_choose.setEnabled(not running)
        self._btn_replay_start.setEnabled(not running)
        self._btn_replay_parallel.setEnabled(not running)
        self._btn_replay_stop.setEnabled(running)
        self._btn_replay_stop.setText("停止")
        self._spn_replay_jobs.setEnabled(not running)
        self._chk_replay_annotated.setEnabled(not running)

    def _on_replay_progress(
        self,
        event: str,
        current: int,
        total: int,
        summary: ReplayVideoSummary | None,
    ) -> None:
        self._replay_total_count = max(self._replay_total_count, total)
        if event == "video_start":
            self._bar_replay_progress.setRange(0, max(total, 1))
            self._bar_replay_progress.setValue(self._replay_done_count)
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos[key] = summary
                self._lbl_replay_current.setText(
                    f"目前影片：派發 {current}/{total}，正在跑 {len(self._replay_active_videos)} 支"
                )
                self._update_replay_status_strip(summary, prefix=f"影片回測 {self._replay_mode_label}")
            else:
                self._lbl_replay_current.setText(f"目前影片：{current}/{total}")
            self._refresh_replay_parallel_status()
        elif event == "video_done":
            self._bar_replay_progress.setRange(0, max(total, 1))
            self._replay_done_count = max(self._replay_done_count, current)
            self._bar_replay_progress.setValue(self._replay_done_count)
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos.pop(key, None)
                self._replay_recent_done.insert(0, self._format_replay_video_label(summary, include_status=True))
                self._replay_recent_done = self._replay_recent_done[:3]
                failed_text = "，此支失敗" if summary.status == "failed" else ""
                self._lbl_replay_current.setText(
                    f"目前影片：已完成 {self._replay_done_count}/{max(total, 1)}{failed_text}"
                )
                self._update_replay_status_strip(summary, prefix=f"影片回測 {self._replay_mode_label}")
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
                self._lbl_replay_current.setText(
                    f"目前影片：subject {summary.subject} / label {summary.label} "
                    f"{summary.frames}/{total} frames"
                )
            else:
                self._lbl_replay_current.setText(
                    f"目前影片：subject {summary.subject} / label {summary.label} "
                    f"{summary.frames} frames"
                )
            self._update_replay_status_strip(summary, prefix=f"影片回測 {self._replay_mode_label}")
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
        total_text = str(self._replay_total_count) if self._replay_total_count > 0 else "?"
        self._lbl_replay_parallel_status.setText(
            f"進行中：{active_text}\n"
            f"已完成：{self._replay_done_count}/{total_text}；最近完成：{recent_text}"
        )

    def _update_replay_status_strip(self, summary: ReplayVideoSummary, *, prefix: str) -> None:
        self._lbl_pipeline.setText(f"管線：{prefix}")
        self._lbl_camera.setText(f"影片：S{summary.subject} / L{summary.label} {summary.label_name}")
        if summary.frames > 0:
            face_rate = summary.face_frames / max(summary.frames, 1)
            self._lbl_face.setText(f"臉部：{face_rate:.0%} ({summary.face_frames}/{summary.frames})")
        else:
            self._lbl_face.setText("臉部：統計中")
        if summary.fps > 0:
            self._lbl_fps.setText(f"FPS：影片 {summary.fps:.1f}")
        else:
            self._lbl_fps.setText("FPS：—")
        if summary.width > 0 and summary.height > 0:
            self._lbl_codec.setText(f"解析度：{summary.width}x{summary.height}")
        else:
            self._lbl_codec.setText("解析度：—")

    def _on_replay_preview_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        pix = QPixmap.fromImage(image)
        target = self._frame_replay_preview.contentsRect().size()
        if target.width() <= 0 or target.height() <= 0:
            target = QSize(640, 360)
        target = QSize(
            min(target.width(), 960),
            min(target.height(), 440),
        )
        scaled = pix.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._lbl_replay_preview.setPixmap(scaled)

    def _on_replay_finished_ok(self, result: ReplayBatchResult) -> None:
        self._bar_replay_progress.setRange(0, max(result.videos_total, 1))
        self._bar_replay_progress.setValue(result.videos_done + result.videos_failed)
        self._lbl_replay_result.setText(
            f"摘要檔：{result.summary_csv}\n驗證報表：{result.validation_report_csv}\n完整欄位：{result.full_summary_csv}"
        )
        stopped = any(summary.status == "stopped" for summary in result.summaries)
        if stopped or self._replay_stopping:
            state = "已停止"
        elif result.videos_failed > 0:
            state = "完成但有失敗"
        else:
            state = "完成"
        self._lbl_replay_current.setText(f"目前影片：{state}")
        self._replay_done_count = result.videos_done + result.videos_failed
        self._replay_total_count = result.videos_total
        self._replay_active_videos.clear()
        if result.summaries and not self._replay_recent_done:
            self._replay_recent_done = [
                self._format_replay_video_label(summary, include_status=True)
                for summary in reversed(result.summaries[-3:])
            ]
        self._refresh_replay_parallel_status()
        if result.summaries:
            self._update_replay_status_strip(result.summaries[-1], prefix=f"影片回測 {state}")
        else:
            self._lbl_pipeline.setText(f"管線：影片回測 {state}")
        self._append_log(
            f"[影片回測] {state}，完成 {result.videos_done} 支，失敗 {result.videos_failed} 支，"
            f"摘要：{result.summary_csv}"
        )

    def _on_replay_failed(self, msg: str) -> None:
        self._lbl_replay_current.setText("目前影片：批次失敗")
        total_text = str(self._replay_total_count) if self._replay_total_count > 0 else "?"
        self._lbl_replay_parallel_status.setText(
            f"處理清單：批次失敗；已完成 {self._replay_done_count}/{total_text}"
        )
        self._lbl_pipeline.setText("管線：影片回測 失敗")
        self._append_log(f"[影片回測] 批次失敗：{msg}")
        QMessageBox.warning(self, "影片回測", msg)

    def _on_replay_thread_finished(self) -> None:
        self._replay_thread = None
        self._replay_worker = None
        self._replay_stopping = False
        self._replay_mode_label = "回放中"
        self._set_replay_controls_running(False)
        if self._close_after_replay:
            self._close_after_replay = False
            self.close()

    def _on_toggle_all(self, checked: bool) -> None:
        for chk in (self._chk_metrics, self._chk_preview):
            chk.blockSignals(True)
            chk.setChecked(checked)
            chk.blockSignals(False)
        self._sync_overlay_visibility()
        self._append_log(f"[UI] 全部 Overlay → {'顯示' if checked else '隱藏'}")

    def _on_preview_toggled(self, checked: bool) -> None:
        self._preview_overlay.set_preview_visible(checked)
        self._sync_overlay_visibility()
        self._append_log(f"[UI] 鏡頭預覽 Overlay → {'開啟' if checked else '關閉'}")

    def _on_metrics_toggled(self, checked: bool) -> None:
        self._preview_overlay.set_metrics_visible(checked)
        self._sync_overlay_visibility()
        self._append_log(f"[UI] 數值 Overlay → {'開啟' if checked else '關閉'}")

    def _on_lock_toggled(self, checked: bool) -> None:
        self._preview_overlay.apply_lock_state(checked)
        self._append_log(f"[UI] Overlay 鎖定 → {'鎖定（穿透點擊）' if checked else '解鎖（可拖曳）'}")

    def _sync_overlay_visibility(self) -> None:
        """Show overlay window only when pipeline running AND at least one overlay is on."""
        any_on = self._chk_preview.isChecked() or self._chk_metrics.isChecked()
        if self._pipeline_running and any_on:
            self._preview_overlay.refresh_layout()
            self._preview_overlay.show()
        else:
            self._preview_overlay.hide()

    def _on_opacity(self, v: int) -> None:
        self._lbl_opacity.setText(f"{v}%")
        self._preview_overlay.set_opacity(v / 100.0)

    # ── Camera worker ─────────────────────────────────────────────────────────

    def _start_camera_worker(self) -> None:
        cam_idx = self.selected_camera_index
        if cam_idx is None:
            self._append_log("⚠ 請先選擇攝影機再開始。")
            self._pipeline_running = False
            self._btn_start.setText("開始")
            self._lbl_pipeline.setText("管線：停止")
            return

        res_map = {
            "640×480": (640, 480),
            "800×600": (800, 600),
            "1280×720（720p）": (1280, 720),
            "1280×800": (1280, 800),
            "1920×1080（1080p）": (1920, 1080),
        }
        w, h = res_map.get(self._cmb_resolution.currentText(), (1280, 720))
        try:
            target_fps = int(self._cmb_fps.currentText())
        except (ValueError, AttributeError):
            target_fps = 30

        backend = self._cmb_backend.currentData() or "auto"
        backend_label = self._cmb_backend.currentText().split("（")[0].strip()
        horizontal_flip = self._chk_horizontal_flip.isChecked()

        thread = QThread(self)
        worker = CameraStreamWorker(cam_idx, width=w, height=h,
                                    target_fps=target_fps, backend=backend,
                                    horizontal_flip=horizontal_flip)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.camera_info.connect(self._on_camera_info)
        worker.diagnostic_ready.connect(self._append_log)
        worker.fps_ready.connect(self._on_fps)
        worker.failed.connect(self._on_camera_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._cam_thread = thread
        self._cam_worker = worker
        thread.start()
        # Initial frame routing (camera → overlay); may be overridden when
        # rPPG / fatigue workers start and call _update_frame_routing().
        self._update_frame_routing()
        self._append_log(
            f"▶ 相機 [{cam_idx}] 開啟（{backend_label}  {w}×{h} @ {target_fps} fps"
            f"{'，水平翻轉' if horizontal_flip else ''}）"
        )

    def _stop_camera_worker(self) -> None:
        self._stop_analysis_workers()   # stop all analysis before camera
        self._set_record_source(None)
        self._set_frame_source(None)
        if self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue()   # clear all queues
            self._cam_worker.request_stop()
        if self._cam_thread is not None:
            self._cam_thread.quit()
            self._cam_thread.wait(3000)
        self._cam_thread = None
        self._cam_worker = None

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
        want_rppg, _ = self._analysis_needed()
        return want_rppg

    def _on_belt_calib_toggled(self, checked: bool) -> None:
        self._append_log(f"[UI] 心跳帶真值校準 → {'開啟' if checked else '關閉'}")
        if checked and self._pipeline_running and not self._rppg_active():
            self._append_log(
                "⚠ 心跳帶校準需要 rPPG：請勾選「壓力／HRV（心率估測）」，rPPG 啟用後才會開始比對。"
            )
        self._ensure_belt_calibration()

    def _ensure_belt_calibration(self) -> None:
        """依勾選狀態與 rPPG 是否運行，啟停背景心跳帶校準。"""
        want = (
            self._pipeline_running
            and self._chk_belt_calib.isChecked()
            and self._rppg_active()
        )
        if want and self._belt_calibrator is None:
            self._start_belt_calibration()
        elif not want and self._belt_calibrator is not None:
            self._stop_belt_calibration()

    def _start_belt_calibration(self) -> None:
        belt_cfg = load_hr_belt_config()
        self._belt_cfg = belt_cfg
        if not self._belt_runtime.belt_running:
            self._belt_runtime.hub.clear()
            err = self._belt_runtime.start_belt(belt_cfg)
            if err:
                self._append_log(f"⚠ 心跳帶校準啟動失敗：{err}")
                self._lbl_belt_status.setText("心跳帶校準：啟動失敗")
                self._chk_belt_calib.blockSignals(True)
                self._chk_belt_calib.setChecked(False)
                self._chk_belt_calib.blockSignals(False)
                return
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
        self._belt_ui_timer.start()
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
                writer = self._belt_runtime.create_truth_capture_writer()
            except OSError as exc:
                self._belt_truth_capture = None
                self._append_log(f"⚠ belt-truth 錄製檔建立失敗，本次停用錄製：{exc}")
            else:
                self._belt_truth_capture = writer
                self._dispatch_belt_truth_capture(writer)
                self._append_log(f"▶ belt-truth 同步錄製已啟用 → {writer.path}")
        else:
            self._belt_truth_capture = None
        self._update_belt_status_label()

    def _dispatch_belt_truth_capture(self, writer: BeltTruthCaptureWriter | None) -> None:
        """把 belt-truth 錄製 writer（或 None＝停用）下發給目前運行中的 worker。"""
        if self._combined_worker is not None:
            self._combined_worker.set_belt_truth_capture(writer)
        if self._rppg_worker is not None:
            self._rppg_worker.set_belt_truth_capture(writer)

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
        self._belt_ui_timer.stop()
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
        if self._belt_runtime.belt_running:
            self._belt_runtime.stop_belt()
        self._append_log("■ 心跳帶真值校準停止。")
        self._lbl_belt_status.setText("未啟用")
        self._reset_belt_panel()

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
        st = self._belt_runtime.belt_status()
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
        self._update_belt_status_label()

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
        st = self._belt_runtime.belt_status()
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

    def _update_belt_status_label(self) -> None:
        """輪詢心跳帶連線與校準狀態並更新狀態列（QTimer 每秒觸發）。"""
        self._update_belt_panel()
        st = self._belt_runtime.belt_status()
        cal = self._belt_calibrator
        if st is None:
            self._lbl_belt_status.setText("心跳帶校準：停止")
            return
        if st.state != "connected":
            state_text = {
                "idle": "待命",
                "scanning": "掃描中…",
                "connecting": f"連線中…（{st.device_name or st.device_address}）",
                "reconnecting": "斷線，重新連線中…",
                "error": f"錯誤：{st.last_error}" if st.last_error else "錯誤",
                "stopped": "停止",
            }.get(st.state, st.state)
            self._lbl_belt_status.setText(f"心跳帶校準：{state_text}")
            return
        name = st.device_name or st.device_address or "未知裝置"
        parts = [f"心跳帶 {name}"]
        if hr_is_stale(st):
            age = time.time() - (st.last_sample_at or 0.0)
            parts.append(f"⚠ {age:.0f} 秒無心率")
        else:
            parts.append(f"{st.bpm} BPM" if st.bpm > 0 else "等待心率…")
        if st.rr_count > 0:
            parts.append(f"RR×{st.rr_count}")
        if st.battery_level is not None:
            parts.append(f"電量 {st.battery_level}%")
        if st.sensor_contact_supported and not st.sensor_contact_detected:
            parts.append("⚠ 接觸不良")
        if cal is not None:
            cs = cal.state()
            parts.append(f"校正 {cs.offset_bpm:+.1f} BPM")
            if cs.diverged:
                parts.append("⚠ rPPG 偏差大，校正中")
            elif cs.converged:
                parts.append(f"已收斂（信心 {cs.confidence}）")
            else:
                parts.append(f"收斂中 {cs.pairs_used} 配對")
        self._lbl_belt_status.setText("｜".join(parts))

    def _reset_belt_panel(self) -> None:
        """把心跳帶專屬區塊所有欄位重置為「—」（未啟用／停止時呼叫）。"""
        for lbl in (
            self._lbl_belt_bpm, self._lbl_belt_rr, self._lbl_belt_contact,
            self._lbl_belt_battery, self._lbl_belt_rssi, self._lbl_belt_stale,
            self._lbl_belt_device, self._lbl_belt_address, self._lbl_belt_location,
            self._lbl_belt_connected_since, self._lbl_belt_notifications, self._lbl_belt_last_error,
            self._lbl_belt_hrv_rmssd, self._lbl_belt_hrv_sdnn, self._lbl_belt_hrv_lfhf,
            self._lbl_belt_hrv_conf, self._lbl_belt_hrv_warmup,
            self._lbl_belt_calib_offset, self._lbl_belt_calib_raw_resid, self._lbl_belt_calib_corr_resid,
            self._lbl_belt_calib_confidence, self._lbl_belt_calib_status, self._lbl_belt_calib_pairs,
        ):
            lbl.setText("—")

    def _update_belt_panel(self) -> None:
        """更新「心跳帶」專屬區塊的所有數值（即時／連線／HRV／rPPG 校準）。

        唯讀輪詢既有狀態物件，不改動任何校準/worker/BLE 邏輯與數值行為；
        HRV 僅供顯示，絕不寫回任何會被疲勞融合分數讀取的欄位。
        """
        st = self._belt_runtime.belt_status()
        cal = self._belt_calibrator
        if st is None:
            self._reset_belt_panel()
            return

        # 即時
        self._lbl_belt_bpm.setText(f"{st.bpm} BPM" if st.bpm > 0 else "—")
        self._lbl_belt_rr.setText(str(st.rr_count) if st.rr_count > 0 else "—")
        if st.sensor_contact_supported:
            self._lbl_belt_contact.setText("良好" if st.sensor_contact_detected else "⚠ 接觸不良")
        else:
            self._lbl_belt_contact.setText("不支援回報")
        self._lbl_belt_battery.setText(f"{st.battery_level}%" if st.battery_level is not None else "—")
        self._lbl_belt_rssi.setText(f"{st.rssi:.0f} dBm" if st.rssi else "—")
        if st.state == "connected" and hr_is_stale(st):
            age = time.time() - (st.last_sample_at or 0.0)
            self._lbl_belt_stale.setText(f"⚠ {age:.0f} 秒無心率")
        elif st.state == "connected":
            self._lbl_belt_stale.setText("正常")
        else:
            self._lbl_belt_stale.setText("—")

        # 連線
        self._lbl_belt_device.setText(st.device_name or "—")
        self._lbl_belt_address.setText(st.device_address or "—")
        self._lbl_belt_location.setText(st.sensor_location or "—")
        if st.connected_since is not None:
            self._lbl_belt_connected_since.setText(f"{time.time() - st.connected_since:.0f} 秒")
        else:
            self._lbl_belt_connected_since.setText("—")
        self._lbl_belt_notifications.setText(str(st.notifications) if st.notifications else "—")
        self._lbl_belt_last_error.setText(st.last_error or "—")

        # HRV（rppg.watch_physio.compute_watch_physio，唯讀顯示、不進疲勞融合分數）
        try:
            samples = self._belt_runtime.hub.snapshot()
            physio = compute_watch_physio(samples)
        except Exception:
            physio = None
        if physio is not None and physio.sample_count >= 2:
            self._lbl_belt_hrv_rmssd.setText(f"{physio.rmssd:.1f} ms" if physio.rmssd > 0 else "暖機中")
            self._lbl_belt_hrv_sdnn.setText(f"{physio.sdnn:.1f} ms" if physio.sdnn > 0 else "暖機中")
            self._lbl_belt_hrv_lfhf.setText(f"{physio.lf_hf:.2f}" if physio.lf_hf > 0 else "暖機中")
            self._lbl_belt_hrv_conf.setText(physio.hrv_confidence)
            self._lbl_belt_hrv_warmup.setText(f"{physio.warmup_progress * 100:.0f}%")
        else:
            for lbl in (self._lbl_belt_hrv_rmssd, self._lbl_belt_hrv_sdnn, self._lbl_belt_hrv_lfhf, self._lbl_belt_hrv_conf):
                lbl.setText("暖機中")
            self._lbl_belt_hrv_warmup.setText(f"{physio.warmup_progress * 100:.0f}%" if physio is not None else "0%")

        # rPPG 校準（沿用現有 OnlineBpmCalibrator，不新建校準器）
        if cal is not None:
            cs = cal.state()
            self._lbl_belt_calib_offset.setText(f"{cs.offset_bpm:+.1f} BPM")
            self._lbl_belt_calib_raw_resid.setText(f"{cs.raw_residual_bpm:.1f} BPM")
            self._lbl_belt_calib_corr_resid.setText(f"{cs.corrected_residual_bpm:.1f} BPM")
            self._lbl_belt_calib_confidence.setText(cs.confidence)
            if cs.diverged:
                self._lbl_belt_calib_status.setText("⚠ 偏差大，校正中")
            elif cs.converged:
                self._lbl_belt_calib_status.setText("已收斂")
            else:
                self._lbl_belt_calib_status.setText("收斂中")
            self._lbl_belt_calib_pairs.setText(f"{cs.pairs_used} / {cs.total_observations}")
        else:
            for lbl in (
                self._lbl_belt_calib_offset, self._lbl_belt_calib_raw_resid, self._lbl_belt_calib_corr_resid,
                self._lbl_belt_calib_confidence, self._lbl_belt_calib_status, self._lbl_belt_calib_pairs,
            ):
                lbl.setText("—")

    def _analysis_needed(self) -> tuple[bool, bool]:
        """Return (want_rppg, want_fatigue) from checkbox state."""
        want_fatigue = self._chk_behavior.isChecked()
        return self._chk_stress.isChecked(), want_fatigue

    def _stop_analysis_workers(self) -> None:
        """Stop ALL analysis workers in the correct order."""
        self._stop_combined_worker()
        self._stop_rppg_worker()
        self._stop_fatigue_worker()

    def _restart_analysis_workers(self) -> None:
        """(Re)start whichever analysis workers the UI requires.

        Called whenever a checkbox is toggled while the pipeline is running.
        Stops everything first, then starts the right combination:
          - both enabled  → CombinedWorker (one MediaPipe instance, all annotations)
          - rPPG only     → RppgWorker
          - fatigue only  → FatigueWorker
          - neither       → nothing (raw camera frames)
        """
        if not self._pipeline_running:
            return
        self._stop_analysis_workers()
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        want_rppg, want_fatigue = self._analysis_needed()
        if want_rppg and want_fatigue:
            self._start_combined_worker(enable_rppg=True)
        elif want_rppg:
            self._start_rppg_worker()
        elif want_fatigue:
            self._start_fatigue_worker()
        else:
            self._update_frame_routing()   # restore raw camera feed
        self._ensure_belt_calibration()   # rPPG 是否運行改變時，同步啟停背景校準
        self._emit_web_metrics(force=True)

    # ── Combined worker ───────────────────────────────────────────────────────

    def _start_combined_worker(self, enable_rppg: bool = True) -> None:
        if self._combined_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線。")
            return

        self._combined_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._combined_queue)

        thread = QThread(self)
        worker = CombinedWorker(
            self._combined_queue,
            enable_rppg=enable_rppg, enable_fatigue=True,
            target_fps=30.0, buffer_sec=12.0,
            calibration_loader=self._load_rppg_calibration_version,
            live_feed_writer=write_live_feed,
            fuser_config=FuserConfig.for_rppg(),
            personal_profile=self._personal_profile,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.rppg_metrics_ready.connect(self._on_rppg_metrics)
        worker.fatigue_metrics_ready.connect(self._on_fatigue_metrics)
        worker.fused_score_ready.connect(self._on_fused_score)
        worker.face_detected.connect(self._on_face_detected)
        worker.status_changed.connect(self._on_combined_status)
        worker.failed.connect(self._on_combined_failed)
        worker.candidate_bpm_ready.connect(self._on_candidate_bpm_ready)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._combined_thread = thread
        self._combined_worker = worker
        thread.start()

        self._begin_auto_baseline()
        self._update_frame_routing()
        self._preview_overlay.show_rppg_panel(enable_rppg)
        self._preview_overlay.show_fatigue_panel(True)
        self._preview_overlay.show_fused_panel(True)
        self._append_log("▶ 合併引擎啟動（rPPG + 行為警覺，單 MediaPipe 實例）")

    def _stop_combined_worker(self) -> None:
        if self._combined_worker is not None:
            self._combined_worker.request_stop()
        if self._combined_thread is not None:
            self._combined_thread.quit()
            self._combined_thread.wait(5000)
        self._combined_thread = None
        self._combined_worker = None
        self._end_baseline_collection()
        if self._combined_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._combined_queue)
        self._combined_queue = None
        self._preview_overlay.show_rppg_panel(False)
        self._preview_overlay.show_fatigue_panel(False)
        self._preview_overlay.show_fused_panel(False)
        self._update_frame_routing()

    def _on_fused_score(self, score: object) -> None:
        self._preview_overlay.update_fused_score(score)  # type: ignore[arg-type]
        self._latest_fused_score = score
        self._record_metrics()
        self._emit_web_metrics()

    def _on_combined_status(self, msg: str) -> None:
        self._lbl_pipeline.setText(f"引擎：{msg}")

    def _on_combined_failed(self, msg: str) -> None:
        self._append_log(f"✗ 合併引擎錯誤：{msg}")
        self._stop_combined_worker()
        self._chk_stress.setChecked(False)
        self._chk_behavior.setChecked(False)
        QMessageBox.warning(self, "引擎錯誤", msg)

    # ── rPPG worker (solo — only when fatigue is OFF) ─────────────────────────

    def _start_rppg_worker(self) -> None:
        if self._rppg_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線再開啟 rPPG。")
            return

        self._bgr_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._bgr_queue)

        thread = QThread(self)
        worker = RppgWorker(
            self._bgr_queue, target_fps=30.0, buffer_sec=12.0,
            calibration_loader=self._load_rppg_calibration_version,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.metrics_ready.connect(self._on_rppg_metrics)
        worker.face_detected.connect(self._on_face_detected)
        worker.status_changed.connect(self._on_rppg_status)
        worker.failed.connect(self._on_rppg_failed)
        worker.candidate_bpm_ready.connect(self._on_candidate_bpm_ready)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._rppg_thread = thread
        self._rppg_worker = worker
        thread.start()

        self._update_frame_routing()
        self._preview_overlay.show_rppg_panel(True)
        self._append_log("▶ rPPG 引擎啟動（MediaPipe Face Landmarker + POS）")

    def _stop_rppg_worker(self) -> None:
        if self._rppg_worker is not None:
            self._rppg_worker.request_stop()
        if self._rppg_thread is not None:
            self._rppg_thread.quit()
            self._rppg_thread.wait(4000)
        self._rppg_thread = None
        self._rppg_worker = None
        if self._bgr_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._bgr_queue)
        self._bgr_queue = None
        self._update_frame_routing()
        self._preview_overlay.show_rppg_panel(False)
        self._lbl_face.setText("臉部：—")

    def _on_stress_toggled(self, checked: bool) -> None:
        self._append_log(f"[UI] 壓力／HRV → {'開啟' if checked else '關閉'}")
        self._restart_analysis_workers()

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
        self._preview_overlay.update_rppg_metrics(metrics)  # type: ignore[arg-type]
        self._latest_rppg_metrics = metrics
        self._record_metrics()
        self._emit_web_metrics()

    def _on_face_detected(self, detected: bool) -> None:
        self._lbl_face.setText("臉部：偵測中 ✓" if detected else "臉部：未偵測到")

    def _on_rppg_status(self, msg: str) -> None:
        self._lbl_pipeline.setText(f"rPPG：{msg}")

    def _on_rppg_failed(self, msg: str) -> None:
        self._append_log(f"✗ rPPG 錯誤：{msg}")
        self._stop_rppg_worker()
        self._chk_stress.setChecked(False)
        QMessageBox.warning(self, "rPPG 錯誤", msg)

    # ── Fatigue / Behaviour Alertness worker ──────────────────────────────────

    def _start_fatigue_worker(self) -> None:
        if self._fatigue_worker is not None:
            return
        if self._cam_worker is None:
            self._append_log("⚠ 請先啟動相機管線再開啟行為警覺。")
            return

        self._fatigue_queue = queue.Queue(maxsize=2)
        self._cam_worker.attach_bgr_queue(self._fatigue_queue)

        thread = QThread(self)
        worker = FatigueWorker(self._fatigue_queue, target_fps=30.0,
                               personal_profile=self._personal_profile)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.metrics_ready.connect(self._on_fatigue_metrics)
        worker.face_detected.connect(self._on_fatigue_face_detected)
        worker.status_changed.connect(self._on_fatigue_status)
        worker.failed.connect(self._on_fatigue_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._fatigue_thread = thread
        self._fatigue_worker = worker
        thread.start()

        self._begin_auto_baseline()
        self._update_frame_routing()
        self._preview_overlay.show_fatigue_panel(True)
        self._append_log("▶ 行為警覺引擎啟動（V2：EAR + 瞳孔 + 注視 + 頭部）")

    def _stop_fatigue_worker(self) -> None:
        if self._fatigue_worker is not None:
            self._fatigue_worker.request_stop()
        if self._fatigue_thread is not None:
            self._fatigue_thread.quit()
            self._fatigue_thread.wait(4000)
        self._fatigue_thread = None
        self._fatigue_worker = None
        self._end_baseline_collection()
        if self._fatigue_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._fatigue_queue)
        self._fatigue_queue = None
        self._update_frame_routing()
        self._preview_overlay.show_fatigue_panel(False)

    def _on_behavior_toggled(self, checked: bool) -> None:
        self._append_log(f"[UI] 行為警覺 → {'開啟' if checked else '關閉'}")
        self._restart_analysis_workers()

    def _on_fatigue_metrics(self, metrics: object) -> None:
        self._preview_overlay.update_fatigue_metrics(metrics)  # type: ignore[arg-type]
        self._latest_fatigue_metrics = metrics
        self._alarm_controller.on_metrics(metrics)
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
        # 自動基線只在「尚無 manual profile」時作為本 session 暫定值套用，不落檔。
        if self._personal_profile is not None and self._personal_profile.source == "manual":
            return
        if not prof.valid:
            self._set_profile_status("個人基線：自動校準樣本不足，沿用預設")
            return
        self._hot_swap_profile(prof)
        self._set_profile_status("個人基線：自動（暫定，未儲存）")
        self._append_log("[基線] 自動清醒基線已建立（本 session 暫定，未落檔）")

    def _finalize_manual_baseline(self, collector: PersonalBaselineCollector) -> None:
        prof = collector.finalize(source="manual")
        self._btn_record_baseline.setEnabled(True)
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
        if hasattr(self, "_lbl_profile_status"):
            self._lbl_profile_status.setText(text)

    def _on_record_baseline_clicked(self) -> None:
        if self._active_fatigue_worker() is None:
            self._set_profile_status("個人基線：請先按「開始」啟動偵測")
            return
        self._manual_baseline_collector = PersonalBaselineCollector(
            window_sec=60.0, now_iso=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._btn_record_baseline.setEnabled(False)
        self._set_profile_status("記錄清醒基線中… 0%")
        self._append_log("[基線] 開始手動記錄清醒基線（約 60 秒，請保持清醒自然狀態）")

    def _on_fatigue_face_detected(self, detected: bool) -> None:
        if self._rppg_worker is None:
            self._lbl_face.setText("臉部：偵測中 ✓" if detected else "臉部：未偵測到")

    def _on_fatigue_status(self, msg: str) -> None:
        self._lbl_pipeline.setText(f"警覺：{msg}")

    def _on_fatigue_failed(self, msg: str) -> None:
        self._append_log(f"✗ 行為警覺錯誤：{msg}")
        self._stop_fatigue_worker()
        self._chk_behavior.setChecked(False)
        QMessageBox.warning(self, "行為警覺錯誤", msg)

    def _on_camera_info(self, codec: str, w: int, h: int, fps: float) -> None:
        """Called once after camera opens — shows actual driver-reported settings."""
        fps_str = f"{fps:.0f}" if fps > 0 else "—"
        self._lbl_codec.setText(f"編碼：{codec}")
        self._lbl_fps.setText(f"FPS：{fps_str}")
        self._last_camera_info = {"codec": codec, "width": w, "height": h}
        cam_text = self._cmb_camera.currentText()
        self._append_log(
            f"[相機] 實際格式 → 編碼：{codec}  解析度：{w}×{h}  FPS：{fps_str}"
        )
        self._preview_overlay.update_camera_info(codec, w, h, cam_text)
        self._emit_web_metrics(force=True)

    def _on_frame(self, image) -> None:
        self._preview_overlay.update_frame(image)
        self._emit_web_frame(image)

    def _on_record_frame(self, image) -> None:
        if self._video_queue is None:
            return
        try:
            self._video_queue.put_nowait((time.perf_counter(), image))
        except queue.Full:
            pass

    def _on_fps(self, fps: float) -> None:
        self._preview_overlay.update_fps(fps)
        self._lbl_fps.setText(f"FPS：{fps:.1f}")
        self._last_fps = float(fps)
        self._emit_web_metrics()

    def _on_camera_failed(self, msg: str) -> None:
        self._append_log(f"✗ 相機錯誤：{msg}")
        self._cancel_pending_auto_capture_timer()
        self._rollback_auto_capture_toggles()
        if self._belt_calibrator is not None:
            self._stop_belt_calibration()
        self._stop_analysis_workers()
        self._set_record_source(None)
        self._set_frame_source(None)
        if self._cam_worker is not None:
            self._cam_worker.request_stop()
        self._pipeline_running = False
        self._cam_worker = None
        self._cam_thread = None
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        self._last_fps = 0.0
        self._last_camera_info = {"codec": "", "width": 0, "height": 0}
        self._btn_start.setText("開始")
        self._lbl_pipeline.setText("管線：停止")
        self._lbl_fps.setText("FPS：—")
        self._sync_overlay_visibility()
        self._emit_web_metrics(force=True)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("攝影機錯誤")
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(msg)
        dlg.setInformativeText(
            "請確認：\n"
            "• 相機未被其他程式（OBS、Teams 等）佔用\n"
            "• USB 連接穩定，嘗試重新插拔後再按「開始」"
        )
        dlg.exec()

    # ── Pipeline toggle ───────────────────────────────────────────────────────

    def _toggle_pipeline(self) -> None:
        self._pipeline_running = not self._pipeline_running
        if self._pipeline_running:
            self._latest_rppg_metrics = None
            self._latest_fatigue_metrics = None
            self._latest_fused_score = None
            self._btn_start.setText("停止")
            self._lbl_pipeline.setText("管線：運作中")
            self._lbl_fps.setText("FPS：—")
            self._lbl_face.setText("臉部：—")
            self._start_camera_worker()
            if not self._pipeline_running:
                self._sync_overlay_visibility()
                self._emit_web_metrics(force=True)
                return
            # Start the appropriate analysis worker(s) based on checkbox state
            want_rppg, want_fatigue = self._analysis_needed()
            if want_rppg and want_fatigue:
                self._start_combined_worker(enable_rppg=True)
            elif want_rppg:
                self._start_rppg_worker()
            elif want_fatigue:
                self._start_fatigue_worker()
            self._ensure_belt_calibration()   # rPPG 運行時視勾選啟動背景校準
            self._sync_overlay_visibility()
            if self._chk_auto_record.isChecked() and not self._recording:
                self._toggle_recording()
            self._emit_web_metrics(force=True)
        else:
            self._cancel_pending_auto_capture_timer()
            self._rollback_auto_capture_toggles()
            self._latest_rppg_metrics = None
            self._latest_fatigue_metrics = None
            self._latest_fused_score = None
            self._last_fps = 0.0
            self._last_camera_info = {"codec": "", "width": 0, "height": 0}
            self._btn_start.setText("開始")
            self._lbl_pipeline.setText("管線：停止")
            self._lbl_fps.setText("FPS：—")
            self._lbl_codec.setText("編碼：—")
            if self._belt_calibrator is not None:
                self._stop_belt_calibration()   # 停止前先存本次 session 校準版本
            self._stop_camera_worker()
            self._sync_overlay_visibility()
            self._append_log("■ 管線停止。")
            if self._recording:
                self._recording = False
                self._btn_record.setText("開始記錄")
                self._lbl_record.setText("記錄狀態：未啟動")
                self._stop_recording()
                self._append_log("○ 管線停止，已一併結束記錄。")
            self._emit_web_metrics(force=True)
            if self._benchmark_active:
                self._benchmark_active = False
                self._btn_bench.setText("DL 基準測試（120s）")
                self._lbl_bench.setText("")
                self._append_log("基準測試已隨管線停止。")

    def _toggle_recording(self) -> None:
        if not self._pipeline_running and not self._recording:
            QMessageBox.information(self, "記錄", "請先啟動管線再開始記錄（示範規則）。")
            return
        self._recording = not self._recording
        if self._recording:
            try:
                self._start_recording()
            except Exception as exc:
                QMessageBox.warning(self, "記錄", f"無法啟動記錄：{exc}")
                self._recording = False
                return
            self._btn_record.setText("停止記錄")
            self._lbl_record.setText("記錄狀態：進行中")
            if self._recording_db_path is not None:
                self._append_log(f"● 記錄開始 → {self._recording_db_path}")
            else:
                self._append_log("● 記錄開始 → recordings/")
            self._emit_web_metrics(force=True)
        else:
            self._cancel_pending_auto_capture_timer()
            self._rollback_auto_capture_toggles()
            self._btn_record.setText("開始記錄")
            self._lbl_record.setText("記錄狀態：未啟動")
            self._stop_recording()
            self._append_log("○ 記錄停止。")
            self._emit_web_metrics(force=True)

    def _cancel_pending_auto_capture_timer(self) -> None:
        """停止自動採集倒數計時器（若有）並還原其 UI 狀態：按鈕文字、時長 spinbox
        啟用狀態。刻意不動錄製／心跳帶／壓力勾選狀態——那些由呼叫端依情境決定是否
        一併回滾（見 `_rollback_auto_capture_toggles`）。供所有既有「停止」入口
        （手動停止記錄／停止管線／相機失敗／關閉視窗）呼叫，避免自動採集計時器在
        它所依附的錄製已被其他操作結束後，仍在背景倒數並於稍後誤停一段不相關的新錄製。"""
        if self._auto_capture_timer is None:
            return
        self._auto_capture_timer.stop()
        self._auto_capture_timer.deleteLater()
        self._auto_capture_timer = None
        self._btn_auto_capture.setText("自動採集")
        self._spn_auto_capture_seconds.setEnabled(True)

    def _rollback_auto_capture_toggles(self) -> None:
        """回滾本次自動採集自己強制勾選的核取方塊，且只在目前仍是勾選狀態才動，
        避免覆蓋使用者在期間手動做的操作。"""
        if self._auto_capture_started_belt_calib and self._chk_belt_calib.isChecked():
            self._chk_belt_calib.setChecked(False)
        self._auto_capture_started_belt_calib = False
        if self._auto_capture_started_stress and self._chk_stress.isChecked():
            self._chk_stress.setChecked(False)
        self._auto_capture_started_stress = False

    def _on_auto_capture_clicked(self) -> None:
        """一鍵自動採集：只串接既有觸發點（setChecked／_toggle_pipeline／_toggle_recording），
        不重寫任何 worker 啟停、記錄或心跳帶校準邏輯本身。"""
        if self._auto_capture_timer is not None:
            # 倒數中再按一次 → 提前停止。
            self._append_log("■ 自動採集：使用者提前按下停止。")
            self._finish_auto_capture(early=True)
            return

        include_belt = self._chk_auto_capture_belt.isChecked()
        self._auto_capture_started_belt_calib = False
        self._auto_capture_started_stress = False
        self._auto_capture_started_recording = False
        if include_belt:
            if not self._chk_stress.isChecked():
                self._chk_stress.setChecked(True)
                self._auto_capture_started_stress = True
            if not self._chk_belt_calib.isChecked():
                self._chk_belt_calib.setChecked(True)
                self._auto_capture_started_belt_calib = True

        pipeline_started_by_this_call = False
        if not self._pipeline_running:
            self._toggle_pipeline()
            if not self._pipeline_running:
                self._append_log("⚠ 自動採集：管線未能啟動，已中止（請先選擇攝影機）。")
                self._rollback_auto_capture_toggles()
                return
            pipeline_started_by_this_call = True

        if not self._recording:
            self._toggle_recording()
            if not self._recording:
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

        duration_s = self._spn_auto_capture_seconds.value()
        self._btn_auto_capture.setText("停止自動採集")
        self._spn_auto_capture_seconds.setEnabled(False)
        self._append_log(
            f"▶ 自動採集開始（{duration_s}s，{'含心跳帶' if include_belt else '僅記錄'}）"
        )
        self._auto_capture_timer = QTimer(self)
        self._auto_capture_timer.setSingleShot(True)
        self._auto_capture_timer.timeout.connect(lambda: self._finish_auto_capture(early=False))
        self._auto_capture_timer.start(duration_s * 1000)

    def _finish_auto_capture(self, early: bool) -> None:
        """自動採集收尾：只呼叫既有停止觸發點，belt-truth capture writer 的關閉交給
        既有 _stop_belt_calibration（經由 unchecked _chk_belt_calib 觸發）自行處理。
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
        # _chk_belt_calib 觸發 _stop_belt_calibration（把 _belt_truth_capture 設回
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
        if started_recording and self._recording and self._recording_db_path == expected_db_path:
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
        QMessageBox.information(self, "自動採集完成", "\n".join(lines))

    def _toggle_benchmark(self) -> None:
        if not self._pipeline_running:
            QMessageBox.information(self, "基準測試", "請先啟動管線再執行基準測試（示範）。")
            return
        self._benchmark_active = not self._benchmark_active
        if self._benchmark_active:
            self._btn_bench.setText("停止基準測試")
            self._lbl_bench.setText("錄製中 0s／120s（示範）")
            self._append_log("⏱ DL 基準測試開始（示範，無實際採樣）")
        else:
            self._btn_bench.setText("DL 基準測試（120s）")
            self._lbl_bench.setText("")
            self._append_log("基準測試已停止（示範）。")

    def _on_camera_combo_changed(self, _index: int) -> None:
        data = self._cmb_camera.currentData()
        text = self._cmb_camera.currentText()
        if data is None:
            self._lbl_camera.setText("相機：未選擇")
        else:
            self._lbl_camera.setText(f"相機：{text}")

    @property
    def selected_camera_index(self) -> int | None:
        """OpenCV device index for the current combo selection, or None if placeholder."""
        d = self._cmb_camera.currentData()
        if d is None:
            return None
        try:
            return int(d)
        except (TypeError, ValueError):
            return None

    def _on_hotkeys(self) -> None:
        dlg = HotkeySettingsDialog(self._hotkeys, self)
        if dlg.exec():
            self._hotkeys = dlg.get_config()
            self._apply_hotkey_shortcuts()
            if self._global_hotkey_enabled:
                self._append_log("快捷鍵已更新（全域熱鍵已重新註冊）。")
            else:
                self._append_log("快捷鍵已更新（非 Windows 平台無全域熱鍵）。")

    def _on_user_profile(self) -> None:
        dlg = UserProfileDialog(self._user, self)
        if dlg.exec():
            self._user = dlg.get_profile()
            self._append_log(
                f"使用者資料已更新：年齡 {self._user.age}，"
                f"{self._user.height_cm} cm / {self._user.weight_kg} kg"
            )

    def _on_alarm_settings(self) -> None:
        dlg = AlarmSettingsDialog(self._alarm_config, self)
        if not dlg.exec():
            return
        self._alarm_config = dlg.get_config()
        self._alarm_controller.set_config(self._alarm_config)
        try:
            path = self._save_settings()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "保存失敗",
                f"警報器設定已套用，但無法寫入 settings.json：{exc}",
            )
            self._append_log(f"⚠ 警報器設定已套用，但保存失敗：{exc}")
            return
        state = "已啟用" if self._alarm_config.enabled else "已關閉"
        self._append_log(f"🔔 警報器設定已更新（{state}）並保存 → {path}")

    def _open_recordings_dir(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rec = root / "recordings"
        rec.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(rec)))

    def _on_save_layout(self) -> None:
        try:
            path = self._save_settings()
        except OSError as exc:
            QMessageBox.warning(self, "保存失敗", f"無法寫入設定檔：{exc}")
            self._append_log(f"✗ 保存配置失敗：{exc}")
            return
        QMessageBox.information(self, "保存", f"配置與布局已保存：\n{path}")
        self._append_log(f"💾 已保存配置與布局 → {path}")

    def _on_reset_layout(self) -> None:
        r = QMessageBox.question(
            self,
            "重置",
            "確定要重置為原廠設定嗎？（示範）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._cmb_resolution.setCurrentText("1280×720（720p）")
            self._cmb_fps.setCurrentText("30")
            self._sld_opacity.setValue(55)
            self._chk_metrics.setChecked(True)
            self._chk_preview.setChecked(False)
            self._chk_lock.setChecked(True)
            self._chk_stress.setChecked(False)
            self._act_web_allow_lan.setChecked(False)
            self._alarm_config = AlarmConfig.defaults()
            self._alarm_controller.set_config(self._alarm_config)
            self._restart_web_server()
            try:
                self._save_settings()
            except OSError as exc:
                self._append_log(f"⚠ 重置後保存 settings.json 失敗：{exc}")
            self._append_log("🔄 已重置為示範預設值。")

    def _on_web_allow_lan_toggled(self, checked: bool) -> None:
        self._restart_web_server()
        try:
            self._save_settings()
        except OSError as exc:
            self._append_log(f"⚠ 區域網設定已套用，但保存 settings.json 失敗：{exc}")
        state = "已啟用" if checked else "已關閉"
        self._append_log(
            f"🌐 Web 儀表板區域網存取{state}：{self._format_web_dashboard_message()}"
        )
        self._append_log("提示：請重新整理已開啟的 Web 儀表板頁面，以重新連線 Socket.IO。")
        if checked:
            self._append_log(
                f"提示：其他裝置若無法連線，請檢查防火牆是否放行 TCP {WEB_DASHBOARD_DEFAULT_PORT}。"
            )
            self._append_log(
                "⚠ 警告：LAN 模式將以未加密 HTTP 廣播人臉影像與生理數據，僅限受信任網路使用；"
                "存取需附帶網址中的 token。"
            )

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
        if not self._web_allow_lan_enabled() or len(options) == 1:
            return options[0][1]

        display_labels = [label for label, _url in options]
        default_index = 0
        for index, (_label, url) in enumerate(options):
            if not url.startswith("http://127.0.0.1"):
                default_index = index
                break

        choice, ok = QInputDialog.getItem(
            self,
            "開啟 Web 儀表板",
            "已啟用區域網存取，請選擇要開啟的網址：",
            display_labels,
            default_index,
            False,
        )
        if not ok:
            return None
        for label, url in options:
            if label == choice:
                return url
        return options[default_index][1]

    def _on_web_info(self) -> None:
        if self._web_server is None:
            self._start_web_server()
        if self._web_server is None:
            QMessageBox.warning(
                self,
                "Web 儀表板",
                "Web 儀表板啟動失敗，請確認已安裝 Flask/Socket.IO 相依套件。",
            )
            return
        url_str = self._pick_web_dashboard_url()
        if url_str is None:
            return
        QDesktopServices.openUrl(QUrl(url_str))
        all_urls = "\n".join(self._web_dashboard_urls())
        QMessageBox.information(
            self,
            "Web 儀表板",
            f"已開啟 Web 儀表板：\n{url_str}\n\n"
            f"可用網址：\n{all_urls}\n"
            f"\n若瀏覽器無法連線，請確認防火牆或埠 {WEB_DASHBOARD_DEFAULT_PORT} 未被佔用。"
            + (
                "\n\n其他裝置請使用「區域網」網址，不要用 127.0.0.1。"
                if self._web_allow_lan_enabled()
                else ""
            ),
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._replay_thread is not None:
            self._close_after_replay = True
            self._stop_replay()
            event.ignore()
            return
        self._unregister_global_hotkeys()
        self._cancel_pending_auto_capture_timer()
        if self._belt_calibrator is not None:
            self._stop_belt_calibration()   # 存本次 session 校準版本
        self._belt_ui_timer.stop()
        self._belt_runtime.stop_belt()
        self._stop_web_server()
        self._stop_recording()
        self._stop_camera_worker()
        self._preview_overlay.hide()
        self._preview_overlay.close()
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802
        if self._global_hotkey_enabled and event_type == "windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:
                self._on_global_hotkey(int(msg.wParam))
                return True, 0
        return super().nativeEvent(cast(Any, event_type), message)
