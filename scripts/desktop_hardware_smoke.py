"""Exercise the source engine camera path through desktop API v2.

This smoke verifies the Tauri-facing engine boundary, camera selection, frame
acquisition, metrics publication, worker-mode lifecycle, and clean pipeline
shutdown without changing rPPG or fatigue numeric behavior.  The default
``raw`` mode disables both analysis pillars; ``fatigue``, ``rppg``, and
``combined`` are available for live-worker lifecycle checks.  BLE hardware
remains covered by ``scripts.hr_belt_monitor`` so the protocol implementation
is not duplicated here.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scripts.desktop_engine_client import (
        control_state,
        request_json,
        start_source_engine,
        stop_engine,
    )
except ModuleNotFoundError:
    # 允許以 `python scripts/desktop_hardware_smoke.py` 直接執行。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.desktop_engine_client import (
        control_state,
        request_json,
        start_source_engine,
        stop_engine,
    )

ANALYSIS_MODES = ("raw", "fatigue", "rppg", "combined")


def _command(*, host: str, port: int, command: str, args: dict[str, Any]) -> dict[str, Any]:
    payload = request_json(
        "POST",
        "/api/control/command",
        host=host,
        port=port,
        body={"command": command, "args": args},
        timeout=5.0,
    )
    if not payload.get("success"):
        raise RuntimeError(f"desktop command failed ({command}): {payload}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"desktop command returned invalid data ({command}): {payload}")
    return data


def _choose_camera(cameras: list[dict[str, Any]], requested: int | None) -> dict[str, Any]:
    if not cameras:
        raise RuntimeError(
            "desktop API reported no camera; connect a camera or verify the camera driver"
        )
    if requested is None:
        return cameras[0]
    for camera in cameras:
        if camera.get("index") == requested:
            return camera
    available = ", ".join(str(camera.get("index")) for camera in cameras)
    raise RuntimeError(f"camera index {requested} is unavailable (available: {available})")


def _metrics_ready(
    metrics: dict[str, Any], *, expected_frame_source: str | None = None
) -> bool:
    try:
        fps = float(metrics.get("fps", 0.0))
        width = int(metrics.get("camera_width", 0))
        height = int(metrics.get("camera_height", 0))
    except (TypeError, ValueError):
        return False
    if not (bool(metrics.get("camera_running")) and fps > 0.0 and width > 0 and height > 0):
        return False
    return expected_frame_source is None or metrics.get("frame_source") == expected_frame_source


def _analysis_flags(mode: str) -> tuple[bool, bool]:
    if mode == "raw":
        return False, False
    if mode == "fatigue":
        return True, False
    if mode == "rppg":
        return False, True
    if mode == "combined":
        return True, True
    raise ValueError(f"unsupported analysis mode: {mode}")


def _expected_frame_source(mode: str) -> str:
    if mode not in ANALYSIS_MODES:
        raise ValueError(f"unsupported analysis mode: {mode}")
    return "camera" if mode == "raw" else mode


def run_smoke(
    *,
    host: str = "127.0.0.1",
    port: int = 5012,
    camera_index: int | None = None,
    analysis_mode: str = "raw",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Run a non-persistent camera acquisition smoke through desktop API v2."""

    behavior_enabled, rppg_enabled = _analysis_flags(analysis_mode)
    expected_frame_source = _expected_frame_source(analysis_mode)
    process, ready_ms = start_source_engine(host=host, port=port, timeout=timeout)
    try:
        state = control_state(host=host, port=port)
        camera = _choose_camera(state.get("cameras", []), camera_index)
        selected = _command(
            host=host,
            port=port,
            command="camera.select",
            args={"index": camera["index"]},
        )
        _command(
            host=host,
            port=port,
            command="analysis.configure",
            args={
                "behavior_enabled": behavior_enabled,
                "rppg_enabled": rppg_enabled,
            },
        )
        running = _command(
            host=host,
            port=port,
            command="pipeline.set",
            args={"enabled": True},
        )

        deadline = time.monotonic() + timeout
        metrics: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            payload = request_json(
                "GET",
                "/api/metrics",
                host=host,
                port=port,
                timeout=2.0,
            )
            candidate = payload.get("metrics")
            if isinstance(candidate, dict) and _metrics_ready(
                candidate, expected_frame_source=expected_frame_source
            ):
                metrics = candidate
                break
            time.sleep(0.2)
        if metrics is None:
            raise TimeoutError("camera pipeline produced no live metrics before timeout")

        stopped = _command(
            host=host,
            port=port,
            command="pipeline.set",
            args={"enabled": False},
        )
        return {
            "schema_version": 1,
            "kind": "desktop_hardware_smoke",
            "platform": sys.platform,
            "api_ready_ms": round(ready_ms, 3),
            "analysis": {
                "mode": analysis_mode,
                "behavior_enabled": behavior_enabled,
                "rppg_enabled": rppg_enabled,
            },
            "camera": {
                "requested_index": camera_index,
                "index": camera.get("index"),
                "label": camera.get("label", ""),
                "selected_index": selected.get("selected_camera_index"),
                "codec": metrics.get("camera_codec", ""),
                "width": metrics.get("camera_width", 0),
                "height": metrics.get("camera_height", 0),
                "fps": metrics.get("fps", 0.0),
                "frame_source": metrics.get("frame_source", ""),
            },
            "checks": {
                "desktop_api_version": state.get("desktop_api_version"),
                "pipeline_started": bool(running.get("pipeline_running")),
                "camera_metrics_ready": _metrics_ready(metrics),
                "expected_frame_source": expected_frame_source,
                "frame_source_matches_mode": metrics.get("frame_source") == expected_frame_source,
                "pipeline_stopped": stopped.get("pipeline_running") is False,
                "analysis_configured": (
                    running.get("behavior_enabled") is behavior_enabled
                    and running.get("rppg_enabled") is rppg_enabled
                ),
            },
            "limitations": [
                "This smoke does not evaluate rPPG or fatigue numeric values.",
                "BLE hardware is verified separately with scripts.hr_belt_monitor.",
                "The smoke uses the source engine and does not render the Tauri WebView.",
            ],
        }
    finally:
        stop_engine(process, host=host, port=port)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-index", type=int, default=None)
    parser.add_argument("--analysis-mode", choices=ANALYSIS_MODES, default="raw")
    parser.add_argument("--port", type=int, default=5012)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_smoke(
            port=args.port,
            camera_index=args.camera_index,
            analysis_mode=args.analysis_mode,
            timeout=max(5.0, args.timeout),
        )
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
