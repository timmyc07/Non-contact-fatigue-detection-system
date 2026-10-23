"""分析 worker 的連續推論失敗停止與短暫錯誤恢復。"""

from __future__ import annotations

import importlib
import queue
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(params=[
    ("gui.fatigue_worker", "FatigueWorker"),
    ("gui.combined_worker", "CombinedWorker"),
    ("rppg.rppg_worker", "RppgWorker"),
])
def worker_run(request, monkeypatch):
    module_name, worker_name = request.param
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "ensure_face_model", lambda *_a, **_k: Path("mock.task"))
    monkeypatch.setattr(module, "create_face_landmarker_base_options", lambda *_: object())
    monkeypatch.setattr(module._mp_vision, "FaceLandmarkerOptions", lambda **_: object())

    def run(outcomes, *, with_face=False, frame_interval=1 / 30):
        worker = getattr(module, worker_name)(queue.Queue())
        failures, finished, metrics = [], [], []

        class Landmarker:
            calls = 0
            closed = False

            def __init__(self):
                self.previews = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.closed = True

            def detect_for_video(self, *_):
                success = outcomes[self.calls]
                self.calls += 1
                if self.calls == len(outcomes):
                    worker.request_stop()
                if not success:
                    raise RuntimeError("inference failure")
                return SimpleNamespace(
                    face_landmarks=(
                        [[SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]] if with_face else []
                    ),
                    face_blendshapes=[], facial_transformation_matrixes=[],
                )

        landmarker = Landmarker()
        monkeypatch.setattr(
            module._mp_vision.FaceLandmarker, "create_from_options", lambda _: landmarker,
        )
        monkeypatch.setattr(module, "get_latest", lambda *_a, **_k: (
            10.0 + landmarker.calls * frame_interval, np.zeros((32, 32, 3), dtype=np.uint8),
        ))
        worker.failed.connect(lambda msg: failures.append((msg, landmarker.closed)))
        worker.finished.connect(lambda: finished.append(landmarker.closed))
        signal = (
            worker.fatigue_metrics_ready if worker_name == "CombinedWorker" else worker.metrics_ready
        )
        signal.connect(metrics.append)
        worker.frame_annotated.connect(landmarker.previews.append)
        worker.run()
        return landmarker, failures, finished, metrics

    return run


def test_repeated_inference_failures_stop_and_release_landmarker(worker_run):
    landmarker, failures, finished, metrics = worker_run([False] * 60)

    assert landmarker.calls == 30
    assert len(failures) == 1
    assert "連續 30 次" in failures[0][0]
    assert "inference failure" in failures[0][0]
    assert failures[0][1] is True
    assert finished == [True]
    assert metrics == []


def test_successful_frame_resets_consecutive_inference_failure_count(worker_run):
    outcomes = [False] * 29 + [True] + [False] * 29 + [True]
    landmarker, failures, finished, metrics = worker_run(outcomes)

    assert landmarker.calls == len(outcomes)
    assert failures == []
    assert finished == [True]
    assert len(metrics) == 2
    assert all(not metric.face_detected for metric in metrics)


def test_persistent_failure_after_recovery_still_stops(worker_run):
    outcomes = [False] * 29 + [True] + [False] * 40
    landmarker, failures, finished, metrics = worker_run(outcomes)

    assert landmarker.calls == 60
    assert len(failures) == 1
    assert finished == [True]
    assert len(metrics) == 1


def test_normal_frames_keep_emitting_metrics_without_failure(worker_run):
    landmarker, failures, finished, metrics = worker_run([True] * 6)

    assert landmarker.calls == 6
    assert failures == []
    assert finished == [True]
    assert len(metrics) == 6


def test_preview_throttling_skips_pixel_annotations_but_keeps_all_analysis(
    worker_run, request, monkeypatch,
):
    module_name, worker_name = request.node.callspec.params["worker_run"]
    module = importlib.import_module(module_name)
    fatigue_draws = []
    roi_draws = []
    if worker_name != "RppgWorker":
        def draw_fatigue(frame, *_args):
            fatigue_draws.append(None)
            return frame.copy()
        monkeypatch.setattr(module, "draw_fatigue_annotations", draw_fatigue)
    if worker_name != "FatigueWorker":
        original = module.draw_rois

        def draw_roi(*args, **kwargs):
            roi_draws.append(kwargs.get("draw", True))
            return original(*args, **kwargs)
        monkeypatch.setattr(module, "draw_rois", draw_roi)

    landmarker, failures, finished, metrics = worker_run(
        [True] * 60, with_face=True, frame_interval=1 / 60,
    )

    assert failures == []
    assert finished == [True]
    assert len(metrics) == 60
    assert 1 < len(landmarker.previews) < len(metrics)
    if worker_name != "RppgWorker":
        assert len(fatigue_draws) == len(landmarker.previews)
    if worker_name != "FatigueWorker":
        assert len(roi_draws) == 60
        assert sum(roi_draws) == len(landmarker.previews)
