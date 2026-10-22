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

import logging
import math
import os
import queue
import sys
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, cast

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision
from scipy.interpolate import interp1d as _scipy_interp1d
from scipy.signal import butter, filtfilt, find_peaks, sosfiltfilt, welch

from gui.frame_queue import get_latest
from gui.mediapipe_tuning import MediaPipeTuning, load_mediapipe_tuning
from gui.model_assets import MODEL_URL, download_face_model
from gui.runtime_paths import data_path, resource_path
from gui.platforms import (
    create_face_landmarker_base_options,
    validate_mediapipe_runtime,
)
from gui.worker_safety import fail_closed_worker
from rppg.adaptive_calibration import recompute_raw_bpm_from_roi_windows
from rppg.belt_truth_capture import BeltTruthCaptureWriter
from rppg.rppg_hrv_engine import compute_rppg_hrv_from_pulse, hrv_confidence_rppg

_HAS_MP = True
_HAS_SCIPY = True
_ANNOTATED_PREVIEW_MAX_FPS = 30.0

log = logging.getLogger(__name__)

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

# P6b-2：套用心跳帶有護欄自適應學到的 ROI base_weights 時，個別 ROI 正規化後
# 佔比的護欄範圍——避免單一 ROI 因候選權重異常而近乎獨佔（進而使其餘 ROI 在
# `_roi_weights_from_pose` 的姿態/遮蔽衰減後被 `min_roi_weight` 門檻完全排除），
# 同時仍允許有意義的重新配重。範圍本身是可討論的設計取捨，
# 見 docs/2026-07-04-p6b-handoff.md 的 P6b-2 clamp/正規化語意說明。
ROI_WEIGHT_OVERRIDE_MIN_FRACTION = 0.05
ROI_WEIGHT_OVERRIDE_MAX_FRACTION = 0.70


def resolve_roi_weights_override(
    rppg_params: Mapping[str, Any] | None,
) -> Optional[dict[str, float]]:
    """從 ``CalibrationParams.rppg_params`` 解析 ROI base_weights 覆寫（P6b-2）。

    Schema：``{"roi_weights": {"forehead": float, "L_cheek": float,
    "R_cheek": float, "glabella": float}}``（鍵名須與 :data:`ROI_SPECS` 完全
    一致，多一個或少一個都視為不完整集合）。

    回傳值：驗證通過時回傳 clamp 後正規化（總和為 1.0，與 ``RppgRoiTuning
    .base_weights`` 預設的語意一致）的 4-ROI dict；``rppg_params`` 為 None/空、
    或任何欄位異常（缺 ROI、含未知 ROI 名稱、非數值、NaN/Inf、非正值）一律
    回傳 None——**不做部分套用**，任一欄位異常即整組覆寫失效並記 warning，
    呼叫端應以 None 視為「維持現行 tuning，不覆寫」。本函式純運算、不丟例外。
    """
    if not rppg_params:
        return None
    if not isinstance(rppg_params, Mapping):
        log.warning("rppg_params 型別非 dict（%r），忽略 ROI 權重覆寫", type(rppg_params))
        return None
    raw = rppg_params.get("roi_weights")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        log.warning("rppg_params.roi_weights 型別非 dict（%r），忽略 ROI 權重覆寫", type(raw))
        return None

    expected_names = {name for name, _ in ROI_SPECS}
    given_names = set(raw.keys())
    if given_names != expected_names:
        log.warning(
            "rppg_params.roi_weights ROI 名稱不完整或含未知名稱（預期 %s，收到 %s），"
            "忽略整組 ROI 權重覆寫",
            sorted(expected_names), sorted(given_names),
        )
        return None

    values: dict[str, float] = {}
    for name in expected_names:
        raw_v = raw[name]
        try:
            fv = float(raw_v)
        except (TypeError, ValueError):
            log.warning(
                "rppg_params.roi_weights[%s]=%r 非數值，忽略整組 ROI 權重覆寫", name, raw_v
            )
            return None
        if not math.isfinite(fv) or fv <= 0.0:
            log.warning(
                "rppg_params.roi_weights[%s]=%r 非正值或非有限值，忽略整組 ROI 權重覆寫",
                name, fv,
            )
            return None
        values[name] = fv

    total = sum(values.values())
    if total <= 0.0:
        log.warning("rppg_params.roi_weights 總和非正，忽略整組 ROI 權重覆寫")
        return None

    fractions = {k: v / total for k, v in values.items()}
    return _project_fractions_onto_bounds(
        fractions, ROI_WEIGHT_OVERRIDE_MIN_FRACTION, ROI_WEIGHT_OVERRIDE_MAX_FRACTION
    )


def _project_fractions_onto_bounds(
    fractions: dict[str, float], lo: float, hi: float
) -> dict[str, float]:
    """把已正規化（總和 1.0）的比例投影到 [lo, hi] 範圍內，投影後總和仍為 1.0。

    單純「clamp 後再除以新總和」在多個值同時被 clamp 到同一邊界時，重新正規化
    會把已 clamp 的值再度推出邊界（例：一個 ROI 給極端大值、其餘給極小值時，
    三個下限違規與一個上限違規若同時固定，會使上限違規者吃下全部剩餘 budget
    而再度超過 hi）。這裡改用疊代水位法：每輪只固定「偏離邊界最遠」的單一
    元素在其邊界值，其餘元素依剩餘比例分攤剩餘總和（1.0 減去已固定值）後
    重新檢查，直到沒有元素再違反邊界或只剩一個自由元素。每輪固定恰好一個
    元素，故最多疊代 n-1 輪（n=元素數）即收斂。僅在 ``lo * n <= 1.0 <= hi * n``
    時保證收斂到界內；本專案預設邊界（0.05~0.70，n=4）滿足此條件。
    """
    fixed: dict[str, float] = {}
    free = dict(fractions)
    while free:
        budget = 1.0 - sum(fixed.values())
        if len(free) == 1:
            (only_key,) = free.keys()
            fixed[only_key] = budget
            free = {}
            break
        free_total = sum(free.values())
        if free_total <= 0.0:
            # 數值退化（剩餘元素原始比例都趨近 0）：均分剩餘 budget 作為安全回退。
            share = budget / len(free)
            for k in free:
                fixed[k] = share
            free = {}
            break
        scale = budget / free_total
        scaled = {k: v * scale for k, v in free.items()}
        violators = {k: v for k, v in scaled.items() if v < lo or v > hi}
        if not violators:
            fixed.update(scaled)
            free = {}
            break
        # 只固定本輪偏離邊界最遠的單一元素，避免一次固定多個造成總和跑掉
        # （其餘違規元素留到下一輪，以更新後的 budget/free_total 重新評估）。
        worst_key = max(
            violators,
            key=lambda k: (lo - violators[k]) if violators[k] < lo else (violators[k] - hi),
        )
        worst_val = scaled[worst_key]
        fixed[worst_key] = lo if worst_val < lo else hi
        del free[worst_key]
    return fixed


def apply_roi_weights_override(
    tuning: MediaPipeTuning,
    override: Optional[dict[str, float]],
) -> MediaPipeTuning:
    """套用（或不套用）ROI base_weights 覆寫，回傳供 rPPG ROI 抽取使用的 tuning。

    ``override`` 為 None 時原樣回傳 ``tuning``（同一物件，不複製、不建立新
    dataclass 實例），確保呼叫端在無覆寫時的程式路徑與輸出逐位元不變。僅在
    ``override`` 非 None 時才建立 ``rppg_roi.base_weights`` 已替換的淺拷貝，
    其餘 tuning 欄位（含 ``face_landmarker``、``quality`` 等）保持原值。
    """
    if override is None:
        return tuning
    return replace(tuning, rppg_roi=replace(tuning.rppg_roi, base_weights=dict(override)))


