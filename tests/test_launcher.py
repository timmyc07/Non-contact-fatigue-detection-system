from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import main as launcher


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_entry_reuses_app_font_cache_after_pyinstaller_hook(
    tmp_path, monkeypatch,
) -> None:
    runtime = tmp_path / "runtime-data"
    cache = runtime / "cache" / "matplotlib"
    cache.mkdir(parents=True)
    previous = cache / "fontlist-v390.json"
    previous.write_text('{"existing": true}', encoding="utf-8")
    observed = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("NCFD_DATA_ROOT", str(runtime))
    monkeypatch.setattr(sys, "argv", ["ncfd-engine", "--runtime-preflight-face-landmarker"])

    def before_first_mediapipe_import():
        observed.append(os.environ["MPLCONFIGDIR"])
        return 0

    monkeypatch.setattr(launcher, "_run_face_landmarker_preflight", before_first_mediapipe_import)
    for hook_cache in (tmp_path / "hook-first", tmp_path / "hook-second"):
        monkeypatch.setenv("MPLCONFIGDIR", str(hook_cache))
        assert launcher.main() == 0

    assert observed == [str(cache), str(cache)]
    assert previous.read_text(encoding="utf-8") == '{"existing": true}'


@pytest.mark.parametrize("configured", [False, True])
def test_source_entry_preserves_matplotlib_environment(tmp_path, monkeypatch, configured) -> None:
    runtime = tmp_path / "runtime-data"
    user_cache = str(tmp_path / "user-matplotlib") if configured else None
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("NCFD_DATA_ROOT", str(runtime))
    if user_cache is None:
        monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    else:
        monkeypatch.setenv("MPLCONFIGDIR", user_cache)
    monkeypatch.setattr(sys, "argv", ["main.py", "--runtime-preflight-face-landmarker"])
    monkeypatch.setattr(launcher, "_run_face_landmarker_preflight", lambda: 0)

    assert launcher.main() == 0
    assert os.environ.get("MPLCONFIGDIR") == user_cache
    assert not runtime.exists()


@pytest.mark.parametrize("failure", ["mkdir", "write"])
def test_unwritable_app_cache_retains_pyinstaller_temporary_cache(
    tmp_path, monkeypatch, failure,
) -> None:
    runtime = tmp_path / "runtime-data"
    hook_cache = str(tmp_path / "secure-hook-cache")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("NCFD_DATA_ROOT", str(runtime))
    monkeypatch.setenv("MPLCONFIGDIR", hook_cache)
    monkeypatch.setattr(sys, "argv", ["ncfd-engine", "--runtime-preflight-face-landmarker"])
    observed = []
    if failure == "mkdir":
        runtime.mkdir()
        (runtime / "cache").write_text("Existing user file", encoding="utf-8")

    def deny_cache_write(*_args, **_kwargs):
        raise PermissionError("Cache is read-only")

    monkeypatch.setattr("tempfile.TemporaryFile", deny_cache_write)
    monkeypatch.setattr(launcher, "_run_face_landmarker_preflight",
                        lambda: observed.append(os.environ["MPLCONFIGDIR"]) or 0)

    assert launcher.main() == 0
    assert observed == [hook_cache]
    if failure == "mkdir":
        assert (runtime / "cache").read_text(encoding="utf-8") == "Existing user file"


def test_desktop_launcher_uses_asset_preparation_and_propagates_exit_code(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/tools/{name}")

    def call(command, *, cwd):
        calls.append((command, cwd))
        return 23

    monkeypatch.setattr(launcher.subprocess, "call", call)

    assert launcher._launch_tauri() == 23
    assert calls == [(["/tools/npm", "run", "desktop"], ROOT)]


def test_legacy_panel_flag_is_rejected_without_starting_qt() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--legacy-ui"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "舊版 PySide 主面板已移除" in result.stdout
    assert "npm run desktop" in result.stdout


@pytest.mark.parametrize("cleanup_complete", [True, False])
def test_engine_entry_creates_only_headless_application_adapter(
    monkeypatch, capsys, cleanup_complete,
) -> None:
    events: list[object] = []

    class FakeApplication:
        def __init__(self, args: list[str]) -> None:
            events.append(("app", args))

        def setQuitOnLastWindowClosed(self, enabled: bool) -> None:  # noqa: N802
            events.append(("quit_on_last_window", enabled))

        def setStyle(self, _style: str) -> None:  # noqa: N802
            raise AssertionError("engine mode must not apply a visual Qt style")

        def setStyleSheet(self, _stylesheet: str) -> None:  # noqa: N802
            raise AssertionError("engine mode must not apply a visual stylesheet")

        def exec(self) -> int:
            return 0

    class FakeEngineApplication:
        def __init__(self) -> None:
            events.append("engine_application")

        def close_runtime(self) -> bool:
            events.append("engine_close")
            return cleanup_complete

    monkeypatch.setattr(launcher, "QApplication", FakeApplication)
    monkeypatch.setattr(launcher, "EngineApplication", FakeEngineApplication)
    monkeypatch.setattr(launcher, "_missing_linux_qt_runtime_libraries", lambda: [])
    monkeypatch.setattr(sys, "argv", ["main.py", "--engine"])

    assert launcher.main() == (0 if cleanup_complete else 1)
    assert ("cleanup did not complete" in capsys.readouterr().err) is not cleanup_complete
    assert events == [
        ("app", ["main.py"]),
        ("quit_on_last_window", False),
        "engine_application",
        "engine_close",
    ]
