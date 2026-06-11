"""UTA-RLDD video replay analysis.

This module treats dataset videos as deterministic camera input and reuses the
production fatigue/rPPG engines to write normal MetricsRecorder databases.
"""

from __future__ import annotations

import csv
import html
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
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
    post_calibration_frames: int = 0
    behavior_available_frames: int = 0
    rppg_available_frames: int = 0
    low_quality_frames: int = 0
    perclos_low_frames: int = 0
    perclos_drowsy_frames: int = 0
    blink_temporal_warn_frames: int = 0
    squint_frames: int = 0
    gaze_fatigue_frames: int = 0
    yawn_frames: int = 0
    label_alignment: str = ""
    primary_fatigue_evidence: str = ""
    recommended_next_action: str = ""
    optimization_flags_json: str = "[]"
    status_counts_json: str = "{}"


@dataclass
class UtaRlddBatchResult:
    output_dir: Path
    summary_csv: Path
    full_summary_csv: Path
    validation_report_csv: Path
    visual_report_html: Path
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
_BROKEN_POOL_MESSAGE = (
    "平行處理子行程異常中止。常見原因是平行數過高、同時輸出標註影片造成記憶體/編碼器壓力，"
    "或特定影片 codec 讓 OpenCV/MediaPipe 子行程崩潰。請先關閉輸出標註影片，並把平行數降到 2-4 後重跑。"
)


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
    fourcc_fn = getattr(cv2, "VideoWriter_fourcc")
    fourcc = fourcc_fn(*"mp4v")
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
                if int(payload.get("calibrated", 0) or 0):
                    summary.post_calibration_frames += 1
                if int(payload.get("fused_behavior_available", 0) or 0):
                    summary.behavior_available_frames += 1
                if int(payload.get("fused_rppg_available", 0) or 0):
                    summary.rppg_available_frames += 1
                if float(payload.get("fatigue_quality_score", 0.0) or 0.0) < 0.55:
                    summary.low_quality_frames += 1
                if float(payload.get("perclos", 0.0) or 0.0) >= 0.10:
                    summary.perclos_low_frames += 1
                if float(payload.get("perclos", 0.0) or 0.0) >= 0.25:
                    summary.perclos_drowsy_frames += 1
                if float(payload.get("blink_temporal_score", 0.0) or 0.0) >= 0.45:
                    summary.blink_temporal_warn_frames += 1
                if int(payload.get("is_squinting", 0) or 0):
                    summary.squint_frames += 1
                if int(payload.get("gaze_mental_fatigue", 0) or 0):
                    summary.gaze_fatigue_frames += 1
                if int(payload.get("yawn_detected", 0) or 0):
                    summary.yawn_frames += 1
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
    _update_summary_diagnostics(summary)
    return summary


def _run_replay_video_process_job(args: tuple[UtaRlddVideo, str, str, int, bool]) -> UtaRlddVideoSummary:
    video, output_dir, run_stamp, max_frames, write_annotated_video = args
    return run_replay_video(
        video,
        Path(output_dir),
        run_stamp,
        max_frames=max_frames,
        write_annotated_video=write_annotated_video,
    )


def _failed_replay_summary(video: UtaRlddVideo, error: str) -> UtaRlddVideoSummary:
    return UtaRlddVideoSummary(
        subject=video.subject,
        label=video.label,
        label_name=video.label_name,
        video_path=str(video.path),
        status="failed",
        error=error,
    )


def _broken_pool_error(exc: BaseException) -> str:
    detail = str(exc).strip()
    if detail:
        return f"{_BROKEN_POOL_MESSAGE} 原始錯誤：{detail}"
    return _BROKEN_POOL_MESSAGE


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 2)


