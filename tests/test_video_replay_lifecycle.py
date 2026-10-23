from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import gui.video_replay as replay


@pytest.fixture
def resources(monkeypatch):
    events = []

    class Capture:
        opened = True

        def isOpened(self):
            return self.opened

        def get(self, prop):
            return {replay.cv2.CAP_PROP_FPS: 30, replay.cv2.CAP_PROP_FRAME_WIDTH: 16,
                    replay.cv2.CAP_PROP_FRAME_HEIGHT: 16}.get(prop, 0)

        def read(self):
            return False, None

        def release(self):
            events.append("capture.release")

    class Recorder:
        def request_close(self):
            events.append("recorder.request_close")

        def wait_closed(self, timeout_seconds):
            assert timeout_seconds is None
            events.append("recorder.drained")
            return True

    capture = Capture()
    recorder = Recorder()
    writer = SimpleNamespace(
        isOpened=lambda: True,
        release=lambda: events.append("writer.release"),
    )
    monkeypatch.setattr(replay.cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(replay, "_writer_for", lambda *_args: writer)
    monkeypatch.setattr(replay, "MetricsRecorder", lambda _path: recorder)
    monkeypatch.setattr(replay, "ensure_face_model", lambda _path: "model.task")
    monkeypatch.setattr(replay, "create_face_landmarker_base_options", lambda *_args: object())
    monkeypatch.setattr(replay._mp_vision, "FaceLandmarkerOptions", lambda **_kwargs: object())
    monkeypatch.setattr(replay._mp_vision.FaceLandmarker, "create_from_options",
                        lambda _options: nullcontext(SimpleNamespace()))
    return SimpleNamespace(capture=capture, recorder=recorder, writer=writer, events=events)


def run_video(tmp_path):
    video = replay.ReplayVideo("01", "0", "Alert", tmp_path / "0.mov")
    return replay.run_replay_video(video, tmp_path / "output", "test", write_annotated_video=True)


def test_unopened_capture_is_released(tmp_path, resources):
    resources.capture.opened = False
    summary = run_video(tmp_path)
    assert summary.status == "failed"
    assert resources.events == ["capture.release"]


@pytest.mark.parametrize("stage", ["recorder", "model"])
def test_replay_setup_failure_closes_all_acquired_resources(tmp_path, monkeypatch, resources, stage):
    def fail(*_args):
        raise OSError(f"{stage} unavailable")

    monkeypatch.setattr(replay, "MetricsRecorder" if stage == "recorder" else "ensure_face_model", fail)
    summary = run_video(tmp_path)
    assert summary.status == "failed"
    assert f"{stage} unavailable" in summary.error
    assert "capture.release" in resources.events
    assert "writer.release" in resources.events
    if stage == "model":
        assert resources.events[:2] == ["recorder.request_close", "recorder.drained"]


def test_replay_does_not_report_done_before_database_is_drained(tmp_path, resources):
    summary = run_video(tmp_path)
    assert summary.status == "done"
    assert resources.events == ["recorder.request_close", "recorder.drained", "capture.release", "writer.release"]


@pytest.mark.parametrize("resource_name,method", [
    ("recorder", "wait_closed"), ("capture", "release"), ("writer", "release"),
])
def test_cleanup_failure_is_reported_without_skipping_other_resources(
    tmp_path, monkeypatch, resources, resource_name, method,
):
    def fail(*_args, **_kwargs):
        resources.events.append(f"{resource_name}.failed")
        raise OSError(f"{resource_name} cleanup failed")

    monkeypatch.setattr(getattr(resources, resource_name), method, fail)
    summary = run_video(tmp_path)
    assert summary.status == "failed"
    assert f"{resource_name} cleanup failed" in summary.error
    for name in ("capture", "writer"):
        assert f"{name}.{'failed' if name == resource_name else 'release'}" in resources.events
