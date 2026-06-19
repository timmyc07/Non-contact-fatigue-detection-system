"""Watch heart-rate HTTP receiver for rPPG calibration sessions."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class WatchSample:
    __slots__ = ("received_at", "bpm", "ts_ms", "interval_ms")

    def __init__(self, received_at: float, bpm: int, ts_ms: int, interval_ms: int) -> None:
        self.received_at = received_at
        self.bpm = int(bpm)
        self.ts_ms = int(ts_ms)
        self.interval_ms = int(interval_ms)


class WatchHrHub:
    """Thread-safe store for watch POST samples."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[WatchSample] = []
        self._last: WatchSample | None = None
        self.total_received: int = 0

    def add(self, sample: WatchSample) -> None:
        with self._lock:
            self._samples.append(sample)
            self._last = sample
            self.total_received += 1

    def latest(self) -> WatchSample | None:
        with self._lock:
            return self._last

    def snapshot(self) -> list[WatchSample]:
        with self._lock:
            return list(self._samples)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._last = None
            self.total_received = 0

    def is_connected(self, stale_multiplier: float = 3.0) -> bool:
        last = self.latest()
        if last is None:
            return False
        interval_sec = max(0.5, last.interval_ms / 1000.0)
        return (time.time() - last.received_at) <= interval_sec * stale_multiplier


def _normalize_hr_path(path: str) -> str:
    normalized = (path or "/").split("?", 1)[0].strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/") or "/"


def _make_handler(hub: WatchHrHub, on_received: Any | None = None, on_request: Any | None = None):
    class Handler(BaseHTTPRequestHandler):
        def _emit_request(self, status_code: int) -> None:
            if on_request is not None:
                try:
                    on_request(self.client_address[0], status_code, self.path)
                except Exception:
                    pass

        def do_GET(self) -> None:
            path = _normalize_hr_path(self.path)
            if path in ("/hr", "/"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok")
                self._emit_request(200)
                return
            self.send_error(404)
            self._emit_request(404)

        def do_POST(self) -> None:
            if _normalize_hr_path(self.path) != "/hr":
                self.send_error(404)
                self._emit_request(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                bpm = int(data["bpm"])
                ts_ms = int(data.get("ts", 0) or 0)
                interval_ms = int(data.get("interval_ms", 1000) or 1000)
            except Exception:
                self.send_error(400)
                self._emit_request(400)
                return
            hub.add(WatchSample(time.time(), bpm, ts_ms, interval_ms))
            if on_received is not None:
                try:
                    on_received(bpm)
                except Exception:
                    pass
            self.send_response(200)
            self.end_headers()
            self._emit_request(200)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


class WatchHrHttpServer:
    """Background HTTP server for ``POST /hr`` from the watch app."""

    def __init__(
        self,
        hub: WatchHrHub,
        host: str = "0.0.0.0",
        port: int = 8080,
        on_received: Any | None = None,
        on_request: Any | None = None,
    ) -> None:
        self.hub = hub
        self.host = host
        self.port = int(port)
        self._on_received = on_received
        self._on_request = on_request
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.last_error: str = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self.running:
            return
        self.last_error = ""
        handler = _make_handler(self.hub, self._on_received, self._on_request)
        self._server = HTTPServer((self.host, self.port), handler)
        self._server.allow_reuse_address = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
