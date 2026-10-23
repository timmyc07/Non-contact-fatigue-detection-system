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
        controller.start_pipeline()

    controller.replace_cameras([CameraDevice(0, "Camera")])
    configured = controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
    )
    plan = controller.start_pipeline()
    assert plan == configured
    assert plan.worker == "combined"
    assert controller.pipeline_snapshot().running is True

    next_plan = controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=False,
        ports=AnalysisLifecyclePorts(
            stop_all=lambda: True,
            start_combined=lambda: None,
            start_rppg=lambda: None,
            start_fatigue=lambda: None,
            restore_raw_routing=lambda: None,
        ),
    )
    assert next_plan.worker == "rppg"
    assert controller.pipeline_snapshot().analysis == next_plan

    controller.start_recording()
    assert controller.pipeline_snapshot().recording is True
    controller.stop_recording()
    assert controller.pipeline_snapshot().recording is False

    controller.stop_pipeline()
    assert controller.pipeline_snapshot().running is False
    assert controller.pipeline_snapshot().analysis.worker == "none"
    assert controller.analysis_snapshot() == next_plan


def test_analysis_preferences_are_product_state_while_pipeline_is_idle() -> None:
    controller = EngineController()

    assert controller.analysis_snapshot().worker == "fatigue"

    configured = controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=False,
    )

    assert configured.worker == "rppg"
    assert controller.analysis_snapshot() == configured
    assert controller.pipeline_snapshot().analysis.worker == "none"


def test_pending_analysis_stop_preserves_camera_recording_and_committed_plan() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline()
    controller.start_recording()
    joined = False
    events = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: joined,
        start_combined=lambda: events.append("combined"),
        start_rppg=lambda: events.append("rppg"),
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=False, ports=ports)
    assert events == []
    assert controller.analysis_transitioning
    assert controller.analysis_snapshot().worker == "fatigue"
    assert controller.pipeline_snapshot().running
    assert controller.pipeline_snapshot().recording
    assert not controller.pipeline_snapshot().cleanup_pending
    with pytest.raises(RuntimeError, match="transition"):
        controller.activate_current_analysis(ports)
    with pytest.raises(RuntimeError, match="transition"):
        controller.start_recording()
    with pytest.raises(RuntimeError, match="transition"):
        controller.start_pipeline()
    joined = True
    controller.advance_analysis_transition(ports)
    assert events == ["rppg"]
    assert not controller.analysis_transitioning
    assert controller.analysis_snapshot().worker == "rppg"


def test_failed_analysis_start_waits_for_partial_worker_before_rollback() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline()
    joined = True
    events = []

    def start_rppg():
        nonlocal joined
        joined = False
        events.append("new.failed")
        raise RuntimeError("start failed")

    ports = AnalysisLifecyclePorts(
        stop_all=lambda: joined,
        start_combined=lambda: None,
        start_rppg=start_rppg,
        start_fatigue=lambda: events.append("old.restored"),
        restore_raw_routing=lambda: None,
    )
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=False, ports=ports)
    assert events == ["new.failed"]
    assert controller.analysis_transitioning
    assert controller.pipeline_snapshot().running
    joined = True
    with pytest.raises(RuntimeError, match="start failed"):
        controller.advance_analysis_transition(ports)
    assert events == ["new.failed", "old.restored"]
    assert not controller.analysis_transitioning
    assert controller.analysis_snapshot().worker == "fatigue"


@pytest.mark.parametrize("stop_method", ["stop_pipeline", "mark_pipeline_cleanup_pending"])
def test_pipeline_stop_cancels_pending_analysis_target(stop_method) -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline()
    events = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: False,
        start_combined=lambda: events.append("combined"),
        start_rppg=lambda: events.append("rppg"),
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True, ports=ports)
    getattr(controller, stop_method)()
    controller.advance_analysis_transition(ports)
    assert not controller.analysis_transitioning
    assert events == []


@pytest.mark.parametrize("previous", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("target", [(False, False), (False, True), (True, False), (True, True)])
def test_all_analysis_modes_wait_for_old_worker_without_overlap(previous, target) -> None:
    controller = EngineController()
    controller.configure_analysis(rppg_enabled=previous[0], fatigue_enabled=previous[1])
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline()
    released = False
    starts = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: released,
        start_combined=lambda: starts.append("combined"),
        start_rppg=lambda: starts.append("rppg"),
        start_fatigue=lambda: starts.append("fatigue"),
        restore_raw_routing=lambda: starts.append("none"),
    )
    controller.configure_analysis(rppg_enabled=target[0], fatigue_enabled=target[1], ports=ports)
    assert starts == []
    assert controller.analysis_transitioning is (previous != target)
    released = True
    controller.advance_analysis_transition(ports)
    expected = controller.analysis_plan(rppg_enabled=target[0], fatigue_enabled=target[1])
    assert controller.analysis_snapshot() == expected
    assert starts == ([] if previous == target else [expected.worker])


