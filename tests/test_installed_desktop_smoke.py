from __future__ import annotations

import pytest

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
