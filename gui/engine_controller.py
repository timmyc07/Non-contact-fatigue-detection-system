"""Headless ownership for engine configuration and runtime inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable


CAMERA_RESOLUTIONS = (
    "640×480",
    "800×600",
    "1280×720（720p）",
    "1280×800",
    "1920×1080（1080p）",
)
CAMERA_FPS_OPTIONS = ("15", "24", "30", "60")
CAMERA_BACKENDS = ("ffmpeg",)
CAMERA_RESOLUTION_SIZES = {
    "640×480": (640, 480),
    "800×600": (800, 600),
    "1280×720（720p）": (1280, 720),
    "1280×800": (1280, 800),
    "1920×1080（1080p）": (1920, 1080),
}
_UNSET = object()


@dataclass(frozen=True, slots=True)
class CameraDevice:
    index: int
    label: str


@dataclass(frozen=True, slots=True)
class CameraConfig:
    devices: tuple[CameraDevice, ...] = ()
    selected_index: int | None = None
    resolution: str = "1280×720（720p）"
    fps: str = "30"
    backend: str = "ffmpeg"
    horizontal_flip: bool = True


@dataclass(frozen=True, slots=True)
class CameraStartSpec:
    index: int
    width: int
    height: int
    target_fps: int
    backend: str
    horizontal_flip: bool
    camera_label: str


class EngineController:
    """Own engine-facing state without importing Qt or GUI widgets."""

    def __init__(self) -> None:
        self._camera = CameraConfig()
        self._preferred_camera_index: int | None = None

    def replace_cameras(self, devices: Iterable[CameraDevice]) -> None:
        catalog = tuple(devices)
        available = {device.index for device in catalog}
        if self._preferred_camera_index in available:
            selected = self._preferred_camera_index
            self._preferred_camera_index = None
        else:
            selected = self._camera.selected_index
        if selected not in available:
            selected = catalog[0].index if catalog else None
        self._camera = replace(self._camera, devices=catalog, selected_index=selected)

    def select_camera(self, index: int | None) -> None:
        if index is None:
            self._preferred_camera_index = None
            self._camera = replace(self._camera, selected_index=None)
            return
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Camera index must be an integer")
        if not any(device.index == index for device in self._camera.devices):
            raise ValueError(f"Camera index is unavailable: {index}")
        self._preferred_camera_index = None
        self._camera = replace(self._camera, selected_index=index)

    def restore_camera(self, index: int) -> None:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Camera index must be an integer")
        if any(device.index == index for device in self._camera.devices):
            self.select_camera(index)
            return
        self._preferred_camera_index = index

    def configure_camera(
        self,
        *,
        resolution: object = _UNSET,
        fps: object = _UNSET,
        backend: object = _UNSET,
        horizontal_flip: object = _UNSET,
    ) -> None:
        changes: dict[str, object] = {}
        if resolution is not _UNSET:
            value = str(resolution)
            if value not in CAMERA_RESOLUTIONS:
                raise ValueError(f"Unsupported camera resolution: {value}")
            changes["resolution"] = value
        if fps is not _UNSET:
            value = str(fps)
            if value not in CAMERA_FPS_OPTIONS:
                raise ValueError(f"Unsupported camera FPS: {value}")
            changes["fps"] = value
        if backend is not _UNSET:
            value = str(backend)
            if value not in CAMERA_BACKENDS:
                raise ValueError(f"Unsupported camera backend: {value}")
            changes["backend"] = value
        if horizontal_flip is not _UNSET:
            if not isinstance(horizontal_flip, bool):
                raise ValueError("horizontal_flip must be a boolean")
            changes["horizontal_flip"] = horizontal_flip
        self._camera = replace(self._camera, **changes)

    def camera_snapshot(self) -> CameraConfig:
        return replace(self._camera)

    def reset_camera_settings(self) -> None:
        defaults = CameraConfig()
        self._camera = replace(
            self._camera,
            resolution=defaults.resolution,
            fps=defaults.fps,
            backend=defaults.backend,
            horizontal_flip=defaults.horizontal_flip,
        )

    def selected_camera_label(self) -> str:
        selected = self._camera.selected_index
        for device in self._camera.devices:
            if device.index == selected:
                return device.label
        return ""

    def camera_start_spec(self) -> CameraStartSpec:
        selected = self._camera.selected_index
        if selected is None:
            raise ValueError("Select a camera before starting the pipeline")
        device = next(
            (device for device in self._camera.devices if device.index == selected),
            None,
        )
        if device is None:
            raise ValueError(f"Camera index is unavailable: {selected}")
        width, height = CAMERA_RESOLUTION_SIZES[self._camera.resolution]
        return CameraStartSpec(
            index=selected,
            width=width,
            height=height,
            target_fps=int(self._camera.fps),
            backend=self._camera.backend,
            horizontal_flip=self._camera.horizontal_flip,
            camera_label=device.label,
        )
