from __future__ import annotations

import pytest

from scripts import installed_desktop_smoke_macos as macos_smoke
from scripts.installed_desktop_smoke import _select_main_windows


def test_select_main_windows_ignores_tauri_event_pump_helpers() -> None:
    main_window = {
        "hwnd": 101,
        "title": "Fatigue Monitor",
        "class_name": "Tauri Window",
        "visible": True,
    }
    windows = [
        main_window,
        {
            "hwnd": 102,
            "title": "tw.fatigue-monitor.desktop-siw",
            "class_name": "tw.fatigue-monitor.desktop-sic",
            "visible": True,
        },
        {
            "hwnd": 103,
            "title": "",
            "class_name": "Tao Thread Event Target",
            "visible": True,
        },
    ]

    selected = _select_main_windows(windows)

    assert selected == [main_window]
    assert selected[0]["title"] == "Fatigue Monitor"
    assert selected[0]["class_name"] == "Tauri Window"


@pytest.mark.parametrize(
    "windows",
    [
        [],
        [
            {
                "hwnd": 101,
                "title": "Fatigue Monitor",
                "class_name": "Tauri Window",
                "visible": False,
            }
        ],
        [
            {
                "hwnd": hwnd,
                "title": "Fatigue Monitor",
                "class_name": "Tauri Window",
                "visible": True,
            }
            for hwnd in (101, 102)
        ],
    ],
)
def test_select_main_windows_rejects_ambiguous_shells(
    windows: list[dict[str, object]],
) -> None:
    with pytest.raises(RuntimeError, match="one visible Tauri window"):
        _select_main_windows(windows)


def test_macos_shell_quit_targets_packaged_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append(command)

    monkeypatch.setattr(macos_smoke.subprocess, "run", fake_run)

    macos_smoke._request_shell_quit()

    assert calls == [
        [
            "osascript",
            "-e",
            'tell application id "tw.fatigue-monitor.desktop" to quit',
        ]
    ]


def test_macos_shell_exit_wait_has_a_timeout() -> None:
    class FinishedProcess:
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            assert timeout == 2.0
            return self.returncode

    assert macos_smoke._wait_for_shell_exit(FinishedProcess(), 2.0) == 0


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"camera_running": True, "fps": 30, "camera_width": 1280, "camera_height": 720, "frame_source": "camera"}, True),
        ({"camera_running": False, "fps": 30, "camera_width": 1280, "camera_height": 720, "frame_source": "camera"}, False),
        ({"camera_running": True, "fps": 30, "camera_width": 1280, "camera_height": 720, "frame_source": "combined"}, False),
    ],
)
def test_macos_packaged_smoke_requires_live_raw_camera_metrics(
    metrics: dict[str, object], expected: bool
) -> None:
    assert macos_smoke._camera_metrics_ready(metrics) is expected
