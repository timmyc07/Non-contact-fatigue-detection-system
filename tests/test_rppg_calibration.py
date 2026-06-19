"""Tests for rPPG BPM calibration store and apply helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rppg.calibration import (
    ORIGIN_VERSION_ID,
    CalibrationParams,
    CalibrationSessionAnalyzer,
    CalibrationVersion,
    CalibrationVersionStore,
    apply_bpm_calibration,
    apply_calibration_to_metrics,
    effective_bpm,
    origin_version,
    rppg_sample_quality_ok,
)
from rppg.rppg_worker import RppgMetrics


def test_apply_bpm_bias_offset():
    version = CalibrationVersion(
        id="v_test",
        name="test",
        model="bias",
        params=CalibrationParams(bpm_offset=-5.0, bpm_scale=1.0),
    )
    assert apply_bpm_calibration(76.0, version) == pytest.approx(71.0)


def test_origin_version_is_identity():
    version = origin_version()
    assert version.is_identity
    assert apply_bpm_calibration(80.0, version) == pytest.approx(80.0)


def test_apply_calibration_to_rppg_metrics():
    version = CalibrationVersion(
        id="v_test",
        name="test",
        model="bias",
        params=CalibrationParams(bpm_offset=3.0),
    )
    raw = RppgMetrics(bpm=70.0, raw_bpm=72.0, face_detected=True)
    out = apply_calibration_to_metrics(raw, version)
    assert out.bpm_calibrated == pytest.approx(73.0)
    assert out.calibration_version_id == "v_test"
    assert out.peak_freq_hz_calibrated == pytest.approx(73.0 / 60.0)


def test_effective_bpm_prefers_calibrated():
    metrics = RppgMetrics(bpm=70.0, bpm_calibrated=68.0)
    assert effective_bpm(metrics) == pytest.approx(68.0)


def test_quality_gate_rejects_low_sqi():
    sample = {
        "bpm": 72.0,
        "warmup_progress": 1.0,
        "sqi": 0.2,
        "quality_score": 0.8,
        "roi_valid_count": 4,
        "bpm_guarded": False,
    }
    assert rppg_sample_quality_ok(sample) is False


def test_calibration_rppg_bpm_prefers_raw_when_guarded():
    from rppg.calibration import calibration_rppg_bpm

    sample = {"bpm": 70.0, "raw_bpm": 78.0, "bpm_guarded": True}
    assert calibration_rppg_bpm(sample) == pytest.approx(78.0)


def test_session_analyzer_uses_calibration_gates(tmp_path: Path):
    analyzer = CalibrationSessionAnalyzer(window_sec=10.0, warmup_sec=0.0)
    start = 1000.0
    for i in range(20):
        ts = start + i
        analyzer.add_watch(ts, 72.0)
        analyzer.add_rppg(
            ts,
            {
                "bpm": 77.0,
                "warmup_progress": 1.0,
                "sqi": 0.6,
                "quality_score": 0.7,
                "roi_valid_count": 4,
                "bpm_guarded": False,
            },
        )
    result = analyzer.estimate(start, start + 20.0)
    assert result["windows_used"] >= 1
    assert result["offset_bpm"] == pytest.approx(-5.0, abs=0.5)


def test_version_store_save_and_switch(tmp_path: Path):
    store = CalibrationVersionStore(root=tmp_path / "rppg_calibration")
    version = store.save_new_version("測試", offset_bpm=-4.0, note="unit")
    assert version.id != ORIGIN_VERSION_ID
    assert store.get_active_version_id() == version.id
    store.set_active_version(ORIGIN_VERSION_ID)
    active = store.get_active_version()
    assert active.is_identity

    manifest = json.loads((tmp_path / "rppg_calibration" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["versions"]) >= 2
