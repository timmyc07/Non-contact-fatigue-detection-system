from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib
import logging
import queue

import pytest

import scripts.runtime_preflight as runtime_preflight
from gui.platforms import (
    CAPABILITY_IDS,
    DESKTOP_PLATFORM_IDS,
    MEDIAPIPE_RUNTIME_VERSION,
    MOBILE_PLATFORM_IDS,
    OPENCV_RUNTIME_DISTRIBUTION,
    OPENCV_RUNTIME_VERSION,
    UnsupportedDesktopEngineError,
    create_face_landmarker_base_options,
    get_desktop_platform_runtime,
    get_platform_descriptor,
    normalize_platform_name,
    require_desktop_engine_support,
    validate_mediapipe_runtime,
)
from gui.worker_safety import fail_closed_worker


ROOT = Path(__file__).resolve().parents[1]


class _FakeBaseOptions:
    Delegate = SimpleNamespace(CPU="cpu")

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


_FAKE_MP_PYTHON = SimpleNamespace(BaseOptions=_FakeBaseOptions)


def test_windows_and_macos_runtime_policies_are_separate() -> None:
    windows = get_desktop_platform_runtime("win32")
    macos = get_desktop_platform_runtime("darwin")

    assert windows.key == "windows"
    assert windows.preferred_camera_api_names[:2] == ("CAP_DSHOW", "CAP_MSMF")
    assert windows.force_mediapipe_cpu_delegate is False
    assert macos.key == "macos"
    assert macos.preferred_camera_api_names[0] == "CAP_AVFOUNDATION"
    assert macos.force_mediapipe_cpu_delegate is True


def test_five_platform_registry_is_explicit_and_mobile_is_fail_closed() -> None:
    assert set(DESKTOP_PLATFORM_IDS) == {"windows", "macos", "linux"}
    assert set(MOBILE_PLATFORM_IDS) == {"android", "ios"}
    assert normalize_platform_name("win32") == "windows"
    assert normalize_platform_name("darwin") == "macos"
    assert get_platform_descriptor("android").status == "planned"
    assert get_platform_descriptor("ios").native_inference_ready is False
    assert get_platform_descriptor("linux").artifact_types == ("appimage", "deb")
    for platform_name in ("windows", "macos", "linux", "android", "ios"):
        descriptor = get_platform_descriptor(platform_name)
        assert descriptor.key == platform_name
        assert descriptor.capabilities <= CAPABILITY_IDS
        assert descriptor.artifact_types
    with pytest.raises(UnsupportedDesktopEngineError, match="android"):
        require_desktop_engine_support("android")
    with pytest.raises(UnsupportedDesktopEngineError, match="ios"):
        get_desktop_platform_runtime("ios")


def test_mediapipe_runtime_version_is_locked_for_cross_platform_parity() -> None:
    assert validate_mediapipe_runtime(
        platform_name="darwin", version=MEDIAPIPE_RUNTIME_VERSION
    ) == MEDIAPIPE_RUNTIME_VERSION
    assert validate_mediapipe_runtime(
        platform_name="win32", version=MEDIAPIPE_RUNTIME_VERSION
    ) == MEDIAPIPE_RUNTIME_VERSION

    with pytest.raises(RuntimeError, match="1.0.1"):
        validate_mediapipe_runtime(platform_name="darwin", version="1.0.1")


def test_macos_forces_cpu_but_windows_preserves_delegate_default() -> None:
    macos = create_face_landmarker_base_options(
        _FAKE_MP_PYTHON,
        "/tmp/model.task",
        platform_name="darwin",
        version=MEDIAPIPE_RUNTIME_VERSION,
    )
    windows = create_face_landmarker_base_options(
        _FAKE_MP_PYTHON,
        "/tmp/model.task",
        platform_name="win32",
        version=MEDIAPIPE_RUNTIME_VERSION,
    )

    assert macos.kwargs == {"model_asset_path": "/tmp/model.task", "delegate": "cpu"}
    assert windows.kwargs == {"model_asset_path": "/tmp/model.task"}


def test_requirements_pin_validated_mediapipe_version() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert f"mediapipe=={MEDIAPIPE_RUNTIME_VERSION}" in requirements
    assert (
        f"{OPENCV_RUNTIME_DISTRIBUTION}=={OPENCV_RUNTIME_VERSION}" in requirements
    )
    assert "\nopencv-python" not in requirements


def test_desktop_start_scripts_run_runtime_preflight() -> None:
    macos_script = (ROOT / "scripts" / "start_desktop_macos.sh").read_text(
        encoding="utf-8"
    )
    windows_script = (ROOT / "scripts" / "start_desktop.ps1").read_text(
        encoding="utf-8"
    )

    assert macos_script.index("scripts.runtime_preflight") < macos_script.index(
        "npm run desktop"
    )
    assert windows_script.index("scripts.runtime_preflight") < windows_script.index(
        "npm run desktop"
    )


