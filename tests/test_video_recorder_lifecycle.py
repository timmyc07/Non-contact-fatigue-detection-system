from __future__ import annotations

import queue
from pathlib import Path

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
