"""Background camera capture for overlay preview (OpenCV only; no MediaPipe)."""

from __future__ import annotations

import queue
import time
from collections import deque
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

import cv2

# How long to wait for the first frame before declaring failure (seconds).
_FIRST_FRAME_TIMEOUT = 10.0
_READ_FAILURE_TIMEOUT = 5.0
_DARK_FRAME_WARN_SECONDS = 3.0

# Sliding-window FPS: keeps timestamps of last N frames.
# fps = (N-1) / (newest_ts - oldest_ts)
# Immune to MSMF's bursty delivery which spikes EMA-based counters.
_FPS_WINDOW_FRAMES = 60


class CameraStreamWorker(QObject):
    """Runs in a QThread: grab frames via FFMPEG (or other backend), emit QImage + real FPS.

    FFMPEG backend:
        cap.set() for resolution and FPS does not trigger a full pipeline rebuild
        (unlike MSMF), so we apply the user's requested values before reading.
        FOURCC is intentionally not set — FFMPEG selects the best format.

    FPS measurement:
        Sliding-window counter over the last _FPS_WINDOW_FRAMES timestamps.
        fps = (N-1) / (newest_ts - oldest_ts)
        Immune to backends that deliver frames in bursts (e.g. MSMF).
    """

    frame_ready = Signal(QImage)
    fps_ready = Signal(float)
    # emitted once after open (and again if values change): (codec, w, h, fps)
    camera_info = Signal(str, int, int, float)
    diagnostic_ready = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        camera_index: int,
        width: int = 1280,
        height: int = 720,
        target_fps: int = 30,
        backend: str = "ffmpeg",
    ) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._width = max(160, width)
        self._height = max(120, height)
        self._target_fps = max(1, target_fps)
        self._backend = backend.lower().strip()
        self._stop = False
        self._bgr_queues: set["queue.Queue[tuple[float, np.ndarray]]"] = set()

    def attach_bgr_queue(self, q: "queue.Queue[tuple[float, np.ndarray]]") -> None:
        """Attach a queue to receive (timestamp, BGR frame) tuples.
        Multiple queues may be attached simultaneously (e.g. rPPG + fatigue).
        """
        self._bgr_queues.add(q)

    def detach_bgr_queue(self, q: "Optional[queue.Queue]" = None) -> None:
        """Detach a specific queue, or all queues if *q* is None."""
        if q is None:
            self._bgr_queues.clear()
        else:
            self._bgr_queues.discard(q)

    def request_stop(self) -> None:
        self._stop = True

    @staticmethod
    def _fourcc_to_str(raw: int) -> str:
        return "".join(
            chr((raw >> (8 * i)) & 0xFF) for i in range(4)
        ).strip("\x00").upper() or "—"

    def _read_cap_info(self, cap) -> tuple[str, int, int, float]:
        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cc  = self._fourcc_to_str(int(cap.get(cv2.CAP_PROP_FOURCC)))
        return cc, w, h, fps

    @staticmethod
    def _frame_stats(frame: np.ndarray) -> tuple[float, float]:
        if frame.size == 0:
            return 0.0, 1.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        mean = float(np.mean(gray))
        near_black_ratio = float(np.count_nonzero(gray <= 2) / gray.size)
        return mean, near_black_ratio

    def _is_diagnostic_black_frame(self, frame: np.ndarray) -> bool:
        mean, near_black_ratio = self._frame_stats(frame)
        return mean < 3.0 or near_black_ratio > 0.98

    def _format_capture_context(self, codec: str, width: int, height: int, fps: float) -> str:
        fps_str = f"{fps:.1f}" if fps > 0 else "未知"
        return (
            f"相機 {self._camera_index}，後端 {self._backend}，"
            f"格式 {codec or '未知'} {width}×{height} @ {fps_str} fps"
        )

    @Slot()
    def run(self) -> None:
        if cv2 is None:
            self.failed.emit("OpenCV 未安裝")
            self.finished.emit()
            return

        from gui.camera_devices import configure_camera_capture, open_camera_capture

        self._stop = False
        cap = open_camera_capture(self._camera_index, backend=self._backend)
        if cap is None:
            self.failed.emit(f"無法開啟攝影機索引 {self._camera_index}")
            self.finished.emit()
            return

        # ── Apply resolution / FPS ────────────────────────────────────────
        # FFMPEG (and fallback backends): cap.set() is lightweight, apply freely.
        # MSMF: every cap.set() on an open capture triggers a full pipeline
        # rebuild (~1-2 s each), so skip all property setting for MSMF and let
        # the driver auto-negotiate its native format instead.
        if self._backend != "msmf":
            configure_camera_capture(
                cap,
                width=self._width,
                height=self._height,
                target_fps=self._target_fps,
                prefer_mjpg=True,
            )

        # Read what the backend negotiated and emit immediately.
        pre_codec, pre_w, pre_h, pre_fps = self._read_cap_info(cap)
        self.camera_info.emit(pre_codec, pre_w, pre_h, float(pre_fps))
        if pre_fps > 0:
            self.fps_ready.emit(float(pre_fps))

        # ── Wait for first real frame ─────────────────────────────────────
        deadline = time.perf_counter() + _FIRST_FRAME_TIMEOUT
        first_frame: np.ndarray | None = None
        while not self._stop and time.perf_counter() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                first_frame = frame
                break
            time.sleep(0.005)

        if first_frame is None:
            try:
                cap.release()
            except Exception:
                pass
            self.failed.emit(
                f"相機 {self._camera_index} 在 {_FIRST_FRAME_TIMEOUT:.0f} 秒內未送出影像。\n"
                "請確認相機未被其他程式佔用，Linux 可執行 scripts/diagnose_camera.py 檢查權限與 V4L2。"
            )
            self.finished.emit()
            return

        # Re-read after first frame — MSMF sometimes finalises FOURCC only then.
        post_codec, post_w, post_h, post_fps = self._read_cap_info(cap)
        if (post_codec, post_w, post_h) != (pre_codec, pre_w, pre_h):
            self.camera_info.emit(post_codec, post_w, post_h, float(post_fps))
        capture_context = self._format_capture_context(post_codec, post_w, post_h, float(post_fps))

        if self._is_diagnostic_black_frame(first_frame):
            mean, near_black_ratio = self._frame_stats(first_frame)
            self.diagnostic_ready.emit(
                f"[相機診斷] 首幀接近全黑（平均亮度 {mean:.1f}，黑像素 {near_black_ratio:.1%}）。"
                f"{capture_context}；若 FPS 仍正常，優先檢查鏡頭蓋、隱私快門、虛擬相機來源或光線。"
            )

        # ── Main capture loop ─────────────────────────────────────────────
        ts_window: deque[float] = deque(maxlen=_FPS_WINDOW_FRAMES)

        def _emit_frame(f: np.ndarray) -> None:
            rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            fh, fw = rgb.shape[:2]
            qimg = QImage(rgb.data, fw, fh, rgb.strides[0], QImage.Format.Format_RGB888)
            self.frame_ready.emit(qimg.copy())

        def _tick_fps() -> None:
            now = time.perf_counter()
            ts_window.append(now)
            if len(ts_window) >= 2:
                span = ts_window[-1] - ts_window[0]
                if span > 0.0:
                    self.fps_ready.emit((len(ts_window) - 1) / span)

        _emit_frame(first_frame)
        _tick_fps()
        last_good_read = time.perf_counter()
        dark_started_at = last_good_read if self._is_diagnostic_black_frame(first_frame) else None
        dark_warning_sent = dark_started_at is not None

        while not self._stop:
            ok, frame = cap.read()
            if not ok or frame is None:
                if time.perf_counter() - last_good_read >= _READ_FAILURE_TIMEOUT:
                    self.failed.emit(
                        f"{capture_context} 已連續 {_READ_FAILURE_TIMEOUT:.0f} 秒讀取失敗。\n"
                        "請確認相機未被其他程式佔用，USB/驅動是否穩定。"
                    )
                    break
                time.sleep(0.001)
                continue
            last_good_read = time.perf_counter()
            if self._is_diagnostic_black_frame(frame):
                if dark_started_at is None:
                    dark_started_at = last_good_read
                elif (
                    not dark_warning_sent
                    and last_good_read - dark_started_at >= _DARK_FRAME_WARN_SECONDS
                ):
                    mean, near_black_ratio = self._frame_stats(frame)
                    self.diagnostic_ready.emit(
                        f"[相機診斷] 連續 {_DARK_FRAME_WARN_SECONDS:.0f} 秒接近全黑"
                        f"（平均亮度 {mean:.1f}，黑像素 {near_black_ratio:.1%}）。"
                        "程式仍有收到影像，較可能是鏡頭遮擋、光線不足或虛擬相機無來源。"
                    )
                    dark_warning_sent = True
            else:
                dark_started_at = None
                dark_warning_sent = False
            _tick_fps()
            _emit_frame(frame)
            # Feed any attached BGR consumers (rPPG / fatigue workers) non-blocking.
            if self._bgr_queues:
                payload = (time.perf_counter(), frame.copy())
                for q in self._bgr_queues:
                    try:
                        q.put_nowait(payload)
                    except queue.Full:
                        pass

        try:
            cap.release()
        except Exception:
            pass
        self.finished.emit()
