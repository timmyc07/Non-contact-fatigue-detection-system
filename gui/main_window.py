from __future__ import annotations

import html
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Callable, cast

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPoint, QRect, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QImageWriter,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.alarm_config import (
    ALARM_SCENARIO_KEYS,
    AlarmConfig,
)
from gui.alarm_player import FatigueAlarmController
from gui.belt_runtime import BeltRuntime
from gui.camera_stream_worker import CameraStreamWorker
from gui.capture_preferences_state import CapturePreferencesState
from gui.combined_worker import CombinedWorker
from gui.dialogs import HotkeyConfig, UserProfile
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
    CAMERA_BACKENDS,
    CAMERA_FPS_OPTIONS,
    CAMERA_RESOLUTIONS,
    CameraDevice,
    EngineController,
)
from gui.fatigue_scorer import FuserConfig
from gui.fatigue_worker import FatigueWorker
from gui.metrics_recorder import MetricsRecorder
from gui.overlay_runtime_state import OverlayRuntimeState
from gui.personal_profile import (
    PersonalBaselineCollector,
    PersonalProfileStore,
    resolve_active_baseline,
)
from gui.replay_runtime_state import ReplayRuntimeState
from gui.runtime_paths import data_path
from gui.preview_overlay_window import PreviewOverlayWindow
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


class _WebRestartBridge(QObject):
    stopped = Signal(bool, bool)


@dataclass(frozen=True, slots=True)
class _GlobalHotkeyBinding:
    field: str
    sequence: str
    callback: Callable[[], None]


# ── 視覺主題 token（僅影響 QSS 外觀，絕不影響任何 signal/slot 或數值行為） ──
# 轉譯自 claude.ai/design 設計稿（Industry design system）：深色為預設，另備淺色。
# 語意色（ok/warn/bad、綜合疲勞等級動態色）由資料驅動，不放進 palette。
FONT_HEADING = '"Barlow Condensed", "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif'
FONT_BODY = '"Barlow", "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif'
FONT_MONO = '"JetBrains Mono", "Consolas", "Cascadia Mono", monospace'

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "DESK": "#0b0d0f",       # 視窗最外層底
        "BG": "#0d1113",         # 內容底
        "SIDEBAR": "#101719",    # 側邊導航底
        "CARD": "#172023",       # 卡片 / GroupBox
        "INPUT": "#202c2f",      # 輸入元件底
        "VIDEO": "#0a0e10",      # 影片 / Log 深底
        "TEXT": "#e5eeed",
        "TEXT_MUTED": "rgba(229,238,237,0.64)",
        "TEXT_FAINT": "rgba(229,238,237,0.44)",
        # VIDEO 深底始終為深色（兩主題皆然），其上文字固定用淺色，不隨主題翻轉。
        "TEXT_ON_VIDEO": "rgba(255,255,255,0.82)",
        "TEXT_ON_VIDEO_MUTED": "rgba(255,255,255,0.5)",
        "ACCENT": "#7ce2cf",
        "ACCENT_HOVER": "#9aefdf",
        "ACCENT_PRESSED": "#55b9a8",
        "ON_ACCENT": "#062c27",  # accent 填色上的文字
        "DIVIDER": "rgba(229,238,237,0.16)",
        "DIVIDER_STRONG": "rgba(229,238,237,0.28)",
        "HOVER": "rgba(229,238,237,0.07)",
        "PRESSED": "rgba(229,238,237,0.14)",
        "NAV_HOVER": "rgba(124,226,207,0.12)",
        "BAD": "#ff9f93",
        "BAD_TEXT": "#ff9f93",
        "BAD_BG": "rgba(255,159,147,0.14)",
        "MENUBAR_BG": "#131f21",
        # 綜合疲勞大卡（hero）：accent 10% 疊在 BG 上的近似值 + accent 邊框。
        "HERO_BG": "#132a27",
        # 預覽面板 blueprint 網格線（深底上的淺色細線）。
        "GRID_LINE": "rgba(255,255,255,0.06)",
        # DEVICE STATUS / 預覽 tag 的狀態圓點語意色（非疲勞等級語意）。
        "STATUS_OK": "#7ce2cf",
        "STATUS_WARN": "#edc46e",
        "STATUS_OFF": "rgba(229,238,237,0.30)",
    },
    "light": {
        "DESK": "#d4d4d7",
        "BG": "#f2f2f3",
        "SIDEBAR": "#ececed",
        "CARD": "#e9e9ea",
        "INPUT": "#f7f7f8",
        "VIDEO": "#20262c",      # 設計稿淺色主題仍保留深色影片 / Log 面板
        "TEXT": "#1d1f20",
        "TEXT_MUTED": "rgba(29,31,32,0.62)",
        "TEXT_FAINT": "rgba(29,31,32,0.45)",
        # VIDEO 深底始終為深色（兩主題皆然），其上文字固定用淺色，不隨主題翻轉。
        "TEXT_ON_VIDEO": "rgba(255,255,255,0.82)",
        "TEXT_ON_VIDEO_MUTED": "rgba(255,255,255,0.5)",
        "ACCENT": "#5980a6",
        "ACCENT_HOVER": "#597ea3",
        "ACCENT_PRESSED": "#416180",
        "ON_ACCENT": "#f2f2f3",
        "DIVIDER": "rgba(29,31,32,0.16)",
        "DIVIDER_STRONG": "rgba(29,31,32,0.30)",
        "HOVER": "rgba(29,31,32,0.06)",
        "PRESSED": "rgba(29,31,32,0.12)",
        "NAV_HOVER": "rgba(89,128,166,0.10)",
        "BAD": "#a8503c",
        "BAD_TEXT": "#a8503c",
        "BAD_BG": "rgba(168,80,60,0.12)",
        "MENUBAR_BG": "#e6e7e9",
        # 綜合疲勞大卡（hero）：accent 10% 疊在 BG 上的近似值 + accent 邊框。
        "HERO_BG": "#e6ecf2",
        # 預覽面板始終為深底（VIDEO），網格線用白色細線兩主題共用。
        "GRID_LINE": "rgba(255,255,255,0.06)",
        # DEVICE STATUS / 預覽 tag 的狀態圓點語意色（非疲勞等級語意）。
        "STATUS_OK": "#4a7f5f",
        "STATUS_WARN": "#a8833c",
        "STATUS_OFF": "rgba(29,31,32,0.30)",
    },
}

_QSS_TEMPLATE = Template(
    """
    QWidget {
        background-color: $BG;
        color: $TEXT;
        font-size: 13px;
        font-family: """
    + FONT_BODY
    + """;
    }
    QLabel, QCheckBox, QRadioButton { background: transparent; }
    QMainWindow, QDialog { background-color: $DESK; }
    QWidget#sidebar {
        background-color: $SIDEBAR;
        border-right: 1px solid $DIVIDER;
    }
    QGroupBox {
        font-family: """
    + FONT_HEADING
    + """;
        font-weight: 600;
        font-size: 15px;
        border: 1px solid $DIVIDER;
        border-radius: 8px;
        margin-top: 14px;
        padding: 18px 16px 16px 16px;
        background-color: $CARD;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 6px;
        color: $TEXT_MUTED;
    }
    QLabel#titleLabel {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 25px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#brandSub {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_FAINT;
        letter-spacing: 2px;
    }
    QLabel#pageKicker {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        font-weight: 600;
        color: $ACCENT;
        letter-spacing: 2px;
    }
    QLabel#subtitleLabel {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 26px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#hintLabel {
        color: $TEXT_MUTED;
        font-size: 12px;
    }
    QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: $INPUT;
        border: 1px solid $DIVIDER;
        border-radius: 7px;
        padding: 6px 10px;
        min-height: 22px;
        font-size: 13px;
        color: $TEXT;
    }
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: $ACCENT;
    }
    QComboBox::drop-down { border: none; width: 24px; }
    QComboBox QAbstractItemView {
        background-color: $CARD;
        color: $TEXT;
        border: 1px solid $DIVIDER;
        selection-background-color: $ACCENT;
        selection-color: $ON_ACCENT;
    }
    QPushButton {
        background-color: transparent;
        border: 1px solid $DIVIDER;
        border-radius: 7px;
        padding: 8px 16px;
        min-height: 20px;
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 14px;
        font-weight: 600;
        color: $TEXT;
    }
    QPushButton:hover { background-color: $HOVER; border-color: $DIVIDER_STRONG; }
    QPushButton:pressed { background-color: $PRESSED; }
    QPushButton#primaryButton {
        background-color: $ACCENT;
        border: 1px solid $ACCENT;
        color: $ON_ACCENT;
        padding: 10px 22px;
    }
    QPushButton#primaryButton:hover { background-color: $ACCENT_HOVER; border-color: $ACCENT_HOVER; }
    QPushButton#primaryButton:pressed { background-color: $ACCENT_PRESSED; }
    QPushButton#dangerButton {
        border-color: $BAD;
        color: $BAD_TEXT;
        background-color: $BAD_BG;
    }
    QPushButton#dangerButton:hover { background-color: $BAD_BG; border-color: $BAD; }
    QPushButton#themeToggle {
        border: 1px solid $DIVIDER;
        border-radius: 999px;
        padding: 7px 14px;
        color: $TEXT_MUTED;
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 12px;
    }
    QPushButton#themeToggle:hover { background-color: $NAV_HOVER; color: $TEXT; }
    QCheckBox { spacing: 8px; color: $TEXT; }
    QCheckBox::indicator {
        width: 17px;
        height: 17px;
        border-radius: 5px;
        border: 1px solid $DIVIDER_STRONG;
        background-color: $INPUT;
    }
    QCheckBox::indicator:checked { background-color: $ACCENT; border-color: $ACCENT; }
    QSlider::groove:horizontal { height: 4px; background: $DIVIDER; border-radius: 2px; }
    QSlider::sub-page:horizontal { background: $ACCENT; border-radius: 2px; }
    QSlider::handle:horizontal { width: 16px; margin: -7px 0; border-radius: 8px; background: $ACCENT; }
    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
    QScrollBar::handle:vertical { background: $DIVIDER_STRONG; border-radius: 4px; min-height: 30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; height: 9px; margin: 0; }
    QScrollBar::handle:horizontal { background: $DIVIDER_STRONG; border-radius: 4px; min-width: 30px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
    QFrame#statusBarFrame {
        background-color: $CARD;
        border: 1px solid $DIVIDER;
        border-radius: 10px;
        padding: 8px 14px;
    }
    QLabel#statusStripLabel {
        color: $TEXT_MUTED;
        font-family: """
    + FONT_MONO
    + """;
        font-size: 12px;
    }
    QTextEdit, QPlainTextEdit {
        background-color: $VIDEO;
        border: 1px solid $DIVIDER;
        border-radius: 10px;
        padding: 8px;
        font-family: """
    + FONT_MONO
    + """;
        font-size: 12px;
        color: $TEXT_ON_VIDEO;
    }
    QMenuBar { background-color: $MENUBAR_BG; border-bottom: 1px solid $DIVIDER; padding: 2px; color: $TEXT; }
    QMenuBar::item { padding: 4px 10px; border-radius: 8px; background: transparent; }
    QMenuBar::item:selected { background-color: $HOVER; }
    QMenu { background-color: $CARD; border: 1px solid $DIVIDER; padding: 4px; color: $TEXT; }
    QMenu::item { padding: 6px 20px; border-radius: 6px; }
    QMenu::item:selected { background-color: $ACCENT; color: $ON_ACCENT; }
    QStatusBar { background-color: $DESK; border-top: 1px solid $DIVIDER; color: $TEXT_MUTED; }
    QListWidget#navList {
        background-color: transparent;
        border: none;
        outline: 0;
        padding: 8px 6px;
    }
    QLabel#cardCaption {
        color: $TEXT_MUTED;
        font-family: """
    + FONT_MONO
    + """;
        font-size: 11px;
        letter-spacing: 1px;
    }
    QLabel#cardValue {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 14px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#cardValueBig {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 40px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#cardUnit {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 12px;
        color: $TEXT_MUTED;
    }
    QLabel#levelBadge {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 15px;
        font-weight: 600;
        color: $ON_ACCENT;
        background-color: $DIVIDER_STRONG;
        border-radius: 999px;
        padding: 3px 12px;
    }
    QLabel#sectionSub {
        font-size: 13px;
        font-weight: 600;
        color: $TEXT_MUTED;
        margin-top: 6px;
    }
    QLabel#previewLabel {
        background-color: $VIDEO;
        border: 1px solid $DIVIDER;
        border-radius: 12px;
        color: $TEXT_ON_VIDEO_MUTED;
        font-size: 14px;
    }
    QFrame#replayPreviewFrame {
        background-color: $VIDEO;
        border: 1px solid $DIVIDER;
        border-radius: 12px;
    }
    QLabel#replayPreviewLabel { background: transparent; color: $TEXT_ON_VIDEO_MUTED; }
    QProgressBar {
        border: 1px solid $DIVIDER;
        border-radius: 999px;
        background-color: $INPUT;
        max-height: 10px;
        text-align: center;
        color: $TEXT_MUTED;
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
    }
    QProgressBar::chunk { background-color: $ACCENT; border-radius: 999px; }
    QToolTip { background-color: $CARD; color: $TEXT; border: 1px solid $DIVIDER; padding: 4px 8px; }
    /* ── 設計稿重建：卡片外殼與版面元件（純視覺 object name） ── */
    QFrame#panelCard {
        background-color: $CARD;
        border: 1px solid $DIVIDER;
        border-radius: 12px;
    }
    QFrame#panelHero {
        background-color: $HERO_BG;
        border: 1px solid $ACCENT;
        border-radius: 12px;
    }
    QFrame#previewPanel {
        background-color: $VIDEO;
        border: 1px solid $DIVIDER;
        border-radius: 12px;
    }
    QLabel#previewInner {
        background: transparent;
        color: $TEXT_ON_VIDEO_MUTED;
        font-size: 14px;
    }
    QLabel#cardHeading {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 16px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#monoCaption {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_FAINT;
        letter-spacing: 2px;
    }
    QLabel#groupLabel {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_FAINT;
        letter-spacing: 2px;
    }
    QLabel#heroScore {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 46px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#heroTrend {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 11px;
        color: $TEXT_MUTED;
    }
    QLabel#contribName { font-size: 12px; color: $TEXT_MUTED; }
    QLabel#contribValue {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 12px;
        color: $TEXT;
    }
    QLabel#scaleMark {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 9px;
        color: $TEXT_FAINT;
    }
    QLabel#bpmDelta {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_MUTED;
    }
    QLabel#hrvLabel {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 9px;
        color: $TEXT_FAINT;
        letter-spacing: 1px;
    }
    QLabel#hrvValue {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 20px;
        font-weight: 600;
        color: $TEXT;
    }
    QFrame#hrvCell {
        border: none;
        border-left: 2px solid $ACCENT;
        border-radius: 2px;
        background: transparent;
    }
    QFrame#hrvCellMuted {
        border: none;
        border-left: 2px solid $DIVIDER_STRONG;
        border-radius: 2px;
        background: transparent;
    }
    QLabel#telemetry {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_ON_VIDEO;
        background: transparent;
    }
    QLabel#brandMono {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 9px;
        color: $TEXT_FAINT;
        letter-spacing: 3px;
    }
    QLabel#deviceStatusTitle {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 9px;
        color: $TEXT_FAINT;
        letter-spacing: 3px;
    }
    QLabel#deviceStatusName { font-size: 11px; color: $TEXT_MUTED; }
    QLabel#deviceStatusValue { font-size: 11px; color: $TEXT; }
    QLabel#recPill {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 11px;
        color: $BAD_TEXT;
        border: 1px solid $BAD;
        border-radius: 999px;
        padding: 4px 12px;
        background-color: $BAD_BG;
    }
    QFrame#segGroup {
        border: 1px solid $DIVIDER;
        border-radius: 14px;
        background: transparent;
    }
    QPushButton#segButton {
        border: none;
        border-radius: 12px;
        padding: 5px 13px;
        margin: 0;
        min-height: 0;
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 12px;
        font-weight: 600;
        color: $TEXT_MUTED;
        background: transparent;
    }
    QPushButton#segButton:hover { color: $TEXT; }
    QPushButton#segButton[selected="true"] {
        background-color: $ACCENT;
        color: $ON_ACCENT;
    }
    QLabel#sessionLabel {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        color: $TEXT_FAINT;
        letter-spacing: 2px;
    }
    /* ── 設計稿重建（2/3/4 頁）：key-value 列、橫幅、佇列表格、摘要 ── */
    QFrame#kvRow {
        border: none;
        border-bottom: 1px solid $DIVIDER;
        background: transparent;
    }
    QLabel#kvKey { color: $TEXT_MUTED; font-size: 13px; }
    QLabel#kvVal {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 12px;
        color: $TEXT;
    }
    QLabel#bannerDevice {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 22px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#bannerBig {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 44px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#bannerConn { font-size: 12px; color: $TEXT_MUTED; }
    QLabel#sumBig {
        font-family: """
    + FONT_HEADING
    + """;
        font-size: 24px;
        font-weight: 600;
        color: $TEXT;
    }
    QLabel#calibResid {
        font-family: """
    + FONT_MONO
    + """;
        font-size: 11px;
        color: $TEXT;
    }
    QTableWidget#queueTable {
        background: transparent;
        border: none;
        gridline-color: transparent;
        outline: 0;
    }
    QTableWidget#queueTable::item {
        padding: 4px 6px;
        border: none;
        border-bottom: 1px solid $DIVIDER;
        color: $TEXT;
    }
    QTableWidget#queueTable::item:selected {
        background-color: $NAV_HOVER;
        color: $TEXT;
    }
    QHeaderView#queueHeader::section {
        background: transparent;
        color: $TEXT_FAINT;
        border: none;
        border-bottom: 1px solid $DIVIDER_STRONG;
        padding: 4px 6px;
        font-family: """
    + FONT_MONO
    + """;
        font-size: 10px;
        letter-spacing: 1px;
    }
    """
)


