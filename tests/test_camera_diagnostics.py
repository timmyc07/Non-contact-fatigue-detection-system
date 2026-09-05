from __future__ import annotations

from scripts.diagnose_camera import _measured_fps


def test_camera_diagnostic_measures_fps_from_frame_timestamps() -> None:
    assert _measured_fps(10.0, 11.0, 31) == 30.0
    assert _measured_fps(None, None, 0) == 0.0
    assert _measured_fps(10.0, 10.0, 2) == 0.0
