from __future__ import annotations

import subprocess
import sys

import pytest

from gui.engine_controller import (
    AnalysisLifecyclePorts,
    CameraDevice,
    EngineController,
)


def test_engine_controller_import_is_qt_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import gui.engine_controller; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("rppg_enabled", "fatigue_enabled", "worker"),
    [
        (True, True, "combined"),
        (True, False, "rppg"),
        (False, True, "fatigue"),
        (False, False, "none"),
    ],
)
def test_analysis_plan_preserves_single_landmarker_worker_modes(
    rppg_enabled: bool, fatigue_enabled: bool, worker: str
) -> None:
    plan = EngineController.analysis_plan(
        rppg_enabled=rppg_enabled,
        fatigue_enabled=fatigue_enabled,
    )

    assert plan.worker == worker
    assert plan.rppg_enabled is rppg_enabled
    assert plan.fatigue_enabled is fatigue_enabled


def test_pipeline_lifecycle_requires_camera_and_preserves_analysis_snapshot() -> None:
    controller = EngineController()

    with pytest.raises(ValueError, match="camera"):
        controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)

    controller.replace_cameras([CameraDevice(0, "Camera")])
    plan = controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)
    assert plan.worker == "combined"
    assert controller.pipeline_snapshot().running is True

    next_plan = controller.set_analysis_plan(rppg_enabled=True, fatigue_enabled=False)
    assert next_plan.worker == "rppg"
    assert controller.pipeline_snapshot().analysis == next_plan

    controller.start_recording()
    assert controller.pipeline_snapshot().recording is True
    controller.stop_recording()
    assert controller.pipeline_snapshot().recording is False

    controller.stop_pipeline()
    assert controller.pipeline_snapshot().running is False
    assert controller.pipeline_snapshot().analysis.worker == "none"


def test_recording_lifecycle_rejects_start_without_pipeline() -> None:
    controller = EngineController()

    with pytest.raises(RuntimeError, match="Pipeline"):
        controller.start_recording()


def test_replay_shutdown_waits_for_finish_before_close() -> None:
    controller = EngineController()
    controller.start_replay()

    assert controller.request_shutdown() == "stop_replay"
    assert controller.replay_snapshot().stopping is True
    assert controller.replay_snapshot().shutdown_pending is True
    assert controller.finish_replay() is True
    assert controller.replay_snapshot().running is False
    assert controller.request_shutdown() == "close"


def test_pipeline_start_rejects_active_replay() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_replay()

    with pytest.raises(RuntimeError, match="replay"):
        controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)

    assert controller.pipeline_snapshot().running is False
    assert controller.replay_snapshot().running is True


def test_engine_controller_owns_belt_runtime_lifecycle() -> None:
    events: list[object] = []

    class FakeHub:
        def clear(self) -> None:
            events.append("clear")

        def snapshot(self) -> list[str]:
            events.append("snapshot")
            return ["sample"]

    class FakeBeltRuntime:
        hub = FakeHub()
        belt_running = False

        def start_belt(self, config: object = None) -> str:
            events.append(("start", config))
            self.belt_running = True
            return ""

        def stop_belt(self) -> None:
            events.append("stop")
            self.belt_running = False

        def belt_status(self) -> object:
            events.append("status")
            return "connected"

        def create_truth_capture_writer(self, path=None) -> object:
            events.append(("writer", path))
            return "writer"

    runtime = FakeBeltRuntime()
    controller = EngineController(belt_runtime=runtime)  # type: ignore[arg-type]

    assert controller.belt_runtime is runtime
    assert controller.belt_running is False
    assert controller.start_belt() == ""
    assert controller.belt_running is True
    assert controller.belt_status() == "connected"
    assert controller.belt_samples() == ["sample"]
    controller.clear_belt_samples()
    assert controller.create_belt_truth_capture_writer() == "writer"
    controller.stop_belt()
    assert events == [
        ("start", None),
        "status",
        "snapshot",
        "clear",
        ("writer", None),
        "stop",
    ]


def test_analysis_lifecycle_ports_preserve_worker_start_and_restart_order() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    events: list[str] = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: events.append("stop"),
        start_combined=lambda: events.append("combined"),
        start_rppg=lambda: events.append("rppg"),
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)
    controller.activate_current_analysis(ports)
    controller.reconcile_analysis(
        rppg_enabled=True,
        fatigue_enabled=False,
        ports=ports,
    )
    controller.reconcile_analysis(
        rppg_enabled=False,
        fatigue_enabled=True,
        ports=ports,
    )
    controller.reconcile_analysis(
        rppg_enabled=False,
        fatigue_enabled=False,
        ports=ports,
    )

    assert events == [
        "combined",
        "stop",
        "rppg",
        "stop",
        "fatigue",
        "stop",
        "raw",
    ]


def test_analysis_reconcile_rolls_back_worker_and_snapshot_on_start_failure() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)
    events: list[str] = []

    def fail_rppg() -> None:
        events.append("rppg-failed")
        raise RuntimeError("worker failed")

    ports = AnalysisLifecyclePorts(
        stop_all=lambda: events.append("stop"),
        start_combined=lambda: events.append("combined"),
        start_rppg=fail_rppg,
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        controller.reconcile_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    assert events == ["stop", "rppg-failed", "stop", "combined"]
    assert controller.pipeline_snapshot().analysis.worker == "combined"


def test_analysis_reconcile_fails_closed_when_worker_rollback_also_fails() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)

    def fail(message: str):
        def callback() -> None:
            raise RuntimeError(message)

        return callback

    ports = AnalysisLifecyclePorts(
        stop_all=lambda: None,
        start_combined=fail("rollback failed"),
        start_rppg=fail("new worker failed"),
        start_fatigue=lambda: None,
        restore_raw_routing=lambda: None,
    )

    with pytest.raises(RuntimeError, match="rollback failed"):
        controller.reconcile_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    snapshot = controller.pipeline_snapshot()
    assert snapshot.running is False
    assert snapshot.cleanup_pending is True
    with pytest.raises(RuntimeError, match="cleanup"):
        controller.start_replay()


def test_analysis_reconcile_fails_closed_when_initial_stop_fails() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline(rppg_enabled=True, fatigue_enabled=True)
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: (_ for _ in ()).throw(RuntimeError("stop failed")),
        start_combined=lambda: None,
        start_rppg=lambda: None,
        start_fatigue=lambda: None,
        restore_raw_routing=lambda: None,
    )

    with pytest.raises(RuntimeError, match="rollback failed"):
        controller.reconcile_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    snapshot = controller.pipeline_snapshot()
    assert snapshot.running is False
    assert snapshot.cleanup_pending is True
