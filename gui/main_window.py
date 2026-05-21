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

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.camera_stream_worker import CameraStreamWorker
from gui.combined_worker import CombinedWorker
from gui.dialogs import HotkeyConfig, HotkeySettingsDialog, UserProfile, UserProfileDialog
from gui.fatigue_worker import FatigueWorker
from gui.metrics_recorder import MetricsRecorder
from gui.preview_overlay_window import PreviewOverlayWindow
from rppg.rppg_worker import RppgWorker
from gui.video_recorder import VideoRecorderWorker
from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread


def application_stylesheet() -> str:
    return """
    QWidget {
        background-color: #16181d;
        color: #e8eaed;
        font-size: 13px;
        font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
    }
    QMainWindow, QDialog {
        background-color: #16181d;
    }
    QGroupBox {
        font-weight: 600;
        border: 1px solid #2a2f38;
        border-radius: 10px;
        margin-top: 14px;
        padding: 14px 12px 12px 12px;
        background-color: #1c2028;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: #9aa0a9;
    }
    QLabel#titleLabel {
        font-size: 22px;
        font-weight: 700;
        color: #f1f3f5;
        letter-spacing: 0.5px;
    }
    QLabel#subtitleLabel {
        font-size: 12px;
        color: #868e96;
        margin-bottom: 4px;
    }
    QLabel#hintLabel {
        color: #868e96;
        font-size: 12px;
    }
    QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #252a33;
        border: 1px solid #343a46;
        border-radius: 6px;
        padding: 6px 10px;
        min-height: 22px;
    }
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: #4dabf7;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QPushButton {
        background-color: #2a3038;
        border: 1px solid #3d4450;
        border-radius: 8px;
        padding: 8px 16px;
        min-height: 20px;
    }
    QPushButton:hover {
        background-color: #343b46;
        border-color: #5c677a;
    }
    QPushButton:pressed {
        background-color: #1f2329;
    }
    QPushButton#primaryButton {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #339af0, stop:1 #228be6);
        border: 1px solid #4dabf7;
        color: #ffffff;
        font-weight: 600;
        padding: 10px 22px;
    }
    QPushButton#primaryButton:hover {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #4dabf7, stop:1 #339af0);
    }
    QPushButton#dangerButton {
        background-color: #2f1f24;
        border-color: #c92a2a;
        color: #ffa8a8;
    }
    QCheckBox {
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid #495057;
        background-color: #252a33;
    }
    QCheckBox::indicator:checked {
        background-color: #339af0;
        border-color: #4dabf7;
    }
    QSlider::groove:horizontal {
        height: 6px;
        background: #2a3038;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        width: 16px;
        margin: -6px 0;
        border-radius: 8px;
        background: #339af0;
        border: 2px solid #74c0fc;
    }
    QScrollArea {
        border: none;
        background: transparent;
    }
    QFrame#statusBarFrame {
        background-color: #14161a;
        border: 1px solid #2a2f38;
        border-radius: 8px;
        padding: 8px 12px;
    }
    QTextEdit, QPlainTextEdit {
        background-color: #14161a;
        border: 1px solid #2a2f38;
        border-radius: 8px;
        padding: 8px;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
    }
    QMenuBar {
        background-color: #14161a;
        border-bottom: 1px solid #2a2f38;
        padding: 2px;
    }
    QMenuBar::item:selected {
        background-color: #252a33;
        border-radius: 4px;
    }
    QMenu {
        background-color: #1c2028;
        border: 1px solid #343a46;
        padding: 4px;
    }
    QMenu::item:selected {
        background-color: #339af0;
        color: #ffffff;
    }
    QStatusBar {
        background-color: #14161a;
        border-top: 1px solid #2a2f38;
        color: #868e96;
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
        self._web_frame_interval = 0.2
        self._web_last_emit = 0.0
        self._web_last_frame_emit = 0.0

        self._build_menu()
        self._build_central()

        self._load_settings()
        self._apply_hotkey_shortcuts()
        self._apply_overlay_state()
        self._start_web_server()

        self.statusBar().showMessage("就緒 — 選擇攝影機後按「開始」可預覽（無 MediaPipe）")

    def _build_menu(self) -> None:
        act_hotkeys = QAction("快捷鍵設定…", self)
        act_hotkeys.triggered.connect(self._on_hotkeys)

        act_profile = QAction("使用者資料…", self)
        act_profile.triggered.connect(self._on_user_profile)

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

        m_settings = self.menuBar().addMenu("設定")
        m_settings.addAction(act_hotkeys)
        m_settings.addAction(act_profile)
        m_settings.addSeparator()
        m_settings.addAction(act_refresh)
        m_settings.addAction(act_recordings)
        m_settings.addSeparator()
        m_settings.addAction(act_save)
        m_settings.addAction(act_reset)
        m_settings.addSeparator()
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
        t = QLabel("rPPG 控制台")
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
        self._cmb_backend.setCurrentIndex(0)
        self._cmb_backend.setToolTip(
            "自動 — 依平台優先選擇可用後端\n"
            "V4L2 — Linux 原生攝影機後端\n"
            "FFMPEG — 嘗試 FFMPEG 後再回退到平台後端\n"
            "MSMF — Windows Media Foundation，可保留原生 MJPG"
        )
        lbl_backend = QLabel("後端：")
        lbl_backend.setObjectName("hintLabel")
        row3.addWidget(lbl_backend)
        row3.addWidget(self._cmb_backend)
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
        self._chk_lock = QCheckBox("Overlay 鎖定（穿透點擊）")
        self._chk_lock.setChecked(True)
        row_b.addWidget(self._chk_behavior)
        row_b.addWidget(self._chk_stress)
        row_b.addWidget(self._chk_lock)
        row_b.addStretch(1)
        ctl.addLayout(row_b)

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

        body_layout.addWidget(gb_ctl)

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

        self._append_log("歡迎使用 rPPG V2 控制台（介面示範）。變更選項僅寫入此視窗日誌。")
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

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = int(self.winId())

        for hotkey_id, act in self._global_hotkey_id_map.items():
            seq = act.shortcut().toString()
            parsed = self._parse_hotkey(seq)
            if parsed is None:
                continue
            mod_flags, vk = parsed
            if not user32.RegisterHotKey(hwnd, hotkey_id, mod_flags, vk):
                err = ctypes.get_last_error()
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
        user32 = ctypes.WinDLL("user32", use_last_error=True)
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

            if isinstance(resolution, str):
                self._cmb_resolution.setCurrentText(resolution)
            if isinstance(fps, str):
                self._cmb_fps.setCurrentText(fps)
            if isinstance(backend, str):
                if not self._select_combo_by_data(self._cmb_backend, backend):
                    self._cmb_backend.setCurrentIndex(0)
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
            },
            "toggles": {
                "all": self._chk_all.isChecked(),
                "preview": self._chk_preview.isChecked(),
                "metrics": self._chk_metrics.isChecked(),
                "lock": self._chk_lock.isChecked(),
                "behavior": self._chk_behavior.isChecked(),
                "stress": self._chk_stress.isChecked(),
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
            self._append_log("未取得攝影機清單。")

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

    def _start_web_server(self) -> None:
        if self._web_server is not None:
            return
        try:
            playback_manager = PlaybackManager(self._recordings_dir())
            self._web_server = WebServerThread(
                self._web_metrics_buffer,
                playback_manager,
                host="127.0.0.1",
                port=5000,
            )
            self._web_server.start()
            self._append_log("🌐 Web 儀表板啟動：http://127.0.0.1:5000")
        except Exception as exc:
            self._append_log(f"⚠ Web 儀表板啟動失敗：{exc}")
            self._web_server = None

    def _stop_web_server(self) -> None:
        if self._web_server is None:
            return
        self._web_server.stop()
        self._web_server = None

    def _build_web_metrics(self) -> dict:
        r = self._latest_rppg_metrics
        f = self._latest_fatigue_metrics
        z = self._latest_fused_score

        face_r = bool(getattr(r, "face_detected", False)) if r else False
        face_f = bool(getattr(f, "face_detected", False)) if f else False
        calib_progress = float(getattr(f, "calib_progress", 0.0) or 0.0) if f else 0.0
        calib_target = 100
        calib_samples = int(round(calib_progress * calib_target)) if f else 0
        warmup_progress = float(getattr(r, "warmup_progress", 0.0) or 0.0) if r else 0.0
        perclos_pct = float(getattr(f, "perclos", 0.0) or 0.0) * 100.0 if f else 0.0

        return {
            "timestamp": time.time(),
            "fps": float(self._last_fps or 0.0),
            "face_detected": face_r or face_f,
            "calibrated": bool(getattr(f, "calibrated", False)) if f else False,
            "calib_samples": calib_samples,
            "calib_target": calib_target if f else 0,
            "ear": float(getattr(f, "ear", 0.0) or 0.0),
            "perclos": perclos_pct,
            "blink_count": int(getattr(f, "blink_count", 0) or 0),
            "status": str(getattr(f, "status", "NO_FACE") or "NO_FACE"),
            "stress_bpm": float(getattr(r, "bpm", 0.0) or 0.0),
            "stress_rmssd": float(getattr(r, "rmssd", 0.0) or 0.0),
            "stress_sdnn": float(getattr(r, "sdnn", 0.0) or 0.0),
            "stress_lf_hf": float(getattr(r, "lf_hf", 0.0) or 0.0),
            "stress_sqi": float(getattr(r, "sqi", 0.0) or 0.0),
            "stress_quality_score": float(getattr(r, "quality_score", 0.0) or 0.0),
            "stress_peak_freq": float(getattr(r, "peak_freq_hz", 0.0) or 0.0),
            "stress_hrv_confidence": str(getattr(r, "hrv_confidence", "") or ""),
            "stress_ibi_artifact_ratio": float(getattr(r, "ibi_artifact_ratio", 0.0) or 0.0),
            "stress_prob": float(getattr(r, "stress_prob", 0.0) or 0.0),
            "stress_waveform": list(getattr(r, "waveform", []) or []),
            "stress_psd_freqs": list(getattr(r, "psd_freqs", []) or []),
            "stress_psd_values": list(getattr(r, "psd_vals", []) or []),
            "stress_enabled": self._chk_stress.isChecked(),
            "stress_has_face": face_r,
            "stress_warmup_progress": warmup_progress,
            "stress_warmup_done": warmup_progress >= 0.99,
            "fusion_state_zh": str(getattr(z, "level", "") or ""),
            "fusion_confidence": float(getattr(z, "score", 0.0) or 0.0),
            "head_pitch": float(getattr(f, "head_pitch", 0.0) or 0.0),
            "head_yaw": float(getattr(f, "head_yaw", 0.0) or 0.0),
            "head_roll": float(getattr(f, "head_roll", 0.0) or 0.0),
            "fatigue_quality_score": float(getattr(f, "quality_score", 0.0) or 0.0),
            "fatigue_blend_calib_progress": float(getattr(f, "blend_calib_progress", 0.0) or 0.0),
            "early_warning": bool(getattr(f, "early_warning", False)) if f else False,
            "blink_rate_pm": float(getattr(f, "blink_rate_pm", 0.0) or 0.0),
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

    def _emit_web_metrics(self) -> None:
        if self._web_server is None:
            return
        now = time.perf_counter()
        if now - self._web_last_emit < self._web_emit_interval:
            return
        metrics = self._build_web_metrics()
        self._web_metrics_buffer.append(metrics)
        self._web_server.broadcast_metrics(metrics)
        self._web_last_emit = now

    def _encode_frame_jpeg(self, image: QImage, *, max_width: int = 640, quality: int = 70) -> str | None:
        if image is None:
            return None
        if image.width() > max_width:
            image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        if image.format() != QImage.Format.Format_RGB888:
            image = image.convertToFormat(QImage.Format.Format_RGB888)
        buffer = QByteArray()
        qbuffer = QBuffer(buffer)
        qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = image.save(qbuffer, b"JPEG", quality)
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
        b64 = self._encode_frame_jpeg(image)
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

        thread = QThread(self)
        worker = CameraStreamWorker(cam_idx, width=w, height=h,
                                    target_fps=target_fps, backend=backend)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.camera_info.connect(self._on_camera_info)
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
            f"▶ 相機 [{cam_idx}] 開啟（{backend_label}  {w}×{h} @ {target_fps} fps）"
        )

    def _stop_camera_worker(self) -> None:
        self._stop_analysis_workers()   # stop all analysis before camera
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
        if source == "combined" and self._combined_worker is not None:
            self._combined_worker.frame_annotated.disconnect(handler)
        elif source == "rppg" and self._rppg_worker is not None:
            self._rppg_worker.frame_annotated.disconnect(handler)
        elif source == "fatigue" and self._fatigue_worker is not None:
            self._fatigue_worker.frame_annotated.disconnect(handler)
        elif source == "camera" and self._cam_worker is not None:
            self._cam_worker.frame_ready.disconnect(handler)

    # ── Analysis workers (rPPG / fatigue / combined) ──────────────────────────

    def _analysis_needed(self) -> tuple[bool, bool]:
        """Return (want_rppg, want_fatigue) from checkbox state."""
        return self._chk_stress.isChecked(), self._chk_behavior.isChecked()

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
        want_rppg, want_fatigue = self._analysis_needed()
        if want_rppg and want_fatigue:
            self._start_combined_worker()
        elif want_rppg:
            self._start_rppg_worker()
        elif want_fatigue:
            self._start_fatigue_worker()
        else:
            self._update_frame_routing()   # restore raw camera feed

    # ── Combined worker ───────────────────────────────────────────────────────

    def _start_combined_worker(self) -> None:
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
            enable_rppg=True, enable_fatigue=True,
            target_fps=30.0, buffer_sec=12.0,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.rppg_metrics_ready.connect(self._on_rppg_metrics)
        worker.fatigue_metrics_ready.connect(self._on_fatigue_metrics)
        worker.fused_score_ready.connect(self._on_fused_score)
        worker.face_detected.connect(self._on_face_detected)
        worker.status_changed.connect(self._on_combined_status)
        worker.failed.connect(self._on_combined_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._combined_thread = thread
        self._combined_worker = worker
        thread.start()

        self._update_frame_routing()
        self._preview_overlay.show_rppg_panel(True)
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
        worker = RppgWorker(self._bgr_queue, target_fps=30.0, buffer_sec=12.0)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.metrics_ready.connect(self._on_rppg_metrics)
        worker.face_detected.connect(self._on_face_detected)
        worker.status_changed.connect(self._on_rppg_status)
        worker.failed.connect(self._on_rppg_failed)
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

    def _on_rppg_metrics(self, metrics: object) -> None:
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
        worker = FatigueWorker(self._fatigue_queue, target_fps=30.0)
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
        self._record_metrics()
        self._emit_web_metrics()

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

    def _on_camera_failed(self, msg: str) -> None:
        self._append_log(f"✗ 相機錯誤：{msg}")
        self._pipeline_running = False
        self._btn_start.setText("開始")
        self._lbl_pipeline.setText("管線：停止")
        self._lbl_fps.setText("FPS：—")
        self._sync_overlay_visibility()
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
            self._btn_start.setText("停止")
            self._lbl_pipeline.setText("管線：運作中")
            self._lbl_fps.setText("FPS：—")
            self._lbl_face.setText("臉部：—")
            self._start_camera_worker()
            # Start the appropriate analysis worker(s) based on checkbox state
            want_rppg, want_fatigue = self._analysis_needed()
            if want_rppg and want_fatigue:
                self._start_combined_worker()
            elif want_rppg:
                self._start_rppg_worker()
            elif want_fatigue:
                self._start_fatigue_worker()
            self._sync_overlay_visibility()
            if self._chk_auto_record.isChecked() and not self._recording:
                self._toggle_recording()
        else:
            self._btn_start.setText("開始")
            self._lbl_pipeline.setText("管線：停止")
            self._lbl_fps.setText("FPS：—")
            self._lbl_codec.setText("編碼：—")
            self._stop_camera_worker()
            self._sync_overlay_visibility()
            self._append_log("■ 管線停止。")
            if self._recording:
                self._recording = False
                self._btn_record.setText("開始記錄")
                self._lbl_record.setText("記錄狀態：未啟動")
                self._stop_recording()
                self._append_log("○ 管線停止，已一併結束記錄。")
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
        else:
            self._btn_record.setText("開始記錄")
            self._lbl_record.setText("記錄狀態：未啟動")
            self._stop_recording()
            self._append_log("○ 記錄停止。")

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
            self._append_log("🔄 已重置為示範預設值。")

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
        url = QUrl("http://127.0.0.1:5000")
        QDesktopServices.openUrl(url)
        QMessageBox.information(
            self,
            "Web 儀表板",
            "已開啟 Web 儀表板：\nhttp://127.0.0.1:5000\n"
            "若瀏覽器無法連線，請確認防火牆或埠 5000 未被佔用。",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._unregister_global_hotkeys()
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
