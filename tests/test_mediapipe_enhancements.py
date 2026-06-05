from __future__ import annotations

from types import SimpleNamespace
import sys
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from gui.mediapipe_tuning import load_mediapipe_tuning  # noqa: E402
from gui.metrics_recorder import MetricsRecorder  # noqa: E402
from gui.fatigue_scorer import FatigueFuser  # noqa: E402
from gui.fatigue_engine import FatigueMetrics  # noqa: E402
from gui.fatigue_engine import _norm_blend  # noqa: E402
from rppg.rppg_worker import (  # noqa: E402
    RppgMetrics,
    RppgEngine,
    RoiGeometryTracker,
    _face_quality_from_pose,
    _roi_weights_from_pose,
    collect_rppg_roi_sample,
)


def _fake_landmarks() -> list[SimpleNamespace]:
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[1] = SimpleNamespace(x=0.50, y=0.45)
    pts[10] = SimpleNamespace(x=0.50, y=0.20)
    pts[152] = SimpleNamespace(x=0.50, y=0.82)
    pts[234] = SimpleNamespace(x=0.34, y=0.52)
    pts[454] = SimpleNamespace(x=0.66, y=0.52)
    pts[33] = SimpleNamespace(x=0.38, y=0.36)
    pts[263] = SimpleNamespace(x=0.62, y=0.38)
    for idx in (338, 297, 332, 284, 251, 389, 356, 323, 361, 288, 397, 365, 379, 378, 400, 377, 148, 176, 149, 150, 136, 172, 58, 132, 93, 127, 162, 21, 54, 103, 67, 109):
        pts[idx] = SimpleNamespace(x=0.50, y=0.35)
    return pts


def test_roi_weights_are_normalised() -> None:
    lm = _fake_landmarks()
    weights = _roi_weights_from_pose(8.0, 12.0, 4.0, lm, 640, 480)

    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["L_cheek"] != weights["R_cheek"]


def test_quality_score_penalises_motion() -> None:
    base = _face_quality_from_pose(5.0, 5.0, 2.0, 0.12, 0.05, 1.0)
    moved = _face_quality_from_pose(5.0, 5.0, 2.0, 0.12, 1.20, 1.0)

    assert 0.0 <= moved < base <= 1.0


def test_blendshape_normalisation_uses_baseline() -> None:
    assert _norm_blend(0.65, 0.15) > _norm_blend(0.35, 0.15)
    assert _norm_blend(0.10, 0.15) == 0.0


def test_mediapipe_tuning_profiles_load() -> None:
    tuning = load_mediapipe_tuning()

    assert tuning.face_landmarker.num_faces == 1
    assert "stable_indoor" in tuning.profiles
    assert 0.0 <= tuning.rppg_roi.roi_smoothing_alpha <= 1.0
    assert tuning.rppg_roi.canonical_roi_warp_enabled is False


def test_roi_tracker_reports_jitter_and_area_stability() -> None:
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    lm = _fake_landmarks()
    tracker = RoiGeometryTracker()
    tuning = load_mediapipe_tuning()

    collect_rppg_roi_sample(frame, lm, None, tracker, tuning)
    first_jitter = tracker.landmark_jitter_norm
    lm[10] = SimpleNamespace(x=0.52, y=0.22)
    collect_rppg_roi_sample(frame, lm, None, tracker, tuning)

    assert first_jitter == 0.0
    assert tracker.landmark_jitter_norm > 0.0
    assert 0.0 <= tracker.roi_area_stability <= 1.0


def test_rppg_compute_non_warmup_returns_roi_weights() -> None:
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    lm = _fake_landmarks()
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    tracker = RoiGeometryTracker()
    tuning = load_mediapipe_tuning()
    roi_weights = {"forehead": 0.4, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.2}
    for i in range(150):
        t = i / 30.0
        val = 128.0 + 3.0 * np.sin(2.0 * np.pi * 1.2 * t)
        engine.push(t, val, 128.0, 127.0)

    tracker.update_landmarks(lm, 640, 480)
    metrics = engine.compute(
        5.0,
        frame,
        lm,
        roi_valid_count=4,
        roi_weights=roi_weights,
        roi_tracker=tracker,
        tuning=tuning,
    )

    assert metrics.roi_weight_forehead == 0.4
    assert metrics.roi_valid_count == 4
    assert metrics.landmark_jitter_norm >= 0.0


def test_fatigue_fuser_downweights_rppg_when_both_sources_available() -> None:
    fuser = FatigueFuser()
    rppg = RppgMetrics(
        bpm=82.0,
        sqi=0.8,
        quality_score=0.8,
        roi_valid_count=4,
        stress_prob=0.6,
        warmup_progress=1.0,
        face_detected=True,
    )
    fatigue = FatigueMetrics(
        face_detected=True,
        calibrated=True,
        fatigue_level=0.4,
        perclos=0.2,
    )

    score = fuser.update(rppg=rppg, fatigue=fatigue)

    assert score.rppg_available is True
    assert score.behavior_available is True
    assert score.rppg_weight_eff == 0.15
    assert score.behavior_weight_eff == 0.85


def test_fatigue_fuser_uses_blink_temporal_score() -> None:
    fuser = FatigueFuser()
    fatigue = FatigueMetrics(
        face_detected=True,
        calibrated=True,
        perclos=0.05,
        blink_temporal_score=0.8,
    )

    score = fuser.update(rppg=None, fatigue=fatigue)

    assert score.behavior_available is True
    assert score.beh_blink_temporal_score == 0.8
    assert score.behavior_sub > 0.0


def test_fatigue_fuser_ignores_low_quality_rppg() -> None:
    fuser = FatigueFuser()
    rppg = RppgMetrics(
        bpm=82.0,
        sqi=0.2,
        quality_score=0.8,
        roi_valid_count=4,
        stress_prob=0.6,
        warmup_progress=1.0,
        face_detected=True,
    )

    score = fuser.update(rppg=rppg, fatigue=None)

    assert score.rppg_available is False
    assert score.rppg_weight_eff == 0.0


def test_metrics_recorder_migrates_mediapipe_diagnostics(tmp_path: Path) -> None:
    db_path = tmp_path / "old_metrics.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL)")

    recorder = MetricsRecorder(str(db_path))
    try:
        cols = {
            row[1]
            for row in recorder.conn.execute("PRAGMA table_info(metrics)").fetchall()  # type: ignore[union-attr]
        }
    finally:
        recorder.close()

    assert "rppg_landmark_jitter_norm" in cols
    assert "rppg_roi_area_stability" in cols
    assert "rppg_canonical_roi_warp_used" in cols
    assert "raw_bpm" in cols
    assert "bpm_guard_reason" in cols
    assert "blink_temporal_score" in cols
    assert "fused_beh_blink_temporal_score" in cols
