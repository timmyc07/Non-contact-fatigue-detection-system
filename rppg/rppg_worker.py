"""Production rPPG engine for rPPG V2 GUI.

Signal pipeline:
    CameraStreamWorker → BGR queue → RppgWorker (own QThread)
    → MediaPipe Face Landmarker → ROI extraction
    → POS algorithm → Butterworth BP → Welch PSD
    → BPM / HRV metrics → Overlay

Usage:
    # After pipeline starts:
    q = queue.Queue(maxsize=2)
    cam_worker.attach_bgr_queue(q)
    rppg_worker = RppgWorker(q, target_fps=30.0)
    # rppg_worker.run() in a QThread
"""

from __future__ import annotations

import queue
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, cast

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision
from scipy.interpolate import interp1d as _scipy_interp1d
from scipy.signal import butter, filtfilt, find_peaks, sosfiltfilt, welch

_HAS_MP = True
_HAS_SCIPY = True

# ── ROI landmark indices (MediaPipe 478-point face mesh) ────────────────────
FOREHEAD_ROI_IDX  = [107, 66, 69, 109, 10, 338, 299, 296, 336, 9]
LEFT_CHEEK_ROI_IDX  = [118, 119, 100, 126, 209, 49, 129, 203, 205, 50]
RIGHT_CHEEK_ROI_IDX = [347, 348, 329, 355, 429, 279, 358, 423, 425, 280]
GLABELLA_ROI_IDX  = [151, 108, 107, 55, 8, 285, 336, 337]

ROI_SPECS: list[tuple[str, list[int]]] = [
    ("forehead", FOREHEAD_ROI_IDX),
    ("L_cheek",  LEFT_CHEEK_ROI_IDX),
    ("R_cheek",  RIGHT_CHEEK_ROI_IDX),
    ("glabella", GLABELLA_ROI_IDX),
]

ROI_BASE_WEIGHTS = {
    "forehead": 0.34,
    "L_cheek": 0.25,
    "R_cheek": 0.25,
    "glabella": 0.16,
}

FOREHEAD_IDX = 10
CHIN_IDX = 152
NOSE_TIP_IDX = 1
LEFT_CHEEK_IDX = 234
RIGHT_CHEEK_IDX = 454
FACE_OVAL_IDXS = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
_MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


# ── Metrics dataclass ────────────────────────────────────────────────────────

@dataclass
class RppgMetrics:
    bpm:               float = 0.0
    rmssd:             float = 0.0
    sdnn:              float = 0.0
    lf_hf:             float = 0.0
    sqi:               float = 0.0
    stress_prob:       float = 0.0
    stress_status:     str   = "calibrating"
    hrv_confidence:    str   = "LOW"
    ibi_artifact_ratio: float = 0.0
    peak_freq_hz:      float = 0.0
    frame_brightness:  float = 0.0
    warmup_progress:   float = 0.0
    quality_score:     float = 0.0
    pose_roll_deg:     float = 0.0
    pose_yaw_deg:      float = 0.0
    pose_pitch_deg:    float = 0.0
    roi_valid_count:   int   = 0
    roi_weight_forehead: float = 0.0
    roi_weight_l_cheek:   float = 0.0
    roi_weight_r_cheek:    float = 0.0
    roi_weight_glabella:   float = 0.0
    face_detected:     bool  = False
    waveform:  list[float] = field(default_factory=list)
    psd_freqs: list[float] = field(default_factory=list)
    psd_vals:  list[float] = field(default_factory=list)


# ── Signal processing helpers ────────────────────────────────────────────────

def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def _lm_xy(lm: Any, idx: int, w: int, h: int) -> tuple[int, int]:
    p = lm[idx]
    return int(float(p.x) * w), int(float(p.y) * h)


def _dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return float(np.hypot(p1[0] - p2[0], p1[1] - p2[1]))


def _lm_xyf(lm: Any, idx: int, w: int, h: int) -> tuple[float, float]:
    x, y = _lm_xy(lm, idx, w, h)
    return float(x), float(y)


