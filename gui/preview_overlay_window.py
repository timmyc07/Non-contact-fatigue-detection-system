"""Floating overlay: camera preview + FPS + rPPG / HRV metrics panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import (
    QColor, QFont, QImage, QMouseEvent, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from rppg.rppg_worker import RppgMetrics
    from gui.fatigue_engine import FatigueMetrics
    from gui.fatigue_scorer import FusedFatigueScore


# ── Waveform mini-widget ─────────────────────────────────────────────────────

class _WaveformWidget(QWidget):
    """Draws a normalised signal waveform using QPainter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._data: list[float] = []
        self._color = QColor("#40c057")

    def set_data(self, data: list[float]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#0d1117"))

        if len(self._data) < 2:
            painter.setPen(QColor("#495057"))
            painter.drawText(
                QRect(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "等待脈搏信號…",
            )
            painter.end()
            return

        data = self._data
        mn, mx = min(data), max(data)
        span = mx - mn
        if span < 1e-9:
            painter.end()
            return

        n = len(data)
        pen = QPen(self._color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        prev = None
        for i, v in enumerate(data):
            x = int(i / (n - 1) * (w - 1))
            y = int((1.0 - (v - mn) / span) * (h - 6) + 3)
            pt = QPoint(x, y)
            if prev is not None:
                painter.drawLine(prev, pt)
            prev = pt

        painter.end()


# ── Horizontal score bar widget ──────────────────────────────────────────────

class _ScoreBar(QWidget):
    """Thin coloured progress bar with a percentage label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value: float = 0.0
        self._color = QColor("#40c057")

    def set_value(self, v: float, color: QColor | None = None) -> None:
        self._value = max(0.0, min(1.0, v))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1e2228"))
        painter.drawRoundedRect(0, 0, w, h, 3, 3)

        # Fill
        fill_w = int(self._value * w)
        if fill_w > 0:
            painter.setBrush(self._color)
            painter.drawRoundedRect(0, 0, fill_w, h, 3, 3)

        # Percentage text
        pct_txt = f"{self._value * 100:.0f}%"
        painter.setPen(QColor("#dee2e6"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRect(0, 0, w, h),
            Qt.AlignmentFlag.AlignCenter,
            pct_txt,
        )
        painter.end()


# ── Large circular gauge widget ───────────────────────────────────────────────

class _GaugeWidget(QWidget):
    """Ring gauge showing overall fatigue score (0-1)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(110, 110)
        self._value: float = 0.0
        self._color = QColor("#40c057")
        self._label = "清醒"

    def set_value(self, v: float, color: QColor, label: str) -> None:
        self._value  = max(0.0, min(1.0, v))
        self._color  = color
        self._label  = label
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, r = w // 2, h // 2, min(w, h) // 2 - 8

        # Background ring
        pen = QPen(QColor("#1e2228"), 10)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(cx - r, cy - r, r * 2, r * 2, 225 * 16, -270 * 16)

        # Value arc
        if self._value > 0.0:
            span = int(-270 * 16 * self._value)
            pen2 = QPen(self._color, 10)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen2)
            painter.drawArc(cx - r, cy - r, r * 2, r * 2, 225 * 16, span)

        # Centre: percentage
        painter.setPen(self._color)
        pct_font = QFont("Segoe UI", 16, QFont.Weight.Bold)
        painter.setFont(pct_font)
        painter.drawText(
            QRect(0, cy - 20, w, 24),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._value * 100:.0f}",
        )
        # Unit
        painter.setPen(QColor("#868e96"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRect(0, cy + 6, w, 16),
            Qt.AlignmentFlag.AlignCenter,
            "%",
        )
        # Label below gauge
        painter.setPen(self._color)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(
            QRect(0, h - 18, w, 18),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )
        painter.end()


# ── Main overlay window ──────────────────────────────────────────────────────

class PreviewOverlayWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("鏡頭預覽 Overlay")
        self.setMinimumSize(480, 320)
        self.resize(640, 460)
        self._locked = True

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(
            "background-color: rgba(20,22,26,230);"
            "border-radius: 8px 8px 0 0;"
            "border: 1px solid #2f3640; border-bottom: none;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 6, 10, 6)
        self._lbl_fps = QLabel("FPS：—")
        self._lbl_fps.setStyleSheet("color: #74c0fc; font-weight: 600; font-size: 14px;")
        self._lbl_title = QLabel("RGB 預覽")
        self._lbl_title.setStyleSheet("color: #adb5bd; font-size: 12px;")
        hl.addWidget(self._lbl_fps)
        hl.addStretch(1)
        hl.addWidget(self._lbl_title)
        root.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────────
        body = QFrame()
        body.setStyleSheet("background-color: #0d0f12; border: 1px solid #2f3640; border-top: none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(8)

        # Video area — fixed height; grows with window when no panels are shown
        self._lbl_video = QLabel()
        self._lbl_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_video.setFixedHeight(240)
        self._lbl_video.setStyleSheet(
            "background-color: #14181d; border-radius: 6px; color: #495057;"
        )
        self._lbl_video.setText("等待影像…")
        bl.addWidget(self._lbl_video)

        # ── rPPG metrics panel (hidden until enabled) ────────────────────────
        self._rppg_panel = QFrame()
        self._rppg_panel.setStyleSheet(
            "background-color: #111418; border-radius: 6px; border: 1px solid #2a2f3a;"
        )
        self._rppg_panel.hide()
        rp = QVBoxLayout(self._rppg_panel)
        rp.setContentsMargins(12, 10, 12, 10)
        rp.setSpacing(6)

        # Row 1: BPM (large) + face status
        bpm_row = QHBoxLayout()
        lbl_bpm_cap = QLabel("❤  心率")
        lbl_bpm_cap.setStyleSheet("color: #868e96; font-size: 11px;")
        self._lbl_bpm = QLabel("— BPM")
        self._lbl_bpm.setStyleSheet(
            "color: #ff6b6b; font-size: 22px; font-weight: bold;"
        )
        self._lbl_face_status = QLabel("未偵測到臉部")
        self._lbl_face_status.setStyleSheet("color: #868e96; font-size: 11px;")
        bpm_row.addWidget(lbl_bpm_cap)
        bpm_row.addWidget(self._lbl_bpm)
        bpm_row.addStretch(1)
        bpm_row.addWidget(self._lbl_face_status)
        rp.addLayout(bpm_row)

        # Warmup progress bar
        warm_row = QHBoxLayout()
        lbl_warm = QLabel("暖機")
        lbl_warm.setStyleSheet("color: #868e96; font-size: 11px; min-width: 32px;")
        self._bar_warmup = QProgressBar()
        self._bar_warmup.setRange(0, 100)
        self._bar_warmup.setValue(0)
        self._bar_warmup.setTextVisible(False)
        self._bar_warmup.setFixedHeight(6)
        self._bar_warmup.setStyleSheet(
            "QProgressBar{background:#1e2228; border-radius:3px;}"
            "QProgressBar::chunk{background:#4dabf7; border-radius:3px;}"
        )
        self._lbl_warmup_pct = QLabel("0%")
        self._lbl_warmup_pct.setStyleSheet("color: #4dabf7; font-size: 11px; min-width: 30px;")
        warm_row.addWidget(lbl_warm)
        warm_row.addWidget(self._bar_warmup, 1)
        warm_row.addWidget(self._lbl_warmup_pct)
        rp.addLayout(warm_row)

        # Row 2: HRV metrics
        hrv_row = QHBoxLayout()
        hrv_row.setSpacing(20)
        self._lbl_rmssd = self._metric_label("RMSSD", "— ms")
        self._lbl_sdnn  = self._metric_label("SDNN",  "— ms")
        self._lbl_lfhf  = self._metric_label("LF/HF", "—")
        self._lbl_sqi   = self._metric_label("SQI",   "—")
        for w in (self._lbl_rmssd, self._lbl_sdnn, self._lbl_lfhf, self._lbl_sqi):
            hrv_row.addWidget(w)
        hrv_row.addStretch(1)
        rp.addLayout(hrv_row)

        # Row 3: Stress + HRV confidence
        stress_row = QHBoxLayout()
        stress_row.setSpacing(20)
        self._lbl_stress   = self._metric_label("壓力指數", "— (—)")
        self._lbl_hrv_conf = self._metric_label("HRV 信心", "LOW")
        stress_row.addWidget(self._lbl_stress)
        stress_row.addWidget(self._lbl_hrv_conf)
        stress_row.addStretch(1)
        rp.addLayout(stress_row)

        # Waveform
        lbl_wf_cap = QLabel("帶通脈搏波形（POS）")
        lbl_wf_cap.setStyleSheet("color: #495057; font-size: 10px; margin-top: 2px;")
        rp.addWidget(lbl_wf_cap)
        self._waveform = _WaveformWidget()
        rp.addWidget(self._waveform)

        bl.addWidget(self._rppg_panel)

        # ── Fatigue / Behaviour Alertness panel (hidden until enabled) ────────
        self._fatigue_panel = QFrame()
        self._fatigue_panel.setStyleSheet(
            "background-color: #111418; border-radius: 6px; border: 1px solid #2a3040;"
        )
        self._fatigue_panel.hide()
        fp = QVBoxLayout(self._fatigue_panel)
        fp.setContentsMargins(12, 10, 12, 10)
        fp.setSpacing(6)

        # Title row: status badge + calibration bar
        fat_title_row = QHBoxLayout()
        lbl_fat_icon = QLabel("🔍 行為警覺")
        lbl_fat_icon.setStyleSheet("color: #74c0fc; font-size: 11px; font-weight: 600;")
        self._lbl_fat_status = QLabel("—")
        self._lbl_fat_status.setStyleSheet(
            "color: #adb5bd; font-size: 13px; font-weight: bold;"
        )
        fat_title_row.addWidget(lbl_fat_icon)
        fat_title_row.addStretch(1)
        fat_title_row.addWidget(self._lbl_fat_status)
        fp.addLayout(fat_title_row)

        # Calibration bar
        fat_calib_row = QHBoxLayout()
        lbl_fat_calib = QLabel("校準")
        lbl_fat_calib.setStyleSheet("color: #868e96; font-size: 10px; min-width: 30px;")
        self._bar_fat_calib = QProgressBar()
        self._bar_fat_calib.setRange(0, 100)
        self._bar_fat_calib.setValue(0)
        self._bar_fat_calib.setTextVisible(False)
        self._bar_fat_calib.setFixedHeight(5)
        self._bar_fat_calib.setStyleSheet(
            "QProgressBar{background:#1e2228;border-radius:2px;}"
            "QProgressBar::chunk{background:#63e6be;border-radius:2px;}"
        )
        fat_calib_row.addWidget(lbl_fat_calib)
        fat_calib_row.addWidget(self._bar_fat_calib, 1)
        fp.addLayout(fat_calib_row)

        # Row: EAR + Blinks + PERCLOS + fatigue level
        ear_row = QHBoxLayout()
        ear_row.setSpacing(20)
        self._lbl_ear      = self._metric_label("EAR",     "—")
        self._lbl_blinks   = self._metric_label("眨眼/分",  "—")
        self._lbl_perclos  = self._metric_label("PERCLOS", "—")
        self._lbl_fat_lvl  = self._metric_label("疲勞指數", "—")
        for w in (self._lbl_ear, self._lbl_blinks, self._lbl_perclos, self._lbl_fat_lvl):
            ear_row.addWidget(w)
        ear_row.addStretch(1)
        fp.addLayout(ear_row)

        # Row: micro-expressions (3 items)
        micro_row = QHBoxLayout()
        micro_row.setSpacing(16)
        lbl_micro_cap = QLabel("微表情 ›")
        lbl_micro_cap.setStyleSheet(
            "color: #868e96; font-size: 10px; min-width: 52px;"
        )
        self._lbl_squint = QLabel("瞇眼: —")
        self._lbl_squint.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_frown  = QLabel("皺眉: —")
        self._lbl_frown.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_iris   = QLabel("虹膜比: —")
        self._lbl_iris.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_nose   = QLabel("鼻動: —")
        self._lbl_nose.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_mouth  = QLabel("嘴開: —")
        self._lbl_mouth.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_lidbal = QLabel("眼瞼差: —")
        self._lbl_lidbal.setStyleSheet("color: #dee2e6; font-size: 11px;")
        micro_row.addWidget(lbl_micro_cap)
        micro_row.addWidget(self._lbl_squint)
        micro_row.addWidget(self._lbl_frown)
        micro_row.addWidget(self._lbl_iris)
        micro_row.addWidget(self._lbl_nose)
        micro_row.addWidget(self._lbl_mouth)
        micro_row.addWidget(self._lbl_lidbal)
        micro_row.addStretch(1)
        fp.addLayout(micro_row)

        # Row: gaze dynamics (3 items)
        gaze_row = QHBoxLayout()
        gaze_row.setSpacing(16)
        lbl_gaze_cap = QLabel("注視 ›")
        lbl_gaze_cap.setStyleSheet(
            "color: #868e96; font-size: 10px; min-width: 52px;"
        )
        self._lbl_gaze_stab = QLabel("穩定度: —")
        self._lbl_gaze_stab.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_fixation  = QLabel("凝視: —")
        self._lbl_fixation.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_saccade   = QLabel("掃視: —/分")
        self._lbl_saccade.setStyleSheet("color: #dee2e6; font-size: 11px;")
        gaze_row.addWidget(lbl_gaze_cap)
        gaze_row.addWidget(self._lbl_gaze_stab)
        gaze_row.addWidget(self._lbl_fixation)
        gaze_row.addWidget(self._lbl_saccade)
        gaze_row.addStretch(1)
        fp.addLayout(gaze_row)

        # Row: head pose + microsleep + yawn (split into 2 rows for clarity)
        head_row = QHBoxLayout()
        head_row.setSpacing(16)
        lbl_head_cap = QLabel("頭部 ›")
        lbl_head_cap.setStyleSheet(
            "color: #868e96; font-size: 10px; min-width: 52px;"
        )
        self._lbl_pitch      = QLabel("Pitch: —")
        self._lbl_pitch.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_yaw_roll   = QLabel("Yaw/Roll: —")
        self._lbl_yaw_roll.setStyleSheet("color: #868e96; font-size: 11px;")
        self._lbl_microsleep = QLabel("微睡眠: 0")
        self._lbl_microsleep.setStyleSheet("color: #dee2e6; font-size: 11px;")
        self._lbl_yawn       = QLabel("哈欠: 0")
        self._lbl_yawn.setStyleSheet("color: #868e96; font-size: 11px;")
        head_row.addWidget(lbl_head_cap)
        head_row.addWidget(self._lbl_pitch)
        head_row.addWidget(self._lbl_yaw_roll)
        head_row.addWidget(self._lbl_microsleep)
        head_row.addWidget(self._lbl_yawn)
        head_row.addStretch(1)
        fp.addLayout(head_row)

        bl.addWidget(self._fatigue_panel)

        # ── Fused Fatigue Score panel (shown when BOTH rPPG + fatigue active) ─
        self._fused_panel = QFrame()
        self._fused_panel.setStyleSheet(
            "background-color: #0e1117; border-radius: 6px;"
            "border: 1px solid #3d2f10;"
        )
        self._fused_panel.hide()
        fp2 = QHBoxLayout(self._fused_panel)
        fp2.setContentsMargins(12, 10, 12, 10)
        fp2.setSpacing(16)

        # Left: ring gauge
        self._gauge = _GaugeWidget()
        fp2.addWidget(self._gauge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Right: breakdown + trend
        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        # Title + trend row
        fused_title_row = QHBoxLayout()
        lbl_fused_title = QLabel("綜合疲勞度")
        lbl_fused_title.setStyleSheet(
            "color: #ffa94d; font-size: 12px; font-weight: 600; border: none;"
        )
        self._lbl_fused_trend = QLabel("→ 穩定")
        self._lbl_fused_trend.setStyleSheet("color: #868e96; font-size: 11px; border: none;")
        fused_title_row.addWidget(lbl_fused_title)
        fused_title_row.addStretch(1)
        fused_title_row.addWidget(self._lbl_fused_trend)
        right_col.addLayout(fused_title_row)

        # rPPG sub-bar
        rppg_bar_row = QHBoxLayout()
        rppg_bar_row.setSpacing(8)
        lbl_rppg_bar = QLabel("❤  rPPG × 40%")
        lbl_rppg_bar.setStyleSheet(
            "color: #ff6b6b; font-size: 10px; min-width: 100px; border: none;"
        )
        self._bar_rppg_sub = _ScoreBar()
        rppg_bar_row.addWidget(lbl_rppg_bar)
        rppg_bar_row.addWidget(self._bar_rppg_sub, 1)
        right_col.addLayout(rppg_bar_row)

        # Behaviour sub-bar
        beh_bar_row = QHBoxLayout()
        beh_bar_row.setSpacing(8)
        lbl_beh_bar = QLabel("👁  行為 × 60%")
        lbl_beh_bar.setStyleSheet(
            "color: #74c0fc; font-size: 10px; min-width: 100px; border: none;"
        )
        self._bar_beh_sub = _ScoreBar()
        beh_bar_row.addWidget(lbl_beh_bar)
        beh_bar_row.addWidget(self._bar_beh_sub, 1)
        right_col.addLayout(beh_bar_row)

        # Component detail row
        self._lbl_fused_detail = QLabel("等待資料…")
        self._lbl_fused_detail.setStyleSheet(
            "color: #6c757d; font-size: 10px; border: none;"
        )
        self._lbl_fused_detail.setWordWrap(True)
        right_col.addWidget(self._lbl_fused_detail)

        right_col.addStretch(1)
        fp2.addLayout(right_col, 1)

        bl.addWidget(self._fused_panel)
        bl.addStretch(1)

        root.addWidget(body)

        self._drag_pos = None
        self._preview_on = True

    # ── Helper ──────────────────────────────────────────────────────────────

    @staticmethod
    def _metric_label(caption: str, initial: str) -> QLabel:
        lbl = QLabel(f"<span style='color:#868e96;font-size:10px;'>{caption}</span><br>"
                     f"<span style='color:#dee2e6;font-size:12px;font-weight:600;'>{initial}</span>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        return lbl

    @staticmethod
    def _set_metric(lbl: QLabel, caption: str, value: str) -> None:
        lbl.setText(
            f"<span style='color:#868e96;font-size:10px;'>{caption}</span><br>"
            f"<span style='color:#dee2e6;font-size:12px;font-weight:600;'>{value}</span>"
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def show_rppg_panel(self, visible: bool) -> None:
        """Show or hide the rPPG metrics panel below the video."""
        self._rppg_panel.setVisible(visible)
        self._resize_to_content()

    # Panel height constants (approximate, based on row counts + margins)
    _H_VIDEO    = 240
    _H_HEADER   = 36
    _H_BODY_PAD = 28   # 10 top + 10 bottom + 8 spacing below video
    _H_RPPG     = 182  # BPM + warmup + HRV + stress + waveform
    _H_FATIGUE  = 175  # title + calib + EAR + micro + gaze + head
    _H_FUSED    = 130  # gauge row

    def _resize_to_content(self) -> None:
        h = self._H_HEADER + self._H_BODY_PAD + self._H_VIDEO
        if self._rppg_panel.isVisible():
            h += self._H_RPPG + 8
        if self._fatigue_panel.isVisible():
            h += self._H_FATIGUE + 8
        if self._fused_panel.isVisible():
            h += self._H_FUSED + 8
        self.resize(self.width(), h)

    def refresh_layout(self) -> None:
        self._resize_to_content()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.updateGeometry()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh_layout)

    def update_rppg_metrics(self, metrics: "RppgMetrics") -> None:
        """Update all rPPG metric labels from a RppgMetrics instance."""
        # Face status
        if metrics.face_detected:
            self._lbl_face_status.setText("臉部偵測中 ✓")
            self._lbl_face_status.setStyleSheet("color: #40c057; font-size: 11px;")
        else:
            self._lbl_face_status.setText("未偵測到臉部")
            self._lbl_face_status.setStyleSheet("color: #868e96; font-size: 11px;")

        # BPM
        if metrics.bpm > 0:
            bpm_color = "#ff6b6b" if metrics.bpm > 100 else "#40c057" if metrics.bpm > 50 else "#4dabf7"
            self._lbl_bpm.setText(f"{metrics.bpm:.0f} BPM")
            self._lbl_bpm.setStyleSheet(
                f"color: {bpm_color}; font-size: 22px; font-weight: bold;"
            )
        else:
            self._lbl_bpm.setText("— BPM")
            self._lbl_bpm.setStyleSheet("color: #868e96; font-size: 22px; font-weight: bold;")

        # Warmup progress
        pct = int(metrics.warmup_progress * 100)
        self._bar_warmup.setValue(pct)
        self._lbl_warmup_pct.setText(f"{pct}%")

        # HRV
        self._set_metric(self._lbl_rmssd, "RMSSD", f"{metrics.rmssd:.1f} ms" if metrics.rmssd > 0 else "—")
        self._set_metric(self._lbl_sdnn,  "SDNN",  f"{metrics.sdnn:.1f} ms"  if metrics.sdnn  > 0 else "—")
        self._set_metric(self._lbl_lfhf,  "LF/HF", f"{metrics.lf_hf:.2f}"   if metrics.lf_hf > 0 else "—")
        self._set_metric(self._lbl_sqi,   "SQI",   f"{metrics.sqi:.2f}"     if metrics.sqi   > 0 else "—")

        # Stress
        prob_str = f"{metrics.stress_prob:.0%}" if metrics.stress_prob > 0 else "—"
        self._set_metric(self._lbl_stress, "壓力指數",
                         f"{prob_str}  ({metrics.stress_status})")

        # HRV confidence
        conf_color = {"HIGH": "#40c057", "MEDIUM": "#ffd43b", "LOW": "#ff6b6b"}.get(
            metrics.hrv_confidence, "#868e96"
        )
        self._lbl_hrv_conf.setText(
            f"<span style='color:#868e96;font-size:10px;'>HRV 信心</span><br>"
            f"<span style='color:{conf_color};font-size:12px;font-weight:600;'>"
            f"{metrics.hrv_confidence}</span>"
        )

        # Waveform
        if metrics.waveform:
            self._waveform.set_data(metrics.waveform)

    def show_fused_panel(self, visible: bool) -> None:
        """Show or hide the combined fatigue score panel."""
        self._fused_panel.setVisible(visible)
        self._resize_to_content()

    def update_fused_score(self, score: "FusedFatigueScore") -> None:
        """Refresh the fused fatigue gauge + breakdown bars."""
        # Gauge colour from BGR → QColor (RGB)
        b, g, r = score.color_bgr
        gauge_col = QColor(r, g, b)

        self._gauge.set_value(score.score, gauge_col, score.level)

        # rPPG sub-bar colour
        rppg_col = QColor(
            int(255 * score.rppg_sub),
            int(255 * (1.0 - score.rppg_sub)),
            80,
        )
        self._bar_rppg_sub.set_value(
            score.rppg_sub,
            rppg_col if score.rppg_available else QColor("#495057"),
        )

        # Behaviour sub-bar colour
        beh_col = QColor(
            int(255 * score.behavior_sub),
            int(255 * (1.0 - score.behavior_sub)),
            120,
        )
        self._bar_beh_sub.set_value(
            score.behavior_sub,
            beh_col if score.behavior_available else QColor("#495057"),
        )

        # Trend label
        td = score.trend * 100   # convert to percentage points
        if td > 2:
            trend_col, trend_txt = "#ff6b6b", f"↑ +{td:.1f}pt/30s"
        elif td < -2:
            trend_col, trend_txt = "#40c057", f"↓ {td:.1f}pt/30s"
        else:
            trend_col, trend_txt = "#868e96", "→ 穩定"
        self._lbl_fused_trend.setText(trend_txt)
        self._lbl_fused_trend.setStyleSheet(
            f"color: {trend_col}; font-size: 11px; border: none;"
        )

        # Component detail — show 2 highest contributing behaviour factors
        factors: list[tuple[float, str]] = [
            (score.beh_perclos_score,     f"PERCLOS {score.beh_perclos_score*100:.0f}%"),
            (score.beh_squint_score,      f"瞇眼 {score.beh_squint_score*100:.0f}%"),
            (score.beh_microsleep_score,  f"微睡眠 {score.beh_microsleep_score*100:.0f}%"),
            (score.beh_gaze_score,        f"凝視 {score.beh_gaze_score*100:.0f}%"),
            (score.beh_frown_score,       f"皺眉 {score.beh_frown_score*100:.0f}%"),
        ]
        factors.sort(reverse=True)
        top_two = [t for _, t in factors[:2] if _ > 0.05]
        rppg_txt = (
            f"壓力 {score.rppg_stress_score*100:.0f}%  "
            f"心率偏差 {score.rppg_bpm_score*100:.0f}%"
        ) if score.rppg_available else "rPPG 暖機中"
        detail = ("  |  ".join(top_two) if top_two else "行為指標正常") + f"\n{rppg_txt}"
        self._lbl_fused_detail.setText(detail)

    def show_fatigue_panel(self, visible: bool) -> None:
        """Show or hide the behaviour alertness metrics panel."""
        self._fatigue_panel.setVisible(visible)
        self._resize_to_content()

    def update_fatigue_metrics(self, metrics: "FatigueMetrics") -> None:
        """Refresh all fatigue metric labels from a FatigueMetrics instance."""
        # Status badge colour
        _col = {
            "OK":          "#40c057",
            "CALIBRATING": "#ffd43b",
            "ALERT":       "#74c0fc",
            "TIRED":       "#ffa94d",
            "DROWSY":      "#ff6b6b",
            "MICROSLEEP":  "#e03131",
            "NO_FACE":     "#868e96",
        }
        status_col = _col.get(metrics.status, "#adb5bd")
        status_zh = {
            "OK": "正常", "CALIBRATING": "校準中",
            "ALERT": "早期警示", "TIRED": "疲勞",
            "DROWSY": "嗜睡", "MICROSLEEP": "微睡眠！",
            "NO_FACE": "未偵測臉部",
        }.get(metrics.status, metrics.status)
        self._lbl_fat_status.setText(status_zh)
        self._lbl_fat_status.setStyleSheet(
            f"color: {status_col}; font-size: 13px; font-weight: bold;"
        )

        # Calibration bar
        pct = int(metrics.calib_progress * 100)
        self._bar_fat_calib.setValue(pct)

        # EAR / blinks / PERCLOS / fatigue level
        self._set_metric(self._lbl_ear,     "EAR",     f"{metrics.ear_smooth:.3f}" if metrics.face_detected else "—")
        self._set_metric(self._lbl_blinks,  "眨眼/分",  f"{metrics.blink_rate_pm:.0f}" if metrics.face_detected else "—")
        perclos_str = f"{metrics.perclos*100:.1f}%" if metrics.face_detected else "—"
        self._set_metric(self._lbl_perclos, "PERCLOS", perclos_str)
        fat_str = f"{metrics.fatigue_level*100:.0f}%" if metrics.face_detected else "—"
        self._set_metric(self._lbl_fat_lvl, "疲勞指數", fat_str)

        # Micro-expressions
        if metrics.is_squinting:
            sq_col = "#ffa94d"
            sq_txt = f"瞇眼: {metrics.squint_duration:.0f}s ⚠"
        else:
            sq_col = "#495057"
            sq_txt = "瞇眼: 無"
        self._lbl_squint.setText(sq_txt)
        self._lbl_squint.setStyleSheet(f"color: {sq_col}; font-size: 11px;")

        if metrics.is_frowning:
            fr_col = "#ffa94d"
            fr_txt = f"皺眉: ⚠ ({metrics.brow_dist_norm:.2f})"
        else:
            fr_col = "#495057"
            fr_txt = "皺眉: 無"
        self._lbl_frown.setText(fr_txt)
        self._lbl_frown.setStyleSheet(f"color: {fr_col}; font-size: 11px;")

        if metrics.has_iris:
            trend_sym = "▲" if metrics.iris_ratio_trend > 0.001 else ("▼" if metrics.iris_ratio_trend < -0.001 else "─")
            self._lbl_iris.setText(f"虹膜比: {metrics.iris_ratio:.2f} {trend_sym}")
            self._lbl_iris.setStyleSheet("color: #dee2e6; font-size: 11px;")
        else:
            self._lbl_iris.setText("虹膜比: —")
            self._lbl_iris.setStyleSheet("color: #495057; font-size: 11px;")

        if metrics.face_detected:
            nose_col = "#40c057" if metrics.nose_speed < 120.0 else "#ff6b6b"
            self._lbl_nose.setText(f"鼻動: {metrics.nose_speed:.0f}")
            self._lbl_nose.setStyleSheet(f"color: {nose_col}; font-size: 11px;")

            mouth_col = "#ffa94d" if metrics.mouth_open_ratio > 0.30 else "#dee2e6"
            self._lbl_mouth.setText(f"嘴開: {metrics.mouth_open_ratio:.2f}")
            self._lbl_mouth.setStyleSheet(f"color: {mouth_col}; font-size: 11px;")

            lid_col = "#ffa94d" if metrics.lid_balance > 0.35 else "#dee2e6"
            self._lbl_lidbal.setText(f"眼瞼差: {metrics.lid_balance:.2f}")
            self._lbl_lidbal.setStyleSheet(f"color: {lid_col}; font-size: 11px;")
        else:
            self._lbl_nose.setText("鼻動: —")
            self._lbl_nose.setStyleSheet("color: #495057; font-size: 11px;")
            self._lbl_mouth.setText("嘴開: —")
            self._lbl_mouth.setStyleSheet("color: #495057; font-size: 11px;")
            self._lbl_lidbal.setText("眼瞼差: —")
            self._lbl_lidbal.setStyleSheet("color: #495057; font-size: 11px;")

        # Gaze dynamics
        stab = metrics.gaze_stability_index
        stab_col = "#40c057" if stab > 0.7 else "#ffd43b" if stab > 0.4 else "#ff6b6b"
        self._lbl_gaze_stab.setText(f"穩定度: {stab:.2f}")
        self._lbl_gaze_stab.setStyleSheet(f"color: {stab_col}; font-size: 11px;")

        fix_dur = metrics.fixation_duration
        if metrics.gaze_mental_fatigue:
            fix_col = "#ff6b6b"
            fix_txt = f"凝視: {fix_dur:.0f}s ⚠"
        elif fix_dur > 5.0:
            fix_col = "#ffd43b"
            fix_txt = f"凝視: {fix_dur:.0f}s"
        else:
            fix_col = "#dee2e6"
            fix_txt = f"凝視: {fix_dur:.1f}s"
        self._lbl_fixation.setText(fix_txt)
        self._lbl_fixation.setStyleSheet(f"color: {fix_col}; font-size: 11px;")

        sac_freq = metrics.saccade_freq_pm
        sac_col  = "#ffd43b" if sac_freq < 2.0 and metrics.face_detected else "#dee2e6"
        self._lbl_saccade.setText(f"掃視: {sac_freq:.0f}/分")
        self._lbl_saccade.setStyleSheet(f"color: {sac_col}; font-size: 11px;")

        # Head pose
        pitch = metrics.head_pitch
        pitch_col = "#ff6b6b" if pitch < -12.0 else "#dee2e6"
        self._lbl_pitch.setText(f"Pitch: {pitch:+.0f}°")
        self._lbl_pitch.setStyleSheet(f"color: {pitch_col}; font-size: 11px;")

        self._lbl_yaw_roll.setText(f"Y:{metrics.head_yaw:+.0f}° R:{metrics.head_roll:+.0f}°")

        ms_col = "#ff6b6b" if metrics.microsleep_count > 0 else "#dee2e6"
        self._lbl_microsleep.setText(f"微睡眠: {metrics.microsleep_count}")
        self._lbl_microsleep.setStyleSheet(f"color: {ms_col}; font-size: 11px;")

        yawn_col = "#ffa94d" if metrics.yawn_count > 0 else "#868e96"
        self._lbl_yawn.setText(f"哈欠: {metrics.yawn_count}")
        self._lbl_yawn.setStyleSheet(f"color: {yawn_col}; font-size: 11px;")

    def apply_lock_state(self, locked: bool) -> None:
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)

    def set_opacity(self, alpha: float) -> None:
        self.setWindowOpacity(max(0.15, min(1.0, float(alpha))))

    def set_preview_visible(self, visible: bool) -> None:
        self._preview_on = visible
        if not visible:
            self._lbl_video.clear()
            self._lbl_video.setText("預覽已關閉")
            self._lbl_video.setStyleSheet(
                "background-color: #14181d; border-radius: 6px; color: #868e96; font-size: 13px;"
            )
        else:
            self._lbl_video.clear()
            self._lbl_video.setText("等待影像…")
            self._lbl_video.setStyleSheet(
                "background-color: #14181d; border-radius: 6px; color: #495057;"
            )

    def set_metrics_visible(self, visible: bool) -> None:
        """Legacy: controls the old metrics placeholder (kept for compatibility)."""
        pass

    def update_frame(self, image: QImage) -> None:
        if not self._preview_on:
            return
        pix = QPixmap.fromImage(image)
        scaled = pix.scaled(
            self._lbl_video.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._lbl_video.setPixmap(scaled)
        self._lbl_video.setStyleSheet("background-color: #14181d; border-radius: 6px;")

    def update_fps(self, fps: float) -> None:
        self._lbl_fps.setText(f"FPS：{fps:4.1f}")

    def update_camera_info(self, codec: str, w: int, h: int, cam_name: str = "") -> None:
        res_str = f"{w}×{h}" if w > 0 and h > 0 else "—"
        label = cam_name.split("]", 1)[-1].strip() if "]" in cam_name else cam_name
        self._lbl_title.setText(f"{label}  {res_str}  [{codec}]")

    # ── Drag support ────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._locked:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._locked:
            return super().mouseMoveEvent(event)
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
