"""Repeatable desktop engine and preview transport microbenchmark.

The default run starts ``main.py --engine`` and measures API readiness, RSS,
and read-only ``state.get`` command latency. Preview measurements use a fixed
synthetic image, so they cover JPEG encoding, payload size, and Socket.IO
server dispatch without requiring a camera.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import gc
import http.client
import json
import os
import statistics
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
API_VERSION = 2


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    ordered = sorted(float(value) for value in values)

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
        return ordered[index]

    return {
        "min": round(ordered[0], 3),
        "p50": round(percentile(0.50), 3),
        "p95": round(percentile(0.95), 3),
        "max": round(ordered[-1], 3),
        "mean": round(statistics.fmean(ordered), 3),
    }


def _request_json(
    method: str,
    path: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    body: dict[str, Any] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if encoded is not None else {}
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if not 200 <= response.status < 300:
            raise RuntimeError(f"HTTP {response.status}: {payload}")
        if not isinstance(payload, dict):
            raise RuntimeError("API response is not an object")
        return payload
    finally:
        connection.close()


def _control_state(*, host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    payload = _request_json("GET", "/api/control/state", host=host, port=port, timeout=timeout)
    data = payload.get("data")
    if not payload.get("success") or not isinstance(data, dict):
        raise RuntimeError(f"Invalid control state: {payload}")
    if data.get("desktop_api_version") != API_VERSION:
        raise RuntimeError(f"Unexpected desktop API version: {data.get('desktop_api_version')}")
    return data


def _port_in_use(*, host: str, port: int) -> bool:
    try:
        connection = socket.create_connection((host, port), timeout=0.3)
        connection.close()
        return True
    except OSError:
        return False


def _start_engine(*, host: str, port: int, timeout: float) -> tuple[subprocess.Popen[bytes], float]:
    if _port_in_use(host=host, port=port):
        raise RuntimeError(
            f"A compatible engine already owns {host}:{port}; stop it before benchmarking"
        )
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--engine"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = started + timeout
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Engine exited before the API became ready: exit={process.returncode}"
            )
        try:
            _control_state(host=host, port=port, timeout=0.5)
            return process, (time.perf_counter() - started) * 1000.0
        except Exception:
            time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)
    raise TimeoutError(f"Engine did not become ready within {timeout:.1f}s")


def _stop_engine(process: subprocess.Popen[bytes], *, host: str, port: int) -> None:
    try:
        _request_json(
            "POST", "/api/control/command", host=host, port=port,
            body={"command": "app.shutdown", "args": {}}, timeout=2.0,
        )
    except Exception:
        pass
    try:
        process.wait(timeout=8.0)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)


def _rss_bytes(pid: int) -> int | None:
    if sys.platform.startswith("linux"):
        try:
            for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None
    if sys.platform.startswith("win"):
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None
        try:
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    return None


def _benchmark_commands(*, host: str, port: int, warmup: int, samples: int) -> dict[str, Any]:
    body = {"command": "state.get", "args": {}}
    for _ in range(warmup):
        _request_json("POST", "/api/control/command", host=host, port=port, body=body)
    latencies: list[float] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        payload = _request_json("POST", "/api/control/command", host=host, port=port, body=body)
        if not payload.get("success"):
            raise RuntimeError(f"state.get failed: {payload}")
        latencies.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return {"samples": samples, "latency_ms": _distribution(latencies)}


def _synthetic_image(width: int = 640, height: int = 360):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    colors = (QColor(32, 40, 48), QColor(118, 83, 180), QColor(224, 220, 236))
    cell = 24
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            painter.fillRect(QRect(x, y, cell, cell), colors[(x // cell + y // cell) % len(colors)])
    painter.end()
    return image


def _benchmark_synthetic_preview(*, warmup: int, samples: int) -> dict[str, Any]:
    from gui.main_window import MainWindow
    from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread

    image = _synthetic_image()
    for _ in range(warmup):
        MainWindow._encode_frame_jpeg(image, max_width=640, quality=70)
    gc.collect()
    encode_latencies: list[float] = []
    payloads: list[str] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        payload = MainWindow._encode_frame_jpeg(image, max_width=640, quality=70)
        encode_latencies.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if payload is None:
            raise RuntimeError("synthetic preview JPEG encode failed")
        payloads.append(payload)

    with tempfile.TemporaryDirectory(prefix="ncfd-preview-bench-") as temp_dir:
        server = WebServerThread(MetricsBuffer(), PlaybackManager(Path(temp_dir)), host="127.0.0.1")
        client = server.socketio.test_client(server.app)
        client.get_received()
        for _ in range(warmup):
            server.broadcast_frame(payloads[0])
            client.get_received()
        started = time.perf_counter_ns()
        for payload in payloads:
            server.broadcast_frame(payload)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000_000.0
        events = client.get_received()
        delivered = sum(1 for event in events if event.get("name") == "frame_update")
        client.disconnect()

    payload_bytes = len(payloads[0].encode("ascii"))
    jpeg_bytes = len(base64.b64decode(payloads[0], validate=True))
    return {
        "kind": "synthetic_in_process", "samples": samples,
        "dimensions": [image.width(), image.height()],
        "jpeg_bytes": jpeg_bytes, "base64_bytes": payload_bytes,
        "encode_latency_ms": _distribution(encode_latencies),
        "dispatch_delivered": delivered,
        "dispatch_frames_per_second": round(samples / elapsed, 3) if elapsed > 0 else 0.0,
        "limitations": "Excludes camera, network, Tauri WebView decode, and Flutter rendering",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the desktop engine and preview transport")
    parser.add_argument("--samples", type=int, default=30, help="Measured sample count (default: 30)")
    parser.add_argument("--warmup", type=int, default=5, help="Discarded warmup count (default: 5)")
    parser.add_argument("--startup-timeout", type=float, default=45.0, help="Engine startup timeout in seconds")
    parser.add_argument("--synthetic-only", action="store_true", help="Run only the process-free preview benchmark")
    parser.add_argument("--output", type=Path, default=None, help="Also write the JSON result to this path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    samples = max(1, args.samples)
    warmup = max(0, args.warmup)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    result: dict[str, Any] = {
        "schema_version": 1, "python": sys.version.split()[0], "platform": sys.platform,
        "noise_control": {"warmup_discarded": warmup, "samples": samples, "loopback_only": True},
    }
    process: subprocess.Popen[bytes] | None = None
    try:
        if not args.synthetic_only:
            process, startup_ms = _start_engine(
                host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=max(1.0, args.startup_timeout)
            )
            rss = _rss_bytes(process.pid)
            result["engine"] = {
                "pid": process.pid, "startup_to_api_ready_ms": round(startup_ms, 3),
                "rss_bytes_at_ready": rss,
                "rss_mib_at_ready": round(rss / (1024 * 1024), 3) if rss is not None else None,
                "command": _benchmark_commands(
                    host=DEFAULT_HOST, port=DEFAULT_PORT, warmup=warmup, samples=samples
                ),
            }
        result["preview"] = _benchmark_synthetic_preview(warmup=warmup, samples=samples)
    finally:
        if process is not None:
            _stop_engine(process, host=DEFAULT_HOST, port=DEFAULT_PORT)

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
