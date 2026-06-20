from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rppg.rppg_worker import (  # noqa: E402
    RppgEngine,
    butter_bandpass,
    compute_sqi,
    ibi_artifact_ratio,
    ibi_from_peaks,
    lf_hf_from_tachogram,
    resolve_rppg_hrv_metrics,
    validate_ibi_intervals,
    welch_peak_hz,
)
from rppg.rppg_hrv_engine import compute_rppg_hrv_from_pulse, hrv_confidence_rppg  # noqa: E402
from rppg.demo_rppg_live import RppgDemo  # noqa: E402


def test_bandpass_and_welch_estimate_72_bpm() -> None:
    fs = 30.0
    t = np.arange(0.0, 12.0, 1.0 / fs)
    rng = np.random.default_rng(42)
    sig = np.sin(2.0 * np.pi * 1.2 * t) + 0.05 * rng.standard_normal(t.size)

    filtered = butter_bandpass(sig, fs, 0.65, 3.7)
    peak_hz, _, _ = welch_peak_hz(filtered, fs)

    assert abs(peak_hz * 60.0 - 72.0) < 4.0


def test_welch_peak_keeps_sub_10_bpm_detail() -> None:
    fs = 30.0
    t = np.arange(0.0, 12.0, 1.0 / fs)
    sig = np.sin(2.0 * np.pi * (73.0 / 60.0) * t)

    filtered = butter_bandpass(sig, fs, 0.65, 3.7)
    peak_hz, _, _ = welch_peak_hz(filtered, fs)

    assert abs(peak_hz * 60.0 - 73.0) < 2.0


def test_welch_helpers_handle_short_signal_without_overlap_error() -> None:
    short = np.sin(np.linspace(0.0, np.pi, 16))

    peak_hz, freqs, pxx = welch_peak_hz(short, 30.0)
    sqi = compute_sqi(short, 30.0)
    lf_hf = lf_hf_from_tachogram(np.full(8, 800.0))

    assert peak_hz >= 0.0
    assert freqs.size == pxx.size
    assert sqi == 0.0
    assert lf_hf >= 0.0


def test_validate_ibi_removes_local_outlier() -> None:
    ibis = np.array([800.0, 810.0, 790.0, 300.0, 805.0, 795.0, 815.0])

    clean = validate_ibi_intervals(ibis)

    assert 300.0 not in clean
    assert clean.size >= 5


def test_ibi_artifact_ratio_uses_cleaned_count() -> None:
    raw = np.array([800.0, 810.0, 790.0, 300.0, 805.0])
    clean = validate_ibi_intervals(raw)

    ratio = ibi_artifact_ratio(raw, clean)

    assert 0.0 < ratio < 1.0


def test_demo_trim_buffer_keeps_channels_aligned() -> None:
    demo = RppgDemo(buffer_sec=1.0, target_fps=30.0, hrv_window_sec=1.0)
    demo.push(0.0, 1.0, 2.0, 3.0)
    demo.push(0.5, 4.0, 5.0, 6.0)
    demo.push(1.5, 7.0, 8.0, 9.0)

    demo._trim_buffer(1.5)

    assert len(demo._t) == len(demo._r) == len(demo._g) == len(demo._b) == 2
    assert list(demo._r) == [4.0, 7.0]
    assert list(demo._g) == [5.0, 8.0]
    assert list(demo._b) == [6.0, 9.0]


def test_bpm_stabilizer_smooths_large_transient_jump() -> None:
    engine = RppgEngine(target_fps=30.0)
    stable = engine._stabilize_bpm(1.0, 72.0)
    jumped = engine._stabilize_bpm(1.2, 130.0)

    assert stable == 72.0
    assert jumped == stable
    assert engine._last_bpm_guarded is True
    assert engine._last_bpm_guard_reason == "transient_jump"
    assert engine._last_bpm_delta == 58.0


def test_bpm_stabilizer_confirms_sustained_large_jump() -> None:
    engine = RppgEngine(target_fps=30.0)
    engine._stabilize_bpm(1.0, 80.0)

    assert engine._stabilize_bpm(1.2, 50.0) == 80.0
    assert engine._stabilize_bpm(1.6, 51.0) == 80.0
    assert engine._stabilize_bpm(2.0, 49.0) == 80.0
    confirmed = engine._stabilize_bpm(2.4, 50.0)

    assert confirmed < 80.0
    assert confirmed > 70.0
    assert engine._last_bpm_guarded is True
    assert engine._last_bpm_guard_reason == "confirmed_jump_smoothed"