def _face_center_px(lm: Any, w: int, h: int) -> tuple[float, float]:
    pts = np.array([_lm_xy(lm, idx, w, h) for idx in FACE_OVAL_IDXS], dtype=np.float64)
    if pts.size == 0:
        return 0.0, 0.0
    return float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))


def _rotate_points(
    pts: np.ndarray,
    center: tuple[float, float],
    angle_deg: float,
) -> np.ndarray:
    if pts.size == 0 or abs(angle_deg) < 1e-6:
        return pts
    ang = np.deg2rad(angle_deg)
    c = float(np.cos(ang))
    s = float(np.sin(ang))
    rot = np.array([[c, -s], [s, c]], dtype=np.float64)
    ctr = np.array(center, dtype=np.float64)
    return ((pts.astype(np.float64) - ctr) @ rot.T) + ctr


def _pose_from_matrix(
    transform_matrix: Any | None,
    lm: Any,
    w: int,
    h: int,
) -> tuple[float, float, float, float]:
    """Return (roll_deg, yaw_deg, pitch_deg, scale)."""
    if transform_matrix is not None:
        try:
            mat = np.asarray(transform_matrix, dtype=np.float64)
            if mat.shape[0] >= 3 and mat.shape[1] >= 3:
                rot = mat[:3, :3].copy()
                scale = float(np.mean([np.linalg.norm(rot[:, i]) for i in range(3)]))
                if scale > 1e-8:
                    rot /= scale
                roll = float(np.degrees(np.arctan2(rot[1, 0], rot[0, 0])))
                yaw = float(
                    np.degrees(
                        np.arctan2(-rot[2, 0], np.hypot(rot[0, 0], rot[1, 0]))
                    )
                )
                pitch = float(np.degrees(np.arctan2(rot[2, 1], rot[2, 2])))
                return roll, yaw, pitch, max(scale, 1e-6)
        except Exception:
            pass

    try:
        le = _lm_xyf(lm, 33, w, h)
        re = _lm_xyf(lm, 263, w, h)
        roll = float(np.degrees(np.arctan2(re[1] - le[1], re[0] - le[0])))
        n_pt = _lm_xyf(lm, NOSE_TIP_IDX, w, h)
        l_pt = _lm_xyf(lm, LEFT_CHEEK_IDX, w, h)
        r_pt = _lm_xyf(lm, RIGHT_CHEEK_IDX, w, h)
        d_l = _dist(n_pt, l_pt)
        d_r = _dist(n_pt, r_pt)
        yaw = float(np.degrees(np.arctan2(d_r - d_l, d_r + d_l + 1e-6)) * 2.0)
        forehead = _lm_xyf(lm, FOREHEAD_IDX, w, h)
        chin = _lm_xyf(lm, CHIN_IDX, w, h)
        pitch = float(
            np.degrees(np.arctan2(chin[1] - forehead[1], abs(chin[0] - forehead[0]) + 1e-6))
        )
        return roll, yaw, pitch, 1.0
    except Exception:
        return 0.0, 0.0, 0.0, 1.0


def _roi_weights_from_pose(
    roll_deg: float,
    yaw_deg: float,
    pitch_deg: float,
    lm: Any,
    w: int,
    h: int,
) -> dict[str, float]:
    roll_q = _clamp(1.0 - abs(roll_deg) / 42.0, 0.35, 1.0)
    yaw_q = _clamp(1.0 - abs(yaw_deg) / 42.0, 0.35, 1.0)
    pitch_q = _clamp(1.0 - max(0.0, abs(pitch_deg) - 8.0) / 34.0, 0.35, 1.0)

    n_pt = _lm_xyf(lm, NOSE_TIP_IDX, w, h)
    l_pt = _lm_xyf(lm, LEFT_CHEEK_IDX, w, h)
    r_pt = _lm_xyf(lm, RIGHT_CHEEK_IDX, w, h)
    d_l = _dist(n_pt, l_pt)
    d_r = _dist(n_pt, r_pt)
    total = d_l + d_r + 1e-6
    left_bias = _clamp(d_r / total, 0.35, 1.15)
    right_bias = _clamp(d_l / total, 0.35, 1.15)

    weights = {
        "forehead": ROI_BASE_WEIGHTS["forehead"] * roll_q * pitch_q,
        "L_cheek": ROI_BASE_WEIGHTS["L_cheek"] * roll_q * yaw_q * left_bias,
        "R_cheek": ROI_BASE_WEIGHTS["R_cheek"] * roll_q * yaw_q * right_bias,
        "glabella": ROI_BASE_WEIGHTS["glabella"] * (0.70 * roll_q + 0.30 * pitch_q),
    }
    total_w = sum(weights.values()) or 1.0
    return {k: float(v / total_w) for k, v in weights.items()}


