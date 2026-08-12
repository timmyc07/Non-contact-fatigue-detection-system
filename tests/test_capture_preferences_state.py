from __future__ import annotations

import subprocess
import sys

import pytest

from gui.capture_preferences_state import (
    CapturePreferencesSnapshot,
    CapturePreferencesState,
)


def test_capture_preferences_import_is_qt_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import gui.capture_preferences_state; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_capture_preferences_defaults_preserve_desktop_contract() -> None:
    state = CapturePreferencesState()

    assert state.to_desktop_state() == {
        "auto_record": False,
        "belt_calibration": False,
        "auto_capture_seconds": 60,
        "auto_capture_include_belt": False,
    }
    assert state.to_settings_toggles() == {
        "belt_calib": False,
        "auto_record": False,
    }


def test_capture_preferences_load_is_tolerant_and_reset_is_scoped() -> None:
    state = CapturePreferencesState()
    state.configure(auto_capture_seconds=120, auto_capture_include_belt=True)

    state.load(toggles={"auto_record": True, "belt_calib": "invalid"})
    assert state.snapshot().auto_record is True
    assert state.snapshot().belt_calibration is False

    state.reset_persisted()
    snapshot = state.snapshot()
    assert snapshot.auto_record is False
    assert snapshot.belt_calibration is False
    assert snapshot.auto_capture_seconds == 120
    assert snapshot.auto_capture_include_belt is True


def test_capture_preferences_restore_replaces_the_entire_snapshot() -> None:
    state = CapturePreferencesState()
    original = state.snapshot()
    state.configure(
        auto_record=True,
        belt_calibration=True,
        auto_capture_seconds=120,
        auto_capture_include_belt=True,
    )

    assert state.restore(original) == original

    with pytest.raises(ValueError, match="CapturePreferencesSnapshot"):
        state.restore(object())  # type: ignore[arg-type]

    assert isinstance(state.snapshot(), CapturePreferencesSnapshot)


@pytest.mark.parametrize("value", [0, 9, 601, True, 60.0, "60"])
def test_capture_preferences_reject_invalid_duration(value: object) -> None:
    with pytest.raises(ValueError, match="auto_capture_seconds"):
        CapturePreferencesState().configure(auto_capture_seconds=value)


@pytest.mark.parametrize("field", ["auto_record", "belt_calibration", "auto_capture_include_belt"])
def test_capture_preferences_reject_non_boolean_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        CapturePreferencesState().configure(**{field: 1})
