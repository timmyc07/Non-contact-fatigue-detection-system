"""V2 Behavior Alertness Worker — QObject that runs in its own QThread.

Signal pipeline:
    CameraStreamWorker → BGR queue → FatigueWorker (own QThread)
    → MediaPipe Face Landmarker → FatigueEngine
    → FatigueMetrics → Overlay

Uses the same face_landmarker.task model as RppgWorker (shared download).
"""

from __future__ import annotations

import queue
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

_HAS_MP = True
_ANNOTATED_PREVIEW_MAX_FPS = 20.0

from .fatigue_engine import FatigueEngine, FatigueMetrics, FatigueParams
from .frame_queue import get_latest
from .mediapipe_tuning import load_mediapipe_tuning
from rppg.rppg_worker import ensure_face_model, _MODELS_DIR


# ── Drawing constants ────────────────────────────────────────────────────────

# Eye 6-point contour
_EYE_L_IDX = [362, 385, 387, 263, 373, 380]
_EYE_R_IDX = [33,  160, 158, 133, 153, 144]

# Iris (478-pt model): centre + 4 edge points
_IRIS_L_CTR   = 468
_IRIS_L_EDGES = [469, 470, 471, 472]
_IRIS_R_CTR   = 473
_IRIS_R_EDGES = [474, 475, 476, 477]

# Inner brow anchor points
_BROW_L_INNER = 55
_BROW_R_INNER = 285

# Nose anchor points (bridge + tip)
_NOSE_TIP = 1
_NOSE_BRIDGE = [6, 168]

# Outer brow ridge (for drawing the full brow arc)
_BROW_L = [336, 296, 334, 293, 300, 276, 283, 282, 295]
_BROW_R = [107,  66, 105,  63,  70,  46,  53,  52,  65]

# Outer lip contour
_MOUTH_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409,
                291, 375, 321, 405, 314, 17, 84, 181, 91, 146]

# Face oval
_FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172,  58, 132,  93, 234, 127, 162,  21,  54, 103,  67, 109,
]

_STATUS_COLOR = {
    "OK":          (0,   200,   0),
    "CALIBRATING": (180, 180,   0),
    "ALERT":       (0,   165, 255),
    "TIRED":       (0,   165, 255),
    "DROWSY":      (0,    80, 255),
    "MICROSLEEP":  (0,     0, 255),
    "NO_FACE":     (120, 120, 120),
}


def _lm_px(lm, w: int, h: int, idx: int) -> tuple[int, int]:
    return int(lm[idx].x * w), int(lm[idx].y * h)


def _lm_mean_px(lm, w: int, h: int, idxs: list[int]) -> tuple[int, int]:
    pts = np.array([_lm_px(lm, w, h, i) for i in idxs], dtype=np.float64)
    return int(np.mean(pts[:, 0])), int(np.mean(pts[:, 1]))


def _draw_head_pose_axes(
    out: np.ndarray,
    nose_px: tuple[int, int],
    pitch_deg: float,
    yaw_deg: float,
    roll_deg: float,
    scale: int,
) -> None:
    """Draw three coloured head-pose axes at the nose tip (BGR colours)."""
    p = np.radians(-pitch_deg)   # image Y flipped
    y = np.radians(yaw_deg)
    r = np.radians(roll_deg)

    cp, sp = float(np.cos(p)), float(np.sin(p))
    cy, sy = float(np.cos(y)), float(np.sin(y))
    cr, sr = float(np.cos(r)), float(np.sin(r))

    # ZYX rotation matrix (matches solvePnP conventions)
    R = np.array([
        [cy * cr + sy * sp * sr,  -cy * sr + sy * sp * cr,  sy * cp],
        [cp * sr,                   cp * cr,                 -sp    ],
        [-sy * cr + cy * sp * sr,   sy * sr + cy * sp * cr,  cy * cp],
    ], dtype=np.float64)

    nx, ny = nose_px
    # Red = X (right), Green = Y (up), Blue = Z (toward camera)
    for axis_vec, color in [
        (np.array([1, 0, 0]), (0,   50, 220)),
        (np.array([0, 1, 0]), (0,  200,   0)),
        (np.array([0, 0, 1]), (220,  80,   0)),
    ]:
        rv = R @ axis_vec
        tx = int(nx + scale * rv[0])
        ty = int(ny - scale * rv[1])   # negate Y for image coords (down = positive)
        cv2.arrowedLine(out, (nx, ny), (tx, ty), color, 2,
                        tipLength=0.25, line_type=cv2.LINE_AA)


