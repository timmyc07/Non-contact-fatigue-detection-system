"""worker 端個人基線注入 / 熱換旗標機制（P5）。

只測純屬性層的執行緒安全旗標，不啟動 Qt event loop / 相機 / MediaPipe 推論。
若環境缺 PySide6 / mediapipe 等 worker 匯入相依，整檔 skip。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest.importorskip("PySide6")

from gui.personal_profile import PersonalProfile  # noqa: E402


def _make_profile() -> PersonalProfile:
    return PersonalProfile(valid=True, source="manual", perclos_awake_p90=0.02)


def test_fatigue_worker_stores_and_hotswaps_profile() -> None:
    fw_mod = pytest.importorskip("gui.fatigue_worker")
    import queue
    prof = _make_profile()
    worker = fw_mod.FatigueWorker(queue.Queue(), personal_profile=prof)
    assert worker._personal_profile is prof
    assert worker._has_pending_profile is False
    new_prof = _make_profile()
    worker.set_personal_profile(new_prof)
    assert worker._has_pending_profile is True
    assert worker._pending_profile is new_prof


def test_combined_worker_stores_and_hotswaps_profile() -> None:
    cw_mod = pytest.importorskip("gui.combined_worker")
    import queue
    prof = _make_profile()
    worker = cw_mod.CombinedWorker(queue.Queue(), personal_profile=prof)
    assert worker._personal_profile is prof
    assert worker._has_pending_profile is False
    worker.set_personal_profile(None)  # 允許清空（回退到無 profile）
    assert worker._has_pending_profile is True
    assert worker._pending_profile is None
