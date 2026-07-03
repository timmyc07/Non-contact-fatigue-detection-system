"""FatigueFuser 融合分數：無資料顯示與等級遲滯（2026-07-03 審核 P1-2 / P1-3 回歸鎖定）。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_scorer import _LEVELS, FatigueFuser, FuserConfig  # noqa: E402
from gui.fatigue_engine import FatigueMetrics  # noqa: E402


def test_perclos_scores_in_actual_operating_range() -> None:
    # 2026-07-03 準確度校準：PERCLOS 計分門檻對齊系統實際 operating range
    # （清醒~0.006、嗜睡~0.031）。嗜睡級 PERCLOS 必須產生有意義的行為分數，
    # 清醒級接近 0——這是把 AUC 0.79 訊號從「恆為 0」救回輸出的關鍵回歸鎖定。
    drowsy = FatigueMetrics(face_detected=True, calibrated=True, perclos=0.03, fatigue_level=0.0)
    alert = FatigueMetrics(face_detected=True, calibrated=True, perclos=0.005, fatigue_level=0.0)
    s_drowsy = FatigueFuser().update(None, drowsy)
    s_alert = FatigueFuser().update(None, alert)
    assert s_drowsy.behavior_sub > s_alert.behavior_sub
    assert s_drowsy.behavior_sub > 0.08   # 嗜睡 PERCLOS 現在有實質分數（舊門檻下為 0）
    assert s_alert.behavior_sub < 0.03    # 清醒仍接近 0


def test_perclos_weight_dominates_behavior() -> None:
    # PERCLOS 為此資料上唯一強訊號（AUC 0.79），必須是行為柱最大權重
    cfg = FuserConfig()
    assert cfg.beh_w_perclos >= 0.50
    assert cfg.beh_w_perclos > cfg.beh_w_microsleep + cfg.beh_w_blink_temporal
    weights = (cfg.beh_w_perclos + cfg.beh_w_blink_temporal + cfg.beh_w_microsleep
               + cfg.beh_w_gaze + cfg.beh_w_squint + cfg.beh_w_yawn + cfg.beh_w_frown)
    assert abs(weights - 1.0) < 1e-9   # 行為子權重仍總和為 1


def test_perclos_sentinel_eff_matches_cfg_defaults() -> None:
    # P1 向後相容：哨兵 -1（預設）必須與明確帶 cfg 預設門檻算出相同分數（bit-identical）。
    sentinel = FatigueMetrics(face_detected=True, calibrated=True, perclos=0.03)
    explicit = FatigueMetrics(
        face_detected=True, calibrated=True, perclos=0.03,
        perclos_mild_th_eff=0.015, perclos_high_th_eff=0.07,
    )
    s_sent = FatigueFuser().update(None, sentinel).behavior_sub
    s_expl = FatigueFuser().update(None, explicit).behavior_sub
    assert s_sent == s_expl


def test_perclos_personalized_thresholds_shift_score() -> None:
    # P1：清醒時 PERCLOS 本就偏高的駕駛員，個人化門檻拉高 → 同一 PERCLOS 得較低分（更寬容）。
    base = FatigueMetrics(face_detected=True, calibrated=True, perclos=0.03)
    personalized = FatigueMetrics(
        face_detected=True, calibrated=True, perclos=0.03,
        perclos_mild_th_eff=0.03, perclos_high_th_eff=0.12,
    )
    s_base = FatigueFuser().update(None, base).behavior_sub
    s_pers = FatigueFuser().update(None, personalized).behavior_sub
    assert s_pers < s_base


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
