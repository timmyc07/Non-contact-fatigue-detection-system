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
from ctypes import wintypes
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


def _expand_process_tree(root_pid: int, parent_by_pid: dict[int, int]) -> list[int]:
    pids = [int(root_pid)]
    seen = {int(root_pid)}
    index = 0
    while index < len(pids):
        parent = pids[index]
        index += 1
        for pid, parent_pid in parent_by_pid.items():
            if parent_pid == parent and pid not in seen:
                seen.add(pid)
                pids.append(pid)
    return pids


def _windows_process_parent_map() -> dict[int, int]:
    if not sys.platform.startswith("win"):
        return {}

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    snapshot_value = getattr(snapshot, "value", snapshot)
    if not snapshot_value or snapshot_value == invalid_handle:
        raise OSError("CreateToolhelp32Snapshot failed")
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise OSError("Process32FirstW failed")
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _process_tree_pids(root_pid: int) -> list[int]:
    if sys.platform.startswith("win"):
        return _expand_process_tree(root_pid, _windows_process_parent_map())
    return [int(root_pid)]


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
    environment["NCFD_BACKEND_PORT"] = str(port)
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

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None
        try:
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    return None


def _process_tree_rss_bytes(root_pid: int) -> tuple[list[int], int | None]:
    pids = _process_tree_pids(root_pid)
    values = [_rss_bytes(pid) for pid in pids]
    measured = [value for value in values if value is not None]
    return pids, sum(measured) if measured else None


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
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Loopback engine port (default: 5000)")
    parser.add_argument("--synthetic-only", action="store_true", help="Run only the process-free preview benchmark")
    parser.add_argument("--output", type=Path, default=None, help="Also write the JSON result to this path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    samples = max(1, args.samples)
    warmup = max(0, args.warmup)
    port = int(args.port)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    result: dict[str, Any] = {
        "schema_version": 1, "python": sys.version.split()[0], "platform": sys.platform,
        "noise_control": {"warmup_discarded": warmup, "samples": samples, "loopback_only": True},
    }
    process: subprocess.Popen[bytes] | None = None
    try:
        if not args.synthetic_only:
            process, startup_ms = _start_engine(
                host=DEFAULT_HOST, port=port, timeout=max(1.0, args.startup_timeout)
            )
            process_tree_pids, rss = _process_tree_rss_bytes(process.pid)
            command_result = _benchmark_commands(
                host=DEFAULT_HOST, port=port, warmup=warmup, samples=samples
            )
            result["engine"] = {
                "pid": process.pid, "startup_to_api_ready_ms": round(startup_ms, 3),
                "process_tree_pids": process_tree_pids,
                "rss_bytes_at_ready": rss,
                "rss_mib_at_ready": round(rss / (1024 * 1024), 3) if rss is not None else None,
                "command": command_result,
            }
        result["preview"] = _benchmark_synthetic_preview(warmup=warmup, samples=samples)
    finally:
        if process is not None:
            _stop_engine(process, host=DEFAULT_HOST, port=port)

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
