from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts import desktop_hardware_smoke as smoke


def test_choose_camera_defaults_to_first_and_honors_requested_index() -> None:
    cameras = [{"index": 2, "label": "Second"}, {"index": 4, "label": "Fourth"}]

    assert smoke._choose_camera(cameras, None) == cameras[0]
    assert smoke._choose_camera(cameras, 4) == cameras[1]


def test_choose_camera_reports_missing_hardware_or_index() -> None:
    with pytest.raises(RuntimeError, match="no camera"):
        smoke._choose_camera([], None)
    with pytest.raises(RuntimeError, match="unavailable"):
        smoke._choose_camera([{"index": 0, "label": "Camera"}], 9)


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"camera_running": True, "fps": 30, "camera_width": 1280, "camera_height": 720}, True),
        ({"camera_running": False, "fps": 30, "camera_width": 1280, "camera_height": 720}, False),
        ({"camera_running": True, "fps": 0, "camera_width": 1280, "camera_height": 720}, False),
        ({"camera_running": True, "fps": 30, "camera_width": 0, "camera_height": 720}, False),
    ],
)
def test_metrics_ready_requires_live_camera_dimensions_and_fps(
    metrics: dict[str, Any], expected: bool
) -> None:
    assert smoke._metrics_ready(metrics) is expected


def test_metrics_ready_can_require_the_expected_worker_frame_source() -> None:
    metrics = {
        "camera_running": True,
        "fps": 30,
        "camera_width": 1280,
        "camera_height": 720,
        "frame_source": "combined",
    }

    assert smoke._metrics_ready(metrics, expected_frame_source="combined") is True
    assert smoke._metrics_ready(metrics, expected_frame_source="camera") is False


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("raw", (False, False)),
        ("fatigue", (True, False)),
        ("rppg", (False, True)),
        ("combined", (True, True)),
    ],
)
def test_analysis_flags_match_worker_modes(mode: str, expected: tuple[bool, bool]) -> None:
    assert smoke._analysis_flags(mode) == expected


def test_analysis_flags_reject_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        smoke._analysis_flags("invalid")


@pytest.mark.parametrize(
    ("mode", "source"),
    [("raw", "camera"), ("fatigue", "fatigue"), ("rppg", "rppg"), ("combined", "combined")],
)
def test_expected_frame_source_matches_mode(mode: str, source: str) -> None:
    assert smoke._expected_frame_source(mode) == source


def test_hardware_smoke_supports_direct_script_execution() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "desktop_hardware_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "except ModuleNotFoundError:" in source
    assert "Path(__file__).resolve().parents[1]" in source


def test_run_smoke_exercises_commands_and_always_stops_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    process = object()
    calls: list[tuple[str, dict[str, Any]]] = []
    stopped: list[object] = []

    monkeypatch.setattr(smoke, "start_source_engine", lambda **_: (process, 12.5))
    monkeypatch.setattr(
        smoke,
        "control_state",
        lambda **_: {
            "desktop_api_version": 2,
            "cameras": [{"index": 0, "label": "Camera 0"}],
        },
    )

    def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "GET" and path == "/api/metrics":
            return {
                "success": True,
                "metrics": {
                    "camera_running": True,
                    "fps": 30.0,
                    "camera_width": 640,
                    "camera_height": 480,
                    "camera_codec": "MJPG",
                    "frame_source": "combined",
                },
            }
        body = kwargs["body"]
        calls.append((body["command"], body["args"]))
        if body["command"] == "analysis.configure":
            behavior_enabled = body["args"]["behavior_enabled"]
            rppg_enabled = body["args"]["rppg_enabled"]
        else:
            behavior_enabled = True
            rppg_enabled = True
        data = {
            "selected_camera_index": 0,
            "pipeline_running": body["command"] == "pipeline.set" and body["args"]["enabled"],
            "behavior_enabled": behavior_enabled,
            "rppg_enabled": rppg_enabled,
        }
        return {"success": True, "data": data}

    monkeypatch.setattr(smoke, "request_json", request)
    monkeypatch.setattr(
        smoke,
        "stop_engine",
        lambda proc, **_: stopped.append(proc),
    )

    result = smoke.run_smoke(analysis_mode="combined", timeout=5.0)

    assert stopped == [process]
    assert [name for name, _args in calls] == [
        "camera.select",
        "analysis.configure",
        "pipeline.set",
        "pipeline.set",
    ]
    assert calls[1] == (
        "analysis.configure",
        {"behavior_enabled": True, "rppg_enabled": True},
    )
    assert result["analysis"] == {
        "mode": "combined",
        "behavior_enabled": True,
        "rppg_enabled": True,
    }
    assert result["checks"] == {
        "desktop_api_version": 2,
        "pipeline_started": True,
        "camera_metrics_ready": True,
        "expected_frame_source": "combined",
        "frame_source_matches_mode": True,
        "pipeline_stopped": True,
        "analysis_configured": True,
    }
