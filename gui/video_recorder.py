"""Background video recorder for raw camera frames."""

from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any, Optional
import shutil
import subprocess

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage


class VideoRecorderWorker(QObject):
    started = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        frame_queue: "queue.Queue[tuple[float, object]]",
        output_path: Path,
        fps: float = 30.0,
    ) -> None:
        super().__init__()
        self._queue = frame_queue
        self._output_path = Path(output_path)
        self._fps = float(fps) if fps > 0 else 30.0
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None
        self._writer: Optional[Any] = None
        self._started = False
        self._width: int | None = None
        self._height: int | None = None

    def request_stop(self) -> None:
        self._stop = True

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def _start_ffmpeg(self, width: int, height: int, codec: str) -> Optional[subprocess.Popen]:
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return None

        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            f"{self._fps:.2f}",
            "-i",
            "-",
            "-an",
            "-c:v",
            codec,
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(self._output_path),
        ]

        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self.failed.emit("無法啟動 ffmpeg。")
            return None

    def _start_opencv_writer(self, width: int, height: int) -> Optional[object]:
        fourcc_fn = getattr(cv2, "VideoWriter_fourcc")
        fourcc = fourcc_fn(*"mp4v")
        writer = cv2.VideoWriter(str(self._output_path), fourcc, self._fps, (width, height))
        if writer.isOpened():
            return writer

        alt_path = self._output_path.with_suffix(".avi")
        fourcc = fourcc_fn(*"XVID")
        writer = cv2.VideoWriter(str(alt_path), fourcc, self._fps, (width, height))
        if writer.isOpened():
            self._output_path = alt_path
            return writer
        writer.release()
        return None

    @Slot()
    def run(self) -> None:
        if np is None:
            self.failed.emit("NumPy 未安裝，無法錄製影片。")
            self.finished.emit()
            return

        first_frame_deadline = time.monotonic() + 3.0

        while not self._stop:
            try:
                _ts, frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                if not self._started and time.monotonic() > first_frame_deadline:
                    self.failed.emit("錄影未收到影像，請確認相機預覽與管線已啟動。")
                    break
                continue

            if frame is None:
                continue

            if isinstance(frame, QImage):
                img = frame
                if img.format() != QImage.Format.Format_RGB888:
                    img = img.convertToFormat(QImage.Format.Format_RGB888)
                width = img.width()
                height = img.height()
                ptr = img.constBits()
                arr = np.frombuffer(
                    ptr,
                    dtype=np.uint8,
                    count=img.bytesPerLine() * height,
                )
                arr = arr.reshape((height, img.bytesPerLine() // 3, 3))
                frame = arr[:, :width, :]
                # RGB→BGR via reversed view is non-contiguous; some cv2 builds
                # require C-contiguous input for VideoWriter.write().
                frame = np.ascontiguousarray(frame[:, :, ::-1])

            if not isinstance(frame, np.ndarray):
                self.failed.emit("影像格式不支援，無法建立影片檔。")
                break

            if self._proc is None and self._writer is None:
                self._width = int(frame.shape[1])
                self._height = int(frame.shape[0])
                self._proc = self._start_ffmpeg(self._width, self._height, "libx264")
                if self._proc is not None and self._proc.poll() is not None:
                    self._proc = self._start_ffmpeg(self._width, self._height, "mpeg4")
                    if self._proc is not None:
                        self.failed.emit("libx264 不可用，已改用 mpeg4。")

                if self._proc is None:
                    self._writer = self._start_opencv_writer(self._width, self._height)
                    if self._writer is None:
                        self.failed.emit("找不到 ffmpeg，且 OpenCV VideoWriter 無法啟動。")
                        break
                self._started = True
                self.started.emit(str(self._output_path))

            if self._proc is not None and self._proc.poll() is not None:
                try:
                    if self._proc.stdin is not None:
                        self._proc.stdin.close()
                    self._proc.wait(timeout=0.2)
                except Exception:
                    pass
                self._proc = None
                self.failed.emit("ffmpeg 已中止，嘗試改用 OpenCV。")
                if self._writer is None:
                    self._writer = self._start_opencv_writer(int(frame.shape[1]), int(frame.shape[0]))
                if self._writer is None:
                    self.failed.emit("OpenCV VideoWriter 啟動失敗，無法錄製影片。")
                    break

            try:
                if self._proc is not None:
                    assert self._proc.stdin is not None
                    self._proc.stdin.write(frame.tobytes())
                elif self._writer is not None:
                    self._writer.write(frame)
            except Exception:
                self.failed.emit("寫入影片失敗，請確認 ffmpeg 狀態與磁碟空間。")
                break

        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None

        if self._started:
            self.finished.emit()
