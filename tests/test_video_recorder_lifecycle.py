from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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
