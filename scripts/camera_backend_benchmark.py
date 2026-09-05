"""比較本機相機 backend 的實際幀率、抖動與 CPU 成本。

此工具只做相機輸入量測，不啟動 MediaPipe、不改設定，也不會寫入錄影檔。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import cv2

from gui.camera_devices import configure_camera_capture, open_camera_capture


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))]


def _measure_backend(
    camera: int, backend: str, seconds: float, width: int, height: int, target_fps: float
) -> dict[str, Any]:
    cap = open_camera_capture(camera, backend=backend)
    if cap is None:
        return {"backend": backend, "opened": False, "reason": "open_failed"}
    try:
        configure_camera_capture(
            cap, width=width, height=height, target_fps=target_fps, prefer_mjpg=False
        )
        for _ in range(10):
            cap.read()
        timestamps: list[float] = []
        read_attempts = 0
        read_failures = 0
        cpu_start = time.process_time()
        wall_start = time.perf_counter()
        deadline = wall_start + seconds
        while time.perf_counter() < deadline:
            read_attempts += 1
            ok, frame = cap.read()
            if ok and frame is not None:
                timestamps.append(time.perf_counter())
            else:
                read_failures += 1
        wall_elapsed = max(time.perf_counter() - wall_start, 1e-9)
        intervals = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
        measured_fps = (
            (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
            if len(timestamps) >= 2
            else 0.0
        )
        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return {
            "backend": backend,
            "opened": True,
            "frames": len(timestamps),
            "read_attempts": read_attempts,
            "read_failures": read_failures,
            "read_success_ratio": round(
                len(timestamps) / read_attempts if read_attempts else 0.0, 4
            ),
            "measured_fps": round(measured_fps, 3),
            "megapixels_per_second": round(
                actual_width * actual_height * measured_fps / 1_000_000.0, 3
            ),
            "effective_read_fps": round(len(timestamps) / wall_elapsed, 3),
            "cpu_percent": round((time.process_time() - cpu_start) / wall_elapsed * 100.0, 2),
            "interval_ms_p50": round(_percentile([v * 1000.0 for v in intervals], 0.50), 3),
            "interval_ms_p95": round(_percentile([v * 1000.0 for v in intervals], 0.95), 3),
            "reported_fps": round(float(cap.get(cv2.CAP_PROP_FPS) or 0.0), 3),
            "backend_id": int(cap.get(cv2.CAP_PROP_BACKEND) or 0),
            "width": actual_width,
            "height": actual_height,
        }
    finally:
        cap.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "--backends", nargs="+", default=["ffmpeg", "auto", "avfoundation", "dshow", "msmf", "v4l2"]
    )
    args = parser.parse_args(argv)
    result = {
        "schema_version": 1,
        "platform": sys.platform,
        "request": {
            "camera": args.camera,
            "seconds": args.seconds,
            "width": args.width,
            "height": args.height,
            "fps": args.fps,
        },
        "results": [
            _measure_backend(
                args.camera,
                backend,
                max(0.5, args.seconds),
                max(160, args.width),
                max(120, args.height),
                max(1.0, args.fps),
            )
            for backend in args.backends
        ],
        "interpretation": "以 measured_fps、interval_ms_p95 與 cpu_percent 比較；backend_id 可用來確認 ffmpeg 邏輯設定是否實際落到原生 API。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
