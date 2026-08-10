from __future__ import annotations

from pathlib import Path

import pytest

from gui import alarm_config, mediapipe_tuning, web_server
from gui.runtime_paths import data_path, resource_path
from gui.web_server import MetricsBuffer, PlaybackManager
from rppg import belt_truth_capture, hr_belt_ble, rppg_worker


def test_default_resource_and_data_paths_keep_development_layout() -> None:
    assert mediapipe_tuning.CONFIG_PATH == resource_path(
        "config", "mediapipe_tuning.json"
    )
    assert mediapipe_tuning.CALIBRATION_PATH == data_path(
        "config", "mediapipe_calibration.json"
    )
    assert hr_belt_ble.DEFAULT_CONFIG_PATH == data_path("config", "hr_belt.json")
    assert belt_truth_capture.DEFAULT_CAPTURE_DIR == data_path(
        "recordings", "belt_truth_capture"
    )
    assert rppg_worker._MODELS_DIR == resource_path("models")


def test_missing_tuning_resource_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "immutable" / "config" / "mediapipe_tuning.json"

    tuning = mediapipe_tuning.load_mediapipe_tuning(missing)

    assert tuning.active_profile == "default"
    assert not missing.exists()


def test_default_tuning_is_created_only_in_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tuning_path = tmp_path / "config" / "mediapipe_tuning.json"
    monkeypatch.delenv("NCFD_RESOURCE_ROOT", raising=False)
    monkeypatch.setattr(mediapipe_tuning, "CONFIG_PATH", tuning_path)

    tuning = mediapipe_tuning.load_mediapipe_tuning()

    assert tuning.active_profile == "default"
    assert tuning_path.exists()


def test_packaged_missing_face_model_never_writes_resource_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resource = tmp_path / "resources"
    models = resource / "models"
    models.mkdir(parents=True)
    monkeypatch.setenv("NCFD_RESOURCE_ROOT", str(resource))
    monkeypatch.delenv("NCFD_DATA_ROOT", raising=False)

    with pytest.raises(FileNotFoundError):
        rppg_worker.ensure_face_model(models)

    assert not (models / "face_landmarker.task").exists()


def test_alert_defaults_resolve_from_resource_root(
    tmp_path: Path, monkeypatch
) -> None:
    resource_root = tmp_path / "bundle"
    monkeypatch.setattr(
        alarm_config,
        "resource_path",
        lambda *parts: resource_root.joinpath(*parts),
    )

    assert alarm_config.default_alerts_dir() == resource_root / "assets" / "alerts"
    assert alarm_config.default_sound_path("critical") == str(
        resource_root / "assets" / "alerts" / "critical.wav"
    )


def test_web_ui_resolves_from_resource_root(tmp_path: Path, monkeypatch) -> None:
    resource_root = tmp_path / "bundle"
    monkeypatch.setattr(
        web_server,
        "resource_path",
        lambda *parts: resource_root.joinpath(*parts),
    )

    app, _socketio = web_server.create_app(
        MetricsBuffer(), PlaybackManager(tmp_path / "recordings")
    )

    assert Path(app.template_folder or "") == (
        resource_root / "gui" / "web_ui" / "templates"
    )
    assert Path(app.static_folder or "") == (
        resource_root / "gui" / "web_ui" / "static"
    )