def resolve_effective_rppg_tuning(
    tuning: MediaPipeTuning,
    explicit_override: Optional[dict[str, float]],
    calibration_loader: Optional[Callable[[], object]],
) -> MediaPipeTuning:
    """P6b-2：worker 啟動時解析一次「供 rPPG ROI 抽取使用」的 tuning。

    優先序：``explicit_override`` 非 None 時直接採用（供測試／呼叫端明確指定）；
    否則若提供 ``calibration_loader``，呼叫一次取得目前 active 校準版本並解析其
    ``params.rppg_params``。loader 例外、無版本、無 ``rppg_params``、或驗證未通過
    （見 :func:`resolve_roi_weights_override`）皆視為「無覆寫」。

    只呼叫 ``calibration_loader`` 一次，供 worker ``run()`` 在進入逐幀迴圈前呼叫，
    不做逐幀重新解析／熱切換（P6b-3 範疇）。無覆寫時回傳原始 ``tuning`` 物件
    （不複製），確保呼叫端沿用既有 ``self._tuning`` 的程式路徑與輸出逐位元不變。
    """
    override = explicit_override
    if override is None and calibration_loader is not None:
        try:
            version = calibration_loader()
        except Exception:
            log.warning("rPPG 校準版本載入失敗，略過 ROI 權重覆寫解析", exc_info=True)
            version = None
        params = getattr(version, "params", None) if version is not None else None
        rppg_params = getattr(params, "rppg_params", None) if params is not None else None
        override = resolve_roi_weights_override(rppg_params)
    return apply_roi_weights_override(tuning, override)


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
FACE_STABILITY_IDXS = sorted(set(
    FACE_OVAL_IDXS
    + FOREHEAD_ROI_IDX
    + LEFT_CHEEK_ROI_IDX
    + RIGHT_CHEEK_ROI_IDX
    + GLABELLA_ROI_IDX
    + [33, 263, NOSE_TIP_IDX]
))

_MODELS_DIR = resource_path("models")


# ── Metrics dataclass ────────────────────────────────────────────────────────

@dataclass
class RppgMetrics:
    bpm:               float = 0.0
    raw_bpm:           float = 0.0
    bpm_delta:         float = 0.0
    bpm_guarded:       bool  = False
    bpm_guard_reason:  str   = ""
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
    landmark_jitter_norm:  float = 0.0
    roi_area_stability:    float = 1.0
    roi_area_jitter_ratio: float = 0.0
    roi_smoothing_applied: bool = False
    canonical_roi_warp_used: bool = False
    face_detected:     bool  = False
    bpm_calibrated:    float = 0.0
    calibration_version_id: str = ""
    peak_freq_hz_calibrated: float = 0.0
    waveform:  list[float] = field(default_factory=list)
    psd_freqs: list[float] = field(default_factory=list)
    psd_vals:  list[float] = field(default_factory=list)
    # 恆為 "rppg"。手錶接觸式量測與其轉接層（watch_adapter/watch_hrv）已移除；
    # 心跳帶真值走 belt 校準路徑，不經此欄位。列舉值僅保留向後相容。
    physio_source: str = "rppg"   # "rppg"


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


def _face_diag_px(lm: Any, w: int, h: int) -> float:
    xs = np.array([_lm_xy(lm, i, w, h)[0] for i in FACE_OVAL_IDXS], dtype=np.float64)
    ys = np.array([_lm_xy(lm, i, w, h)[1] for i in FACE_OVAL_IDXS], dtype=np.float64)
    if xs.size == 0 or ys.size == 0:
        return 1.0
    return float(np.hypot(np.ptp(xs), np.ptp(ys)) + 1e-6)


def _face_center_px(lm: Any, w: int, h: int) -> tuple[float, float]:
    pts = np.array([_lm_xy(lm, idx, w, h) for idx in FACE_OVAL_IDXS], dtype=np.float64)
    if pts.size == 0:
        return 0.0, 0.0
    return float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))


def _polygon_area(pts: np.ndarray) -> float:
    if pts.shape[0] < 3:
        return 0.0
    x = pts[:, 0].astype(np.float64)
    y = pts[:, 1].astype(np.float64)
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) * 0.5)


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


def _pose_normalized_points(
    pts: np.ndarray,
    center: tuple[float, float],
    yaw_deg: float,
    pitch_deg: float,
    strength: float,
) -> np.ndarray:
    """Experimental, disabled-by-default ROI geometry normalization."""
    if pts.shape[0] < 3 or strength <= 1e-6:
        return pts
    strength = _clamp(strength, 0.0, 0.60)
    yaw_scale = 1.0 + strength * min(abs(yaw_deg), 45.0) / 180.0
    pitch_scale = 1.0 + strength * min(abs(pitch_deg), 45.0) / 220.0
    ctr = np.array(center, dtype=np.float64)
    out = pts.astype(np.float64) - ctr
    out[:, 0] *= yaw_scale
    out[:, 1] *= pitch_scale
    return out + ctr


class RoiGeometryTracker:
    """Track MediaPipe ROI geometry stability and apply conservative smoothing."""

    def __init__(self) -> None:
        self._smoothed_roi_pts: dict[str, np.ndarray] = {}
        self.last_roi_pts: dict[str, np.ndarray] = {}
        self._prev_landmark_pts: np.ndarray | None = None
        self._prev_roi_area_ratio: float | None = None
        self.landmark_jitter_norm: float = 0.0
        self.roi_area_jitter_ratio: float = 0.0
        self.roi_area_stability: float = 1.0
        self.roi_smoothing_applied: bool = False
        self.canonical_roi_warp_used: bool = False

    def reset(self) -> None:
        self._smoothed_roi_pts.clear()
        self.last_roi_pts.clear()
        self._prev_landmark_pts = None
        self._prev_roi_area_ratio = None
        self.landmark_jitter_norm = 0.0
        self.roi_area_jitter_ratio = 0.0
        self.roi_area_stability = 1.0
        self.roi_smoothing_applied = False
        self.canonical_roi_warp_used = False

    def begin_frame(self) -> None:
        self.roi_smoothing_applied = False
        self.canonical_roi_warp_used = False
        self.last_roi_pts.clear()

    def update_landmarks(self, lm: Any, w: int, h: int) -> None:
        diag = _face_diag_px(lm, w, h)
        pts = np.array([_lm_xy(lm, idx, w, h) for idx in FACE_STABILITY_IDXS], dtype=np.float64)
        if self._prev_landmark_pts is not None and self._prev_landmark_pts.shape == pts.shape:
            self.landmark_jitter_norm = float(np.mean(np.linalg.norm(pts - self._prev_landmark_pts, axis=1)) / diag)
        else:
            self.landmark_jitter_norm = 0.0
        self._prev_landmark_pts = pts

    def smooth_roi(self, name: str, pts: np.ndarray, face_diag: float, tuning: MediaPipeTuning) -> np.ndarray:
        cfg = tuning.rppg_roi
        if not cfg.roi_smoothing_enabled or pts.shape[0] < 3:
            self._smoothed_roi_pts[name] = pts.copy()
            self.last_roi_pts[name] = pts.copy()
            return pts
        prev = self._smoothed_roi_pts.get(name)
        if prev is None or prev.shape != pts.shape:
            self._smoothed_roi_pts[name] = pts.copy()
            self.last_roi_pts[name] = pts.copy()
            return pts
        shift = float(np.mean(np.linalg.norm(pts - prev, axis=1)) / max(face_diag, 1e-6))
        if shift > cfg.roi_smoothing_max_shift_ratio:
            self._smoothed_roi_pts[name] = pts.copy()
            self.last_roi_pts[name] = pts.copy()
            return pts
        alpha = _clamp(cfg.roi_smoothing_alpha, 0.05, 1.0)
        smoothed = alpha * pts + (1.0 - alpha) * prev
        self._smoothed_roi_pts[name] = smoothed.copy()
        self.last_roi_pts[name] = smoothed.copy()
        self.roi_smoothing_applied = True
        return smoothed

    def update_roi_area(self, areas_px: list[float], frame_area: float, tuning: MediaPipeTuning) -> None:
        area_ratio = float(sum(areas_px) / max(frame_area, 1.0))
        if self._prev_roi_area_ratio is None or self._prev_roi_area_ratio <= 1e-9:
            self.roi_area_jitter_ratio = 0.0
        else:
            self.roi_area_jitter_ratio = abs(area_ratio - self._prev_roi_area_ratio) / self._prev_roi_area_ratio
        self._prev_roi_area_ratio = area_ratio
        full = max(tuning.rppg_roi.roi_area_jitter_full_ratio, 1e-6)
        self.roi_area_stability = _clamp(1.0 - self.roi_area_jitter_ratio / full)


def roi_points(
    frame_bgr: np.ndarray,
    lm: Any,
    indices: list[int],
    name: str,
    transform_matrix: Any | None = None,
    tracker: RoiGeometryTracker | None = None,
    tuning: MediaPipeTuning | None = None,
) -> np.ndarray:
    tuning = tuning or load_mediapipe_tuning()
    h, w = frame_bgr.shape[:2]
    pts = np.array([_lm_xy(lm, i, w, h) for i in indices], dtype=np.float64)
    if pts.shape[0] < 3:
        return pts
    center = _face_center_px(lm, w, h)
    roll_deg, yaw_deg, pitch_deg, _ = _pose_from_matrix(transform_matrix, lm, w, h)
    if transform_matrix is not None:
        pts = _rotate_points(pts, center, -roll_deg)
    if tuning.rppg_roi.canonical_roi_warp_enabled and transform_matrix is not None:
        warped = _pose_normalized_points(
            pts,
            center,
            yaw_deg,
            pitch_deg,
            tuning.rppg_roi.canonical_roi_warp_strength,
        )
        if warped.shape == pts.shape and _polygon_area(warped) >= 30.0:
            pts = warped
            if tracker is not None:
                tracker.canonical_roi_warp_used = True
    if tracker is not None:
        pts = tracker.smooth_roi(name, pts, _face_diag_px(lm, w, h), tuning)
    return pts


