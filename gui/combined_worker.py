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

import logging
import queue
import time
from typing import Optional, Callable

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

log = logging.getLogger(__name__)

from .fatigue_engine import FatigueEngine, FatigueMetrics, FatigueParams
from .personal_profile import PersonalProfile
from .frame_queue import get_latest
from .mediapipe_tuning import load_mediapipe_tuning
from .fatigue_scorer import FatigueFuser, FusedFatigueScore, FuserConfig
from .fatigue_worker import draw_fatigue_annotations
from rppg.rppg_worker import (
    RppgEngine, RppgMetrics,
    draw_rois,
    RoiGeometryTracker, collect_rppg_roi_sample_with_means,
    ensure_face_model, _MODELS_DIR,
    resolve_effective_rppg_tuning,
    ROI_SPECS, ROI_BASE_WEIGHTS,
)
from rppg.adaptive_calibration import recompute_raw_bpm_from_roi_windows
from rppg.calibration import apply_calibration_to_metrics


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
    calibration_loader : callable | None
        Returns active :class:`CalibrationVersion` for BPM correction.
    live_feed_writer : callable | None
        Called with raw (uncalibrated) :class:`RppgMetrics` for GUI calibration live feed.
    fuser_config : FuserConfig | None
        Fatigue fusion weights (rPPG + behaviour).
    """

    rppg_metrics_ready:    Signal = Signal(object)   # RppgMetrics
    fatigue_metrics_ready: Signal = Signal(object)   # FatigueMetrics
    fused_score_ready:     Signal = Signal(object)   # FusedFatigueScore
    frame_annotated:       Signal = Signal(QImage)   # combined annotated preview
    face_detected:         Signal = Signal(bool)
    status_changed:        Signal = Signal(str)
    failed:                Signal = Signal(str)
    finished:              Signal = Signal()
    # P6b-3b：低頻（~1Hz）current vs candidate ROI 權重原始 BPM 重算結果，供 GUI
    # 協調層（RppgParamCoordinator）做 A/B。(t_now, cur_raw_bpm, cand_raw_bpm)；
    # 任一值無法算出時以 NaN 表示。僅在 set_candidate_roi_weights() 設有候選時
    # 才會發射，見 _maybe_emit_candidate_bpm。
    candidate_bpm_ready:   Signal = Signal(float, float, float)

    # P6b-3b：candidate vs current BPM 低頻重算節奏（秒），與逐幀迴圈脫鉤。
    _CANDIDATE_RECOMPUTE_INTERVAL_SEC = 1.0

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, np.ndarray]]",
        enable_rppg:    bool = True,
        enable_fatigue: bool = True,
        target_fps:  float = 30.0,
        buffer_sec:  float = 12.0,
        fatigue_params: Optional[FatigueParams] = None,
        calibration_loader: Optional[Callable[[], object]] = None,
        live_feed_writer: Optional[Callable[[RppgMetrics], None]] = None,
        fuser_config: Optional[FuserConfig] = None,
        personal_profile: Optional[PersonalProfile] = None,
    ) -> None:
        super().__init__()
        self._queue          = frame_queue
        self._enable_rppg    = enable_rppg
        self._enable_fatigue = enable_fatigue
        self._target_fps     = target_fps
        self._buffer_sec     = buffer_sec
        self._fatigue_params = fatigue_params or FatigueParams()
        self._fuser          = FatigueFuser(fuser_config or FuserConfig())
        self._calibration_loader = calibration_loader
        self._live_feed_writer = live_feed_writer
        self._stop           = False
        self._tuning         = load_mediapipe_tuning()
        # 個人清醒基線：建構期注入（跨 session 載入）+ 執行中熱換（手動記錄基線）。
        self._personal_profile = personal_profile
        self._fatigue_engine: Optional[FatigueEngine] = None
        self._pending_profile: Optional[PersonalProfile] = None
        self._has_pending_profile = False
        # P6b-2：ROI base_weights 覆寫（None＝不覆寫，逐位元回退現行 tuning）。
        self._roi_weights_override: Optional[dict[str, float]] = None
        # P6b-3b：候選 ROI 權重（None＝無候選，低頻重算分支整段 early-return，
        # 逐幀路徑與現況逐位元不變）。pending-flag 熱設定，run() 迴圈輪詢讀取。
        self._candidate_roi_weights: Optional[dict[str, float]] = None
        self._last_candidate_recompute_t: float = 0.0

    def request_stop(self) -> None:
        self._stop = True

    def set_roi_base_weights_override(self, weights: Optional[dict[str, float]]) -> None:
        """P6b-2：顯式設定 ROI base_weights 覆寫。僅供 ``run()`` 開始前呼叫；
        套用只發生於 run() 啟動時的一次性讀取，不支援執行中熱切換
        （熱切換屬 P6b-3 線上協調層範疇）。"""
        self._roi_weights_override = weights

    def set_candidate_roi_weights(self, weights: Optional[dict[str, float]]) -> None:
        """P6b-3b：pending-flag 式熱設定候選 ROI 權重（None＝清除候選，暫停低頻
        重算與 candidate_bpm_ready 發射）。GUI 主執行緒呼叫；worker 執行緒於下一次
        低頻檢查週期（至多 ``_CANDIDATE_RECOMPUTE_INTERVAL_SEC`` 秒）讀取生效。
        執行緒安全假設同 ``set_roi_base_weights_override``：單一參照賦值，CPython
        GIL 下具原子性，讀寫不需額外鎖。
        """
        self._candidate_roi_weights = weights

    def _maybe_emit_candidate_bpm(
        self,
        rppg_engine: Optional["RppgEngine"],
        rppg_tuning,
        t_now: float,
    ) -> None:
        """P6b-3b：OFF（``rppg_engine is None`` 或無候選）時立即返回，不做任何
        額外運算／引擎存取／訊號發射，確保逐幀路徑與現況逐位元不變。ON 時低頻
        （約 1Hz）以 ``rppg_engine.get_roi_window`` 快照 + ``recompute_raw_bpm_
        from_roi_windows`` 對現行與候選 ROI 權重各重算一次 raw BPM，並發出
        ``candidate_bpm_ready`` 供 GUI 協調層做 A/B。
        """
        if rppg_engine is None:
            return
        candidate = self._candidate_roi_weights
        if candidate is None:
            return
        if t_now - self._last_candidate_recompute_t < self._CANDIDATE_RECOMPUTE_INTERVAL_SEC:
            return
        self._last_candidate_recompute_t = t_now

        roi_windows = {
            name: rppg_engine.get_roi_window(name, self._buffer_sec, t_now)
            for name, _ in ROI_SPECS
        }
        current_weights = dict(rppg_tuning.rppg_roi.base_weights or ROI_BASE_WEIGHTS)
        cur_bpm = recompute_raw_bpm_from_roi_windows(roi_windows, current_weights)
        cand_bpm = recompute_raw_bpm_from_roi_windows(roi_windows, candidate)
        self.candidate_bpm_ready.emit(
            float(t_now),
            float(cur_bpm) if cur_bpm is not None else float("nan"),
            float(cand_bpm) if cand_bpm is not None else float("nan"),
        )

    def set_personal_profile(self, profile: Optional[PersonalProfile]) -> None:
        """執行緒安全熱換個人基線（仿 request_stop：主執行緒設旗標，run 迴圈輪詢套用）。"""
        self._pending_profile = profile
        self._has_pending_profile = True

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
        fatigue_engine = (FatigueEngine(params=self._fatigue_params,
                                        personal_profile=self._personal_profile)
                          if self._enable_fatigue else None)
        self._fatigue_engine = fatigue_engine

        last_face      = False
        t_origin: Optional[float] = None
        ts_ms_prev     = 0
        last_preview_emit = 0.0
        preview_emit_interval = 1.0 / _ANNOTATED_PREVIEW_MAX_FPS

        # P6b-2：啟動時解析一次 ROI base_weights 覆寫（無覆寫時 rppg_tuning 與
        # self._tuning 為同一物件，逐幀路徑不變）。
        rppg_tuning = resolve_effective_rppg_tuning(
            self._tuning, self._roi_weights_override, self._calibration_loader
        )
        # P6b-3b（審查 B 修正）：weighted_mix 由「本次 run 是否實際套用了 ROI 權重
        # 覆寫」推導，而非 self._roi_weights_override（production 覆寫走
        # calibration_loader → rppg_params，不會設該欄位）。無覆寫時
        # resolve_effective_rppg_tuning 原樣回傳 self._tuning → roi_override_active
        # 為 False → 逐位元回退等權平均。
        roi_override_active = rppg_tuning is not self._tuning

        parts = []
        if self._enable_rppg:
            parts.append("rPPG")
        if self._enable_fatigue:
            parts.append("行為警覺")
        self.status_changed.emit(f"合併引擎就緒（{' + '.join(parts)}），等待幀資料…")

        with _mp_vision.FaceLandmarker.create_from_options(lm_options) as landmarker:
            while not self._stop:
                if self._has_pending_profile and fatigue_engine is not None:
                    fatigue_engine.set_personal_profile(self._pending_profile)
                    self._has_pending_profile = False
                try:
                    ts, bgr = get_latest(self._queue, timeout=0.1)
                except queue.Empty:
                    continue

                try:
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
                            sample, roi_weights, roi_valid_count, per_roi_means = collect_rppg_roi_sample_with_means(
                                bgr, lm, transform_matrix, roi_tracker, rppg_tuning,
                                weighted_mix=roi_override_active,
                            )
                            draw_rois(annotated, lm, transform_matrix, roi_tracker, self._tuning)
                            if sample is not None:
                                rppg_engine.push(ts, sample[0], sample[1], sample[2])
                            # P6b-1 新增：per-ROI 旁路緩衝，不影響上面既有 push() 的輸入/行為。
                            if per_roi_means:
                                rppg_engine.push_roi_means(ts, per_roi_means)
                            # P6b-3b：OFF（無候選）時 early-return，不影響本行以下既有流程。
                            self._maybe_emit_candidate_bpm(rppg_engine, rppg_tuning, ts)
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
                            if self._live_feed_writer is not None:
                                self._live_feed_writer(r_metrics)
                            if self._calibration_loader is not None:
                                try:
                                    version = self._calibration_loader()
                                    if version is not None:
                                        r_metrics = apply_calibration_to_metrics(r_metrics, version)
                                except Exception:
                                    pass
                            self.rppg_metrics_ready.emit(r_metrics)

                        # ── Composite status line ─────────────────────────────────
                        self._emit_status(f_metrics, r_metrics)
                    else:
                        # No face — reset both engines
                        if fatigue_engine is not None:
                            f_metrics = fatigue_engine.on_no_face(ts)
                            self.fatigue_metrics_ready.emit(f_metrics)
                        if rppg_engine is not None:
                            rppg_engine.reset()
                            if roi_tracker is not None:
                                roi_tracker.reset()
                            r_metrics = RppgMetrics(face_detected=False)
                            if self._live_feed_writer is not None:
                                self._live_feed_writer(r_metrics)
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
                except Exception:
                    log.exception("每幀處理發生未預期例外，略過此幀")
                    continue

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
                disp = rm.bpm_calibrated if rm.bpm_calibrated > 0 else rm.bpm
                parts.append(f"❤ {disp:.0f}bpm")
        self.status_changed.emit("  │  ".join(parts) if parts else "偵測中…")
