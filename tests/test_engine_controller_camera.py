from __future__ import annotations

from dataclasses import FrozenInstanceError


import pytest  # noqa: E402

from gui.engine_controller import CameraDevice, EngineController  # noqa: E402


def test_camera_catalog_selects_first_device_and_preserves_selection() -> None:
    controller = EngineController()

    controller.replace_cameras(
        [CameraDevice(0, "Integrated Camera"), CameraDevice(2, "USB Camera")]
    )
    assert controller.camera_snapshot().selected_index == 0

    controller.select_camera(2)
    controller.replace_cameras(
        [CameraDevice(2, "USB Camera"), CameraDevice(3, "Capture Card")]
    )

    snapshot = controller.camera_snapshot()
    assert snapshot.selected_index == 2
    assert snapshot.devices == (
        CameraDevice(2, "USB Camera"),
        CameraDevice(3, "Capture Card"),
    )


def test_camera_catalog_restores_preferred_device_when_it_becomes_available() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(0, "Integrated Camera")])

    controller.restore_camera(5)
    assert controller.camera_snapshot().selected_index == 0

    controller.replace_cameras(
        [CameraDevice(0, "Integrated Camera"), CameraDevice(5, "USB Camera")]
    )

    assert controller.camera_snapshot().selected_index == 5


def test_camera_configure_validates_atomically() -> None:
    controller = EngineController()
    controller.configure_camera(
        resolution="800×600",
        backend="ffmpeg",
        horizontal_flip=False,
    )
    configured = controller.camera_snapshot()
    assert configured.resolution == "800×600"
    assert configured.fps == "30"
    assert configured.backend == "ffmpeg"
    assert configured.horizontal_flip is False

    try:
        controller.configure_camera(resolution="320×240", fps="60")
    except ValueError as exc:
        assert "resolution" in str(exc).lower()
    else:
        raise AssertionError("Unsupported resolution must be rejected")

    assert controller.camera_snapshot() == configured

    with pytest.raises(ValueError, match="FPS"):
        controller.configure_camera(fps="60")
    assert controller.camera_snapshot() == configured


@pytest.mark.parametrize(
    ("resolution", "expected_size"),
    [
        ("640×480", (640, 480)),
        ("800×600", (800, 600)),
        ("1280×720（720p）", (1280, 720)),
        ("1280×800", (1280, 800)),
        ("1920×1080（1080p）", (1920, 1080)),
    ],
)
def test_camera_start_spec_preserves_legacy_resolution_mapping(
    resolution: str, expected_size: tuple[int, int]
) -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(4, "[4] USB Camera")])
    controller.configure_camera(
        resolution=resolution,
        fps="30",
        backend="ffmpeg",
        horizontal_flip=False,
    )

    spec = controller.camera_start_spec()

    assert (spec.width, spec.height) == expected_size
    assert spec.index == 4
    assert spec.target_fps == 30
    assert spec.backend == "ffmpeg"
    assert spec.horizontal_flip is False
    assert spec.camera_label == "[4] USB Camera"


def test_camera_snapshot_is_an_immutable_copy() -> None:
    controller = EngineController()
    first = controller.camera_snapshot()
    second = controller.camera_snapshot()

    assert first == second
    assert first is not second
    with pytest.raises(FrozenInstanceError):
        first.fps = "60"  # type: ignore[misc]


def test_reset_camera_settings_preserves_catalog_and_selection() -> None:
    controller = EngineController()
    controller.replace_cameras([CameraDevice(4, "USB Camera")])
    controller.configure_camera(
        resolution="1920×1080（1080p）",
        fps="30",
        backend="ffmpeg",
        horizontal_flip=False,
    )

    controller.reset_camera_settings()

    snapshot = controller.camera_snapshot()
    assert snapshot.devices == (CameraDevice(4, "USB Camera"),)
    assert snapshot.selected_index == 4
    assert snapshot.resolution == "1280×720（720p）"
    assert snapshot.fps == "30"
    assert snapshot.backend == "ffmpeg"
    assert snapshot.horizontal_flip is True