def roi_mean_from_points(
    frame_bgr: np.ndarray,
    pts: np.ndarray,
    blur_ksize: int = 5,
) -> Optional[tuple[float, float, float]]:
    h, w = frame_bgr.shape[:2]
    if pts.shape[0] < 3:
        return None
    pts_i = np.round(pts).astype(np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, pts_i, 255)
    if cv2.countNonZero(mask) < 30:
        return None
    roi = cv2.GaussianBlur(frame_bgr, (blur_ksize, blur_ksize), 0)
    mean = cv2.mean(roi, mask=mask)
    return float(mean[2]), float(mean[1]), float(mean[0])


def roi_obstruction_score_from_points(
    frame_bgr: np.ndarray,
    pts: np.ndarray,
    tuning: MediaPipeTuning | None = None,
) -> float:
    cfg = (tuning or load_mediapipe_tuning()).rppg_roi
    h, w = frame_bgr.shape[:2]
    if pts.shape[0] < 3:
        return 1.0
    pts_i = np.round(pts).astype(np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, pts_i, 255)
    if cv2.countNonZero(mask) < 30:
        return 1.0
    mean_b, mean_g, mean_r, _ = cv2.mean(frame_bgr, mask=mask)
    luma = 0.114 * mean_b + 0.587 * mean_g + 0.299 * mean_r
    chroma = float(np.std([mean_b, mean_g, mean_r]))
    dark_penalty = _clamp((cfg.obstruction_dark_luma - luma) / max(cfg.obstruction_dark_luma, 1e-6))
    bright_penalty = _clamp((luma - cfg.obstruction_bright_luma) / max(255.0 - cfg.obstruction_bright_luma, 1e-6))
    low_chroma_penalty = _clamp((cfg.obstruction_low_chroma - chroma) / max(cfg.obstruction_low_chroma, 1e-6))
    high_chroma_penalty = _clamp((chroma - cfg.obstruction_high_chroma) / max(80.0 - cfg.obstruction_high_chroma, 1e-6))
    return float(max(dark_penalty, bright_penalty, low_chroma_penalty, high_chroma_penalty))


def collect_rppg_roi_sample(
    frame_bgr: np.ndarray,
    lm: Any,
    transform_matrix: Any | None,
    tracker: RoiGeometryTracker,
    tuning: MediaPipeTuning,
) -> tuple[Optional[tuple[float, float, float]], dict[str, float], int]:
    h, w = frame_bgr.shape[:2]
    tracker.begin_frame()
    tracker.update_landmarks(lm, w, h)
    roll_deg, yaw_deg, pitch_deg, _ = _pose_from_matrix(transform_matrix, lm, w, h)
    roi_weights = _roi_weights_from_pose(roll_deg, yaw_deg, pitch_deg, lm, w, h, tuning)
    rgbs: list[tuple[float, float, float]] = []
    areas: list[float] = []
    effective_weights: dict[str, float] = {name: 0.0 for name, _ in ROI_SPECS}
    for name, indices in ROI_SPECS:
        if tracker is not None and name in tracker.last_roi_pts:
            pts = tracker.last_roi_pts[name]
        else:
            pts = roi_points(frame_bgr, lm, indices, name, transform_matrix, tracker, tuning)
        areas.append(_polygon_area(pts))
        val = roi_mean_from_points(frame_bgr, pts)
        obstruction = roi_obstruction_score_from_points(frame_bgr, pts, tuning)
        weight = roi_weights.get(name, 0.0) * (1.0 - obstruction)
        if weight < tuning.rppg_roi.min_roi_weight:
            weight = 0.0
        effective_weights[name] = float(weight)
        if val is not None and weight > 0.0:
            rgbs.append(val)
    tracker.update_roi_area(areas, float(h * w), tuning)
    if not rgbs:
        return None, effective_weights, 0
    # Keep the first-version rPPG sampling behavior: valid skin ROIs are
    # averaged equally. The pose/obstruction weights remain diagnostic only.
    sample = (
        sum(x[0] for x in rgbs) / len(rgbs),
        sum(x[1] for x in rgbs) / len(rgbs),
        sum(x[2] for x in rgbs) / len(rgbs),
    )
    norm_total = sum(effective_weights.values()) or 1.0
    effective_weights = {k: float(v / norm_total) if v > 0.0 else 0.0 for k, v in effective_weights.items()}
    return sample, effective_weights, len(rgbs)


