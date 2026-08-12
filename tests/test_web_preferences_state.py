from __future__ import annotations

import subprocess
import sys

import pytest

from gui.web_preferences_state import WebPreferencesState


def test_web_preferences_import_is_qt_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import gui.web_preferences_state; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_web_preferences_default_to_local_only() -> None:
    state = WebPreferencesState()

    assert state.snapshot().allow_lan is False
    assert state.to_desktop_state() == {"web_allow_lan": False}
    assert state.to_settings() == {"allow_lan": False}


def test_web_preferences_configure_load_and_reset() -> None:
    state = WebPreferencesState()

    assert state.configure(allow_lan=True).allow_lan is True
    assert state.load(web={"allow_lan": False}).allow_lan is False
    assert state.load(web={"allow_lan": "invalid"}).allow_lan is False
    assert state.configure(allow_lan=True).allow_lan is True
    assert state.reset().allow_lan is False


@pytest.mark.parametrize("value", [0, 1, None, "true"])
def test_web_preferences_reject_non_boolean_values(value: object) -> None:
    with pytest.raises(ValueError, match="allow_lan"):
        WebPreferencesState().configure(allow_lan=value)
