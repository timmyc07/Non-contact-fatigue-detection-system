from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rppg.rppg_worker import (  # noqa: E402
    butter_bandpass,
    ibi_artifact_ratio,
    validate_ibi_intervals,
    welch_peak_hz,
)


def test_bandpass_and_welch_estimate_72_bpm() -> None:
    fs = 30.0
    t = np.arange(0.0, 12.0, 1.0 / fs)
    rng = np.random.default_rng(42)
    sig = np.sin(2.0 * np.pi * 1.2 * t) + 0.05 * rng.standard_normal(t.size)

    filtered = butter_bandpass(sig, fs, 0.65, 3.7)
    peak_hz, _, _ = welch_peak_hz(filtered, fs)

    assert abs(peak_hz * 60.0 - 72.0) < 4.0


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