def collect_rppg_roi_sample_with_means(
    frame_bgr: np.ndarray,
    lm: Any,
    transform_matrix: Any | None,
    tracker: RoiGeometryTracker,
    tuning: MediaPipeTuning,
    *,
    weighted_mix: bool = False,
) -> tuple[Optional[tuple[float, float, float]], dict[str, float], int, dict[str, tuple[float, float, float]]]:
    """P6b-1 新增：伴生函式（companion），與 collect_rppg_roi_sample() 邏輯完全相同，
    額外回傳每個 ROI 各自的 (R,G,B) 均值 per_roi_means，供之後「候選 ROI 權重對同段
    訊號重算 BPM」做 A/B 使用。

    刻意不修改、也不呼叫 collect_rppg_roi_sample()：tracker（RoiGeometryTracker）
    是每幀狀態機（begin_frame()/update_landmarks()/update_roi_area() 每幀只能推進
    一次），若兩函式在同一幀各呼叫一次會使 jitter/area-stability 狀態被重複推進、
    改變既有數值行為。因此本函式獨立複製一份完全相同的運算，呼叫端每幀應二擇一。

    ``weighted_mix``（P6b-3a 新增）：
    - ``False``（預設）：走原本「有效 ROI 等權平均」路徑。回傳的
      sample/effective_weights/len(rgbs) 與 collect_rppg_roi_sample() 在同一輸入
      下逐位元相同（程式碼與運算順序未變動，only surfaces 額外資訊）。所有既有
      呼叫端（含 replay/golden、live worker run() 迴圈）皆走此路徑，逐位元不變。
    - ``True``：改用「該幀有效權重加權平均」。加權係數即本函式已算出的
      effective_weights（= override base weight × 姿態/遮蔽懲罰，通過 min_roi_weight
      門檻後的值），與 sample 用同一組權重、同一幀訊號，讓候選 ROI 權重能真正影響
      混合後 RGB → 進而影響 BPM（等權語意下候選權重對混合訊號無槓桿，見
      docs/2026-07-04-p6b-handoff.md P6b-3 動機）。**語意約定（P6b-3b 起生效）**：
      呼叫端只有在 P6b-2 的 ROI 權重 override 存在（``rppg_params`` 不是 None，即
      worker 的 ``self._roi_weights_override is not None``）時才傳 ``True``；override
      為 None 時一律用預設 ``False``，確保無 override 路徑逐位元回退等權平均。
      **目前（P6b-3a）尚未有任何生產呼叫端傳入 True**——`RppgWorker.run()`/
      `CombinedWorker` 皆固定用預設 `False` 呼叫，此參數僅供測試與未來 P6b-3b
      接線使用；本次新增不改變任何現行 live 行為。加權係數用正規化前或正規化後
      皆等價（加權平均 sum(w*x)/sum(w) 對權重同比例縮放不變）。
    """
    h, w = frame_bgr.shape[:2]
    tracker.begin_frame()
    tracker.update_landmarks(lm, w, h)
    roll_deg, yaw_deg, pitch_deg, _ = _pose_from_matrix(transform_matrix, lm, w, h)
    roi_weights = _roi_weights_from_pose(roll_deg, yaw_deg, pitch_deg, lm, w, h, tuning)
    rgbs: list[tuple[float, float, float]] = []
    areas: list[float] = []
    effective_weights: dict[str, float] = {name: 0.0 for name, _ in ROI_SPECS}
    per_roi_means: dict[str, tuple[float, float, float]] = {}
    for name, indices in ROI_SPECS:
        if tracker is not None and name in tracker.last_roi_pts:
            pts = tracker.last_roi_pts[name]
        else:
            pts = roi_points(frame_bgr, lm, indices, name, transform_matrix, tracker, tuning)
        areas.append(_polygon_area(pts))
        val = roi_mean_from_points(frame_bgr, pts)
        obstruction = roi_obstruction_score_from_points(frame_bgr, pts, tuning)
        weight = roi_weights.get(name, 0.0) * (1.0 - obstruction)
        if weight < tuning.rppg_roi.min_roi_weight:
            weight = 0.0
        effective_weights[name] = float(weight)
        if val is not None:
            # 記錄每個 ROI 的原始均值，不受當前姿態/遮蔽權重篩選——之後若候選權重
            # 給予目前零權重的 ROI 非零權重，仍能對同段訊號重算 BPM。
            per_roi_means[name] = val
        if val is not None and weight > 0.0:
            rgbs.append(val)
    tracker.update_roi_area(areas, float(h * w), tuning)
    if not rgbs:
        return None, effective_weights, 0, per_roi_means
    # Keep the first-version rPPG sampling behavior: valid skin ROIs are
    # averaged equally. The pose/obstruction weights remain diagnostic only.
    sample = (
        sum(x[0] for x in rgbs) / len(rgbs),
        sum(x[1] for x in rgbs) / len(rgbs),
        sum(x[2] for x in rgbs) / len(rgbs),
    )
    # P6b-3a：override 存在時（呼叫端傳 weighted_mix=True）改用有效權重加權平均。
    # 此處 effective_weights 仍為「正規化前」的門檻後權重；貢獻 ROI 集合
    # {name: effective_weights[name] > 0 且 name in per_roi_means} 與上方等權
    # sample 用的 rgbs 完全一致（rgbs 於 val 非 None 且 weight > 0 時加入），故
    # w_sum 必 > 0（rgbs 非空已在上方保證），if 為安全護欄。原等權 sample 三行
    # 完全未動：weighted_mix=False 時本區塊整段跳過，逐位元回退等權平均。
    if weighted_mix:
        w_sum = 0.0
        acc_r = acc_g = acc_b = 0.0
        for name, _ in ROI_SPECS:
            ew = effective_weights[name]
            rgb = per_roi_means.get(name)
            if ew > 0.0 and rgb is not None:
                w_sum += ew
                acc_r += ew * rgb[0]
                acc_g += ew * rgb[1]
                acc_b += ew * rgb[2]
        if w_sum > 0.0:
            sample = (acc_r / w_sum, acc_g / w_sum, acc_b / w_sum)
    norm_total = sum(effective_weights.values()) or 1.0
    effective_weights = {k: float(v / norm_total) if v > 0.0 else 0.0 for k, v in effective_weights.items()}
    return sample, effective_weights, len(rgbs), per_roi_means


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
    tuning: MediaPipeTuning | None = None,
) -> dict[str, float]:
    roi_cfg = (tuning or load_mediapipe_tuning()).rppg_roi
    base = roi_cfg.base_weights or ROI_BASE_WEIGHTS
    roll_q = _clamp(1.0 - abs(roll_deg) / max(roi_cfg.roll_full_penalty_deg, 1e-6), 0.35, 1.0)
    yaw_q = _clamp(1.0 - abs(yaw_deg) / max(roi_cfg.yaw_full_penalty_deg, 1e-6), 0.35, 1.0)
    pitch_q = _clamp(
        1.0 - max(0.0, abs(pitch_deg) - roi_cfg.pitch_free_deg)
        / max(roi_cfg.pitch_full_penalty_deg, 1e-6),
        0.35,
        1.0,
    )

    n_pt = _lm_xyf(lm, NOSE_TIP_IDX, w, h)
    l_pt = _lm_xyf(lm, LEFT_CHEEK_IDX, w, h)
    r_pt = _lm_xyf(lm, RIGHT_CHEEK_IDX, w, h)
    d_l = _dist(n_pt, l_pt)
    d_r = _dist(n_pt, r_pt)
    total = d_l + d_r + 1e-6
    left_bias = _clamp(d_r / total, 0.35, 1.15)
    right_bias = _clamp(d_l / total, 0.35, 1.15)

    weights = {
        "forehead": float(base.get("forehead", ROI_BASE_WEIGHTS["forehead"])) * roll_q * pitch_q,
        "L_cheek": float(base.get("L_cheek", ROI_BASE_WEIGHTS["L_cheek"])) * roll_q * yaw_q * left_bias,
        "R_cheek": float(base.get("R_cheek", ROI_BASE_WEIGHTS["R_cheek"])) * roll_q * yaw_q * right_bias,
        "glabella": float(base.get("glabella", ROI_BASE_WEIGHTS["glabella"])) * (0.70 * roll_q + 0.30 * pitch_q),
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
    tuning: MediaPipeTuning | None = None,
) -> float:
    q_cfg = (tuning or load_mediapipe_tuning()).quality
    pose_q = _clamp(
        0.40 * (1.0 - abs(roll_deg) / 48.0)
        + 0.35 * (1.0 - abs(yaw_deg) / 48.0)
        + 0.25 * (1.0 - max(0.0, abs(pitch_deg) - 6.0) / 38.0),
        0.0, 1.0,
    )
    motion_q = _clamp(1.0 - face_motion_norm / 0.85, 0.0, 1.0)
    coverage_q = _clamp(face_area_ratio / 0.08, 0.0, 1.0)
    roi_q = _clamp(roi_valid_ratio, 0.0, 1.0)
    total = q_cfg.pose_weight + q_cfg.motion_weight + q_cfg.coverage_weight + q_cfg.roi_weight
    if total <= 1e-9:
        return 0.0
    return float(_clamp(
        (
            q_cfg.pose_weight * pose_q
            + q_cfg.motion_weight * motion_q
            + q_cfg.coverage_weight * coverage_q
            + q_cfg.roi_weight * roi_q
        ) / total
    ))


def roi_obstruction_score(
    frame_bgr: np.ndarray,
    lm: Any,
    indices: list[int],
    tuning: MediaPipeTuning | None = None,
) -> float:
    """Return 0..1 penalty for likely unusable ROI colour/illumination."""
    pts = roi_points(frame_bgr, lm, indices, "", tuning=tuning)
    return roi_obstruction_score_from_points(frame_bgr, pts, tuning)


def roi_mean_bgr(
    frame_bgr: np.ndarray,
    lm: Any,
    indices: list[int],
    blur_ksize: int = 5,
    transform_matrix: Any | None = None,
    tuning: MediaPipeTuning | None = None,
) -> Optional[tuple[float, float, float]]:
    # Pass tuning through: roi_points() otherwise falls back to
    # load_mediapipe_tuning(), which re-reads the JSON from disk on every call.
    pts = roi_points(frame_bgr, lm, indices, "", transform_matrix=transform_matrix, tuning=tuning)
    return roi_mean_from_points(frame_bgr, pts, blur_ksize)


def draw_rois(
    frame_bgr: np.ndarray,
    lm: Any,
    transform_matrix: Any | None = None,
    tracker: RoiGeometryTracker | None = None,
    tuning: MediaPipeTuning | None = None,
) -> None:
    h, w = frame_bgr.shape[:2]
    for name, indices in ROI_SPECS:
        pts = roi_points(frame_bgr, lm, indices, name, transform_matrix, tracker, tuning)
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
    params = _safe_welch_params(n, max_nperseg=256)
    if params is None:
        return 0.0, np.array([]), np.array([])
    nperseg, noverlap = params
    f, pxx = welch(
        sig,
        fs=fs,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=max(2048, nperseg * 4),
    )
    band = (f >= 0.7) & (f <= 3.5)
    if not np.any(band):
        return 0.0, f, pxx
    band_idx = np.flatnonzero(band)
    peak_i = int(band_idx[np.argmax(pxx[band])])
    peak_hz = float(f[peak_i])
    if 0 < peak_i < len(pxx) - 1:
        y0 = float(np.log(max(pxx[peak_i - 1], 1e-18)))
        y1 = float(np.log(max(pxx[peak_i], 1e-18)))
        y2 = float(np.log(max(pxx[peak_i + 1], 1e-18)))
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-12:
            delta = float(np.clip(0.5 * (y0 - y2) / denom, -1.0, 1.0))
            peak_hz = float(f[peak_i] + delta * (f[1] - f[0]))
    return peak_hz, f, pxx


