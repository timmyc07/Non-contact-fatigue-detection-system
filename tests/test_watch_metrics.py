"""Tests for the HR-reference physiology helpers (HRV port for belt samples).

手錶 HTTP 融合模式已移除；此檔保留供心跳帶樣本計算 HRV 的純運算層測試
（`rppg/watch_physio.py`）。
"""

from __future__ import annotations

import time

import numpy as np

from rppg.calibration_watch import WatchSample
from rppg.watch_physio import compute_watch_physio, ibis_from_watch_samples, imu_motion_gate


def test_imu_motion_gate_active_motion():
    gate, motion_s = imu_motion_gate(2.0)
    assert gate < 0.5
    assert motion_s > 0.0


def test_ibis_from_watch_samples():
    samples = [WatchSample(time.time(), 60 + i, 0, 1000) for i in range(5)]
    ibis = ibis_from_watch_samples(samples)
    assert ibis.size == 5
    assert np.all(ibis > 0)


def test_compute_watch_physio_requires_min_samples():
    samples = [WatchSample(time.time(), 72, 0, 1000) for _ in range(4)]
    state = compute_watch_physio(samples, min_samples=8)
    assert state.hrv_ready is False


def test_compute_watch_physio_with_enough_samples():
    now = time.time()
    samples = [
        WatchSample(now - (20 - i), 70 + (i % 3), 0, 1000, motion_level=0.1)
        for i in range(20)
    ]
    state = compute_watch_physio(samples, min_samples=8)
    assert state.sample_count >= 8
    assert state.rmssd >= 0.0
