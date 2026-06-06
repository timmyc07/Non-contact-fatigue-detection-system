"""
Live rPPG demo: MediaPipe Face Landmarker ROIs + POS pulse + HRV-style metrics.

Metrics (aligned with mediapipe_rppg_system stress_* fields, minus enable flags):
  BPM, RMSSD, SDNN, LF/HF, SQI, stress_prob, stress_status_text,
  HRV confidence, IBI artifact ratio, peak frequency,
  optional waveform + PSD preview, frame brightness.

Usage:
  python -m rppg.demo_rppg_live
  python -m rppg.demo_rppg_live --list-cameras
  python -m rppg.demo_rppg_live --pick
  python -m rppg.demo_rppg_live --camera 1
  python -m rppg.demo_rppg_live --backend msmf   # DroidCam / virtual cams often need MSMF
  python -m rppg.demo_rppg_live --backend v4l2   # Ubuntu / Linux cameras

PowerShell: options belong to Python, e.g. python -m rppg.demo_rppg_live --list-cameras
(not "--list-cameras" alone).

Windows: pygrabber gives DirectShow names; capture may use MSMF first (--backend auto).
Linux: capture uses V4L2 first when available (--backend auto).
First run downloads face_landmarker.task into ./models/ if missing.
"""

from __future__ import annotations

import argparse
import platform
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, cast

import cv2
import numpy as np

from rppg.rppg_worker import (
    FACE_OVAL_IDXS,
    _face_center_px,
    _pose_from_matrix,
    _roi_weights_from_pose,
    _rotate_points,
)
from gui.mediapipe_tuning import load_mediapipe_tuning

_IS_WIN = platform.system() == "Windows"
# OpenCV: device description (MSMF / some backends)
_CAP_DEVICE_DESC = getattr(cv2, "CAP_PROP_DEVICE_DESCRIPTION", None)

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

# -----------------------------------------------------------------------------
# Landmark ROI indices (same as mediapipe_rppg_system fatigue_engine.py)
# -----------------------------------------------------------------------------
FOREHEAD_ROI_IDX = [107, 66, 69, 109, 10, 338, 299, 296, 336, 9]
LEFT_CHEEK_ROI_IDX = [118, 119, 100, 126, 209, 49, 129, 203, 205, 50]
RIGHT_CHEEK_ROI_IDX = [347, 348, 329, 355, 429, 279, 358, 423, 425, 280]
GLABELLA_ROI_IDX = [151, 108, 107, 55, 8, 285, 336, 337]

ROI_SPECS = [
    ("forehead", FOREHEAD_ROI_IDX, 0),
    ("L_cheek", LEFT_CHEEK_ROI_IDX, 1),
    ("R_cheek", RIGHT_CHEEK_ROI_IDX, 2),
    ("glabella", GLABELLA_ROI_IDX, 3),
]

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)


def _video_capture_single(index: int, backend: str) -> tuple[Optional[Any], str]:
    """Try one backend. Returns (cap_or_none, tag)."""
    b = backend.lower().strip()
    if b == "dshow":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        return (cap if cap.isOpened() else None), "DSHOW"
    if b == "msmf":
        cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
        return (cap if cap.isOpened() else None), "MSMF"
    if b == "any":
        cap = cv2.VideoCapture(index)
        return (cap if cap.isOpened() else None), "DEFAULT"
    if b == "v4l2":
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        return (cap if cap.isOpened() else None), "V4L2"
    return None, ""


def open_video_capture(index: int, backend: str = "auto") -> tuple[Optional[Any], str]:
    """Open camera; on Windows 'auto' tries MSMF then DSHOW then default (DroidCam often needs MSMF)."""
    b = backend.lower().strip()
    if b != "auto":
        cap, tag = _video_capture_single(index, b)
        return cap, tag

    if not _IS_WIN:
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if cap.isOpened():
            return cap, "V4L2"
        cap = cv2.VideoCapture(index)
        return (cap if cap.isOpened() else None), "DEFAULT"

    for api, tag in (
        (cv2.CAP_MSMF, "MSMF"),
        (cv2.CAP_DSHOW, "DSHOW"),
    ):
        cap = cv2.VideoCapture(index, api)
        if cap.isOpened():
            return cap, tag
    cap = cv2.VideoCapture(index)
    return (cap if cap.isOpened() else None), "DEFAULT"