def _num(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _rate(count: int, total: int) -> float:
    return _ratio(count, total)


def _evidence_items(summary: UtaRlddVideoSummary) -> list[tuple[str, float]]:
    frames = max(summary.frames, 1)
    return [
        ("PERCLOS>=0.10", _rate(summary.perclos_low_frames, frames)),
        ("PERCLOS>=0.25", _rate(summary.perclos_drowsy_frames, frames)),
        ("眨眼時序異常", _rate(summary.blink_temporal_warn_frames, frames)),
        ("瞇眼", _rate(summary.squint_frames, frames)),
        ("凝視/低掃視", _rate(summary.gaze_fatigue_frames, frames)),
        ("哈欠", _rate(summary.yawn_frames, frames)),
        (
            "嗜睡/危急狀態",
            _rate(summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames, frames),
        ),
    ]


def _primary_evidence(summary: UtaRlddVideoSummary) -> str:
    items = sorted(_evidence_items(summary), key=lambda item: item[1], reverse=True)
    strong = [f"{name} {_pct(value)}%" for name, value in items if value >= 0.01]
    if not strong:
        return (
            f"未見明顯觸發；max PERCLOS={_pct(summary.max_perclos)}%，"
            f"p95 fused={_num(summary.p95_fused_score)}"
        )
    return (
        "；".join(strong[:3])
        + f"；max PERCLOS={_pct(summary.max_perclos)}%，p95 fused={_num(summary.p95_fused_score)}"
    )


def _summary_flags(summary: UtaRlddVideoSummary) -> list[str]:
    frames = max(summary.frames, 1)
    flags: list[str] = []
    low_ratio = _rate(summary.low_vigilance_frames, frames)
    drowsy_ratio = _rate(
        summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames,
        frames,
    )
    low_quality_ratio = _rate(summary.low_quality_frames, frames)
    behavior_rate = _rate(summary.behavior_available_frames, frames)

    if summary.face_rate < 0.90:
        flags.append("face_detection_unstable")
    if behavior_rate < 0.70:
        flags.append("behavior_effective_frames_low")
    if low_quality_ratio > 0.25:
        flags.append("fatigue_quality_low")
    if summary.label == "0" and (low_ratio > 0.20 or drowsy_ratio > 0.01 or summary.max_perclos >= 0.10):
        flags.append("alert_false_alarm_risk")
    if summary.label == "10" and drowsy_ratio < 0.03 and summary.max_perclos < 0.10 and summary.p95_fused_score < 0.20:
        flags.append("drowsy_miss_risk")
    if summary.label == "5" and low_ratio < 0.05 and summary.max_perclos < 0.08:
        flags.append("low_vigilance_insensitive")
    if summary.label == "5" and drowsy_ratio > 0.05:
        flags.append("low_vigilance_too_severe")
    if summary.rppg_available_frames == 0 and summary.frames > 0:
        flags.append("rppg_unavailable")
    return flags


def _label_alignment(summary: UtaRlddVideoSummary, flags: list[str]) -> str:
    if summary.status == "failed":
        return "處理失敗，無法判斷"
    if summary.status == "stopped":
        return "使用者中止，無法判斷"
    if summary.frames <= 0:
        return "沒有有效幀"
    if "face_detection_unstable" in flags:
        return "偵測品質不足，先修正相機/人臉品質"
    if "alert_false_alarm_risk" in flags:
        return "Alert 誤報風險"
    if "drowsy_miss_risk" in flags:
        return "Drowsy 漏報風險"
    if "low_vigilance_insensitive" in flags:
        return "Low Vigilant 偏不敏感"
    if "low_vigilance_too_severe" in flags:
        return "Low Vigilant 偏嚴重"
    if summary.label == "10" and (
        summary.max_perclos >= 0.10
        or _rate(summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames, summary.frames) >= 0.03
    ):
        return "部分符合 Drowsy 標籤"
    if summary.label == "0":
        return "大致符合 Alert 標籤"
    return "趨勢需與同受試者 0/5/10 比較"


def _recommended_action(summary: UtaRlddVideoSummary, flags: list[str]) -> str:
    if summary.status != "done":
        return "先修正影片處理錯誤或重新執行 replay"
    actions: list[str] = []
    if "face_detection_unstable" in flags:
        actions.append("優先改善相機、光線、臉部框選與 MediaPipe tracking")
    if "behavior_effective_frames_low" in flags:
        actions.append("新增 post-calibration/behavior-available 分母並避免校準期稀釋平均")
    if "fatigue_quality_low" in flags:
        actions.append("檢查 roll/yaw/鼻尖速度/嘴部開合造成的品質 gate")
    if "alert_false_alarm_risk" in flags:
        actions.append("調高 LOW_VIGILANCE 條件或加入原因碼確認 PERCLOS/眨眼/凝視誤報")
    if "drowsy_miss_risk" in flags:
        actions.append("檢查 Drowsy 影片是否缺少長閉眼；需要調整 blink temporal、凝視與 PERCLOS 權重")
    if "low_vigilance_insensitive" in flags:
        actions.append("檢查低警覺早期特徵是否過度依賴閉眼")
    if "low_vigilance_too_severe" in flags:
        actions.append("檢查 DROWSY/CRITICAL 門檻是否對 Low Vigilant 過敏感")
    if "rppg_unavailable" in flags:
        actions.append("檢查 ROI、SQI、rPPG quality 與影片光照")
    if not actions:
        actions.append("保留目前門檻，加入更多同場域標註資料做交叉驗證")
    return "；".join(actions[:3])


def _update_summary_diagnostics(summary: UtaRlddVideoSummary) -> None:
    flags = _summary_flags(summary)
    summary.optimization_flags_json = json.dumps(flags, ensure_ascii=False)
    summary.label_alignment = _label_alignment(summary, flags)
    summary.primary_fatigue_evidence = _primary_evidence(summary)
    summary.recommended_next_action = _recommended_action(summary, flags)


def _quick_reading(summary: UtaRlddVideoSummary) -> str:
    if not summary.primary_fatigue_evidence:
        _update_summary_diagnostics(summary)
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
        "校準後幀數",
        "行為有效幀數",
        "行為有效率(%)",
        "rPPG可用幀數",
        "rPPG可用率(%)",
        "低品質幀數",
        "低品質比例(%)",
        "PERCLOS低警覺觸發幀數",
        "PERCLOS嗜睡觸發幀數",
        "眨眼時序警示幀數",
        "瞇眼幀數",
        "凝視疲勞幀數",
        "哈欠幀數",
        "標籤對齊判讀",
        "主要判斷依據",
        "建議修正方向",
        "優化旗標",
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
            _update_summary_diagnostics(summary)
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
                    "校準後幀數": summary.post_calibration_frames,
                    "行為有效幀數": summary.behavior_available_frames,
                    "行為有效率(%)": _pct(_rate(summary.behavior_available_frames, summary.frames)),
                    "rPPG可用幀數": summary.rppg_available_frames,
                    "rPPG可用率(%)": _pct(_rate(summary.rppg_available_frames, summary.frames)),
                    "低品質幀數": summary.low_quality_frames,
                    "低品質比例(%)": _pct(_rate(summary.low_quality_frames, summary.frames)),
                    "PERCLOS低警覺觸發幀數": summary.perclos_low_frames,
                    "PERCLOS嗜睡觸發幀數": summary.perclos_drowsy_frames,
                    "眨眼時序警示幀數": summary.blink_temporal_warn_frames,
                    "瞇眼幀數": summary.squint_frames,
                    "凝視疲勞幀數": summary.gaze_fatigue_frames,
                    "哈欠幀數": summary.yawn_frames,
                    "標籤對齊判讀": summary.label_alignment,
                    "主要判斷依據": summary.primary_fatigue_evidence,
                    "建議修正方向": summary.recommended_next_action,
                    "優化旗標": summary.optimization_flags_json,
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
            _update_summary_diagnostics(summary)
            writer.writerow(asdict(summary))


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / max(float(denominator), 1.0)


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _validation_score(summary: UtaRlddVideoSummary) -> float:
    drowsy_ratio = _ratio(
        summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames,
        summary.frames,
    )
    low_ratio = _ratio(summary.low_vigilance_frames, summary.frames)
    return float(
        0.35 * summary.p95_fused_score
        + 0.25 * summary.p95_fatigue_score
        + 0.25 * drowsy_ratio
        + 0.10 * low_ratio
        + 0.05 * summary.max_perclos
    )


def _trend_label(v0: float, v5: float, v10: float, *, epsilon: float) -> str:
    if v0 + epsilon <= v5 and v5 + epsilon <= v10:
        return "完整上升"
    if v0 + epsilon <= v10:
        return "Drowsy高於Alert"
    if v10 + epsilon < v0:
        return "反向"
    return "趨勢不明"


def _validation_conclusion(rows_done: int, rows_failed: int, monotonic_rate: float, drowsy_gt_alert_rate: float) -> str:
    if rows_done == 0:
        return "無有效完成影片，不能驗證"
    if rows_failed > 0:
        base = "部分影片失敗，僅能作初步趨勢"
    else:
        base = "資料完整"
    if drowsy_gt_alert_rate >= 0.75 and monotonic_rate >= 0.50:
        return f"{base}；趨勢支持系統"
    if drowsy_gt_alert_rate >= 0.50:
        return f"{base}；部分支持但需校正門檻"
    return f"{base}；目前不支持分類有效"


def write_validation_report_csv(path: Path, summaries: list[UtaRlddVideoSummary]) -> None:
    """Write validation-oriented label/subject trend checks for UTA-RLDD."""
    path.parent.mkdir(parents=True, exist_ok=True)
    done = [s for s in summaries if s.status == "done"]
    failed = [s for s in summaries if s.status == "failed"]
    fieldnames = [
        "列類型",
        "受試者",
        "資料集標籤",
        "警覺類別",
        "完成影片數",
        "失敗影片數",
        "人臉偵測率平均(%)",
        "平均疲勞分數",
        "95分位疲勞分數",
        "平均融合分數",
        "95分位融合分數",
        "平均PERCLOS(%)",
        "最高PERCLOS平均(%)",
        "低警覺比例(%)",
        "嗜睡危急比例(%)",
        "驗證綜合分數",
        "趨勢判定",
        "結論",
        "備註",
    ]
    by_subject: dict[str, dict[str, UtaRlddVideoSummary]] = {}
    for summary in done:
        by_subject.setdefault(summary.subject, {})[summary.label] = summary

    subject_trends: list[str] = []
    for label_map in by_subject.values():
        if {"0", "5", "10"}.issubset(label_map):
            s0 = _validation_score(label_map["0"])
            s5 = _validation_score(label_map["5"])
            s10 = _validation_score(label_map["10"])
            subject_trends.append(_trend_label(s0, s5, s10, epsilon=0.005))
    monotonic_rate = _ratio(subject_trends.count("完整上升"), len(subject_trends))
    drowsy_gt_alert_rate = _ratio(
        sum(1 for trend in subject_trends if trend in {"完整上升", "Drowsy高於Alert"}),
        len(subject_trends),
    )
    conclusion = _validation_conclusion(len(done), len(failed), monotonic_rate, drowsy_gt_alert_rate)

    def aggregate_row(label: str) -> dict[str, object]:
        group = [s for s in done if s.label == label]
        frames = sum(s.frames for s in group)
        low = sum(s.low_vigilance_frames for s in group)
        drowsy = sum(s.drowsy_frames + s.critical_frames + s.microsleep_frames for s in group)
        return {
            "列類型": "label_summary",
            "受試者": "ALL",
            "資料集標籤": label,
            "警覺類別": UTARLDD_LABELS.get(label, ""),
            "完成影片數": len(group),
            "失敗影片數": sum(1 for s in failed if s.label == label),
            "人臉偵測率平均(%)": _pct(_mean([s.face_rate for s in group])),
            "平均疲勞分數": _num(_mean([s.avg_fatigue_score for s in group])),
            "95分位疲勞分數": _num(_mean([s.p95_fatigue_score for s in group])),
            "平均融合分數": _num(_mean([s.avg_fused_score for s in group])),
            "95分位融合分數": _num(_mean([s.p95_fused_score for s in group])),
            "平均PERCLOS(%)": _pct(_mean([s.avg_perclos for s in group])),
            "最高PERCLOS平均(%)": _pct(_mean([s.max_perclos for s in group])),
            "低警覺比例(%)": _pct(_ratio(low, frames)),
            "嗜睡危急比例(%)": _pct(_ratio(drowsy, frames)),
            "驗證綜合分數": _num(_mean([_validation_score(s) for s in group])),
            "趨勢判定": "",
            "結論": conclusion,
            "備註": "依完成影片統計；failed 影片不納入均值",
        }

    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "列類型": "run_summary",
                "受試者": "ALL",
                "完成影片數": len(done),
                "失敗影片數": len(failed),
                "趨勢判定": f"完整上升 {subject_trends.count('完整上升')}/{len(subject_trends)}；Drowsy高於Alert {sum(1 for t in subject_trends if t in {'完整上升', 'Drowsy高於Alert'})}/{len(subject_trends)}",
                "結論": conclusion,
                "備註": "UTA-RLDD label 為整段影片類別；此報表檢查趨勢支持度，不代表逐幀 ground truth",
            }
        )
        for label in ("0", "5", "10"):
            writer.writerow(aggregate_row(label))
        for subject in sorted(by_subject):
            label_map = by_subject[subject]
            if not {"0", "5", "10"}.issubset(label_map):
                writer.writerow(
                    {
                        "列類型": "subject_trend",
                        "受試者": subject,
                        "完成影片數": len(label_map),
                        "失敗影片數": sum(1 for s in failed if s.subject == subject),
                        "趨勢判定": "影片不完整",
                        "結論": "不納入趨勢",
                        "備註": "需同一受試者同時有 0/5/10 三段完成影片",
                    }
                )
                continue
            score0 = _validation_score(label_map["0"])
            score5 = _validation_score(label_map["5"])
            score10 = _validation_score(label_map["10"])
            trend = _trend_label(score0, score5, score10, epsilon=0.005)
            writer.writerow(
                {
                    "列類型": "subject_trend",
                    "受試者": subject,
                    "完成影片數": 3,
                    "失敗影片數": sum(1 for s in failed if s.subject == subject),
                    "驗證綜合分數": f"0={_num(score0)};5={_num(score5)};10={_num(score10)}",
                    "趨勢判定": trend,
                    "結論": "支持" if trend in {"完整上升", "Drowsy高於Alert"} else "不支持",
                    "備註": (
                        f"p95_fused 0={_num(label_map['0'].p95_fused_score)} "
                        f"5={_num(label_map['5'].p95_fused_score)} "
                        f"10={_num(label_map['10'].p95_fused_score)}"
                    ),
                }
            )


