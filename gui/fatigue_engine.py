"""V2 Behavior Alertness Engine — pure computation, no UI code.

Architecture (Frame Interleaving):
    HIGH_FREQ  (every frame)   : EAR, blinks, gaze, iris/pupil, squinting
    LOW_FREQ   (every N frames): head pose (solvePnP), brow furrowing, PERCLOS
    LATE_STAGE (low weight)    : yawn (MAR)

V2 vs V1 changes:
    + Squinting detection (sustained sub-threshold EAR without blink)
    + Brow furrowing (inner-brow distance normalised to inter-ocular baseline)
    + Pupillometry (iris-radius / eye-height ratio + trend EMA)
    + Saccadic velocity & fixation duration
    - Yaw / Roll weight reduced (multi-screen observers turn head normally)
    ~ Pitch strictly monitored for nod-microsleep (solvePnP runs LOW_FREQ)
    ~ Yawn weight demoted to late-stage indicator only
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import cv2 as _cv2

from .mediapipe_tuning import CalibrationStore, MediaPipeTuning, load_mediapipe_tuning

_CV2_OK = True
log = logging.getLogger(__name__)

# ── Landmark indices (MediaPipe 478-pt FaceLandmarker) ───────────────────────

# EAR — 6-point eye model (same as V1)
RIGHT_EYE_IDX = [33, 160, 158, 133, 153, 144]
LEFT_EYE_IDX  = [362, 385, 387, 263, 373, 380]

# Iris landmarks (478-pt model, indices 468-477)
LEFT_IRIS_CTR   = 468        # left iris centre
LEFT_IRIS_EDGES = [469, 470, 471, 472]   # top / right / bottom / left
RIGHT_IRIS_CTR  = 473
RIGHT_IRIS_EDGES = [474, 475, 476, 477]

# Eye inner/outer corners & top/bottom (for iris-ratio denominator)
LEFT_EYE_INNER  = 133
LEFT_EYE_OUTER  = 33
LEFT_EYE_TOP    = 159
LEFT_EYE_BOT    = 145
RIGHT_EYE_INNER = 362
RIGHT_EYE_OUTER = 263
RIGHT_EYE_TOP   = 386
RIGHT_EYE_BOT   = 374

# Brow furrowing (inner brow anchors)
LEFT_BROW_INNER  = 55     # inner corner of left brow
RIGHT_BROW_INNER = 285    # inner corner of right brow

# MAR mouth landmarks
MAR_LM_IDX = [61, 82, 13, 312, 291, 316, 14, 86]

# Head pose solvePnP
HEAD_POSE_LM_IDX = [1, 199, 33, 263, 61, 291]
_HEAD_POSE_3D = np.array([
    [  0.0,    0.0,    0.0],   # 1:   鼻尖
    [  0.0, -330.0,  -65.0],   # 199: 下巴
    [-225.0,  170.0, -135.0],  # 33:  左眼外角
    [ 225.0,  170.0, -135.0],  # 263: 右眼外角
    [-150.0, -150.0, -125.0],  # 61:  左嘴角
    [ 150.0, -150.0, -125.0],  # 291: 右嘴角
], dtype=np.float64)
_HEAD_POSE_DIST = np.zeros((4, 1), dtype=np.float64)
_HEAD_POSE_CAM_CACHE: dict = {}

# Face bounding helpers
FOREHEAD_IDX = 10
CHIN_IDX     = 152
FACE_OVAL_IDXS = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172,  58, 132,  93, 234, 127, 162,  21,  54, 103,  67, 109,
]

NOSE_TIP_IDX  = 1
NOSE_BRIDGE_IDX = [6, 168]
LEFT_CHEEK_IDX  = 234
RIGHT_CHEEK_IDX = 454


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _dist(p1: tuple, p2: tuple) -> float:
    return float(np.hypot(p1[0] - p2[0], p1[1] - p2[1]))


def _p(lm: Any, w: int, h: int, idx: int) -> tuple[int, int]:
    return (int(lm[idx].x * w), int(lm[idx].y * h))


def _pf(lm: Any, idx: int) -> tuple[float, float]:
    """Normalised (0-1) coordinate."""
    return float(lm[idx].x), float(lm[idx].y)


def _mean_pf(lm: Any, idxs: list[int]) -> tuple[float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for idx in idxs:
        x, y = _pf(lm, idx)
        xs.append(x)
        ys.append(y)
    return float(np.mean(xs)), float(np.mean(ys))


def _mean_p(lm: Any, w: int, h: int, idxs: list[int]) -> tuple[float, float]:
    pts = [_p(lm, w, h, idx) for idx in idxs]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return float(np.mean(xs)), float(np.mean(ys))


def _blendshape_map(blendshapes: Any | None) -> dict[str, float]:
    if blendshapes is None:
        return {}
    if isinstance(blendshapes, dict):
        out: dict[str, float] = {}
        for k, v in blendshapes.items():
            try:
                out[str(k).lower()] = float(v)
            except Exception:
                continue
        return out

    out: dict[str, float] = {}
    try:
        for item in blendshapes:
            key = (
                getattr(item, "category_name", None)
                or getattr(item, "display_name", None)
                or ""
            )
            if not key:
                continue
            try:
                out[str(key).lower()] = float(getattr(item, "score", 0.0) or 0.0)
            except Exception:
                continue
    except Exception:
        return {}
    return out


def _bs(bs: dict[str, float], *names: str) -> float:
    return max((float(bs.get(name.lower(), 0.0)) for name in names), default=0.0)


def _norm_blend(raw: float, base: float) -> float:
    if raw <= 0.0:
        return 0.0
    denom = max(1e-6, 1.0 - base)
    return _clamp((raw - base) / denom, 0.0, 1.0)


def _clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


def eye_aspect_ratio(pts6: list[tuple[int, int]]) -> float:
    p1, p2, p3, p4, p5, p6 = pts6
    h_dist = _dist(p1, p4)
    if h_dist < 1.0:
        return 0.0
    return (_dist(p2, p6) + _dist(p3, p5)) / (2.0 * h_dist)


def mouth_aspect_ratio(pts8: list[tuple[int, int]]) -> float:
    p1, p2, p3, p4, p5, p6, p7, p8 = pts8
    horiz = _dist(p1, p5)
    if horiz < 1.0:
        return 0.0
    return (_dist(p2, p8) + _dist(p3, p7) + _dist(p4, p6)) / (2.0 * horiz)


def solve_head_pose(lm: Any, w: int, h: int) -> Optional[tuple[float, float, float]]:
    """solvePnP → (pitch, yaw, roll) degrees.  pitch > 0 = looking up."""
    if not _CV2_OK:
        return None
    try:
        img_pts = np.array(
            [[lm[i].x * w, lm[i].y * h] for i in HEAD_POSE_LM_IDX],
            dtype=np.float64,
        )
        key = (w, h)
        if key not in _HEAD_POSE_CAM_CACHE:
            f = float(w)
            _HEAD_POSE_CAM_CACHE[key] = np.array(
                [[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1]], dtype=np.float64
            )
        ok, rvec, _ = _cv2.solvePnP(
            _HEAD_POSE_3D, img_pts, _HEAD_POSE_CAM_CACHE[key], _HEAD_POSE_DIST,
            flags=_cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return None
        rmat, _ = _cv2.Rodrigues(rvec)
        angles, _, _, _, _, _ = _cv2.RQDecomp3x3(rmat)
        pitch = float(angles[0])
        if pitch > 90.0:
            pitch -= 180.0
        elif pitch < -90.0:
            pitch += 180.0
        return -pitch, float(angles[1]), float(angles[2])
    except Exception:
        return None


# ── Parameters ───────────────────────────────────────────────────────────────

@dataclass
class FatigueParams:
    # Frame interleaving
    pose_stride: int   = 3     # run solvePnP every N frames
    brow_stride: int   = 3     # brow furrowing every N frames

    # EAR / calibration
    calib_sec: float         = 5.0
    min_calib_samples: int   = 20
    ear_ema_alpha: float     = 0.40
    thresh_ratio: float      = 0.75
    base_th_default: float   = 0.18
    calib_ear_min: float     = 0.15
    closed_open_hyst: float  = 1.06

    # Blink timing
    blink_min_sec: float     = 0.08
    blink_max_sec: float     = 0.45
    blink_grace_frames: int  = 3

    # Quality gates
    min_face_area_ratio_blink:   float = 0.03
    roll_limit_blink:            float = 40.0
    min_face_area_ratio_fatigue: float = 0.06
    roll_limit_fatigue:          float = 25.0
    yaw_ratio_limit_fatigue:     float = 1.45
    nose_speed_limit_fatigue:    float = 240.0

    # PERCLOS
    perclos_window_sec: float  = 60.0
    tired_perclos_th:   float  = 0.25
    long_closed_sec:    float  = 1.5
    use_stable_face_area: bool = True
    tighten_strength_fatigue: float = 0.25
    min_th_factor_fatigue:    float = 0.60

    # Head pose (V2: focus on Pitch, relax Yaw/Roll)
    pitch_eye_gate_deg:       float = 10.0
    pitch_up_deg:             float = 22.0
    pitch_up_sustained_sec:   float = 1.0
    head_pitch_down_th:       float = -15.0
    head_microsleep_sec:      float = 1.5
    dz_ref_ema_alpha:         float = 0.005

    # Yawn (V2: late-stage only, low weight)
    mar_yawn_th:       float  = 0.60
    mar_yawn_dur_sec:  float  = 1.5
    mouth_open_yawn_th: float  = 0.24
    mouth_open_noise_th: float = 0.30

    # Gaze (V2: stability + saccade + fixation)
    gaze_window_sec:      float  = 3.0
    gaze_fixed_std_th:    float  = 0.015
    gaze_fixed_alert_sec: float  = 5.0
    saccade_velocity_th:  float  = 0.08   # normalised units / s
    saccade_window_sec:   float  = 60.0   # window for saccade frequency

    # V2 — Squinting (sustained sub-threshold EAR without full blink)
    squint_ear_ratio:   float  = 1.35    # squint_th = base_th * this ratio
    squint_min_sec:     float  = 3.0     # must persist this long
    lid_balance_gate_th: float  = 0.35

    # V2 — Brow furrowing
    brow_furrow_ratio:  float  = 0.85    # trigger when norm_dist < baseline * this
    brow_calib_frames:  int    = 120     # frames to establish brow baseline

    # V2 — Pupillometry
    iris_ratio_ema_alpha: float = 0.10   # EMA for iris_ratio trend

    # V2 — Blendshape calibration / thresholds
    blend_calib_sec: float = 4.0
    blend_min_samples: int = 24
    blend_ema_alpha: float = 0.22
    blend_blink_gate: float = 0.20
    blend_squint_gate: float = 0.18
    blend_brow_gate: float = 0.18
    blend_jaw_gate: float = 0.20


# ── Output metrics dataclass ─────────────────────────────────────────────────

@dataclass
class FatigueMetrics:
    # Overall
    face_detected:  bool  = False
    calibrated:     bool  = False
    status:         str   = "NO_FACE"   # NO_FACE | CALIBRATING | OK | TIRED | DROWSY | MICROSLEEP
    fatigue_level:  float = 0.0         # composite 0-1
    early_warning:  bool  = False       # cognitive / micro-expression based

    # Eye basics
    ear:             float = 0.0
    ear_smooth:      float = 0.0
    blink_count:     int   = 0
    perclos:         float = 0.0
    blink_rate_pm:   float = 0.0        # blinks per minute (60-s sliding window)

    # V2 micro-expressions
    is_squinting:      bool  = False
    squint_duration:   float = 0.0
    is_frowning:       bool  = False
    brow_dist_norm:    float = 1.0      # 1 = baseline; < brow_furrow_ratio → frowning
    lid_open_left:     float = 0.0
    lid_open_right:    float = 0.0
    lid_balance:       float = 0.0

    # V2 pupillometry
    iris_ratio:        float = 0.0      # iris_radius / (eye_height/2)
    iris_ratio_trend:  float = 0.0      # positive = dilating (higher load / alertness)
    nose_speed:        float = 0.0
    blend_eye_blink:   float = 0.0
    blend_eye_squint:  float = 0.0
    blend_brow_down:   float = 0.0
    blend_jaw_open:    float = 0.0

    # Gaze basics
    gaze_x:            float = 0.0
    gaze_y:            float = 0.0
    gaze_stability_index: float = 0.0
    gaze_mental_fatigue:  bool  = False

    # V2 gaze dynamics
    saccadic_velocity:    float = 0.0
    is_saccade:           bool  = False
    fixation_duration:    float = 0.0
    saccade_freq_pm:      float = 0.0   # saccades per minute (60-s window)

    # Head pose (V2: Pitch-focused)
    head_pitch:       float = 0.0
    head_yaw:         float = 0.0
    head_roll:        float = 0.0
    microsleep_alert: bool  = False
    microsleep_count: int   = 0

    # Yawn (V2: late-stage, low weight)
    mar:          float = 0.0
    yawn_detected: bool = False
    yawn_count:   int   = 0
    mouth_open_ratio: float = 0.0
    mouth_blend_stretch: float = 0.0
    quality_score: float = 0.0
    blend_calib_progress: float = 0.0

    # Debug / display
    has_iris:     bool  = False
    calib_progress: float = 0.0   # 0-1


# ── EyeCognitiveModule ───────────────────────────────────────────────────────

class EyeCognitiveModule:
    """EAR, blinks, PERCLOS + V2: squinting, brow furrowing, pupillometry."""

    def __init__(self, p: FatigueParams) -> None:
        self.p = p
        self.reset(full=True)

    def reset(self, *, full: bool = True) -> None:
        p = self.p
        self._ear_ema: Optional[float] = None

        # Calibration
        self.calibrated         = False
        self._calib_start       = time.perf_counter()
        self._calib_ears: list[float] = []
        self.base_ear_th        = p.base_th_default
        self._calib_logged      = False

        # Blink
        self.blink_count        = 0 if full else getattr(self, "blink_count", 0)
        self._blink_closed      = False
        self._blink_enter_t: Optional[float] = None
        self._blink_ok_miss     = 0
        self._blink_timestamps: deque[float] = deque()  # for per-minute rate
        self.blink_rate_pm      = 0.0

        # Fatigue / PERCLOS
        self._fatigue_closed    = False
        self._fat_enter_t: Optional[float] = None
        self._closed_intervals: deque = deque()
        self._closed_start: Optional[float] = None
        self._closed_quality    = 1.0
        self.last_perclos       = 0.0

        # Squinting (V2)
        self._squint_enter_t: Optional[float] = None
        self.squint_duration    = 0.0
        self.is_squinting       = False

        # Brow furrowing (V2)
        self._brow_calib_samples: list[float] = []
        self._brow_baseline: Optional[float] = None
        self.brow_dist_norm     = 1.0
        self.is_frowning        = False
        self._brow_logged       = False

        self.lid_open_left      = 0.0
        self.lid_open_right     = 0.0
        self.lid_balance        = 0.0

        # Pupillometry (V2)
        self._iris_ratio_ema: Optional[float] = None
        self.iris_ratio         = 0.0
        self.iris_ratio_trend   = 0.0   # positive = dilating
        self.blend_eye_blink    = 0.0
        self.blend_eye_squint   = 0.0
        self.blend_brow_down    = 0.0
        self.blend_calib_progress = 0.0
        self._blend_calibrated = False
        self._blend_samples: dict[str, list[float]] = {
            "blink": [],
            "squint": [],
            "brow": [],
        }
        self._blend_baseline: dict[str, float] = {
            "blink": 0.0,
            "squint": 0.0,
            "brow": 0.0,
        }

        # Nose speed (quality gate)
        self._prev_nose: Optional[tuple] = None
        self._prev_t: Optional[float] = None
        self.nose_speed = 0.0

    # ── PERCLOS helpers ──────────────────────────────────────────────────────

    def _open_interval(self, t: float, q: float) -> None:
        if self._closed_start is None:
            self._closed_start   = t
            self._closed_quality = q

    def _close_interval(self, t: float) -> None:
        if self._closed_start is not None:
            self._closed_intervals.append((self._closed_start, t, self._closed_quality))
            self._closed_start = None

    def _perclos(self, t_now: float) -> float:
        w = self.p.perclos_window_sec
        cutoff = t_now - w
        while self._closed_intervals and self._closed_intervals[0][1] <= cutoff:
            self._closed_intervals.popleft()
        closed = sum(
            (min(b, t_now) - max(a, cutoff)) * q
            for a, b, q in self._closed_intervals
        )
        if self._closed_start is not None:
            closed += (t_now - max(self._closed_start, cutoff)) * self._closed_quality
        elapsed = max(1.0, min(t_now - self._calib_start - self.p.calib_sec, w))
        return _clamp(closed / elapsed, 0.0, 1.0)

    # ── Main per-frame step ───────────────────────────────────────────────────

    def step(
        self,
        lm: Any, w: int, h: int,
        t_now: float,
        blink_ok: bool, fatigue_ok: bool,
        fatigue_quality: float,
        blendshapes: Any | None = None,
        run_brow: bool = True,
    ) -> None:
        p = self.p
        bs = _blendshape_map(blendshapes)
        raw_eye_blink = _bs(bs, "eye_blink_left", "eye_blink_right")
        raw_eye_squint = _bs(bs, "eye_squint_left", "eye_squint_right")
        raw_brow_down = _bs(bs, "brow_down_left", "brow_down_right", "brow_inner_up")
        self.blend_calib_progress = _clamp(
            (t_now - self._calib_start) / max(p.blend_calib_sec, 1e-6), 0.0, 1.0
        )
        if not self._blend_calibrated:
            if fatigue_quality > 0.55 and blink_ok:
                self._blend_samples["blink"].append(raw_eye_blink)
                self._blend_samples["squint"].append(raw_eye_squint)
                self._blend_samples["brow"].append(raw_brow_down)
            if (
                self.blend_calib_progress >= 1.0
                and min(len(v) for v in self._blend_samples.values()) >= p.blend_min_samples
            ):
                self._blend_baseline = {
                    key: float(np.median(vals)) if vals else 0.0
                    for key, vals in self._blend_samples.items()
                }
                self._blend_calibrated = True
                log.info(
                    "Blendshape 校準完成：blink=%.3f squint=%.3f brow=%.3f",
                    self._blend_baseline["blink"],
                    self._blend_baseline["squint"],
                    self._blend_baseline["brow"],
                )
        self.blend_eye_blink = _norm_blend(raw_eye_blink, self._blend_baseline["blink"])
        self.blend_eye_squint = _norm_blend(raw_eye_squint, self._blend_baseline["squint"])
        self.blend_brow_down = _norm_blend(raw_brow_down, self._blend_baseline["brow"])

        # ── EAR ─────────────────────────────────────────────────────────────
        l_pts = [_p(lm, w, h, i) for i in LEFT_EYE_IDX]
        r_pts = [_p(lm, w, h, i) for i in RIGHT_EYE_IDX]
        ear = (eye_aspect_ratio(l_pts) + eye_aspect_ratio(r_pts)) / 2.0
        alpha = p.ear_ema_alpha
        self._ear_ema = ear if self._ear_ema is None else alpha * ear + (1 - alpha) * self._ear_ema
        ear_s = self._ear_ema

        # ── Calibration ─────────────────────────────────────────────────────
        calib_elapsed = t_now - self._calib_start
        if not self.calibrated:
            if blink_ok and ear_s > p.calib_ear_min:
                self._calib_ears.append(ear_s)
            if calib_elapsed >= p.calib_sec:
                if len(self._calib_ears) >= p.min_calib_samples:
                    self.base_ear_th = float(np.median(self._calib_ears)) * p.thresh_ratio
                else:
                    self.base_ear_th = p.base_th_default
                self.calibrated = True
                self._closed_intervals.clear()
                self._closed_start = None
                self.last_perclos  = 0.0
                if not self._calib_logged:
                    log.info(
                        "EAR 校準完成：base_ear_th=%.3f, samples=%d",
                        self.base_ear_th,
                        len(self._calib_ears),
                    )
                    self._calib_logged = True
        calib_progress = _clamp(calib_elapsed / p.calib_sec, 0.0, 1.0)

        # Thresholds
        close_blink  = self.base_ear_th
        open_blink   = close_blink * p.closed_open_hyst
        close_fat    = self.base_ear_th
        open_fat     = close_fat * p.closed_open_hyst
        squint_th    = self.base_ear_th * p.squint_ear_ratio

        # ── Blink state machine ──────────────────────────────────────────────
        if self.calibrated:
            if blink_ok:
                self._blink_ok_miss = 0
                if not self._blink_closed:
                    if ear < close_blink:
                        self._blink_closed  = True
                        self._blink_enter_t = t_now
                else:
                    if ear_s > open_blink:
                        self._blink_closed = False
                        if self._blink_enter_t is not None:
                            dur = t_now - self._blink_enter_t
                            if p.blink_min_sec <= dur <= p.blink_max_sec:
                                self.blink_count += 1
                                self._blink_timestamps.append(t_now)
                        self._blink_enter_t = None
            else:
                if self._blink_closed:
                    self._blink_ok_miss += 1
                    if self._blink_ok_miss > p.blink_grace_frames:
                        self._blink_closed  = False
                        self._blink_enter_t = None
                        self._blink_ok_miss = 0
                else:
                    self._blink_ok_miss = 0

        # Blink rate per minute (60-s sliding window)
        cutoff60 = t_now - 60.0
        while self._blink_timestamps and self._blink_timestamps[0] < cutoff60:
            self._blink_timestamps.popleft()
        self.blink_rate_pm = float(len(self._blink_timestamps))

        # ── Fatigue / PERCLOS ────────────────────────────────────────────────
        long_closed = False
        fat_dur = 0.0
        if self.calibrated and fatigue_ok:
            if not self._fatigue_closed:
                if ear_s < close_fat:
                    self._fatigue_closed = True
                    self._fat_enter_t    = t_now
                    self._open_interval(t_now, fatigue_quality)
            else:
                if ear_s > open_fat:
                    self._fatigue_closed = False
                    self._close_interval(t_now)
                    self._fat_enter_t    = None
            if self._fatigue_closed and self._fat_enter_t:
                fat_dur = t_now - self._fat_enter_t
                if fat_dur >= p.long_closed_sec:
                    long_closed = True
            self.last_perclos = self._perclos(t_now)
        else:
            self._close_interval(t_now)
            self._fatigue_closed = False
            self._fat_enter_t    = None

        # Store for external retrieval
        self.ear            = ear
        self.ear_smooth     = ear_s
        self.long_closed    = long_closed
        self.fat_dur        = fat_dur
        self.calib_progress = calib_progress

        # Explicit eyelid openness and asymmetry
        left_w = abs(lm[LEFT_EYE_OUTER].x - lm[LEFT_EYE_INNER].x) + 1e-6
        right_w = abs(lm[RIGHT_EYE_OUTER].x - lm[RIGHT_EYE_INNER].x) + 1e-6
        self.lid_open_left = abs(lm[LEFT_EYE_TOP].y - lm[LEFT_EYE_BOT].y) / left_w
        self.lid_open_right = abs(lm[RIGHT_EYE_TOP].y - lm[RIGHT_EYE_BOT].y) / right_w
        avg_lid = (self.lid_open_left + self.lid_open_right) / 2.0
        self.lid_balance = abs(self.lid_open_left - self.lid_open_right) / (avg_lid + 1e-6)

        # ── V2: Squinting detection ───────────────────────────────────────────
        # Non-blink sustained low EAR: squint_th > ear_s > 0 (not a full blink)
        if self.calibrated and blink_ok:
            if (
                close_blink < ear_s < squint_th
                and not self._blink_closed
                and self.lid_balance < p.lid_balance_gate_th
                and self.blend_eye_blink < p.blend_blink_gate
            ):
                if self._squint_enter_t is None:
                    self._squint_enter_t = t_now
                self.squint_duration = t_now - self._squint_enter_t
                self.is_squinting = self.squint_duration >= p.squint_min_sec
            else:
                self._squint_enter_t = None
                self.squint_duration = 0.0
                self.is_squinting    = False
        else:
            self._squint_enter_t = None
            self.squint_duration = 0.0
            self.is_squinting    = False

        # ── V2: Brow furrowing ───────────────────────────────────────────────
        if run_brow:
            l_brow = _pf(lm, LEFT_BROW_INNER)
            r_brow = _pf(lm, RIGHT_BROW_INNER)
            l_eye  = _pf(lm, LEFT_EYE_OUTER)
            r_eye  = _pf(lm, RIGHT_EYE_OUTER)
            inter_ocular = _dist(
                (l_eye[0], l_eye[1]), (r_eye[0], r_eye[1])
            ) + 1e-6
            raw_brow_dist = _dist(
                (l_brow[0], l_brow[1]), (r_brow[0], r_brow[1])
            )
            norm = raw_brow_dist / inter_ocular

            if self._brow_baseline is None:
                self._brow_calib_samples.append(norm)
                if len(self._brow_calib_samples) >= p.brow_calib_frames:
                    self._brow_baseline = float(np.median(self._brow_calib_samples))
                    if not self._brow_logged:
                        log.info(
                            "眉距基準已建立：baseline=%.3f, samples=%d",
                            self._brow_baseline,
                            len(self._brow_calib_samples),
                        )
                        self._brow_logged = True
            else:
                self.brow_dist_norm = _clamp(
                    norm / (self._brow_baseline + 1e-6), 0.0, 2.0
                )
                self.is_frowning = (
                    self.brow_dist_norm < p.brow_furrow_ratio
                    or self.blend_brow_down > p.blend_brow_gate
                )

        # ── V2: Pupillometry ─────────────────────────────────────────────────
        has_iris = len(lm) >= 478
        if has_iris:
            # Iris radius from centre to 4 edge points (normalised coords)
            l_ctr  = _pf(lm, LEFT_IRIS_CTR)
            l_rad  = float(np.mean([
                _dist(l_ctr, _pf(lm, e)) for e in LEFT_IRIS_EDGES
            ]))
            r_ctr  = _pf(lm, RIGHT_IRIS_CTR)
            r_rad  = float(np.mean([
                _dist(r_ctr, _pf(lm, e)) for e in RIGHT_IRIS_EDGES
            ]))
            # Eye height in normalised coords
            l_h = abs(lm[LEFT_EYE_TOP].y  - lm[LEFT_EYE_BOT].y)  + 1e-6
            r_h = abs(lm[RIGHT_EYE_TOP].y - lm[RIGHT_EYE_BOT].y) + 1e-6
            l_iris_ratio = l_rad / (l_h / 2.0)
            r_iris_ratio = r_rad / (r_h / 2.0)
            iris_ratio   = (l_iris_ratio + r_iris_ratio) / 2.0

            a = p.iris_ratio_ema_alpha
            prev = self._iris_ratio_ema
            new_ema = iris_ratio if prev is None else a * iris_ratio + (1 - a) * prev
            self._iris_ratio_ema = new_ema
            self.iris_ratio_trend = (
                float(new_ema - prev) if prev is not None else 0.0
            )
            self.iris_ratio = iris_ratio
        self.has_iris = has_iris


# ── GazeTrackingModule ───────────────────────────────────────────────────────

class GazeTrackingModule:
    """Iris gaze position + V2: saccadic velocity, fixation duration, mental fatigue."""

    def __init__(self, p: FatigueParams) -> None:
        self.p = p
        self.reset()

    def reset(self) -> None:
        p = self.p
        self._history: deque  = deque()   # (t, gx, gy)
        self._saccade_times: deque = deque()
        self._prev_gaze: Optional[tuple[float, float]] = None
        self._prev_gaze_t: Optional[float] = None
        self._fixation_start: Optional[float] = None
        self._gaze_fixed_start: Optional[float] = None
        # outputs
        self.gaze_x              = 0.0
        self.gaze_y              = 0.0
        self.gaze_stability_index = 0.0
        self.gaze_mental_fatigue  = False
        self.saccadic_velocity   = 0.0
        self.is_saccade          = False
        self.fixation_duration   = 0.0
        self.saccade_freq_pm     = 0.0

    def step(self, lm: Any, t_now: float, has_iris: bool) -> None:
        p = self.p
        if not has_iris:
            self._prev_gaze   = None
            self._prev_gaze_t = None
            self._fixation_start = None
            self._gaze_fixed_start = None
            self.gaze_mental_fatigue = False
            return

        # ── Gaze position ────────────────────────────────────────────────────
        l_cx = (lm[LEFT_EYE_INNER].x  + lm[LEFT_EYE_OUTER].x)  / 2.0
        l_ew = abs(lm[LEFT_EYE_OUTER].x  - lm[LEFT_EYE_INNER].x)  + 1e-6
        r_cx = (lm[RIGHT_EYE_INNER].x + lm[RIGHT_EYE_OUTER].x) / 2.0
        r_ew = abs(lm[RIGHT_EYE_OUTER].x - lm[RIGHT_EYE_INNER].x) + 1e-6
        l_cy = (lm[LEFT_EYE_TOP].y  + lm[LEFT_EYE_BOT].y)  / 2.0
        l_eh = abs(lm[LEFT_EYE_BOT].y  - lm[LEFT_EYE_TOP].y)  + 1e-6
        r_cy = (lm[RIGHT_EYE_TOP].y + lm[RIGHT_EYE_BOT].y) / 2.0
        r_eh = abs(lm[RIGHT_EYE_BOT].y - lm[RIGHT_EYE_TOP].y) + 1e-6

        gx = ((lm[LEFT_IRIS_CTR].x  - l_cx) / l_ew +
              (lm[RIGHT_IRIS_CTR].x - r_cx) / r_ew) / 2.0
        gy = ((lm[LEFT_IRIS_CTR].y  - l_cy) / l_eh +
              (lm[RIGHT_IRIS_CTR].y - r_cy) / r_eh) / 2.0
        self.gaze_x, self.gaze_y = gx, gy
        self._history.append((t_now, gx, gy))

        # ── Sliding window trim ───────────────────────────────────────────────
        cutoff = t_now - p.gaze_window_sec
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        # ── Gaze stability index ──────────────────────────────────────────────
        gaze_is_fixed = False
        if len(self._history) >= 10:
            arr = np.array(self._history)
            std = float(np.sqrt(np.var(arr[:, 1]) + np.var(arr[:, 2])))
            self.gaze_stability_index = _clamp(
                1.0 - std / (p.gaze_fixed_std_th * 4.0), 0.0, 1.0
            )
            gaze_is_fixed = std < p.gaze_fixed_std_th
        else:
            self.gaze_stability_index = 0.0

        # ── V2: Saccadic velocity ─────────────────────────────────────────────
        if self._prev_gaze is not None and self._prev_gaze_t is not None:
            dt = t_now - self._prev_gaze_t
            if dt > 1e-4:
                displacement = float(np.hypot(gx - self._prev_gaze[0],
                                               gy - self._prev_gaze[1]))
                self.saccadic_velocity = displacement / dt
                self.is_saccade = self.saccadic_velocity > p.saccade_velocity_th
                if self.is_saccade:
                    self._saccade_times.append(t_now)
        self._prev_gaze   = (gx, gy)
        self._prev_gaze_t = t_now

        # Saccade frequency (per minute, 60-s window)
        s_cutoff = t_now - p.saccade_window_sec
        while self._saccade_times and self._saccade_times[0] < s_cutoff:
            self._saccade_times.popleft()
        elapsed_sac = min(t_now - (self._saccade_times[0]
                                   if self._saccade_times else t_now) + 1e-3,
                          p.saccade_window_sec)
        self.saccade_freq_pm = len(self._saccade_times) / (elapsed_sac / 60.0 + 1e-9)

        # ── V2: Fixation duration ─────────────────────────────────────────────
        if not self.is_saccade:
            if self._fixation_start is None:
                self._fixation_start = t_now
            self.fixation_duration = t_now - self._fixation_start
        else:
            self._fixation_start   = None
            self.fixation_duration = 0.0

        # ── Mental fatigue (空洞凝視) ─────────────────────────────────────────
        # Trigger when gaze is fixed AND saccade frequency drops very low
        low_saccades = self.saccade_freq_pm < 1.0   # less than 1 saccade/min = unusual
        if gaze_is_fixed or (self.fixation_duration > 10.0 and low_saccades):
            if self._gaze_fixed_start is None:
                self._gaze_fixed_start = t_now
            if (t_now - self._gaze_fixed_start) >= p.gaze_fixed_alert_sec:
                self.gaze_mental_fatigue = True
        else:
            self._gaze_fixed_start   = None
            self.gaze_mental_fatigue = False


# ── HeadMouthModule ──────────────────────────────────────────────────────────

class HeadMouthModule:
    """Head pose (Pitch-focused) + MAR / yawn (late-stage, low weight)."""

    def __init__(self, p: FatigueParams) -> None:
        self.p = p
        self.reset(full=True)

    def reset(self, *, full: bool = True) -> None:
        self.head_pitch = 0.0
        self.head_yaw   = 0.0
        self.head_roll  = 0.0
        self.mar        = 0.0
        self.mouth_blend_stretch = 0.0

        self._pitch_calib: list[float] = []
        self._pitch_offset              = 0.0
        self._pitch_calibrated          = False
        self._pitch_up_start: Optional[float] = None
        self._pitch_down_start: Optional[float] = None
        self._microsleep_fired          = False
        self.microsleep_count = 0 if full else getattr(self, "microsleep_count", 0)

        self._yawn_open_start: Optional[float] = None
        self._yawn_fired                = False
        self.yawn_count = 0 if full else getattr(self, "yawn_count", 0)
        self.mouth_open_ratio = 0.0
        self.mouth_blend_stretch = 0.0
        self._mouth_blend_calibrated = False
        self._mouth_blend_samples: list[float] = []
        self._mouth_blend_baseline = 0.0

    def step(
        self,
        lm: Any, w: int, h: int,
        t_now: float,
        blendshapes: Any | None = None,
        fatigue_quality: float = 1.0,
        blend_calib_progress: float = 0.0,
        run_pose: bool = True,
    ) -> tuple[bool, bool]:
        """Returns (microsleep_alert, yawn_detected)."""
        p = self.p
        bs = _blendshape_map(blendshapes)

        # ── Head pose (LOW_FREQ) ─────────────────────────────────────────────
        if run_pose:
            pose = solve_head_pose(lm, w, h)
            if pose is not None:
                self.head_pitch, self.head_yaw, self.head_roll = pose
                if not self._pitch_calibrated:
                    self._pitch_calib.append(self.head_pitch)
                    if len(self._pitch_calib) >= 60:
                        offset = float(np.median(self._pitch_calib))
                        self._pitch_offset      = _clamp(offset, -20.0, 20.0)
                        self._pitch_calibrated  = True

        pitch_rel = self.head_pitch - self._pitch_offset

        # Pitch-up guard (V2: still needed to suppress EAR during strong upward look)
        if pitch_rel > p.pitch_up_deg:
            if self._pitch_up_start is None:
                self._pitch_up_start = t_now
        else:
            self._pitch_up_start = None
        pitch_up_sustained = (
            self._pitch_up_start is not None
            and (t_now - self._pitch_up_start) >= p.pitch_up_sustained_sec
        )

        # Microsleep: Pitch nod (strictly below threshold)
        microsleep_alert = False
        if pitch_rel < p.head_pitch_down_th:
            if self._pitch_down_start is None:
                self._pitch_down_start = t_now
                self._microsleep_fired = False
            elif (not self._microsleep_fired
                  and (t_now - self._pitch_down_start) >= p.head_microsleep_sec):
                microsleep_alert       = True
                self.microsleep_count += 1
                self._microsleep_fired = True
        else:
            self._pitch_down_start = None
            self._microsleep_fired = False

        # ── MAR / Yawn (late-stage, low weight) ─────────────────────────────
        mar_pts = [_p(lm, w, h, i) for i in MAR_LM_IDX]
        self.mar = mouth_aspect_ratio(mar_pts)
        mouth_w = _dist(_p(lm, w, h, 61), _p(lm, w, h, 291)) + 1e-6
        mouth_gap = _dist(_p(lm, w, h, 13), _p(lm, w, h, 14))
        self.mouth_open_ratio = mouth_gap / mouth_w
        mouth_blend_raw = _bs(bs, "mouth_stretch_left", "mouth_stretch_right", "jaw_open")
        if not self._mouth_blend_calibrated:
            if self.mouth_open_ratio < p.mouth_open_noise_th and fatigue_quality > 0.55:
                self._mouth_blend_samples.append(mouth_blend_raw)
            if (
                blend_calib_progress >= 1.0
                and len(self._mouth_blend_samples) >= p.blend_min_samples
            ):
                self._mouth_blend_baseline = float(np.median(self._mouth_blend_samples))
                self._mouth_blend_calibrated = True
                log.info(
                    "嘴部 blendshape 校準完成：baseline=%.3f",
                    self._mouth_blend_baseline,
                )
        self.mouth_blend_stretch = _norm_blend(mouth_blend_raw, self._mouth_blend_baseline)
        yawn_detected = False
        if (
            self.mar > p.mar_yawn_th
            and self.mouth_open_ratio > p.mouth_open_yawn_th
            and self.mouth_blend_stretch > p.blend_jaw_gate
        ):
            if self._yawn_open_start is None:
                self._yawn_open_start = t_now
                self._yawn_fired      = False
            elif (not self._yawn_fired
                  and (t_now - self._yawn_open_start) >= p.mar_yawn_dur_sec):
                yawn_detected        = True
                self.yawn_count     += 1
                self._yawn_fired     = True
        else:
            self._yawn_open_start = None
            self._yawn_fired      = False

        self.pitch_up_sustained = pitch_up_sustained
        self.pitch_rel          = pitch_rel
        return microsleep_alert, yawn_detected


# ── FatigueEngine (orchestrator) ─────────────────────────────────────────────

class FatigueEngine:
    """Coordinates all modules with frame interleaving.

    Call ``step(lm, w, h, t_now)`` each frame.
    Pass raw MediaPipe FaceLandmarker landmarks (list of 478 NormalizedLandmarks).
    """

    def __init__(self, params: Optional[FatigueParams] = None) -> None:
        self._tuning: MediaPipeTuning = load_mediapipe_tuning()
        self._calibration_store = CalibrationStore()
        self.p      = params or FatigueParams(
            blend_calib_sec=self._tuning.blendshape.calib_sec,
            blend_min_samples=self._tuning.blendshape.min_samples,
            blend_ema_alpha=self._tuning.blendshape.ema_alpha,
            blend_blink_gate=self._tuning.blendshape.blink_gate,
            blend_squint_gate=self._tuning.blendshape.squint_gate,
            blend_brow_gate=self._tuning.blendshape.brow_gate,
            blend_jaw_gate=self._tuning.blendshape.jaw_gate,
        )
        self.eye    = EyeCognitiveModule(self.p)
        self.gaze   = GazeTrackingModule(self.p)
        self.head   = HeadMouthModule(self.p)
        self._frame = 0
        self._load_persisted_calibration()

    def reset(self) -> None:
        self.eye.reset(full=True)
        self.gaze.reset()
        self.head.reset(full=True)
        self._frame = 0
        self._load_persisted_calibration()

    def _load_persisted_calibration(self) -> None:
        eye_cal = self._calibration_store.get_section("fatigue_eye_blendshape")
        mouth_cal = self._calibration_store.get_section("fatigue_mouth_blendshape")
        if eye_cal:
            for key in ("blink", "squint", "brow"):
                if key in eye_cal:
                    self.eye._blend_baseline[key] = float(eye_cal.get(key, 0.0) or 0.0)
            self.eye._blend_calibrated = True
        if mouth_cal:
            self.head._mouth_blend_baseline = float(mouth_cal.get("baseline", 0.0) or 0.0)
            self.head._mouth_blend_calibrated = True

    def _save_persisted_calibration(self) -> None:
        if self.eye._blend_calibrated:
            self._calibration_store.set_section(
                "fatigue_eye_blendshape",
                {
                    "blink": self.eye._blend_baseline["blink"],
                    "squint": self.eye._blend_baseline["squint"],
                    "brow": self.eye._blend_baseline["brow"],
                },
            )
        if self.head._mouth_blend_calibrated:
            self._calibration_store.set_section(
                "fatigue_mouth_blendshape",
                {"baseline": self.head._mouth_blend_baseline},
            )

    def on_no_face(self) -> FatigueMetrics:
        self.eye.reset(full=False)
        self.gaze.reset()
        self.head._pitch_down_start = None
        self.head._yawn_open_start  = None
        self.head.mouth_open_ratio   = 0.0
        return FatigueMetrics(face_detected=False, status="NO_FACE")

    def step(
        self,
        lm: Any,
        w: int,
        h: int,
        t_now: float,
        blendshapes: Any | None = None,
    ) -> FatigueMetrics:
        p  = self.p
        fc = self._frame
        self._frame += 1

        # ── Frame-interleaving flags ────────────────────────────────────────
        run_pose = (fc % p.pose_stride == 0)
        run_brow = (fc % p.brow_stride == 0)

        # ── Quality gates ───────────────────────────────────────────────────
        oval = np.array([_p(lm, w, h, i) for i in FACE_OVAL_IDXS], dtype=np.int32)
        if p.use_stable_face_area:
            fh_px = abs(_p(lm, w, h, CHIN_IDX)[1] - _p(lm, w, h, FOREHEAD_IDX)[1])
            face_area = (fh_px ** 2) / max(1, w * h)
        else:
            ow, oh = np.ptp(oval[:, 0]), np.ptp(oval[:, 1])
            face_area = (ow * oh) / max(1, w * h)

        le_pt = _p(lm, w, h, LEFT_EYE_OUTER)
        re_pt = _p(lm, w, h, RIGHT_EYE_OUTER)
        roll = float(abs(((np.degrees(np.arctan2(
            re_pt[1] - le_pt[1], re_pt[0] - le_pt[0]
        )) + 90.0) % 180.0) - 90.0))

        n_pt  = _p(lm, w, h, NOSE_TIP_IDX)
        n_bridge = _mean_p(lm, w, h, NOSE_BRIDGE_IDX)
        nose_anchor = (
            (n_pt[0] + n_bridge[0]) / 2.0,
            (n_pt[1] + n_bridge[1]) / 2.0,
        )
        lc_pt = _p(lm, w, h, LEFT_CHEEK_IDX)
        rc_pt = _p(lm, w, h, RIGHT_CHEEK_IDX)
        dL    = _dist(n_pt, lc_pt)
        dR    = _dist(n_pt, rc_pt)
        yaw_r = max(dL / (dR + 1e-6), dR / (dL + 1e-6))
        mouth_w = _dist(_p(lm, w, h, 61), _p(lm, w, h, 291)) + 1e-6
        mouth_gap = _dist(_p(lm, w, h, 13), _p(lm, w, h, 14))
        mouth_open_ratio = mouth_gap / mouth_w

        # Nose speed
        if self.eye._prev_t is not None and self.eye._prev_nose is not None:
            dt = t_now - self.eye._prev_t
            if dt > 1e-3:
                self.eye.nose_speed = _dist(nose_anchor, self.eye._prev_nose) / dt
        self.eye._prev_t    = t_now
        self.eye._prev_nose = nose_anchor

        blink_ok = (
            face_area >= p.min_face_area_ratio_blink
            and roll  <= p.roll_limit_blink
        )
        fatigue_q = min(
            _clamp(face_area / p.min_face_area_ratio_fatigue, 0.0, 1.0),
            _clamp(1.0 - (roll - p.roll_limit_fatigue * 0.7)
                   / (p.roll_limit_fatigue * 0.3 + 1e-6), 0.0, 1.0),
            _clamp(1.0 - max(0.0, yaw_r - p.yaw_ratio_limit_fatigue * 0.9)
                   / (p.yaw_ratio_limit_fatigue * 0.1 + 1e-6), 0.0, 1.0),
            _clamp(1.0 - max(0.0, self.eye.nose_speed - p.nose_speed_limit_fatigue * 0.8)
                   / (p.nose_speed_limit_fatigue * 0.2 + 1e-6), 0.0, 1.0),
            _clamp(1.0 - max(0.0, self.eye.lid_balance - p.lid_balance_gate_th)
                   / (p.lid_balance_gate_th + 1e-6), 0.0, 1.0),
            _clamp(1.0 - max(0.0, mouth_open_ratio - p.mouth_open_noise_th)
                   / (p.mouth_open_noise_th + 1e-6), 0.0, 1.0),
        )
        fatigue_ok = (
            face_area >= p.min_face_area_ratio_fatigue
            and roll  <= p.roll_limit_fatigue
            and yaw_r <= p.yaw_ratio_limit_fatigue
            and self.eye.nose_speed <= p.nose_speed_limit_fatigue
        )

        # ── Pitch-up gate (suppress blink/fatigue if strongly looking up) ───
        pitch_rel = self.head.head_pitch - self.head._pitch_offset
        if pitch_rel > p.pitch_eye_gate_deg:
            blink_ok   = False
            fatigue_ok = False

        # ── Module steps ────────────────────────────────────────────────────
        self.eye.step(
            lm,
            w,
            h,
            t_now,
            bool(blink_ok),
            bool(fatigue_ok),
            fatigue_q,
            blendshapes=blendshapes,
            run_brow=run_brow,
        )

        has_iris = self.eye.has_iris
        self.gaze.step(lm, t_now, has_iris)

        microsleep_alert, yawn_detected = self.head.step(
            lm,
            w,
            h,
            t_now,
            blendshapes=blendshapes,
            fatigue_quality=fatigue_q,
            blend_calib_progress=self.eye.blend_calib_progress,
            run_pose=run_pose,
        )
        if self.eye._blend_calibrated or self.head._mouth_blend_calibrated:
            self._save_persisted_calibration()

        # ── Status & composite fatigue level ─────────────────────────────────
        # V2 early-warning: cognitive / micro-expression driven
        early_warning = (
            self.eye.is_squinting
            or self.eye.is_frowning
            or self.gaze.gaze_mental_fatigue
            or (self.gaze.fixation_duration > 15.0)
            or self.eye.blend_eye_squint > p.blend_squint_gate
            or self.eye.blend_brow_down > p.blend_brow_gate
            or (
                self.eye.lid_balance > p.lid_balance_gate_th
                and self.eye.ear_smooth < self.eye.base_ear_th * 1.25
            )
        )

        status = "CALIBRATING" if not self.eye.calibrated else "OK"
        if self.eye.calibrated:
            if self.eye.last_perclos >= p.tired_perclos_th:
                status = "TIRED"
            if self.eye.long_closed:
                status = "DROWSY"
            if microsleep_alert:
                status = "MICROSLEEP"
            if early_warning and status == "OK":
                status = "ALERT"

        # Composite fatigue (0-1) — V2 weights
        # Pitch nod → heavy weight when it fires
        # PERCLOS → standard
        # Cognitive (squint + frown + gaze fixation) → early, moderate weight
        # Yawn → late stage, very low weight
        fatigue_level = _clamp(
            self.eye.last_perclos * 0.40
            + (1.0 if microsleep_alert else 0.0) * 0.30
            + (self.eye.squint_duration / 30.0 if self.eye.is_squinting else 0.0) * 0.15
            + (0.15 if self.eye.is_frowning else 0.0)
            + (0.10 if self.gaze.gaze_mental_fatigue else 0.0)
            + (0.05 if self.eye.blend_eye_squint > p.blend_squint_gate else 0.0)
            + (0.05 if self.eye.blend_brow_down > p.blend_brow_gate else 0.0)
            + (self.head.yawn_count / 10.0) * 0.05,
            0.0, 1.0,
        )
        quality_score = _clamp(fatigue_q)

        return FatigueMetrics(
            face_detected   = True,
            calibrated      = self.eye.calibrated,
            status          = status,
            fatigue_level   = fatigue_level,
            early_warning   = early_warning,
            # Eye
            ear             = self.eye.ear,
            ear_smooth      = self.eye.ear_smooth,
            blink_count     = self.eye.blink_count,
            perclos         = self.eye.last_perclos,
            blink_rate_pm   = self.eye.blink_rate_pm,
            # Micro-expressions
            is_squinting    = self.eye.is_squinting,
            squint_duration = self.eye.squint_duration,
            is_frowning     = self.eye.is_frowning,
            brow_dist_norm  = self.eye.brow_dist_norm,
            # Pupillometry
            iris_ratio      = self.eye.iris_ratio,
            iris_ratio_trend = self.eye.iris_ratio_trend,
            blend_eye_blink = self.eye.blend_eye_blink,
            blend_eye_squint = self.eye.blend_eye_squint,
            blend_brow_down  = self.eye.blend_brow_down,
            lid_open_left   = self.eye.lid_open_left,
            lid_open_right  = self.eye.lid_open_right,
            lid_balance     = self.eye.lid_balance,
            nose_speed      = self.eye.nose_speed,
            # Gaze
            gaze_x          = self.gaze.gaze_x,
            gaze_y          = self.gaze.gaze_y,
            gaze_stability_index  = self.gaze.gaze_stability_index,
            gaze_mental_fatigue   = self.gaze.gaze_mental_fatigue,
            saccadic_velocity     = self.gaze.saccadic_velocity,
            is_saccade            = self.gaze.is_saccade,
            fixation_duration     = self.gaze.fixation_duration,
            saccade_freq_pm       = self.gaze.saccade_freq_pm,
            # Head
            head_pitch      = self.head.head_pitch,
            head_yaw        = self.head.head_yaw,
            head_roll       = self.head.head_roll,
            microsleep_alert = microsleep_alert,
            microsleep_count = self.head.microsleep_count,
            # Yawn
            mar             = self.head.mar,
            yawn_detected   = yawn_detected,
            yawn_count      = self.head.yawn_count,
            mouth_open_ratio = self.head.mouth_open_ratio,
            blend_jaw_open  = self.head.mouth_blend_stretch,
            mouth_blend_stretch = self.head.mouth_blend_stretch,
            quality_score   = quality_score,
            blend_calib_progress = self.eye.blend_calib_progress,
            # Meta
            has_iris        = has_iris,
            calib_progress  = self.eye.calib_progress,
        )
