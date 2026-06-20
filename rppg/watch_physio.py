"""Extended watch physiology: HRV, waveform, PSD, quality, BPM guard."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
from scipy.interpolate import interp1d as _scipy_interp1d
from scipy.signal import welch

from rppg.calibration_watch import WatchSample
from rppg.rppg_worker import (
    _safe_welch_params,
    hrv_confidence,
    hrv_time_domain,
    ibi_artifact_ratio,
    lf_hf_from_tachogram,
    stress_heuristic,
    validate_ibi_intervals,
)


@dataclass
class WatchPhysioState:
    rmssd: float = 0.0
    sdnn: float = 0.0
    lf_hf: float = 0.0
    stress_prob: float = 0.0
    stress_status: str = "calibrating"
    hrv_confidence: str = "LOW"
    ibi_artifact_ratio: float = 1.0
    hrv_ready: bool = False
    sample_count: int = 0
    ibi_count: int = 0
    sqi: float = 0.0
    quality_score: float = 0.0
    warmup_progress: float = 0.0
    bpm_delta: float = 0.0
    bpm_guarded: bool = False
    bpm_guard_reason: str = ""
    peak_freq_hz: float = 0.0
    pose_roll_deg: float = 0.0
    pose_yaw_deg: float = 0.0
    pose_pitch_deg: float = 0.0
    motion_level: float | None = None
    imu_gate: float = 1.0
    lf_hf_window_ok: bool = False
    waveform: list[float] = field(default_factory=list)
    psd_freqs: list[float] = field(default_factory=list)
    psd_vals: list[float] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ibis_from_watch_samples(samples: list[WatchSample]) -> np.ndarray:
    ibis: list[float] = []
    for sample in samples:
        bpm = int(sample.bpm)
        if bpm <= 0:
            continue
        ibis.append(60000.0 / float(bpm))
    return np.asarray(ibis, dtype=np.float64)


def pose_from_imu(ax: float | None, ay: float | None, az: float | None) -> tuple[float, float, float]:
    if ax is None or ay is None or az is None:
        return 0.0, 0.0, 0.0
    roll = math.degrees(math.atan2(float(ay), float(az)))
    pitch = math.degrees(math.atan2(-float(ax), math.hypot(float(ay), float(az)) + 1e-6))
    return roll, 0.0, pitch


def imu_motion_gate(
    motion_level: float | None,
    *,
    still_max: float = 0.35,
    active_min: float = 1.5,
) -> tuple[float, float]:
    if motion_level is None:
        return 0.85, 0.0
    level = max(0.0, float(motion_level))
    if level <= still_max:
        return 1.0, 0.0
    if level >= active_min:
        return 0.35, _clamp((level - active_min) / (active_min + 1e-6))
    span = active_min - still_max
    t = (level - still_max) / (span + 1e-6)
    return _clamp(1.0 - 0.65 * t), _clamp(t * 0.5)


def _hrv_sqi(n_samples: int, motion_level: float | None, *, target_samples: int = 24) -> float:
    density = _clamp(n_samples / max(target_samples, 1))
    if motion_level is None:
        motion_w = 0.75
    else:
        motion_w = _clamp(1.0 - float(motion_level) / 1.5)
    return _clamp(0.55 * density + 0.45 * motion_w)


def _tachogram_series(ibis_ms: np.ndarray, fs_resample: float = 4.0) -> tuple[np.ndarray, np.ndarray] | None:
    if ibis_ms.size < 4:
        return None
    ibi_s = ibis_ms / 1000.0
    t = np.cumsum(ibi_s)
    t = t - t[0]
    if t[-1] < 2.0:
        return None
    t_uniform = np.arange(0.0, t[-1], 1.0 / fs_resample)
    try:
        series = _scipy_interp1d(t, ibi_s, kind="linear", fill_value=cast(Any, "extrapolate"))(t_uniform)
        series = series - np.mean(series)
    except Exception:
        return None
    return t_uniform, series


def _waveform_and_psd(ibis_ms: np.ndarray) -> tuple[list[float], list[float], list[float], bool]:
    packed = _tachogram_series(ibis_ms)
    if packed is None:
        return [], [], [], False
    _, series = packed
    std = float(np.std(series))
    wf = (series / (std + 1e-6)).tolist()
    if len(wf) > 160:
        wf = wf[-160:]

    params = _safe_welch_params(len(series), max_nperseg=128)
    if params is None:
        return wf, [], [], False
    nperseg, noverlap = params
    ff, pxx = welch(series, fs=4.0, nperseg=nperseg, noverlap=noverlap)
    ibi_s = ibis_ms / 1000.0
    t_end = float(np.sum(ibi_s))
    window_ok = t_end >= 4.0
    return wf, ff.tolist(), pxx.tolist(), window_ok


def _bpm_guard(current_bpm: int, history: list[int], *, jump_bpm: float = 18.0) -> tuple[float, bool, str]:
    if current_bpm <= 0 or len(history) < 3:
        return 0.0, False, ""
    med = float(np.median(np.asarray(history[-12:], dtype=np.float64)))
    delta = float(current_bpm) - med
    if abs(delta) >= jump_bpm:
        reason = "watch_bpm_jump" if delta > 0 else "watch_bpm_drop"
        return delta, True, reason
    return delta, False, ""


def compute_watch_physio(
    samples: list[WatchSample],
    *,
    window_sec: float = 90.0,
    min_samples: int = 8,
    still_motion_max: float = 0.35,
) -> WatchPhysioState:
    now = time.time()
    recent = [
        s for s in samples
        if (now - s.received_at) <= window_sec and int(s.bpm) > 0
    ]
    warmup = _clamp(len(recent) / max(min_samples, 1), hi=1.0)

    latest = recent[-1] if recent else None
    motion_level = float(latest.motion_level) if latest and latest.motion_level is not None else None
    gate, _ = imu_motion_gate(motion_level)
    roll, yaw, pitch = pose_from_imu(
        getattr(latest, "ax", None),
        getattr(latest, "ay", None),
        getattr(latest, "az", None),
    )

    if len(recent) < 2:
        return WatchPhysioState(
            sample_count=len(recent),
            warmup_progress=warmup,
            motion_level=motion_level,
            imu_gate=gate,
            pose_roll_deg=roll,
            pose_yaw_deg=yaw,
            pose_pitch_deg=pitch,
        )

    bpm_hist = [int(s.bpm) for s in recent]
    cur_bpm = bpm_hist[-1]
    bpm_delta, guarded, guard_reason = _bpm_guard(cur_bpm, bpm_hist)
    peak_hz = float(cur_bpm) / 60.0 if cur_bpm > 0 else 0.0

    if len(recent) < min_samples:
        sqi = _hrv_sqi(len(recent), motion_level, target_samples=min_samples)
        quality = _clamp(sqi * gate)
        return WatchPhysioState(
            sample_count=len(recent),
            warmup_progress=warmup,
            sqi=sqi,
            quality_score=quality,
            bpm_delta=bpm_delta,
            bpm_guarded=guarded,
            bpm_guard_reason=guard_reason,
            peak_freq_hz=peak_hz,
            pose_roll_deg=roll,
            pose_yaw_deg=yaw,
            pose_pitch_deg=pitch,
            motion_level=motion_level,
            imu_gate=gate,
        )

    still = [
        s for s in recent
        if s.motion_level is None or float(s.motion_level) <= still_motion_max
    ]
    use = still if len(still) >= min_samples else recent

    ibis_raw = ibis_from_watch_samples(use)
    if ibis_raw.size < min_samples:
        sqi = _hrv_sqi(ibis_raw.size, motion_level, target_samples=min_samples)
        return WatchPhysioState(
            sample_count=len(recent),
            warmup_progress=warmup,
            sqi=sqi,
            quality_score=_clamp(sqi * gate),
            bpm_delta=bpm_delta,
            bpm_guarded=guarded,
            bpm_guard_reason=guard_reason,
            peak_freq_hz=peak_hz,
            pose_roll_deg=roll,
            pose_yaw_deg=yaw,
            pose_pitch_deg=pitch,
            motion_level=motion_level,
            imu_gate=gate,
        )

    ibis_clean = validate_ibi_intervals(ibis_raw)
    wf, psd_f, psd_v, lf_hf_ok = _waveform_and_psd(ibis_clean)

    if ibis_clean.size < 4:
        sqi = _hrv_sqi(ibis_clean.size, motion_level, target_samples=min_samples)
        return WatchPhysioState(
            sample_count=len(recent),
            ibi_count=int(ibis_clean.size),
            warmup_progress=warmup,
            sqi=sqi,
            quality_score=_clamp(sqi * gate),
            bpm_delta=bpm_delta,
            bpm_guarded=guarded,
            bpm_guard_reason=guard_reason,
            peak_freq_hz=peak_hz,
            pose_roll_deg=roll,
            pose_yaw_deg=yaw,
            pose_pitch_deg=pitch,
            motion_level=motion_level,
            imu_gate=gate,
            waveform=wf,
            psd_freqs=psd_f,
            psd_vals=psd_v,
        )

    rmssd, sdnn = hrv_time_domain(ibis_clean)
    lf_hf = lf_hf_from_tachogram(ibis_clean)
    art = ibi_artifact_ratio(ibis_raw, ibis_clean)
    stress_prob, stress_status = stress_heuristic(lf_hf, rmssd)

    motion_vals = [float(s.motion_level) for s in use if s.motion_level is not None]
    motion_med = float(np.median(motion_vals)) if motion_vals else motion_level
    sqi = _hrv_sqi(ibis_clean.size, motion_med)
    conf = hrv_confidence(int(ibis_clean.size), sqi, art)
    ready = conf != "LOW" and rmssd > 0
    quality = _clamp(0.55 * sqi + 0.45 * gate)

    return WatchPhysioState(
        rmssd=rmssd,
        sdnn=sdnn,
        lf_hf=lf_hf,
        stress_prob=stress_prob,
        stress_status=stress_status,
        hrv_confidence=conf,
        ibi_artifact_ratio=art,
        hrv_ready=ready,
        sample_count=len(recent),
        ibi_count=int(ibis_clean.size),
        sqi=sqi,
        quality_score=quality,
        warmup_progress=1.0 if ready else warmup,
        bpm_delta=bpm_delta,
        bpm_guarded=guarded,
        bpm_guard_reason=guard_reason,
        peak_freq_hz=peak_hz,
        pose_roll_deg=roll,
        pose_yaw_deg=yaw,
        pose_pitch_deg=pitch,
        motion_level=motion_med,
        imu_gate=gate,
        lf_hf_window_ok=lf_hf_ok and lf_hf > 0,
        waveform=wf,
        psd_freqs=psd_f,
        psd_vals=psd_v,
    )
