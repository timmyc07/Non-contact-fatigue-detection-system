from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from scripts import prepare_local_assets as assets


def test_missing_icons_are_valid_for_desktop_and_android(tmp_path: Path) -> None:
    created = assets.prepare_icons(tmp_path)

    assert len(created) == 11
    for path in created:
        with Image.open(path) as image:
            image.load()
            assert image.width == image.height
            assert image.mode == "RGBA"
    with Image.open(tmp_path / "src-tauri/icons/icon-windows.ico") as icon:
        assert {(size, size) for size in (16, 24, 32, 48, 64, 256)} <= icon.info["sizes"]
    for density, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96),
                          ("xxhdpi", 144), ("xxxhdpi", 192)):
        with Image.open(tmp_path / f"flutter_app/android/app/src/main/res/mipmap-{density}/ic_launcher.png") as icon:
            assert icon.size == (size, size)
    assert not (tmp_path / "models/face_landmarker.task").exists()


def test_existing_icons_are_preserved_and_reused(tmp_path: Path) -> None:
    source = tmp_path / "src-tauri/icons/icon.png"
    source.parent.mkdir(parents=True)
    Image.new("RGBA", (128, 128), "red").save(source)
    original = source.read_bytes()

    assets.prepare_icons(tmp_path)

    assert source.read_bytes() == original
    with Image.open(source.parent / "32x32.png") as icon:
        assert icon.getpixel((16, 16)) == (255, 0, 0, 255)
    assert assets.prepare_icons(tmp_path) == []


def test_model_download_is_opt_in_and_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(assets, "ROOT", tmp_path)
    monkeypatch.setattr(assets, "prepare_icons", lambda: [])
    monkeypatch.setattr(assets, "download_face_model", calls.append)
    monkeypatch.setattr(sys, "argv", ["prepare_local_assets"])

    assert assets.main() == 0
    assert calls == []
    monkeypatch.setattr(sys, "argv", ["prepare_local_assets", "--download-model"])
    assert assets.main() == 0
    target = tmp_path / "models/face_landmarker.task"
    assert calls == [target]
    target.parent.mkdir()
    target.write_bytes(b"custom model")
    assert assets.main() == 0
    assert calls == [target]
    assert target.read_bytes() == b"custom model"
