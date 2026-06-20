"""Map watch HTTP samples to :class:`RppgMetrics` for full UI / fusion parity."""

from __future__ import annotations

from typing import Any

from rppg.calibration import CalibrationVersion, apply_calibration_to_metrics
from rppg.calibration_watch import WatchHrHub, WatchSample
from rppg.rppg_worker import RppgMetrics
from rppg.watch_physio import WatchPhysioState, compute_watch_physio


def _roi_valid_count(connected: bool, physio: WatchPhysioState) -> int:
    if not connected:
        return 0
    if physio.hrv_ready and physio.quality_score >= 0.55:
        return 4
    if physio.sample_count >= 6:
        return 3
    if physio.sample_count >= 2:
        return 1
    return 0


def _virtual_roi_weights(valid_count: int) -> tuple[float, float, float, float]:
    if valid_count >= 4:
        return 0.25, 0.25, 0.25, 0.25
    if valid_count >= 1:
        return 1.0, 0.0, 0.0, 0.0
    return 0.0, 0.0, 0.0, 0.0


def watch_sample_to_rppg_metrics(
    sample: WatchSample | None,
    physio: WatchPhysioState,
    *,
    connected: bool = False,
    calibration_version: CalibrationVersion | None = None,
) -> RppgMetrics:
    """Build rPPG-compatible metrics from the latest watch sample + physio state."""
    if sample is None or not connected or int(sample.bpm) <= 0:
        return RppgMetrics(face_detected=False, physio_source="watch")

    bpm = float(int(sample.bpm))
    raw_bpm = bpm
    if physio.bpm_guarded:
        bpm = max(40.0, bpm - physio.bpm_delta * 0.35)

    roi_valid = _roi_valid_count(connected, physio)
    wf, wl, wr, wg = _virtual_roi_weights(roi_valid)
    motion = physio.motion_level
    jitter = float(motion) if motion is not None else 0.0
    area_stability = 1.0 if motion is None or motion <= 0.35 else max(0.2, 1.0 - motion / 1.5)

    metrics = RppgMetrics(
        bpm=bpm,
        raw_bpm=raw_bpm,
        bpm_delta=physio.bpm_delta,
        bpm_guarded=physio.bpm_guarded,
        bpm_guard_reason=physio.bpm_guard_reason,
        rmssd=physio.rmssd,
        sdnn=physio.sdnn,
        lf_hf=physio.lf_hf,
        sqi=physio.sqi,
        stress_prob=physio.stress_prob,
        stress_status=physio.stress_status,
        hrv_confidence=physio.hrv_confidence,
        ibi_artifact_ratio=physio.ibi_artifact_ratio,
        peak_freq_hz=physio.peak_freq_hz,
        warmup_progress=physio.warmup_progress,
        quality_score=physio.quality_score,
        pose_roll_deg=physio.pose_roll_deg,
        pose_yaw_deg=physio.pose_yaw_deg,
        pose_pitch_deg=physio.pose_pitch_deg,
        roi_valid_count=roi_valid,
        roi_weight_forehead=wf,
        roi_weight_l_cheek=wl,
        roi_weight_r_cheek=wr,
        roi_weight_glabella=wg,
        landmark_jitter_norm=jitter,
        roi_area_stability=area_stability,
        roi_area_jitter_ratio=max(0.0, 1.0 - area_stability),
        roi_smoothing_applied=False,
        canonical_roi_warp_used=False,
        face_detected=True,
        waveform=list(physio.waveform),
        psd_freqs=list(physio.psd_freqs),
        psd_vals=list(physio.psd_vals),
        physio_source="watch",
    )

    if calibration_version is not None:
        metrics = apply_calibration_to_metrics(metrics, calibration_version)

    return metrics


def build_watch_rppg_metrics(
    hub: WatchHrHub,
    calibration_version: CalibrationVersion | None = None,
    **physio_kwargs: Any,
) -> RppgMetrics:
    samples = hub.snapshot()
    physio = compute_watch_physio(samples, **physio_kwargs)
    sample = hub.latest()
    connected = hub.is_connected()
    return watch_sample_to_rppg_metrics(
        sample,
        physio,
        connected=connected,
        calibration_version=calibration_version,
    )
