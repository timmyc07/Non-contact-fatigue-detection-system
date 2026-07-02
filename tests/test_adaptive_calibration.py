"""Tests for online adaptive rPPG BPM calibration (belt truth → rPPG offset nudge)."""

from __future__ import annotations

import pytest

from rppg.adaptive_calibration import (
    CONF_LOW,
    OnlineBpmCalibrator,
)
from rppg.calibration import apply_bpm_calibration


def _good_rppg(bpm: float, *, raw_bpm: float | None = None) -> dict:
    """通過品質門檻的 rPPG 樣本 dict。"""
    return {
        "bpm": float(bpm),
        "raw_bpm": float(raw_bpm if raw_bpm is not None else bpm),
        "sqi": 0.8,
        "quality_score": 0.8,
        "warmup_progress": 1.0,
        "roi_valid_count": 4,
        "bpm_guarded": False,
    }


def _feed(cal: OnlineBpmCalibrator, belt: float, rppg_bpm: float, n: int, *, start: float = 0.0):
    """以 1 秒間隔餵入 n 筆良好配對觀測。"""
    for i in range(n):
        cal.observe(start + i, belt, True, True, _good_rppg(rppg_bpm))


# ── 初始化與防呆 ─────────────────────────────────────────────────────────────

def test_initial_offset_clamped():
    cal = OnlineBpmCalibrator(initial_offset=100.0, max_abs_offset_bpm=25.0)
    assert cal.offset == 25.0
    cal2 = OnlineBpmCalibrator(initial_offset=-100.0, max_abs_offset_bpm=25.0)
    assert cal2.offset == -25.0


def test_initial_state_is_low_confidence():
    st = OnlineBpmCalibrator().state()
    assert st.confidence == CONF_LOW
    assert st.pairs_used == 0
    assert st.converged is False


# ── 觀測拒收路徑 ─────────────────────────────────────────────────────────────

def test_reject_when_belt_not_fresh_or_no_contact():
    cal = OnlineBpmCalibrator()
    cal.observe(1.0, 75, True, False, _good_rppg(70))   # not fresh
    cal.observe(2.0, 75, False, True, _good_rppg(70))   # no contact
    cal.observe(3.0, 0, True, True, _good_rppg(70))     # belt bpm 0
    st = cal.state()
    assert st.total_observations == 3
    assert st.accepted_observations == 0
    assert st.pairs_used == 0


def test_reject_when_rppg_quality_fails():
    cal = OnlineBpmCalibrator()
    bad = _good_rppg(70)
    bad["sqi"] = 0.1  # 低於門檻
    cal.observe(1.0, 75, True, True, bad)
    assert cal.state().accepted_observations == 0


def test_reject_when_pair_gap_too_large():
    cal = OnlineBpmCalibrator(max_pair_bpm_gap=40.0)
    # belt 130 vs rppg 70 → 差距 60，視為離群配對
    cal.observe(1.0, 130, True, True, _good_rppg(70))
    assert cal.state().accepted_observations == 0


def test_reject_when_rppg_bpm_non_positive():
    cal = OnlineBpmCalibrator()
    cal.observe(1.0, 72, True, True, _good_rppg(0, raw_bpm=0))
    assert cal.state().accepted_observations == 0


# ── EMA 慢速收斂 ─────────────────────────────────────────────────────────────

def test_offset_does_not_jump_on_first_update():
    cal = OnlineBpmCalibrator(alpha=0.08, min_pairs=6, update_min_interval_sec=2.0)
    _feed(cal, belt=80, rppg_bpm=70, n=6)  # residual +10，僅觸發一次更新
    # 首次更新後 offset 應遠小於目標 10（EMA 低增益），約 0.08*10 = 0.8
    assert 0.0 < cal.offset < 2.0


def test_offset_converges_toward_true_residual():
    cal = OnlineBpmCalibrator(alpha=0.08, min_pairs=6, update_min_interval_sec=2.0)
    _feed(cal, belt=80, rppg_bpm=70, n=200)  # 真值比 rPPG 高 10 BPM
    st = cal.state()
    assert cal.offset == pytest.approx(10.0, abs=0.8)
    assert abs(st.corrected_residual_bpm) < 1.0
    assert st.converged is True


