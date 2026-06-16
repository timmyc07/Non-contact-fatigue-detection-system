"""Combined Face Worker — single MediaPipe instance drives both rPPG and Fatigue.

Running two separate FaceLandmarker instances (one per worker) causes both to
compete for the same BGR frames and only one set of annotations to appear on the
overlay.  This module solves that by sharing the landmark result between both
engines and compositing all annotations onto a single output frame.

Signal pipeline:
    CameraStreamWorker → BGR queue → CombinedWorker (own QThread)
    → MediaPipe FaceLandmarker (one call per frame)
    ├── FatigueEngine.step()  → FatigueMetrics  → fatigue_metrics_ready
    └── RppgEngine  (ROI extraction + POS + HRV) → RppgMetrics    → rppg_metrics_ready
    → draw_fatigue_annotations() + draw_rois()
    → frame_annotated  (combined QImage → Overlay)

Enable/disable each sub-pipeline at construction time:
    CombinedWorker(q, enable_rppg=True, enable_fatigue=True)
"""

from __future__ import annotations

import queue
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

_HAS_MP = True
_HAS_SCIPY = True
_ANNOTATED_PREVIEW_MAX_FPS = 30.0

from .fatigue_engine import FatigueEngine, FatigueMetrics, FatigueParams
from .frame_queue import get_latest
from .mediapipe_tuning import load_mediapipe_tuning
from .fatigue_scorer import FatigueFuser, FusedFatigueScore, FuserConfig
from .fatigue_worker import draw_fatigue_annotations
from rppg.rppg_worker import (
    RppgEngine, RppgMetrics,
    draw_rois,
    RoiGeometryTracker, collect_rppg_roi_sample,
    ensure_face_model, _MODELS_DIR,
)