def _face_quality_from_pose(
    roll_deg: float,
    yaw_deg: float,
    pitch_deg: float,
    face_area_ratio: float,
    face_motion_norm: float,
    roi_valid_ratio: float,
) -> float:
    pose_q = _clamp(
        0.40 * (1.0 - abs(roll_deg) / 48.0)
        + 0.35 * (1.0 - abs(yaw_deg) / 48.0)
        + 0.25 * (1.0 - max(0.0, abs(pitch_deg) - 6.0) / 38.0),
        0.0, 1.0,
    )
    motion_q = _clamp(1.0 - face_motion_norm / 0.85, 0.0, 1.0)
    coverage_q = _clamp(face_area_ratio / 0.08, 0.0, 1.0)
    roi_q = _clamp(roi_valid_ratio, 0.0, 1.0)
    return float(_clamp(0.30 * pose_q + 0.25 * motion_q + 0.25 * coverage_q + 0.20 * roi_q))


def roi_mean_bgr(
    frame_bgr: np.ndarray,
    lm: Any,
    indices: list[int],
    blur_ksize: int = 5,
    transform_matrix: Any | None = None,
) -> Optional[tuple[float, float, float]]:
    h, w = frame_bgr.shape[:2]
    pts = np.array([_lm_xy(lm, i, w, h) for i in indices], dtype=np.float64)
    if pts.shape[0] < 3:
        return None
    if transform_matrix is not None:
        roll_deg, _, _, _ = _pose_from_matrix(transform_matrix, lm, w, h)
        center = _face_center_px(lm, w, h)
        pts = _rotate_points(pts, center, -roll_deg)
    pts = np.round(pts).astype(np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, pts, 255)
    if cv2.countNonZero(mask) < 30:
        return None
    roi = cv2.GaussianBlur(frame_bgr, (blur_ksize, blur_ksize), 0)
    mean = cv2.mean(roi, mask=mask)
    return float(mean[2]), float(mean[1]), float(mean[0])  # R, G, B


def draw_rois(frame_bgr: np.ndarray, lm: Any, transform_matrix: Any | None = None) -> None:
    h, w = frame_bgr.shape[:2]
    center = _face_center_px(lm, w, h)
    roll_deg, _, _, _ = _pose_from_matrix(transform_matrix, lm, w, h)
    for _, indices in ROI_SPECS:
        pts = np.array([_lm_xy(lm, i, w, h) for i in indices], dtype=np.float64)
        if transform_matrix is not None:
            pts = _rotate_points(pts, center, -roll_deg)
        pts = np.round(pts).astype(np.int32)
        if pts.shape[0] >= 3:
            cv2.polylines(frame_bgr, [pts], True, (0, 200, 255), 1, cv2.LINE_AA)