def _fmt_percent(value: float) -> str:
    return f"{_pct(value)}%"


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _bar(label: str, value: float, *, max_value: float = 1.0, color: str = "#2563eb") -> str:
    width = max(0.0, min(100.0, (float(value) / max(max_value, 1e-9)) * 100.0))
    return (
        '<div class="bar-row">'
        f'<span class="bar-label">{_escape(label)}</span>'
        '<div class="bar-track">'
        f'<div class="bar-fill" style="width:{width:.2f}%;background:{_escape(color)}"></div>'
        '</div>'
        f'<span class="bar-value">{_escape(_fmt_percent(value))}</span>'
        '</div>'
    )


def _mean_float(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _flag_count(rows: list[dict[str, object]], flag: str) -> int:
    count = 0
    for row in rows:
        raw = str(row.get("優化旗標", "") or row.get("optimization_flags_json", ""))
        if flag in raw:
            count += 1
    return count


def _summary_visual_rows(summaries: list[UtaRlddVideoSummary]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        _update_summary_diagnostics(summary)
        drowsy_ratio = _rate(
            summary.drowsy_frames + summary.critical_frames + summary.microsleep_frames,
            summary.frames,
        )
        rows.append(
            {
                "受試者": summary.subject,
                "資料集標籤": summary.label,
                "警覺類別": summary.label_name,
                "快速判讀": _quick_reading(summary),
                "處理狀態": summary.status,
                "人臉偵測率": summary.face_rate,
                "平均PERCLOS": summary.avg_perclos,
                "最高PERCLOS": summary.max_perclos,
                "95分位融合分數": summary.p95_fused_score,
                "低警覺比例": _rate(summary.low_vigilance_frames, summary.frames),
                "嗜睡危急比例": drowsy_ratio,
                "行為有效率": _rate(summary.behavior_available_frames, summary.frames),
                "低品質比例": _rate(summary.low_quality_frames, summary.frames),
                "標籤對齊判讀": summary.label_alignment,
                "主要判斷依據": summary.primary_fatigue_evidence,
                "建議修正方向": summary.recommended_next_action,
                "優化旗標": summary.optimization_flags_json,
            }
        )
    return rows


def _read_summary_visual_rows(summary_csv: Path) -> list[dict[str, object]]:
    with Path(summary_csv).open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, object]] = []
        for raw in reader:
            frames = int(float(raw.get("總幀數", 0) or 0))
            drowsy_count = sum(
                int(float(raw.get(name, 0) or 0))
                for name in ("嗜睡幀數", "危急幀數", "微睡幀數")
            )
            rows.append(
                {
                    "受試者": raw.get("受試者", ""),
                    "資料集標籤": raw.get("資料集標籤", ""),
                    "警覺類別": raw.get("警覺類別", ""),
                    "快速判讀": raw.get("快速判讀", ""),
                    "處理狀態": raw.get("處理狀態", ""),
                    "人臉偵測率": float(raw.get("人臉偵測率(%)", 0) or 0) / 100.0,
                    "平均PERCLOS": float(raw.get("平均PERCLOS(%)", 0) or 0) / 100.0,
                    "最高PERCLOS": float(raw.get("最高PERCLOS(%)", 0) or 0) / 100.0,
                    "95分位融合分數": float(raw.get("95分位融合分數(0-1)", 0) or 0),
                    "低警覺比例": _rate(int(float(raw.get("低警覺幀數", 0) or 0)), frames),
                    "嗜睡危急比例": _rate(drowsy_count, frames),
                    "行為有效率": float(raw.get("行為有效率(%)", 0) or 0) / 100.0,
                    "低品質比例": float(raw.get("低品質比例(%)", 0) or 0) / 100.0,
                    "標籤對齊判讀": raw.get("標籤對齊判讀", ""),
                    "主要判斷依據": raw.get("主要判斷依據", ""),
                    "建議修正方向": raw.get("建議修正方向", ""),
                    "優化旗標": raw.get("優化旗標", ""),
                }
            )
        return rows


