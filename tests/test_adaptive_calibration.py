"""Tests for online adaptive rPPG BPM calibration (belt truth → rPPG offset nudge)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from gui.mediapipe_tuning import load_mediapipe_tuning
from rppg.adaptive_calibration import (
    CONF_HIGH,
    CONF_LOW,
    COORD_ADOPT,
    COORD_COOLDOWN,
    COORD_EVALUATING,
    COORD_GATED,
    COORD_IDLE,
    COORD_ROLLBACK,
    AdaptiveCalibState,
    OnlineBpmCalibrator,
    RppgParamAbEvaluator,
    RppgParamCoordinator,
    propose_roi_weight_candidate,
    recompute_raw_bpm_from_roi_windows,
)
from rppg.calibration import apply_bpm_calibration
from rppg.rppg_worker import (
    ROI_SPECS,
    ROI_WEIGHT_OVERRIDE_MAX_FRACTION,
    ROI_WEIGHT_OVERRIDE_MIN_FRACTION,
    RppgEngine,
    RoiGeometryTracker,
)


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


# ── P6：rPPG 解析參數有護欄 A/B 評估 ───────────────────────────────────────

def _feed_ab(ev, *, belt, current, candidate, n, t0=0.0):
    for i in range(n):
        ev.observe(t0 + i, belt, current, candidate)


def test_ab_insufficient_pairs_is_pending():
    ev = RppgParamAbEvaluator(min_pairs=6, confirm_windows=2)
    _feed_ab(ev, belt=80, current=70, candidate=79, n=3)
    v = ev.evaluate()
    assert v.verdict == "pending"
    assert v.pairs_used == 3


def test_ab_candidate_clearly_better_adopts_after_confirm():
    # 候選殘差 1（|80-79|）明顯小於現行殘差 10（|80-70|）→ 連續 confirm 次後 adopt。
    ev = RppgParamAbEvaluator(min_pairs=6, improve_margin_bpm=1.5, confirm_windows=3)
    _feed_ab(ev, belt=80, current=70, candidate=79, n=10)
    verdicts = [ev.evaluate().verdict for _ in range(3)]
    assert verdicts[-1] == "adopt"
    assert verdicts[0] == "pending"   # 第一次評估尚未達 confirm


def test_ab_candidate_clearly_worse_rolls_back():
    # 候選殘差 10 明顯大於現行殘差 1 → 連續 confirm 次後 rollback。
    ev = RppgParamAbEvaluator(min_pairs=6, worsen_margin_bpm=2.0, confirm_windows=2)
    _feed_ab(ev, belt=80, current=79, candidate=70, n=10)
    assert ev.evaluate().verdict == "pending"
    assert ev.evaluate().verdict == "rollback"


def test_ab_marginal_difference_stays_pending():
    # 差距小於 improve_margin → 永遠 pending（不採用也不回退）。
    ev = RppgParamAbEvaluator(min_pairs=6, improve_margin_bpm=1.5,
                              worsen_margin_bpm=2.0, confirm_windows=2)
    _feed_ab(ev, belt=80, current=78.5, candidate=79.0, n=10)
    for _ in range(5):
        assert ev.evaluate().verdict == "pending"


def test_ab_rejects_outlier_pairs():
    # 殘差超過 max_pair_bpm_gap 的壞樣本不計入。
    ev = RppgParamAbEvaluator(min_pairs=3, max_pair_bpm_gap=40.0)
    ev.observe(0.0, 80, 10, 79)    # |80-10|=70 > 40 → 拒
    ev.observe(1.0, 80, 200, 79)   # |80-200|=120 > 40 → 拒
    assert ev.evaluate().pairs_used == 0


def test_ab_window_trims_old_pairs():
    ev = RppgParamAbEvaluator(window_sec=10.0, min_pairs=1)
    _feed_ab(ev, belt=80, current=70, candidate=79, n=5, t0=0.0)
    ev.observe(100.0, 80, 70, 79)   # 遠未來 → 舊配對被修剪
    assert ev.evaluate().pairs_used == 1


def test_ab_reset_clears_state():
    ev = RppgParamAbEvaluator(min_pairs=6, confirm_windows=2)
    _feed_ab(ev, belt=80, current=70, candidate=79, n=10)
    ev.evaluate(); ev.evaluate()
    ev.reset()
    v = ev.evaluate()
    assert v.pairs_used == 0
    assert v.improve_streak == 0 and v.worsen_streak == 0


# ── recompute_raw_bpm_from_roi_windows（P6b-3a 離線重算純函式）─────────────────

def _pulse_channels(
    t: np.ndarray,
    f0: float,
    *,
    seed: int | None = None,
    amp: tuple[float, float, float] = (0.5, 2.0, 0.2),
    phase: tuple[float, float, float] = (0.0, 0.4, 0.8),
    noise: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """合成 (r,g,b) 三通道脈搏訊號。各通道用不同振幅+相位，避免三通道互為純量倍數
    而在 POS 正規化後互相抵消；如此 POS→bandpass→Welch 能取到 f0 的主峰。"""
    rng = np.random.default_rng(seed) if seed is not None else None
    out = []
    for a, ph in zip(amp, phase):
        c = a * np.sin(2 * np.pi * f0 * t + ph)
        if rng is not None and noise > 0.0:
            c = c + noise * rng.standard_normal(t.size)
        out.append(c)
    return out[0], out[1], out[2]


def _fake_landmarks() -> list[SimpleNamespace]:
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[1] = SimpleNamespace(x=0.50, y=0.45)
    pts[10] = SimpleNamespace(x=0.50, y=0.20)
    pts[152] = SimpleNamespace(x=0.50, y=0.82)
    pts[234] = SimpleNamespace(x=0.34, y=0.52)
    pts[454] = SimpleNamespace(x=0.66, y=0.52)
    pts[33] = SimpleNamespace(x=0.38, y=0.36)
    pts[263] = SimpleNamespace(x=0.62, y=0.38)
    return pts


def test_recompute_matches_engine_raw_bpm_single_roi_equal_weight() -> None:
    """3(a)：單一 ROI、權重 1.0，重算 BPM 與 RppgEngine.compute() 的 raw_bpm 一致。

    容差 1e-6 BPM：單 ROI 權重 1.0 時加權平均 = w*x/w = x（除以 1.0 為精確浮點），
    兩路徑餵入完全相同的 (t,r,g,b)，走完全相同的 _fs 公式 + pos_pulse/butter_bandpass/
    welch_peak_hz 純函式，理論上逐位元相等（實測 diff=0.0）。1e-6 僅為防範任何非
    決定性浮點加總差異的安全邊界，非表示允許有意義偏差。"""
    n, fs, f0 = 256, 30.0, 1.25
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, f0, seed=0)

    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    for i in range(n):
        engine.push(float(t[i]), float(r[i]), float(g[i]), float(b[i]))
    metrics = engine.compute(
        float(t[-1]),
        np.full((480, 640, 3), 128, dtype=np.uint8),
        _fake_landmarks(),
        transform_matrix=None,
        roi_valid_count=4,
        roi_weights={name: 0.25 for name, _ in ROI_SPECS},
        roi_tracker=RoiGeometryTracker(),
        tuning=load_mediapipe_tuning(),
    )
    rec = recompute_raw_bpm_from_roi_windows({"forehead": (t, r, g, b)}, {"forehead": 1.0})

    assert metrics.raw_bpm > 0.0
    assert rec is not None
    assert abs(rec - metrics.raw_bpm) < 1e-6


def test_recompute_weights_change_bpm() -> None:
    """3(d)：本次任務核心——不同權重必須產生可分辨的不同 BPM（證明權重有槓桿）。

    forehead 脈搏在 1.0 Hz（60 bpm）、L_cheek 在 2.2 Hz（132 bpm）。加重哪個 ROI，
    加權混合後的主頻就趨近該 ROI。"""
    n, fs = 256, 30.0
    t = np.arange(n) / fs
    r_fh, g_fh, b_fh = _pulse_channels(t, 1.0, seed=1)
    r_ch, g_ch, b_ch = _pulse_channels(t, 2.2, seed=2)
    windows = {"forehead": (t, r_fh, g_fh, b_fh), "L_cheek": (t, r_ch, g_ch, b_ch)}

    bpm_forehead_heavy = recompute_raw_bpm_from_roi_windows(
        windows, {"forehead": 0.9, "L_cheek": 0.1}
    )
    bpm_cheek_heavy = recompute_raw_bpm_from_roi_windows(
        windows, {"forehead": 0.1, "L_cheek": 0.9}
    )

    assert bpm_forehead_heavy is not None and bpm_cheek_heavy is not None
    # 可分辨且方向正確：forehead 重→趨近 60、L_cheek 重→趨近 132。
    assert abs(bpm_forehead_heavy - 60.0) < 10.0
    assert abs(bpm_cheek_heavy - 132.0) < 10.0
    assert (bpm_cheek_heavy - bpm_forehead_heavy) > 30.0


def test_recompute_uses_timestamp_intersection_not_union() -> None:
    """3(b)：多 ROI 取共同時間戳交集、不插值。

    forehead 只在偶數索引有樣本（乾淨脈搏）；L_cheek 在所有索引都有，但奇數索引是
    3.3 Hz 的強污染。交集 = 偶數索引（兩 ROI 皆有）。若誤用聯集/插值，奇數索引的
    污染會主導 → BPM 遠離 72；正確取交集則污染被排除 → BPM≈f0*60=72。"""
    fs, N, f0 = 30.0, 256, 1.2
    tf = np.arange(N) / fs
    clean_r, clean_g, clean_b = _pulse_channels(tf, f0, noise=0.0)
    cont_r, cont_g, cont_b = _pulse_channels(tf, 3.3, noise=0.0)
    even = np.arange(0, N, 2)
    is_even = (np.arange(N) % 2 == 0)
    rB = np.where(is_even, clean_r, 8.0 * cont_r)
    gB = np.where(is_even, clean_g, 8.0 * cont_g)
    bB = np.where(is_even, clean_b, 8.0 * cont_b)

    windows = {
        "forehead": (tf[even], clean_r[even], clean_g[even], clean_b[even]),
        "L_cheek": (tf, rB, gB, bB),
    }
    bpm = recompute_raw_bpm_from_roi_windows(
        windows, {"forehead": 0.5, "L_cheek": 0.5}, min_samples=64, min_duration_sec=6.0
    )
    assert bpm is not None
    assert abs(bpm - f0 * 60.0) < 6.0


def test_recompute_disjoint_timestamps_returns_none() -> None:
    """3(b) 補充：兩 ROI 時間戳完全不重疊 → 交集為空 → None（證明是交集非聯集）。"""
    n, fs = 256, 30.0
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, 1.2, seed=3)
    windows = {"forehead": (t, r, g, b), "L_cheek": (t + 1000.0, r, g, b)}
    assert recompute_raw_bpm_from_roi_windows(
        windows, {"forehead": 0.5, "L_cheek": 0.5}
    ) is None


def test_recompute_insufficient_samples_returns_none() -> None:
    """3(c)：樣本數過少 → None，不丟例外。"""
    t = np.arange(10) / 30.0
    assert recompute_raw_bpm_from_roi_windows(
        {"forehead": (t, t, t, t)}, {"forehead": 1.0}
    ) is None


def test_recompute_short_duration_returns_none() -> None:
    """3(c)：樣本數足夠但時長不足（高取樣率短視窗）→ None。"""
    n, fs = 200, 200.0  # 恰好 ~1 秒
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, 1.2, seed=5)
    assert recompute_raw_bpm_from_roi_windows(
        {"forehead": (t, r, g, b)}, {"forehead": 1.0}, min_samples=64, min_duration_sec=6.0
    ) is None


def test_recompute_nan_sample_returns_none() -> None:
    """審查發現的 major：ROI 樣本含 NaN 時，混合後訊號被污染，welch_peak_hz 內部
    np.argmax 在含 NaN 陣列上行為不穩定，可能選到仍為有限值的 peak_hz，繞過
    `peak_hz <= 0.0` 護欄、靜默算出錯誤 BPM（審查者實測：乾淨訊號 ~71.9 BPM，
    污染 1 筆 G 通道為 NaN 後變成 42.19，無例外無警告）。修法：混合完成後、
    最終 BPM 算出後皆檢查 np.isfinite，任何非有限值一律回傳 None。"""
    fs, N, f0 = 30.0, 256, 1.2
    t = np.arange(N) / fs
    r, g, b = _pulse_channels(t, f0, noise=0.0)

    # 對照：乾淨訊號應能算出有限、合理的 BPM。
    clean = recompute_raw_bpm_from_roi_windows({"forehead": (t, r, g, b)}, {"forehead": 1.0})
    assert clean is not None and np.isfinite(clean)

    g_nan = g.copy()
    g_nan[10] = np.nan
    contaminated = recompute_raw_bpm_from_roi_windows(
        {"forehead": (t, r, g_nan, b)}, {"forehead": 1.0}
    )
    assert contaminated is None


def test_recompute_inf_sample_returns_none() -> None:
    """同上，補測 Inf（而非 NaN）污染樣本的情形。"""
    fs, N, f0 = 30.0, 256, 1.2
    t = np.arange(N) / fs
    r, g, b = _pulse_channels(t, f0, noise=0.0)

    b_inf = b.copy()
    b_inf[50] = np.inf
    assert recompute_raw_bpm_from_roi_windows(
        {"forehead": (t, r, g, b_inf)}, {"forehead": 1.0}
    ) is None


def test_recompute_no_active_weight_returns_none() -> None:
    """3(c)：沒有正權重的 ROI（權重全 0 或缺）→ None，不丟例外。"""
    n, fs = 256, 30.0
    t = np.arange(n) / fs
    r, g, b = _pulse_channels(t, 1.2, seed=4)
    assert recompute_raw_bpm_from_roi_windows(
        {"forehead": (t, r, g, b)}, {"forehead": 0.0}
    ) is None
    assert recompute_raw_bpm_from_roi_windows({"forehead": (t, r, g, b)}, {}) is None
    assert recompute_raw_bpm_from_roi_windows({}, {}) is None


# ── P6b-3b：propose_roi_weight_candidate（候選產生純函式）────────────────────

_ROI_NAMES = [name for name, _ in ROI_SPECS]


def _equal_weights() -> dict[str, float]:
    return {name: 1.0 / len(_ROI_NAMES) for name in _ROI_NAMES}


def test_propose_candidate_sums_to_one_and_within_bounds():
    candidate = propose_roi_weight_candidate(_equal_weights(), {})
    assert candidate.keys() == set(_ROI_NAMES)
    assert sum(candidate.values()) == pytest.approx(1.0, abs=1e-9)
    for v in candidate.values():
        assert ROI_WEIGHT_OVERRIDE_MIN_FRACTION - 1e-9 <= v <= ROI_WEIGHT_OVERRIDE_MAX_FRACTION + 1e-9


def test_propose_candidate_is_deterministic():
    weights = {"forehead": 0.34, "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.16}
    hint = {"forehead": 3.0, "L_cheek": 1.0, "R_cheek": 5.0, "glabella": 2.0}
    a = propose_roi_weight_candidate(weights, hint)
    b = propose_roi_weight_candidate(weights, hint)
    assert a == b


def test_propose_candidate_boosts_lowest_residual_hint_roi():
    """有提示時：挑對心跳帶殘差最小（表現最好）的 ROI 加重。"""
    weights = _equal_weights()
    hint = {"forehead": 0.5, "L_cheek": 5.0, "R_cheek": 5.0, "glabella": 5.0}
    candidate = propose_roi_weight_candidate(weights, hint, step=0.05)
    assert candidate["forehead"] > weights["forehead"]
    # 其餘 ROI 應被等比縮減（不高於原權重）。
    for name in ("L_cheek", "R_cheek", "glabella"):
        assert candidate[name] <= weights[name] + 1e-9


def test_propose_candidate_no_hint_boosts_smallest_current_weight():
    """無提示（空字典）fallback：挑目前權重最小者做探索性加重。"""
    weights = {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.2, "glabella": 0.1}
    candidate = propose_roi_weight_candidate(weights, {}, step=0.05)
    assert candidate["glabella"] > weights["glabella"]
    for name in ("forehead", "L_cheek", "R_cheek"):
        assert candidate[name] <= weights[name] + 1e-9


def test_propose_candidate_ignores_non_finite_hints():
    """非有限提示值（NaN/Inf）視為無效，不參與挑選；若全部無效則走無提示 fallback。"""
    weights = {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.2, "glabella": 0.1}
    hint = {
        "forehead": float("nan"),
        "L_cheek": float("inf"),
        "R_cheek": float("nan"),
        "glabella": float("inf"),
    }
    candidate = propose_roi_weight_candidate(weights, hint, step=0.05)
    # 全部提示皆非有限值 → 等同無提示 → fallback 挑權重最小者（glabella）。
    assert candidate["glabella"] > weights["glabella"]


def test_propose_candidate_zero_total_weights_falls_back_to_uniform():
    """current_weights 總和非正（例如全 0）時安全回退為均分，不丟例外。"""
    candidate = propose_roi_weight_candidate({name: 0.0 for name in _ROI_NAMES}, {})
    assert sum(candidate.values()) == pytest.approx(1.0, abs=1e-9)
    for v in candidate.values():
        assert v > 0.0


# ── P6b-3b：RppgParamCoordinator（belt 殘差 → 候選 → A/B → adopt/rollback）───

def _calib_state(*, confidence: str = CONF_HIGH, corrected_residual_bpm: float = 5.0) -> AdaptiveCalibState:
    """使用者裁決 1 後：觸發 gate 只看 confidence（offset 是否穩定），殘差不再是
    前置——corrected_residual_bpm 保留欄位僅為讓合成狀態貼近真實，不影響 gate。"""
    return AdaptiveCalibState(confidence=confidence, corrected_residual_bpm=corrected_residual_bpm)


def test_coordinator_starts_idle():
    coord = RppgParamCoordinator()
    assert coord.phase == COORD_IDLE
    assert coord.candidate_roi_weights is None


def test_coordinator_gated_when_offset_not_stable():
    """offset 未穩定（confidence == CONF_LOW）→ gated，不產候選。"""
    coord = RppgParamCoordinator()
    candidate = coord.tick(0.0, _calib_state(confidence=CONF_LOW), _equal_weights())
    assert candidate is None
    assert coord.phase == COORD_GATED


def test_coordinator_evaluates_once_offset_stable_regardless_of_residual():
    """使用者裁決 1 新語意：offset 穩定（confidence != CONF_LOW）即進 evaluating，
    即使殘差很小（原本會被『殘差不夠大→gated』擋掉的情形，現在應照樣產候選，
    由後續 A/B 護欄裁決好壞）。"""
    coord = RppgParamCoordinator()
    candidate = coord.tick(
        0.0, _calib_state(confidence=CONF_HIGH, corrected_residual_bpm=0.5), _equal_weights()
    )
    assert candidate is not None
    assert coord.phase == COORD_EVALUATING


def test_coordinator_triggers_evaluating_when_offset_stable():
    coord = RppgParamCoordinator(step_size=0.05)
    candidate = coord.tick(0.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert candidate is not None
    assert sum(candidate.values()) == pytest.approx(1.0, abs=1e-9)
    assert coord.phase == COORD_EVALUATING
    assert coord.candidate_roi_weights == candidate


def test_coordinator_does_not_retrigger_while_evaluating():
    coord = RppgParamCoordinator()
    first = coord.tick(0.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert first is not None
    again = coord.tick(1.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert again is None
    assert coord.phase == COORD_EVALUATING
    assert coord.candidate_roi_weights == first


def test_coordinator_observe_ab_noop_when_not_evaluating():
    coord = RppgParamCoordinator()
    verdict = coord.observe_ab(0.0, 70.0, 72.0, 71.0)
    assert verdict is None
    assert coord.phase == COORD_IDLE


def _drive_to_evaluating(coord: RppgParamCoordinator) -> dict:
    candidate = coord.tick(0.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert candidate is not None
    assert coord.phase == COORD_EVALUATING
    return candidate


def test_coordinator_adopt_transition_and_records_adopted_weights():
    coord = RppgParamCoordinator()
    candidate = _drive_to_evaluating(coord)

    verdict = None
    for i in range(8):
        # belt=70：現行殘差 10（80-70），候選殘差 1（71-70）— 候選明顯較佳。
        verdict = coord.observe_ab(float(i), 70.0, 80.0, 71.0)
    assert verdict is not None
    assert verdict.verdict == "adopt"
    assert coord.phase == COORD_ADOPT
    assert coord.state().adopted_roi_weights == candidate


def test_coordinator_rollback_transition():
    coord = RppgParamCoordinator()
    _drive_to_evaluating(coord)

    verdict = None
    for i in range(8):
        # belt=70：現行殘差 1（71-70），候選殘差 10（80-70）— 候選明顯較差。
        verdict = coord.observe_ab(float(i), 70.0, 71.0, 80.0)
    assert verdict is not None
    assert verdict.verdict == "rollback"
    assert coord.phase == COORD_ROLLBACK


def test_coordinator_enters_cooldown_after_adopt_on_next_tick():
    coord = RppgParamCoordinator(cooldown_sec=120.0)
    _drive_to_evaluating(coord)
    for i in range(8):
        coord.observe_ab(float(i), 70.0, 80.0, 71.0)
    assert coord.phase == COORD_ADOPT

    candidate = coord.tick(100.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert candidate is None
    assert coord.phase == COORD_COOLDOWN
    assert coord.candidate_roi_weights is None


def test_coordinator_stays_in_cooldown_until_elapsed_then_can_retrigger():
    coord = RppgParamCoordinator(cooldown_sec=120.0)
    _drive_to_evaluating(coord)
    for i in range(8):
        coord.observe_ab(float(i), 70.0, 80.0, 71.0)
    coord.tick(100.0, _calib_state(confidence=CONF_HIGH), _equal_weights())
    assert coord.phase == COORD_COOLDOWN
    cooldown_until = coord.state().cooldown_until

    # 冷卻未滿：仍維持 cooldown，不觸發。
    still_cooling = coord.tick(
        cooldown_until - 1.0, _calib_state(confidence=CONF_HIGH), _equal_weights()
    )
    assert still_cooling is None
    assert coord.phase == COORD_COOLDOWN

    # 冷卻期滿：同一次 tick 內落回 idle 並可重新觸發。
    candidate = coord.tick(
        cooldown_until + 1.0, _calib_state(confidence=CONF_HIGH), _equal_weights()
    )
    assert candidate is not None
    assert coord.phase == COORD_EVALUATING


def test_coordinator_reset_clears_all_state():
    coord = RppgParamCoordinator()
    _drive_to_evaluating(coord)
    for i in range(8):
        coord.observe_ab(float(i), 70.0, 80.0, 71.0)
    assert coord.phase == COORD_ADOPT

    coord.reset()
    st = coord.state()
    assert st.phase == COORD_IDLE
    assert st.candidate_roi_weights is None
    assert st.adopted_roi_weights is None
    assert st.verdict is None
    assert st.cooldown_until == 0.0


def test_coordinator_observe_ab_noop_in_adopt_state_before_cooldown():
    """審查 A 補測：adopt 判決後、下一次 tick 進 cooldown 前的中間態，若呼叫端多送
    一筆 observe_ab，必須安全 no-op（phase != evaluating），不改變已定案的 adopt。"""
    coord = RppgParamCoordinator()
    _drive_to_evaluating(coord)
    for i in range(8):
        coord.observe_ab(float(i), 70.0, 80.0, 71.0)
    assert coord.phase == COORD_ADOPT
    adopted_before = coord.state().adopted_roi_weights

    extra = coord.observe_ab(99.0, 70.0, 71.0, 80.0)  # 額外一筆（且方向相反）
    assert extra is None                              # 中間態 no-op
    assert coord.phase == COORD_ADOPT                 # 仍維持 adopt 終態
    assert coord.state().adopted_roi_weights == adopted_before


def test_coordinator_observe_ab_noop_in_rollback_state_before_cooldown():
    """同上，補測 rollback 中間態。"""
    coord = RppgParamCoordinator()
    _drive_to_evaluating(coord)
    for i in range(8):
        coord.observe_ab(float(i), 70.0, 71.0, 80.0)
    assert coord.phase == COORD_ROLLBACK

    extra = coord.observe_ab(99.0, 70.0, 80.0, 71.0)
    assert extra is None
    assert coord.phase == COORD_ROLLBACK
