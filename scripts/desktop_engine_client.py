"""Shared localhost client and source-engine lifecycle helpers for desktop smoke tools."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DESKTOP_API_VERSION = 2


def request_json(
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


def control_state(*, host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    payload = request_json("GET", "/api/control/state", host=host, port=port, timeout=timeout)
    data = payload.get("data")
    if not payload.get("success") or not isinstance(data, dict):
        raise RuntimeError(f"Invalid control state: {payload}")
    if data.get("desktop_api_version") != DESKTOP_API_VERSION:
        raise RuntimeError(f"Unexpected desktop API version: {data.get('desktop_api_version')}")
    return data


def port_in_use(*, host: str, port: int) -> bool:
    try:
        connection = socket.create_connection((host, port), timeout=0.3)
        connection.close()
        return True
    except OSError:
        return False


def start_source_engine(
    *, host: str, port: int, timeout: float
) -> tuple[subprocess.Popen[bytes], float]:
    if port_in_use(host=host, port=port):
        raise RuntimeError(f"A compatible engine already owns {host}:{port}; stop it first")
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
            raise RuntimeError(f"Engine exited before API readiness: exit={process.returncode}")
        try:
            control_state(host=host, port=port, timeout=0.5)
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


def stop_engine(process: subprocess.Popen[bytes], *, host: str, port: int) -> None:
    try:
        request_json(
            "POST",
            "/api/control/command",
            host=host,
            port=port,
            body={"command": "app.shutdown", "args": {}},
            timeout=2.0,
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