def pos_pulse(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Wang et al. POS on temporally normalised channels."""
    r = (r - np.mean(r)) / (np.std(r) + 1e-8)
    g = (g - np.mean(g)) / (np.std(g) + 1e-8)
    b = (b - np.mean(b)) / (np.std(b) + 1e-8)
    x = 3.0 * r - 2.0 * g
    y = 1.5 * r + g - 1.5 * b
    alpha = float(np.std(x) / (np.std(y) + 1e-8))
    return x - alpha * y


def butter_bandpass(
    sig: np.ndarray, fs: float, low: float = 0.65, high: float = 3.7, order: int = 3
) -> np.ndarray:
    if not _HAS_SCIPY:
        return sig.astype(np.float64)
    nyq = 0.5 * fs
    lo = max(low / nyq, 1e-4)
    hi = min(high / nyq, 0.99)
    if hi <= lo:
        return sig.astype(np.float64)
    sig64 = sig.astype(np.float64)
    try:
        sos = butter(order, [lo, hi], btype="band", output="sos")
        return sosfiltfilt(sos, sig64)
    except ValueError:
        return sig64
    except Exception:
        try:
            b, a = cast(tuple[Any, Any], butter(order, [lo, hi], btype="band"))
            return filtfilt(b, a, sig64)
        except Exception:
            return sig64


def welch_peak_hz(
    sig: np.ndarray, fs: float
) -> tuple[float, np.ndarray, np.ndarray]:
    if not _HAS_SCIPY:
        return 0.0, np.array([]), np.array([])
    n = len(sig)
    nperseg = min(n, max(64, int(fs * 5)))
    noverlap = min(nperseg - 1, nperseg * 3 // 4)
    f, pxx = welch(
        sig,
        fs=fs,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=max(512, nperseg),
        window="blackmanharris",
    )
    band = (f >= 0.7) & (f <= 3.5)
    if not np.any(band):
        return 0.0, f, pxx
    ib = np.argmax(pxx[band])
    return float(f[band][ib]), f, pxx


def compute_sqi(sig: np.ndarray, fs: float) -> float:
    if not _HAS_SCIPY or len(sig) < 32:
        return 0.0
    nperseg = min(len(sig), max(64, int(fs * 5)))
    noverlap = min(nperseg - 1, nperseg * 3 // 4)
    f, pxx = welch(
        sig,
        fs=fs,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=max(512, nperseg),
        window="blackmanharris",
    )
    total = float(np.sum(pxx)) + 1e-12
    inband = float(np.sum(pxx[(f >= 0.6) & (f <= 4.0)]))
    return float(np.clip(inband / total, 0.0, 1.0))


def ibi_from_peaks(sig: np.ndarray, fs: float) -> np.ndarray:
    if not _HAS_SCIPY:
        return np.array([], dtype=np.float64)
    dist = int(max(3, fs * 0.35))
    prom = float(np.std(sig) * 0.35 + 1e-6)
    peaks, _ = find_peaks(sig, distance=dist, prominence=prom)
    if len(peaks) < 2:
        return np.array([], dtype=np.float64)
    return np.diff(peaks) / fs * 1000.0  # ms


def validate_ibi_intervals(ibis_ms: np.ndarray) -> np.ndarray:
    """Remove implausible and locally inconsistent rPPG IBI intervals."""
    ibis = np.asarray(ibis_ms, dtype=np.float64)
    ibis = ibis[np.isfinite(ibis)]
    if ibis.size == 0:
        return np.array([], dtype=np.float64)

    valid = ibis[(ibis >= 300.0) & (ibis <= 2000.0)]
    if valid.size < 3:
        return valid

    if valid.size >= 5:
        half_w = 2
        padded = np.pad(valid, (half_w, half_w), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half_w + 1)
        local_median = np.median(windows, axis=1)
    else:
        local_median = np.full(valid.shape, float(np.median(valid)), dtype=np.float64)

    local_median = np.where(local_median < 1e-6, float(np.median(valid)), local_median)
    delta = np.abs(valid - local_median)
    q1, q3 = np.percentile(delta, [25, 75])
    adaptive = float(np.median(delta)) + 5.2 * float(q3 - q1)
    threshold = np.maximum(adaptive, 0.20 * local_median)
    valid = valid[delta <= threshold]
    if valid.size < 3:
        return valid

    half_w = 2
    padded = np.pad(valid, (half_w, half_w), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half_w + 1)
    local_median = np.median(windows, axis=1)
    keep = np.abs(valid - local_median) <= 0.30 * local_median
    return valid[keep]


def hrv_time_domain(ibis_ms: np.ndarray) -> tuple[float, float]:
    if ibis_ms.size < 2:
        return 0.0, 0.0
    diff = np.diff(ibis_ms)
    rmssd = float(np.sqrt(np.mean(diff * diff))) if diff.size else 0.0
    sdnn = float(np.std(ibis_ms, ddof=1)) if ibis_ms.size > 1 else 0.0
    return rmssd, sdnn


def ibi_artifact_ratio(ibis_ms: np.ndarray, clean_ibis_ms: Optional[np.ndarray] = None) -> float:
    if ibis_ms.size == 0:
        return 1.0
    if clean_ibis_ms is None:
        good = (ibis_ms >= 300.0) & (ibis_ms <= 2000.0)
        return float(1.0 - np.mean(good.astype(np.float64)))
    return float(np.clip(1.0 - clean_ibis_ms.size / max(ibis_ms.size, 1), 0.0, 1.0))


def lf_hf_from_tachogram(ibis_ms: np.ndarray, fs_resample: float = 4.0) -> float:
    if not _HAS_SCIPY or ibis_ms.size < 8:
        return 0.0
    ibi_s = ibis_ms / 1000.0
    t = np.cumsum(ibi_s)
    t = t - t[0]
    if t[-1] < 4.0:
        return 0.0
    t_uniform = np.arange(0.0, t[-1], 1.0 / fs_resample)
    try:
        series = _scipy_interp1d(t, ibi_s, kind="linear", fill_value=cast(Any, "extrapolate"))(t_uniform)
        series = series - np.mean(series)
    except Exception:
        return 0.0
    nperseg = min(128, max(32, len(series) // 2))
    if nperseg < 32:
        return 0.0
    ff, pxx = welch(series, fs=fs_resample, nperseg=nperseg, noverlap=nperseg // 2)
    lf = float(np.sum(pxx[(ff >= 0.04) & (ff < 0.15)])) + 1e-12
    hf = float(np.sum(pxx[(ff >= 0.15) & (ff <= 0.4)])) + 1e-12
    return float(lf / hf)


def stress_heuristic(lf_hf: float, rmssd: float) -> tuple[float, str]:
    if lf_hf <= 0 or rmssd <= 0:
        return 0.0, "calibrating"
    lf_term = float(np.clip((lf_hf - 1.2) / 2.5, 0.0, 1.0))
    rm_term = float(np.clip((65.0 - rmssd) / 65.0, 0.0, 1.0))
    prob = float(np.clip(0.45 * lf_term + 0.55 * rm_term, 0.0, 1.0))
    if prob < 0.35:
        label = "輕鬆"
    elif prob < 0.6:
        label = "一般"
    else:
        label = "緊張"
    return prob, label


def hrv_confidence(n_ibis: int, sqi: float, art_ratio: float) -> str:
    if n_ibis < 6 or sqi < 0.25 or art_ratio > 0.35:
        return "LOW"
    if n_ibis < 12 or sqi < 0.45 or art_ratio > 0.15:
        return "MEDIUM"
    return "HIGH"


# ── Model download ───────────────────────────────────────────────────────────

def ensure_face_model(
    models_dir: Path,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / "face_landmarker.task"
    if target.exists() and target.stat().st_size > 1_000_000:
        return target
    if status_cb:
        status_cb("正在下載 MediaPipe 臉部模型…（首次執行約 20-30 MB）")
    urllib.request.urlretrieve(MODEL_URL, target)
    if status_cb:
        status_cb("模型下載完成")
    return target


# ── RppgEngine ───────────────────────────────────────────────────────────────

class RppgEngine:
    """Buffer RGB samples and compute rPPG + HRV metrics on demand."""

    def __init__(self, buffer_sec: float = 12.0, target_fps: float = 30.0) -> None:
        self.buffer_sec = buffer_sec
        self.target_fps = target_fps
        self._r: deque[float] = deque(maxlen=100_000)
        self._g: deque[float] = deque(maxlen=100_000)
        self._b: deque[float] = deque(maxlen=100_000)
        self._t: deque[float] = deque(maxlen=100_000)
        self._last_fs: float = target_fps
        self._prev_face_center: Optional[tuple[float, float]] = None
        self._prev_face_center_t: Optional[float] = None
        self._face_motion_speed: float = 0.0

    def reset(self) -> None:
        self._r.clear(); self._g.clear()
        self._b.clear(); self._t.clear()
        self._prev_face_center = None
        self._prev_face_center_t = None
        self._face_motion_speed = 0.0

    def push(self, t: float, r: float, g: float, b: float) -> None:
        self._r.append(r); self._g.append(g)
        self._b.append(b); self._t.append(t)

    def _trim(self, t_now: float) -> None:
        cutoff = t_now - self.buffer_sec
        while self._t and self._t[0] < cutoff:
            self._t.popleft(); self._r.popleft()
            self._g.popleft(); self._b.popleft()

    def _fs(self) -> float:
        if len(self._t) < 5:
            return self.target_fps
        dt = (self._t[-1] - self._t[0]) / (len(self._t) - 1)
        if dt <= 1e-6:
            return self.target_fps
        self._last_fs = float(np.clip(1.0 / dt, 8.0, 90.0))
        return self._last_fs

    def compute(
        self,
        t_now: float,
        frame_bgr: np.ndarray,
        lm: Any,
        transform_matrix: Any | None = None,
        roi_valid_count: int | None = None,
    ) -> RppgMetrics:
        self._trim(t_now)
        fs = self._fs()
        n = len(self._t)
        need = int(fs * max(6.0, self.buffer_sec * 0.5))
        warm = float(min(1.0, n / max(need, 1)))
        roi_valid_ratio = (
            (roi_valid_count if roi_valid_count is not None else len(ROI_SPECS))
            / max(len(ROI_SPECS), 1)
        )

        roll_deg, yaw_deg, pitch_deg, _scale = _pose_from_matrix(transform_matrix, lm, *frame_bgr.shape[:2][::-1])
        face_center = _face_center_px(lm, frame_bgr.shape[1], frame_bgr.shape[0])
        face_w = float(np.ptp(np.array([_lm_xy(lm, i, frame_bgr.shape[1], frame_bgr.shape[0])[0] for i in FACE_OVAL_IDXS], dtype=np.float64))) + 1e-6
        face_h = float(np.ptp(np.array([_lm_xy(lm, i, frame_bgr.shape[1], frame_bgr.shape[0])[1] for i in FACE_OVAL_IDXS], dtype=np.float64))) + 1e-6
        face_area_ratio = (face_w * face_h) / max(1.0, frame_bgr.shape[0] * frame_bgr.shape[1])

        if self._prev_face_center is not None and self._prev_face_center_t is not None:
            dt_center = t_now - self._prev_face_center_t
            if dt_center > 1e-4:
                self._face_motion_speed = _dist(face_center, self._prev_face_center) / dt_center
        self._prev_face_center = face_center
        self._prev_face_center_t = t_now

        br = roi_mean_bgr(frame_bgr, lm, FOREHEAD_ROI_IDX, transform_matrix=transform_matrix)
        brightness = float(br[1]) if br else -1.0

        if n < int(fs * 4):
            pose_quality = _face_quality_from_pose(
                roll_deg,
                yaw_deg,
                pitch_deg,
                face_area_ratio,
                self._face_motion_speed / max(face_h, 1e-6),
                roi_valid_ratio,
            )
            return RppgMetrics(
                warmup_progress=warm,
                frame_brightness=brightness,
                quality_score=pose_quality,
                pose_roll_deg=roll_deg,
                pose_yaw_deg=yaw_deg,
                pose_pitch_deg=pitch_deg,
                hrv_confidence="LOW",
                face_detected=True,
            )

        r = np.array(self._r, dtype=np.float64)
        g = np.array(self._g, dtype=np.float64)
        b = np.array(self._b, dtype=np.float64)

        raw = pos_pulse(r, g, b)
        filt = butter_bandpass(raw, fs, 0.65, 3.7)
        peak_f, freqs, pxx = welch_peak_hz(filt, fs)
        bpm = peak_f * 60.0 if peak_f > 0 else 0.0
        sqi = compute_sqi(filt, fs)

        ibis = ibi_from_peaks(filt, fs)
        ibis_clean = validate_ibi_intervals(ibis)
        art = ibi_artifact_ratio(ibis, ibis_clean)
        rmssd, sdnn = hrv_time_domain(ibis_clean)
        lf_hf = lf_hf_from_tachogram(ibis_clean)
        prob, st = stress_heuristic(lf_hf, rmssd)
        conf = hrv_confidence(ibis_clean.size, sqi, art)
        signal_quality = _clamp(0.60 * sqi + 0.40 * (1.0 - art))
        roi_valid_count = len(ROI_SPECS) if roi_valid_count is None else int(max(0, roi_valid_count))
        quality_score = _face_quality_from_pose(
            roll_deg,
            yaw_deg,
            pitch_deg,
            face_area_ratio,
            self._face_motion_speed / max(face_h, 1e-6),
            roi_valid_count / max(len(ROI_SPECS), 1),
        )
        quality_score = _clamp(0.55 * quality_score + 0.45 * signal_quality)

        wf_n = min(160, filt.size)
        wave = filt[-wf_n:].copy()
        std = float(np.std(wave))
        wave = (wave - float(np.mean(wave))) / (std + 1e-9) if std > 1e-9 else wave * 0.0

        psd_mask = (freqs >= 0.5) & (freqs <= 4.0)
        pf, pv = freqs[psd_mask], pxx[psd_mask]
        if pf.size > 64:
            step = pf.size // 64
            pf, pv = pf[::step], pv[::step]

        return RppgMetrics(
            bpm=float(bpm), rmssd=float(rmssd), sdnn=float(sdnn),
            lf_hf=float(lf_hf), sqi=float(sqi),
            stress_prob=float(prob), stress_status=st,
            hrv_confidence=conf,
            ibi_artifact_ratio=float(art),
            peak_freq_hz=float(peak_f),
            frame_brightness=brightness,
            warmup_progress=warm,
            quality_score=float(quality_score),
            pose_roll_deg=float(roll_deg),
            pose_yaw_deg=float(yaw_deg),
            pose_pitch_deg=float(pitch_deg),
            roi_valid_count=int(roi_valid_count),
            roi_weight_forehead=float(roi_weights.get("forehead", 0.0)),
            roi_weight_l_cheek=float(roi_weights.get("L_cheek", 0.0)),
            roi_weight_r_cheek=float(roi_weights.get("R_cheek", 0.0)),
            roi_weight_glabella=float(roi_weights.get("glabella", 0.0)),
            face_detected=True,
            waveform=[float(x) for x in wave],
            psd_freqs=[float(x) for x in pf],
            psd_vals=[float(x) for x in pv],
        )


# ── RppgWorker ───────────────────────────────────────────────────────────────

class RppgWorker(QObject):
    """Runs in a QThread.  Consumes BGR frames from a queue, runs MediaPipe
    face detection, computes rPPG + HRV metrics, and emits results.

    Annotated frames (with ROI outlines) are emitted as QImage so the overlay
    can display them instead of the plain camera frames while rPPG is active.
    """

    metrics_ready   = Signal(object)   # RppgMetrics
    frame_annotated = Signal(QImage)   # BGR frame with ROI overlays → QImage
    face_detected   = Signal(bool)
    status_changed  = Signal(str)
    failed          = Signal(str)
    finished        = Signal()

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        target_fps: float = 30.0,
        buffer_sec: float = 12.0,
    ) -> None:
        super().__init__()
        self._queue = frame_queue
        self._target_fps = target_fps
        self._buffer_sec = buffer_sec
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        if not _HAS_MP:
            self.failed.emit(
                "MediaPipe 未安裝。\n請執行：pip install mediapipe"
            )
            self.finished.emit()
            return
        if not _HAS_SCIPY:
            self.failed.emit(
                "SciPy 未安裝。\n請執行：pip install scipy"
            )
            self.finished.emit()
            return
        if cv2 is None:
            self.failed.emit("OpenCV 未安裝。")
            self.finished.emit()
            return

        # Download / verify model
        try:
            model_path = ensure_face_model(
                _MODELS_DIR,
                status_cb=lambda s: self.status_changed.emit(s),
            )
        except Exception as exc:
            self.failed.emit(f"MediaPipe 模型下載失敗：{exc}")
            self.finished.emit()
            return

        # Build Face Landmarker options
        base_opts = _mp_python.BaseOptions(model_asset_path=str(model_path))
        lm_options = _mp_vision.FaceLandmarkerOptions(
            base_options=base_opts,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=0.55,
            min_face_presence_confidence=0.55,
            min_tracking_confidence=0.60,
            num_faces=1,
            running_mode=_mp_vision.RunningMode.VIDEO,
        )

        engine = RppgEngine(buffer_sec=self._buffer_sec, target_fps=self._target_fps)
        last_face = False
        t_origin: Optional[float] = None
        ts_ms_prev = 0

        self.status_changed.emit("MediaPipe 初始化完成，等待幀資料…")

        with _mp_vision.FaceLandmarker.create_from_options(lm_options) as landmarker:
            while not self._stop:
                # Drain the queue
                try:
                    ts, bgr = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if t_origin is None:
                    t_origin = ts

                # Monotonically increasing ms timestamp required by MediaPipe VIDEO mode
                ts_ms = max(ts_ms_prev + 1, int((ts - t_origin) * 1000))
                ts_ms_prev = ts_ms

                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
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

                annotated = bgr.copy()
                metrics: RppgMetrics

                if has_face:
                    lm = result.face_landmarks[0]
                    transform_matrix = (
                        result.facial_transformation_matrixes[0]
                        if result.facial_transformation_matrixes else None
                    )
                    roll_deg, yaw_deg, pitch_deg, _scale = _pose_from_matrix(
                        transform_matrix, lm, bgr.shape[1], bgr.shape[0]
                    )
                    draw_rois(annotated, lm, transform_matrix)

                    roi_weights = _roi_weights_from_pose(
                        roll_deg, yaw_deg, pitch_deg, lm, bgr.shape[1], bgr.shape[0]
                    )
                    rgbs: list[tuple[float, float, float]] = []
                    weights: list[float] = []
                    for name, indices in ROI_SPECS:
                        val = roi_mean_bgr(bgr, lm, indices, transform_matrix=transform_matrix)
                        weight = roi_weights.get(name, 0.0)
                        if val is not None and weight > 0.0:
                            rgbs.append(val)
                            weights.append(weight)

                    if rgbs:
                        total_w = sum(weights) or float(len(rgbs))
                        r_avg = sum(x[0] * w for x, w in zip(rgbs, weights)) / total_w
                        g_avg = sum(x[1] * w for x, w in zip(rgbs, weights)) / total_w
                        b_avg = sum(x[2] * w for x, w in zip(rgbs, weights)) / total_w
                        engine.push(ts, r_avg, g_avg, b_avg)

                    roi_valid_count = len(rgbs)
                    metrics = engine.compute(
                        ts,
                        bgr,
                        lm,
                        transform_matrix=transform_matrix,
                        roi_valid_count=roi_valid_count,
                    )
                    metrics.roi_valid_count = roi_valid_count
                    metrics.face_detected = True

                    # Emit status
                    if metrics.warmup_progress < 1.0:
                        pct = int(metrics.warmup_progress * 100)
                        self.status_changed.emit(f"暖機中… {pct}%")
                    else:
                        conf_zh = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}.get(
                            metrics.hrv_confidence, metrics.hrv_confidence
                        )
                        self.status_changed.emit(
                            f"❤  {metrics.bpm:.0f} BPM  │  HRV 信心：{conf_zh}"
                        )
                else:
                    engine.reset()
                    metrics = RppgMetrics(face_detected=False)
                    self.status_changed.emit("未偵測到臉部…")

                self.metrics_ready.emit(metrics)

                # Emit annotated QImage (BGR → RGB → QImage)
                rgb_ann = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                rgb_ann = np.ascontiguousarray(rgb_ann)
                fh, fw = rgb_ann.shape[:2]
                qimg = QImage(
                    rgb_ann.data, fw, fh,
                    rgb_ann.strides[0],
                    QImage.Format.Format_RGB888,
                )
                self.frame_annotated.emit(qimg.copy())

        self.finished.emit()
