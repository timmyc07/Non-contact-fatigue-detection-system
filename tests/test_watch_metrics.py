"""Tests for watch HR / IMU payload parsing and derived metrics."""

from __future__ import annotations

import time

import numpy as np

from gui.fatigue_scorer import FatigueFuser, FuserConfig
from rppg.calibration_watch import WatchSample, parse_watch_hr_payload
from rppg.rppg_worker import RppgMetrics
from rppg.watch_hrv import compute_watch_hrv, ibis_from_watch_samples
from rppg.watch_metrics import bpm_deviation_score, imu_motion_gate, metrics_from_sample


def test_parse_watch_hr_payload_without_imu():
    sample = parse_watch_hr_payload({"bpm": 72, "ts": 1000, "interval_ms": 1000})
    assert sample.bpm == 72
    assert sample.ts_ms == 1000
    assert sample.interval_ms == 1000
    assert sample.has_imu is False


def test_parse_watch_hr_payload_with_imu():
    sample = parse_watch_hr_payload(
        {
            "bpm": 80,
            "ts": 2000,
            "interval_ms": 500,
            "imu": {"ax": 0.1, "ay": 0.2, "az": 9.7, "motion_level": 0.15},
        }
    )
    assert sample.bpm == 80
    assert sample.has_imu is True
    assert sample.motion_level == 0.15


def test_metrics_from_sample_still_imu_high_gate():
    sample = WatchSample(time.time(), 72, 0, 1000, motion_level=0.1)
    metrics = metrics_from_sample(sample, connected=True)
    assert metrics.connected is True
    assert metrics.imu_gate == 1.0
    assert metrics.bpm_score == 0.0


def test_bpm_deviation_score_out_of_range():
    assert bpm_deviation_score(120) > 0.0
    assert bpm_deviation_score(72) == 0.0


def test_imu_motion_gate_active_motion():
    gate, motion_s = imu_motion_gate(2.0)
    assert gate < 0.5
    assert motion_s > 0.0


def test_ibis_from_watch_samples():
    samples = [WatchSample(time.time(), 60 + i, 0, 1000) for i in range(5)]
    ibis = ibis_from_watch_samples(samples)
    assert ibis.size == 5
    assert np.all(ibis > 0)


def test_compute_watch_hrv_requires_min_samples():
    samples = [WatchSample(time.time(), 72, 0, 1000) for _ in range(4)]
    state = compute_watch_hrv(samples, min_samples=8)
    assert state.hrv_ready is False


def test_compute_watch_hrv_with_enough_samples():
    now = time.time()
    samples = [
        WatchSample(now - (20 - i), 70 + (i % 3), 0, 1000, motion_level=0.1)
        for i in range(20)
    ]
    state = compute_watch_hrv(samples, min_samples=8)
    assert state.sample_count >= 8
    assert state.rmssd >= 0.0


def test_fuser_watch_mode_uses_watch_pillar():
    fuser = FatigueFuser(FuserConfig.for_watch())
    watch = RppgMetrics(
        bpm=120.0,
        raw_bpm=120.0,
        face_detected=True,
        warmup_progress=1.0,
        sqi=0.8,
        quality_score=0.8,
        roi_valid_count=4,
        stress_prob=0.4,
        rmssd=30.0,
        lf_hf=1.8,
        hrv_confidence="MEDIUM",
        physio_source="watch",
    )
    fused = fuser.update(rppg=watch, fatigue=None)
    assert fused.fatigue_mode == "watch"
    assert fused.watch_available is True
    assert fused.score > 0.0