def test_pending_transition_rejects_conflict_and_cancel_restores_previous_mode() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.start_pipeline()
    released = False
    starts = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: released,
        start_combined=lambda: starts.append("combined"),
        start_rppg=lambda: starts.append("rppg"),
        start_fatigue=lambda: starts.append("fatigue"),
        restore_raw_routing=lambda: None,
    )
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True, ports=ports)
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True, ports=ports)
    with pytest.raises(RuntimeError, match="pending"):
        controller.configure_analysis(rppg_enabled=True, fatigue_enabled=False, ports=ports)
    controller.cancel_analysis_transition()
    released = True
    controller.advance_analysis_transition(ports)
    assert starts == ["fatigue"]
    assert controller.analysis_snapshot().worker == "fatigue"


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
        controller.start_pipeline()

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

        def stop_belt(self, join_timeout: float | None = 0.0) -> bool:
            events.append(("stop", join_timeout))
            self.belt_running = False
            return True

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
    assert controller.stop_belt(join_timeout=None) is True
    assert events == [
        ("start", None),
        "status",
        "snapshot",
        "clear",
        ("writer", None),
        ("stop", None),
    ]


def test_engine_controller_stop_without_runtime_is_complete() -> None:
    assert EngineController().stop_belt() is True


def test_engine_controller_preserves_pending_belt_stop() -> None:
    class PendingRuntime:
        def stop_belt(self, join_timeout: float | None = 0.0) -> bool:
            assert join_timeout == 0.0
            return False

    runtime = PendingRuntime()
    controller = EngineController(belt_runtime=runtime)  # type: ignore[arg-type]
    assert controller.stop_belt() is False
    assert controller.belt_runtime is runtime


def test_analysis_lifecycle_ports_preserve_worker_start_and_restart_order() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    events: list[str] = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: events.append("stop") or True,
        start_combined=lambda: events.append("combined"),
        start_rppg=lambda: events.append("rppg"),
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True)
    controller.start_pipeline()
    controller.activate_current_analysis(ports)
    controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=False,
        ports=ports,
    )
    controller.configure_analysis(
        rppg_enabled=False,
        fatigue_enabled=True,
        ports=ports,
    )
    controller.configure_analysis(
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


def test_repeating_current_analysis_plan_does_not_restart_workers() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True)
    controller.start_pipeline()
    events: list[str] = []
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: events.append("stop") or True,
        start_combined=lambda: events.append("combined"),
        start_rppg=lambda: events.append("rppg"),
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    plan = controller.configure_analysis(
        rppg_enabled=True,
        fatigue_enabled=True,
        ports=ports,
    )

    assert plan.worker == "combined"
    assert events == []


def test_analysis_reconcile_rolls_back_worker_and_snapshot_on_start_failure() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True)
    controller.start_pipeline()
    events: list[str] = []

    def fail_rppg() -> None:
        events.append("rppg-failed")
        raise RuntimeError("worker failed")

    ports = AnalysisLifecyclePorts(
        stop_all=lambda: events.append("stop") or True,
        start_combined=lambda: events.append("combined"),
        start_rppg=fail_rppg,
        start_fatigue=lambda: events.append("fatigue"),
        restore_raw_routing=lambda: events.append("raw"),
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        controller.configure_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    assert events == ["stop", "rppg-failed", "stop", "combined"]
    assert controller.pipeline_snapshot().analysis.worker == "combined"
    assert controller.analysis_snapshot().worker == "combined"


def test_analysis_reconcile_fails_closed_when_worker_rollback_also_fails() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True)
    controller.start_pipeline()

    def fail(message: str):
        def callback() -> None:
            raise RuntimeError(message)

        return callback

    ports = AnalysisLifecyclePorts(
        stop_all=lambda: True,
        start_combined=fail("rollback failed"),
        start_rppg=fail("new worker failed"),
        start_fatigue=lambda: None,
        restore_raw_routing=lambda: None,
    )

    with pytest.raises(RuntimeError, match="rollback failed"):
        controller.configure_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    snapshot = controller.pipeline_snapshot()
    assert snapshot.running is False
    assert snapshot.cleanup_pending is True
    assert controller.analysis_snapshot().worker == "combined"
    with pytest.raises(RuntimeError, match="cleanup"):
        controller.start_replay()


def test_analysis_reconcile_fails_closed_when_initial_stop_fails() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Camera")])
    controller.configure_analysis(rppg_enabled=True, fatigue_enabled=True)
    controller.start_pipeline()
    ports = AnalysisLifecyclePorts(
        stop_all=lambda: (_ for _ in ()).throw(RuntimeError("stop failed")),
        start_combined=lambda: None,
        start_rppg=lambda: None,
        start_fatigue=lambda: None,
        restore_raw_routing=lambda: None,
    )

    with pytest.raises(RuntimeError, match="stop failed"):
        controller.configure_analysis(
            rppg_enabled=True,
            fatigue_enabled=False,
            ports=ports,
        )

    snapshot = controller.pipeline_snapshot()
    assert snapshot.running is False
    assert snapshot.cleanup_pending is True