def draw_fatigue_annotations(
    frame: np.ndarray,
    lm: list,
    metrics: FatigueMetrics,
) -> np.ndarray:
    """Draw rich fatigue / behaviour-alertness annotations on the frame."""
    if cv2 is None:
        return frame

    out = frame.copy()
    h, w = out.shape[:2]
    font  = cv2.FONT_HERSHEY_SIMPLEX
    s_col = _STATUS_COLOR.get(metrics.status, (180, 180, 180))

    # ── 1. Face oval ─────────────────────────────────────────────────────────
    oval_pts = np.array([_lm_px(lm, w, h, i) for i in _FACE_OVAL], np.int32)
    cv2.polylines(out, [oval_pts], isClosed=True,
                  color=(60, 60, 60), thickness=1, lineType=cv2.LINE_AA)

    # ── 1b. Nose anchor (tip + bridge) ───────────────────────────────────────
    nose_tip = _lm_px(lm, w, h, _NOSE_TIP)
    nose_bridge = _lm_mean_px(lm, w, h, _NOSE_BRIDGE)
    nose_col = (0, 200, 255) if metrics.nose_speed < 120 else (0, 120, 255)
    cv2.line(out, nose_bridge, nose_tip, nose_col, 1, lineType=cv2.LINE_AA)
    cv2.circle(out, nose_tip, 2, nose_col, -1, lineType=cv2.LINE_AA)
    cv2.putText(
        out,
        f"鼻動:{metrics.nose_speed:.0f}",
        (nose_tip[0] + 4, nose_tip[1] - 4),
        font, 0.34, nose_col, 1, cv2.LINE_AA,
    )

    # ── 2. Brow arcs + inner-brow furrowing indicator ─────────────────────────
    for brow_idxs, inner_idx in [(_BROW_L, _BROW_L_INNER), (_BROW_R, _BROW_R_INNER)]:
        pts = np.array([_lm_px(lm, w, h, i) for i in brow_idxs], np.int32)
        brow_col = (0, 80, 220) if metrics.is_frowning else (80, 80, 160)
        cv2.polylines(out, [pts], isClosed=False,
                      color=brow_col, thickness=1, lineType=cv2.LINE_AA)

    # Inner-brow distance line (highlights furrowing)
    lb = _lm_px(lm, w, h, _BROW_L_INNER)
    rb = _lm_px(lm, w, h, _BROW_R_INNER)
    brow_line_col = (0, 60, 255) if metrics.is_frowning else (60, 60, 120)
    cv2.line(out, lb, rb, brow_line_col, 1, lineType=cv2.LINE_AA)
    if metrics.is_frowning:
        mid = ((lb[0] + rb[0]) // 2, (lb[1] + rb[1]) // 2 - 6)
        cv2.putText(out, "皺眉", mid, font, 0.38, (0, 60, 255), 1, cv2.LINE_AA)

    # ── 3. Eye contours (colour-coded) ────────────────────────────────────────
    # Normal=green, squinting=yellow, PERCLOS alarm=red
    if metrics.is_squinting:
        eye_col = (0, 200, 255)    # yellow-ish
    elif metrics.perclos > 0.20:
        eye_col = (0, 80, 220)     # orange-red alarm
    else:
        eye_col = (40, 200, 80)    # green normal

    for eye_idxs in (_EYE_L_IDX, _EYE_R_IDX):
        pts = np.array([_lm_px(lm, w, h, i) for i in eye_idxs], np.int32)
        cv2.polylines(out, [pts], isClosed=True,
                      color=eye_col, thickness=1, lineType=cv2.LINE_AA)

    # EAR label beside each eye
    l_outer = _lm_px(lm, w, h, 263)
    r_outer = _lm_px(lm, w, h, 33)
    cv2.putText(out, f"{metrics.ear_smooth:.2f}",
                (l_outer[0] + 4, l_outer[1] - 4),
                font, 0.35, eye_col, 1, cv2.LINE_AA)
    cv2.putText(out, f"{metrics.ear_smooth:.2f}",
                (r_outer[0] - 30, r_outer[1] - 4),
                font, 0.35, eye_col, 1, cv2.LINE_AA)
    cv2.putText(out, f"L:{metrics.lid_open_left:.2f}", (l_outer[0] + 4, l_outer[1] + 10),
                font, 0.30, (120, 220, 120), 1, cv2.LINE_AA)
    cv2.putText(out, f"R:{metrics.lid_open_right:.2f}", (r_outer[0] - 30, r_outer[1] + 10),
                font, 0.30, (120, 220, 120), 1, cv2.LINE_AA)

    # ── 4. Iris circles + crosshair ───────────────────────────────────────────
    if metrics.has_iris:
        for ctr_idx, edge_idxs in [(_IRIS_L_CTR, _IRIS_L_EDGES),
                                    (_IRIS_R_CTR, _IRIS_R_EDGES)]:
            cx, cy = _lm_px(lm, w, h, ctr_idx)
            # Radius: mean pixel distance from centre to 4 edge points
            edge_pts = [_lm_px(lm, w, h, ei) for ei in edge_idxs]
            radii = [int(np.hypot(ex - cx, ey - cy)) for ex, ey in edge_pts]
            radius = max(1, int(np.mean(radii)))

            # Outer iris ring
            cv2.circle(out, (cx, cy), radius,
                       (0, 200, 200), 1, lineType=cv2.LINE_AA)
            # Inner pupil approximation (iris centre dot)
            pupil_r = max(1, radius // 3)
            cv2.circle(out, (cx, cy), pupil_r,
                       (0, 255, 220), -1, lineType=cv2.LINE_AA)
            # Crosshair
            arm = radius + 4
            cv2.line(out, (cx - arm, cy), (cx + arm, cy),
                     (0, 180, 160), 1, lineType=cv2.LINE_AA)
            cv2.line(out, (cx, cy - arm), (cx, cy + arm),
                     (0, 180, 160), 1, lineType=cv2.LINE_AA)

        # ── 5. Gaze arrow from nose tip ───────────────────────────────────────
        nx, ny = _lm_px(lm, w, h, 1)
        arrow_len = int(w * 0.08)
        ax = int(nx + metrics.gaze_x * arrow_len)
        ay = int(ny + metrics.gaze_y * arrow_len)
        saccade_col = (0, 50, 255) if metrics.is_saccade else (0, 220, 255)
        cv2.arrowedLine(out, (nx, ny), (ax, ay),
                        saccade_col, 2, tipLength=0.3, line_type=cv2.LINE_AA)

    # ── 6. Head pose 3-axis indicator ─────────────────────────────────────────
    nose_px = _lm_px(lm, w, h, 1)
    axis_scale = int(min(w, h) * 0.13)
    _draw_head_pose_axes(out, nose_px,
                         metrics.head_pitch, metrics.head_yaw, metrics.head_roll,
                         axis_scale)

    # ── 7. Mouth / MAR contour (visible when yawning or MAR > 0.3) ────────────
    if metrics.mar > 0.30 or metrics.mouth_open_ratio > 0.18:
        mouth_pts = np.array([_lm_px(lm, w, h, i) for i in _MOUTH_OUTER], np.int32)
        mouth_col = (0, 50, 255) if metrics.yawn_count > 0 or metrics.mar > 0.55 else (80, 80, 200)
        cv2.polylines(out, [mouth_pts], isClosed=True,
                      color=mouth_col, thickness=1, lineType=cv2.LINE_AA)
        cv2.putText(out, f"口:{metrics.mouth_open_ratio:.2f}", (mouth_pts[0][0] - 8, mouth_pts[0][1] - 8),
                    font, 0.34, mouth_col, 1, cv2.LINE_AA)
        if metrics.mar > 0.55:
            mc = _lm_px(lm, w, h, 13)
            cv2.putText(out, "哈欠", (mc[0] - 12, mc[1] - 6),
                        font, 0.40, (0, 50, 255), 1, cv2.LINE_AA)

    # ── 8. Microsleep / drowsy flash overlay ──────────────────────────────────
    if metrics.status in ("MICROSLEEP", "DROWSY"):
        overlay = out.copy()
        alpha   = 0.22 if metrics.status == "DROWSY" else 0.35
        col     = (0, 30, 180) if metrics.status == "MICROSLEEP" else (0, 0, 160)
        cv2.rectangle(overlay, (0, 0), (w, h), col, -1)
        cv2.addWeighted(overlay, alpha, out, 1 - alpha, 0, out)

    # ── 9. Bottom HUD ─────────────────────────────────────────────────────────
    # Status + key metrics on a semi-transparent dark bar
    hud_h   = 22
    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - hud_h), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.60, out, 0.40, 0, out)

    hud_txt = (
        f"{metrics.status}"
        f"  EAR:{metrics.ear_smooth:.2f}"
        f"  PERCLOS:{metrics.perclos*100:.0f}%"
        f"  眨眼:{metrics.blink_rate_pm:.0f}/min"
    )
    cv2.putText(out, hud_txt, (6, h - 6), font, 0.38, s_col, 1, cv2.LINE_AA)

    # ── 10. Top-right: head pose angles ───────────────────────────────────────
    pose_txt = (
        f"P:{metrics.head_pitch:+.0f}"
        f" Y:{metrics.head_yaw:+.0f}"
        f" R:{metrics.head_roll:+.0f}"
    )
    (pw, ph), _ = cv2.getTextSize(pose_txt, font, 0.38, 1)
    ox = w - pw - 8
    overlay2 = out.copy()
    cv2.rectangle(overlay2, (ox - 4, 2), (w - 2, ph + 10), (0, 0, 0), -1)
    cv2.addWeighted(overlay2, 0.55, out, 0.45, 0, out)
    # Pitch colour warning
    p_col = (0, 60, 220) if metrics.head_pitch < -12.0 else (150, 200, 100)
    cv2.putText(out, pose_txt, (ox, ph + 5), font, 0.38, p_col, 1, cv2.LINE_AA)

    # ── 11. Top-left: alert badges ────────────────────────────────────────────
    alerts: list[tuple[str, tuple]] = []
    if metrics.microsleep_alert:
        alerts.append(("⚠ 微睡眠", (0, 0, 220)))
    if metrics.gaze_mental_fatigue:
        alerts.append(("空洞凝視", (0, 140, 255)))
    if metrics.is_squinting:
        alerts.append((f"瞇眼 {metrics.squint_duration:.0f}s", (0, 190, 255)))
    if metrics.is_frowning:
        alerts.append(("皺眉", (0, 100, 255)))
    if metrics.lid_balance > 0.35:
        alerts.append((f"眼瞼差 {metrics.lid_balance:.2f}", (0, 180, 255)))
    if metrics.mouth_open_ratio > 0.30:
        alerts.append((f"嘴部 {metrics.mouth_open_ratio:.2f}", (0, 140, 255)))
    if metrics.nose_speed > 120.0:
        alerts.append((f"鼻動 {metrics.nose_speed:.0f}", (0, 200, 255)))

    y_off = 4
    for badge_txt, badge_col in alerts:
        (bw, bh), _ = cv2.getTextSize(badge_txt, font, 0.40, 1)
        overlay3 = out.copy()
        cv2.rectangle(overlay3, (0, y_off), (bw + 10, y_off + bh + 6), (0, 0, 0), -1)
        cv2.addWeighted(overlay3, 0.60, out, 0.40, 0, out)
        cv2.putText(out, badge_txt, (5, y_off + bh + 2),
                    font, 0.40, badge_col, 1, cv2.LINE_AA)
        y_off += bh + 10

    # ── 12. PERCLOS heat bar (left edge) ──────────────────────────────────────
    if metrics.calibrated and metrics.perclos > 0.0:
        bar_max_h = h - 40
        bar_h     = int(bar_max_h * min(metrics.perclos / 0.40, 1.0))
        bar_y0    = h - 20 - bar_h
        intensity = int(min(metrics.perclos / 0.40, 1.0) * 255)
        bar_col   = (0, max(0, 180 - intensity), min(255, intensity * 2))
        cv2.rectangle(out, (0, bar_y0), (5, h - 20), bar_col, -1)
        cv2.putText(out, f"{metrics.perclos*100:.0f}%",
                    (7, h - 20), font, 0.32, bar_col, 1, cv2.LINE_AA)

    return out


