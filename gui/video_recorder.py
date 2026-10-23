"""Background video recorder for raw camera frames."""

from __future__ import annotations

import queue
import math
import time
from pathlib import Path
from typing import Any, Optional
import shutil
import subprocess
import threading

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage


class VideoRecorderWorker(QObject):
    ENCODER_STOP_TIMEOUT_SEC = 2.0

    started = Signal(str)
    warning = Signal(str)
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
        self._fps = float(fps) if math.isfinite(fps) and fps > 0 else 30.0
        self._started_at = time.perf_counter()
        self._stopped_at: float | None = None
        self._frames_written = 0
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None
        self._writer: Optional[Any] = None
        self._started = False
        self._width: int | None = None
        self._height: int | None = None
        self._encoder_lock = threading.Lock()
        self._stop_watchdog: threading.Timer | None = None
        self._watchdog_threads: list[threading.Timer] = []
        self._encoder_timed_out = False
        self._encoder_eof = False
        self._failure_reported = False
        self._finished = threading.Event()

    def request_stop(self) -> None:
        with self._encoder_lock:
            if self._stop or self._finished.is_set():
                return
            self._stopped_at = time.perf_counter()
            self._stop = True
        self._arm_stop_watchdog()

    def _fail(self, message: str) -> None:
        with self._encoder_lock:
            if self._failure_reported:
                return
            self._failure_reported = True
            if self._encoder_timed_out:
                message = "停止影片編碼逾時，已中止編碼程序，影片可能不完整。"
        self.failed.emit(message)

    def _arm_stop_watchdog(self) -> None:
        with self._encoder_lock:
            previous, self._stop_watchdog = self._stop_watchdog, None
            if previous is not None:
                previous.cancel()
            proc = self._proc
            if proc is not None and not self._encoder_timed_out and not self._encoder_eof and not self._finished.is_set():
                def abort_stalled_encoder():
                    with self._encoder_lock:
                        if self._stop_watchdog is not timer or self._proc is not proc:
                            return
                        self._encoder_timed_out = True
                    self._fail("停止影片編碼逾時")
                    try:
                        proc.kill()
                    except Exception as exc:
                        self.warning.emit(f"無法停止影片編碼程序：{exc}")

                timer = threading.Timer(self.ENCODER_STOP_TIMEOUT_SEC, abort_stalled_encoder)
                timer.daemon = True
                self._stop_watchdog = timer
                self._watchdog_threads.append(timer)
                timer.start()

    def _cancel_stop_watchdog(self) -> None:
        with self._encoder_lock:
            self._stop_watchdog = None
            timers, self._watchdog_threads = self._watchdog_threads, []
            for timer in timers:
                timer.cancel()
        for timer in timers:
            if timer is not threading.current_thread():
                timer.join(timeout=self.ENCODER_STOP_TIMEOUT_SEC)

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
            str(self._fps),
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
        try:
            self._record_frames()
        except Exception as exc:
            self._fail(f"影片錄製發生未預期錯誤：{exc}")
        finally:
            try:
                self._release_encoders()
            except Exception as exc:
                self._fail(f"影片收尾發生未預期錯誤：{exc}")
            finally:
                self._finished.set()
                self._cancel_stop_watchdog()
                self.finished.emit()

    def _record_frames(self) -> None:
        if np is None:
            self._fail("NumPy 未安裝，無法錄製影片。")
            return

        first_frame_deadline = time.monotonic() + 3.0
        previous_frame: np.ndarray | None = None
        previous_timestamp = self._started_at

        while True:
            try:
                timestamp, frame = (
                    self._queue.get_nowait() if self._stop else self._queue.get(timeout=0.2)
                )
            except queue.Empty:
                if self._stop:
                    break
                if not self._started and time.monotonic() > first_frame_deadline:
                    self._fail("錄影未收到影像，請確認相機預覽與管線已啟動。")
                    return
                continue

            if frame is None:
                continue
            if (
                not math.isfinite(timestamp)
                or timestamp < previous_timestamp
                or timestamp > time.perf_counter() + 1e-6
            ):
                self._fail("影像時間戳無效，已停止錄影以避免時間軸錯誤。")
                return
            if self._stopped_at is not None and timestamp > self._stopped_at:
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
                frame = arr.reshape(height, img.bytesPerLine())[:, :width * 3].reshape(height, width, 3)
                # RGB→BGR via reversed view is non-contiguous; some cv2 builds
                # require C-contiguous input for VideoWriter.write().
                frame = np.ascontiguousarray(frame[:, :, ::-1])

            if not isinstance(frame, np.ndarray):
                self._fail("影像格式不支援，無法建立影片檔。")
                return

            if self._proc is None and self._writer is None:
                self._width = int(frame.shape[1])
                self._height = int(frame.shape[0])
                self._proc = self._start_ffmpeg(self._width, self._height, "libx264")
                if self._proc is not None and self._proc.poll() is not None:
                    self._proc = self._start_ffmpeg(self._width, self._height, "mpeg4")
                    if self._proc is not None:
                        self.warning.emit("libx264 不可用，已改用 mpeg4。")

                if self._proc is None:
                    self._writer = self._start_opencv_writer(self._width, self._height)
                    if self._writer is None:
                        self._fail("找不到 ffmpeg，且 OpenCV VideoWriter 無法啟動。")
                        break
                self._started = True
                self.started.emit(str(self._output_path))
                if self._stop:
                    self._arm_stop_watchdog()

            if self._proc is not None and self._proc.poll() is not None:
                self._fail("ffmpeg 已中止，保留現有影片並停止錄製。")
                return

            try:
                # 固定 FPS 編碼依實際時間補／丟幀，不能把節流後預覽當作相機 FPS。
                held_frame = previous_frame
                if held_frame is None:
                    held_frame = (
                        np.zeros_like(frame)
                        if timestamp - self._started_at >= 1.0 / self._fps else frame
                    )
                self._write_frames_until(held_frame, timestamp)
            except Exception:
                self._fail("寫入影片失敗，請確認 ffmpeg 狀態與磁碟空間。")
                return
            previous_frame = frame
            previous_timestamp = timestamp

        if previous_frame is not None and self._stopped_at is not None:
            self._write_frames_until(previous_frame, self._stopped_at)

    def _write_frames_until(self, frame: np.ndarray, timestamp: float) -> None:
        # 微小浮點誤差不可在整數幀邊界額外補一幀。
        target_count = max(1, math.ceil((timestamp - self._started_at) * self._fps - 1e-6))
        if target_count <= self._frames_written:
            return
        encoded = frame.tobytes() if self._proc is not None else None
        while self._frames_written < target_count:
            if self._proc is not None:
                assert self._proc.stdin is not None
                self._proc.stdin.write(encoded)
            elif self._writer is not None:
                self._writer.write(frame)
            self._frames_written += 1

    def _release_encoders(self) -> None:
        proc = self._proc
        if proc is not None:
            self._arm_stop_watchdog()
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                # EOF 已交付，正常收尾由 wait 自己的期限管理。
                with self._encoder_lock:
                    self._encoder_eof = True
                self._cancel_stop_watchdog()
                returncode = proc.wait(timeout=2.0)
                if returncode != 0:
                    self._fail(f"影片收尾失敗：ffmpeg 結束碼 {returncode}，請檢查影片檔。")
            except Exception as exc:
                self._fail(f"影片收尾失敗：{exc}，影片可能不完整。")
                try:
                    proc.kill()
                except Exception as kill_error:
                    self.warning.emit(f"無法停止影片編碼程序：{kill_error}")
                try:
                    proc.wait(timeout=2.0)
                except Exception as wait_error:
                    self.warning.emit(f"無法回收影片編碼程序：{wait_error}")
            finally:
                self._cancel_stop_watchdog()
                self._proc = None
        writer, self._writer = self._writer, None
        if writer is not None:
            try:
                writer.release()
            except Exception as exc:
                self._fail(f"影片收尾失敗：{exc}，影片可能不完整。")
