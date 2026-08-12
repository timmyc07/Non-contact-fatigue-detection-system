from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


_UNSET = object()


@dataclass(frozen=True, slots=True)
class CapturePreferencesSnapshot:
    auto_record: bool = False
    belt_calibration: bool = False
    auto_capture_seconds: int = 60
    auto_capture_include_belt: bool = False


class CapturePreferencesState:
    """Own recording and capture preferences without importing Qt."""

    def __init__(self) -> None:
        self._state = CapturePreferencesSnapshot()

    def snapshot(self) -> CapturePreferencesSnapshot:
        return replace(self._state)

    def restore(
        self, snapshot: CapturePreferencesSnapshot
    ) -> CapturePreferencesSnapshot:
        if not isinstance(snapshot, CapturePreferencesSnapshot):
            raise ValueError("snapshot must be a CapturePreferencesSnapshot")
        self._state = replace(snapshot)
        return self.snapshot()

    def configure(
        self,
        *,
        auto_record: object = _UNSET,
        belt_calibration: object = _UNSET,
        auto_capture_seconds: object = _UNSET,
        auto_capture_include_belt: object = _UNSET,
    ) -> CapturePreferencesSnapshot:
        changes: dict[str, Any] = {}
        for name, value in (
            ("auto_record", auto_record),
            ("belt_calibration", belt_calibration),
            ("auto_capture_include_belt", auto_capture_include_belt),
        ):
            if value is _UNSET:
                continue
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean")
            changes[name] = value
        if auto_capture_seconds is not _UNSET:
            value = auto_capture_seconds
            if isinstance(value, bool) or not isinstance(value, int) or not 10 <= value <= 600:
                raise ValueError("auto_capture_seconds must be between 10 and 600")
            changes["auto_capture_seconds"] = value
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def load(self, *, toggles: object) -> CapturePreferencesSnapshot:
        values = toggles if isinstance(toggles, dict) else {}
        changes: dict[str, bool] = {}
        for key, field in (
            ("auto_record", "auto_record"),
            ("belt_calib", "belt_calibration"),
        ):
            value = values.get(key)
            if isinstance(value, bool):
                changes[field] = value
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def reset_persisted(self) -> CapturePreferencesSnapshot:
        self._state = replace(
            self._state,
            auto_record=False,
            belt_calibration=False,
        )
        return self.snapshot()

    def to_desktop_state(self) -> dict[str, object]:
        state = self._state
        return {
            "auto_record": state.auto_record,
            "belt_calibration": state.belt_calibration,
            "auto_capture_seconds": state.auto_capture_seconds,
            "auto_capture_include_belt": state.auto_capture_include_belt,
        }

    def to_settings_toggles(self) -> dict[str, bool]:
        state = self._state
        return {
            "belt_calib": state.belt_calibration,
            "auto_record": state.auto_record,
        }
