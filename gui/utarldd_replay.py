"""UTA-RLDD video replay analysis.

This module treats dataset videos as deterministic camera input and reuses the
production fatigue/rPPG engines to write normal MetricsRecorder databases.
"""

from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import cv2
import mediapipe as mp
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

from gui.fatigue_engine import FatigueEngine
from gui.fatigue_scorer import FatigueFuser
from gui.fatigue_worker import draw_fatigue_annotations
from gui.mediapipe_tuning import load_mediapipe_tuning
from gui.metrics_recorder import MetricsRecorder
from rppg.rppg_worker import (
    RppgEngine,
    RoiGeometryTracker,
    collect_rppg_roi_sample,
    draw_rois,
    ensure_face_model,
    _MODELS_DIR,
)


UTARLDD_LABELS: dict[str, str] = {
    "0": "Alert",
    "5": "Low Vigilant",
    "10": "Drowsy",
}
VIDEO_EXTS = {".mov", ".mp4"}


@dataclass(frozen=True)
class UtaRlddVideo:
    subject: str
    label: str
    label_name: str
    path: Path


@dataclass
class UtaRlddVideoSummary:
    subject: str
    label: str
    label_name: str
    video_path: str
    db_path: str = ""
    annotated_video_path: str = ""
    status: str = "pending"
    error: str = ""
    frames: int = 0
    face_frames: int = 0
    face_rate: float = 0.0
    duration_sec: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    avg_fatigue_score: float = 0.0
    p95_fatigue_score: float = 0.0
    avg_fused_score: float = 0.0
    p95_fused_score: float = 0.0
    avg_perclos: float = 0.0
    max_perclos: float = 0.0
    avg_blink_temporal: float = 0.0
    max_blink_temporal: float = 0.0
    avg_rppg_quality: float = 0.0
    avg_sqi: float = 0.0
    avg_bpm: float = 0.0
    bpm_guard_count: int = 0
    low_vigilance_frames: int = 0
    drowsy_frames: int = 0
    critical_frames: int = 0
    microsleep_frames: int = 0
    no_face_frames: int = 0
    ok_frames: int = 0
    calibrating_frames: int = 0
    status_counts_json: str = "{}"


@dataclass
class UtaRlddBatchResult:
    output_dir: Path
    summary_csv: Path
    full_summary_csv: Path
    manifest_path: Path
    videos_total: int
    videos_done: int
    videos_failed: int
    summaries: list[UtaRlddVideoSummary] = field(default_factory=list)


ProgressCallback = Callable[[str, int, int, UtaRlddVideoSummary | None], None]
PreviewFrameCallback = Callable[[QImage], None]
_PREVIEW_TARGET_FPS = 20.0
_PREVIEW_MAX_WIDTH = 960
_PREVIEW_MAX_HEIGHT = 540


def parse_utarldd_label(path: Path) -> tuple[str, str]:
    label = path.stem
    if label not in UTARLDD_LABELS:
        raise ValueError(f"不支援的 UTA-RLDD label: {path.name}")
    return label, UTARLDD_LABELS[label]


def discover_utarldd_videos(
    root: Path,
    *,
    subjects: Iterable[str] | None = None,
    labels: Iterable[str] | None = None,
) -> list[UtaRlddVideo]:
    root = Path(root)
    subject_filter = {str(s) for s in subjects or []}
    label_filter = {str(l) for l in labels or []}
    videos: list[UtaRlddVideo] = []
    if not root.exists():
        raise FileNotFoundError(f"UTA-RLDD 目錄不存在: {root}")

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            continue
        try:
            label, label_name = parse_utarldd_label(path)
        except ValueError:
            continue
        subject = path.parent.name
        if subject_filter and subject not in subject_filter:
            continue
        if label_filter and label not in label_filter:
            continue
        videos.append(UtaRlddVideo(subject=subject, label=label, label_name=label_name, path=path))
    videos.sort(key=lambda item: (item.subject, int(item.label), item.path.name.lower()))
    return videos