def application_stylesheet(theme: str = "dark") -> str:
    """依主題（dark 預設 / light）產生全域 QSS。

    僅視覺 token 替換，不含任何 signal/slot 或數值邏輯；深淺主題共用同一份模板，
    差異全在 `_PALETTES`。未知主題名一律回退 dark。
    """
    palette = _PALETTES.get(theme, _PALETTES["dark"])
    return _QSS_TEMPLATE.substitute(palette)


# QFont 只吃單一 family 名稱（不解析 CSS fallback 串），故另存首選 family 供 delegate 用。
FONT_HEADING_FAMILY = "Barlow Condensed"
FONT_MONO_FAMILY = "JetBrains Mono"


class _NavItemDelegate(QStyledItemDelegate):
    """側邊導航的編號雙語繪製（純視覺 delegate，不改任何選取 / 訊號行為）。

    每列畫出：選中態的 accent 指示條 + 背景、mono 編號、Barlow Condensed 中文主行、
    mono 英文輔助行。編號與英文存在 item 的 UserRole，DisplayRole 仍是中文，確保
    任何 fallback 與既有 `currentRowChanged` 行為完全不受影響。
    """

    NO_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    EN_ROLE = int(Qt.ItemDataRole.UserRole) + 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_colors(_PALETTES["dark"]["ACCENT"], _PALETTES["dark"]["TEXT"])

    def set_colors(self, accent_hex: str, text_hex: str) -> None:
        self._accent = QColor(accent_hex)
        self._text = QColor(text_hex)
        self._muted = QColor(text_hex)
        self._muted.setAlpha(150)
        self._sel_bg = QColor(accent_hex)
        self._sel_bg.setAlpha(46)
        self._hover_bg = QColor(accent_hex)
        self._hover_bg.setAlpha(28)

    def sizeHint(self, option, index):  # type: ignore[override]
        return QSize(option.rect.width(), 52)

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._sel_bg)
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 10, 10)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(QRect(rect.left() + 4, rect.top() + 12, 3, rect.height() - 24), 1, 1)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._hover_bg)
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 10, 10)

        no = str(index.data(self.NO_ROLE) or "")
        zh = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        en = str(index.data(self.EN_ROLE) or "")

        num_font = QFont(FONT_MONO_FAMILY)
        num_font.setPointSize(8)
        painter.setFont(num_font)
        painter.setPen(self._accent if selected else self._muted)
        painter.drawText(
            QRect(rect.left() + 16, rect.top(), 26, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            no,
        )

        zh_font = QFont(FONT_HEADING_FAMILY)
        zh_font.setPointSize(12)
        zh_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(zh_font)
        painter.setPen(self._text if (selected or hovered) else self._muted)
        painter.drawText(
            QRect(rect.left() + 46, rect.top() + 8, rect.width() - 52, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            zh,
        )

        en_font = QFont(FONT_MONO_FAMILY)
        en_font.setPointSize(7)
        painter.setFont(en_font)
        painter.setPen(self._muted)
        painter.drawText(
            QRect(rect.left() + 46, rect.top() + 28, rect.width() - 52, 15),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            en,
        )
        painter.restore()


class _MiniBar(QWidget):
    """指標貢獻列的迷你橫條（純顯示層正規化，不宣稱任何語意權重）。

    `set_fraction(f)` 的 f 已由呼叫端 clamp 至 0–1；None 代表無資料（畫空槽）。
    顏色由 `set_color` 依主題設定。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fraction: float | None = None
        self._fill = QColor("#7ea6cd")
        self._track = QColor(255, 255, 255, 26)

    def set_colors(self, fill_hex: str, track: QColor) -> None:
        self._fill = QColor(fill_hex)
        self._track = track
        self.update()

    def set_fraction(self, f: float | None) -> None:
        self._fraction = None if f is None else max(0.0, min(1.0, float(f)))
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(0, 0, w, h, r, r)
        if self._fraction:
            fw = int(w * self._fraction)
            if fw > 0:
                p.setBrush(self._fill)
                p.drawRoundedRect(0, 0, max(fw, int(h)), h, r, r)
        p.end()


class _SparklineWidget(QWidget):
    """rPPG 脈搏波形迷你圖（主題感知輕量版；復用資料來自 RppgMetrics.waveform）。

    等價於 gui/preview_overlay_window._WaveformWidget，但背景透明、顏色隨主題，
    以嵌入淺/深主題卡片內。無資料時畫提示文字。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._data: list[float] = []
        self._color = QColor("#7ea6cd")
        self._muted = QColor(150, 150, 150)

    def set_colors(self, line_hex: str, muted: QColor) -> None:
        self._color = QColor(line_hex)
        self._muted = muted
        self.update()

    def set_data(self, data: list[float]) -> None:
        self._data = list(data or [])
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if len(self._data) < 2:
            p.setPen(self._muted)
            p.drawText(QRect(0, 0, w, h), int(Qt.AlignmentFlag.AlignCenter), "等待脈搏信號…")
            p.end()
            return
        data = self._data
        mn, mx = min(data), max(data)
        span = mx - mn
        if span < 1e-9:
            p.end()
            return
        n = len(data)
        pen = QPen(self._color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        prev = None
        for i, v in enumerate(data):
            x = int(i / (n - 1) * (w - 1))
            y = int((1.0 - (v - mn) / span) * (h - 6) + 3)
            pt = QPoint(x, y)
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt
        p.end()


class _PreviewPanel(QFrame):
    """即時預覽面板：深底 + blueprint 網格質感（paintEvent 疊在 QSS 底色上）。

    子控件（相機畫面 label、telemetry 文字、MESH/rPPG tag）以 QGridLayout 疊在
    同一格，網格線畫在最底層。純視覺，不影響任何資料流。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QColor(255, 255, 255, 16)

    def set_grid_color(self, c: QColor) -> None:
        self._grid = c
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(self._grid, 1))
        step = 44
        w, h = self.width(), self.height()
        x = step
        while x < w:
            p.drawLine(x, 0, x, h)
            x += step
        y = step
        while y < h:
            p.drawLine(0, y, w, y)
            y += step
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, *, engine_mode: bool = False) -> None:
        super().__init__()
        self._engine_mode = bool(engine_mode)
        self._engine_controller = EngineController(belt_runtime=BeltRuntime())
        if not self._engine_mode:
            self.setWindowTitle("NCFD System — 非接觸式疲勞監測系統 V2")
            self.resize(1420, 900)
            self.setMinimumSize(1080, 620)

        # 本次啟動的 session 識別（真實識別碼，非設計稿假資料）：以啟動日期+時分生成一次。
        self._session_id = "S-" + time.strftime("%m%d")

        # 視覺主題（僅影響 QSS 外觀）：預設深色，偏好僅 in-session（不落設定檔）。
        self._theme = "dark"
        self._pipeline_running = False
        self._recording = False
        self._hotkeys = HotkeyConfig()
        self._user = UserProfile()
        self._overlay_state = OverlayRuntimeState()
        self._capture_preferences = CapturePreferencesState()
        self._web_preferences = WebPreferencesState()

        self._preview_overlay = None if self._engine_mode else PreviewOverlayWindow()
        if not self._engine_mode:
            assert self._preview_overlay is not None
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
        self._global_hotkey_bindings: dict[int, _GlobalHotkeyBinding] = {}
        self._hotkey_failed_once: set[str] = set()
        self._hotkey_registration_failures: list[dict[str, Any]] = []
        self._settings_dirty = False
        self._desktop_notice_seq = 0
        self._desktop_notice: dict[str, Any] | None = None
        self._web_metrics_buffer = MetricsBuffer(maxsize=300)
        self._web_server: WebServerThread | None = None
        self._web_restart_scheduled = False
        self._web_restart_in_progress = False
        self._web_restart_shutdown = False
        self._web_restart_stopping_server: WebServerThread | None = None
        self._web_restart_bridge = _WebRestartBridge(self)
        self._web_restart_bridge.stopped.connect(
            self._on_web_restart_stopped,
            Qt.ConnectionType.QueuedConnection,
        )
        self._desktop_control_broker = DesktopCommandBroker(timeout_seconds=10.0)
        self._web_emit_interval = 0.25
        self._web_frame_interval = 1.0 / WEB_PREVIEW_TARGET_FPS
        self._web_last_emit = 0.0
        self._web_last_frame_emit = 0.0
        self._replay_thread: QThread | None = None
        self._replay_worker: VideoReplayWorker | None = None
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
        self._belt_ui_timer = QTimer(self)
        self._belt_ui_timer.setInterval(1000)
        self._belt_ui_timer.timeout.connect(self._tick_belt_calibration)
        # 純 legacy UI 顯示用：REC pill 的 elapsed 計時；engine mode 不建立。
        self._rec_ui_timer: QTimer | None = None
        if not self._engine_mode:
            self._rec_ui_timer = QTimer(self)
            self._rec_ui_timer.setInterval(1000)
            self._rec_ui_timer.timeout.connect(self._update_rec_pill)
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
        self._monitor_focus = False
        self._monitor_rail = None
        self._monitor_controls_panel = None
        self._preview_panel = None
        self._replay_queue_table = None

        if self._engine_mode:
            self._start_camera_scan()
        else:
            self._build_menu()
            self._build_central()

        self._desktop_control_timer = QTimer(self)
        self._desktop_control_timer.setInterval(20)
        self._desktop_control_timer.timeout.connect(self._drain_desktop_commands)
        self._desktop_control_timer.start()

        self._load_settings()
        self._alarm_controller = FatigueAlarmController(self._alarm_config, self)
        self._apply_hotkey_shortcuts()
        if not self._engine_mode:
            self._apply_overlay_state()
        self._start_web_server()

        if not self._engine_mode:
            self.statusBar().showMessage("就緒 — 選擇攝影機後按「開始」可預覽（無 MediaPipe）")
        if not self._engine_mode:
            self._apply_native_titlebar_theme()

    def _set_legacy_text(self, name: str, text: object) -> None:
        """Update a real Qt label/button without creating an engine-mode mirror."""
        if not self._engine_mode:
            getattr(self, name).setText(str(text))

    def _set_legacy_enabled(self, name: str, enabled: bool) -> None:
        """Update a real Qt control without creating an engine-mode mirror."""
        if not self._engine_mode:
            getattr(self, name).setEnabled(enabled)

    def _toggle_overlay_preference(self, field: str) -> None:
        state = self._overlay_state.snapshot()
        current = getattr(state, field)
        self._configure_overlay(**{field: not current})

    def _sync_analysis_controls(self) -> None:
        if self._engine_mode:
            return
        plan = self._engine_controller.analysis_snapshot()
        for control, checked in (
            (self._chk_behavior, plan.fatigue_enabled),
            (self._chk_stress, plan.rppg_enabled),
        ):
            control.blockSignals(True)
            try:
                control.setChecked(checked)
            finally:
                control.blockSignals(False)
        self._refresh_preview_tags()

    def _sync_overlay_controls(self) -> None:
        if self._engine_mode:
            return
        state = self._overlay_state.snapshot()
        for control, value in (
            (self._chk_all, state.all_enabled),
            (self._chk_preview, state.preview),
            (self._chk_metrics, state.metrics),
            (self._chk_lock, state.locked),
        ):
            control.blockSignals(True)
            try:
                control.setChecked(value)
            finally:
                control.blockSignals(False)
        self._sld_opacity.blockSignals(True)
        try:
            self._sld_opacity.setValue(state.opacity)
        finally:
            self._sld_opacity.blockSignals(False)
        self._lbl_opacity.setText(f"{state.opacity}%")

    def _configure_overlay(self, **changes: object) -> None:
        previous = self._overlay_state.snapshot()
        current = self._overlay_state.configure(**changes)
        if current == previous:
            return
        self._sync_overlay_controls()
        self._apply_overlay_state()
        self._settings_dirty = True

    def _sync_replay_controls(self) -> None:
        if self._engine_mode:
            return
        state = self._replay_state.snapshot()
        self._spn_replay_jobs.blockSignals(True)
        self._chk_replay_annotated.blockSignals(True)
        try:
            self._spn_replay_jobs.setValue(state.jobs)
            self._chk_replay_annotated.setChecked(state.annotated)
        finally:
            self._spn_replay_jobs.blockSignals(False)
            self._chk_replay_annotated.blockSignals(False)
        self._lbl_replay_dir.setText(
            str(state.dataset_dir) if state.dataset_dir is not None else "尚未選擇資料夾"
        )
        self._lbl_replay_current.setText(state.current_text)
        self._lbl_replay_result.setText(state.result_text)
        self._lbl_replay_parallel_status.setText(state.parallel_status_text)

    def _configure_replay(self, **changes: object) -> None:
        self._replay_state.configure(**changes)
        self._sync_replay_controls()

    def _update_replay_presentation(self, **changes: object) -> None:
        self._replay_state.update_presentation(**changes)
        self._sync_replay_controls()

    def _sync_capture_preference_controls(self) -> None:
        if self._engine_mode:
            return
        state = self._capture_preferences.snapshot()
        for control, value in (
            (self._chk_auto_record, state.auto_record),
            (self._chk_belt_calib, state.belt_calibration),
            (self._chk_auto_capture_belt, state.auto_capture_include_belt),
        ):
            control.blockSignals(True)
            try:
                control.setChecked(value)
            finally:
                control.blockSignals(False)
        self._spn_auto_capture_seconds.blockSignals(True)
        try:
            self._spn_auto_capture_seconds.setValue(state.auto_capture_seconds)
        finally:
            self._spn_auto_capture_seconds.blockSignals(False)

    def _sync_web_preference_control(self) -> None:
        if self._engine_mode:
            return
        self._act_web_allow_lan.blockSignals(True)
        try:
            self._act_web_allow_lan.setChecked(
                self._web_preferences.snapshot().allow_lan
            )
        finally:
            self._act_web_allow_lan.blockSignals(False)

    def _configure_web_preferences(
        self,
        *,
        allow_lan: bool,
        mark_dirty: bool = True,
        restart_server: bool = True,
    ) -> None:
        self._web_preferences.configure(allow_lan=allow_lan)
        self._sync_web_preference_control()
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
        self._sync_capture_preference_controls()
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
                self._sync_capture_preference_controls()
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
            self._sync_analysis_controls()
            if not self._engine_controller.pipeline_snapshot().running:
                self._fail_closed_pipeline_adapters()
            raise
        self._sync_analysis_controls()
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

    def _apply_native_titlebar_theme(self) -> None:
        """Windows：讓原生標題列跟隨深/淺主題（DWM immersive dark mode）。

        非 Windows 或任何 ctypes/DWM 呼叫失敗一律靜默略過（try/except 包好），
        不做 frameless、不影響任何非視覺行為。
        """
        if not sys.platform.startswith("win"):
            return
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1 if self._theme == "dark" else 0)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            dwmapi = cast(Any, ctypes).windll.dwmapi
            res = dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_int(DWMWA_USE_IMMERSIVE_DARK_MODE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if res != 0:
                # 舊版 Windows 10 用屬性索引 19。
                dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    ctypes.c_int(19),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
        except Exception:
            pass

    def _build_menu(self) -> None:
        act_refresh = QAction("刷新攝影機列表", self)
        act_refresh.triggered.connect(self._start_camera_scan)

        act_recordings = QAction("開啟記錄檔目錄", self)
        act_recordings.triggered.connect(self._open_recordings_dir)

        act_save = QAction("保存配置與布局", self)
        act_save.triggered.connect(self._on_save_layout)

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
        m_settings.addAction(act_refresh)
        m_settings.addAction(act_recordings)
        m_settings.addSeparator()
        m_settings.addAction(act_save)
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

        # 選單列右側 corner widget：SESSION 識別 + LIGHT/DARK 兩段式主題切換。
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(10)
        self._lbl_session = QLabel(f"SESSION {self._session_id}")
        self._lbl_session.setObjectName("sessionLabel")
        cl.addWidget(self._lbl_session)
        self._theme_seg, self._theme_seg_buttons = self._make_segmented(
            [("light", "LIGHT"), ("dark", "DARK")],
            lambda key: (self._toggle_theme() if key != self._theme else None),
        )
        cl.addWidget(self._theme_seg)
        # 保留 Python 參照，避免 corner widget 被 GC（offscreen 下 menubar 可能不接管所有權）。
        self._menu_corner = corner
        self.menuBar().setCornerWidget(corner, Qt.Corner.TopRightCorner)

    def _build_central(self) -> None:
        """左側邊導航 + 右側 QStackedWidget 四頁 dashboard 架構。

        僅為版面重組：所有既有 self._xxx widget 與 signal/slot 接線一律保留（維持
        原名），只是分散到「即時監測／心跳帶／影片回測／設定」四個分頁；未觸碰任何
        數值路徑、worker 或 overlay 視窗邏輯。
        """
        wrap = QWidget()
        self.setCentralWidget(wrap)
        root = QHBoxLayout(wrap)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左側邊導航 ──
        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(196)
        side.setMaximumWidth(230)
        side.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(0, 18, 0, 0)
        side_l.setSpacing(0)

        # 品牌區：圓形圖示 + NCFD System + mono 副標 + 中文副標
        brand_wrap = QWidget()
        brand_l = QVBoxLayout(brand_wrap)
        brand_l.setContentsMargins(18, 0, 14, 16)
        brand_l.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self._brand_dot = QLabel("●")
        self._brand_dot.setObjectName("brandDot")
        self._brand_dot.setFixedSize(30, 30)
        self._brand_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_row.addWidget(self._brand_dot)
        brand = QLabel("NCFD System")
        brand.setObjectName("titleLabel")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        brand_l.addLayout(brand_row)
        brand_mono = QLabel("NON-CONTACT FATIGUE\nDETECTION SYSTEM")
        brand_mono.setObjectName("brandMono")
        brand_l.addWidget(brand_mono)
        brand_sub = QLabel("非接觸式疲勞監測系統")
        brand_sub.setObjectName("brandSub")
        brand_sub.setWordWrap(True)
        brand_l.addWidget(brand_sub)
        side_l.addWidget(brand_wrap)

        self._nav = QListWidget()
        self._nav.setObjectName("navList")
        self._nav.setSpacing(2)
        self._nav_delegate = _NavItemDelegate(self._nav)
        self._nav.setItemDelegate(self._nav_delegate)
        # DisplayRole 維持中文（fallback 與既有行為不變），編號 / 英文存 UserRole 供 delegate 繪製。
        for no, zh, en in (
            ("01", "即時監測", "LIVE MONITOR"),
            ("02", "心跳帶", "CHEST BELT"),
            ("03", "影片回測", "BATCH REPLAY"),
            ("04", "設定", "SETTINGS"),
        ):
            item = QListWidgetItem(zh)
            item.setData(_NavItemDelegate.NO_ROLE, no)
            item.setData(_NavItemDelegate.EN_ROLE, en)
            self._nav.addItem(item)
        side_l.addWidget(self._nav, 1)

        # ── DEVICE STATUS 區（側邊欄底部）──
        dev_wrap = QWidget()
        dev_l = QVBoxLayout(dev_wrap)
        dev_l.setContentsMargins(18, 14, 18, 16)
        dev_l.setSpacing(10)
        dev_title = QLabel("DEVICE STATUS")
        dev_title.setObjectName("deviceStatusTitle")
        dev_l.addWidget(dev_title)
        self._dot_cam = QLabel()
        self._lbl_dev_cam = QLabel("OFF")
        dev_l.addLayout(self._device_status_row("攝影機", self._dot_cam, self._lbl_dev_cam))
        self._dot_belt = QLabel()
        self._lbl_dev_belt = QLabel("OFF")
        dev_l.addLayout(self._device_status_row("心跳帶", self._dot_belt, self._lbl_dev_belt))
        self._dot_mp = QLabel()
        self._lbl_dev_mp = QLabel("CPU")
        dev_l.addLayout(self._device_status_row("MediaPipe", self._dot_mp, self._lbl_dev_mp))
        side_l.addWidget(dev_wrap)
        root.addWidget(side)

        # ── 右側分頁堆疊 ──
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_monitor_page())
        self._stack.addWidget(self._build_belt_page())
        self._stack.addWidget(self._build_replay_page())
        self._stack.addWidget(self._build_settings_page())
        root.addWidget(self._stack, 1)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        # 勾選框功能接線（元件已於各分頁建立，於此統一連線，維持原行為與順序）
        self._chk_all.toggled.connect(self._on_toggle_all)
        self._chk_preview.toggled.connect(self._on_preview_toggled)
        self._chk_metrics.toggled.connect(self._on_metrics_toggled)
        self._chk_lock.toggled.connect(self._on_lock_toggled)
        # Behaviour alertness toggle — functional
        self._chk_behavior.toggled.connect(self._on_behavior_toggled)
        self._chk_auto_record.toggled.connect(
            lambda checked: self._configure_capture_preferences(auto_record=checked)
        )
        # rPPG stress/HRV toggle — functional
        self._chk_stress.toggled.connect(self._on_stress_toggled)
        self._chk_belt_calib.toggled.connect(
            lambda checked: self._configure_capture_preferences(
                belt_calibration=checked
            )
        )

        self._append_log("歡迎使用 NCFD System。變更選項僅寫入此視窗日誌。")
        self._start_camera_scan()

        # 依當前主題同步 delegate 顏色與主題按鈕文字（app 級 QSS 由 main.py 套用）。
        self._sync_theme_widgets()

    # ── 主題切換 ──────────────────────────────────────────────────────────────
    def _toggle_theme(self) -> None:
        """深 / 淺主題切換：翻轉 self._theme，對 QApplication 重套 QSS 並同步動態上色處。"""
        self._theme = "light" if self._theme == "dark" else "dark"
        app = QApplication.instance()
        if app is not None:
            cast(Any, app).setStyleSheet(application_stylesheet(self._theme))
        self._sync_theme_widgets()
        self._apply_native_titlebar_theme()
        # 綜合疲勞等級徽章：無資料時回到 QSS 中性樣式，有資料時維持資料驅動語意色。
        if hasattr(self, "_mon_fused_level"):
            self._refresh_monitor_metrics()

    def _sync_theme_widgets(self) -> None:
        """把非 QSS 能觸及的動態元件（手動上色處）對齊當前主題。

        涵蓋：nav delegate、LIGHT/DARK segmented 高亮、品牌圓點、sparkline 線色、
        指標貢獻迷你條、預覽網格線、預覽 MESH/rPPG tag、DEVICE STATUS 圓點。
        """
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        if hasattr(self, "_nav_delegate"):
            self._nav_delegate.set_colors(pal["ACCENT"], pal["TEXT"])
            self._nav.viewport().update()
        if hasattr(self, "_theme_seg_buttons"):
            self._set_segmented_selection(self._theme_seg_buttons, self._theme)
        if hasattr(self, "_brand_dot"):
            self._brand_dot.setStyleSheet(
                f"color: {pal['ACCENT']}; border: 1px solid {pal['ACCENT']};"
                " border-radius: 10px; font-size: 12px;"
            )
        if hasattr(self, "_mon_wave"):
            muted = QColor(pal["TEXT"])
            muted.setAlpha(110)
            self._mon_wave.set_colors(pal["ACCENT"], muted)
        if hasattr(self, "_mon_contrib_bars"):
            track = QColor(pal["TEXT"])
            track.setAlpha(26)
            for bar in self._mon_contrib_bars.values():
                bar.set_colors(pal["ACCENT"], track)
        if hasattr(self, "_belt_bpm_spark"):
            muted = QColor(pal["TEXT"])
            muted.setAlpha(110)
            self._belt_bpm_spark.set_colors(pal["ACCENT"], muted)
        if hasattr(self, "_belt_calib_bar"):
            track = QColor(pal["TEXT"])
            track.setAlpha(26)
            self._belt_calib_bar.set_colors(pal["STATUS_OK"], track)
        if self._replay_queue_table is not None:
            self._restyle_replay_queue_rows()
        if self._preview_panel is not None:
            self._preview_panel.set_grid_color(QColor(255, 255, 255, 16))
        self._refresh_preview_tags()
        self._update_device_status()

    # ── DEVICE STATUS（側邊欄） ───────────────────────────────────────────────
    def _device_status_row(self, name: str, dot: QLabel, value: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        nm = QLabel(name)
        nm.setObjectName("deviceStatusName")
        dot.setFixedSize(7, 7)
        value.setObjectName("deviceStatusValue")
        row.addWidget(nm)
        row.addStretch(1)
        row.addWidget(dot)
        row.addWidget(value)
        return row

    def _set_status_dot(self, dot: QLabel, color: str) -> None:
        dot.setStyleSheet(f"background-color: {color}; border-radius: 3px;")

    def _update_device_status(self) -> None:
        """更新側邊欄 DEVICE STATUS 三列（攝影機 / 心跳帶 / MediaPipe）。

        只讀既有旗標與 belt_status()，由管線啟停點與 belt 1s timer 觸發，不新增輪詢。
        """
        if not hasattr(self, "_dot_cam"):
            return
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        cam_on = self._pipeline_running or self._cam_worker is not None
        self._set_status_dot(self._dot_cam, pal["STATUS_OK"] if cam_on else pal["STATUS_OFF"])
        self._lbl_dev_cam.setText("ON" if cam_on else "OFF")

        belt_on = False
        belt_name = "OFF"
        try:
            if self._engine_controller.belt_running:
                st = self._engine_controller.belt_status()
                if st is not None and st.state == "connected":
                    belt_on = True
                    belt_name = (st.device_name or "ON")[:12]
                else:
                    belt_name = "連線中"
        except Exception:
            belt_on = False
        self._set_status_dot(self._dot_belt, pal["STATUS_OK"] if belt_on else pal["STATUS_OFF"])
        self._lbl_dev_belt.setText(belt_name)

        # MediaPipe 恆以 CPU 執行（BaseOptions 未指定 delegate，屬事實靜態顯示）。
        self._set_status_dot(self._dot_mp, pal["STATUS_WARN"])
        self._lbl_dev_mp.setText("CPU")

    # ── 兩段式 segmented 切換（LIGHT/DARK、分割/專注共用視覺語彙） ────────────
    def _make_segmented(self, items: list[tuple[str, str]], on_select) -> tuple[QFrame, dict[str, QPushButton]]:
        frame = QFrame()
        frame.setObjectName("segGroup")
        l = QHBoxLayout(frame)
        l.setContentsMargins(2, 2, 2, 2)
        l.setSpacing(2)
        buttons: dict[str, QPushButton] = {}
        for key, label in items:
            b = QPushButton(label)
            b.setObjectName("segButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("selected", "false")
            b.clicked.connect(lambda _=False, k=key: on_select(k))
            l.addWidget(b)
            buttons[key] = b
        return frame, buttons

    @staticmethod
    def _set_segmented_selection(buttons: dict[str, QPushButton], selected_key: str) -> None:
        for key, b in buttons.items():
            b.setProperty("selected", "true" if key == selected_key else "false")
            style = b.style()
            style.unpolish(b)
            style.polish(b)

    # ── 分頁共用小工具 ────────────────────────────────────────────────────────
    def _page_header(self, kicker: str, title: str) -> QWidget:
        """頁首區塊：mono 編號 kicker（如「01 / LIVE MONITOR」）+ 大標題（純視覺）。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        k = QLabel(kicker)
        k.setObjectName("pageKicker")
        t = QLabel(title)
        t.setObjectName("subtitleLabel")
        v.addWidget(k)
        v.addWidget(t)
        return w

    def _page_scroll(self, content: QWidget) -> QScrollArea:
        """把分頁內容包進垂直捲動區，維持小視窗下的 responsive 行為。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _stat_row(self, target_layout: QVBoxLayout, caption: str, *, min_caption: int = 96) -> QLabel:
        """在 target_layout 追加一列「說明 — 數值」列，回傳右側數值 QLabel。"""
        row = QHBoxLayout()
        cap = QLabel(caption)
        cap.setObjectName("cardCaption")
        cap.setMinimumWidth(min_caption)
        val = QLabel("—")
        val.setObjectName("cardValue")
        val.setWordWrap(True)
        row.addWidget(cap)
        row.addWidget(val, 1, Qt.AlignmentFlag.AlignRight)
        target_layout.addLayout(row)
        return val

    def _kv_row(self, target_layout: QVBoxLayout, caption: str) -> QLabel:
        """設計稿 key-value 列：底部細分隔線、左側說明（muted）、右側 mono 數值，回傳數值 QLabel。"""
        frame = QFrame()
        frame.setObjectName("kvRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(8)
        cap = QLabel(caption)
        cap.setObjectName("kvKey")
        val = QLabel("—")
        val.setObjectName("kvVal")
        val.setWordWrap(True)
        row.addWidget(cap)
        row.addWidget(val, 1, Qt.AlignmentFlag.AlignRight)
        target_layout.addWidget(frame)
        return val

    # ── 監測頁 ────────────────────────────────────────────────────────────────
    def _card(self, heading: str, caption: str, *, hero: bool = False) -> tuple[QFrame, QVBoxLayout]:
        """設計稿卡片外殼：卡內頂部（中文 heading + mono caption），回傳容器與內容 layout。"""
        frame = QFrame()
        frame.setObjectName("panelHero" if hero else "panelCard")
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 9, 14, 10)
        v.setSpacing(7)
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        h = QLabel(heading)
        h.setObjectName("cardHeading")
        c = QLabel(caption)
        c.setObjectName("monoCaption")
        hdr.addWidget(h, 0, Qt.AlignmentFlag.AlignBottom)
        hdr.addWidget(c, 0, Qt.AlignmentFlag.AlignBottom)
        hdr.addStretch(1)
        v.addLayout(hdr)
        return frame, v

    def _group_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("groupLabel")
        return lbl

    def _build_monitor_page(self) -> QWidget:
        page = QWidget()
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(18, 14, 18, 12)
        page_l.setSpacing(12)

        # 頁首列：kicker+大標｜ REC pill ｜ 分割/專注切換
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(self._page_header("01 / LIVE MONITOR", "即時監測"))
        header.addStretch(1)
        self._mon_rec_pill = QLabel("● REC 00:00")
        self._mon_rec_pill.setObjectName("recPill")
        self._mon_rec_pill.setVisible(False)
        header.addWidget(self._mon_rec_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self._layout_seg, self._layout_seg_buttons = self._make_segmented(
            [("split", "分割 Split"), ("focus", "專注 Focus")],
            lambda key: self._set_monitor_layout(key == "focus"),
        )
        header.addWidget(self._layout_seg, 0, Qt.AlignmentFlag.AlignVCenter)
        page_l.addLayout(header)

        # 主體：左欄（預覽 + 控制卡）｜右欄 rail（疲勞 hero + rPPG + HRV）
        body = QHBoxLayout()
        body.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        # 預覽為彈性件：空間不足時先由它縮（下限 260），確保卡片與狀態列不被裁切。
        left_col.addWidget(self._build_preview_panel(), 1)
        self._monitor_controls_panel = self._build_monitor_controls()
        left_col.addWidget(self._monitor_controls_panel)
        left_wrap = QWidget()
        left_wrap.setLayout(left_col)
        self._monitor_left_wrap = left_wrap

        rail = QVBoxLayout()
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(12)
        rail.addWidget(self._build_fatigue_card())
        rail.addWidget(self._build_rppg_card())
        rail.addWidget(self._build_hrv_card())
        rail.addStretch(1)
        rail_inner = QWidget()
        rail_inner.setLayout(rail)
        # fallback：視窗縮到很小時右欄可垂直捲動（無框、細滾條、透明底），寧可捲動不裁切。
        rail_scroll = QScrollArea()
        rail_scroll.setObjectName("railScroll")
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail_scroll.setWidget(rail_inner)
        rail_scroll.setMinimumWidth(324)
        rail_scroll.setMaximumWidth(440)
        rail_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._monitor_rail = rail_scroll

        body.addWidget(left_wrap, 3)
        body.addWidget(rail_scroll, 2)
        page_l.addLayout(body, 1)

        # 狀態列釘底：內容區 stretch=1，狀態列固定，任何視窗高度都不被擠出。
        page_l.addWidget(self._build_status_strip(), 0)

        self._set_monitor_layout(False)
        return page

    def _build_preview_panel(self) -> QWidget:
        """深底 blueprint 網格預覽面板：相機畫面填滿，左上 telemetry、右下 MESH/rPPG tag。"""
        panel = _PreviewPanel()
        panel.setObjectName("previewPanel")
        panel.setMinimumSize(320, 260)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_panel = panel
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)

        # 相機畫面 label（底層，透明底讓網格質感透出；運行時 _update_monitor_preview 貼 pixmap）
        self._lbl_monitor_preview = QLabel("鏡頭預覽（按「開始」啟動）")
        self._lbl_monitor_preview.setObjectName("previewInner")
        self._lbl_monitor_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_monitor_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        grid.addWidget(self._lbl_monitor_preview, 0, 0)

        # overlay 容器（透明、穿透點擊），內含 telemetry（上）與 tag 列（下）
        overlay = QWidget()
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: transparent;")
        ov = QVBoxLayout(overlay)
        ov.setContentsMargins(14, 14, 14, 14)
        ov.setSpacing(0)
        self._lbl_preview_telemetry = QLabel("PIPE · STOPPED")
        self._lbl_preview_telemetry.setObjectName("telemetry")
        ov.addWidget(self._lbl_preview_telemetry, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        ov.addStretch(1)
        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        tag_row.addStretch(1)
        self._tag_mesh = QLabel("MESH")
        self._tag_rppg = QLabel("rPPG")
        tag_row.addWidget(self._tag_mesh)
        tag_row.addWidget(self._tag_rppg)
        ov.addLayout(tag_row)
        grid.addWidget(overlay, 0, 0)

        self._update_preview_telemetry()
        self._refresh_preview_tags()
        return panel

    def _refresh_preview_tags(self) -> None:
        """MESH / rPPG tag 亮暗綁行為警覺 / 壓力 HRV checkbox 實際啟用狀態（非裝飾）。"""
        if not hasattr(self, "_tag_mesh"):
            return
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        analysis = self._engine_controller.analysis_snapshot()
        mesh_on = analysis.fatigue_enabled
        rppg_on = analysis.rppg_enabled

        def _tag_style(on: bool) -> str:
            col = pal["ACCENT"] if on else pal["TEXT_ON_VIDEO_MUTED"]
            return (
                f"font-family: {FONT_MONO}; font-size: 10px; letter-spacing: 1px;"
                f" padding: 3px 10px; border-radius: 999px; border: 1px solid {col};"
                f" color: {col}; background: transparent;"
            )

        self._tag_mesh.setStyleSheet(_tag_style(mesh_on))
        self._tag_rppg.setStyleSheet(_tag_style(rppg_on))

    def _update_preview_telemetry(self) -> None:
        """左上 mono telemetry：解析度·FPS + PIPE 狀態（無 LAT，無資料來源）。"""
        if not hasattr(self, "_lbl_preview_telemetry"):
            return
        info = self._last_camera_info
        w = int(info.get("width", 0) or 0)
        h = int(info.get("height", 0) or 0)
        running = self._pipeline_running
        lines: list[str] = []
        if running and w > 0 and h > 0:
            fps_str = f"{self._last_fps:.0f}" if self._last_fps > 0 else "—"
            lines.append(f"{w}×{h} · {fps_str} FPS")
        lines.append("PIPE · RUNNING" if running else "PIPE · STOPPED")
        self._lbl_preview_telemetry.setText("\n".join(lines))

    def _set_monitor_layout(self, focus: bool) -> None:
        """分割 Split（雙欄）／專注 Focus（隱藏右欄與控制卡、預覽放大）純視覺切換。"""
        self._monitor_focus = focus
        if self._monitor_rail is not None:
            self._monitor_rail.setVisible(not focus)
        if self._monitor_controls_panel is not None:
            self._monitor_controls_panel.setVisible(not focus)
        if hasattr(self, "_layout_seg_buttons"):
            self._set_segmented_selection(self._layout_seg_buttons, "focus" if focus else "split")

    def _build_fatigue_card(self) -> QWidget:
        frame, v = self._card("綜合疲勞", "FATIGUE INDEX", hero=True)

        score_row = QHBoxLayout()
        score_row.setSpacing(12)
        self._mon_score_big = QLabel("—")
        self._mon_score_big.setObjectName("heroScore")
        score_row.addWidget(self._mon_score_big, 0, Qt.AlignmentFlag.AlignBottom)
        badge_col = QVBoxLayout()
        badge_col.setSpacing(4)
        self._mon_fused_level = QLabel("—")
        self._mon_fused_level.setObjectName("levelBadge")
        self._mon_fused_level.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mon_trend = QLabel("—")
        self._mon_trend.setObjectName("heroTrend")
        badge_col.addWidget(self._mon_fused_level)
        badge_col.addWidget(self._mon_trend)
        score_row.addLayout(badge_col)
        score_row.addStretch(1)
        v.addLayout(score_row)

        self._mon_score_bar = QProgressBar()
        self._mon_score_bar.setRange(0, 100)
        self._mon_score_bar.setValue(0)
        self._mon_score_bar.setTextVisible(False)
        v.addWidget(self._mon_score_bar)
        scale = QHBoxLayout()
        m0 = QLabel("0 清醒")
        m0.setObjectName("scaleMark")
        m50 = QLabel("50")
        m50.setObjectName("scaleMark")
        m100 = QLabel("100 高風險")
        m100.setObjectName("scaleMark")
        scale.addWidget(m0)
        scale.addStretch(1)
        scale.addWidget(m50)
        scale.addStretch(1)
        scale.addWidget(m100)
        v.addLayout(scale)

        v.addWidget(self._group_label("指標貢獻 CONTRIBUTION"))
        self._mon_contrib_bars = {}
        # 貢獻列放進緊湊容器（行距 3），壓低整卡高度；value label 沿用既有 _mon_* 屬性名。
        contrib = QVBoxLayout()
        contrib.setContentsMargins(0, 0, 0, 0)
        contrib.setSpacing(3)
        self._mon_fused_score = self._contrib_row(contrib, "疲勞分數", "score")
        self._mon_ear = self._contrib_row(contrib, "EAR", "ear")
        self._mon_perclos = self._contrib_row(contrib, "PERCLOS", "perclos")
        self._mon_blink = self._contrib_row(contrib, "眨眼次數", "blink")
        self._mon_expr = self._contrib_row(contrib, "微表情", "expr")
        self._mon_gaze = self._contrib_row(contrib, "注視", "gaze")
        self._mon_head = self._contrib_row(contrib, "頭部姿態", "head")
        v.addLayout(contrib)
        return frame

    def _contrib_row(self, layout: QVBoxLayout, name: str, key: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)
        nm = QLabel(name)
        nm.setObjectName("contribName")
        nm.setFixedWidth(72)
        bar = _MiniBar()
        val = QLabel("—")
        val.setObjectName("contribValue")
        val.setMinimumWidth(58)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(nm)
        row.addWidget(bar, 1)
        row.addWidget(val)
        layout.addLayout(row)
        self._mon_contrib_bars[key] = bar
        return val

    def _build_rppg_card(self) -> QWidget:
        frame, v = self._card("rPPG 生理", "PHYSIOLOGY")
        bpm_row = QHBoxLayout()
        bpm_row.setSpacing(8)
        self._mon_bpm = QLabel("—")
        self._mon_bpm.setObjectName("cardValueBig")
        unit = QLabel("BPM")
        unit.setObjectName("cardUnit")
        bpm_row.addWidget(self._mon_bpm, 0, Qt.AlignmentFlag.AlignBottom)
        bpm_row.addWidget(unit, 0, Qt.AlignmentFlag.AlignBottom)
        bpm_row.addStretch(1)
        self._mon_bpm_delta = QLabel("")
        self._mon_bpm_delta.setObjectName("bpmDelta")
        self._mon_bpm_delta.setVisible(False)
        bpm_row.addWidget(self._mon_bpm_delta, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(bpm_row)

        self._mon_wave = _SparklineWidget()
        self._mon_wave.setFixedHeight(40)
        v.addWidget(self._mon_wave)

        self._mon_warmup = self._stat_row(v, "暖機進度")
        self._mon_sqi = self._stat_row(v, "訊號品質")
        return frame

    def _build_hrv_card(self) -> QWidget:
        frame, v = self._card("HRV", "rPPG ESTIMATE")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._mon_rmssd = self._hrv_cell(grid, 0, 0, "RMSSD", accent=True)
        self._mon_sdnn = self._hrv_cell(grid, 0, 1, "SDNN", accent=True)
        self._mon_lfhf = self._hrv_cell(grid, 1, 0, "LF/HF", accent=False)
        self._mon_hrv_conf = self._hrv_cell(grid, 1, 1, "HRV 信心", accent=False)
        v.addLayout(grid)
        return frame

    def _hrv_cell(self, grid: QGridLayout, r: int, c: int, label: str, *, accent: bool) -> QLabel:
        cell = QFrame()
        cell.setObjectName("hrvCell" if accent else "hrvCellMuted")
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(10, 2, 4, 2)
        cl.setSpacing(1)
        lab = QLabel(label)
        lab.setObjectName("hrvLabel")
        val = QLabel("—")
        val.setObjectName("hrvValue")
        cl.addWidget(lab)
        cl.addWidget(val)
        grid.addWidget(cell, r, c)
        return val

    def _build_monitor_controls(self) -> QWidget:
        frame, v = self._card("控制", "CONTROL")
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)

        # 主控 MAIN
        main_col = QVBoxLayout()
        main_col.setSpacing(7)
        main_col.addWidget(self._group_label("主控 MAIN"))
        main_row = QHBoxLayout()
        main_row.setSpacing(9)
        self._btn_start = QPushButton("開始")
        self._btn_start.setObjectName("primaryButton")
        self._btn_start.clicked.connect(self._toggle_pipeline)
        main_row.addWidget(self._btn_start)
        main_row.addStretch(1)
        main_col.addLayout(main_row)
        main_col.addStretch(1)
        grid.addLayout(main_col, 0, 0)

        # 偵測模組 MODULES
        mod_col = QVBoxLayout()
        mod_col.setSpacing(7)
        mod_col.addWidget(self._group_label("偵測模組 MODULES"))
        self._chk_behavior = QCheckBox("行為警覺（頭部／哈欠／注視）")
        self._chk_behavior.setChecked(True)
        self._chk_stress = QCheckBox("壓力／HRV（心率估測）")
        self._chk_behavior.toggled.connect(self._refresh_preview_tags)
        self._chk_stress.toggled.connect(self._refresh_preview_tags)
        mod_col.addWidget(self._chk_behavior)
        mod_col.addWidget(self._chk_stress)
        mod_col.addStretch(1)
        grid.addLayout(mod_col, 0, 1)

        # 記錄 RECORDING
        rec_col = QVBoxLayout()
        rec_col.setSpacing(7)
        rec_col.addWidget(self._group_label("記錄 RECORDING"))
        rec_row = QHBoxLayout()
        rec_row.setSpacing(10)
        self._btn_record = QPushButton("開始記錄")
        self._btn_record.clicked.connect(self._toggle_recording)
        self._lbl_record = QLabel("記錄狀態：未啟動")
        self._lbl_record.setObjectName("hintLabel")
        rec_row.addWidget(self._btn_record)
        rec_row.addWidget(self._lbl_record, 1)
        rec_col.addLayout(rec_row)
        self._chk_auto_record = QCheckBox("按下開始時自動記錄")
        rec_col.addWidget(self._chk_auto_record)
        rec_col.addStretch(1)
        grid.addLayout(rec_col, 1, 0)

        # 自動採集 AUTO CAPTURE
        auto_col = QVBoxLayout()
        auto_col.setSpacing(7)
        auto_col.addWidget(self._group_label("自動採集 AUTO CAPTURE"))
        auto_row = QHBoxLayout()
        auto_row.setSpacing(9)
        auto_row.addWidget(QLabel("時長（秒）"))
        self._spn_auto_capture_seconds = QSpinBox()
        self._spn_auto_capture_seconds.setRange(10, 600)
        self._spn_auto_capture_seconds.setValue(60)
        self._spn_auto_capture_seconds.valueChanged.connect(
            lambda value: self._configure_capture_preferences(
                auto_capture_seconds=value
            )
        )
        auto_row.addWidget(self._spn_auto_capture_seconds)
        self._btn_auto_capture = QPushButton("自動採集")
        self._btn_auto_capture.setToolTip(
            "一鍵串接既有流程：啟動管線（若未啟動）→ 開始記錄（採集 A）→\n"
            "勾選「自動採集含心跳帶」時，同步勾選「壓力／HRV」與「心跳帶真值校準」（採集 B，"
            "是否實際落檔仍依現有設定與硬體狀態決定）→\n"
            "倒數結束（或再按一次提前停止）時自動停止記錄，並回報 .db／.jsonl 路徑。"
        )
        self._btn_auto_capture.clicked.connect(self._on_auto_capture_clicked)
        auto_row.addWidget(self._btn_auto_capture)
        auto_row.addStretch(1)
        auto_col.addLayout(auto_row)
        self._chk_auto_capture_belt = QCheckBox("自動採集含心跳帶")
        self._chk_auto_capture_belt.toggled.connect(
            lambda checked: self._configure_capture_preferences(
                auto_capture_include_belt=checked
            )
        )
        auto_col.addWidget(self._chk_auto_capture_belt)
        auto_col.addStretch(1)
        grid.addLayout(auto_col, 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        return frame

    def _build_status_strip(self) -> QFrame:
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
            lb.setObjectName("statusStripLabel")
            sl.addWidget(lb)
            sl.addSpacing(20)
        sl.addStretch(1)
        self._lbl_status_ready = QLabel("就緒 · READY · NO ERRORS")
        self._lbl_status_ready.setObjectName("statusStripLabel")
        sl.addWidget(self._lbl_status_ready)
        return stat

    # ── 心跳帶頁 ──────────────────────────────────────────────────────────────
    def _belt_banner_metric(self, caption: str) -> tuple[QVBoxLayout, QLabel]:
        """橫幅卡右側電量／RSSI 小型指標欄（mono caption + heading 值），回傳 layout 與值 label。"""
        col = QVBoxLayout()
        col.setSpacing(1)
        cap = QLabel(caption)
        cap.setObjectName("monoCaption")
        val = QLabel("—")
        val.setObjectName("hrvValue")
        col.addWidget(cap)
        col.addWidget(val)
        return col, val

    def _belt_banner_divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("bannerDivider")
        line.setFixedWidth(1)
        line.setStyleSheet("background: transparent;")
        line.setFrameShape(QFrame.Shape.VLine)
        return line

    def _build_belt_page(self) -> QWidget:
        page = QWidget()
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(20, 16, 20, 16)
        page_l.setSpacing(14)

        page_l.addWidget(self._page_header("02 / CHEST BELT", "心跳帶設備"))

        # 校準開關（既有控件，移入橫幅前先建立）
        self._chk_belt_calib = QCheckBox("心跳帶真值校準（背景）")
        self._chk_belt_calib.setToolTip(
            "以 BLE 心跳帶（Scosche Rhythm+ 2.0 等標準 Heart Rate Service 裝置）的實測心率為"
            "「真值參考」，在背景持續比對 rPPG 偵測到的心率，並以低增益慢速微調 rPPG 的 BPM"
            "校正量，讓 rPPG 逐漸趨近真值。\n"
            "心跳帶數值只用於校準與可信度判斷，絕不直接進入疲勞判斷。"
            "需勾選「壓力／HRV（心率估測）」啟用 rPPG 才會開始比對。"
        )
        self._lbl_belt_status = QLabel("心跳帶校準：未啟用")
        self._lbl_belt_status.setObjectName("bannerConn")
        self._lbl_belt_status.setWordWrap(True)

        # 裝置橫幅卡（hero，橫向排列；不套 _card 卡頭，直接用 panelHero 外殼）
        banner = QFrame()
        banner.setObjectName("panelHero")
        brow = QHBoxLayout(banner)
        brow.setContentsMargins(16, 12, 18, 14)
        brow.setSpacing(18)
        # 裝置名 + 連線狀態
        dev_col = QVBoxLayout()
        dev_col.setSpacing(2)
        dev_cap = QLabel("DEVICE")
        dev_cap.setObjectName("monoCaption")
        self._lbl_belt_banner_device = QLabel("—")
        self._lbl_belt_banner_device.setObjectName("bannerDevice")
        conn_row = QHBoxLayout()
        conn_row.setSpacing(7)
        self._belt_banner_dot = QLabel()
        self._belt_banner_dot.setFixedSize(7, 7)
        self._set_status_dot(self._belt_banner_dot, _PALETTES[self._theme]["STATUS_OFF"])
        conn_row.addWidget(self._belt_banner_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        conn_row.addWidget(self._lbl_belt_status, 1)
        dev_col.addWidget(dev_cap)
        dev_col.addWidget(self._lbl_belt_banner_device)
        dev_col.addLayout(conn_row)
        brow.addLayout(dev_col)
        brow.addWidget(self._belt_banner_divider())
        # BPM 真值
        bpm_row = QHBoxLayout()
        bpm_row.setSpacing(7)
        self._lbl_belt_banner_bpm = QLabel("—")
        self._lbl_belt_banner_bpm.setObjectName("bannerBig")
        bpm_unit = QLabel("BPM 真值")
        bpm_unit.setObjectName("cardUnit")
        bpm_row.addWidget(self._lbl_belt_banner_bpm, 0, Qt.AlignmentFlag.AlignBottom)
        bpm_row.addWidget(bpm_unit, 0, Qt.AlignmentFlag.AlignBottom)
        brow.addLayout(bpm_row)
        brow.addWidget(self._belt_banner_divider())
        # 背景校準 checkbox
        chk_col = QVBoxLayout()
        chk_col.setSpacing(2)
        chk_col.addWidget(self._chk_belt_calib)
        brow.addLayout(chk_col)
        brow.addStretch(1)
        # 電量 / RSSI
        batt_col, self._lbl_belt_banner_battery = self._belt_banner_metric("電量")
        rssi_col, self._lbl_belt_banner_rssi = self._belt_banner_metric("RSSI")
        brow.addLayout(batt_col)
        brow.addLayout(rssi_col)
        page_l.addWidget(banner)

        # 下方雙欄
        grid = QHBoxLayout()
        grid.setSpacing(14)
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        col1.setSpacing(14)
        col2.setSpacing(14)

        # 連線 CONNECTION
        conn_card, cl = self._card("連線", "CONNECTION")
        self._lbl_belt_device = self._kv_row(cl, "裝置名稱")
        self._lbl_belt_address = self._kv_row(cl, "裝置位址")
        self._lbl_belt_location = self._kv_row(cl, "配戴位置")
        self._lbl_belt_connected_since = self._kv_row(cl, "連線時長")
        self._lbl_belt_notifications = self._kv_row(cl, "封包數")
        self._lbl_belt_last_error = self._kv_row(cl, "最後錯誤")
        col1.addWidget(conn_card)

        # 即時 LIVE（含 BPM 趨勢 sparkline）
        live_card, rl = self._card("即時", "LIVE")
        self._belt_bpm_spark = _SparklineWidget()
        self._belt_bpm_spark.setFixedHeight(46)
        rl.addWidget(self._belt_bpm_spark)
        self._lbl_belt_bpm = self._kv_row(rl, "BPM")
        self._lbl_belt_rr = self._kv_row(rl, "RR 樣本數")
        self._lbl_belt_contact = self._kv_row(rl, "感測器接觸")
        self._lbl_belt_battery = self._kv_row(rl, "電量")
        self._lbl_belt_rssi = self._kv_row(rl, "RSSI")
        self._lbl_belt_stale = self._kv_row(rl, "停滯警告")
        col1.addWidget(live_card)

        # HRV（僅供顯示）
        hrv_card, hl = self._card("HRV", "僅供顯示，不進疲勞融合")
        self._lbl_belt_hrv_rmssd = self._kv_row(hl, "RMSSD")
        self._lbl_belt_hrv_sdnn = self._kv_row(hl, "SDNN")
        self._lbl_belt_hrv_lfhf = self._kv_row(hl, "LF/HF")
        self._lbl_belt_hrv_conf = self._kv_row(hl, "HRV 信心")
        self._lbl_belt_hrv_warmup = self._kv_row(hl, "暖機進度")
        col2.addWidget(hrv_card)

        # rPPG 校準 CALIBRATION（含殘差橫條）
        cal_card, cal_l = self._card("rPPG 校準", "CALIBRATION")
        resid_row = QHBoxLayout()
        resid_row.setSpacing(10)
        resid_cap = QLabel("殘差")
        resid_cap.setObjectName("monoCaption")
        self._belt_calib_bar = _MiniBar()
        self._lbl_belt_calib_resid = QLabel("—")
        self._lbl_belt_calib_resid.setObjectName("calibResid")
        resid_row.addWidget(resid_cap)
        resid_row.addWidget(self._belt_calib_bar, 1)
        resid_row.addWidget(self._lbl_belt_calib_resid)
        cal_l.addLayout(resid_row)
        self._lbl_belt_calib_offset = self._kv_row(cal_l, "Offset")
        self._lbl_belt_calib_raw_resid = self._kv_row(cal_l, "原始殘差")
        self._lbl_belt_calib_corr_resid = self._kv_row(cal_l, "校正後殘差")
        self._lbl_belt_calib_confidence = self._kv_row(cal_l, "信心")
        self._lbl_belt_calib_status = self._kv_row(cal_l, "狀態")
        self._lbl_belt_calib_pairs = self._kv_row(cal_l, "配對數")
        col2.addWidget(cal_card)

        # 設備設定（讀 config/hr_belt.json 載入結果，唯讀顯示；設計稿為可編輯輸入，
        # 但 GUI 無對應套用 handler，故保留為唯讀資訊卡，不造假輸入控件）
        cfg_card, fl = self._card("設備設定", "PREFERENCES")
        self._lbl_belt_cfg_name_prefix = self._kv_row(fl, "名稱前綴")
        self._lbl_belt_cfg_address = self._kv_row(fl, "指定位址")
        self._lbl_belt_cfg_tuning = self._kv_row(fl, "參數自適應")
        self._lbl_belt_cfg_capture = self._kv_row(fl, "同步錄製")
        col2.addWidget(cfg_card)

        col1.addStretch(1)
        col2.addStretch(1)
        c1w = QWidget()
        c1w.setLayout(col1)
        c2w = QWidget()
        c2w.setLayout(col2)
        grid.addWidget(c1w, 1)
        grid.addWidget(c2w, 1)
        page_l.addLayout(grid, 1)

        self._refresh_belt_cfg_labels()
        return self._page_scroll(page)

    # ── 影片回測頁 ────────────────────────────────────────────────────────────
    def _build_replay_page(self) -> QWidget:
        page = QWidget()
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(20, 16, 20, 16)
        page_l.setSpacing(14)

        # 頁首：資料夾路徑由正式 Flutter/Tauri 面板設定。
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(self._page_header("03 / BATCH REPLAY", "影片回測"))
        header.addStretch(1)
        self._lbl_replay_dir = QLabel("尚未選擇資料夾")
        self._lbl_replay_dir.setObjectName("sessionLabel")
        self._lbl_replay_dir.setWordWrap(True)
        self._lbl_replay_dir.setMaximumWidth(360)
        header.addWidget(self._lbl_replay_dir, 0, Qt.AlignmentFlag.AlignVCenter)
        page_l.addLayout(header)

        # 工具列卡（hero，橫向）：主要動作 + 平行數 + 標註 chk + 右側進度區
        toolbar = QFrame()
        toolbar.setObjectName("panelHero")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 12, 18, 12)
        tb.setSpacing(12)
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
        self._spn_replay_jobs.valueChanged.connect(
            lambda value: self._configure_replay(jobs=value)
        )
        self._chk_replay_annotated = QCheckBox("輸出標註影片")
        self._chk_replay_annotated.toggled.connect(
            lambda checked: self._configure_replay(annotated=checked)
        )
        tb.addWidget(self._btn_replay_start)
        tb.addWidget(self._btn_replay_parallel)
        tb.addWidget(self._btn_replay_stop)
        tb.addWidget(self._belt_banner_divider())
        tb.addWidget(self._spn_replay_jobs)
        tb.addWidget(self._chk_replay_annotated)
        tb.addStretch(1)
        # 右側進度區
        prog_col = QVBoxLayout()
        prog_col.setSpacing(5)
        self._lbl_replay_current = QLabel("目前影片：--")
        self._lbl_replay_current.setObjectName("hintLabel")
        self._bar_replay_progress = QProgressBar()
        self._bar_replay_progress.setRange(0, 1)
        self._bar_replay_progress.setValue(0)
        self._lbl_replay_result = QLabel("摘要檔：--")
        self._lbl_replay_result.setObjectName("sessionLabel")
        self._lbl_replay_result.setWordWrap(True)
        prog_col.addWidget(self._lbl_replay_current)
        prog_col.addWidget(self._bar_replay_progress)
        prog_col.addWidget(self._lbl_replay_result)
        prog_wrap = QWidget()
        prog_wrap.setLayout(prog_col)
        prog_wrap.setMinimumWidth(300)
        tb.addWidget(prog_wrap)
        page_l.addWidget(toolbar)

        # 下方：處理清單表格（左，較寬）｜ 預覽 + 摘要（右）
        grid = QHBoxLayout()
        grid.setSpacing(14)

        # 處理清單 QUEUE
        queue_card, ql = self._card("處理清單", "QUEUE")
        table = QTableWidget(0, 5)
        table.setObjectName("queueTable")
        table.setHorizontalHeaderLabels(["#", "檔案", "時長", "疲勞", "狀態"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setShowGrid(False)
        table.setWordWrap(False)
        hh = table.horizontalHeader()
        hh.setObjectName("queueHeader")
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(4, 88)
        hh.setHighlightSections(False)
        table.setMinimumHeight(300)
        self._replay_queue_table = table
        ql.addWidget(table, 1)
        self._lbl_replay_parallel_status = QLabel("處理清單：--")
        self._lbl_replay_parallel_status.setObjectName("hintLabel")
        self._lbl_replay_parallel_status.setWordWrap(True)
        ql.addWidget(self._lbl_replay_parallel_status)
        grid.addWidget(queue_card, 3)

        # 右欄：預覽 + 摘要
        right_col = QVBoxLayout()
        right_col.setSpacing(14)
        self._frame_replay_preview = QFrame()
        self._frame_replay_preview.setObjectName("replayPreviewFrame")
        self._frame_replay_preview.setMinimumHeight(240)
        self._frame_replay_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        replay_preview_layout = QVBoxLayout(self._frame_replay_preview)
        replay_preview_layout.setContentsMargins(0, 0, 0, 0)
        replay_preview_layout.setSpacing(0)
        self._lbl_replay_preview = QLabel("影片預覽")
        self._lbl_replay_preview.setObjectName("replayPreviewLabel")
        self._lbl_replay_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_replay_preview.setScaledContents(False)
        self._lbl_replay_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        replay_preview_layout.addWidget(self._lbl_replay_preview, 1)
        right_col.addWidget(self._frame_replay_preview, 1)

        # 摘要 SUMMARY（GUI 端對已完成片聚合；MAE(BPM) 無資料來源，故不做該格）
        sum_card, sl = self._card("摘要", "SUMMARY")
        sum_grid = QHBoxLayout()
        sum_grid.setSpacing(12)
        self._lbl_replay_sum_avg = self._summary_cell(sum_grid, "平均疲勞")
        self._lbl_replay_sum_warn = self._summary_cell(sum_grid, "警戒影片")
        self._lbl_replay_sum_fail = self._summary_cell(sum_grid, "失敗數")
        sl.addLayout(sum_grid)
        right_col.addWidget(sum_card)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        grid.addWidget(right_wrap, 2)
        page_l.addLayout(grid, 1)
        return self._page_scroll(page)

    def _summary_cell(self, target: QHBoxLayout, caption: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        cap = QLabel(caption)
        cap.setObjectName("monoCaption")
        val = QLabel("—")
        val.setObjectName("sumBig")
        col.addWidget(cap)
        col.addWidget(val)
        target.addLayout(col, 1)
        return val

    def _replay_status_kind(self, summary: ReplayVideoSummary | None, *, done: bool) -> str:
        """把 summary.status 對映到佇列 pill 的語意種類（done/fail/warn/run/wait）。"""
        if not done:
            return "run"
        if summary is None:
            return "wait"
        if summary.status == "failed":
            return "fail"
        if summary.critical_frames > 0 or summary.drowsy_frames > 0:
            return "warn"
        return "done"

    def _replay_status_color_text(self, kind: str) -> tuple[str, str]:
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        return {
            "done": (pal["STATUS_OK"], "完成"),
            "fail": (pal["BAD"], "失敗"),
            "warn": (pal["STATUS_WARN"], "警戒"),
            "run": (pal["ACCENT"], "處理中"),
            "wait": (pal["TEXT_FAINT"], "等待"),
        }.get(kind, (pal["TEXT_FAINT"], "—"))

    def _make_status_pill(self, kind: str) -> QLabel:
        pill = QLabel()
        pill.setProperty("statusKind", kind)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_status_pill_style(pill, kind)
        return pill

    def _apply_status_pill_style(self, pill: QLabel, kind: str) -> None:
        color, text = self._replay_status_color_text(kind)
        pill.setText(text)
        pill.setStyleSheet(
            f"font-family: {FONT_HEADING}; font-size: 11px; font-weight: 600;"
            f" padding: 1px 10px; border-radius: 999px; border: 1px solid {color};"
            f" color: {color}; background: transparent;"
        )

    def _restyle_replay_queue_rows(self) -> None:
        """主題切換時重新著色佇列 pill（顏色含主題相依 accent）。"""
        table = getattr(self, "_replay_queue_table", None)
        if table is None:
            return
        for r in range(table.rowCount()):
            pill = table.cellWidget(r, 4)
            if pill is not None:
                self._apply_status_pill_style(pill, pill.property("statusKind") or "wait")

    def _queue_mono_item(self, text: str, *, muted: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        font = QFont()
        font.setFamilies(["JetBrains Mono", "Consolas", "Cascadia Mono", "monospace"])
        font.setPointSize(9)
        item.setFont(font)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        if muted:
            pal = _PALETTES.get(self._theme, _PALETTES["dark"])
            c = QColor(pal["TEXT"])
            c.setAlpha(140)
            item.setForeground(c)
        return item

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        s = int(round(seconds or 0.0))
        if s <= 0:
            return "—"
        return f"{s // 60:02d}:{s % 60:02d}"

    def _replay_queue_reset(self) -> None:
        """批次開始時清空處理清單表格與摘要聚合。"""
        self._replay_queue_rows = {}
        self._replay_completed_summaries = []
        if self._replay_queue_table is not None:
            self._replay_queue_table.setRowCount(0)
        self._refresh_replay_summary()

    def _replay_queue_upsert(self, summary: ReplayVideoSummary, *, done: bool) -> None:
        """依 video_start／video_done 事件在處理清單表格新增或更新一列（純顯示層）。"""
        table = self._replay_queue_table
        if table is None:
            return
        key = self._replay_video_key(summary)
        row = self._replay_queue_rows.get(key)
        if row is None:
            row = table.rowCount()
            table.insertRow(row)
            self._replay_queue_rows[key] = row
            table.setItem(row, 0, self._queue_mono_item(f"{row + 1:02d}", muted=True))
            table.setItem(row, 1, self._queue_mono_item(""))
            table.setItem(row, 2, self._queue_mono_item("—", muted=True))
            table.setItem(row, 3, self._queue_mono_item("—"))
            table.setCellWidget(row, 4, self._make_status_pill("run"))
        name = Path(summary.video_path).name or f"S{summary.subject}/L{summary.label}"
        table.item(row, 1).setText(name)
        if done:
            table.item(row, 2).setText(self._fmt_duration(summary.duration_sec))
            if summary.status == "failed":
                table.item(row, 3).setText("—")
            else:
                table.item(row, 3).setText(f"{round(summary.avg_fatigue_score * 100)}")
        kind = self._replay_status_kind(summary, done=done)
        pill = table.cellWidget(row, 4)
        if pill is not None:
            self._apply_status_pill_style(pill, kind)

    def _refresh_replay_summary(self) -> None:
        """摘要卡三格：平均疲勞 / 警戒影片數 / 失敗數（GUI 端對已完成片聚合）。"""
        if not hasattr(self, "_lbl_replay_sum_avg"):
            return
        done = self._replay_completed_summaries
        scored = [s.avg_fatigue_score for s in done if s.status != "failed"]
        warn = sum(1 for s in done if s.status != "failed" and (s.critical_frames > 0 or s.drowsy_frames > 0))
        fail = sum(1 for s in done if s.status == "failed")
        self._lbl_replay_sum_avg.setText(f"{round(sum(scored) / len(scored) * 100)}" if scored else "—")
        self._lbl_replay_sum_warn.setText(str(warn) if done else "—")
        self._lbl_replay_sum_fail.setText(str(fail) if done else "—")

    # ── 設定頁 ────────────────────────────────────────────────────────────────
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(20, 18, 20, 18)
        page_l.setSpacing(14)

        page_l.addWidget(self._page_header("04 / SETTINGS", "設定"))

        # 上半：攝影機（左）｜ Overlay + 個人清醒基線（右）
        grid = QHBoxLayout()
        grid.setSpacing(14)

        # 攝影機（RGB）
        cam_card, cam_l = self._card("攝影機（RGB）", "CAMERA")
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
        cam_l.addLayout(row1)
        cam_l.addWidget(self._lbl_cam_hint)

        row2 = QHBoxLayout()
        camera_defaults = self._engine_controller.camera_snapshot()
        self._cmb_resolution = QComboBox()
        self._cmb_resolution.addItems(CAMERA_RESOLUTIONS)
        self._cmb_resolution.setCurrentText(camera_defaults.resolution)
        self._cmb_fps = QComboBox()
        self._cmb_fps.addItems(CAMERA_FPS_OPTIONS)
        self._cmb_fps.setCurrentText(camera_defaults.fps)
        row2.addWidget(QLabel("解析度："))
        row2.addWidget(self._cmb_resolution, 1)
        row2.addSpacing(16)
        row2.addWidget(QLabel("目標 FPS："))
        row2.addWidget(self._cmb_fps)
        cam_l.addLayout(row2)

        row3 = QHBoxLayout()
        self._cmb_backend = QComboBox()
        for backend in CAMERA_BACKENDS:
            self._cmb_backend.addItem(backend.upper(), backend)
        self._select_combo_by_data(self._cmb_backend, camera_defaults.backend)
        self._cmb_backend.setToolTip(
            "FFMPEG — 嘗試 FFMPEG 後再回退到平台後端"
        )
        self._chk_horizontal_flip = QCheckBox("水平翻轉（鏡像校正）")
        self._chk_horizontal_flip.setChecked(True)
        self._chk_horizontal_flip.setToolTip("相機畫面左右相反時啟用；預覽、錄影與分析會使用同一個翻轉後畫面。")
        self._cmb_resolution.currentTextChanged.connect(
            lambda value: self._on_camera_config_changed(resolution=value)
        )
        self._cmb_fps.currentTextChanged.connect(
            lambda value: self._on_camera_config_changed(fps=value)
        )
        self._cmb_backend.currentIndexChanged.connect(
            lambda _index: self._on_camera_config_changed(
                backend=self._cmb_backend.currentData()
            )
        )
        self._chk_horizontal_flip.toggled.connect(
            lambda checked: self._on_camera_config_changed(horizontal_flip=checked)
        )
        row3.addWidget(QLabel("後端："))
        row3.addWidget(self._cmb_backend, 1)
        row3.addSpacing(16)
        row3.addWidget(self._chk_horizontal_flip)
        cam_l.addLayout(row3)
        cam_l.addStretch(1)
        grid.addWidget(cam_card, 1)

        # 右欄：Overlay 顯示 + 個人清醒基線
        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        ov_card, ov = self._card("Overlay 顯示", "OVERLAY")
        ov_grid = QGridLayout()
        ov_grid.setHorizontalSpacing(16)
        ov_grid.setVerticalSpacing(8)
        self._chk_all = QCheckBox("顯示／隱藏 全部 Overlay")
        self._chk_all.setChecked(True)
        self._chk_preview = QCheckBox("鏡頭預覽 Overlay（含 MediaPipe）")
        self._chk_metrics = QCheckBox("數值 Overlay")
        self._chk_metrics.setChecked(True)
        self._chk_lock = QCheckBox("Overlay 鎖定（穿透點擊）")
        self._chk_lock.setChecked(True)
        ov_grid.addWidget(self._chk_all, 0, 0)
        ov_grid.addWidget(self._chk_preview, 0, 1)
        ov_grid.addWidget(self._chk_metrics, 1, 0)
        ov_grid.addWidget(self._chk_lock, 1, 1)
        ov_grid.setColumnStretch(0, 1)
        ov_grid.setColumnStretch(1, 1)
        ov.addLayout(ov_grid)

        row_d = QHBoxLayout()
        lbl_op = QLabel("Overlay 透明度")
        lbl_op.setObjectName("hintLabel")
        row_d.addWidget(lbl_op)
        self._sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self._sld_opacity.setRange(0, 100)
        self._sld_opacity.setValue(55)
        self._sld_opacity.valueChanged.connect(self._on_opacity)
        self._lbl_opacity = QLabel("55%")
        self._lbl_opacity.setObjectName("cardValue")
        self._lbl_opacity.setMinimumWidth(40)
        row_d.addWidget(self._sld_opacity, 1)
        row_d.addWidget(self._lbl_opacity)
        ov.addLayout(row_d)
        right_col.addWidget(ov_card)

        prof_card, prof_l = self._card("個人清醒基線", "PERSONAL")
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
            "個人基線：已載入" if self._personal_profile is not None else "個人基線：未建立 · 建議 120 秒清醒錄製")
        self._lbl_profile_status.setObjectName("hintLabel")
        self._lbl_profile_status.setWordWrap(True)
        row_profile.addWidget(self._lbl_profile_status, 1)
        row_profile.addWidget(self._btn_record_baseline, 0, Qt.AlignmentFlag.AlignVCenter)
        prof_l.addLayout(row_profile)
        right_col.addWidget(prof_card)
        right_col.addStretch(1)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        grid.addWidget(right_wrap, 1)
        page_l.addLayout(grid)

        # Log CONSOLE（全寬，深底 console 風格）
        log_card, log_l = self._card("Log", "CONSOLE")
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(150)
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_l.addWidget(self._log)
        page_l.addWidget(log_card, 1)

        return self._page_scroll(page)

    # ── 監測頁即時顯示（唯讀，僅讀 self._latest_* 快照） ──────────────────────
    def _update_monitor_preview(self, image) -> None:
        lbl = getattr(self, "_lbl_monitor_preview", None)
        if lbl is None:
            return
        try:
            pm = QPixmap.fromImage(image)
        except Exception:
            return
        if pm.isNull():
            return
        lbl.setPixmap(pm.scaled(
            lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _reset_monitor_view(self) -> None:
        lbl = getattr(self, "_lbl_monitor_preview", None)
        if lbl is not None:
            lbl.setPixmap(QPixmap())
            lbl.setText("鏡頭預覽（按「開始」啟動）")
        self._update_preview_telemetry()
        self._update_rec_pill()
        self._refresh_monitor_metrics()

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    def _refresh_monitor_metrics(self) -> None:
        """把最新一筆 rPPG / 疲勞 / 融合快照渲染到監測頁卡片（唯讀，不改任何數值）。"""
        if self._engine_mode:
            return
        if not hasattr(self, "_mon_fused_level"):
            return
        r = self._latest_rppg_metrics
        f = self._latest_fatigue_metrics
        z = self._latest_fused_score
        bars = getattr(self, "_mon_contrib_bars", {})

        # 綜合疲勞融合：大分數（0–100）+ 等級徽章（資料驅動語意色）+ 趨勢 + 0–100 進度條
        if z is not None:
            level = str(getattr(z, "level", "") or "—")
            score01 = float(getattr(z, "score", 0.0) or 0.0)
            try:
                b, g, rr = z.color_bgr
                col = QColor(int(rr), int(g), int(b)).name()
            except Exception:
                col = "#30363d"
            self._mon_score_big.setText(f"{round(score01 * 100)}")
            self._mon_fused_level.setText(level)
            self._mon_fused_level.setStyleSheet(
                f"background-color: {col}; color: #ffffff; border-radius: 999px;"
                " padding: 3px 12px; font-size: 15px; font-weight: 700;"
            )
            # 趨勢：trend 為分數（0–1）/30s 增量，*100 換算成與大分數同尺度的 pts。
            trend = float(getattr(z, "trend", 0.0) or 0.0)
            sym = str(getattr(z, "trend_symbol", "→") or "→")
            self._mon_trend.setText(f"{sym} {abs(trend) * 100:.0f} pts / 30s")
            self._mon_score_bar.setValue(int(round(self._clamp01(score01) * 100)))
            self._mon_score_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {col}; border-radius: 999px; }}"
            )
            # 疲勞分數貢獻列（沿用 _mon_fused_score 屬性）
            self._mon_fused_score.setText(f"{score01 * 100:.0f}%")
            if "score" in bars:
                bars["score"].set_fraction(self._clamp01(score01))
        else:
            self._mon_score_big.setText("—")
            self._mon_fused_level.setText("—")
            self._mon_fused_level.setStyleSheet("")
            self._mon_trend.setText("—")
            self._mon_score_bar.setValue(0)
            self._mon_score_bar.setStyleSheet("")
            self._mon_fused_score.setText("—")
            if "score" in bars:
                bars["score"].set_fraction(None)

        # 行為疲勞（貢獻列數值沿用現行格式；迷你條為顯示層正規化，clamp 範圍見下，無語意權重）
        if f is not None:
            fd = bool(getattr(f, "face_detected", False))
            ear = float(getattr(f, "ear", 0.0) or 0.0)
            perclos = float(getattr(f, "perclos", 0.0) or 0.0)
            blink = int(getattr(f, "blink_count", 0) or 0)
            self._mon_ear.setText(f"{ear:.3f}" if fd else "—")
            self._mon_perclos.setText(f"{perclos * 100:.0f}%")
            self._mon_blink.setText(str(blink))
            expr = []
            if getattr(f, "is_squinting", False):
                expr.append("瞇眼")
            if getattr(f, "is_frowning", False):
                expr.append("皺眉")
            self._mon_expr.setText("／".join(expr) if expr else "正常")
            fixation = float(getattr(f, "fixation_duration", 0.0) or 0.0)
            self._mon_gaze.setText(
                f"固視 {fixation:.1f}s"
                f"／掃視 {float(getattr(f, 'saccade_freq_pm', 0.0) or 0.0):.0f}/min"
            )
            pitch = float(getattr(f, "head_pitch", 0.0) or 0.0)
            yaw = float(getattr(f, "head_yaw", 0.0) or 0.0)
            roll = float(getattr(f, "head_roll", 0.0) or 0.0)
            self._mon_head.setText(f"P {pitch:.0f}° Y {yaw:.0f}° R {roll:.0f}°")
            if bars:
                # EAR: 眼開合度映射到 0–1（0.10–0.40 clamp）；其餘同理，純視覺。
                bars["ear"].set_fraction(self._clamp01((ear - 0.10) / 0.30) if fd else None)
                bars["perclos"].set_fraction(self._clamp01(perclos))
                bars["blink"].set_fraction(self._clamp01(blink / 40.0))
                bars["expr"].set_fraction(0.5 * len(expr))
                bars["gaze"].set_fraction(self._clamp01(fixation / 3.0))
                bars["head"].set_fraction(self._clamp01(max(abs(pitch), abs(yaw), abs(roll)) / 30.0))
        else:
            for lbl in (self._mon_ear, self._mon_perclos, self._mon_blink,
                        self._mon_expr, self._mon_gaze, self._mon_head):
                lbl.setText("—")
            for key in ("ear", "perclos", "blink", "expr", "gaze", "head"):
                if key in bars:
                    bars[key].set_fraction(None)

        # rPPG + HRV
        if r is not None:
            bpm = effective_bpm(r)
            self._mon_bpm.setText(f"{bpm:.0f}" if bpm and bpm > 0 else "—")
            self._mon_warmup.setText(f"{float(getattr(r, 'warmup_progress', 0.0) or 0.0) * 100:.0f}%")
            sqi = float(getattr(r, "sqi", 0.0) or 0.0)
            q = float(getattr(r, "quality_score", 0.0) or 0.0)
            self._mon_sqi.setText(f"SQI {sqi:.2f}／Q {q:.2f}")
            self._mon_rmssd.setText(f"{float(getattr(r, 'rmssd', 0.0) or 0.0):.1f} ms")
            self._mon_sdnn.setText(f"{float(getattr(r, 'sdnn', 0.0) or 0.0):.1f} ms")
            self._mon_lfhf.setText(f"{float(getattr(r, 'lf_hf', 0.0) or 0.0):.2f}")
            self._mon_hrv_conf.setText(str(getattr(r, "hrv_confidence", "") or "—"))
            if hasattr(self, "_mon_wave"):
                self._mon_wave.set_data(list(getattr(r, "waveform", []) or []))
            self._update_bpm_delta(bpm)
        else:
            for lbl in (self._mon_bpm, self._mon_warmup, self._mon_sqi,
                        self._mon_rmssd, self._mon_sdnn, self._mon_lfhf, self._mon_hrv_conf):
                lbl.setText("—")
            if hasattr(self, "_mon_wave"):
                self._mon_wave.set_data([])
            self._update_bpm_delta(0.0)

    def _update_bpm_delta(self, rppg_bpm: float) -> None:
        """rPPG vs 心跳帶真值差值（Δ）：僅心跳帶連線且雙方 BPM 有效時顯示，否則隱藏。"""
        if self._engine_mode:
            return
        if not hasattr(self, "_mon_bpm_delta"):
            return
        belt_bpm = 0.0
        belt_name = "belt"
        try:
            if self._engine_controller.belt_running:
                st = self._engine_controller.belt_status()
                if st is not None and st.state == "connected" and st.bpm > 0 and not hr_is_stale(st):
                    belt_bpm = float(st.bpm)
                    belt_name = (st.device_name or "belt").split()[0][:6]
        except Exception:
            belt_bpm = 0.0
        if rppg_bpm and rppg_bpm > 0 and belt_bpm > 0:
            diff = rppg_bpm - belt_bpm
            arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
            self._mon_bpm_delta.setText(f"Δ {arrow} {abs(diff):.1f} vs {belt_name}")
            self._mon_bpm_delta.setVisible(True)
        else:
            self._mon_bpm_delta.setVisible(False)

    def _update_rec_pill(self) -> None:
        """REC 錄影指示 pill：錄製中顯示 ● REC mm:ss（elapsed 來自 _recording_started_at）。"""
        if self._engine_mode:
            return
        if not hasattr(self, "_mon_rec_pill"):
            return
        if self._recording and self._recording_started_at is not None:
            elapsed = max(0, int(time.time() - self._recording_started_at))
            m, s = divmod(elapsed, 60)
            self._mon_rec_pill.setText(f"● REC {m:02d}:{s:02d}")
            self._mon_rec_pill.setVisible(True)
        else:
            self._mon_rec_pill.setVisible(False)

    def _refresh_belt_cfg_labels(self) -> None:
        """把 config/hr_belt.json 載入結果（self._belt_cfg）唯讀顯示到設備設定卡。"""
        if self._engine_mode:
            return
        if not hasattr(self, "_lbl_belt_cfg_name_prefix"):
            return
        cfg = self._belt_cfg
        if cfg is None:
            self._lbl_belt_cfg_name_prefix.setText("—")
            self._lbl_belt_cfg_address.setText("—")
            self._lbl_belt_cfg_tuning.setText("—")
            self._lbl_belt_cfg_capture.setText("—")
            return
        self._lbl_belt_cfg_name_prefix.setText(cfg.name_prefix or "（未指定）")
        self._lbl_belt_cfg_address.setText(cfg.address or "（自動掃描）")
        self._lbl_belt_cfg_tuning.setText("開啟" if cfg.rppg_param_tuning_enabled else "關閉")
        self._lbl_belt_cfg_capture.setText("開啟" if cfg.capture_enabled else "關閉")

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
        if not self._global_hotkey_enabled:
            return
        self._unregister_global_hotkeys()

        user32 = cast(Any, ctypes).WinDLL("user32", use_last_error=True)
        hwnd = int(self.winId())

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
            mod_flags, vk = parsed
            if not user32.RegisterHotKey(hwnd, hotkey_id, mod_flags, vk):
                err = cast(Any, ctypes).get_last_error()
                self._hotkey_registration_failures.append(
                    {
                        "key": binding.field,
                        "sequence": seq,
                        "code": int(err),
                        "reason": "already_registered" if err == 1409 else "registration_failed",
                    }
                )
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
        for hotkey_id in self._global_hotkey_bindings:
            user32.UnregisterHotKey(hwnd, hotkey_id)
        self._global_hotkeys_registered = False

    def _on_global_hotkey(self, hotkey_id: int) -> None:
        binding = self._global_hotkey_bindings.get(hotkey_id)
        if binding is None:
            return
        binding.callback()

    def _settings_path(self) -> Path:
        return data_path("settings.json")

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
        if self._engine_mode:
            raise RuntimeError("Camera widgets are unavailable in engine mode")
        for i in range(self._cmb_camera.count()):
            if self._cmb_camera.itemData(i) == cam_idx:
                try:
                    self._engine_controller.select_camera(cam_idx)
                except ValueError:
                    return False
                self._cmb_camera.setCurrentIndex(i)
                return True
        return False

    def _sync_camera_widgets(self) -> None:
        """Mirror controller-owned camera state into the legacy widgets."""
        if self._engine_mode:
            return
        camera = self._engine_controller.camera_snapshot()
        for widget in (
            self._cmb_resolution,
            self._cmb_fps,
            self._cmb_backend,
            self._chk_horizontal_flip,
        ):
            widget.blockSignals(True)
        try:
            self._cmb_resolution.setCurrentText(camera.resolution)
            self._cmb_fps.setCurrentText(camera.fps)
            self._select_combo_by_data(self._cmb_backend, camera.backend)
            self._chk_horizontal_flip.setChecked(camera.horizontal_flip)
        finally:
            for widget in (
                self._cmb_resolution,
                self._cmb_fps,
                self._cmb_backend,
                self._chk_horizontal_flip,
            ):
                widget.blockSignals(False)

        self._cmb_camera.blockSignals(True)
        try:
            target = 0
            for i in range(self._cmb_camera.count()):
                if self._cmb_camera.itemData(i) == camera.selected_index:
                    target = i
                    break
            self._cmb_camera.setCurrentIndex(target)
        finally:
            self._cmb_camera.blockSignals(False)
        self._on_camera_combo_changed(self._cmb_camera.currentIndex())

    def _on_camera_config_changed(self, **changes: object) -> None:
        self._engine_controller.configure_camera(**changes)

    def _apply_overlay_state(self) -> None:
        overlay = self._preview_overlay
        if overlay is None:
            return
        state = self._overlay_state.snapshot()
        overlay.set_opacity(state.opacity / 100.0)
        overlay.apply_lock_state(state.locked)
        overlay.set_preview_visible(state.preview)
        overlay.set_metrics_visible(state.metrics)
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
        if self._preview_overlay is not None and isinstance(overlay_geo, str):
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
            self._sync_camera_widgets()

        toggles = data.get("toggles", {})
        if isinstance(toggles, dict):
            self._capture_preferences.load(toggles=toggles)
            self._sync_capture_preference_controls()
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
            self._sync_analysis_controls()

        self._overlay_state.load(toggles=toggles, overlay=overlay)
        loaded_overlay_geometry = self._overlay_state.snapshot().geometry
        if self._preview_overlay is not None and loaded_overlay_geometry is not None:
            self._preview_overlay.setGeometry(
                loaded_overlay_geometry.x,
                loaded_overlay_geometry.y,
                loaded_overlay_geometry.width,
                loaded_overlay_geometry.height,
            )
        self._sync_overlay_controls()

        self._web_preferences.load(web=data.get("web", {}))
        self._sync_web_preference_control()

        alarm = data.get("alarm", {})
        if isinstance(alarm, dict):
            self._alarm_config = AlarmConfig.from_dict(alarm)

    def _save_settings(self) -> Path:
        path = self._settings_path()
        if self._preview_overlay is not None:
            geometry = self._preview_overlay.geometry()
            self._overlay_state.configure(
                geometry={
                    "x": geometry.x(),
                    "y": geometry.y(),
                    "width": geometry.width(),
                    "height": geometry.height(),
                }
            )
        camera = self._engine_controller.camera_snapshot()
        analysis = self._engine_controller.analysis_snapshot()
        overlay_state = self._overlay_state.to_settings()
        capture_toggles = self._capture_preferences.to_settings_toggles()
        data = {
            "window": {
                "geometry": self._encode_bytes(self.saveGeometry()),
                "state": self._encode_bytes(self.saveState()),
            },
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
        """Refresh camera list (same strategy as V1: DirectShow names first, no OpenCV open)."""
        if not self._engine_mode:
            self._lbl_cam_hint.setText("載入中…")
            self._cmb_camera.setEnabled(False)
        dev_list: list[tuple[int, str]] = []
        try:
            from gui.camera_devices import list_camera_devices

            dev_list = list_camera_devices(max_index=20, warmup_read=True)
        except Exception as exc:
            message = f"攝影機列舉失敗：{exc}"
            if self._engine_mode:
                logger.warning(message)
            else:
                self._append_log(message)
        self._finish_camera_scan_ui(dev_list)

    def _finish_camera_scan_ui(self, dev_list: list[tuple[int, str]]) -> None:
        """Update the controller catalog and mirror it to legacy widgets."""
        self._engine_controller.replace_cameras(
            CameraDevice(index, f"[{index}] {name}") for index, name in dev_list
        )
        if self._engine_mode:
            if dev_list:
                logger.info("攝影機清單已更新：%d 個項目。", len(dev_list))
            else:
                logger.warning(
                    "未取得攝影機清單。Linux 請檢查 /dev/video*、video 群組權限，"
                    "或執行 scripts/diagnose_camera.py。"
                )
            return
        camera = self._engine_controller.camera_snapshot()
        self._cmb_camera.blockSignals(True)
        try:
            self._cmb_camera.clear()
            self._cmb_camera.addItem("── 請選擇攝影機 ──", None)
            for device in camera.devices:
                self._cmb_camera.addItem(device.label, device.index)
            self._lbl_cam_hint.setText(f"偵測：{len(camera.devices)} 台")
            self._cmb_camera.setEnabled(True)
            if camera.selected_index is None:
                self._cmb_camera.setCurrentIndex(0)
            else:
                self._select_camera_by_index(camera.selected_index)
        finally:
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
        if self._engine_mode:
            callbacks = (
                lambda: self._toggle_overlay_preference("metrics"),
                lambda: self._toggle_overlay_preference("preview"),
                self._toggle_pipeline,
                lambda: self._toggle_overlay_preference("locked"),
                lambda: self._toggle_overlay_preference("all_enabled"),
                self._toggle_recording,
            )
        else:
            actions = self._menu_actions_hotkeys
            for action, key in zip(actions, keys, strict=True):
                action.setShortcut(QKeySequence(key))
            callbacks = tuple(action.trigger for action in actions)
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

        def stop_in_background() -> None:
            stopped = server.stop(join_timeout=5.0)
            still_alive = bool(not stopped and server.is_alive())
            self._web_restart_bridge.stopped.emit(stopped, still_alive)

        threading.Thread(
            target=stop_in_background,
            daemon=True,
            name="WebServerRestartStop",
        ).start()

    def _on_web_restart_stopped(self, _stopped: bool, still_alive: bool) -> None:
        stopping_server = self._web_restart_stopping_server
        self._web_restart_in_progress = False
        self._web_restart_stopping_server = None
        if still_alive:
            if not self._web_restart_shutdown:
                self._web_server = stopping_server
            self._append_log(
                "⚠ Web 儀表板舊執行緒未能及時結束；若儀表板無法更新，請重新啟動程式。"
            )
            return
        if not self._web_restart_shutdown:
            self._start_web_server()

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
        for thread in dict.fromkeys(servers):
            stopped = thread.stop(join_timeout=5.0)
            if not stopped and thread.is_alive():
                self._append_log(
                    "⚠ Web 儀表板舊執行緒未能及時結束；若儀表板無法更新，請重新啟動程式。"
                )

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
            self._alarm_controller.set_config(self._alarm_config)
        if "camera" in selected:
            self._engine_controller.reset_camera_settings()
            self._sync_camera_widgets()
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
            self._sync_replay_controls()
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
            "recording_path": str(self._recording_db_path or ""),
            "auto_capture_active": self._auto_capture_timer is not None,
            "monitor_focus": bool(getattr(self, "_monitor_focus", False)),
            "selected_camera_index": camera.selected_index,
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
                "supported": bool(self._global_hotkey_enabled),
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

    def _set_combo_value(self, combo: QComboBox, value: object, *, by_data: bool = False) -> None:
        wanted = str(value)
        for index in range(combo.count()):
            current = combo.itemData(index) if by_data else combo.itemText(index)
            if str(current) == wanted:
                combo.setCurrentIndex(index)
                return
        raise ValueError(f"Unsupported option: {wanted}")

    def _handle_desktop_command(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if command == "state.get":
            return self._desktop_control_state()

        if command == "pipeline.set":
            enabled = self._require_bool(args, "enabled")
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
            self._sync_camera_widgets()
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
            self._sync_camera_widgets()
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
                capture = self._capture_preferences.snapshot()
                duration = args.get("duration_seconds", capture.auto_capture_seconds)
                if isinstance(duration, bool) or not isinstance(duration, int) or not 10 <= duration <= 600:
                    raise ValueError("duration_seconds must be between 10 and 600")
                include_belt = (
                    self._require_bool(args, "include_belt")
                    if "include_belt" in args
                    else False
                )
                if self._auto_capture_timer is None:
                    self._configure_capture_preferences(
                        auto_capture_seconds=duration,
                        auto_capture_include_belt=include_belt,
                    )
                    self._on_auto_capture_clicked()
            elif self._auto_capture_timer is not None:
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
            self._alarm_controller.set_config(self._alarm_config)
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
            source = self._alarm_controller.preview_scenario(
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
            actions = {
                "recordings": self._open_recordings_dir,
                "save": self._on_save_layout,
                "web": self._on_web_info,
            }
            if action == "web_lan":
                enabled = self._require_bool(args, "enabled")
                self._configure_web_preferences(allow_lan=enabled)
            elif action in actions:
                actions[action]()
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
            QTimer.singleShot(0, self._shutdown_engine)

        else:
            raise ValueError(f"Unsupported desktop command: {command}")

        return self._desktop_control_state()

    def _shutdown_engine(self) -> None:
        if self._engine_controller.request_shutdown() == "stop_replay":
            self._stop_replay()
            return
        self.close()
        if self._engine_mode:
            app = QApplication.instance()
            if app is not None:
                app.quit()

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
        if self._video_thread is not None or self._video_worker is not None:
            raise RuntimeError("Previous video recorder cleanup is still pending")
        if self._metrics_recorder is not None:
            return
        rec_dir = self._recordings_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_path = rec_dir / f"metrics_{stamp}.db"
        self._metrics_recorder = MetricsRecorder(str(db_path))
        self._recording_db_path = db_path
        self._recording_started_at = time.time()
        self._recording_count = 0
        if self._rec_ui_timer is not None:
            self._rec_ui_timer.start()
            self._update_rec_pill()

        self._video_queue = queue.Queue(maxsize=8)
        video_path = rec_dir / f"video_{stamp}.mp4"
        self._recording_video_path = video_path
        thread = QThread(self)
        worker = VideoRecorderWorker(self._video_queue, video_path, fps=self._last_fps or 30.0)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_video_recording_started)
        worker.warning.connect(self._on_video_recording_warning)
        worker.failed.connect(self._on_video_recording_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_adapter_thread_finished("video", current)
        )
        thread.finished.connect(thread.deleteLater)
        self._video_thread = thread
        self._video_worker = worker
        thread.start()
        self._update_recording_routing()

    def _stop_recording(self) -> bool:
        self._engine_controller.stop_recording()
        if self._rec_ui_timer is not None:
            self._rec_ui_timer.stop()
        if hasattr(self, "_mon_rec_pill"):
            self._mon_rec_pill.setVisible(False)
        if self._metrics_recorder is not None:
            try:
                self._metrics_recorder.close()
            except Exception as exc:
                logger.warning("關閉指標記錄器失敗：%s", exc)
            finally:
                self._metrics_recorder = None
        if self._video_worker is not None:
            try:
                self._video_worker.request_stop()
            except Exception as exc:
                logger.warning("停止影片記錄器失敗：%s", exc)
        stopped = True
        if self._video_thread is not None:
            try:
                self._video_thread.quit()
                stopped = self._video_thread.wait(2000) is not False
            except Exception as exc:
                stopped = False
                logger.warning("等待影片記錄執行緒結束失敗：%s", exc)
        self._metrics_recorder = None
        self._recording_db_path = None
        self._recording_started_at = None
        if stopped:
            self._video_thread = None
            self._video_worker = None
            self._video_queue = None
            self._recording_video_path = None
        self._update_recording_routing()
        return stopped

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
        if self._recording_count % 60 == 0:
            self._set_legacy_text(
                "_lbl_record", f"記錄狀態：進行中（{self._recording_count} 筆）"
            )

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
        self._set_legacy_text("_btn_record", "開始記錄")
        self._set_legacy_text("_lbl_record", "記錄狀態：未啟動")
        self._stop_recording()
        self._notify_user("影片錄製", msg)

    def _append_log(self, msg: str) -> None:
        if self._engine_mode:
            severity = _classify_log_message(msg, warning_priority=True)
            if severity == "error":
                logger.error("%s", msg)
            elif severity == "warning":
                logger.warning("%s", msg)
            else:
                logger.info("%s", msg)
            return
        self._append_log_html(msg)
        self.statusBar().showMessage(msg, 4000)

    def _append_log_html(self, msg: str) -> None:
        """把訊息以 rich text 顯示到 Log console：前綴 HH:MM:SS 時間戳，依既有符號著色。

        純顯示層加工（不改任何呼叫端傳入的訊息內容）；console 底色恆為深色（VIDEO），
        故著色一律取深色 palette 語意色以確保對比。訊息文字先 html escape 再嵌入。
        """
        if not hasattr(self, "_log"):
            return
        d = _PALETTES["dark"]
        severity = _classify_log_message(msg)
        if severity == "error":
            color = d["BAD"]
        elif severity == "warning":
            color = d["STATUS_WARN"]
        elif severity == "success":
            color = d["STATUS_OK"]
        elif severity == "link":
            color = d["ACCENT"]
        else:
            color = d["TEXT_ON_VIDEO"]
        ts = time.strftime("%H:%M:%S")
        line = (
            f'<span style="color:rgba(255,255,255,0.45)">{ts}</span> '
            f'<span style="color:{color}">{html.escape(msg)}</span>'
        )
        self._log.append(line)

    def _publish_desktop_notice(self, message: str, *, level: str = "error") -> None:
        """Publish a one-shot UI notice for the Flutter/Tauri shell."""
        self._desktop_notice_seq += 1
        self._desktop_notice = {
            "id": self._desktop_notice_seq,
            "level": level,
            "message": str(message),
        }

    def _notify_user(self, title: str, message: str, *, level: str = "error") -> None:
        if self._engine_mode:
            self._publish_desktop_notice(f"{title}：{message}", level=level)
            return
        if level == "info":
            QMessageBox.information(self, title, message)
        else:
            QMessageBox.warning(self, title, message)

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
            thread = QThread(self)
            worker = VideoReplayWorker(
                replay_state.dataset_dir,
                write_annotated_video=replay_state.annotated,
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
            self._replay_queue_reset()
            self._set_replay_controls_running(True)
            self._sync_replay_controls()
            if not self._engine_mode:
                self._bar_replay_progress.setRange(0, 0)
                self._lbl_replay_preview.clear()
                if preview_enabled:
                    self._lbl_replay_preview.setText("影片預覽載入中")
                else:
                    self._lbl_replay_preview.setText("平行驗證中：預覽停用，以提升批次速度")
            self._set_legacy_text("_lbl_pipeline", f"管線：影片回測 {mode_label}")
            self._set_legacy_text("_lbl_camera", "影片：準備中")
            self._set_legacy_text("_lbl_face", "臉部：統計中")
            self._set_legacy_text("_lbl_fps", "FPS：—")
            self._set_legacy_text("_lbl_codec", "解析度：—")
            self._append_log(
                f"[影片回測] 開始{mode_label}：{replay_state.dataset_dir} "
                f"(jobs={jobs}, preview={'on' if preview_enabled else 'off'})"
            )
            thread.start()
        except Exception:
            self._replay_thread = None
            self._replay_worker = None
            self._replay_state.restore(previous_replay_state)
            self._sync_replay_controls()
            self._set_replay_controls_running(False)
            self._engine_controller.finish_replay()
            raise

    def _stop_replay(self) -> None:
        if self._replay_worker is None:
            return
        self._engine_controller.request_replay_stop()
        self._replay_stopping = True
        self._replay_worker.request_stop()
        self._update_replay_presentation(
            current_text="目前影片：正在停止，請稍候",
            parallel_status_text="處理清單：正在停止，已派發的影片會安全收尾",
        )
        if not self._engine_mode:
            self._btn_replay_stop.setEnabled(False)
            self._btn_replay_stop.setText("停止中")
        self._set_legacy_text("_lbl_pipeline", "管線：影片回測 停止中")
        self._append_log("[影片回測] 已送出停止請求，等待目前 frame 安全收尾")

    def _set_replay_controls_running(self, running: bool) -> None:
        if self._engine_mode:
            return
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
        replay_state = self._replay_state.snapshot()
        total_count = max(replay_state.total_count, total)
        self._update_replay_presentation(total_count=total_count)
        if event == "video_start":
            if not self._engine_mode:
                self._bar_replay_progress.setRange(0, max(total, 1))
                self._bar_replay_progress.setValue(replay_state.done_count)
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos[key] = summary
                self._replay_queue_upsert(summary, done=False)
                self._update_replay_presentation(
                    current_text=(
                        f"目前影片：派發 {current}/{total}，正在跑 "
                        f"{len(self._replay_active_videos)} 支"
                    )
                )
                self._update_replay_status_strip(
                    summary,
                    prefix=f"影片回測 {self._replay_state.snapshot().mode_label}",
                )
            else:
                self._update_replay_presentation(
                    current_text=f"目前影片：{current}/{total}"
                )
            self._refresh_replay_parallel_status()
        elif event == "video_done":
            done_count = max(self._replay_state.snapshot().done_count, current)
            self._update_replay_presentation(done_count=done_count)
            if not self._engine_mode:
                self._bar_replay_progress.setRange(0, max(total, 1))
                self._bar_replay_progress.setValue(done_count)
            if summary is not None:
                key = self._replay_video_key(summary)
                self._replay_active_videos.pop(key, None)
                self._replay_completed_summaries.append(summary)
                self._replay_queue_upsert(summary, done=True)
                self._refresh_replay_summary()
                self._replay_recent_done.insert(0, self._format_replay_video_label(summary, include_status=True))
                self._replay_recent_done = self._replay_recent_done[:3]
                failed_text = "，此支失敗" if summary.status == "failed" else ""
                self._update_replay_presentation(
                    current_text=(
                        f"目前影片：已完成 {done_count}/{max(total, 1)}{failed_text}"
                    )
                )
                self._update_replay_status_strip(
                    summary,
                    prefix=f"影片回測 {self._replay_state.snapshot().mode_label}",
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
            self._update_replay_status_strip(
                summary,
                prefix=f"影片回測 {self._replay_state.snapshot().mode_label}",
            )
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

    def _update_replay_status_strip(self, summary: ReplayVideoSummary, *, prefix: str) -> None:
        if self._engine_mode:
            return
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
        if self._engine_mode or image.isNull():
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
        if not self._engine_mode:
            self._bar_replay_progress.setRange(0, max(result.videos_total, 1))
            self._bar_replay_progress.setValue(result.videos_done + result.videos_failed)
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
        if result.summaries:
            self._update_replay_status_strip(result.summaries[-1], prefix=f"影片回測 {state}")
        else:
            self._set_legacy_text("_lbl_pipeline", f"管線：影片回測 {state}")
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
        self._set_legacy_text("_lbl_pipeline", "管線：影片回測 失敗")
        self._append_log(f"[影片回測] 批次失敗：{msg}")
        self._notify_user("影片回測", msg)

    def _on_replay_thread_finished(self) -> None:
        self._replay_thread = None
        self._replay_worker = None
        self._replay_stopping = False
        self._replay_state.finish_thread()
        self._sync_replay_controls()
        self._set_replay_controls_running(False)
        if self._engine_controller.finish_replay():
            self._shutdown_engine()

    def _on_toggle_all(self, checked: bool) -> None:
        self._configure_overlay(all_enabled=checked)
        self._append_log(f"[UI] 全部 Overlay → {'顯示' if checked else '隱藏'}")

    def _on_preview_toggled(self, checked: bool) -> None:
        self._configure_overlay(preview=checked)
        self._append_log(f"[UI] 鏡頭預覽 Overlay → {'開啟' if checked else '關閉'}")

    def _on_metrics_toggled(self, checked: bool) -> None:
        self._configure_overlay(metrics=checked)
        self._append_log(f"[UI] 數值 Overlay → {'開啟' if checked else '關閉'}")

    def _on_lock_toggled(self, checked: bool) -> None:
        self._configure_overlay(locked=checked)
        self._append_log(f"[UI] Overlay 鎖定 → {'鎖定（穿透點擊）' if checked else '解鎖（可拖曳）'}")

    def _sync_overlay_visibility(self) -> None:
        """Show overlay window only when pipeline running AND at least one overlay is on."""
        overlay = self._preview_overlay
        if overlay is None:
            return
        state = self._overlay_state.snapshot()
        any_on = state.preview or state.metrics
        if self._engine_controller.pipeline_snapshot().running and any_on:
            overlay.refresh_layout()
            overlay.show()
        else:
            overlay.hide()

    def _on_opacity(self, v: int) -> None:
        self._configure_overlay(opacity=v)

    # ── Camera worker ─────────────────────────────────────────────────────────

    def _start_camera_worker(self) -> None:
        cam_idx = self.selected_camera_index
        if cam_idx is None:
            self._append_log("⚠ 請先選擇攝影機再開始。")
            self._pipeline_running = False
            self._engine_controller.stop_pipeline()
            self._set_legacy_text("_btn_start", "開始")
            self._set_legacy_text("_lbl_pipeline", "管線：停止")
            return

        spec = self._engine_controller.camera_start_spec()
        cam_idx = spec.index
        w, h = spec.width, spec.height
        target_fps = spec.target_fps
        backend = spec.backend
        backend_label = backend.upper()
        horizontal_flip = spec.horizontal_flip

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
        thread.finished.connect(
            lambda current=thread: self._on_adapter_thread_finished("camera", current)
        )
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
        self._engine_controller.mark_pipeline_cleanup_pending()
        self._fail_closed_pipeline_adapters()

    def _fail_closed_pipeline_adapters(self) -> None:
        """Best-effort cleanup after controller can no longer restore live topology."""
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
                    ("camera worker", self._cam_worker.request_stop),
                )
            )
        if self._cam_thread is not None:
            camera_steps.extend(
                (
                    ("camera thread quit", self._cam_thread.quit),
                    ("camera thread wait", lambda: self._cam_thread.wait(3000)),
                )
            )
        camera_thread_stopped = self._cam_thread is None
        for label, cleanup in camera_steps:
            try:
                result = cleanup()
                if label == "camera thread wait":
                    camera_thread_stopped = result is not False
            except Exception as exc:
                all_stopped = False
                logger.warning("fail-closed %s cleanup failed: %s", label, exc)
        if camera_thread_stopped:
            self._cam_thread = None
            self._cam_worker = None
        else:
            all_stopped = False
        self._pipeline_running = False
        self._recording = False
        if all_stopped:
            self._engine_controller.finish_pipeline_cleanup()
        else:
            self._engine_controller.mark_pipeline_cleanup_pending()
        self._set_legacy_text("_btn_start", "開始")
        self._set_legacy_text("_lbl_pipeline", "管線：停止")
        self._set_legacy_text("_btn_record", "開始記錄")
        self._set_legacy_text("_lbl_record", "記錄狀態：未啟動")

    def _on_adapter_thread_finished(self, kind: str, thread: QThread) -> None:
        """Release late-finishing adapter ownership without touching a newer session."""
        if kind == "video" and self._video_thread is thread:
            self._video_thread = None
            self._video_worker = None
            self._video_queue = None
            self._recording_video_path = None
        elif kind == "camera" and self._cam_thread is thread:
            self._cam_thread = None
            self._cam_worker = None
        elif kind == "combined" and self._combined_thread is thread:
            self._combined_thread = None
            self._combined_worker = None
            self._combined_queue = None
        elif kind == "rppg" and self._rppg_thread is thread:
            self._rppg_thread = None
            self._rppg_worker = None
            self._bgr_queue = None
        elif kind == "fatigue" and self._fatigue_thread is thread:
            self._fatigue_thread = None
            self._fatigue_worker = None
            self._fatigue_queue = None
        else:
            return
        if self._engine_controller.pipeline_snapshot().cleanup_pending:
            self._fail_closed_pipeline_adapters()

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
        if not self._engine_controller.belt_running:
            self._engine_controller.clear_belt_samples()
            err = self._engine_controller.start_belt(belt_cfg)
            if err:
                self._append_log(f"⚠ 心跳帶校準啟動失敗：{err}")
                if not self._engine_mode:
                    self._lbl_belt_status.setText("心跳帶校準：啟動失敗")
                self._capture_preferences.configure(belt_calibration=False)
                self._sync_capture_preference_controls()
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
        self._update_belt_status_label()

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
            self._belt_ui_timer.stop()
        except Exception:
            logger.exception("心跳帶校準啟動回滾時停止計時器失敗")
        self._rppg_param_coordinator = None
        self._belt_calibrator = None
        self._last_calib_fed_metrics = None
        if stop_belt and self._engine_controller.belt_running:
            try:
                self._engine_controller.stop_belt()
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
        if self._engine_controller.belt_running:
            self._engine_controller.stop_belt()
        self._append_log("■ 心跳帶真值校準停止。")
        if not self._engine_mode:
            self._lbl_belt_status.setText("未啟用")
        self._reset_belt_panel()
        self._update_device_status()

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
        self._update_belt_status_label()
        self._update_device_status()

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

    def _update_belt_status_label(self) -> None:
        """輪詢心跳帶連線與校準狀態並更新狀態列（QTimer 每秒觸發）。"""
        if self._engine_mode:
            return
        self._update_belt_panel()
        st = self._engine_controller.belt_status()
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
        if self._engine_mode:
            return
        for lbl in (
            self._lbl_belt_bpm, self._lbl_belt_rr, self._lbl_belt_contact,
            self._lbl_belt_battery, self._lbl_belt_rssi, self._lbl_belt_stale,
            self._lbl_belt_device, self._lbl_belt_address, self._lbl_belt_location,
            self._lbl_belt_connected_since, self._lbl_belt_notifications, self._lbl_belt_last_error,
            self._lbl_belt_hrv_rmssd, self._lbl_belt_hrv_sdnn, self._lbl_belt_hrv_lfhf,
            self._lbl_belt_hrv_conf, self._lbl_belt_hrv_warmup,
            self._lbl_belt_calib_offset, self._lbl_belt_calib_raw_resid, self._lbl_belt_calib_corr_resid,
            self._lbl_belt_calib_confidence, self._lbl_belt_calib_status, self._lbl_belt_calib_pairs,
            self._lbl_belt_banner_device, self._lbl_belt_banner_bpm,
            self._lbl_belt_banner_battery, self._lbl_belt_banner_rssi,
            self._lbl_belt_calib_resid,
        ):
            lbl.setText("—")
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        self._set_status_dot(self._belt_banner_dot, pal["STATUS_OFF"])
        self._belt_bpm_spark.set_data([])
        self._belt_calib_bar.set_fraction(None)

    def _update_belt_panel(self) -> None:
        """更新「心跳帶」專屬區塊的所有數值（即時／連線／HRV／rPPG 校準）。

        唯讀輪詢既有狀態物件，不改動任何校準/worker/BLE 邏輯與數值行為；
        HRV 僅供顯示，絕不寫回任何會被疲勞融合分數讀取的欄位。
        """
        if self._engine_mode:
            return
        self._refresh_belt_cfg_labels()
        st = self._engine_controller.belt_status()
        cal = self._belt_calibrator
        if st is None:
            self._reset_belt_panel()
            return

        # 橫幅卡（裝置名／連線狀態圓點／BPM 真值／電量／RSSI）
        pal = _PALETTES.get(self._theme, _PALETTES["dark"])
        self._lbl_belt_banner_device.setText(st.device_name or st.device_address or "—")
        connected = st.state == "connected" and not hr_is_stale(st)
        self._set_status_dot(
            self._belt_banner_dot,
            pal["STATUS_OK"] if connected else (pal["STATUS_WARN"] if st.state == "connected" else pal["STATUS_OFF"]),
        )
        self._lbl_belt_banner_bpm.setText(f"{st.bpm}" if st.bpm > 0 and not hr_is_stale(st) else "—")
        self._lbl_belt_banner_battery.setText(f"{st.battery_level}%" if st.battery_level is not None else "—")
        self._lbl_belt_banner_rssi.setText(f"{st.rssi:.0f} dBm" if st.rssi else "—")

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
            samples = self._engine_controller.belt_samples()
            physio = compute_watch_physio(samples)
        except Exception:
            samples = []
            physio = None
        # 即時卡 BPM 趨勢 sparkline（復用既有 hub 樣本，不新增採樣機制）
        bpm_hist = [float(s.bpm) for s in samples if getattr(s, "bpm", 0) and s.bpm > 0]
        self._belt_bpm_spark.set_data(bpm_hist[-120:])
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
            # 殘差橫條：校正後殘差相對原始殘差的比例（越短代表校正後越接近真值）
            raw = float(cs.raw_residual_bpm or 0.0)
            corr = float(cs.corrected_residual_bpm or 0.0)
            if raw > 0.0:
                self._belt_calib_bar.set_fraction(self._clamp01(corr / raw))
                self._lbl_belt_calib_resid.setText(f"{raw:.1f} → {corr:.1f}")
            else:
                self._belt_calib_bar.set_fraction(None)
                self._lbl_belt_calib_resid.setText("—")
        else:
            for lbl in (
                self._lbl_belt_calib_offset, self._lbl_belt_calib_raw_resid, self._lbl_belt_calib_corr_resid,
                self._lbl_belt_calib_confidence, self._lbl_belt_calib_status, self._lbl_belt_calib_pairs,
                self._lbl_belt_calib_resid,
            ):
                lbl.setText("—")
            self._belt_calib_bar.set_fraction(None)

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
        thread.finished.connect(
            lambda current=thread: self._on_adapter_thread_finished("combined", current)
        )
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._combined_thread = thread
        self._combined_worker = worker
        thread.start()

        self._begin_auto_baseline()
        self._update_frame_routing()
        if self._preview_overlay is not None:
            self._preview_overlay.show_rppg_panel(enable_rppg)
            self._preview_overlay.show_fatigue_panel(True)
            self._preview_overlay.show_fused_panel(True)
        self._append_log("▶ 合併引擎啟動（rPPG + 行為警覺，單 MediaPipe 實例）")

    def _stop_combined_worker(self) -> bool:
        if self._combined_worker is not None:
            self._combined_worker.request_stop()
        stopped = True
        if self._combined_thread is not None:
            self._combined_thread.quit()
            stopped = self._combined_thread.wait(5000) is not False
        if not stopped:
            return False
        self._combined_thread = None
        self._combined_worker = None
        self._end_baseline_collection()
        if self._combined_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._combined_queue)
        self._combined_queue = None
        if self._preview_overlay is not None:
            self._preview_overlay.show_rppg_panel(False)
            self._preview_overlay.show_fatigue_panel(False)
            self._preview_overlay.show_fused_panel(False)
        self._update_frame_routing()
        return True

    def _on_fused_score(self, score: object) -> None:
        if self._preview_overlay is not None:
            self._preview_overlay.update_fused_score(score)  # type: ignore[arg-type]
        self._latest_fused_score = score
        self._refresh_monitor_metrics()
        self._record_metrics()
        self._emit_web_metrics()

    def _on_combined_status(self, msg: str) -> None:
        self._set_legacy_text("_lbl_pipeline", f"引擎：{msg}")

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
        thread.finished.connect(
            lambda current=thread: self._on_adapter_thread_finished("rppg", current)
        )
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._rppg_thread = thread
        self._rppg_worker = worker
        thread.start()

        self._update_frame_routing()
        if self._preview_overlay is not None:
            self._preview_overlay.show_rppg_panel(True)
        self._append_log("▶ rPPG 引擎啟動（MediaPipe Face Landmarker + POS）")

    def _stop_rppg_worker(self) -> bool:
        if self._rppg_worker is not None:
            self._rppg_worker.request_stop()
        stopped = True
        if self._rppg_thread is not None:
            self._rppg_thread.quit()
            stopped = self._rppg_thread.wait(4000) is not False
        if not stopped:
            return False
        self._rppg_thread = None
        self._rppg_worker = None
        if self._bgr_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._bgr_queue)
        self._bgr_queue = None
        self._update_frame_routing()
        if self._preview_overlay is not None:
            self._preview_overlay.show_rppg_panel(False)
        self._set_legacy_text("_lbl_face", "臉部：—")
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
        if self._preview_overlay is not None:
            self._preview_overlay.update_rppg_metrics(metrics)  # type: ignore[arg-type]
        self._latest_rppg_metrics = metrics
        self._refresh_monitor_metrics()
        self._record_metrics()
        self._emit_web_metrics()

    def _on_face_detected(self, detected: bool) -> None:
        self._set_legacy_text(
            "_lbl_face", "臉部：偵測中 ✓" if detected else "臉部：未偵測到"
        )

    def _on_rppg_status(self, msg: str) -> None:
        self._set_legacy_text("_lbl_pipeline", f"rPPG：{msg}")

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
        thread.finished.connect(
            lambda current=thread: self._on_adapter_thread_finished("fatigue", current)
        )
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._fatigue_thread = thread
        self._fatigue_worker = worker
        thread.start()

        self._begin_auto_baseline()
        self._update_frame_routing()
        if self._preview_overlay is not None:
            self._preview_overlay.show_fatigue_panel(True)
        self._append_log("▶ 行為警覺引擎啟動（V2：EAR + 瞳孔 + 注視 + 頭部）")

    def _stop_fatigue_worker(self) -> bool:
        if self._fatigue_worker is not None:
            self._fatigue_worker.request_stop()
        stopped = True
        if self._fatigue_thread is not None:
            self._fatigue_thread.quit()
            stopped = self._fatigue_thread.wait(4000) is not False
        if not stopped:
            return False
        self._fatigue_thread = None
        self._fatigue_worker = None
        self._end_baseline_collection()
        if self._fatigue_queue is not None and self._cam_worker is not None:
            self._cam_worker.detach_bgr_queue(self._fatigue_queue)
        self._fatigue_queue = None
        self._update_frame_routing()
        if self._preview_overlay is not None:
            self._preview_overlay.show_fatigue_panel(False)
        return True

    def _on_behavior_toggled(self, checked: bool) -> None:
        analysis = self._engine_controller.analysis_snapshot()
        self._configure_analysis(
            behavior_enabled=checked,
            rppg_enabled=analysis.rppg_enabled,
        )

    def _on_fatigue_metrics(self, metrics: object) -> None:
        if self._preview_overlay is not None:
            self._preview_overlay.update_fatigue_metrics(metrics)  # type: ignore[arg-type]
        self._latest_fatigue_metrics = metrics
        self._refresh_monitor_metrics()
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
        self._set_legacy_enabled("_btn_record_baseline", True)
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
        self._set_legacy_enabled("_btn_record_baseline", False)
        self._set_profile_status("記錄清醒基線中… 0%")
        self._append_log("[基線] 開始手動記錄清醒基線（約 60 秒，請保持清醒自然狀態）")

    def _on_fatigue_face_detected(self, detected: bool) -> None:
        if self._rppg_worker is None:
            self._set_legacy_text(
                "_lbl_face", "臉部：偵測中 ✓" if detected else "臉部：未偵測到"
            )

    def _on_fatigue_status(self, msg: str) -> None:
        self._set_legacy_text("_lbl_pipeline", f"警覺：{msg}")

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
        """Called once after camera opens — shows actual driver-reported settings."""
        fps_str = f"{fps:.0f}" if fps > 0 else "—"
        self._set_legacy_text("_lbl_codec", f"編碼：{codec}")
        self._set_legacy_text("_lbl_fps", f"FPS：{fps_str}")
        self._last_camera_info = {"codec": codec, "width": w, "height": h}
        cam_text = self._engine_controller.selected_camera_label()
        self._append_log(
            f"[相機] 實際格式 → 編碼：{codec}  解析度：{w}×{h}  FPS：{fps_str}"
        )
        if self._preview_overlay is not None:
            self._preview_overlay.update_camera_info(codec, w, h, cam_text)
        self._update_preview_telemetry()
        self._emit_web_metrics(force=True)

    def _on_frame(self, image) -> None:
        if self._preview_overlay is not None:
            self._preview_overlay.update_frame(image)
        self._update_monitor_preview(image)
        self._emit_web_frame(image)

    def _on_record_frame(self, image) -> None:
        if self._video_queue is None:
            return
        try:
            self._video_queue.put_nowait((time.perf_counter(), image))
        except queue.Full:
            pass

    def _on_fps(self, fps: float) -> None:
        if self._preview_overlay is not None:
            self._preview_overlay.update_fps(fps)
        self._set_legacy_text("_lbl_fps", f"FPS：{fps:.1f}")
        self._last_fps = float(fps)
        self._update_preview_telemetry()
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
            self._set_legacy_text("_btn_record", "開始記錄")
            self._set_legacy_text("_lbl_record", "記錄狀態：未啟動")
            self._stop_recording()
            self._append_log("○ 相機中斷，已一併結束記錄。")
        self._set_record_source(None)
        self._set_frame_source(None)
        if self._cam_worker is not None:
            self._cam_worker.request_stop()
        self._pipeline_running = False
        self._engine_controller.stop_pipeline()
        self._cam_worker = None
        self._cam_thread = None
        self._latest_rppg_metrics = None
        self._latest_fatigue_metrics = None
        self._latest_fused_score = None
        self._last_fps = 0.0
        self._last_camera_info = {"codec": "", "width": 0, "height": 0}
        self._reset_monitor_view()
        self._set_legacy_text("_btn_start", "開始")
        self._set_legacy_text("_lbl_pipeline", "管線：停止")
        self._set_legacy_text("_lbl_fps", "FPS：—")
        self._sync_overlay_visibility()
        self._update_device_status()
        self._emit_web_metrics(force=True)
        if self._engine_mode:
            self._publish_desktop_notice(f"攝影機錯誤：{msg}")
            return
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
        pipeline_running = self._engine_controller.pipeline_snapshot().running
        if not pipeline_running:
            self._latest_rppg_metrics = None
            self._latest_fatigue_metrics = None
            self._latest_fused_score = None
            self._reset_monitor_view()
            self._set_legacy_text("_btn_start", "停止")
            self._set_legacy_text("_lbl_pipeline", "管線：運作中")
            self._set_legacy_text("_lbl_fps", "FPS：—")
            self._set_legacy_text("_lbl_face", "臉部：—")
            try:
                self._engine_controller.start_pipeline()
            except (ValueError, RuntimeError):
                self._pipeline_running = False
                self._set_legacy_text("_btn_start", "開始")
                self._set_legacy_text("_lbl_pipeline", "管線：停止")
                self._engine_controller.stop_pipeline()
                self._sync_overlay_visibility()
                self._update_preview_telemetry()
                self._update_device_status()
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
                self._set_legacy_text("_btn_start", "開始")
                self._set_legacy_text("_lbl_pipeline", "管線：停止")
                self._notify_user("管線", f"無法啟動分析管線：{exc}")
                self._sync_overlay_visibility()
                self._update_device_status()
                self._emit_web_metrics(force=True)
                return
            self._ensure_belt_calibration()   # rPPG 運行時視勾選啟動背景校準
            self._sync_overlay_visibility()
            self._update_preview_telemetry()
            self._update_device_status()
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
            self._reset_monitor_view()
            self._set_legacy_text("_btn_start", "開始")
            self._set_legacy_text("_lbl_pipeline", "管線：停止")
            self._set_legacy_text("_lbl_fps", "FPS：—")
            self._set_legacy_text("_lbl_codec", "編碼：—")
            if self._belt_calibrator is not None:
                self._stop_belt_calibration()   # 停止前先存本次 session 校準版本
            self._stop_camera_worker()
            self._sync_overlay_visibility()
            self._update_preview_telemetry()
            self._update_device_status()
            self._append_log("■ 管線停止。")
            if self._recording:
                self._recording = False
                self._set_legacy_text("_btn_record", "開始記錄")
                self._set_legacy_text("_lbl_record", "記錄狀態：未啟動")
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
            self._set_legacy_text("_btn_record", "停止記錄")
            self._set_legacy_text("_lbl_record", "記錄狀態：進行中")
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
            self._set_legacy_text("_btn_record", "開始記錄")
            self._set_legacy_text("_lbl_record", "記錄狀態：未啟動")
            if not self._stop_recording():
                self._engine_controller.mark_pipeline_cleanup_pending()
                self._fail_closed_pipeline_adapters()
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
        if not self._engine_mode:
            self._btn_auto_capture.setText("自動採集")
            self._spn_auto_capture_seconds.setEnabled(True)

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
        if self._auto_capture_timer is not None:
            # 倒數中再按一次 → 提前停止。
            self._append_log("■ 自動採集：使用者提前按下停止。")
            self._finish_auto_capture(early=True)
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
        if not self._engine_mode:
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

    def _on_camera_combo_changed(self, _index: int) -> None:
        data = self._cmb_camera.currentData()
        text = self._cmb_camera.currentText()
        if data is None:
            self._engine_controller.select_camera(None)
            self._lbl_camera.setText("相機：未選擇")
        else:
            try:
                selected = self._engine_controller.camera_snapshot().selected_index
                if int(data) != selected:
                    self._engine_controller.select_camera(int(data))
            except (TypeError, ValueError):
                self._lbl_camera.setText("相機：未選擇")
                return
            self._lbl_camera.setText(f"相機：{text}")

    @property
    def selected_camera_index(self) -> int | None:
        """OpenCV device index owned by the headless engine controller."""
        return self._engine_controller.camera_snapshot().selected_index

    def _open_recordings_dir(self) -> None:
        rec = self._recordings_dir()
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

    def _on_web_allow_lan_toggled(self, checked: bool) -> None:
        self._configure_web_preferences(allow_lan=checked)
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
        if self._engine_mode:
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
            if self._engine_mode:
                raise RuntimeError("Web dashboard failed to start")
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
        if self._engine_mode:
            return
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
        if self._engine_controller.request_shutdown() == "stop_replay":
            self._stop_replay()
            event.ignore()
            return
        self._unregister_global_hotkeys()
        self._cancel_pending_auto_capture_timer()
        if self._belt_calibrator is not None:
            self._stop_belt_calibration()   # 存本次 session 校準版本
        self._belt_ui_timer.stop()
        self._engine_controller.stop_belt()
        self._web_restart_shutdown = True
        self._web_restart_scheduled = False
        self._stop_web_server()
        self._stop_recording()
        self._stop_camera_worker()
        if self._preview_overlay is not None:
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
