"""Derived metrics from watch HR / IMU samples (legacy helpers + HRV state)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from rppg.calibration_watch import WatchHrHub, WatchSample
from rppg.watch_adapter import build_watch_rppg_metrics
from rppg.watch_physio import WatchPhysioState, compute_watch_physio, imu_motion_gate


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# Backward-compatible alias used by tests / imports
WatchHrvState = WatchPhysioState
compute_watch_hrv = compute_watch_physio


@dataclass
class WatchMetrics:
    connected: bool = False
    bpm: int = 0
    motion_level: float | None = None
    age_sec: float = 0.0
    bpm_score: float = 0.0
    motion_score: float = 0.0
    hrv_score: float = 0.0
    imu_gate: float = 1.0
    watch_sub: float = 0.0
    rmssd: float = 0.0
    sdnn: float = 0.0
    lf_hf: float = 0.0
    stress_prob: float = 0.0
    stress_status: str = "calibrating"
    hrv_confidence: str = "LOW"
    ibi_artifact_ratio: float = 1.0
    hrv_ready: bool = False
    hrv_sample_count: int = 0
    sqi: float = 0.0
    quality_score: float = 0.0
    warmup_progress: float = 0.0


def bpm_deviation_score(
    bpm: int,
    *,
    normal_lo: float = 60.0,
    normal_hi: float = 100.0,
    max_dev: float = 40.0,
) -> float:
    if bpm <= 0:
        return 0.0
    val = float(bpm)
    if val < normal_lo:
        return _clamp((normal_lo - val) / max_dev)
    if val > normal_hi:
        return _clamp((val - normal_hi) / max_dev)
    return 0.0


def metrics_from_sample(
    sample: WatchSample | None,
    *,
    connected: bool = False,
    physio: WatchPhysioState | None = None,
    bpm_normal_lo: float = 60.0,
    bpm_normal_hi: float = 100.0,
    bpm_max_dev: float = 40.0,
    motion_active_min: float = 1.5,
    motion_still_max: float = 0.35,
) -> WatchMetrics:
    if sample is None or not connected:
        return WatchMetrics(connected=False)

    state = physio or WatchPhysioState()
    age = max(0.0, time.time() - sample.received_at)
    bpm_s = bpm_deviation_score(
        sample.bpm,
        normal_lo=bpm_normal_lo,
        normal_hi=bpm_normal_hi,
        max_dev=bpm_max_dev,
    )
    gate, motion_s = imu_motion_gate(
        sample.motion_level,
        still_max=motion_still_max,
        active_min=motion_active_min,
    )
    hrv_s = _clamp(state.stress_prob) if state.hrv_ready else 0.0

    return WatchMetrics(
        connected=True,
        bpm=sample.bpm,
        motion_level=sample.motion_level,
        age_sec=age,
        bpm_score=bpm_s,
        motion_score=motion_s,
        hrv_score=hrv_s,
        imu_gate=gate,
        watch_sub=0.0,
        rmssd=state.rmssd,
        sdnn=state.sdnn,
        lf_hf=state.lf_hf,
        stress_prob=state.stress_prob,
        stress_status=state.stress_status,
        hrv_confidence=state.hrv_confidence,
        ibi_artifact_ratio=state.ibi_artifact_ratio,
        hrv_ready=state.hrv_ready,
        hrv_sample_count=state.sample_count,
        sqi=state.sqi,
        quality_score=state.quality_score,
        warmup_progress=state.warmup_progress,
    )


def metrics_from_hub(hub: WatchHrHub, **kwargs: object) -> WatchMetrics:
    physio = compute_watch_physio(hub.snapshot())
    sample = hub.latest()
    return metrics_from_sample(
        sample,
        connected=hub.is_connected(),
        physio=physio,
        **kwargs,  # type: ignore[arg-type]
    )


__all__ = [
    "WatchMetrics",
    "WatchHrvState",
    "bpm_deviation_score",
    "build_watch_rppg_metrics",
    "compute_watch_hrv",
    "imu_motion_gate",
    "metrics_from_hub",
    "metrics_from_sample",
]
