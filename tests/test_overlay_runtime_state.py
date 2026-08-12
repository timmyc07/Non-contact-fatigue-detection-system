from __future__ import annotations

import subprocess
import sys

import pytest

from gui.overlay_runtime_state import OverlayRuntimeState


def test_overlay_runtime_state_import_is_qt_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import gui.overlay_runtime_state; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_overlay_defaults_and_all_toggle_preserve_desktop_contract() -> None:
    state = OverlayRuntimeState()

    assert state.to_desktop_state() == {
        "overlay_preview": False,
        "overlay_metrics": True,
        "overlay_locked": True,
        "overlay_all": True,
        "overlay_opacity": 55,
    }

    state.configure(all_enabled=False)
    assert state.to_desktop_state() == {
        "overlay_preview": False,
        "overlay_metrics": False,
        "overlay_locked": True,
        "overlay_all": False,
        "overlay_opacity": 55,
    }


def test_overlay_partial_configuration_and_persistence_projection() -> None:
    state = OverlayRuntimeState()

    state.configure(preview=True, locked=False, opacity=72)

    assert state.to_settings() == {
        "toggles": {
            "all": True,
            "preview": True,
            "metrics": True,
            "lock": False,
        },
        "overlay": {"opacity": 72},
    }


def test_overlay_individual_values_override_all_in_same_configuration() -> None:
    state = OverlayRuntimeState()

    state.configure(all_enabled=False, preview=True, metrics=True)

    assert state.snapshot().all_enabled is False
    assert state.snapshot().preview is True
    assert state.snapshot().metrics is True


def test_overlay_load_ignores_invalid_values_and_reset_restores_defaults() -> None:
    state = OverlayRuntimeState()

    state.load(
        toggles={
            "all": False,
            "preview": True,
            "metrics": "invalid",
            "lock": False,
        },
        overlay={"opacity": 120},
    )

    assert state.snapshot().all_enabled is False
    assert state.snapshot().preview is True
    assert state.snapshot().metrics is True
    assert state.snapshot().locked is False
    assert state.snapshot().opacity == 55

    state.reset()
    assert state.snapshot() == OverlayRuntimeState().snapshot()


@pytest.mark.parametrize("opacity", [-1, 101, True, 55.5, "55"])
def test_overlay_configuration_rejects_invalid_opacity(opacity: object) -> None:
    state = OverlayRuntimeState()

    with pytest.raises(ValueError, match="opacity"):
        state.configure(opacity=opacity)
