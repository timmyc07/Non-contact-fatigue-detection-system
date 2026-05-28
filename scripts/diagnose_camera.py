"""Linux/Ubuntu camera diagnostics for GUI black-screen reports."""

from __future__ import annotations

import argparse
import glob
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.camera_devices import list_camera_devices, open_camera_capture  # noqa: E402


def _run(command: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
    except FileNotFoundError:
        return 127, f"找不到指令：{command[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"指令逾時：{' '.join(command)}"
    return proc.returncode, proc.stdout.strip()


def _print_command(command: list[str]) -> None:
    code, out = _run(command)
    print(f"$ {' '.join(command)}")
    if out:
        print(out)
    print(f"[exit={code}]")


def _frame_stats(frame: np.ndarray) -> tuple[float, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    mean = float(np.mean(gray))
    near_black_ratio = float(np.count_nonzero(gray <= 2) / gray.size)
    return mean, near_black_ratio


def _read_probe(index: int, backend: str, seconds: float) -> dict[str, Any]:
    cap = open_camera_capture(index, backend=backend)
    if cap is None:
        return {"opened": False, "frames": 0}

    try:
        deadline = time.perf_counter() + seconds
        frames = 0
        last_stats: tuple[float, float] | None = None
        shape: tuple[int, ...] | None = None
        while time.perf_counter() < deadline:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            frames += 1
            shape = tuple(frame.shape)
            last_stats = _frame_stats(frame)

        return {
            "opened": True,
            "frames": frames,
            "shape": shape,
            "stats": last_stats,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(cap.get(cv2.CAP_PROP_FPS)),
            "fourcc": int(cap.get(cv2.CAP_PROP_FOURCC)),
        }
    finally:
        cap.release()


def _fourcc_to_str(raw: int) -> str:
    return "".join(chr((raw >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00").upper() or "未知"


def main() -> int:
    parser = argparse.ArgumentParser(description="診斷 Linux/Ubuntu 相機與黑屏問題。")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index，預設 0。")
    parser.add_argument("--backend", default="v4l2", choices=("auto", "v4l2", "ffmpeg"), help="測試後端。")
    parser.add_argument("--seconds", type=float, default=3.0, help="讀幀測試秒數。")
    args = parser.parse_args()

    print("== 系統 ==")
    print(f"platform={platform.platform()}")
    print(f"python={sys.version.split()[0]}")
    print(f"opencv={cv2.__version__}")
    print(f"DISPLAY={os.environ.get('DISPLAY', '') or '未設定'}")
    print(f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '') or '未設定'}")
    print()

    print("== 裝置節點 ==")
    video_nodes = sorted(glob.glob("/dev/video*"))
    if video_nodes:
        for node in video_nodes:
            print(node)
    else:
        print("未找到 /dev/video*，偏向硬體未枚舉、驅動或容器/權限隔離問題。")
    print()

    print("== V4L2 資訊 ==")
    _print_command(["v4l2-ctl", "--list-devices"])
    if video_nodes:
        _print_command(["v4l2-ctl", "--all", "-d", f"/dev/video{args.camera}"])
    print()

    print("== 權限與占用 ==")
    _print_command(["groups"])
    if video_nodes:
        node = f"/dev/video{args.camera}"
        _print_command(["ls", "-l", node])
        _print_command(["fuser", node])
    print()

    print("== 專案相機列舉 ==")
    probe_count = max(args.camera + 1, len(video_nodes), 1)
    devices = list_camera_devices(max_index=probe_count, warmup_read=True)
    if devices:
        for index, label in devices:
            print(f"[{index}] {label}")
    else:
        print("OpenCV 未列舉到可讀取相機。")
    print()

    print("== OpenCV 讀幀測試 ==")
    result = _read_probe(args.camera, args.backend, max(0.5, args.seconds))
    if not result["opened"]:
        print(f"無法開啟 camera={args.camera} backend={args.backend}。")
        print("判斷：偏向權限、裝置忙碌、後端不相容或硬體/驅動問題。")
        return 2

    print(
        f"opened=True frames={result['frames']} "
        f"format={_fourcc_to_str(result['fourcc'])} "
        f"{result['width']}x{result['height']} fps={result['fps']:.1f}"
    )
    if result["frames"] <= 0:
        print("判斷：相機可開啟但沒有送出影像，常見於裝置被占用或驅動卡住。")
        return 3

    stats = result["stats"]
    if stats is not None:
        mean, near_black_ratio = stats
        print(f"last_frame_shape={result['shape']} mean_brightness={mean:.1f} near_black={near_black_ratio:.1%}")
        if mean < 3.0 or near_black_ratio > 0.98:
            print("判斷：程式有收到影像但畫面接近全黑，優先檢查鏡頭蓋、隱私快門、光線或虛擬相機來源。")
            return 4

    print("判斷：OpenCV 可正常讀取非黑畫面；若 GUI 仍黑屏，較可能是 GUI 顯示/後端協商問題。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