def test_bpm_stabilizer_ignores_implausible_bpm() -> None:
    engine = RppgEngine(target_fps=30.0)
    engine._stabilize_bpm(1.0, 72.0)
    frozen = engine._stabilize_bpm(2.0, 250.0)

    assert frozen == 72.0
    assert engine._last_bpm_guarded is True
    assert engine._last_bpm_guard_reason == "implausible_range"


def test_bpm_stabilizer_bootstraps_without_quality_gate() -> None:
    engine = RppgEngine(target_fps=30.0)
    bpm = engine._stabilize_bpm(1.0, 84.0)

    assert bpm == 84.0


def test_bpm_stabilizer_accepts_high_but_plausible_bpm() -> None:
    engine = RppgEngine(target_fps=30.0)
    bpm = engine._stabilize_bpm(1.0, 188.0)

    assert bpm == 188.0


def _synthetic_variable_hr_pulse(fs: float = 30.0, duration_sec: float = 35.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.arange(0.0, duration_sec, 1.0 / fs)
    hr_hz = 1.2 + 0.05 * np.sin(2.0 * np.pi * 0.05 * t)
    phase = np.cumsum(hr_hz / fs) * 2.0 * np.pi
    return np.sin(phase) + 0.05 * rng.standard_normal(t.size)


def test_adaptive_hrv_engine_returns_metrics_after_window() -> None:
    fs = 30.0
    pulse = _synthetic_variable_hr_pulse(fs=fs, duration_sec=35.0)
    filt = butter_bandpass(pulse, fs, 0.65, 3.7)

    result = compute_rppg_hrv_from_pulse(filt, fs, min_window_sec=30.0, bpm_hint=72.0)

    assert result.status == "SUCCESS"
    assert result.rmssd > 0.0
    assert result.sdnn > 0.0
    assert result.n_ibis >= 5
    assert result.artifact_ratio < 0.35


def test_adaptive_hrv_engine_buffers_short_signal() -> None:
    fs = 30.0
    pulse = _synthetic_variable_hr_pulse(fs=fs, duration_sec=10.0)
    filt = butter_bandpass(pulse, fs, 0.65, 3.7)

    result = compute_rppg_hrv_from_pulse(filt, fs, min_window_sec=30.0)

    assert result.status == "BUFFERING"
    assert result.progress < 1.0


def test_resolve_rppg_hrv_metrics_uses_adaptive_engine() -> None:
    fs = 30.0
    pulse = _synthetic_variable_hr_pulse(fs=fs, duration_sec=35.0)
    filt = butter_bandpass(pulse, fs, 0.65, 3.7)
    sqi = compute_sqi(filt, fs)

    rmssd, sdnn, lf_hf, art, conf = resolve_rppg_hrv_metrics(
        pulse,
        filt,
        fs,
        sqi,
        hrv_window_sec=30.0,
        bpm_hint=72.0,
    )

    assert rmssd > 0.0
    assert sdnn > 0.0
    assert 0.0 <= art < 0.35
    assert conf in {"MEDIUM", "HIGH"}


def test_hrv_confidence_rppg_medium_with_spectral_override() -> None:
    conf = hrv_confidence_rppg(
        n_ibis=40,
        spectral_sqi=0.98,
        art_ratio=0.30,
        rmssd=40.3,
        sdnn=113.8,
        ibi_sqi=0.70,
    )

    assert conf == "MEDIUM"


def test_hrv_confidence_rppg_low_when_artifact_high() -> None:
    conf = hrv_confidence_rppg(
        n_ibis=40,
        spectral_sqi=0.99,
        art_ratio=0.50,
        rmssd=99.8,
        sdnn=183.5,
        ibi_sqi=0.50,
    )

    assert conf == "LOW"


def test_hrv_confidence_rppg_high_when_artifacts_low() -> None:
    conf = hrv_confidence_rppg(
        n_ibis=40,
        spectral_sqi=0.98,
        art_ratio=0.08,
        rmssd=40.3,
        sdnn=113.8,
        ibi_sqi=0.92,
    )

    assert conf == "HIGH"


def test_ibi_from_peaks_uses_bpm_hint_for_spacing() -> None:
    fs = 30.0
    t = np.arange(0.0, 20.0, 1.0 / fs)
    sig = np.sin(2.0 * np.pi * (72.0 / 60.0) * t)

    ibis_hint = ibi_from_peaks(sig, fs, bpm_hint=72.0)
    ibis_plain = ibi_from_peaks(sig, fs)

    assert ibis_hint.size >= 2
    assert ibis_plain.size >= 2
    assert float(np.median(ibis_hint)) > 700.0
