from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


_UNSET = object()


@dataclass(frozen=True, slots=True)
class ReplayRuntimeSnapshot:
    dataset_dir: Path | None = None
    jobs: int = 2
    annotated: bool = False
    mode_label: str = "回放中"
    total_count: int = 0
    done_count: int = 0
    current_text: str = "目前影片：--"
    result_text: str = "摘要檔：--"
    parallel_status_text: str = "處理清單：--"


class ReplayRuntimeState:
    """Own replay configuration and presentation state without importing Qt."""

    def __init__(self) -> None:
        self._state = ReplayRuntimeSnapshot()

    def snapshot(self) -> ReplayRuntimeSnapshot:
        return replace(self._state)

    def restore(self, snapshot: ReplayRuntimeSnapshot) -> ReplayRuntimeSnapshot:
        if not isinstance(snapshot, ReplayRuntimeSnapshot):
            raise ValueError("snapshot must be a ReplayRuntimeSnapshot")
        self._state = replace(snapshot)
        return self.snapshot()

    def configure(
        self,
        *,
        dataset_dir: object = _UNSET,
        jobs: object = _UNSET,
        annotated: object = _UNSET,
    ) -> ReplayRuntimeSnapshot:
        changes: dict[str, Any] = {}
        if dataset_dir is not _UNSET:
            if dataset_dir is not None and not isinstance(dataset_dir, Path):
                raise ValueError("dataset_dir must be a Path or None")
            changes["dataset_dir"] = dataset_dir
        if jobs is not _UNSET:
            if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 4:
                raise ValueError("jobs must be between 1 and 4")
            changes["jobs"] = jobs
        if annotated is not _UNSET:
            if not isinstance(annotated, bool):
                raise ValueError("annotated must be a boolean")
            changes["annotated"] = annotated
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def update_presentation(
        self,
        *,
        mode_label: object = _UNSET,
        total_count: object = _UNSET,
        done_count: object = _UNSET,
        current_text: object = _UNSET,
        result_text: object = _UNSET,
        parallel_status_text: object = _UNSET,
    ) -> ReplayRuntimeSnapshot:
        changes: dict[str, Any] = {}
        for name, value in (
            ("mode_label", mode_label),
            ("current_text", current_text),
            ("result_text", result_text),
            ("parallel_status_text", parallel_status_text),
        ):
            if value is _UNSET:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            changes[name] = value
        for name, value in (
            ("total_count", total_count),
            ("done_count", done_count),
        ):
            if value is _UNSET:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            changes[name] = value
        if changes:
            self._state = replace(self._state, **changes)
        return self.snapshot()

    def begin(self, *, mode_label: str, parallel_status_text: str) -> ReplayRuntimeSnapshot:
        return self.update_presentation(
            mode_label=mode_label,
            total_count=0,
            done_count=0,
            current_text="目前影片：準備中",
            result_text="摘要檔：--",
            parallel_status_text=parallel_status_text,
        )

    def finish_thread(self) -> ReplayRuntimeSnapshot:
        return self.update_presentation(mode_label="回放中")

    def reset_configuration(self) -> ReplayRuntimeSnapshot:
        self._state = replace(
            self._state,
            dataset_dir=None,
            jobs=2,
            annotated=False,
        )
        return self.snapshot()

    def to_desktop_state(self) -> dict[str, object]:
        state = self._state
        return {
            "replay_dataset_dir": str(state.dataset_dir or ""),
            "replay_jobs": state.jobs,
            "replay_annotated": state.annotated,
            "replay_mode": state.mode_label,
            "replay_total": state.total_count,
            "replay_done": state.done_count,
            "replay_current": state.current_text,
            "replay_result": state.result_text,
            "replay_parallel_status": state.parallel_status_text,
        }
