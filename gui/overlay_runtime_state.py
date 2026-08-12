from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


_UNSET = object()


@dataclass(frozen=True, slots=True)
class OverlayGeometry:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class OverlaySnapshot:
    all_enabled: bool = True
    preview: bool = False
    metrics: bool = True
    locked: bool = True
    opacity: int = 55
    geometry: OverlayGeometry | None = None


class OverlayRuntimeState:
    """Own persisted Tauri overlay preferences without importing Qt."""

    def __init__(self) -> None:
        self._state = OverlaySnapshot()

    def snapshot(self) -> OverlaySnapshot:
        return replace(self._state)

    @staticmethod
    def _validate_bool(name: str, value: object) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        return value

    @staticmethod
    def _validate_opacity(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("opacity must be between 0 and 100")
        return value

    @staticmethod
    def _validate_geometry(value: object) -> OverlayGeometry | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
            raise ValueError("geometry must contain x, y, width, and height")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in value.values()):
            raise ValueError("geometry values must be integers")
        x = value["x"]
        y = value["y"]
        width = value["width"]
        height = value["height"]
        if not -100_000 <= x <= 100_000 or not -100_000 <= y <= 100_000:
            raise ValueError("geometry position is outside the supported range")
        if not 320 <= width <= 16_384 or not 180 <= height <= 16_384:
            raise ValueError("geometry size is outside the supported range")
        return OverlayGeometry(x=x, y=y, width=width, height=height)

    def configure(
        self,
        *,
        all_enabled: object = _UNSET,
        preview: object = _UNSET,
        metrics: object = _UNSET,
        locked: object = _UNSET,
        opacity: object = _UNSET,
        geometry: object = _UNSET,
    ) -> OverlaySnapshot:
        changes: dict[str, Any] = {}
        if all_enabled is not _UNSET:
            enabled = self._validate_bool("all_enabled", all_enabled)
            changes.update(
                all_enabled=enabled,
                preview=enabled,
                metrics=enabled,
            )
        if preview is not _UNSET:
            changes["preview"] = self._validate_bool("preview", preview)
        if metrics is not _UNSET:
            changes["metrics"] = self._validate_bool("metrics", metrics)
        if locked is not _UNSET:
            changes["locked"] = self._validate_bool("locked", locked)
        if opacity is not _UNSET:
            changes["opacity"] = self._validate_opacity(opacity)
        if geometry is not _UNSET:
            changes["geometry"] = self._validate_geometry(geometry)
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def load(self, *, toggles: object, overlay: object) -> OverlaySnapshot:
        toggle_values = toggles if isinstance(toggles, dict) else {}
        overlay_values = overlay if isinstance(overlay, dict) else {}
        changes: dict[str, Any] = {}
        for key, field in (
            ("all", "all_enabled"),
            ("preview", "preview"),
            ("metrics", "metrics"),
            ("lock", "locked"),
        ):
            value = toggle_values.get(key)
            if isinstance(value, bool):
                changes[field] = value
        opacity = overlay_values.get("opacity")
        if isinstance(opacity, int) and not isinstance(opacity, bool) and 0 <= opacity <= 100:
            changes["opacity"] = opacity
        geometry = overlay_values.get("geometry")
        if isinstance(geometry, dict):
            try:
                changes["geometry"] = self._validate_geometry(geometry)
            except ValueError:
                pass
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def reset(self) -> OverlaySnapshot:
        self._state = OverlaySnapshot()
        return self.snapshot()

    def to_desktop_state(self) -> dict[str, object]:
        state = self._state
        return {
            "overlay_preview": state.preview,
            "overlay_metrics": state.metrics,
            "overlay_locked": state.locked,
            "overlay_all": state.all_enabled,
            "overlay_opacity": state.opacity,
            "overlay_geometry": (
                state.geometry.to_dict() if state.geometry is not None else None
            ),
        }

    def to_settings(self) -> dict[str, dict[str, object]]:
        state = self._state
        return {
            "toggles": {
                "all": state.all_enabled,
                "preview": state.preview,
                "metrics": state.metrics,
                "lock": state.locked,
            },
            "overlay": {
                "opacity": state.opacity,
                "geometry": (
                    state.geometry.to_dict() if state.geometry is not None else None
                ),
            },
        }
