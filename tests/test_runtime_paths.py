from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

import pytest

from gui.runtime_paths import data_path, data_root, resource_path, resource_root


def test_resource_root_uses_configured_root_before_frozen_bundle(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-resources"
    bundle = tmp_path / "bundle"

    resolved = resource_root(
        env={"NCFD_RESOURCE_ROOT": str(configured)},
        frozen=True,
        meipass=bundle,
        module_file=tmp_path / "repo" / "gui" / "runtime_paths.py",
    )

    assert resolved == configured


def test_resource_root_uses_pyinstaller_bundle_when_frozen(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"

    resolved = resource_root(
        env={},
        frozen=True,
        meipass=bundle,
        module_file=tmp_path / "repo" / "gui" / "runtime_paths.py",
    )

    assert resolved == bundle


def test_resource_root_uses_repo_layout_in_development(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"

    resolved = resource_root(
        env={},
        frozen=False,
        module_file=repo_root / "gui" / "runtime_paths.py",
    )

    assert resolved == repo_root


@pytest.mark.parametrize(
    ("platform", "environment", "expected_relative"),
    [
        (
            "win32",
            {"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            Path("C:/Users/test/AppData/Local") / "FatigueMonitor",
        ),
        ("darwin", {}, Path("Library") / "Application Support" / "FatigueMonitor"),
        ("linux", {}, Path(".local") / "share" / "FatigueMonitor"),
    ],
)
def test_packaged_data_root_uses_per_user_storage(
    tmp_path: Path,
    platform: str,
    environment: dict[str, str],
    expected_relative: Path,
) -> None:
    home = tmp_path / "home"

    resolved = data_root(
        env=environment,
        frozen=True,
        platform=platform,
        home=home,
    )

    if platform == "win32":
        assert resolved == expected_relative
    else:
        assert resolved == home / expected_relative


def test_data_root_prefers_configured_directory_and_development_repo(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    configured = tmp_path / "runtime-data"
    module_file = repo_root / "gui" / "runtime_paths.py"

    assert data_root(
        env={"NCFD_DATA_ROOT": str(configured)},
        frozen=True,
        platform="win32",
        module_file=module_file,
    ) == configured
    assert data_root(env={}, frozen=False, module_file=module_file) == repo_root


def test_paths_stay_beneath_the_selected_roots(tmp_path: Path) -> None:
    resource = tmp_path / "resources"
    data = tmp_path / "data"

    assert resource_path(
        "models",
        "face_landmarker.task",
        env={"NCFD_RESOURCE_ROOT": str(resource)},
    ) == resource / "models" / "face_landmarker.task"
    assert data_path(
        "config",
        "personal_profile",
        "active.json",
        env={"NCFD_DATA_ROOT": str(data)},
    ) == data / "config" / "personal_profile" / "active.json"


@pytest.mark.parametrize("resolver", [resource_path, data_path])
def test_paths_reject_absolute_components(
    resolver: Callable[..., Path], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="relative"):
        resolver(tmp_path / "outside", env={})


@pytest.mark.skipif(os.name != "nt", reason="Windows rooted-relative semantics")
@pytest.mark.parametrize("resolver", [resource_path, data_path])
def test_paths_reject_windows_rooted_relative_components(
    resolver: Callable[..., Path],
) -> None:
    with pytest.raises(ValueError, match="relative"):
        resolver(r"\outside", env={})


@pytest.mark.parametrize("resolver", [resource_path, data_path])
@pytest.mark.parametrize("component", ["../outside", "safe/../../outside"])
def test_paths_reject_parent_directory_components(
    resolver: Callable[..., Path], component: str
) -> None:
    with pytest.raises(ValueError, match="must not include"):
        resolver(component, env={})


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs Windows privileges")
@pytest.mark.parametrize("resolver", [resource_path, data_path])
def test_paths_reject_existing_symlink_escape(
    resolver: Callable[..., Path], tmp_path: Path
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    env_name = (
        "NCFD_RESOURCE_ROOT" if resolver is resource_path else "NCFD_DATA_ROOT"
    )

    with pytest.raises(ValueError, match="escapes"):
        resolver("link", "data.json", env={env_name: str(root)})
