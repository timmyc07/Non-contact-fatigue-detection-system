from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from gui import model_assets


def test_download_verifies_pinned_model_before_atomic_publish(tmp_path: Path, monkeypatch) -> None:
    content = b"verified model"
    monkeypatch.setattr(model_assets, "MODEL_SHA256", hashlib.sha256(content).hexdigest())
    calls = []

    def urlopen(url: str, timeout: int):
        calls.append((url, timeout))
        return io.BytesIO(content)

    monkeypatch.setattr(model_assets.urllib.request, "urlopen", urlopen)
    target = tmp_path / "models/face_landmarker.task"

    assert model_assets.download_face_model(target) == target
    assert target.read_bytes() == content
    assert calls == [(model_assets.MODEL_URL, 30)]
    assert "/float16/1/" in model_assets.MODEL_URL
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("existing", [False, True])
def test_unverified_download_never_changes_target(tmp_path: Path, monkeypatch, existing: bool) -> None:
    target = tmp_path / "face_landmarker.task"
    if existing:
        target.write_bytes(b"old model")
    monkeypatch.setattr(model_assets.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"invalid"))

    with pytest.raises(ValueError, match="SHA-256"):
        model_assets.download_face_model(target)

    if existing:
        assert target.read_bytes() == b"old model"
    else:
        assert not target.exists()
    assert list(tmp_path.iterdir()) == ([target] if existing else [])


def test_interrupted_download_leaves_no_target(tmp_path: Path, monkeypatch) -> None:
    class InterruptedResponse(io.BytesIO):
        def read(self, *_args):
            raise TimeoutError("interrupted")

    monkeypatch.setattr(model_assets.urllib.request, "urlopen", lambda *_args, **_kwargs: InterruptedResponse())

    with pytest.raises(TimeoutError, match="interrupted"):
        model_assets.download_face_model(tmp_path / "face_landmarker.task")

    assert list(tmp_path.iterdir()) == []


def test_publish_failure_removes_temporary_file_and_keeps_old_model(tmp_path: Path, monkeypatch) -> None:
    content = b"verified model"
    target = tmp_path / "face_landmarker.task"
    target.write_bytes(b"old model")
    monkeypatch.setattr(model_assets, "MODEL_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(model_assets.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(content))

    def replace(*_args):
        raise PermissionError("locked target")

    monkeypatch.setattr(model_assets.os, "replace", replace)

    with pytest.raises(PermissionError, match="locked target"):
        model_assets.download_face_model(target)

    assert target.read_bytes() == b"old model"
    assert list(tmp_path.iterdir()) == [target]


def test_worker_keeps_existing_custom_model_without_network(tmp_path: Path, monkeypatch) -> None:
    from rppg import rppg_worker

    target = tmp_path / "face_landmarker.task"
    target.write_bytes(b"x" * 1_000_001)
    monkeypatch.setattr(rppg_worker, "validate_mediapipe_runtime", lambda: None)
    monkeypatch.setattr(rppg_worker, "download_face_model", lambda _target: pytest.fail("unexpected download"))

    assert rppg_worker.ensure_face_model(tmp_path) == target


def test_worker_repairs_small_source_model_using_verified_download(tmp_path: Path, monkeypatch) -> None:
    from rppg import rppg_worker

    target = tmp_path / "face_landmarker.task"
    target.write_bytes(b"partial model")
    calls = []
    statuses = []
    monkeypatch.setattr(rppg_worker, "validate_mediapipe_runtime", lambda: None)
    monkeypatch.setattr(rppg_worker.sys, "frozen", False, raising=False)
    monkeypatch.delenv("NCFD_RESOURCE_ROOT", raising=False)
    monkeypatch.setattr(rppg_worker, "download_face_model", calls.append)

    assert rppg_worker.ensure_face_model(tmp_path, statuses.append) == target
    assert calls == [target]
    assert statuses[-1] == "模型下載完成"