def _label_aggregates(rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for label in ("0", "5", "10"):
        group = [row for row in rows if str(row.get("資料集標籤", "")) == label]
        out[label] = {
            "count": float(len(group)),
            "face": _mean_float([float(row.get("人臉偵測率", 0.0) or 0.0) for row in group]),
            "perclos": _mean_float([float(row.get("平均PERCLOS", 0.0) or 0.0) for row in group]),
            "max_perclos": _mean_float([float(row.get("最高PERCLOS", 0.0) or 0.0) for row in group]),
            "p95_fused": _mean_float([float(row.get("95分位融合分數", 0.0) or 0.0) for row in group]),
            "low": _mean_float([float(row.get("低警覺比例", 0.0) or 0.0) for row in group]),
            "drowsy": _mean_float([float(row.get("嗜睡危急比例", 0.0) or 0.0) for row in group]),
            "behavior": _mean_float([float(row.get("行為有效率", 0.0) or 0.0) for row in group]),
            "low_quality": _mean_float([float(row.get("低品質比例", 0.0) or 0.0) for row in group]),
        }
    return out


def _render_visual_report(rows: list[dict[str, object]], *, title: str) -> str:
    aggregates = _label_aggregates(rows)
    total = len(rows)
    done = sum(1 for row in rows if str(row.get("處理狀態", "")) == "done")
    face_avg = _mean_float([float(row.get("人臉偵測率", 0.0) or 0.0) for row in rows])
    alert_false = _flag_count(rows, "alert_false_alarm_risk")
    drowsy_miss = _flag_count(rows, "drowsy_miss_risk")
    low_effective = _flag_count(rows, "behavior_effective_frames_low")
    cards = [
        ("影片總數", str(total)),
        ("完成影片", str(done)),
        ("平均人臉偵測率", _fmt_percent(face_avg)),
        ("Alert 誤報風險", str(alert_false)),
        ("Drowsy 漏報風險", str(drowsy_miss)),
        ("有效幀不足", str(low_effective)),
    ]
    card_html = "".join(
        f'<section class="card"><div class="card-label">{_escape(label)}</div><div class="card-value">{_escape(value)}</div></section>'
        for label, value in cards
    )

    chart_sections = []
    chart_specs = [
        ("平均 PERCLOS", "perclos", "#0f766e", 0.25),
        ("最高 PERCLOS 平均", "max_perclos", "#0891b2", 0.35),
        ("95 分位融合分數", "p95_fused", "#7c3aed", 1.0),
        ("低警覺比例", "low", "#f59e0b", 1.0),
        ("嗜睡/危急比例", "drowsy", "#dc2626", 1.0),
        ("行為有效率", "behavior", "#16a34a", 1.0),
        ("低品質比例", "low_quality", "#64748b", 1.0),
    ]
    for chart_title, key, color, max_value in chart_specs:
        bars = "".join(
            _bar(f"{label} {UTARLDD_LABELS.get(label, '')}", aggregates[label][key], max_value=max_value, color=color)
            for label in ("0", "5", "10")
        )
        chart_sections.append(f'<section class="panel"><h2>{_escape(chart_title)}</h2>{bars}</section>')

    table_rows = []
    sorted_rows = sorted(rows, key=lambda row: (str(row.get("受試者", "")), str(row.get("資料集標籤", ""))))
    for row in sorted_rows:
        flags = str(row.get("優化旗標", "") or "")
        table_rows.append(
            "<tr>"
            f"<td>{_escape(row.get('受試者', ''))}</td>"
            f"<td>{_escape(row.get('資料集標籤', ''))}</td>"
            f"<td>{_escape(row.get('警覺類別', ''))}</td>"
            f"<td>{_escape(row.get('快速判讀', ''))}</td>"
            f"<td>{_escape(row.get('標籤對齊判讀', ''))}</td>"
            f"<td>{_escape(row.get('主要判斷依據', ''))}</td>"
            f"<td>{_escape(row.get('建議修正方向', ''))}</td>"
            f"<td><code>{_escape(flags)}</code></td>"
            "</tr>"
        )

    table_html = (
        '<section class="panel wide"><h2>逐影片判讀與修正建議</h2>'
        '<table><thead><tr>'
        '<th>受試者</th><th>Label</th><th>類別</th><th>快速判讀</th>'
        '<th>標籤對齊</th><th>主要判斷依據</th><th>建議修正方向</th><th>優化旗標</th>'
        '</tr></thead><tbody>'
        + "".join(table_rows)
        + "</tbody></table></section>"
    )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
body {{ margin: 0; font-family: "Noto Sans CJK TC", "Microsoft JhengHei", Arial, sans-serif; background: #f8fafc; color: #0f172a; }}
header {{ padding: 28px 32px 16px; background: #0f172a; color: white; }}
h1 {{ margin: 0; font-size: 26px; }}
.subtitle {{ margin-top: 8px; color: #cbd5e1; }}
main {{ padding: 24px 32px 40px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 18px; }}
.card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px; }}
.card-label {{ color: #64748b; font-size: 13px; }}
.card-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }}
.panel {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }}
.panel.wide {{ margin-top: 16px; overflow-x: auto; }}
h2 {{ margin: 0 0 12px; font-size: 17px; }}
.bar-row {{ display: grid; grid-template-columns: 110px 1fr 58px; align-items: center; gap: 10px; margin: 10px 0; }}
.bar-label {{ font-size: 13px; color: #334155; }}
.bar-track {{ height: 12px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 999px; }}
.bar-value {{ text-align: right; font-variant-numeric: tabular-nums; color: #475569; font-size: 13px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; padding: 9px 8px; vertical-align: top; text-align: left; }}
th {{ background: #f1f5f9; color: #334155; position: sticky; top: 0; }}
code {{ white-space: pre-wrap; color: #334155; }}
</style>
</head>
<body>
<header>
<h1>{_escape(title)}</h1>
<div class="subtitle">由 UTA-RLDD replay summary CSV 產生；用途是判斷目前門檻支持度、誤報/漏報風險與下一步優化方向。</div>
</header>
<main>
<section class="cards">{card_html}</section>
<section class="grid">{"".join(chart_sections)}</section>
{table_html}
</main>
</body>
</html>
"""


def write_visual_report_html(path: Path, summaries: list[UtaRlddVideoSummary]) -> None:
    """Write a standalone HTML report from in-memory replay summaries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _summary_visual_rows(summaries)
    path.write_text(
        _render_visual_report(rows, title="UTA-RLDD 疲勞驗證可視化報表"),
        encoding="utf-8",
    )


def write_visual_report_html_from_csv(summary_csv: Path, target: Path) -> None:
    """Write a standalone HTML report from an existing human-readable summary CSV."""
    rows = _read_summary_visual_rows(Path(summary_csv))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _render_visual_report(rows, title=f"UTA-RLDD 疲勞驗證可視化報表 - {Path(summary_csv).name}"),
        encoding="utf-8",
    )


def run_replay_batch(
    root: Path,
    *,
    output_dir: Path | None = None,
    max_videos: int = 0,
    max_frames: int = 0,
    subjects: Iterable[str] | None = None,
    labels: Iterable[str] | None = None,
    write_annotated_video: bool = False,
    jobs: int = 1,
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
    effective_jobs = max(1, int(jobs or 1))
    if preview_frame_cb is not None:
        effective_jobs = 1
    write_annotated_video_effective = bool(write_annotated_video)
    if effective_jobs > 1:
        write_annotated_video_effective = False

    if effective_jobs <= 1 or len(videos) <= 1:
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
                write_annotated_video=write_annotated_video_effective,
                progress_cb=progress_cb,
                preview_frame_cb=preview_frame_cb,
                stop_requested=stop_requested,
            )
            summaries.append(summary)
            if progress_cb:
                progress_cb("video_done", index, len(videos), summary)
    else:
        indexed: list[tuple[int, UtaRlddVideo]] = list(enumerate(videos, start=1))
        summary_by_index: dict[int, UtaRlddVideoSummary] = {}
        max_workers = min(effective_jobs, len(indexed))
        pool_error: str | None = None
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            pending_items = indexed.copy()
            future_to_index = {}
            running = set()
            done_count = 0

            def mark_failed(index: int, video: UtaRlddVideo, error: str) -> None:
                nonlocal done_count
                if index in summary_by_index:
                    return
                summary = _failed_replay_summary(video, error)
                summary_by_index[index] = summary
                done_count += 1
                if progress_cb:
                    progress_cb("video_done", done_count, len(videos), summary)

            def submit_next() -> bool:
                nonlocal pool_error
                if not pending_items:
                    return False
                if stop_requested is not None and stop_requested():
                    return False
                index, video = pending_items.pop(0)
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
                try:
                    future = executor.submit(
                        _run_replay_video_process_job,
                        (video, str(output_dir), run_stamp, max_frames, write_annotated_video_effective),
                    )
                except BrokenProcessPool as exc:
                    pool_error = _broken_pool_error(exc)
                    mark_failed(index, video, pool_error)
                    return False
                future_to_index[future] = (index, video)
                running.add(future)
                return True

            for _ in range(max_workers):
                submit_next()

            while running:
                if pool_error is not None:
                    for future in list(running):
                        future.cancel()
                    break
                if stop_requested is not None and stop_requested():
                    pending_items.clear()
                    for future in list(running):
                        future.cancel()
                done, running = wait(running, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in done:
                    index, video = future_to_index[future]
                    done_count += 1
                    try:
                        summary = future.result()
                    except BrokenProcessPool as exc:
                        pool_error = _broken_pool_error(exc)
                        summary = _failed_replay_summary(video, pool_error)
                    except Exception as exc:
                        summary = _failed_replay_summary(video, str(exc))
                    summary_by_index[index] = summary
                    if progress_cb:
                        progress_cb("video_done", done_count, len(videos), summary)
                    if pool_error is not None:
                        for future_left in list(running):
                            future_left.cancel()
                        break
                if pool_error is not None:
                    break
                while len(running) < max_workers and submit_next():
                    pass
        if pool_error is not None:
            for index, video in indexed:
                if index not in summary_by_index:
                    summary_by_index[index] = _failed_replay_summary(video, pool_error)
        summaries = [summary_by_index[index] for index, _video in indexed if index in summary_by_index]

    summary_csv = output_dir / f"utarldd_summary_{run_stamp}.csv"
    full_summary_csv = output_dir / f"utarldd_summary_full_{run_stamp}.csv"
    validation_report_csv = output_dir / f"utarldd_validation_report_{run_stamp}.csv"
    visual_report_html = output_dir / f"utarldd_visual_report_{run_stamp}.html"
    manifest_path = output_dir / f"utarldd_manifest_{run_stamp}.json"
    write_summary_csv(summary_csv, summaries)
    write_full_summary_csv(full_summary_csv, summaries)
    write_validation_report_csv(validation_report_csv, summaries)
    write_visual_report_html(visual_report_html, summaries)
    manifest = {
        "dataset_root": str(Path(root)),
        "output_dir": str(output_dir),
        "summary_csv": str(summary_csv),
        "full_summary_csv": str(full_summary_csv),
        "validation_report_csv": str(validation_report_csv),
        "visual_report_html": str(visual_report_html),
        "created_at": run_stamp,
        "source": "UTA-RLDD",
        "source_url": "https://sites.google.com/view/utarldd/home",
        "labels": UTARLDD_LABELS,
        "jobs_requested": int(jobs or 1),
        "jobs_effective": effective_jobs,
        "write_annotated_video_requested": bool(write_annotated_video),
        "write_annotated_video_effective": write_annotated_video_effective,
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
        validation_report_csv=validation_report_csv,
        visual_report_html=visual_report_html,
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
        jobs: int = 1,
        preview_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.dataset_root = Path(dataset_root)
        self.output_dir = output_dir
        self.max_videos = int(max_videos)
        self.max_frames = int(max_frames)
        self.write_annotated_video = bool(write_annotated_video)
        self.jobs = max(1, int(jobs))
        self.preview_enabled = bool(preview_enabled)
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
                jobs=self.jobs,
                progress_cb=self._progress_cb,
                preview_frame_cb=self._preview_frame_cb if self.preview_enabled else None,
                stop_requested=self._stop.is_set,
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
