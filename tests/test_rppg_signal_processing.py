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
    ibi_artifact_ratio,
    validate_ibi_intervals,
    welch_peak_hz,
)
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
    demo = RppgDemo(buffer_sec=1.0, target_fps=30.0)
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
