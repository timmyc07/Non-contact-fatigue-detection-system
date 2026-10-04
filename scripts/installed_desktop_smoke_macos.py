"""Smoke-test the bundled macOS app and its packaged Python engine."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from scripts.desktop_engine_client import control_state, port_in_use, request_json
except ModuleNotFoundError:
    # 允許以 `python scripts/installed_desktop_smoke_macos.py` 直接執行。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.desktop_engine_client import control_state, port_in_use, request_json


ROOT = Path(__file__).resolve().parents[1]
APP_BUNDLE_IDENTIFIER = "tw.fatigue-monitor.desktop"
MACOS_DATA_DIR = Path.home() / "Library" / "Application Support" / APP_BUNDLE_IDENTIFIER
DEFAULT_APP = (
    ROOT
    / "src-tauri"
    / "target"
    / "release"
    / "bundle"
    / "macos"
    / "疲勞監測操作台.app"
)


def _request_shell_quit() -> None:
    subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application id "{APP_BUNDLE_IDENTIFIER}" to quit',
        ],
        check=True,
        timeout=10.0,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_for_shell_exit(process: subprocess.Popen[bytes], timeout: float) -> int:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"macOS shell did not exit within {timeout:.1f}s after quit request"
        ) from exc


def _desktop_command(port: int, command: str, args: dict[str, object]) -> dict[str, object]:
    response = request_json(
        "POST",
        "/api/control/command",
        host="127.0.0.1",
        port=port,
        body={"command": command, "args": args},
        timeout=5.0,
    )
    if not response.get("success"):
        raise RuntimeError(f"desktop command failed ({command}): {response}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"desktop command returned invalid data ({command}): {response}")
    return data


def _camera_metrics_ready(metrics: object) -> bool:
    if not isinstance(metrics, dict):
        return False
    try:
        return (
            bool(metrics.get("camera_running"))
            and float(metrics.get("fps", 0.0)) > 0.0
            and int(metrics.get("camera_width", 0)) > 0
            and int(metrics.get("camera_height", 0)) > 0
            and metrics.get("frame_source") == "camera"
        )
    except (TypeError, ValueError):
        return False


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

    environment = os.environ.copy()
    environment["NCFD_BACKEND_PORT"] = str(args.port)
    process = subprocess.Popen(
        [str(executable)],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.perf_counter()
    ready_elapsed_ms: float | None = None
    state: dict[str, object] | None = None
    camera_checks: dict[str, object] | None = None
    shell_exit_code: int | None = None
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

        cameras = state.get("cameras")
        if not isinstance(cameras, list) or not cameras:
            raise RuntimeError("packaged desktop API reported no camera")
        camera = cameras[0]
        if not isinstance(camera, dict) or not isinstance(camera.get("index"), int):
            raise RuntimeError(f"packaged desktop API returned invalid camera: {camera}")
        selected = _desktop_command(
            args.port,
            "camera.select",
            {"index": camera["index"]},
        )
        configured = _desktop_command(
            args.port,
            "analysis.configure",
            {"behavior_enabled": False, "rppg_enabled": False},
        )
        started_pipeline = _desktop_command(
            args.port,
            "pipeline.set",
            {"enabled": True},
        )
        metrics: dict[str, object] | None = None
        metrics_deadline = time.perf_counter() + args.timeout
        while time.perf_counter() < metrics_deadline:
            payload = request_json(
                "GET",
                "/api/metrics",
                host="127.0.0.1",
                port=args.port,
                timeout=2.0,
            )
            candidate = payload.get("metrics")
            if _camera_metrics_ready(candidate):
                metrics = candidate
                break
            time.sleep(0.2)
        if metrics is None:
            raise TimeoutError("packaged camera pipeline produced no live metrics")
        stopped_pipeline = _desktop_command(
            args.port,
            "pipeline.set",
            {"enabled": False},
        )
        camera_checks = {
            "selected_index": selected.get("selected_camera_index"),
            "analysis_configured": (
                configured.get("behavior_enabled") is False
                and configured.get("rppg_enabled") is False
            ),
            "pipeline_started": started_pipeline.get("pipeline_running") is True,
            "camera_metrics_ready": _camera_metrics_ready(metrics),
            "pipeline_stopped": stopped_pipeline.get("pipeline_running") is False,
            "frame_source": metrics.get("frame_source"),
            "width": metrics.get("camera_width"),
            "height": metrics.get("camera_height"),
            "fps": metrics.get("fps"),
        }
        if not MACOS_DATA_DIR.is_dir():
            raise RuntimeError(f"packaged data directory was not created: {MACOS_DATA_DIR}")

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
        _request_shell_quit()
        shell_exit_code = _wait_for_shell_exit(process, args.timeout)
        if shell_exit_code != 0:
            raise RuntimeError(f"macOS shell exited with code {shell_exit_code}")
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
                "camera_pipeline": camera_checks,
                "data_dir": str(MACOS_DATA_DIR),
                "data_dir_exists": MACOS_DATA_DIR.is_dir(),
                "ready_ms": round(ready_elapsed_ms, 1) if ready_elapsed_ms is not None else None,
                "engine_shutdown": True,
                "shell_exit_code": shell_exit_code,
                "shell_exited": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