class CombinedWorker(QObject):
    """Single-MediaPipe worker that feeds both rPPG and Fatigue engines.

    Use this instead of running RppgWorker + FatigueWorker concurrently —
    it avoids duplicate MediaPipe inference and ensures all annotations appear
    on the same preview frame without flickering.

    Parameters
    ----------
    frame_queue : queue.Queue
        (timestamp, bgr_frame) tuples from CameraStreamWorker.
    enable_rppg : bool
        Whether to run the rPPG / HRV pipeline.
    enable_fatigue : bool
        Whether to run the behaviour-alertness pipeline.
    target_fps : float
        Expected camera frame rate (used by RppgEngine warmup & FatigueEngine calibration).
    buffer_sec : float
        rPPG temporal buffer length in seconds.
    fatigue_params : FatigueParams | None
        Custom fatigue parameters; defaults are used when None.
    """

    rppg_metrics_ready:    Signal = Signal(object)   # RppgMetrics
    fatigue_metrics_ready: Signal = Signal(object)   # FatigueMetrics
    fused_score_ready:     Signal = Signal(object)   # FusedFatigueScore
    frame_annotated:       Signal = Signal(QImage)   # combined annotated preview
    face_detected:         Signal = Signal(bool)
    status_changed:        Signal = Signal(str)
    failed:                Signal = Signal(str)
    finished:              Signal = Signal()

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        enable_rppg:    bool = True,
        enable_fatigue: bool = True,
        target_fps:  float = 30.0,
        buffer_sec:  float = 12.0,
        fatigue_params: Optional[FatigueParams] = None,
    ) -> None:
        super().__init__()
        self._queue          = frame_queue
        self._enable_rppg    = enable_rppg
        self._enable_fatigue = enable_fatigue
        self._target_fps     = target_fps
        self._buffer_sec     = buffer_sec
        self._fatigue_params = fatigue_params or FatigueParams()
        self._fuser          = FatigueFuser()
        self._stop           = False
        self._tuning         = load_mediapipe_tuning()

    def request_stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        # ── Dependency checks ─────────────────────────────────────────────────
        if not _HAS_MP:
            self.failed.emit("MediaPipe 未安裝。\n請執行：pip install mediapipe")
            self.finished.emit()
            return
        if cv2 is None:
            self.failed.emit("OpenCV 未安裝。")
            self.finished.emit()
            return
        if self._enable_rppg and not _HAS_SCIPY:
            self.failed.emit("SciPy 未安裝（rPPG 需要）。\n請執行：pip install scipy")
            self.finished.emit()
            return

        # ── Model download ────────────────────────────────────────────────────
        try:
            model_path = ensure_face_model(
                _MODELS_DIR,
                status_cb=lambda s: self.status_changed.emit(s),
            )
        except Exception as exc:
            self.failed.emit(f"MediaPipe 模型下載失敗：{exc}")
            self.finished.emit()
            return

        # ── Build FaceLandmarker ──────────────────────────────────────────────
        base_opts  = _mp_python.BaseOptions(model_asset_path=str(model_path))
        lm_options = _mp_vision.FaceLandmarkerOptions(
            base_options=base_opts,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=self._tuning.face_landmarker.min_face_detection_confidence,
            min_face_presence_confidence=self._tuning.face_landmarker.min_face_presence_confidence,
            min_tracking_confidence=self._tuning.face_landmarker.min_tracking_confidence,
            num_faces=max(1, int(self._tuning.face_landmarker.num_faces)),
            running_mode=_mp_vision.RunningMode.VIDEO,
        )

        # ── Engines ───────────────────────────────────────────────────────────
        rppg_engine    = RppgEngine(buffer_sec=self._buffer_sec,
                                    target_fps=self._target_fps) if self._enable_rppg else None
        roi_tracker    = RoiGeometryTracker() if self._enable_rppg else None
        fatigue_engine = FatigueEngine(params=self._fatigue_params) if self._enable_fatigue else None

        last_face      = False
        t_origin: Optional[float] = None
        ts_ms_prev     = 0
        last_preview_emit = 0.0
        preview_emit_interval = 1.0 / _ANNOTATED_PREVIEW_MAX_FPS

        parts = []
        if self._enable_rppg:    parts.append("rPPG")
        if self._enable_fatigue: parts.append("行為警覺")
        self.status_changed.emit(f"合併引擎就緒（{' + '.join(parts)}），等待幀資料…")

        with _mp_vision.FaceLandmarker.create_from_options(lm_options) as landmarker:
            while not self._stop:
                try:
                    ts, bgr = get_latest(self._queue, timeout=0.1)
                except queue.Empty:
                    continue

                if t_origin is None:
                    t_origin = ts

                ts_ms      = max(ts_ms_prev + 1, int((ts - t_origin) * 1000))
                ts_ms_prev = ts_ms

                rgb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(rgb),
                )

                try:
                    result = landmarker.detect_for_video(mp_img, ts_ms)
                except Exception:
                    continue

                blendshapes = result.face_blendshapes[0] if result.face_blendshapes else None

                has_face = bool(result.face_landmarks)
                if has_face != last_face:
                    self.face_detected.emit(has_face)
                    last_face = has_face

                annotated = bgr.copy()

                r_metrics: Optional[RppgMetrics]    = None
                f_metrics: Optional[FatigueMetrics] = None

                if has_face:
                    lm       = result.face_landmarks[0]
                    h_px, w_px = bgr.shape[:2]
                    transform_matrix = (
                        result.facial_transformation_matrixes[0]
                        if result.facial_transformation_matrixes else None
                    )

                    # ── Step 1: Fatigue annotations (drawn first, underneath rPPG ROI)
                    if fatigue_engine is not None:
                        f_metrics = fatigue_engine.step(lm, w_px, h_px, ts, blendshapes=blendshapes)
                        f_metrics.face_detected = True
                        annotated = draw_fatigue_annotations(annotated, lm, f_metrics)
                        self.fatigue_metrics_ready.emit(f_metrics)

                    # ── Step 2: rPPG ROI extraction + engine (draws on top)
                    if rppg_engine is not None:
                        assert roi_tracker is not None
                        sample, roi_weights, roi_valid_count = collect_rppg_roi_sample(
                            bgr, lm, transform_matrix, roi_tracker, self._tuning
                        )
                        draw_rois(annotated, lm, transform_matrix, roi_tracker, self._tuning)
                        if sample is not None:
                            rppg_engine.push(ts, sample[0], sample[1], sample[2])
                        r_metrics = rppg_engine.compute(
                            ts,
                            bgr,
                            lm,
                            transform_matrix=transform_matrix,
                            roi_valid_count=roi_valid_count,
                            roi_weights=roi_weights,
                            roi_tracker=roi_tracker,
                            tuning=self._tuning,
                        )
                        r_metrics.roi_valid_count = roi_valid_count
                        r_metrics.face_detected = True
                        self.rppg_metrics_ready.emit(r_metrics)

                    # ── Composite status line ─────────────────────────────────
                    self._emit_status(f_metrics, r_metrics)
                else:
                    # No face — reset both engines
                    if fatigue_engine is not None:
                        f_metrics = fatigue_engine.on_no_face()
                        self.fatigue_metrics_ready.emit(f_metrics)
                    if rppg_engine is not None:
                        rppg_engine.reset()
                        if roi_tracker is not None:
                            roi_tracker.reset()
                        r_metrics = RppgMetrics(face_detected=False)
                        self.rppg_metrics_ready.emit(r_metrics)
                    self.status_changed.emit("未偵測到臉部…")

                # ── Fused fatigue score (every frame) ────────────────────────
                fused = self._fuser.update(rppg=r_metrics, fatigue=f_metrics)
                self.fused_score_ready.emit(fused)

                if ts - last_preview_emit >= preview_emit_interval:
                    last_preview_emit = ts
                    rgb_ann = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    rgb_ann = np.ascontiguousarray(rgb_ann)
                    fh, fw  = rgb_ann.shape[:2]
                    qimg    = QImage(
                        rgb_ann.data, fw, fh,
                        rgb_ann.strides[0],
                        QImage.Format.Format_RGB888,
                    )
                    self.frame_annotated.emit(qimg.copy())

        self.finished.emit()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _emit_status(
        self,
        fm: Optional[FatigueMetrics],
        rm: Optional["RppgMetrics"],
    ) -> None:
        parts: list[str] = []
        if fm is not None and fm.face_detected:
            if not fm.calibrated:
                parts.append(f"校準 {fm.calib_progress*100:.0f}%")
            else:
                parts.append(f"{fm.status}  EAR:{fm.ear_smooth:.2f}")
        if rm is not None and rm.face_detected:
            if rm.warmup_progress < 1.0:
                parts.append(f"rPPG暖機 {rm.warmup_progress*100:.0f}%")
            elif rm.bpm > 0:
                parts.append(f"❤ {rm.bpm:.0f}bpm")
        self.status_changed.emit("  │  ".join(parts) if parts else "偵測中…")
