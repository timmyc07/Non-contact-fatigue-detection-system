from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui.video_recorder import VideoRecorderWorker


def test_unexpected_video_error_releases_encoder_and_emits_finished(
    tmp_path: Path,
) -> None:
    worker = VideoRecorderWorker(queue.Queue(), tmp_path / "capture.mp4")
    events: list[str] = []
    worker.failed.connect(lambda message: events.append(f"failed:{message}"))
    worker.finished.connect(lambda: events.append("finished"))
    worker._record_frames = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("unexpected")
    )
    worker._release_encoders = lambda: events.append("released")  # type: ignore[method-assign]

    worker.run()

    assert events == [
        "failed:影片錄製發生未預期錯誤：unexpected",
        "released",
        "finished",
    ]


def test_rgb_image_row_padding_is_not_encoded_as_pixels(tmp_path, monkeypatch):
    frames = queue.Queue()
    image = QImage(641, 2, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)
    frames.put((0.0, image))
    worker = VideoRecorderWorker(frames, tmp_path / "padding.mp4")
    encoded = []
    errors = []

    def write(frame):
        encoded.append(frame.copy())
        worker.request_stop()

    monkeypatch.setattr(worker, "_start_ffmpeg", lambda *_: None)
    monkeypatch.setattr(worker, "_start_opencv_writer", lambda *_: SimpleNamespace(write=write, release=lambda: None))
    worker.failed.connect(errors.append)
    worker.run()

    assert errors == []
    assert len(encoded) == 1
    assert encoded[0].shape == (2, 641, 3)
    assert encoded[0].flags.c_contiguous
    np.testing.assert_array_equal(encoded[0], np.tile([0, 0, 255], (2, 641, 1)))


@pytest.mark.parametrize("failure", ["exit", "timeout", "stdin"])
def test_encoder_finalization_failure_is_reported_and_cleanup_completes(tmp_path, monkeypatch, failure):
    worker = VideoRecorderWorker(queue.Queue(), tmp_path / "capture.mp4")
    events = []
    waits = []

    def close():
        events.append("stdin.close")
        if failure == "stdin":
            raise BrokenPipeError("encoder exited")

    def wait(**kwargs):
        waits.append(kwargs["timeout"])
        events.append("wait")
        if failure == "timeout" and len(waits) == 1:
            raise subprocess.TimeoutExpired("ffmpeg", 2)
        return 1 if failure == "exit" else -9

    worker._proc = SimpleNamespace(stdin=SimpleNamespace(close=close), wait=wait, kill=lambda: events.append("kill"))
    worker._writer = SimpleNamespace(release=lambda: events.append("writer.release"))
    monkeypatch.setattr(worker, "_record_frames", lambda: None)
    failures = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: events.append("finished"))
    worker.run()

    assert failures
    assert events[-2:] == ["writer.release", "finished"]
    assert worker._proc is None
    assert worker._writer is None
    if failure in ("timeout", "stdin"):
        assert "kill" in events
        assert "wait" in events[events.index("kill") + 1:]


def test_release_exception_does_not_prevent_finished(tmp_path, monkeypatch):
    worker = VideoRecorderWorker(queue.Queue(), tmp_path / "capture.mp4")
    events = []
    monkeypatch.setattr(worker, "_record_frames", lambda: None)
    monkeypatch.setattr(worker, "_release_encoders", lambda: (_ for _ in ()).throw(RuntimeError("release")))
    worker.failed.connect(lambda message: events.append("failed"))
    worker.finished.connect(lambda: events.append("finished"))
    worker.run()
    assert events == ["failed", "finished"]


def test_stalled_encoder_write_stops_and_reaps_its_child(tmp_path, monkeypatch):
    frames = queue.Queue()
    frames.put((0.0, np.zeros((512, 512, 3), dtype=np.uint8)))
    worker = VideoRecorderWorker(frames, tmp_path / "stalled.mp4")
    monkeypatch.setattr(worker, "ENCODER_STOP_TIMEOUT_SEC", 0.05, raising=False)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    original_stdin = process.stdin
    writing = threading.Event()
    completed = threading.Event()
    timers = []
    original_timer = threading.Timer

    def timer(*args, **kwargs):
        created = original_timer(*args, **kwargs)
        timers.append(created)
        return created

    def write(data):
        writing.set()
        return original_stdin.write(data)

    process.stdin = SimpleNamespace(write=write, close=original_stdin.close)
    monkeypatch.setattr(threading, "Timer", timer)
    monkeypatch.setattr(worker, "_start_ffmpeg", lambda *_: process)
    failures = []
    worker.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    worker.finished.connect(completed.set, Qt.ConnectionType.DirectConnection)
    thread = threading.Thread(target=worker.run)
    thread.start()
    try:
        assert writing.wait(2.0)
        worker.request_stop()
        worker.request_stop()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert completed.is_set()
        assert process.poll() is not None
        assert len(failures) == 1
        assert "逾時" in failures[0]
        assert len(timers) == 1
        assert not any(timer.is_alive() for timer in timers)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2.0)
        thread.join(timeout=2.0)
        original_stdin.close()


@pytest.mark.parametrize("stop_before_run", [True, False])
def test_normal_eof_cancels_stop_watchdog_before_encoder_finalization(tmp_path, monkeypatch, stop_before_run):
    worker = VideoRecorderWorker(queue.Queue(), tmp_path / "normal.mp4")
    monkeypatch.setattr(worker, "ENCODER_STOP_TIMEOUT_SEC", 0.02, raising=False)
    killed = []
    failures = []

    def wait(**kwargs):
        worker.request_stop()
        time.sleep(0.05)
        return 0

    worker._proc = SimpleNamespace(
        stdin=SimpleNamespace(close=lambda: None), wait=wait,
        kill=lambda: killed.append(True),
    )
    monkeypatch.setattr(worker, "_record_frames", lambda: None)
    worker.failed.connect(failures.append)
    if stop_before_run:
        worker.request_stop()
    worker.run()
    assert not killed
    assert not failures


def test_stalled_encoder_close_is_interrupted_and_finished_once(tmp_path, monkeypatch):
    worker = VideoRecorderWorker(queue.Queue(), tmp_path / "stalled_close.mp4")
    monkeypatch.setattr(worker, "ENCODER_STOP_TIMEOUT_SEC", 0.02)
    unblock = threading.Event()
    failures = []
    finished = []
    worker._proc = SimpleNamespace(
        stdin=SimpleNamespace(close=lambda: unblock.wait(1.0)),
        wait=lambda **kwargs: -9,
        kill=unblock.set,
    )
    monkeypatch.setattr(worker, "_record_frames", lambda: None)
    worker.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert unblock.is_set()
    assert len(failures) == 1 and "逾時" in failures[0]
    assert finished == [True]
    assert worker._stop_watchdog is None