def test_systematic_bias_converges_not_diverged():
    # 穩定 12 BPM 系統性偏差（本功能最主要場景）：收斂後應顯示已收斂，
    # 不可因原始殘差仍為 12 而永遠顯示分歧（回歸測試：diverged 用校正後殘差）。
    cal = OnlineBpmCalibrator(alpha=0.1, min_pairs=6)
    _feed(cal, belt=82, rppg_bpm=70, n=200)
    st = cal.state()
    assert st.converged is True
    assert st.diverged is False
    assert st.raw_residual_bpm == pytest.approx(12.0, abs=0.5)  # 原始殘差不因校正而變


def test_offset_clamped_during_convergence():
    # residual +30 但 gap 30 < 40 不被拒；offset 應收斂到上限 25 而非 30
    cal = OnlineBpmCalibrator(alpha=0.1, min_pairs=6, max_abs_offset_bpm=25.0)
    _feed(cal, belt=100, rppg_bpm=70, n=300)
    assert cal.offset == pytest.approx(25.0, abs=0.5)
    assert cal.offset <= 25.0


def test_negative_residual_converges_negative():
    cal = OnlineBpmCalibrator(alpha=0.1, min_pairs=6)
    _feed(cal, belt=65, rppg_bpm=75, n=200)  # 真值比 rPPG 低 10
    assert cal.offset == pytest.approx(-10.0, abs=0.8)


# ── 收斂 / 分歧旗標 ─────────────────────────────────────────────────────────

def test_diverged_flag_when_residual_exceeds_offset_ceiling():
    # 真值差距 35 BPM 超過 offset 上限 25：即使收斂，校正後仍留約 10 BPM
    # 無法校平，累積足夠配對後應判為分歧。
    cal = OnlineBpmCalibrator(
        alpha=0.15, min_pairs=6, max_abs_offset_bpm=25.0,
        max_pair_bpm_gap=40.0, diverge_residual_bpm=8.0,
    )
    _feed(cal, belt=105, rppg_bpm=70, n=120)  # gap 35 < 40 不被拒
    st = cal.state()
    assert cal.offset == pytest.approx(25.0, abs=0.5)
    assert st.diverged is True
    assert st.converged is False


def test_not_diverged_during_early_convergence():
    # 配對數尚未達分歧判斷門檻（3×min_pairs）前，不應誤報分歧。
    cal = OnlineBpmCalibrator(min_pairs=6, diverge_residual_bpm=8.0)
    _feed(cal, belt=85, rppg_bpm=70, n=6)  # residual +15 但只有 6 配對
    assert cal.state().diverged is False


# ── 更新節流與視窗修剪 ───────────────────────────────────────────────────────

def test_update_throttled_by_min_interval():
    cal = OnlineBpmCalibrator(alpha=0.5, min_pairs=3, update_min_interval_sec=5.0)
    base = 10_000.0  # 用大基準時間戳，確保真的走到「觸發後被節流」路徑
    # t=base+2 累積滿 3 配對且距初始 last_update(0) 已久 → 第一次更新；
    # 之後 base+3、base+4 落在 5s 節流窗內 → 不得再更新。
    updates = [cal.observe(base + t, 80, True, True, _good_rppg(70)) for t in (0, 1, 2, 3, 4)]
    assert updates == [False, False, True, False, False]


def test_window_prunes_old_pairs():
    cal = OnlineBpmCalibrator(min_pairs=6, window_sec=10.0)
    _feed(cal, belt=80, rppg_bpm=70, n=6, start=0.0)      # t=0..5
    # 跳到遠未來，舊配對應被修剪
    cal.observe(100.0, 80, True, True, _good_rppg(70))
    assert cal.state().pairs_used == 1


# ── live_version 套用一致性 ──────────────────────────────────────────────────

def test_live_version_applies_current_offset():
    cal = OnlineBpmCalibrator(alpha=0.1, min_pairs=6)
    _feed(cal, belt=80, rppg_bpm=70, n=200)
    version = cal.live_version()
    assert version.model == "bias"
    # rPPG 原始 70 + offset(~10) 應被校正到接近 80
    assert apply_bpm_calibration(70.0, version) == pytest.approx(70.0 + cal.offset)
    assert apply_bpm_calibration(70.0, version) == pytest.approx(80.0, abs=1.0)
