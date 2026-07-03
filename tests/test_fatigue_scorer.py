"""FatigueFuser 融合分數：無資料顯示與等級遲滯（2026-07-03 審核 P1-2 / P1-3 回歸鎖定）。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_scorer import _LEVELS, FatigueFuser  # noqa: E402
from gui.fatigue_engine import FatigueMetrics  # noqa: E402


def test_fuser_no_data_reports_nodata_not_alert() -> None:
    # 兩 pillar 皆失效時不得顯示「清醒」綠燈
    fuser = FatigueFuser()
    out = fuser.update(None, None)

    assert out.level == "無資料"
    assert out.level_en == "NoData"
    assert out.color_bgr == (128, 128, 128)
    assert out.rppg_available is False and out.behavior_available is False


def test_fuser_no_data_does_not_pollute_trend_history() -> None:
    fuser = FatigueFuser()
    fatigue = FatigueMetrics(face_detected=True, calibrated=True)
    fuser.update(None, fatigue)
    n_after_valid = len(fuser._history)

    fuser.update(None, None)
    fuser.update(None, None)

    assert len(fuser._history) == n_after_valid  # 無資料樣本不進 history


def test_level_hysteresis_holds_near_threshold() -> None:
    fuser = FatigueFuser()
    assert fuser._level_with_hysteresis(0.21)[0] == "輕度疲勞"
    # 跌回門檻下但在遲滯帶內（0.20 - 0.03 = 0.17）：維持原級
    assert fuser._level_with_hysteresis(0.19)[0] == "輕度疲勞"
    # 跌破遲滯帶：降級
    assert fuser._level_with_hysteresis(0.16)[0] == "清醒"


def test_level_hysteresis_upgrade_is_immediate() -> None:
    fuser = FatigueFuser()
    assert fuser._level_with_hysteresis(0.05)[0] == "清醒"
    assert fuser._level_with_hysteresis(0.45)[0] == "中度疲勞"  # 跨級上升不延遲
    assert fuser._level_with_hysteresis(0.85)[0] == "極度危險"


def test_level_hysteresis_multi_level_drop_passes_through() -> None:
    fuser = FatigueFuser()
    assert fuser._level_with_hysteresis(0.75)[0] == "高度疲勞"
    # 大幅跌落（遠低於遲滯帶）：直接降到對應級，不逐級卡住
    assert fuser._level_with_hysteresis(0.05)[0] == "清醒"


def test_levels_table_monotonic() -> None:
    thresholds = [t for t, _zh, _en, _col in _LEVELS]
    assert thresholds == sorted(thresholds)