def _dshow_names_pygrabber() -> list[str]:
    if not _IS_WIN:
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph  # pyright: ignore[reportMissingModuleSource]

        devs = FilterGraph().get_input_devices()
        return [str(x).strip() for x in devs if str(x).strip()]
    except Exception:
        return []


def list_camera_devices(backend: str = "auto") -> list[tuple[int, str]]:
    """Return [(opencv_index, display_name), ...] for devices that actually open."""
    dshow_names = _dshow_names_pygrabber()
    found: list[tuple[int, str]] = []
    for i in range(10):
        cap, _tag = open_video_capture(i, backend)
        if cap is None:
            continue
        label = ""
        if i < len(dshow_names):
            label = dshow_names[i]
        if not label and _CAP_DEVICE_DESC is not None:
            try:
                raw = cap.get(_CAP_DEVICE_DESC)
                if raw and str(raw).strip() and str(raw).lower() != "unknown":
                    label = str(raw).strip()
            except Exception:
                pass
        cap.release()
        if not label:
            label = f"Camera {i}"
        found.append((i, label))
    return found


def resolve_camera_label(
    index: int,
    devices: Optional[list[tuple[int, str]]] = None,
    backend: str = "auto",
) -> str:
    if devices is None:
        devices = list_camera_devices(backend=backend)
    for i, name in devices:
        if i == index:
            return name
    return f"Camera {index}"


def print_camera_list(backend: str = "auto") -> None:
    devices = list_camera_devices(backend=backend)
    if not devices:
        if _IS_WIN:
            print("No cameras detected (try --backend msmf or dshow, different USB port).")
        else:
            print("No cameras detected (try --backend v4l2 or check /dev/video* permissions).")
        return
    print(f"Available cameras (backend={backend!r} for probe):")
    for idx, name in devices:
        print(f"  [{idx}] {name}")


def pick_camera_interactive(backend: str = "auto") -> int:
    devices = list_camera_devices(backend=backend)
    if not devices:
        print("No cameras found; falling back to index 0.")
        return 0
    print("Select camera:")
    for idx, name in devices:
        print(f"  [{idx}] {name}")
    while True:
        try:
            s = input("Enter index (blank = 0): ").strip()
        except EOFError:
            return devices[0][0]
        if not s:
            return devices[0][0]
        try:
            choice = int(s)
        except ValueError:
            print("Invalid number.")
            continue
        valid = {i for i, _ in devices}
        if choice in valid:
            return choice
        print(f"Index {choice} not in {sorted(valid)}.")


