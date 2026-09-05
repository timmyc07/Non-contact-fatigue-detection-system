"""Headless ownership for engine configuration and runtime inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Protocol

if TYPE_CHECKING:
    from rppg.belt_truth_capture import BeltTruthCaptureWriter
    from rppg.calibration_watch import WatchHrHub
    from rppg.hr_belt_ble import HrBeltConfig, HrBeltStatus


CAMERA_RESOLUTIONS = (
    "640×480",
    "800×600",
    "1280×720（720p）",
    "1280×800",
    "1920×1080（1080p）",
)
CAMERA_FIXED_FPS = "30"
CAMERA_FPS_OPTIONS = (CAMERA_FIXED_FPS,)
CAMERA_BACKENDS = ("ffmpeg",)
CAMERA_RESOLUTION_SIZES = {
    "640×480": (640, 480),
    "800×600": (800, 600),
    "1280×720（720p）": (1280, 720),
    "1280×800": (1280, 800),
    "1920×1080（1080p）": (1920, 1080),
}
_UNSET = object()


class BeltRuntimePort(Protocol):
    hub: WatchHrHub

    @property
    def belt_running(self) -> bool:
        ...

    def start_belt(self, config: HrBeltConfig | None = None) -> str:
        ...

    def stop_belt(self) -> None:
        ...

    def belt_status(self) -> HrBeltStatus | None:
        ...

    def create_truth_capture_writer(
        self, path: str | Path | None = None
    ) -> BeltTruthCaptureWriter:
        ...


@dataclass(frozen=True, slots=True)
class CameraDevice:
    index: int
    label: str


@dataclass(frozen=True, slots=True)
class CameraConfig:
    devices: tuple[CameraDevice, ...] = ()
    selected_index: int | None = None
    resolution: str = "1280×720（720p）"
    fps: str = CAMERA_FIXED_FPS
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


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    """決定分析 worker 拓樸；不包含任何 Qt 或執行緒物件。"""

    worker: str
    rppg_enabled: bool
    fatigue_enabled: bool


@dataclass(frozen=True, slots=True)
class PipelineSnapshot:
    """Headless pipeline lifecycle 的不可變快照。"""

    running: bool = False
    analysis: AnalysisPlan = AnalysisPlan("none", False, False)
    recording: bool = False
    cleanup_pending: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisLifecyclePorts:
    """Qt adapter 提供的 worker 操作；controller 只管理呼叫順序。"""

    stop_all: Callable[[], None]
    start_combined: Callable[[], None]
    start_rppg: Callable[[], None]
    start_fatigue: Callable[[], None]
    restore_raw_routing: Callable[[], None]


@dataclass(frozen=True, slots=True)
class ReplayLifecycleSnapshot:
    running: bool = False
    stopping: bool = False
    shutdown_pending: bool = False


class EngineController:
    """Own engine-facing state without importing Qt or GUI widgets."""

    def __init__(self, *, belt_runtime: BeltRuntimePort | None = None) -> None:
        self._camera = CameraConfig()
        self._preferred_camera_index: int | None = None
        self._analysis = AnalysisPlan("fatigue", False, True)
        self._pipeline = PipelineSnapshot()
        self._replay = ReplayLifecycleSnapshot()
        self._belt_runtime = belt_runtime

    @property
    def belt_runtime(self) -> BeltRuntimePort:
        if self._belt_runtime is None:
            raise RuntimeError("Belt runtime adapter is not configured")
        return self._belt_runtime

    @property
    def belt_running(self) -> bool:
        return self.belt_runtime.belt_running

    def start_belt(self, config: HrBeltConfig | None = None) -> str:
        return self.belt_runtime.start_belt(config)

    def stop_belt(self) -> None:
        if self._belt_runtime is not None:
            self._belt_runtime.stop_belt()

    def belt_status(self) -> HrBeltStatus | None:
        return self.belt_runtime.belt_status()

    def clear_belt_samples(self) -> None:
        self.belt_runtime.hub.clear()

    def belt_samples(self) -> list[Any]:
        return self.belt_runtime.hub.snapshot()

    def create_belt_truth_capture_writer(
        self, path: str | Path | None = None
    ) -> BeltTruthCaptureWriter:
        return self.belt_runtime.create_truth_capture_writer(path)

    @staticmethod
    def analysis_plan(*, rppg_enabled: bool, fatigue_enabled: bool) -> AnalysisPlan:
        """保留既有三種 worker 模式，禁止平行啟動兩個 FaceLandmarker。"""
        if not isinstance(rppg_enabled, bool):
            raise ValueError("rppg_enabled must be a boolean")
        if not isinstance(fatigue_enabled, bool):
            raise ValueError("fatigue_enabled must be a boolean")
        if rppg_enabled and fatigue_enabled:
            worker = "combined"
        elif rppg_enabled:
            worker = "rppg"
        elif fatigue_enabled:
            worker = "fatigue"
        else:
            worker = "none"
        return AnalysisPlan(worker, rppg_enabled, fatigue_enabled)

    def pipeline_snapshot(self) -> PipelineSnapshot:
        return replace(self._pipeline)

    def analysis_snapshot(self) -> AnalysisPlan:
        return replace(self._analysis)

    def start_pipeline(self) -> AnalysisPlan:
        if self._pipeline.cleanup_pending:
            raise RuntimeError("Wait for live pipeline adapter cleanup before restarting")
        if self._replay.running:
            raise RuntimeError("Stop replay before starting the live pipeline")
        if self._camera.selected_index is None:
            raise ValueError("Select a camera before starting the pipeline")
        self._pipeline = PipelineSnapshot(running=True, analysis=self._analysis)
        return self.analysis_snapshot()

    def stop_pipeline(self) -> None:
        self._pipeline = PipelineSnapshot()

    def mark_pipeline_cleanup_pending(self) -> None:
        self._pipeline = PipelineSnapshot(cleanup_pending=True)

    def finish_pipeline_cleanup(self) -> None:
        self._pipeline = PipelineSnapshot()

    def start_recording(self) -> None:
        if not self._pipeline.running:
            raise RuntimeError("Pipeline must be running before recording starts")
        self._pipeline = replace(self._pipeline, recording=True)

    def stop_recording(self) -> None:
        if self._pipeline.recording:
            self._pipeline = replace(self._pipeline, recording=False)

    def replay_snapshot(self) -> ReplayLifecycleSnapshot:
        return replace(self._replay)

    def start_replay(self) -> None:
        if self._pipeline.cleanup_pending:
            raise RuntimeError("Wait for live pipeline adapter cleanup before replay starts")
        if self._pipeline.running or self._pipeline.recording:
            raise RuntimeError("Stop the live pipeline and recording before replay starts")
        if self._replay.running:
            raise RuntimeError("Replay is already running")
        self._replay = ReplayLifecycleSnapshot(running=True)

    def request_replay_stop(self) -> None:
        if self._replay.running:
            self._replay = replace(self._replay, stopping=True)

    def request_shutdown(self) -> str:
        if self._replay.running:
            self._replay = replace(
                self._replay,
                stopping=True,
                shutdown_pending=True,
            )
            return "stop_replay"
        return "close"

    def finish_replay(self) -> bool:
        resume_shutdown = self._replay.shutdown_pending
        self._replay = ReplayLifecycleSnapshot()
        return resume_shutdown

    def configure_analysis(
        self,
        *,
        rppg_enabled: bool,
        fatigue_enabled: bool,
        ports: AnalysisLifecyclePorts | None = None,
    ) -> AnalysisPlan:
        plan = self.analysis_plan(
            rppg_enabled=rppg_enabled,
            fatigue_enabled=fatigue_enabled,
        )
        if plan == self._analysis:
            return self.analysis_snapshot()
        if not self._pipeline.running:
            self._analysis = plan
            return self.analysis_snapshot()
        if ports is None:
            raise ValueError("Analysis lifecycle ports are required while the pipeline is running")
        previous_plan = self._analysis
        try:
            ports.stop_all()
            self._activate_analysis(plan, ports)
        except Exception as start_error:
            try:
                ports.stop_all()
                self._activate_analysis(previous_plan, ports)
            except Exception as rollback_error:
                self.mark_pipeline_cleanup_pending()
                raise RuntimeError(
                    "Analysis worker start failed and rollback failed: "
                    f"start={start_error}; rollback={rollback_error}"
                ) from rollback_error
            raise
        self._analysis = plan
        self._pipeline = replace(self._pipeline, analysis=plan)
        return self.analysis_snapshot()

    @staticmethod
    def _activate_analysis(plan: AnalysisPlan, ports: AnalysisLifecyclePorts) -> None:
        if plan.worker == "combined":
            ports.start_combined()
        elif plan.worker == "rppg":
            ports.start_rppg()
        elif plan.worker == "fatigue":
            ports.start_fatigue()
        else:
            ports.restore_raw_routing()

    def activate_current_analysis(self, ports: AnalysisLifecyclePorts) -> AnalysisPlan:
        if not self._pipeline.running:
            raise RuntimeError("Pipeline must be running before analysis workers start")
        plan = self._pipeline.analysis
        self._activate_analysis(plan, ports)
        return plan

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
