"""Smoke-test the bundled macOS app and its packaged Python engine."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from scripts.desktop_engine_client import control_state, port_in_use, request_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP = (
    ROOT
    / "src-tauri"
    / "target"
    / "release"
    / "bundle"
    / "macos"
    / "疲勞監測操作台.app"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("This smoke test requires macOS")
    executable = args.app / "Contents" / "MacOS" / "fatigue-monitor-shell"
    engine = args.app / "Contents" / "Resources" / "engine" / "ncfd-engine"
    if not executable.is_file() or not engine.is_file():
        raise FileNotFoundError(f"Incomplete macOS app bundle: {args.app}")
    if port_in_use(host="127.0.0.1", port=args.port):
        raise RuntimeError(f"Port 127.0.0.1:{args.port} is already in use")

    process = subprocess.Popen(
        [str(executable)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.perf_counter()
    ready_elapsed_ms: float | None = None
    state: dict[str, object] | None = None
    try:
        deadline = started + args.timeout
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"macOS shell exited early: {process.returncode}")
            try:
                state = control_state(host="127.0.0.1", port=args.port, timeout=0.5)
                ready_elapsed_ms = (time.perf_counter() - started) * 1000.0
                break
            except Exception:
                time.sleep(0.1)
        if state is None:
            raise TimeoutError(f"Packaged engine did not become ready on port {args.port}")

        request_json(
            "POST",
            "/api/control/command",
            host="127.0.0.1",
            port=args.port,
            body={"command": "app.shutdown", "args": {}},
        )
        shutdown_deadline = time.perf_counter() + 10.0
        while port_in_use(host="127.0.0.1", port=args.port):
            if time.perf_counter() >= shutdown_deadline:
                raise TimeoutError("Packaged engine did not release its control port")
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)

    print(
        json.dumps(
            {
                "app": str(args.app),
                "desktop_api_version": state.get("desktop_api_version") if state else None,
                "camera_count": len(state.get("cameras", [])) if state else 0,
                "ready_ms": round(ready_elapsed_ms, 1) if ready_elapsed_ms is not None else None,
                "engine_shutdown": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