# ── FatigueWorker ────────────────────────────────────────────────────────────

class FatigueWorker(QObject):
    """Behaviour alertness worker: runs MediaPipe + FatigueEngine in a QThread.

    Parameters
    ----------
    frame_queue : queue.Queue[tuple[float, np.ndarray]]
        Thread-safe queue fed by CameraStreamWorker.  Each item is
        (perf_counter_timestamp, bgr_frame).
    target_fps : float
        Expected frame rate; passed to FatigueEngine for calibration timing.
    params : FatigueParams, optional
        Engine configuration.  Default parameters are used if None.
    """

    metrics_ready:   Signal = Signal(object)         # FatigueMetrics
    frame_annotated: Signal = Signal(QImage)         # annotated preview frame
    face_detected:   Signal = Signal(bool)
    status_changed:  Signal = Signal(str)
    failed:          Signal = Signal(str)
    finished:        Signal = Signal()

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        target_fps: float = 30.0,
        params: Optional[FatigueParams] = None,
    ) -> None:
        super().__init__()
        self._queue      = frame_queue
        self._target_fps = target_fps
        self._params     = params or FatigueParams()
        self._stop       = False

    def request_stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        if not _HAS_MP:
            self.failed.emit("MediaPipe 未安裝。\n請執行：pip install mediapipe")
            self.finished.emit()
            return
        if cv2 is None:
            self.failed.emit("OpenCV 未安裝。")
            self.finished.emit()
            return

        # Download / verify model (shared with rPPG worker)
        try:
            model_path = ensure_face_model(
                _MODELS_DIR,
                status_cb=lambda s: self.status_changed.emit(s),
            )
        except Exception as exc:
            self.failed.emit(f"MediaPipe 模型下載失敗：{exc}")
            self.finished.emit()
            return

        base_opts  = _mp_python.BaseOptions(model_asset_path=str(model_path))
        tuning = load_mediapipe_tuning()
        lm_options = _mp_vision.FaceLandmarkerOptions(
            base_options=base_opts,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=tuning.face_landmarker.min_face_detection_confidence,
            min_face_presence_confidence=tuning.face_landmarker.min_face_presence_confidence,
            min_tracking_confidence=tuning.face_landmarker.min_tracking_confidence,
            num_faces=max(1, int(tuning.face_landmarker.num_faces)),
            running_mode=_mp_vision.RunningMode.VIDEO,
        )

        engine    = FatigueEngine(params=self._params)
        last_face = False
        t_origin: Optional[float] = None
        ts_ms_prev = 0
        last_preview_emit = 0.0
        preview_emit_interval = 1.0 / _ANNOTATED_PREVIEW_MAX_FPS

        self.status_changed.emit("行為警覺引擎就緒，等待幀資料…")

        with _mp_vision.FaceLandmarker.create_from_options(lm_options) as landmarker:
            while not self._stop:
                try:
                    ts, bgr = get_latest(self._queue, timeout=0.1)
                except queue.Empty:
                    continue

                if t_origin is None:
                    t_origin = ts

                # Monotonically increasing ms timestamp (MediaPipe VIDEO mode requirement)
                ts_ms      = max(ts_ms_prev + 1, int((ts - t_origin) * 1000))
                ts_ms_prev = ts_ms

                rgb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(rgb),
                )

                try:
                    result = landmarker.detect_for_video(mp_img, ts_ms)
                except Exception:
                    continue

                has_face = bool(result.face_landmarks)
                if has_face != last_face:
                    self.face_detected.emit(has_face)
                    last_face = has_face

                blendshapes = result.face_blendshapes[0] if result.face_blendshapes else None

                annotated = bgr.copy()

                if has_face:
                    lm      = result.face_landmarks[0]
                    h_px, w_px = bgr.shape[:2]
                    metrics = engine.step(lm, w_px, h_px, ts, blendshapes=blendshapes)
                    metrics.face_detected = True

                    annotated = draw_fatigue_annotations(annotated, lm, metrics)

                    if not metrics.calibrated:
                        pct = int(metrics.calib_progress * 100)
                        self.status_changed.emit(f"校準中… {pct}%")
                    else:
                        self.status_changed.emit(
                            f"{metrics.status}  "
                            f"EAR {metrics.ear_smooth:.2f}  "
                            f"PERCLOS {metrics.perclos*100:.0f}%  "
                            f"眨眼 {metrics.blink_count}"
                        )
                else:
                    metrics = engine.on_no_face()
                    self.status_changed.emit("未偵測到臉部…")

                self.metrics_ready.emit(metrics)

                if ts - last_preview_emit >= preview_emit_interval:
                    last_preview_emit = ts
                    rgb_ann  = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    rgb_ann  = np.ascontiguousarray(rgb_ann)
                    fh, fw   = rgb_ann.shape[:2]
                    qimg     = QImage(
                        rgb_ann.data, fw, fh,
                        rgb_ann.strides[0],
                        QImage.Format.Format_RGB888,
                    )
                    self.frame_annotated.emit(qimg.copy())

        self.finished.emit()