def ensure_face_model(models_dir: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / "face_landmarker.task"
    if target.exists() and target.stat().st_size > 1_000_000:
        return target
    print(f"[demo] Downloading Face Landmarker model to {target} ...")
    urllib.request.urlretrieve(MODEL_URL, target)
    return target


def _landmark_xy(lm: Any, idx: int, w: int, h: int) -> tuple[int, int]:
    p = lm[idx]
    x = int(float(p.x) * w)
    y = int(float(p.y) * h)
    return x, y


def roi_mean_bgr(
    frame_bgr: np.ndarray,
    lm: Any,
    indices: list[int],
    blur_ksize: int = 5,
    transform_matrix: Any | None = None,
) -> Optional[tuple[float, float, float]]:
    h, w = frame_bgr.shape[:2]
    pts = np.array([_landmark_xy(lm, i, w, h) for i in indices], dtype=np.float64)
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


def pos_pulse(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Wang et al. style POS on temporally normalized channels."""
    r = np.asarray(r, dtype=np.float64)
    g = np.asarray(g, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    r = (r - np.mean(r)) / (np.std(r) + 1e-8)
    g = (g - np.mean(g)) / (np.std(g) + 1e-8)
    b = (b - np.mean(b)) / (np.std(b) + 1e-8)
    x = 3.0 * r - 2.0 * g
    y = 1.5 * r + g - 1.5 * b
    alpha = float(np.std(x) / (np.std(y) + 1e-8))
    return x - alpha * y


def butter_bandpass(sig: np.ndarray, fs: float, low: float, high: float, order: int = 3):
    from scipy.signal import butter, filtfilt

    nyq = 0.5 * fs
    lo = max(low / nyq, 1e-4)
    hi = min(high / nyq, 0.99)
    if hi <= lo:
        return sig.astype(np.float64)
    b, a = cast(tuple[Any, Any], butter(order, [lo, hi], btype="band"))
    try:
        return filtfilt(b, a, sig.astype(np.float64))
    except ValueError:
        return sig.astype(np.float64)


def welch_peak_hz(sig: np.ndarray, fs: float) -> tuple[float, np.ndarray, np.ndarray]:
    from scipy.signal import welch

    n = len(sig)
    params = _safe_welch_params(n, max_nperseg=256)
    if params is None:
        return 0.0, np.array([]), np.array([])
    nperseg, noverlap = params
    f, pxx = welch(sig, fs=fs, nperseg=nperseg, noverlap=noverlap)
    band = (f >= 0.7) & (f <= 3.5)
    if not np.any(band):
        return 0.0, f, pxx
    ib = np.argmax(pxx[band])
    peak_f = float(f[band][ib])
    return peak_f, f, pxx


def compute_sqi(sig: np.ndarray, fs: float) -> float:
    """Band-power ratio in plausible HR band vs total (0..1)."""
    from scipy.signal import welch

    n = len(sig)
    if n < 32:
        return 0.0
    params = _safe_welch_params(n, max_nperseg=256)
    if params is None:
        return 0.0
    nperseg, noverlap = params
    f, pxx = welch(sig, fs=fs, nperseg=nperseg, noverlap=noverlap)
    total = float(np.sum(pxx)) + 1e-12
    in_band = float(np.sum(pxx[(f >= 0.6) & (f <= 4.0)]))
    return float(np.clip(in_band / total, 0.0, 1.0))


def ibi_from_peaks(sig: np.ndarray, fs: float) -> np.ndarray:
    from scipy.signal import find_peaks

    dist = int(max(3, fs * 0.35))
    prom = float(np.std(sig) * 0.35 + 1e-6)
    peaks, _ = find_peaks(sig, distance=dist, prominence=prom)
    if len(peaks) < 2:
        return np.array([], dtype=np.float64)
    return np.diff(peaks) / fs * 1000.0  # ms


def hrv_time_domain(ibis_ms: np.ndarray) -> tuple[float, float]:
    if ibis_ms.size < 2:
        return 0.0, 0.0
    diff = np.diff(ibis_ms)
    rmssd = float(np.sqrt(np.mean(diff * diff))) if diff.size else 0.0
    sdnn = float(np.std(ibis_ms, ddof=1)) if ibis_ms.size > 1 else 0.0
    return rmssd, sdnn


def ibi_artifact_ratio(ibis_ms: np.ndarray) -> float:
    if ibis_ms.size == 0:
        return 1.0
    good = (ibis_ms >= 300.0) & (ibis_ms <= 2000.0)
    return float(1.0 - np.mean(good.astype(np.float64)))


def lf_hf_from_tachogram(ibis_ms: np.ndarray, fs_resample: float = 4.0) -> float:
    """LF/HF from interpolated tachogram (very short windows = noisy)."""
    from scipy.interpolate import interp1d
    from scipy.signal import welch

    if ibis_ms.size < 8:
        return 0.0
    ibi_s = ibis_ms / 1000.0
    t = np.cumsum(ibi_s)
    t = t - t[0]
    if t[-1] < 4.0:
        return 0.0
    t_uniform = np.arange(0.0, t[-1], 1.0 / fs_resample)
    try:
        f = interp1d(t, ibi_s, kind="linear", fill_value=cast(Any, "extrapolate"))
        series = f(t_uniform)
        series = series - np.mean(series)
    except Exception:
        return 0.0
    params = _safe_welch_params(len(series), max_nperseg=128)
    if params is None:
        return 0.0
    nperseg, noverlap = params
    ff, pxx = welch(series, fs=fs_resample, nperseg=nperseg, noverlap=noverlap)
    lf = float(np.sum(pxx[(ff >= 0.04) & (ff < 0.15)])) + 1e-12
    hf = float(np.sum(pxx[(ff >= 0.15) & (ff <= 0.4)])) + 1e-12
    return float(lf / hf)


def _safe_welch_params(n: int, *, max_nperseg: int, min_nperseg: int = 32) -> tuple[int, int] | None:
    if n < 2:
        return None
    nperseg = min(max_nperseg, max(min_nperseg, n // 2), n)
    noverlap = min(nperseg // 2, nperseg - 1)
    if nperseg < 2 or noverlap >= nperseg:
        return None
    return int(nperseg), int(noverlap)


def stress_heuristic(lf_hf: float, rmssd: float) -> tuple[float, str]:
    """Toy mapping for demo overlay (not clinical)."""
    if lf_hf <= 0 or rmssd <= 0:
        return 0.0, "calibrating"
    # Higher LF/HF & lower RMSSD often associated with stress in coarse screens
    lf_term = np.clip((lf_hf - 1.2) / 2.5, 0.0, 1.0)
    rm_term = np.clip((65.0 - rmssd) / 65.0, 0.0, 1.0)
    prob = float(np.clip(0.45 * lf_term + 0.55 * rm_term, 0.0, 1.0))
    if prob < 0.35:
        label = "low_tension"
    elif prob < 0.6:
        label = "moderate"
    else:
        label = "high_tension"
    return prob, label


def hrv_confidence(n_ibis: int, sqi: float, art_ratio: float) -> str:
    if n_ibis < 6 or sqi < 0.25 or art_ratio > 0.35:
        return "LOW"
    if n_ibis < 12 or sqi < 0.45 or art_ratio > 0.15:
        return "MEDIUM"
    return "HIGH"


@dataclass
class Metrics:
    bpm: float = 0.0
    rmssd: float = 0.0
    sdnn: float = 0.0
    lf_hf: float = 0.0
    sqi: float = 0.0
    stress_prob: float = 0.0
    stress_status: str = "-"
    hrv_confidence: str = "LOW"
    ibi_artifact_ratio: float = 0.0
    peak_freq_hz: float = 0.0
    frame_brightness: float = 0.0
    warmup_progress: float = 0.0
    quality_score: float = 0.0
    pose_roll_deg: float = 0.0
    pose_yaw_deg: float = 0.0
    pose_pitch_deg: float = 0.0
    roi_valid_count: int = 0
    waveform: list[float] | None = None
    psd_freqs: list[float] | None = None
    psd_vals: list[float] | None = None


class RppgDemo:
    def __init__(self, buffer_sec: float = 12.0, target_fps: float = 30.0):
        self.buffer_sec = buffer_sec
        self.target_fps = target_fps
        self._r: deque[float] = deque(maxlen=100000)
        self._g: deque[float] = deque(maxlen=100000)
        self._b: deque[float] = deque(maxlen=100000)
        self._t: deque[float] = deque(maxlen=100000)
        self._last_fs: float = target_fps
        self._prev_face_center: tuple[float, float] | None = None
        self._prev_face_center_t: float | None = None
        self._face_motion_speed: float = 0.0

    def reset(self) -> None:
        self._r.clear()
        self._g.clear()
        self._b.clear()
        self._t.clear()
        self._prev_face_center = None
        self._prev_face_center_t = None
        self._face_motion_speed = 0.0

    def push(self, t: float, r: float, g: float, b: float) -> None:
        self._r.append(r)
        self._g.append(g)
        self._b.append(b)
        self._t.append(t)

    def _trim_buffer(self, t_now: float) -> None:
        cutoff = t_now - self.buffer_sec
        while self._t and self._t[0] < cutoff:
            self._t.popleft()
            self._r.popleft()
            self._g.popleft()
            self._b.popleft()

    def estimate_fs(self) -> float:
        if len(self._t) < 5:
            return self.target_fps
        dt = (self._t[-1] - self._t[0]) / (len(self._t) - 1)
        if dt <= 1e-6:
            return self.target_fps
        fs = 1.0 / dt
        self._last_fs = float(np.clip(fs, 8.0, 90.0))
        return self._last_fs

    def compute(
        self,
        t_now: float,
        frame_bgr: np.ndarray,
        lm: Any,
        transform_matrix: Any | None = None,
        roi_valid_count: int | None = None,
    ) -> Metrics:
        self._trim_buffer(t_now)
        fs = self.estimate_fs()
        n = len(self._t)
        need = int(fs * max(6.0, self.buffer_sec * 0.5))
        warm = min(1.0, n / max(need, 1))
        roi_valid_ratio = (
            (roi_valid_count if roi_valid_count is not None else len(ROI_SPECS))
            / max(len(ROI_SPECS), 1)
        )

        face_center = _face_center_px(lm, frame_bgr.shape[1], frame_bgr.shape[0])
        if self._prev_face_center is not None and self._prev_face_center_t is not None:
            dt_center = t_now - self._prev_face_center_t
            if dt_center > 1e-4:
                self._face_motion_speed = float(
                    np.hypot(face_center[0] - self._prev_face_center[0], face_center[1] - self._prev_face_center[1])
                    / dt_center
                )
        self._prev_face_center = face_center
        self._prev_face_center_t = t_now

        face_w = float(np.ptp(np.array([_landmark_xy(lm, i, frame_bgr.shape[1], frame_bgr.shape[0])[0] for i in FACE_OVAL_IDXS], dtype=np.float64))) + 1e-6
        face_h = float(np.ptp(np.array([_landmark_xy(lm, i, frame_bgr.shape[1], frame_bgr.shape[0])[1] for i in FACE_OVAL_IDXS], dtype=np.float64))) + 1e-6
        roll_deg, yaw_deg, pitch_deg, _ = _pose_from_matrix(
            transform_matrix, lm, frame_bgr.shape[1], frame_bgr.shape[0]
        )

        br_mean = roi_mean_bgr(frame_bgr, lm, FOREHEAD_ROI_IDX, transform_matrix=transform_matrix)
        brightness = float(br_mean[1]) if br_mean else -1.0

        if n < int(fs * 4):
            pose_q = float(np.clip(
                0.40 * (1.0 - abs(roll_deg) / 48.0)
                + 0.35 * (1.0 - abs(yaw_deg) / 48.0)
                + 0.25 * (1.0 - max(0.0, abs(pitch_deg) - 6.0) / 38.0),
                0.0, 1.0,
            ))
            return Metrics(
                frame_brightness=brightness,
                warmup_progress=warm,
                quality_score=pose_q,
                pose_roll_deg=roll_deg,
                pose_yaw_deg=yaw_deg,
                pose_pitch_deg=pitch_deg,
                roi_valid_count=int(roi_valid_count or 0),
                hrv_confidence="LOW",
            )

        r = np.array(self._r, dtype=np.float64)
        g = np.array(self._g, dtype=np.float64)
        b = np.array(self._b, dtype=np.float64)
        raw = pos_pulse(r, g, b)
        low_hz, high_hz = 0.65, 3.7  # ~39–222 bpm
        filt = butter_bandpass(raw, fs, low_hz, high_hz)
        peak_f, freqs, pxx = welch_peak_hz(filt, fs)
        bpm = peak_f * 60.0 if peak_f > 0 else 0.0
        sqi = compute_sqi(filt, fs)

        ibis = ibi_from_peaks(filt, fs)
        art = ibi_artifact_ratio(ibis)
        ibis_clean = ibis[(ibis >= 300.0) & (ibis <= 2000.0)]
        rmssd, sdnn = hrv_time_domain(ibis_clean)
        lf_hf = lf_hf_from_tachogram(ibis_clean)
        prob, st_label = stress_heuristic(lf_hf, rmssd)
        conf = hrv_confidence(ibis_clean.size, sqi, art)
        signal_q = float(np.clip(0.60 * sqi + 0.40 * (1.0 - art), 0.0, 1.0))
        pose_q = float(np.clip(
            0.40 * (1.0 - abs(roll_deg) / 48.0)
            + 0.35 * (1.0 - abs(yaw_deg) / 48.0)
            + 0.25 * (1.0 - max(0.0, abs(pitch_deg) - 6.0) / 38.0),
            0.0, 1.0,
        ))
        motion_q = float(np.clip(1.0 - (self._face_motion_speed / max(face_h, 1e-6)) / 0.85, 0.0, 1.0))
        coverage_q = float(np.clip((face_w * face_h) / max(1.0, frame_bgr.shape[0] * frame_bgr.shape[1] * 0.08), 0.0, 1.0))
        coverage_q = float(np.clip(0.65 * coverage_q + 0.35 * roi_valid_ratio, 0.0, 1.0))
        quality_score = float(np.clip(0.30 * pose_q + 0.25 * motion_q + 0.25 * coverage_q + 0.20 * signal_q, 0.0, 1.0))

        wf_n = min(160, filt.size)
        wave = filt[-wf_n:].copy()
        if np.std(wave) > 1e-9:
            wave = (wave - np.mean(wave)) / np.std(wave)
        else:
            wave = wave * 0.0

        psd_mask = (freqs >= 0.5) & (freqs <= 4.0)
        pf = freqs[psd_mask]
        pv = pxx[psd_mask]
        if pf.size > 64:
            step = pf.size // 64
            pf = pf[::step]
            pv = pv[::step]

        return Metrics(
            bpm=float(bpm),
            rmssd=float(rmssd),
            sdnn=float(sdnn),
            lf_hf=float(lf_hf),
            sqi=float(sqi),
            stress_prob=float(prob),
            stress_status=st_label,
            hrv_confidence=conf,
            ibi_artifact_ratio=float(art),
            peak_freq_hz=float(peak_f),
            frame_brightness=brightness,
            warmup_progress=float(warm),
            quality_score=quality_score,
            pose_roll_deg=roll_deg,
            pose_yaw_deg=yaw_deg,
            pose_pitch_deg=pitch_deg,
            roi_valid_count=int(roi_valid_count or 0),
            waveform=[float(x) for x in wave],
            psd_freqs=[float(x) for x in pf],
            psd_vals=[float(x) for x in pv],
        )


def draw_metrics_panel(
    canvas: np.ndarray,
    m: Metrics,
    x0: int,
    panel_w: int,
    *,
    fps_live: float = 0.0,
    fps_nominal: float = 0.0,
    camera_idx: int = 0,
    camera_name: str = "",
) -> None:
    """Draw text + mini waveform on right panel."""
    h, w = canvas.shape[:2]
    cv2.rectangle(canvas, (x0, 0), (w - 1, h - 1), (24, 24, 24), -1)
    y = 22
    dy = 18
    font = cv2.FONT_HERSHEY_SIMPLEX
    cn = camera_name if len(camera_name) <= 34 else camera_name[:31] + "..."
    fps_drv = f"{fps_nominal:.0f} Hz" if fps_nominal > 1.0 else "n/a"
    lines = [
        "rPPG demo (POS + MP ROI)",
        f"Cam [{camera_idx}]: {cn}",
        f"FPS: {fps_live:4.1f} live, drv {fps_drv}",
        f"BPM: {m.bpm:5.1f}  peak: {m.peak_freq_hz:.2f} Hz",
        f"RMSSD: {m.rmssd:5.1f} ms  SDNN: {m.sdnn:5.1f} ms",
        f"LF/HF: {m.lf_hf:5.2f}  SQI: {m.sqi:.2f}",
        f"Quality: {m.quality_score:.2f}  Pose R/Y/P: {m.pose_roll_deg:+.0f}/{m.pose_yaw_deg:+.0f}/{m.pose_pitch_deg:+.0f}",
        f"HRV conf: {m.hrv_confidence}  IBI art: {m.ibi_artifact_ratio:.2f}",
        f"stress_p: {m.stress_prob:.2f}  ({m.stress_status})",
        f"ROI Y (mean G): {m.frame_brightness:5.1f}",
        f"warmup: {m.warmup_progress * 100:.0f}%",
    ]
    for i, line in enumerate(lines):
        col = (220, 220, 220) if i > 0 else (120, 220, 255)
        cv2.putText(canvas, line, (x0 + 8, y + i * dy), font, 0.45, col, 1, cv2.LINE_AA)

    # Mini waveform
    if m.waveform and len(m.waveform) > 3:
        wx0 = x0 + 8
        wy0 = h // 2 - 20
        ww = panel_w - 16
        wh = h // 2 - 40
        cv2.rectangle(canvas, (wx0, wy0), (wx0 + ww, wy0 + wh), (60, 60, 60), 1)
        wf = np.array(m.waveform, dtype=np.float64)
        xs = np.linspace(0, ww - 1, len(wf))
        ys = (wh / 2) * (1.0 - np.clip(wf, -2.5, 2.5) / 2.5) + wy0
        pts = np.stack([xs, ys], axis=1).astype(np.int32)
        cv2.polylines(canvas, [pts], False, (80, 220, 120), 1, cv2.LINE_AA)
        cv2.putText(canvas, "bandpassed pulse", (wx0, wy0 - 6), font, 0.4, (160, 160, 160), 1, cv2.LINE_AA)

    # Mini PSD
    if m.psd_freqs and m.psd_vals and len(m.psd_freqs) > 2:
        wx0 = x0 + 8
        wy0 = h - 120
        ww = panel_w - 16
        wh = 100
        cv2.rectangle(canvas, (wx0, wy0), (wx0 + ww, wy0 + wh), (60, 60, 60), 1)
        pf = np.array(m.psd_freqs, dtype=np.float64)
        pv = np.array(m.psd_vals, dtype=np.float64)
        pv = pv / (np.max(pv) + 1e-12)
        xs = (pf - 0.5) / 3.5 * (ww - 4) + 2 + wx0
        ys = wy0 + wh - 3 - pv * (wh - 6)
        pts = np.stack([xs, ys], axis=1).astype(np.int32)
        cv2.polylines(canvas, [pts], False, (200, 140, 80), 1, cv2.LINE_AA)
        cv2.putText(canvas, "PSD 0.5-4 Hz", (wx0, wy0 - 6), font, 0.4, (160, 160, 160), 1, cv2.LINE_AA)


def draw_rois(frame: np.ndarray, lm: Any, transform_matrix: Any | None = None) -> None:
    h, w = frame.shape[:2]
    center = _face_center_px(lm, w, h)
    roll_deg, _, _, _ = _pose_from_matrix(transform_matrix, lm, w, h)
    for _name, indices, _rid in ROI_SPECS:
        pts = np.array([_landmark_xy(lm, i, w, h) for i in indices], dtype=np.float64)
        if transform_matrix is not None:
            pts = _rotate_points(pts, center, -roll_deg)
        pts = np.round(pts).astype(np.int32)
        if pts.shape[0] >= 3:
            cv2.polylines(frame, [pts], True, (0, 200, 255), 1, cv2.LINE_AA)


def draw_capture_overlay(
    frame: np.ndarray,
    *,
    camera_idx: int,
    camera_name: str,
    fps_live: float,
    fps_nominal: float,
) -> None:
    """Device name + measured / reported FPS on video (top-left)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    name_short = camera_name if len(camera_name) <= 52 else camera_name[:49] + "..."
    line1 = f"[{camera_idx}] {name_short}"
    if fps_nominal > 1.0:
        line2 = f"FPS: {fps_live:4.1f}  (device {fps_nominal:.0f})"
    else:
        line2 = f"FPS: {fps_live:4.1f}  (device n/a)"
    x, y = 8, 22
    for i, txt in enumerate((line1, line2)):
        ty = y + i * 22
        cv2.putText(frame, txt, (x + 1, ty + 1), font, 0.5, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, txt, (x, ty), font, 0.5, (0, 255, 255), 1, cv2.LINE_AA)


def run(camera_id: int, camera_label: str, backend: str = "auto") -> None:
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = ensure_face_model(Path(__file__).resolve().parents[1] / "models")
    tuning = load_mediapipe_tuning()
    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        min_face_detection_confidence=tuning.face_landmarker.min_face_detection_confidence,
        min_face_presence_confidence=tuning.face_landmarker.min_face_presence_confidence,
        min_tracking_confidence=tuning.face_landmarker.min_tracking_confidence,
        num_faces=max(1, int(tuning.face_landmarker.num_faces)),
        running_mode=vision.RunningMode.VIDEO,
    )

    cap, cap_backend = open_video_capture(camera_id, backend)
    if cap is None:
        print(
            f"Cannot open camera index {camera_id} with backend={backend!r}. "
            f"Try: python -m rppg.demo_rppg_live --list-cameras --backend auto"
        )
        print("  Virtual cameras (e.g. DroidCam): --backend msmf")
        return
    print(f"Capture backend: {cap_backend}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    fps_from_device = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    panel_w = 300
    demo = RppgDemo(buffer_sec=12.0, target_fps=max(30.0, fps_from_device or 30.0))

    with vision.FaceLandmarker.create_from_options(options) as landmarker:
        t0 = time.perf_counter()
        last_metrics = Metrics()
        fps_live = 0.0
        prev_t = time.perf_counter()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now_wall = time.perf_counter()
            dt = now_wall - prev_t
            prev_t = now_wall
            if dt > 1e-6:
                inst = 1.0 / dt
                fps_live = 0.92 * fps_live + 0.08 * inst if fps_live > 0.1 else inst

            frame = cv2.flip(frame, 1)
            draw_capture_overlay(
                frame,
                camera_idx=camera_id,
                camera_name=camera_label,
                fps_live=fps_live,
                fps_nominal=fps_from_device,
            )
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            now = now_wall - t0
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame_rgb))
            ts_ms = int(now * 1000)
            result = landmarker.detect_for_video(mp_image, ts_ms)

            display = frame.copy()
            lm = None
            if result.face_landmarks:
                lm = result.face_landmarks[0]
                transform_matrix = (
                    result.facial_transformation_matrixes[0]
                    if result.facial_transformation_matrixes else None
                )
                draw_rois(display, lm, transform_matrix)
                roll_deg, yaw_deg, pitch_deg, _ = _pose_from_matrix(
                    transform_matrix, lm, frame.shape[1], frame.shape[0]
                )
                roi_weights = _roi_weights_from_pose(
                    roll_deg, yaw_deg, pitch_deg, lm, frame.shape[1], frame.shape[0], tuning
                )

                rgbs: list[tuple[float, float, float]] = []
                weights: list[float] = []
                for _name, indices, _rid in ROI_SPECS:
                    m = roi_mean_bgr(frame, lm, indices, transform_matrix=transform_matrix)
                    weight = roi_weights.get(_name, 0.0)
                    if m and weight > 0.0:
                        rgbs.append(m)
                        weights.append(weight)
                if rgbs:
                    total_w = sum(weights) or float(len(rgbs))
                    r = sum(x[0] * w for x, w in zip(rgbs, weights)) / total_w
                    g = sum(x[1] * w for x, w in zip(rgbs, weights)) / total_w
                    b = sum(x[2] * w for x, w in zip(rgbs, weights)) / total_w
                    demo.push(now, r, g, b)
                    last_metrics = demo.compute(
                        now,
                        frame,
                        lm,
                        transform_matrix=transform_matrix,
                        roi_valid_count=len(rgbs),
                    )
            else:
                demo.reset()

            canvas = np.zeros((h, w + panel_w, 3), dtype=np.uint8)
            canvas[:, :w] = display
            draw_metrics_panel(
                canvas,
                last_metrics,
                w,
                panel_w,
                fps_live=fps_live,
                fps_nominal=fps_from_device,
                camera_idx=camera_id,
                camera_name=camera_label,
            )

            cv2.imshow("rPPG demo (q=quit)", canvas)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser(description="MediaPipe ROI + POS rPPG demo")
    ap.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Device index (see --list-cameras). Default: first device or 0.",
    )
    ap.add_argument(
        "--list-cameras",
        action="store_true",
        help="Print detected cameras with names and exit",
    )
    ap.add_argument(
        "--pick",
        action="store_true",
        help="Prompt to choose a camera on startup",
    )
    ap.add_argument(
        "--backend",
        type=str,
        default="auto",
        choices=("auto", "msmf", "dshow", "v4l2", "any"),
        help="Video capture API (Windows: auto=MSMF then DSHOW; Linux: auto=V4L2 then default)",
    )
    args = ap.parse_args()
    be = args.backend
    if args.list_cameras:
        print_camera_list(backend=be)
        return

    devices = list_camera_devices(backend=be)
    if args.pick:
        cam_id = pick_camera_interactive(backend=be)
    elif args.camera is not None:
        cam_id = args.camera
    elif devices:
        cam_id = devices[0][0]
    else:
        cam_id = 0

    label = resolve_camera_label(cam_id, devices if devices else None, backend=be)
    print(f"Opening camera [{cam_id}] {label}")
    run(cam_id, label, backend=be)


if __name__ == "__main__":
    main()
