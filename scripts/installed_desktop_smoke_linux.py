"""Smoke-test a bundled Linux AppImage and its packaged Python engine."""

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
    # 允許以 `python scripts/installed_desktop_smoke_linux.py` 直接執行。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.desktop_engine_client import control_state, port_in_use, request_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APPIMAGE_DIR = ROOT / "src-tauri" / "target" / "release" / "bundle" / "appimage"
LINUX_DATA_DIR = Path.home() / ".local" / "share" / "tw.fatigue-monitor.desktop"


def _resolve_appimage(explicit: Path | None) -> Path:
    if explicit is not None:
        artifact = explicit.resolve()
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        return artifact
    artifacts = sorted(DEFAULT_APPIMAGE_DIR.glob("*.AppImage"))
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected one AppImage under {DEFAULT_APPIMAGE_DIR}, found {artifacts}"
        )
    return artifacts[0]


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


def run_smoke(*, artifact: Path, port: int, timeout: float) -> dict[str, object]:
    if sys.platform != "linux":
        raise RuntimeError("installed Linux desktop smoke is Linux-only")
    if port_in_use(host="127.0.0.1", port=port):
        raise RuntimeError(f"Port 127.0.0.1:{port} is already in use")

    environment = os.environ.copy()
    environment["NCFD_BACKEND_PORT"] = str(port)
    # Supports runners without FUSE while preserving the AppImage runtime.
    environment.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    process = subprocess.Popen(
        [str(artifact)],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.perf_counter()
    state: dict[str, object] | None = None
    try:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"AppImage exited early: {process.returncode}")
            try:
                state = control_state(host="127.0.0.1", port=port, timeout=0.5)
                break
            except Exception:
                time.sleep(0.1)
        if state is None:
            raise TimeoutError(f"Packaged engine did not become ready on port {port}")

        cameras = state.get("cameras")
        if not isinstance(cameras, list) or not cameras:
            raise RuntimeError("packaged desktop API reported no camera")
        camera = cameras[0]
        if not isinstance(camera, dict) or not isinstance(camera.get("index"), int):
            raise RuntimeError(f"packaged desktop API returned invalid camera: {camera}")
        selected = _desktop_command(port, "camera.select", {"index": camera["index"]})
        configured = _desktop_command(
            port,
            "analysis.configure",
            {"behavior_enabled": False, "rppg_enabled": False},
        )
        started_pipeline = _desktop_command(port, "pipeline.set", {"enabled": True})
        metrics: dict[str, object] | None = None
        metrics_deadline = time.monotonic() + timeout
        while time.monotonic() < metrics_deadline:
            candidate = request_json(
                "GET", "/api/metrics", host="127.0.0.1", port=port, timeout=2.0
            ).get("metrics")
            if _camera_metrics_ready(candidate):
                metrics = candidate
                break
            time.sleep(0.2)
        if metrics is None:
            raise TimeoutError("packaged camera pipeline produced no live metrics")
        stopped_pipeline = _desktop_command(port, "pipeline.set", {"enabled": False})
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
        if not LINUX_DATA_DIR.is_dir():
            raise RuntimeError(f"packaged data directory was not created: {LINUX_DATA_DIR}")

        shutdown = request_json(
            "POST",
            "/api/control/command",
            host="127.0.0.1",
            port=port,
            body={"command": "app.shutdown", "args": {}},
        )
        if not shutdown.get("success"):
            raise RuntimeError(f"engine rejected app.shutdown: {shutdown}")
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            raise TimeoutError("AppImage shell did not exit after app.shutdown")
        while port_in_use(host="127.0.0.1", port=port) and time.monotonic() < deadline:
            time.sleep(0.1)
        if port_in_use(host="127.0.0.1", port=port):
            raise TimeoutError("engine port remained open after AppImage shutdown")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)

    return {
        "artifact": str(artifact),
        "desktop_api_version": state["desktop_api_version"],
        "camera_count": len(state.get("cameras", [])),
        "camera_pipeline": camera_checks,
        "data_dir": str(LINUX_DATA_DIR),
        "data_dir_exists": LINUX_DATA_DIR.is_dir(),
        "engine_shutdown": True,
        "shell_exit_code": process.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    result = run_smoke(
        artifact=_resolve_appimage(args.artifact),
        port=args.port,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