def _safe_welch_params(n: int, *, max_nperseg: int, min_nperseg: int = 32) -> tuple[int, int] | None:
    """Return Welch parameters that remain valid after SciPy short-signal adjustment."""
    if n < 2:
        return None
    nperseg = min(max_nperseg, max(min_nperseg, n // 2), n)
    noverlap = min(nperseg // 2, nperseg - 1)
    if nperseg < 2 or noverlap >= nperseg:
        return None
    return int(nperseg), int(noverlap)


def compute_sqi(sig: np.ndarray, fs: float) -> float:
    if not _HAS_SCIPY or len(sig) < 32:
        return 0.0
    params = _safe_welch_params(len(sig), max_nperseg=256)
    if params is None:
        return 0.0
    nperseg, noverlap = params
    f, pxx = welch(
        sig,
        fs=fs,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=max(2048, nperseg * 4),
    )
    total = float(np.sum(pxx)) + 1e-12
    inband = float(np.sum(pxx[(f >= 0.6) & (f <= 4.0)]))
    return float(np.clip(inband / total, 0.0, 1.0))


def ibi_from_peaks(
    sig: np.ndarray,
    fs: float,
    bpm_hint: float = 0.0,
) -> np.ndarray:
    if not _HAS_SCIPY:
        return np.array([], dtype=np.float64)
    if bpm_hint > 0.0:
        beat_sec = 60.0 / float(np.clip(bpm_hint, 42.0, 190.0))
        dist = int(max(3, fs * beat_sec * 0.55))
    else:
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
    params = _safe_welch_params(len(series), max_nperseg=128)
    if params is None:
        return 0.0
    nperseg, noverlap = params
    ff, pxx = welch(series, fs=fs_resample, nperseg=nperseg, noverlap=noverlap)
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


def resolve_rppg_hrv_metrics(
    pulse_raw: np.ndarray,
    filt: np.ndarray,
    fs: float,
    sqi: float,
    *,
    hrv_window_sec: float = 30.0,
    bpm_hint: float = 0.0,
) -> tuple[float, float, float, float, str]:
    """Adaptive MAD HRV on bandpassed POS pulse (Gemini-aligned engine)."""
    window_samples = int(max(8, fs * hrv_window_sec))
    sig = np.asarray(filt, dtype=np.float64)
    sig = sig[np.isfinite(sig)]
    if sig.size < window_samples:
        return 0.0, 0.0, 0.0, 1.0, "LOW"
    if sig.size > window_samples:
        sig = sig[-window_samples:]

    hrv = compute_rppg_hrv_from_pulse(
        sig,
        fs,
        min_window_sec=hrv_window_sec,
        bpm_hint=bpm_hint,
    )

    if hrv.status == "SUCCESS":
        conf = hrv_confidence_rppg(
            hrv.n_ibis,
            sqi,
            hrv.artifact_ratio,
            rmssd=hrv.rmssd,
            sdnn=hrv.sdnn,
            ibi_sqi=hrv.ibi_sqi,
        )
        return hrv.rmssd, hrv.sdnn, hrv.lf_hf, hrv.artifact_ratio, conf

    if hrv.status == "BUFFERING":
        return 0.0, 0.0, 0.0, 1.0, "LOW"

    # 高 artifact 時仍回傳 BPM 相關診斷，但 HRV 指標歸零
    return 0.0, 0.0, 0.0, float(hrv.artifact_ratio), "LOW"


# ── Model download ───────────────────────────────────────────────────────────

def ensure_face_model(
    models_dir: Path,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Path:
    # Validate before returning an already-downloaded model.  MediaPipe 1.0.1
    # aborts inside DrishtiMetalHelper on current macOS and cannot be caught as
    # a Python exception; fail closed with an actionable error instead.
    validate_mediapipe_runtime()
    target = models_dir / "face_landmarker.task"
    if target.exists() and target.stat().st_size > 1_000_000:
        return target
    packaged = bool(getattr(sys, "frozen", False)) or bool(
        os.environ.get("NCFD_RESOURCE_ROOT")
    )
    if packaged:
        if not os.environ.get("NCFD_DATA_ROOT"):
            raise FileNotFoundError(
                f"MediaPipe face model is missing from the read-only resource bundle: {target}"
            )
        models_dir = data_path("models")
        target = models_dir / "face_landmarker.task"
        if target.exists() and target.stat().st_size > 1_000_000:
            return target
    models_dir.mkdir(parents=True, exist_ok=True)
    if status_cb:
        status_cb("正在下載 MediaPipe 臉部模型…（約 4 MB）")
    download_face_model(target)
    if status_cb:
        status_cb("模型下載完成")
    return target


# ── RppgEngine ───────────────────────────────────────────────────────────────

class RppgEngine:
    """Buffer RGB samples and compute rPPG + HRV metrics on demand."""

    _BPM_HISTORY_SEC = 10.0
    _BPM_EMA_ALPHA = 0.18
    _BPM_MIN_PLAUSIBLE = 42.0
    _BPM_MAX_PLAUSIBLE = 210.0
    _BPM_COMPUTE_INTERVAL_SEC = 5.0
    _BPM_JUMP_CONFIRM_DELTA = 25.0
    # 確認窗必須涵蓋 COUNT 個以頻譜重算節奏產生的樣本，否則 pending 佇列每輪被
    # prune 到只剩 1 筆、跳變確認永不成立（2026-07-03 審核 P1-1：舊值 2.0s < 5.0s 為死碼）
    _BPM_JUMP_CONFIRM_COUNT = 3
    _BPM_JUMP_CONFIRM_SEC = (_BPM_JUMP_CONFIRM_COUNT + 0.2) * _BPM_COMPUTE_INTERVAL_SEC
    _BPM_JUMP_CLUSTER_DELTA = 8.0

    def __init__(
        self,
        buffer_sec: float = 12.0,
        target_fps: float = 30.0,
        hrv_window_sec: float = 30.0,
    ) -> None:
        self.buffer_sec = buffer_sec
        self.target_fps = target_fps
        self.hrv_window_sec = hrv_window_sec
        self._r: deque[float] = deque(maxlen=100_000)
        self._g: deque[float] = deque(maxlen=100_000)
        self._b: deque[float] = deque(maxlen=100_000)
        self._t: deque[float] = deque(maxlen=100_000)
        # P6b-1 新增：per-ROI 均值緩衝（旁路，不參與既有 BPM 計算），供之後候選 ROI
        # 權重對同段訊號重算 BPM 做 A/B。maxlen 與既有混合緩衝一致。
        self._roi_buffers: dict[str, dict[str, deque[float]]] = {
            name: {
                "t": deque(maxlen=100_000),
                "r": deque(maxlen=100_000),
                "g": deque(maxlen=100_000),
                "b": deque(maxlen=100_000),
            }
            for name, _ in ROI_SPECS
        }
        self._last_fs: float = target_fps
        self._prev_face_center: Optional[tuple[float, float]] = None
        self._prev_face_center_t: Optional[float] = None
        self._face_motion_speed: float = 0.0
        self._bpm_candidates: deque[tuple[float, float]] = deque()
        self._pending_bpm_jump: deque[tuple[float, float]] = deque()
        self._stable_bpm: Optional[float] = None
        self._stable_bpm_t: Optional[float] = None
        self._last_bpm_guarded: bool = False
        self._last_bpm_guard_reason: str = ""
        self._last_bpm_delta: float = 0.0
        self._last_spectrum_compute_t: Optional[float] = None
        self._cached_spectrum: dict[str, Any] = {}

    def reset(self) -> None:
        self._r.clear(); self._g.clear()
        self._b.clear(); self._t.clear()
        # P6b-1 新增：一併清空 per-ROI 旁路緩衝，避免殘留跨 session/跨錄影的舊資料。
        for buf in self._roi_buffers.values():
            buf["t"].clear(); buf["r"].clear()
            buf["g"].clear(); buf["b"].clear()
        self._prev_face_center = None
        self._prev_face_center_t = None
        self._face_motion_speed = 0.0
        self._bpm_candidates.clear()
        self._pending_bpm_jump.clear()
        self._stable_bpm = None
        self._stable_bpm_t = None
        self._last_bpm_guarded = False
        self._last_bpm_guard_reason = ""
        self._last_bpm_delta = 0.0
        self._last_spectrum_compute_t = None
        self._cached_spectrum = {}

    def push(self, t: float, r: float, g: float, b: float) -> None:
        self._r.append(r); self._g.append(g)
        self._b.append(b); self._t.append(t)

    def push_roi_means(self, t: float, roi_means: dict[str, tuple[float, float, float]]) -> None:
        """P6b-1 新增：旁路緩衝每個 ROI 的 (R,G,B) 均值，供之後候選 ROI 權重 A/B 重算
        BPM 使用。純新增方法，不讀取也不修改 push()/_r/_g/_b/_t 既有混合緩衝，不影響
        既有 BPM 計算輸入。未知 ROI 名稱靜默略過（維持向後相容，不因新 ROI 而報錯）。

        注意：per_roi_means 不受混合權重篩選（零權重 ROI 只要遮罩成功就會入緩衝，
        屬刻意設計，供未來零權重 ROI 也能參與重算），因此 per-ROI 緩衝樣本數可能多於
        混合緩衝，兩者長度不保證一致。執行緒安全假設：本方法與 get_roi_window 目前
        僅供同一 worker 執行緒呼叫；若未來要跨執行緒讀取，須先補鎖或改為快照複製。
        """
        for name, rgb in roi_means.items():
            buf = self._roi_buffers.get(name)
            if buf is None:
                continue
            buf["t"].append(t)
            buf["r"].append(rgb[0])
            buf["g"].append(rgb[1])
            buf["b"].append(rgb[2])

    def get_roi_window(
        self,
        name: str,
        window_sec: float,
        t_now: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """P6b-1 新增：唯讀回傳指定 ROI 最近 window_sec 秒內的 (t, r, g, b) 序列快照，
        供之後離線重算使用。不修改任何緩衝狀態。ROI 名稱不存在或緩衝為空時回傳四個
        空陣列。

        注意：t_now=None 時以「該 ROI 緩衝最後一筆時間戳」為基準；不同 ROI 的最後
        更新時間可能因遮蔽而不同步，故跨多個 ROI 做 A/B 比較時，呼叫端務必顯式傳入
        同一個全域 t_now，確保各 ROI 取到相同的時間窗。
        """
        buf = self._roi_buffers.get(name)
        if buf is None or not buf["t"]:
            empty = np.array([], dtype=np.float64)
            return empty, empty, empty, empty
        t_arr = np.array(buf["t"], dtype=np.float64)
        ref_t = float(t_now) if t_now is not None else float(t_arr[-1])
        cutoff = ref_t - window_sec
        mask = t_arr >= cutoff
        r_arr = np.array(buf["r"], dtype=np.float64)[mask]
        g_arr = np.array(buf["g"], dtype=np.float64)[mask]
        b_arr = np.array(buf["b"], dtype=np.float64)[mask]
        return t_arr[mask], r_arr, g_arr, b_arr

    def _trim(self, t_now: float) -> None:
        keep_sec = max(self.buffer_sec, self.hrv_window_sec)
        cutoff = t_now - keep_sec
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

    def _accept_bpm_candidate(self, t_now: float, raw_bpm: float) -> float:
        self._last_bpm_guarded = False
        self._last_bpm_guard_reason = ""
        self._last_bpm_delta = 0.0
        if not self._BPM_MIN_PLAUSIBLE <= raw_bpm <= self._BPM_MAX_PLAUSIBLE:
            self._last_bpm_guarded = True
            self._last_bpm_guard_reason = "implausible_range"
            self._last_bpm_delta = float(raw_bpm - (self._stable_bpm or 0.0))
            return float(self._stable_bpm or 0.0)
        if self._stable_bpm is not None and abs(raw_bpm - self._stable_bpm) >= self._BPM_JUMP_CONFIRM_DELTA:
            self._last_bpm_delta = float(raw_bpm - self._stable_bpm)
            cutoff = t_now - self._BPM_JUMP_CONFIRM_SEC
            while self._pending_bpm_jump and self._pending_bpm_jump[0][0] < cutoff:
                self._pending_bpm_jump.popleft()
            if (
                self._pending_bpm_jump
                and abs(raw_bpm - self._pending_bpm_jump[-1][1]) > self._BPM_JUMP_CLUSTER_DELTA
            ):
                self._pending_bpm_jump.clear()
            self._pending_bpm_jump.append((t_now, float(raw_bpm)))
            pending_vals = np.array([v for _, v in self._pending_bpm_jump], dtype=np.float64)
            if pending_vals.size < self._BPM_JUMP_CONFIRM_COUNT:
                self._last_bpm_guarded = True
                self._last_bpm_guard_reason = "transient_jump"
                return float(self._stable_bpm)
            raw_bpm = float(np.median(pending_vals))
            self._last_bpm_guarded = True
            self._last_bpm_guard_reason = "confirmed_jump_smoothed"
        else:
            self._pending_bpm_jump.clear()
        self._bpm_candidates.append((t_now, float(raw_bpm)))
        cutoff = t_now - self._BPM_HISTORY_SEC
        while self._bpm_candidates and self._bpm_candidates[0][0] < cutoff:
            self._bpm_candidates.popleft()

        recent = np.array([v for _, v in self._bpm_candidates], dtype=np.float64)
        candidate = float(np.median(recent)) if recent.size else float(raw_bpm)
        if self._stable_bpm is None or self._stable_bpm_t is None:
            self._stable_bpm = candidate
            self._stable_bpm_t = t_now
            return candidate

        self._stable_bpm = (
            (1.0 - self._BPM_EMA_ALPHA) * self._stable_bpm
            + self._BPM_EMA_ALPHA * candidate
        )
        self._stable_bpm_t = t_now
        return float(self._stable_bpm)

    def _stabilize_bpm(self, t_now: float, raw_bpm: float) -> float:
        return self._accept_bpm_candidate(t_now, raw_bpm)

    def compute(
        self,
        t_now: float,
        frame_bgr: np.ndarray,
        lm: Any,
        transform_matrix: Any | None = None,
        roi_valid_count: int | None = None,
        roi_weights: dict[str, float] | None = None,
        roi_tracker: RoiGeometryTracker | None = None,
        tuning: MediaPipeTuning | None = None,
    ) -> RppgMetrics:
        tuning = tuning or load_mediapipe_tuning()
        roi_weights = roi_weights or {name: 0.0 for name, _ in ROI_SPECS}
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

        br = roi_mean_bgr(frame_bgr, lm, FOREHEAD_ROI_IDX, transform_matrix=transform_matrix, tuning=tuning)
        brightness = float(br[1]) if br else -1.0

        if n < int(fs * 4):
            pose_quality = _face_quality_from_pose(
                roll_deg,
                yaw_deg,
                pitch_deg,
                face_area_ratio,
                self._face_motion_speed / max(face_h, 1e-6),
                roi_valid_ratio,
                tuning,
            )
            landmark_jitter = roi_tracker.landmark_jitter_norm if roi_tracker else 0.0
            roi_area_stability = roi_tracker.roi_area_stability if roi_tracker else 1.0
            stability_q = _clamp(
                0.55 * (1.0 - landmark_jitter / max(tuning.rppg_roi.landmark_jitter_full_norm, 1e-6))
                + 0.45 * roi_area_stability
            )
            return RppgMetrics(
                raw_bpm=0.0,
                bpm_delta=0.0,
                bpm_guarded=False,
                bpm_guard_reason="warmup",
                warmup_progress=warm,
                frame_brightness=brightness,
                quality_score=_clamp(0.75 * pose_quality + 0.25 * stability_q),
                pose_roll_deg=roll_deg,
                pose_yaw_deg=yaw_deg,
                pose_pitch_deg=pitch_deg,
                roi_valid_count=int(roi_valid_count or 0),
                roi_weight_forehead=float(roi_weights.get("forehead", 0.0)),
                roi_weight_l_cheek=float(roi_weights.get("L_cheek", 0.0)),
                roi_weight_r_cheek=float(roi_weights.get("R_cheek", 0.0)),
                roi_weight_glabella=float(roi_weights.get("glabella", 0.0)),
                landmark_jitter_norm=float(landmark_jitter),
                roi_area_stability=float(roi_area_stability),
                roi_area_jitter_ratio=float(roi_tracker.roi_area_jitter_ratio if roi_tracker else 0.0),
                roi_smoothing_applied=bool(roi_tracker.roi_smoothing_applied if roi_tracker else False),
                canonical_roi_warp_used=bool(roi_tracker.canonical_roi_warp_used if roi_tracker else False),
                hrv_confidence="LOW",
                face_detected=True,
            )

        landmark_jitter = roi_tracker.landmark_jitter_norm if roi_tracker else 0.0
        roi_area_stability = roi_tracker.roi_area_stability if roi_tracker else 1.0
        stability_q = _clamp(
            0.55 * (1.0 - landmark_jitter / max(tuning.rppg_roi.landmark_jitter_full_norm, 1e-6))
            + 0.45 * roi_area_stability
        )
        roi_valid_count = len(ROI_SPECS) if roi_valid_count is None else int(max(0, roi_valid_count))
        pose_quality = _face_quality_from_pose(
            roll_deg,
            yaw_deg,
            pitch_deg,
            face_area_ratio,
            self._face_motion_speed / max(face_h, 1e-6),
            roi_valid_count / max(len(ROI_SPECS), 1),
            tuning,
        )

        reuse_spectrum = (
            self._last_spectrum_compute_t is not None
            and (t_now - self._last_spectrum_compute_t) < self._BPM_COMPUTE_INTERVAL_SEC
            and bool(self._cached_spectrum)
        )

        if reuse_spectrum:
            cached = self._cached_spectrum
            signal_quality = float(cached.get("signal_quality", 0.0))
            quality_score = _clamp(0.42 * pose_quality + 0.38 * signal_quality + 0.20 * stability_q)
            return RppgMetrics(
                bpm=float(cached.get("bpm", 0.0)),
                raw_bpm=float(cached.get("raw_bpm", 0.0)),
                bpm_delta=float(cached.get("bpm_delta", 0.0)),
                bpm_guarded=bool(cached.get("bpm_guarded", False)),
                bpm_guard_reason=str(cached.get("bpm_guard_reason", "")),
                rmssd=float(cached.get("rmssd", 0.0)),
                sdnn=float(cached.get("sdnn", 0.0)),
                lf_hf=float(cached.get("lf_hf", 0.0)),
                sqi=float(cached.get("sqi", 0.0)),
                stress_prob=float(cached.get("stress_prob", 0.0)),
                stress_status=str(cached.get("stress_status", "calibrating")),
                hrv_confidence=str(cached.get("hrv_confidence", "LOW")),
                ibi_artifact_ratio=float(cached.get("ibi_artifact_ratio", 0.0)),
                peak_freq_hz=float(cached.get("peak_freq_hz", 0.0)),
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
                landmark_jitter_norm=float(landmark_jitter),
                roi_area_stability=float(roi_area_stability),
                roi_area_jitter_ratio=float(roi_tracker.roi_area_jitter_ratio if roi_tracker else 0.0),
                roi_smoothing_applied=bool(roi_tracker.roi_smoothing_applied if roi_tracker else False),
                canonical_roi_warp_used=bool(roi_tracker.canonical_roi_warp_used if roi_tracker else False),
                face_detected=True,
                waveform=list(cached.get("waveform", [])),
                psd_freqs=list(cached.get("psd_freqs", [])),
                psd_vals=list(cached.get("psd_vals", [])),
            )

        r = np.array(self._r, dtype=np.float64)
        g = np.array(self._g, dtype=np.float64)
        b = np.array(self._b, dtype=np.float64)

        raw = pos_pulse(r, g, b)
        filt = butter_bandpass(raw, fs, 0.65, 3.7)
        peak_f, freqs, pxx = welch_peak_hz(filt, fs)
        raw_bpm = peak_f * 60.0 if peak_f > 0 else 0.0
        sqi = compute_sqi(filt, fs)

        rmssd, sdnn, lf_hf, art, conf = resolve_rppg_hrv_metrics(
            raw,
            filt,
            fs,
            sqi,
            hrv_window_sec=self.hrv_window_sec,
            bpm_hint=raw_bpm,
        )
        prob, st = stress_heuristic(lf_hf, rmssd)
        signal_quality = _clamp(0.60 * sqi + 0.40 * (1.0 - art))
        quality_score = _face_quality_from_pose(
            roll_deg,
            yaw_deg,
            pitch_deg,
            face_area_ratio,
            self._face_motion_speed / max(face_h, 1e-6),
            roi_valid_count / max(len(ROI_SPECS), 1),
            tuning,
        )
        quality_score = _clamp(0.42 * quality_score + 0.38 * signal_quality + 0.20 * stability_q)
        bpm = self._stabilize_bpm(t_now, raw_bpm)

        wf_n = min(160, filt.size)
        wave = filt[-wf_n:].copy()
        std = float(np.std(wave))
        wave = (wave - float(np.mean(wave))) / (std + 1e-9) if std > 1e-9 else wave * 0.0

        psd_mask = (freqs >= 0.5) & (freqs <= 4.0)
        pf, pv = freqs[psd_mask], pxx[psd_mask]
        if pf.size > 64:
            step = pf.size // 64
            pf, pv = pf[::step], pv[::step]

        self._last_spectrum_compute_t = t_now
        self._cached_spectrum = {
            "bpm": float(bpm),
            "raw_bpm": float(raw_bpm),
            "bpm_delta": float(self._last_bpm_delta),
            "bpm_guarded": bool(self._last_bpm_guarded),
            "bpm_guard_reason": str(self._last_bpm_guard_reason),
            "rmssd": float(rmssd),
            "sdnn": float(sdnn),
            "lf_hf": float(lf_hf),
            "sqi": float(sqi),
            "stress_prob": float(prob),
            "stress_status": st,
            "hrv_confidence": conf,
            "ibi_artifact_ratio": float(art),
            "peak_freq_hz": float(peak_f),
            "signal_quality": float(signal_quality),
            "waveform": [float(x) for x in wave],
            "psd_freqs": [float(x) for x in pf],
            "psd_vals": [float(x) for x in pv],
        }

        return RppgMetrics(
            bpm=float(bpm),
            raw_bpm=float(raw_bpm),
            bpm_delta=float(self._last_bpm_delta),
            bpm_guarded=bool(self._last_bpm_guarded),
            bpm_guard_reason=str(self._last_bpm_guard_reason),
            rmssd=float(rmssd), sdnn=float(sdnn),
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
            landmark_jitter_norm=float(landmark_jitter),
            roi_area_stability=float(roi_area_stability),
            roi_area_jitter_ratio=float(roi_tracker.roi_area_jitter_ratio if roi_tracker else 0.0),
            roi_smoothing_applied=bool(roi_tracker.roi_smoothing_applied if roi_tracker else False),
            canonical_roi_warp_used=bool(roi_tracker.canonical_roi_warp_used if roi_tracker else False),
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
    # P6b-3b：低頻（~1Hz）current vs candidate ROI 權重原始 BPM 重算結果，供 GUI
    # 協調層（RppgParamCoordinator）做 A/B。(t_now, cur_raw_bpm, cand_raw_bpm)；
    # 任一值無法算出時以 NaN 表示（float 訊號無法傳遞 None）。僅在
    # set_candidate_roi_weights() 設有候選時才會發射，見 _maybe_emit_candidate_bpm。
    candidate_bpm_ready = Signal(float, float, float)

    # P6b-3b：candidate vs current BPM 低頻重算節奏（秒）。刻意與逐幀迴圈脫鉤，
    # 避免每幀都跑一次 Welch PSD 造成不必要的 CPU 負擔。
    _CANDIDATE_RECOMPUTE_INTERVAL_SEC = 1.0

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        target_fps: float = 30.0,
        buffer_sec: float = 12.0,
        calibration_loader: Optional[Callable[[], object]] = None,
    ) -> None:
        super().__init__()
        self._queue = frame_queue
        self._target_fps = target_fps
        self._buffer_sec = buffer_sec
        self._stop = False
        self._tuning = load_mediapipe_tuning()
        # P6b-2：BPM 校準版本的載入器（沿用 CombinedWorker 既有介面），僅在 run()
        # 啟動時讀取一次以解析 rppg_params 的 ROI 權重覆寫，不做逐幀 BPM 校準
        # （RppgWorker 單獨路徑的 BPM 校準仍由呼叫端在 metrics_ready 收到後套用，
        # 本參數不改變此既有流程）。
        self._calibration_loader = calibration_loader
        self._roi_weights_override: Optional[dict[str, float]] = None
        # P6b-3b：候選 ROI 權重（None＝無候選，低頻重算分支整段 early-return，
        # 逐幀路徑與現況逐位元不變）。pending-flag 熱設定，run() 迴圈輪詢讀取。
        self._candidate_roi_weights: Optional[dict[str, float]] = None
        # 初值 0.0 屬刻意：候選剛設定後，只要當前 t_now 大於節奏門檻即立即觸發第一次
        # 重算（提早讓 GUI 拿到 A/B 首筆），非遺漏的初始化。
        self._last_candidate_recompute_t: float = 0.0
        # P6b-4：belt-truth 同步錄製 writer（None＝停用，離線驗證基礎設施關閉，
        # 逐幀路徑逐位元不變）。pending-flag 熱設定，同 set_candidate_roi_weights。
        self._belt_truth_capture: Optional[BeltTruthCaptureWriter] = None

    def request_stop(self) -> None:
        self._stop = True

    def set_roi_base_weights_override(self, weights: Optional[dict[str, float]]) -> None:
        """P6b-2：顯式設定 ROI base_weights 覆寫（None＝不覆寫，逐位元回退現行 tuning）。

        僅供 ``run()`` 開始前呼叫；套用只發生於 run() 啟動時的一次性讀取，不支援
        執行中熱切換（熱切換屬 P6b-3 線上協調層範疇）。若在 run() 已開始後才呼叫，
        對本次 run() 不生效。
        """
        self._roi_weights_override = weights

    def set_candidate_roi_weights(self, weights: Optional[dict[str, float]]) -> None:
        """P6b-3b：pending-flag 式熱設定候選 ROI 權重（None＝清除候選，暫停低頻
        重算與 candidate_bpm_ready 發射）。GUI 主執行緒呼叫；worker 執行緒於下一次
        低頻檢查週期（至多 ``_CANDIDATE_RECOMPUTE_INTERVAL_SEC`` 秒）讀取生效。

        執行緒安全假設：與 ``set_roi_base_weights_override``/``set_personal_profile``
        同樣的單一參照賦值模式，CPython GIL 下具原子性，讀寫不需額外鎖；
        worker 讀到舊值最多一個週期，不影響正確性（下一輪會讀到新值）。
        """
        self._candidate_roi_weights = weights

    def set_belt_truth_capture(self, writer: Optional[BeltTruthCaptureWriter]) -> None:
        """P6b-4：hot-swap belt-truth 同步錄製 writer（None＝停用）。

        GUI 主執行緒呼叫（心跳帶真值校準啟動/停止時）；worker 執行緒於下一幀讀取
        生效。執行緒安全假設同 ``set_candidate_roi_weights``：單一參照賦值，CPython
        GIL 下具原子性，讀寫不需額外鎖。
        """
        self._belt_truth_capture = writer

    def _maybe_capture_belt_truth(
        self, ts: float, per_roi_means: dict[str, tuple[float, float, float]]
    ) -> None:
        """P6b-4：OFF（``self._belt_truth_capture is None``，預設值）時立即返回，
        不做任何額外運算／I/O，確保逐幀路徑與現況逐位元不變。ON 時把本幀 per-ROI
        均值旁路寫入 capture 檔（唯讀觀察，見 rppg/belt_truth_capture.py）。
        """
        writer = self._belt_truth_capture
        if writer is None:
            return
        writer.record(ts, per_roi_means)

    def _maybe_emit_candidate_bpm(
        self,
        engine: "RppgEngine",
        rppg_tuning: MediaPipeTuning,
        t_now: float,
    ) -> None:
        """P6b-3b：OFF（``self._candidate_roi_weights is None``）時立即返回，不做
        任何額外運算／引擎存取／訊號發射，確保逐幀路徑與現況逐位元不變。ON 時
        低頻（約 1Hz）以 ``engine.get_roi_window`` 快照 + ``recompute_raw_bpm_
        from_roi_windows`` 對現行與候選 ROI 權重各重算一次 raw BPM，並發出
        ``candidate_bpm_ready`` 供 GUI 協調層做 A/B。
        """
        candidate = self._candidate_roi_weights
        if candidate is None:
            return
        if t_now - self._last_candidate_recompute_t < self._CANDIDATE_RECOMPUTE_INTERVAL_SEC:
            return
        self._last_candidate_recompute_t = t_now

        roi_windows = {
            name: engine.get_roi_window(name, self._buffer_sec, t_now)
            for name, _ in ROI_SPECS
        }
        current_weights = dict(rppg_tuning.rppg_roi.base_weights or ROI_BASE_WEIGHTS)
        cur_bpm = recompute_raw_bpm_from_roi_windows(roi_windows, current_weights)
        cand_bpm = recompute_raw_bpm_from_roi_windows(roi_windows, candidate)
        self.candidate_bpm_ready.emit(
            float(t_now),
            float(cur_bpm) if cur_bpm is not None else float("nan"),
            float(cand_bpm) if cand_bpm is not None else float("nan"),
        )

    @fail_closed_worker("rPPG worker", log)
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
        try:
            base_opts = create_face_landmarker_base_options(_mp_python, model_path)
            lm_options = _mp_vision.FaceLandmarkerOptions(
                base_options=base_opts,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                min_face_detection_confidence=self._tuning.face_landmarker.min_face_detection_confidence,
                min_face_presence_confidence=self._tuning.face_landmarker.min_face_presence_confidence,
                min_tracking_confidence=self._tuning.face_landmarker.min_tracking_confidence,
                num_faces=max(1, int(self._tuning.face_landmarker.num_faces)),
                running_mode=_mp_vision.RunningMode.VIDEO,
            )
        except Exception as exc:
            self.failed.emit(f"MediaPipe Face Landmarker 選項建立失敗：{exc}")
            self.finished.emit()
            return

        engine = RppgEngine(buffer_sec=self._buffer_sec, target_fps=self._target_fps)
        roi_tracker = RoiGeometryTracker()
        last_face = False
        t_origin: Optional[float] = None
        ts_ms_prev = 0
        last_preview_emit = 0.0
        preview_emit_interval = 1.0 / _ANNOTATED_PREVIEW_MAX_FPS

        # P6b-2：啟動時解析一次 ROI base_weights 覆寫（無覆寫時 rppg_tuning 與
        # self._tuning 為同一物件，逐幀路徑不變）。
        rppg_tuning = resolve_effective_rppg_tuning(
            self._tuning, self._roi_weights_override, self._calibration_loader
        )
        # P6b-3b（審查 B 修正）：weighted_mix 必須由「本次 run 是否實際套用了 ROI
        # 權重覆寫」推導，而非 self._roi_weights_override（後者僅供測試/顯式呼叫，
        # production 的覆寫走 calibration_loader → rppg_params，不會設該欄位）。
        # resolve_effective_rppg_tuning 在無覆寫時原樣回傳 self._tuning（同一物件），
        # 有覆寫時回傳新 dataclass；以身分比較判定，OFF 時 roi_override_active 為
        # False → 逐位元回退等權平均，ON（adopt 後重載）時才啟用加權混合槓桿。
        roi_override_active = rppg_tuning is not self._tuning

        self.status_changed.emit("MediaPipe 初始化完成，等待幀資料…")

        try:
            landmarker = _mp_vision.FaceLandmarker.create_from_options(lm_options)
        except Exception as exc:
            self.failed.emit(f"MediaPipe Face Landmarker 初始化失敗：{exc}")
            self.finished.emit()
            return

        with landmarker:
            while not self._stop:
                try:
                    ts, bgr = get_latest(self._queue, timeout=0.1)
                except queue.Empty:
                    continue

                try:
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
                        sample, roi_weights, roi_valid_count, per_roi_means = collect_rppg_roi_sample_with_means(
                            bgr, lm, transform_matrix, roi_tracker, rppg_tuning,
                            weighted_mix=roi_override_active,
                        )
                        draw_rois(annotated, lm, transform_matrix, roi_tracker, self._tuning)
                        if sample is not None:
                            engine.push(ts, sample[0], sample[1], sample[2])
                        # P6b-1 新增：per-ROI 旁路緩衝，不影響上面既有 push() 的輸入/行為。
                        if per_roi_means:
                            engine.push_roi_means(ts, per_roi_means)
                            # P6b-4：OFF（無 writer）時 early-return，不影響既有流程。
                            self._maybe_capture_belt_truth(ts, per_roi_means)
                        # P6b-3b：OFF（無候選）時 early-return，不影響本行以下既有流程。
                        self._maybe_emit_candidate_bpm(engine, rppg_tuning, ts)

                        metrics = engine.compute(
                            ts,
                            bgr,
                            lm,
                            transform_matrix=transform_matrix,
                            roi_valid_count=roi_valid_count,
                            roi_weights=roi_weights,
                            roi_tracker=roi_tracker,
                            tuning=self._tuning,
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
                        roi_tracker.reset()
                        metrics = RppgMetrics(face_detected=False)
                        self.status_changed.emit("未偵測到臉部…")

                    self.metrics_ready.emit(metrics)

                    if ts - last_preview_emit >= preview_emit_interval:
                        last_preview_emit = ts
                        rgb_ann = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                        rgb_ann = np.ascontiguousarray(rgb_ann)
                        fh, fw = rgb_ann.shape[:2]
                        qimg = QImage(
                            rgb_ann.data, fw, fh,
                            rgb_ann.strides[0],
                            QImage.Format.Format_RGB888,
                        )
                        self.frame_annotated.emit(qimg.copy())
                except Exception:
                    log.exception("每幀處理發生未預期例外，略過此幀")
                    continue

        self.finished.emit()
