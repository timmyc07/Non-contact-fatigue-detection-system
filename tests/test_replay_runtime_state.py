from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from gui.replay_runtime_state import ReplayRuntimeState


def test_replay_runtime_state_import_is_qt_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import gui.replay_runtime_state; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_replay_defaults_preserve_desktop_contract() -> None:
    state = ReplayRuntimeState()

    assert state.to_desktop_state() == {
        "replay_dataset_dir": "",
        "replay_jobs": 2,
        "replay_annotated": False,
        "replay_mode": "回放中",
        "replay_total": 0,
        "replay_done": 0,
        "replay_current": "目前影片：--",
        "replay_result": "摘要檔：--",
        "replay_parallel_status": "處理清單：--",
    }


def test_replay_configuration_reset_does_not_erase_progress() -> None:
    state = ReplayRuntimeState()
    state.configure(dataset_dir=Path("dataset"), jobs=4, annotated=True)
    state.update_presentation(
        mode_label="平行驗證中 x4",
        total_count=10,
        done_count=3,
        current_text="目前影片：3/10",
    )

    state.reset_configuration()

    snapshot = state.snapshot()
    assert snapshot.dataset_dir is None
    assert snapshot.jobs == 2
    assert snapshot.annotated is False
    assert snapshot.mode_label == "平行驗證中 x4"
    assert snapshot.total_count == 10
    assert snapshot.done_count == 3


def test_replay_begin_and_finish_preserve_configuration() -> None:
    state = ReplayRuntimeState()
    state.configure(dataset_dir=Path("dataset"), jobs=3, annotated=True)

    state.begin(
        mode_label="平行驗證中 x3",
        parallel_status_text="處理清單：平行驗證等待工作派發",
    )
    started = state.snapshot()
    assert started.current_text == "目前影片：準備中"
    assert started.result_text == "摘要檔：--"
    assert started.total_count == 0
    assert started.done_count == 0

    state.finish_thread()
    assert state.snapshot().mode_label == "回放中"
    assert state.snapshot().jobs == 3
    assert state.snapshot().annotated is True


def test_replay_restore_rolls_back_entire_snapshot() -> None:
    state = ReplayRuntimeState()
    state.configure(dataset_dir=Path("dataset"), jobs=3, annotated=True)
    before = state.snapshot()
    state.begin(mode_label="回放中", parallel_status_text="處理清單：等待")

    state.restore(before)

    assert state.snapshot() == before


@pytest.mark.parametrize("jobs", [0, 5, True, 2.5, "2"])
def test_replay_configuration_rejects_invalid_jobs(jobs: object) -> None:
    with pytest.raises(ValueError, match="jobs"):
        ReplayRuntimeState().configure(jobs=jobs)


@pytest.mark.parametrize("count", [-1, True, 1.5, "1"])
def test_replay_presentation_rejects_invalid_counts(count: object) -> None:
    with pytest.raises(ValueError, match="total_count"):
        ReplayRuntimeState().update_presentation(total_count=count)
