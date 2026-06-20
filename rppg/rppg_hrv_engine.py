"""Adaptive MAD-based rPPG HRV engine for bandpassed POS pulse waveforms.

Pipeline (aligned with production rPPG worker):
    Butterworth bandpassed POS pulse → Z-score → adaptive find_peaks
    → MAD IBI artifact correction → RMSSD / SDNN / LF-HF
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import find_peaks, welch

_IBI_MIN_MS = 333.0   # ~180 BPM
_IBI_MAX_MS = 1500.0  # ~40 BPM
_MAD_SCALE = 3.0
_MIN_CLEAN_IBIS = 5
_MIN_LF_HF_IBIS = 20
_PEAK_PROMINENCE = 0.30


@dataclass
class RppgHrvResult:
    status: str = "BUFFERING"  # BUFFERING | SUCCESS | ERROR
    rmssd: float = 0.0
    sdnn: float = 0.0
    lf_hf: float = 0.0
    bpm: float = 0.0
    artifact_ratio: float = 1.0
    ibi_sqi: float = 0.0
    n_ibis: int = 0
    n_peaks: int = 0
    progress: float = 0.0
    message: str = ""


def _peak_min_distance(fs: float, bpm_hint: float = 0.0) -> int:
    if bpm_hint > 0.0:
        bpm = float(np.clip(bpm_hint, 42.0, 190.0))
        beat_sec = 60.0 / bpm
        return int(max(3, fs * beat_sec * 0.55))
    return int(max(3, fs * 60.0 / 200.0))


def _adaptive_peaks(
    pulse_signal: np.ndarray,
    fs: float,
    *,
    bpm_hint: float = 0.0,
) -> np.ndarray:
    sig = np.asarray(pulse_signal, dtype=np.float64)
    sig = sig[np.isfinite(sig)]
    if sig.size < 8:
        return np.array([], dtype=np.int64)
    norm = (sig - float(np.mean(sig))) / (float(np.std(sig)) + 1e-6)
    peaks, _ = find_peaks(
        norm,
        distance=_peak_min_distance(fs, bpm_hint),
        prominence=_PEAK_PROMINENCE,
    )
    return peaks.astype(np.int64)


def _clean_ibis_mad(ibi_ms: np.ndarray) -> tuple[np.ndarray, float]:
    ibis = np.asarray(ibi_ms, dtype=np.float64)
    ibis = ibis[np.isfinite(ibis)]
    if ibis.size == 0:
        return np.array([], dtype=np.float64), 1.0

    median_ibi = float(np.median(ibis))
    mad = float(np.median(np.abs(ibis - median_ibi)))
    valid = (ibis >= _IBI_MIN_MS) & (ibis <= _IBI_MAX_MS)
    if mad > 1e-6:
        valid &= np.abs(ibis - median_ibi) <= _MAD_SCALE * mad

    clean = ibis[valid]
    art = float(np.clip(1.0 - clean.size / max(ibis.size, 1), 0.0, 1.0))
    return clean, art


def _lf_hf_from_clean_ibis(clean_ibi_ms: np.ndarray) -> float:
    if clean_ibi_ms.size < _MIN_LF_HF_IBIS:
        return 0.0
    time_axis = np.cumsum(clean_ibi_ms) / 1000.0
    if time_axis[-1] - time_axis[0] < 4.0:
        return 0.0
    try:
        interp_kind = "cubic" if clean_ibi_ms.size >= 4 else "linear"
        f_interp = interp1d(
            time_axis,
            clean_ibi_ms,
            kind=interp_kind,
            fill_value="extrapolate",
        )
        t_new = np.arange(time_axis[0], time_axis[-1], 0.25)
        if t_new.size < 16:
            return 0.0
        resampled = f_interp(t_new)
        resampled = resampled - float(np.mean(resampled))
        nperseg = min(len(resampled), 64)
        if nperseg < 8:
            return 0.0
        freqs, psd = welch(resampled, fs=4.0, nperseg=nperseg)
        lf = float(np.sum(psd[(freqs >= 0.04) & (freqs < 0.15)]))
        hf = float(np.sum(psd[(freqs >= 0.15) & (freqs <= 0.40)]))
        if hf <= 1e-12:
            return 0.0
        return float(lf / hf)
    except Exception:
        return 0.0


def hrv_confidence_rppg(
    n_ibis: int,
    spectral_sqi: float,
    art_ratio: float,
    *,
    rmssd: float = 0.0,
    sdnn: float = 0.0,
    ibi_sqi: float = 0.0,
) -> str:
    """rPPG HRV confidence using IBI artifact ratio + spectral SQI."""
    if n_ibis < 4:
        return "LOW"

    effective_sqi = max(float(spectral_sqi), float(ibi_sqi))
    has_metrics = rmssd > 0.0 and sdnn > 0.0

    if art_ratio > 0.25 or effective_sqi < 0.70:
        if spectral_sqi >= 0.85 and has_metrics and n_ibis >= 10 and art_ratio <= 0.35:
            return "MEDIUM"
        return "LOW"
    if art_ratio > 0.10:
        return "MEDIUM"
    return "HIGH"


def compute_rppg_hrv_from_pulse(
    pulse_signal: np.ndarray,
    fs: float,
    *,
    min_window_sec: float = 30.0,
    bpm_hint: float = 0.0,
    **_kwargs: Any,
) -> RppgHrvResult:
    """Compute HRV from a bandpassed POS pulse waveform (1D array, seconds window)."""
    sig = np.asarray(pulse_signal, dtype=np.float64)
    sig = sig[np.isfinite(sig)]
    min_samples = int(max(8, fs * min_window_sec))
    progress = float(np.clip(sig.size / max(min_samples, 1), 0.0, 1.0))

    if sig.size < min_samples:
        return RppgHrvResult(
            status="BUFFERING",
            progress=progress,
            message=f"{sig.size}/{min_samples}",
        )

    try:
        peaks = _adaptive_peaks(sig, fs, bpm_hint=bpm_hint)
        if peaks.size < 6:
            return RppgHrvResult(
                status="ERROR",
                progress=progress,
                message="insufficient_peaks",
                n_peaks=int(peaks.size),
            )

        ibi_ms = np.diff(peaks) * (1000.0 / fs)
        clean_ibi, art = _clean_ibis_mad(ibi_ms)
        ibi_sqi = float(np.clip(1.0 - art, 0.0, 1.0))

        if clean_ibi.size < _MIN_CLEAN_IBIS or art > 0.35:
            median_ibi = float(np.median(ibi_ms)) if ibi_ms.size else 0.0
            bpm = float(60.0 * 1000.0 / (median_ibi + 1e-6)) if median_ibi > 0 else 0.0
            return RppgHrvResult(
                status="ERROR",
                progress=progress,
                bpm=bpm,
                artifact_ratio=art,
                ibi_sqi=ibi_sqi,
                n_ibis=int(clean_ibi.size),
                n_peaks=int(peaks.size),
                message="excessive_artifacts",
            )

        sdnn = float(np.std(clean_ibi, ddof=1))
        diffs = np.diff(clean_ibi)
        rmssd = float(np.sqrt(np.mean(diffs * diffs))) if diffs.size else 0.0
        bpm = float(60.0 * 1000.0 / float(np.mean(clean_ibi)))
        lf_hf = _lf_hf_from_clean_ibis(clean_ibi)

        if rmssd <= 0.0:
            return RppgHrvResult(
                status="ERROR",
                progress=progress,
                bpm=bpm,
                artifact_ratio=art,
                ibi_sqi=ibi_sqi,
                n_ibis=int(clean_ibi.size),
                n_peaks=int(peaks.size),
                message="insufficient_hrv_metrics",
            )

        return RppgHrvResult(
            status="SUCCESS",
            rmssd=rmssd,
            sdnn=sdnn,
            lf_hf=lf_hf,
            bpm=bpm,
            artifact_ratio=art,
            ibi_sqi=ibi_sqi,
            n_ibis=int(clean_ibi.size),
            n_peaks=int(peaks.size),
            progress=1.0,
        )
    except Exception as exc:
        return RppgHrvResult(
            status="ERROR",
            progress=progress,
            message=str(exc) or "signal_structure_broken",
        )