def _safe_avg(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def _safe_percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(values, percentile)) if values else 0.0


def _fourcc_to_str(raw: int) -> str:
    return "".join(chr((raw >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00").upper()


def _make_record_payload(
    *,
    video: UtaRlddVideo,
    timestamp: float,
    fps: float,
    width: int,
    height: int,
    codec: str,
    r: Any,
    f: Any,
    z: Any,
) -> dict[str, Any]:
    return {
        "timestamp": float(timestamp),
        "fps": float(fps),
        "frame_width": int(width),
        "frame_height": int(height),
        "codec": str(codec or ""),
        "camera_label": f"UTA-RLDD subject={video.subject} label={video.label}",
        "rppg_face_detected": 1 if getattr(r, "face_detected", False) else 0,
        "bpm": float(getattr(r, "bpm", 0.0) or 0.0),
        "raw_bpm": float(getattr(r, "raw_bpm", 0.0) or 0.0),
        "bpm_delta": float(getattr(r, "bpm_delta", 0.0) or 0.0),
        "bpm_guarded": 1 if getattr(r, "bpm_guarded", False) else 0,
        "bpm_guard_reason": str(getattr(r, "bpm_guard_reason", "") or ""),
        "rmssd": float(getattr(r, "rmssd", 0.0) or 0.0),
        "sdnn": float(getattr(r, "sdnn", 0.0) or 0.0),
        "lf_hf": float(getattr(r, "lf_hf", 0.0) or 0.0),
        "sqi": float(getattr(r, "sqi", 0.0) or 0.0),
        "rppg_quality_score": float(getattr(r, "quality_score", 0.0) or 0.0),
        "rppg_pose_roll_deg": float(getattr(r, "pose_roll_deg", 0.0) or 0.0),
        "rppg_pose_yaw_deg": float(getattr(r, "pose_yaw_deg", 0.0) or 0.0),
        "rppg_pose_pitch_deg": float(getattr(r, "pose_pitch_deg", 0.0) or 0.0),
        "rppg_roi_valid_count": int(getattr(r, "roi_valid_count", 0) or 0),
        "rppg_roi_weight_forehead": float(getattr(r, "roi_weight_forehead", 0.0) or 0.0),
        "rppg_roi_weight_l_cheek": float(getattr(r, "roi_weight_l_cheek", 0.0) or 0.0),
        "rppg_roi_weight_r_cheek": float(getattr(r, "roi_weight_r_cheek", 0.0) or 0.0),
        "rppg_roi_weight_glabella": float(getattr(r, "roi_weight_glabella", 0.0) or 0.0),
        "rppg_landmark_jitter_norm": float(getattr(r, "landmark_jitter_norm", 0.0) or 0.0),
        "rppg_roi_area_stability": float(getattr(r, "roi_area_stability", 0.0) or 0.0),
        "rppg_roi_area_jitter_ratio": float(getattr(r, "roi_area_jitter_ratio", 0.0) or 0.0),
        "rppg_roi_smoothing_applied": 1 if getattr(r, "roi_smoothing_applied", False) else 0,
        "rppg_canonical_roi_warp_used": 1 if getattr(r, "canonical_roi_warp_used", False) else 0,
        "stress_prob": float(getattr(r, "stress_prob", 0.0) or 0.0),
        "stress_status": str(getattr(r, "stress_status", "") or ""),
        "hrv_confidence": str(getattr(r, "hrv_confidence", "") or ""),
        "ibi_artifact_ratio": float(getattr(r, "ibi_artifact_ratio", 0.0) or 0.0),
        "peak_freq_hz": float(getattr(r, "peak_freq_hz", 0.0) or 0.0),
        "frame_brightness": float(getattr(r, "frame_brightness", 0.0) or 0.0),
        "warmup_progress": float(getattr(r, "warmup_progress", 0.0) or 0.0),
        "fatigue_face_detected": 1 if getattr(f, "face_detected", False) else 0,
        "calibrated": 1 if getattr(f, "calibrated", False) else 0,
        "status": str(getattr(f, "status", "") or ""),
        "fatigue_level": float(getattr(f, "fatigue_level", 0.0) or 0.0),
        "early_warning": 1 if getattr(f, "early_warning", False) else 0,
        "ear": float(getattr(f, "ear", 0.0) or 0.0),
        "ear_smooth": float(getattr(f, "ear_smooth", 0.0) or 0.0),
        "blink_count": int(getattr(f, "blink_count", 0) or 0),
        "perclos": float(getattr(f, "perclos", 0.0) or 0.0),
        "blink_rate_pm": float(getattr(f, "blink_rate_pm", 0.0) or 0.0),
        "blink_duration_sec": float(getattr(f, "blink_duration_sec", 0.0) or 0.0),
        "blink_duration_mean_sec": float(getattr(f, "blink_duration_mean_sec", 0.0) or 0.0),
        "blink_duration_z": float(getattr(f, "blink_duration_z", 0.0) or 0.0),
        "blink_amplitude": float(getattr(f, "blink_amplitude", 0.0) or 0.0),
        "blink_opening_velocity": float(getattr(f, "blink_opening_velocity", 0.0) or 0.0),
        "blink_opening_velocity_z": float(getattr(f, "blink_opening_velocity_z", 0.0) or 0.0),
        "blink_temporal_score": float(getattr(f, "blink_temporal_score", 0.0) or 0.0),
        "is_squinting": 1 if getattr(f, "is_squinting", False) else 0,
        "squint_duration": float(getattr(f, "squint_duration", 0.0) or 0.0),
        "is_frowning": 1 if getattr(f, "is_frowning", False) else 0,
        "brow_dist_norm": float(getattr(f, "brow_dist_norm", 0.0) or 0.0),
        "iris_ratio": float(getattr(f, "iris_ratio", 0.0) or 0.0),
        "iris_ratio_trend": float(getattr(f, "iris_ratio_trend", 0.0) or 0.0),
        "gaze_x": float(getattr(f, "gaze_x", 0.0) or 0.0),
        "gaze_y": float(getattr(f, "gaze_y", 0.0) or 0.0),
        "gaze_stability_index": float(getattr(f, "gaze_stability_index", 0.0) or 0.0),
        "gaze_mental_fatigue": 1 if getattr(f, "gaze_mental_fatigue", False) else 0,
        "saccadic_velocity": float(getattr(f, "saccadic_velocity", 0.0) or 0.0),
        "is_saccade": 1 if getattr(f, "is_saccade", False) else 0,
        "fixation_duration": float(getattr(f, "fixation_duration", 0.0) or 0.0),
        "saccade_freq_pm": float(getattr(f, "saccade_freq_pm", 0.0) or 0.0),
        "head_pitch": float(getattr(f, "head_pitch", 0.0) or 0.0),
        "head_yaw": float(getattr(f, "head_yaw", 0.0) or 0.0),
        "head_roll": float(getattr(f, "head_roll", 0.0) or 0.0),
        "fatigue_quality_score": float(getattr(f, "quality_score", 0.0) or 0.0),
        "fatigue_blend_calib_progress": float(getattr(f, "blend_calib_progress", 0.0) or 0.0),
        "microsleep_alert": 1 if getattr(f, "microsleep_alert", False) else 0,
        "microsleep_count": int(getattr(f, "microsleep_count", 0) or 0),
        "mar": float(getattr(f, "mar", 0.0) or 0.0),
        "yawn_detected": 1 if getattr(f, "yawn_detected", False) else 0,
        "yawn_count": int(getattr(f, "yawn_count", 0) or 0),
        "has_iris": 1 if getattr(f, "has_iris", False) else 0,
        "calib_progress": float(getattr(f, "calib_progress", 0.0) or 0.0),
        "fused_score": float(getattr(z, "score", 0.0) or 0.0),
        "fused_level": str(getattr(z, "level", "") or ""),
        "fused_level_en": str(getattr(z, "level_en", "") or ""),
        "fused_rppg_sub": float(getattr(z, "rppg_sub", 0.0) or 0.0),
        "fused_behavior_sub": float(getattr(z, "behavior_sub", 0.0) or 0.0),
        "fused_rppg_weight_eff": float(getattr(z, "rppg_weight_eff", 0.0) or 0.0),
        "fused_behavior_weight_eff": float(getattr(z, "behavior_weight_eff", 0.0) or 0.0),
        "fused_trend": float(getattr(z, "trend", 0.0) or 0.0),
        "fused_trend_symbol": str(getattr(z, "trend_symbol", "") or ""),
        "fused_rppg_available": 1 if getattr(z, "rppg_available", False) else 0,
        "fused_behavior_available": 1 if getattr(z, "behavior_available", False) else 0,
        "fused_rppg_stress_score": float(getattr(z, "rppg_stress_score", 0.0) or 0.0),
        "fused_rppg_bpm_score": float(getattr(z, "rppg_bpm_score", 0.0) or 0.0),
        "fused_beh_perclos_score": float(getattr(z, "beh_perclos_score", 0.0) or 0.0),
        "fused_beh_blink_temporal_score": float(getattr(z, "beh_blink_temporal_score", 0.0) or 0.0),
        "fused_beh_squint_score": float(getattr(z, "beh_squint_score", 0.0) or 0.0),
        "fused_beh_microsleep_score": float(getattr(z, "beh_microsleep_score", 0.0) or 0.0),
        "fused_beh_gaze_score": float(getattr(z, "beh_gaze_score", 0.0) or 0.0),
        "fused_beh_frown_score": float(getattr(z, "beh_frown_score", 0.0) or 0.0),
        "fused_beh_yawn_score": float(getattr(z, "beh_yawn_score", 0.0) or 0.0),
    }


def _writer_for(path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    return cv2.VideoWriter(str(path), fourcc, fps if fps > 0 else 30.0, (width, height))


def _bgr_to_qimage(bgr: np.ndarray, *, max_width: int = 0, max_height: int = 0) -> QImage:
    if max_width > 0 or max_height > 0:
        height, width = bgr.shape[:2]
        scale_w = (max_width / width) if max_width > 0 and width > 0 else 1.0
        scale_h = (max_height / height) if max_height > 0 and height > 0 else 1.0
        scale = min(scale_w, scale_h, 1.0)
        if scale < 1.0:
            bgr = cv2.resize(
                bgr,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    height, width = rgb.shape[:2]
    qimg = QImage(
        rgb.data,
        width,
        height,
        rgb.strides[0],
        QImage.Format.Format_RGB888,
    )
    return qimg.copy()


def run_replay_video(
    video: UtaRlddVideo,
    output_dir: Path,
    run_stamp: str,
    *,
    max_frames: int = 0,
    write_annotated_video: bool = False,
    progress_cb: ProgressCallback | None = None,
    preview_frame_cb: PreviewFrameCallback | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> UtaRlddVideoSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = UtaRlddVideoSummary(
        subject=video.subject,
        label=video.label,
        label_name=video.label_name,
        video_path=str(video.path),
    )
    db_path = output_dir / f"metrics_utarldd_{video.subject}_{video.label}_{run_stamp}.db"
    summary.db_path = str(db_path)
    cap = cv2.VideoCapture(str(video.path))
    if not cap.isOpened():
        summary.status = "failed"
        summary.error = "OpenCV 無法開啟影片"
        return summary

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    codec = _fourcc_to_str(int(cap.get(cv2.CAP_PROP_FOURCC) or 0))
    summary.fps = fps
    summary.width = width
    summary.height = height
    writer = None
    if write_annotated_video:
        annotated_path = output_dir / f"video_utarldd_{video.subject}_{video.label}_{run_stamp}.mp4"
        writer = _writer_for(annotated_path, fps, width, height)
        if writer.isOpened():
            summary.annotated_video_path = str(annotated_path)
        else:
            writer.release()
            writer = None

    recorder = MetricsRecorder(str(db_path))
    rppg_engine = RppgEngine(buffer_sec=12.0, target_fps=fps)
    roi_tracker = RoiGeometryTracker()
    fatigue_engine = FatigueEngine()
    fuser = FatigueFuser()
    tuning = load_mediapipe_tuning()
    model_path = ensure_face_model(_MODELS_DIR)
    options = _mp_vision.FaceLandmarkerOptions(
        base_options=_mp_python.BaseOptions(model_asset_path=str(model_path)),
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        min_face_detection_confidence=tuning.face_landmarker.min_face_detection_confidence,
        min_face_presence_confidence=tuning.face_landmarker.min_face_presence_confidence,
        min_tracking_confidence=tuning.face_landmarker.min_tracking_confidence,
        num_faces=max(1, int(tuning.face_landmarker.num_faces)),
        running_mode=_mp_vision.RunningMode.VIDEO,
    )

    fatigue_scores: list[float] = []
    fused_scores: list[float] = []
    perclos_values: list[float] = []
    blink_temporal_values: list[float] = []
    rppg_quality_values: list[float] = []
    sqi_values: list[float] = []
    bpm_values: list[float] = []
    status_counts: dict[str, int] = {}
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ts_ms_prev = 0
    preview_interval_sec = 1.0 / min(max(fps, 1.0), _PREVIEW_TARGET_FPS)
    next_preview_ts = 0.0

    try:
        with _mp_vision.FaceLandmarker.create_from_options(options) as landmarker:
            while True:
                if stop_requested is not None and stop_requested():
                    summary.status = "stopped"
                    break
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    break
                summary.frames += 1
                if max_frames > 0 and summary.frames > max_frames:
                    summary.frames -= 1
                    break

                timestamp = (summary.frames - 1) / max(fps, 1e-6)
                ts_ms = max(ts_ms_prev + 1, int(timestamp * 1000.0))
                ts_ms_prev = ts_ms
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
                result = landmarker.detect_for_video(mp_img, ts_ms)
                annotated_needed = writer is not None or preview_frame_cb is not None
                annotated = bgr.copy() if annotated_needed else bgr

                if result.face_landmarks:
                    summary.face_frames += 1
                    lm = result.face_landmarks[0]
                    blendshapes = result.face_blendshapes[0] if result.face_blendshapes else None
                    transform_matrix = (
                        result.facial_transformation_matrixes[0]
                        if result.facial_transformation_matrixes else None
                    )
                    f_metrics = fatigue_engine.step(lm, width, height, timestamp, blendshapes=blendshapes)
                    f_metrics.face_detected = True
                    sample, roi_weights, roi_valid_count = collect_rppg_roi_sample(
                        bgr, lm, transform_matrix, roi_tracker, tuning
                    )
                    if sample is not None:
                        rppg_engine.push(timestamp, sample[0], sample[1], sample[2])
                    r_metrics = rppg_engine.compute(
                        timestamp,
                        bgr,
                        lm,
                        transform_matrix=transform_matrix,
                        roi_valid_count=roi_valid_count,
                        roi_weights=roi_weights,
                        roi_tracker=roi_tracker,
                        tuning=tuning,
                    )
                    r_metrics.face_detected = True
                    fused = fuser.update(rppg=r_metrics, fatigue=f_metrics)
                    if annotated_needed:
                        annotated = draw_fatigue_annotations(annotated, lm, f_metrics)
                        draw_rois(annotated, lm, transform_matrix, roi_tracker, tuning)
                else:
                    roi_tracker.reset()
                    rppg_engine.reset()
                    f_metrics = fatigue_engine.on_no_face()
                    r_metrics = None
                    fused = fuser.update(rppg=None, fatigue=f_metrics)
                    summary.no_face_frames += 1

                payload = _make_record_payload(
                    video=video,
                    timestamp=timestamp,
                    fps=fps,
                    width=width,
                    height=height,
                    codec=codec,
                    r=r_metrics,
                    f=f_metrics,
                    z=fused,
                )
                recorder.record(payload)
                status = str(payload.get("status") or "NO_FACE")
                status_counts[status] = status_counts.get(status, 0) + 1
                fatigue_scores.append(float(payload["fatigue_level"]))
                fused_scores.append(float(payload["fused_score"]))
                perclos_values.append(float(payload["perclos"]))
                blink_temporal_values.append(float(payload["blink_temporal_score"]))
                rppg_quality_values.append(float(payload["rppg_quality_score"]))
                sqi_values.append(float(payload["sqi"]))
                bpm = float(payload["bpm"])
                if bpm > 0:
                    bpm_values.append(bpm)
                summary.bpm_guard_count += int(payload["bpm_guarded"])
                if writer is not None:
                    writer.write(annotated)
                if preview_frame_cb and (summary.frames == 1 or timestamp + 1e-9 >= next_preview_ts):
                    preview_frame_cb(
                        _bgr_to_qimage(
                            annotated,
                            max_width=_PREVIEW_MAX_WIDTH,
                            max_height=_PREVIEW_MAX_HEIGHT,
                        )
                    )
                    while next_preview_ts <= timestamp + 1e-9:
                        next_preview_ts += preview_interval_sec
                if progress_cb and summary.frames % max(1, int(fps)) == 0:
                    progress_cb("frame", summary.frames, total_frames, replace(summary))
    except Exception as exc:
        summary.status = "failed"
        summary.error = str(exc)
    finally:
        recorder.close()
        cap.release()
        if writer is not None:
            writer.release()

    if summary.status == "pending":
        summary.status = "done"
    summary.face_rate = summary.face_frames / max(summary.frames, 1)
    summary.duration_sec = summary.frames / max(fps, 1e-6)
    summary.avg_fatigue_score = _safe_avg(fatigue_scores)
    summary.p95_fatigue_score = _safe_percentile(fatigue_scores, 95)
    summary.avg_fused_score = _safe_avg(fused_scores)
    summary.p95_fused_score = _safe_percentile(fused_scores, 95)
    summary.avg_perclos = _safe_avg(perclos_values)
    summary.max_perclos = max(perclos_values) if perclos_values else 0.0
    summary.avg_blink_temporal = _safe_avg(blink_temporal_values)
    summary.max_blink_temporal = max(blink_temporal_values) if blink_temporal_values else 0.0
    summary.avg_rppg_quality = _safe_avg(rppg_quality_values)
    summary.avg_sqi = _safe_avg(sqi_values)
    summary.avg_bpm = _safe_avg(bpm_values)
    summary.ok_frames = status_counts.get("OK", 0)
    summary.low_vigilance_frames = status_counts.get("LOW_VIGILANCE", 0)
    summary.drowsy_frames = status_counts.get("DROWSY", 0)
    summary.critical_frames = status_counts.get("CRITICAL", 0)
    summary.microsleep_frames = status_counts.get("MICROSLEEP", 0)
    summary.no_face_frames = status_counts.get("NO_FACE", summary.no_face_frames)
    summary.calibrating_frames = status_counts.get("CALIBRATING", 0)
    summary.status_counts_json = json.dumps(status_counts, ensure_ascii=False, sort_keys=True)
    return summary


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 2)


def _num(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _quick_reading(summary: UtaRlddVideoSummary) -> str:
    if summary.status == "failed":
        return "處理失敗"
    if summary.status == "stopped":
        return "使用者中止"
    if summary.frames <= 0:
        return "沒有有效幀"
    if summary.face_rate < 0.8:
        return "人臉偵測不足"
    if summary.calibrating_frames / max(summary.frames, 1) >= 0.8:
        return "校準中，尚不足判斷"
    drowsy_ratio = (summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames) / max(summary.frames, 1)
    low_ratio = summary.low_vigilance_frames / max(summary.frames, 1)
    if drowsy_ratio >= 0.05 or summary.p95_fused_score >= 0.65 or summary.max_perclos >= 0.25:
        return "高疲勞跡象"
    if low_ratio >= 0.05 or summary.avg_fused_score >= 0.35 or summary.max_perclos >= 0.10:
        return "可能低警覺"
    return "未見明顯疲勞"


def write_summary_csv(path: Path, summaries: list[UtaRlddVideoSummary]) -> None:
    """Write a human-readable summary for quick review in Excel/VS Code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "受試者",
        "資料集標籤",
        "警覺類別",
        "快速判讀",
        "處理狀態",
        "總幀數",
        "偵測到臉幀數",
        "人臉偵測率(%)",
        "影片秒數",
        "FPS",
        "平均疲勞分數(0-1)",
        "95分位疲勞分數(0-1)",
        "平均融合分數(0-1)",
        "95分位融合分數(0-1)",
        "平均PERCLOS(%)",
        "最高PERCLOS(%)",
        "平均眨眼時序分數(0-1)",
        "最高眨眼時序分數(0-1)",
        "平均rPPG品質(0-1)",
        "平均SQI(0-1)",
        "平均BPM",
        "BPM保護次數",
        "低警覺幀數",
        "嗜睡幀數",
        "危急幀數",
        "微睡幀數",
        "無臉幀數",
        "校準中幀數",
        "正常幀數",
        "狀態分布",
        "錯誤訊息",
        "影片路徑",
        "SQLite資料庫",
        "標註影片",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(
                {
                    "受試者": summary.subject,
                    "資料集標籤": summary.label,
                    "警覺類別": summary.label_name,
                    "快速判讀": _quick_reading(summary),
                    "處理狀態": summary.status,
                    "總幀數": summary.frames,
                    "偵測到臉幀數": summary.face_frames,
                    "人臉偵測率(%)": _pct(summary.face_rate),
                    "影片秒數": _num(summary.duration_sec, 2),
                    "FPS": _num(summary.fps, 2),
                    "平均疲勞分數(0-1)": _num(summary.avg_fatigue_score),
                    "95分位疲勞分數(0-1)": _num(summary.p95_fatigue_score),
                    "平均融合分數(0-1)": _num(summary.avg_fused_score),
                    "95分位融合分數(0-1)": _num(summary.p95_fused_score),
                    "平均PERCLOS(%)": _pct(summary.avg_perclos),
                    "最高PERCLOS(%)": _pct(summary.max_perclos),
                    "平均眨眼時序分數(0-1)": _num(summary.avg_blink_temporal),
                    "最高眨眼時序分數(0-1)": _num(summary.max_blink_temporal),
                    "平均rPPG品質(0-1)": _num(summary.avg_rppg_quality),
                    "平均SQI(0-1)": _num(summary.avg_sqi),
                    "平均BPM": _num(summary.avg_bpm, 1),
                    "BPM保護次數": summary.bpm_guard_count,
                    "低警覺幀數": summary.low_vigilance_frames,
                    "嗜睡幀數": summary.drowsy_frames,
                    "危急幀數": summary.critical_frames,
                    "微睡幀數": summary.microsleep_frames,
                    "無臉幀數": summary.no_face_frames,
                    "校準中幀數": summary.calibrating_frames,
                    "正常幀數": summary.ok_frames,
                    "狀態分布": summary.status_counts_json,
                    "錯誤訊息": summary.error,
                    "影片路徑": summary.video_path,
                    "SQLite資料庫": summary.db_path,
                    "標註影片": summary.annotated_video_path,
                }
            )


def write_full_summary_csv(path: Path, summaries: list[UtaRlddVideoSummary]) -> None:
    """Write every summary field for downstream scripts and audits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(UtaRlddVideoSummary(subject="", label="", label_name="", video_path="")).keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(asdict(summary))


def run_replay_batch(
    root: Path,
    *,
    output_dir: Path | None = None,
    max_videos: int = 0,
    max_frames: int = 0,
    subjects: Iterable[str] | None = None,
    labels: Iterable[str] | None = None,
    write_annotated_video: bool = False,
    progress_cb: ProgressCallback | None = None,
    preview_frame_cb: PreviewFrameCallback | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> UtaRlddBatchResult:
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[1] / "recordings" / "utarldd_runs" / run_stamp
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = discover_utarldd_videos(root, subjects=subjects, labels=labels)
    if max_videos > 0:
        videos = videos[:max_videos]

    summaries: list[UtaRlddVideoSummary] = []
    for index, video in enumerate(videos, start=1):
        if stop_requested is not None and stop_requested():
            break
        if progress_cb:
            progress_cb(
                "video_start",
                index,
                len(videos),
                UtaRlddVideoSummary(
                    subject=video.subject,
                    label=video.label,
                    label_name=video.label_name,
                    video_path=str(video.path),
                ),
            )
        summary = run_replay_video(
            video,
            output_dir,
            run_stamp,
            max_frames=max_frames,
            write_annotated_video=write_annotated_video,
            progress_cb=progress_cb,
            preview_frame_cb=preview_frame_cb,
            stop_requested=stop_requested,
        )
        summaries.append(summary)
        if progress_cb:
            progress_cb("video_done", index, len(videos), summary)

    summary_csv = output_dir / f"utarldd_summary_{run_stamp}.csv"
    full_summary_csv = output_dir / f"utarldd_summary_full_{run_stamp}.csv"
    manifest_path = output_dir / f"utarldd_manifest_{run_stamp}.json"
    write_summary_csv(summary_csv, summaries)
    write_full_summary_csv(full_summary_csv, summaries)
    manifest = {
        "dataset_root": str(Path(root)),
        "output_dir": str(output_dir),
        "summary_csv": str(summary_csv),
        "full_summary_csv": str(full_summary_csv),
        "created_at": run_stamp,
        "source": "UTA-RLDD",
        "source_url": "https://sites.google.com/view/utarldd/home",
        "labels": UTARLDD_LABELS,
        "videos_total": len(videos),
        "videos_done": sum(1 for s in summaries if s.status == "done"),
        "videos_failed": sum(1 for s in summaries if s.status == "failed"),
        "summaries": [asdict(s) for s in summaries],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return UtaRlddBatchResult(
        output_dir=output_dir,
        summary_csv=summary_csv,
        full_summary_csv=full_summary_csv,
        manifest_path=manifest_path,
        videos_total=len(videos),
        videos_done=sum(1 for s in summaries if s.status == "done"),
        videos_failed=sum(1 for s in summaries if s.status == "failed"),
        summaries=summaries,
    )


class UtaRlddReplayWorker(QObject):
    progress = Signal(str, int, int, object)
    preview_frame = Signal(QImage)
    finished_ok = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        dataset_root: Path,
        *,
        output_dir: Path | None = None,
        max_videos: int = 0,
        max_frames: int = 0,
        write_annotated_video: bool = False,
    ) -> None:
        super().__init__()
        self.dataset_root = Path(dataset_root)
        self.output_dir = output_dir
        self.max_videos = int(max_videos)
        self.max_frames = int(max_frames)
        self.write_annotated_video = bool(write_annotated_video)
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def _progress_cb(self, event: str, current: int, total: int, summary: UtaRlddVideoSummary | None) -> None:
        self.progress.emit(event, current, total, summary)

    def _preview_frame_cb(self, image: QImage) -> None:
        self.preview_frame.emit(image)

    @Slot()
    def run(self) -> None:
        try:
            result = run_replay_batch(
                self.dataset_root,
                output_dir=self.output_dir,
                max_videos=self.max_videos,
                max_frames=self.max_frames,
                write_annotated_video=self.write_annotated_video,
                progress_cb=self._progress_cb,
                preview_frame_cb=self._preview_frame_cb,
                stop_requested=self._stop.is_set,
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
