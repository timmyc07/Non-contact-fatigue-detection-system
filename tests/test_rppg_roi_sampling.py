"""ROI 同幀濾波重用的數值、遮擋、幾何與亮度等價驗證。"""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from gui.mediapipe_tuning import load_mediapipe_tuning
from rppg import rppg_worker as module


def _landmarks(shift=0.0):
    points = [SimpleNamespace(x=0.5 + shift, y=0.5) for _ in range(478)]
    points[1] = SimpleNamespace(x=0.5, y=0.45)
    points[152] = SimpleNamespace(x=0.5, y=0.82)
    points[234] = SimpleNamespace(x=0.30, y=0.52)
    points[454] = SimpleNamespace(x=0.70, y=0.52)
    points[33] = SimpleNamespace(x=0.38, y=0.36)
    points[263] = SimpleNamespace(x=0.62, y=0.36)
    centers = [(0.5, 0.25), (0.35, 0.55), (0.65, 0.55), (0.5, 0.4)]
    for (_, indices), (cx, cy) in zip(module.ROI_SPECS, centers):
        for index, angle in zip(indices, np.linspace(0, 2 * np.pi, len(indices), endpoint=False)):
            points[index] = SimpleNamespace(
                x=float(cx + shift + 0.06 * np.cos(angle)), y=float(cy + 0.04 * np.sin(angle)),
            )
    return points


@pytest.mark.parametrize("with_means", [False, True])
def test_collector_blurs_the_frame_once_for_all_four_rois(monkeypatch, with_means):
    frame = np.random.default_rng(42).integers(0, 256, (240, 360, 3), dtype=np.uint8)
    blur = cv2.GaussianBlur
    calls = []

    def counted_blur(*args, **kwargs):
        calls.append(None)
        return blur(*args, **kwargs)

    monkeypatch.setattr(cv2, "GaussianBlur", counted_blur)
    collect = module.collect_rppg_roi_sample_with_means if with_means else module.collect_rppg_roi_sample
    result = collect(frame, _landmarks(), None, module.RoiGeometryTracker(), load_mediapipe_tuning())

    assert result[2] > 0
    if with_means:
        assert len(result[3]) == 4
    assert len(calls) == 1


@pytest.mark.parametrize("canonical_warp", [False, True])
@pytest.mark.parametrize("weighted_mix", [False, True])
@pytest.mark.parametrize("with_means", [False, True])
def test_shared_blur_matches_independent_filtering_exactly(
    monkeypatch, canonical_warp, weighted_mix, with_means,
):
    tuning = load_mediapipe_tuning()
    tuning = replace(tuning, rppg_roi=replace(
        tuning.rppg_roi, canonical_roi_warp_enabled=canonical_warp,
    ))
    collect = module.collect_rppg_roi_sample_with_means if with_means else module.collect_rppg_roi_sample
    kwargs = {"weighted_mix": weighted_mix} if with_means else {}
    original_mean = module.roi_mean_from_points

    def independent_mean(frame, points, blur_ksize=5, **_):
        return original_mean(frame, points, blur_ksize)

    trackers = [module.RoiGeometryTracker(), module.RoiGeometryTracker()]
    engines = [module.RppgEngine(), module.RppgEngine()]
    transform = np.eye(4)
    transform[:3, :3] = [[0.98, -0.04, 0.19], [0.08, 0.97, -0.23], [-0.18, 0.24, 0.95]]
    rng = np.random.default_rng(22)
    for index in range(3):
        frame = rng.integers(0, 256, (240, 360, 3), dtype=np.uint8)
        frame[:, :160] = [0, 0, 0] if index == 1 else [255, 255, 255]
        landmarks = _landmarks(index * 0.001)
        with monkeypatch.context() as baseline:
            baseline.setattr(module, "roi_mean_from_points", independent_mean)
            expected = collect(frame, landmarks, transform, trackers[0], tuning, **kwargs)
        actual = collect(frame, landmarks, transform, trackers[1], tuning, **kwargs)
        assert actual == expected

        annotated = []
        metrics = []
        for tracker, engine, result in zip(trackers, engines, (expected, actual)):
            image = frame.copy()
            module.draw_rois(image, landmarks, transform, tracker, tuning)
            annotated.append(image)
            if result[0] is not None:
                engine.push(index / 30.0, *result[0])
            metrics.append(engine.compute(
                index / 30.0, frame, landmarks, transform_matrix=transform,
                roi_valid_count=result[2], roi_weights=result[1], roi_tracker=tracker, tuning=tuning,
            ))
        np.testing.assert_array_equal(annotated[0], annotated[1])
        assert asdict(metrics[0]) == asdict(metrics[1])
        for name, _ in module.ROI_SPECS:
            np.testing.assert_array_equal(trackers[0].last_roi_pts[name], trackers[1].last_roi_pts[name])
        assert trackers[0].canonical_roi_warp_used == trackers[1].canonical_roi_warp_used == canonical_warp


@pytest.mark.parametrize("canonical_warp", [False, True])
def test_skipping_roi_pixels_keeps_tracker_and_following_metrics_identical(canonical_warp):
    tuning = load_mediapipe_tuning()
    tuning = replace(tuning, rppg_roi=replace(
        tuning.rppg_roi, canonical_roi_warp_enabled=canonical_warp,
    ))
    trackers = [module.RoiGeometryTracker(), module.RoiGeometryTracker()]
    engines = [module.RppgEngine(), module.RppgEngine()]
    transform = np.eye(4)
    transform[0, 1] = 0.1
    transform[2, 0] = 0.2
    rng = np.random.default_rng(12)
    for index in range(360):
        frame = rng.integers(0, 256, (240, 360, 3), dtype=np.uint8)
        landmarks = _landmarks(0.004 * np.sin(index / 13.0))
        metrics = []
        samples = []
        for tracker, engine, draw in zip(trackers, engines, (True, index % 3 == 0)):
            result = module.collect_rppg_roi_sample_with_means(frame, landmarks, transform, tracker, tuning)
            samples.append(result)
            preview = frame.copy()
            module.draw_rois(preview, landmarks, transform, tracker, tuning, draw=draw)
            if not draw:
                np.testing.assert_array_equal(preview, frame)
            if result[0] is not None:
                engine.push(index / 30.0, *result[0])
            metrics.append(engine.compute(
                index / 30.0, frame, landmarks, transform_matrix=transform,
                roi_valid_count=result[2], roi_weights=result[1], roi_tracker=tracker, tuning=tuning,
            ))
        assert samples[0] == samples[1]
        assert asdict(metrics[0]) == asdict(metrics[1])
        for name, _ in module.ROI_SPECS:
            np.testing.assert_array_equal(trackers[0].last_roi_pts[name], trackers[1].last_roi_pts[name])