def test_runtime_preflight_reports_missing_import(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "cv2":
            raise ImportError("missing cv2")
        return object()

    monkeypatch.setattr(runtime_preflight, "import_module", fake_import)
    monkeypatch.setattr(runtime_preflight, "validate_mediapipe_runtime", lambda: "0.10.35")
    monkeypatch.setattr(
        runtime_preflight,
        "installed_opencv_distributions",
        lambda: {OPENCV_RUNTIME_DISTRIBUTION: OPENCV_RUNTIME_VERSION},
    )

    assert any("missing cv2" in error for error in runtime_preflight.check_runtime())


def test_runtime_preflight_reports_bad_mediapipe_and_missing_backend(monkeypatch) -> None:
    fake_cv2 = object()
    monkeypatch.setattr(
        runtime_preflight,
        "import_module",
        lambda name: fake_cv2 if name == "cv2" else object(),
    )
    monkeypatch.setattr(
        runtime_preflight,
        "validate_mediapipe_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("bad mediapipe")),
    )
    monkeypatch.setattr(
        runtime_preflight,
        "get_desktop_platform_runtime",
        lambda: SimpleNamespace(
            key="macos",
            preferred_camera_api_names=("CAP_AVFOUNDATION", "CAP_ANY"),
        ),
    )
    monkeypatch.setattr(
        runtime_preflight,
        "installed_opencv_distributions",
        lambda: {OPENCV_RUNTIME_DISTRIBUTION: OPENCV_RUNTIME_VERSION},
    )

    errors = runtime_preflight.check_runtime()

    assert "bad mediapipe" in errors
    assert any("CAP_AVFOUNDATION" in error for error in errors)


def test_runtime_preflight_failure_exit_code_is_78(monkeypatch) -> None:
    monkeypatch.setattr(runtime_preflight, "check_runtime", lambda: ["broken"])

    assert runtime_preflight.main() == 78


@pytest.mark.parametrize("camera_apis,loaded,expected", [((), False, False), ((1200,), False, False), ((1200,), True, True)])
def test_runtime_preflight_checks_registered_camera_backend(monkeypatch, camera_apis, loaded, expected):
    fake_cv2 = SimpleNamespace(
        CAP_ANY=0, CAP_AVFOUNDATION=1200,
        videoio_registry=SimpleNamespace(getCameraBackends=lambda: camera_apis, hasBackend=lambda api: loaded),
    )
    monkeypatch.setattr(runtime_preflight, "import_module", lambda name: fake_cv2 if name == "cv2" else object())
    monkeypatch.setattr(runtime_preflight, "validate_mediapipe_runtime", lambda: "0.10.35")
    monkeypatch.setattr(runtime_preflight, "installed_opencv_distributions", lambda: {OPENCV_RUNTIME_DISTRIBUTION: OPENCV_RUNTIME_VERSION})
    monkeypatch.setattr(runtime_preflight, "get_desktop_platform_runtime", lambda: get_desktop_platform_runtime("darwin"))
    assert (runtime_preflight.check_runtime() == []) is expected


def test_runtime_preflight_rejects_multiple_opencv_distributions(monkeypatch) -> None:
    monkeypatch.setattr(runtime_preflight, "import_module", lambda _name: object())
    monkeypatch.setattr(runtime_preflight, "validate_mediapipe_runtime", lambda: "0.10.35")
    monkeypatch.setattr(
        runtime_preflight,
        "installed_opencv_distributions",
        lambda: {
            OPENCV_RUNTIME_DISTRIBUTION: OPENCV_RUNTIME_VERSION,
            "opencv-python": OPENCV_RUNTIME_VERSION,
        },
    )
    monkeypatch.setattr(
        runtime_preflight,
        "get_desktop_platform_runtime",
        lambda: SimpleNamespace(key="generic", preferred_camera_api_names=("CAP_ANY",)),
    )

    assert any("opencv-python" in error for error in runtime_preflight.check_runtime())


def test_runtime_preflight_runs_face_landmarker_in_subprocess(monkeypatch) -> None:
    monkeypatch.setattr(runtime_preflight, "check_runtime", lambda: [])
    monkeypatch.setattr(runtime_preflight, "run_face_landmarker_smoke", lambda: None)

    assert runtime_preflight.main() == 0


def test_runtime_preflight_reports_face_landmarker_subprocess_failure(monkeypatch) -> None:
    monkeypatch.setattr(runtime_preflight, "check_runtime", lambda: [])
    monkeypatch.setattr(
        runtime_preflight,
        "run_face_landmarker_smoke",
        lambda: "native abort",
    )

    assert runtime_preflight.main() == 78


@pytest.mark.parametrize(
    ("module_name", "worker_name"),
    [
        ("gui.fatigue_worker", "FatigueWorker"),
        ("gui.combined_worker", "CombinedWorker"),
        ("rppg.rppg_worker", "RppgWorker"),
    ],
)
def test_analysis_worker_initialization_failure_emits_failed_and_finished(
    monkeypatch,
    module_name: str,
    worker_name: str,
) -> None:
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "ensure_face_model", lambda *_args, **_kwargs: Path("model.task"))
    monkeypatch.setattr(
        module,
        "create_face_landmarker_base_options",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("init failed")),
    )
    worker = getattr(module, worker_name)(queue.Queue())
    failures: list[str] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert failures and "init failed" in failures[0]
    assert finished == [True]


def test_fail_closed_worker_decorator_emits_failed_and_finished() -> None:
    class _Signal:
        def __init__(self) -> None:
            self.values: list[object] = []

        def emit(self, *values: object) -> None:
            self.values.append(values[0] if len(values) == 1 else values)

    class _Worker:
        def __init__(self) -> None:
            self.failed = _Signal()
            self.finished = _Signal()

        @fail_closed_worker("測試 worker", logging.getLogger(__name__))
        def run(self) -> None:
            raise RuntimeError("unexpected failure")

    worker = _Worker()
    worker.run()

    assert worker.failed.values == ["測試 worker失敗：unexpected failure"]
    assert worker.finished.values == [()]
