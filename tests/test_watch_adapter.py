"""Tests for hub-sample → RppgMetrics adapter (HRV port for belt samples)."""

from __future__ import annotations

import time

from rppg.calibration_watch import WatchHrHub, WatchSample
from rppg.watch_adapter import build_watch_rppg_metrics


def _feed_hub(hub: WatchHrHub, n: int = 12, bpm: int = 72) -> None:
    now = time.time()
    for i in range(n):
        hub.add(
            WatchSample(
                received_at=now - (n - i) * 0.9,
                bpm=bpm + (i % 3) - 1,
                ts_ms=int(now * 1000),
                interval_ms=1000,
                ax=0.1,
                ay=0.05,
                az=9.75,
                motion_level=0.12,
            )
        )


def test_build_watch_rppg_metrics_populates_core_fields():
    hub = WatchHrHub()
    _feed_hub(hub)
    m = build_watch_rppg_metrics(hub)
    assert m.physio_source == "watch"
    assert m.face_detected is True
    assert m.bpm > 0
    assert m.warmup_progress > 0
    assert m.sqi > 0
    assert m.quality_score > 0
    assert m.roi_valid_count >= 3
    assert m.peak_freq_hz > 0


def test_watch_disconnected_returns_empty_rppg():
    hub = WatchHrHub()
    m = build_watch_rppg_metrics(hub)
    assert m.face_detected is False
    assert m.physio_source == "watch"
