"""Fused Fatigue Scorer — combines rPPG (15 %) and behaviour alertness (85 %).

This module is pure computation: no Qt, no UI, no threads.
It takes the latest RppgMetrics and FatigueMetrics objects, computes
normalised sub-scores for each pillar, and returns a FusedFatigueScore.

Score ranges
------------
0.00 – 0.20  清醒        (Alert)
0.20 – 0.40  輕度疲勞    (Mild fatigue)
0.40 – 0.60  中度疲勞    (Moderate fatigue)
0.60 – 0.80  高度疲勞    (High fatigue)
0.80 – 1.00  極度危險    (Critical)

Weight split
------------
    rPPG pillar     : 15 %  (adjustable via FuserConfig)
    Behaviour pillar: 85 %

Both pillars return a 0–1 normalised value; weights are applied and summed.
When one pillar's data is unavailable or unreliable, its weight falls back
to zero and the other pillar carries 100 % of the composite score.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from rppg.rppg_worker import RppgMetrics
    from gui.fatigue_engine import FatigueMetrics


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# PERCLOS→behavior 分數映射門檻的權威預設（單一來源；engine 個人化時以此為 clamp 錨點）。
PERCLOS_MILD_TH_DEFAULT = 0.015  # below = 0 score
PERCLOS_HIGH_TH_DEFAULT = 0.07   # above = 1.0 score


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class FuserConfig:
    # Pillar weights (must sum to 1.0)
    rppg_weight:      float = 0.15
    behavior_weight:  float = 0.85

    # ── rPPG sub-weights (internal, sum = 1.0) ────────────────────────────────
    # stress_prob score
    rppg_w_stress:    float = 0.60
    # BPM deviation score
    rppg_w_bpm:       float = 0.30
    # LF/HF ratio score
    rppg_w_lfhf:      float = 0.10

    # BPM normal range
    bpm_normal_lo:    float = 60.0
    bpm_normal_hi:    float = 100.0
    # BPM range that maps to score = 1.0
    bpm_max_dev:      float = 40.0    # ±40 BPM from boundary → score 1.0

    # LF/HF: autonomic stress (elevated = more stressed)
    lfhf_neutral:     float = 1.5
    lfhf_max:         float = 4.0

    # SQI gate: below this threshold rPPG sub-score is discounted
    sqi_min_reliable: float = 0.45
    rppg_min_quality: float = 0.55
    rppg_min_roi_valid: int = 3

    # ── Behaviour sub-weights (internal, sum = 1.0) ───────────────────────────
    # 權重依 UTA-RLDD 18 片（subject 01-06 × label 0/5/10）各通道分辨力（AUC）重配：
    # PERCLOS AUC 0.79 為唯一強訊號 → 主導；微睡（AUC 0.42）與 blink_temporal（0.42）
    # 在此資料上為反訊號 → 大幅降權但保留（對真實無人機場景的點頭/慢眨眼仍有價值）。
    # 詳見 docs/2026-07-03-fatigue-accuracy-calibration.md（2026-07-03 準確度校準）
    beh_w_perclos:    float = 0.55
    beh_w_blink_temporal: float = 0.12
    beh_w_microsleep: float = 0.10
    beh_w_gaze:       float = 0.08
    beh_w_squint:     float = 0.05
    beh_w_yawn:       float = 0.05
    beh_w_frown:      float = 0.05

    # PERCLOS tiers — 對齊系統實際 operating range（UTA-RLDD：清醒~0.006、嗜睡~0.031、
    # 峰值~0.067）。舊值 0.10/0.25 遠高於系統實際產生的 PERCLOS，使唯一有效訊號恆輸出 0。
    perclos_mild_th:  float = PERCLOS_MILD_TH_DEFAULT  # below = 0 score
    perclos_high_th:  float = PERCLOS_HIGH_TH_DEFAULT  # above = 1.0 score

    # Squint duration that maps to score 1.0
    squint_full_sec:  float = 30.0

    # Microsleep: each event adds this much to the score
    microsleep_per_event: float = 0.35

    # Gaze: fixation duration for full score
    gaze_fix_full_sec: float = 20.0
    # Saccade frequency below which gaze fatigue is flagged
    gaze_saccade_low_pm: float = 3.0

    # Frowning: full score when brow_dist_norm < this ratio
    frown_full_ratio: float = 0.75

    # Yawn: number of yawns for full score
    yawn_full_count: int = 5

    # ── Trend window (seconds) ────────────────────────────────────────────────
    trend_window_sec: float = 30.0

    # ── Level hysteresis ─────────────────────────────────────────────────────
    # 降級需跌破門檻再多此幅度才生效（升級即時，不延遲惡化警示），
    # 防止分數在門檻附近抖動造成等級來回切換（2026-07-03 審核 P1-3）
    level_hysteresis: float = 0.03

    @classmethod
    def for_rppg(cls) -> "FuserConfig":
        return cls()


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class FusedFatigueScore:
    # Overall
    score:         float = 0.0    # 0.0 – 1.0
    level:         str   = "清醒"  # 清醒 / 輕度疲勞 / 中度疲勞 / 高度疲勞 / 極度危險
    level_en:      str   = "Alert"
    color_bgr:     tuple = (0, 200, 0)   # for cv2 drawing

    # Sub-scores
    rppg_sub:      float = 0.0    # 0–1 (pillar score before weighting)
    behavior_sub:  float = 0.0    # 0–1

    # Effective weights (may differ from config when data unavailable)
    rppg_weight_eff:     float = 0.15
    behavior_weight_eff: float = 0.85

    # Trend
    trend:         float = 0.0    # delta per 30 s; positive = worsening
    trend_symbol:  str   = "→"

    # Data availability flags
    rppg_available:     bool = False
    behavior_available: bool = False

    # Component breakdown (for detailed display)
    rppg_stress_score:  float = 0.0
    rppg_bpm_score:     float = 0.0
    beh_perclos_score:  float = 0.0
    beh_blink_temporal_score: float = 0.0
    beh_squint_score:   float = 0.0
    beh_microsleep_score: float = 0.0
    beh_gaze_score:     float = 0.0
    beh_frown_score:    float = 0.0
    beh_yawn_score:     float = 0.0

    # Timestamp
    timestamp: float = field(default_factory=time.perf_counter)


# ── Level lookup ──────────────────────────────────────────────────────────────

_LEVELS = [
    (0.20, "清醒",     "Alert",    (0, 200,   0)),
    (0.40, "輕度疲勞", "Mild",     (0, 200, 160)),
    (0.60, "中度疲勞", "Moderate", (0, 140, 255)),
    (0.80, "高度疲勞", "High",     (0,  60, 255)),
    (1.01, "極度危險", "Critical", (0,   0, 200)),
]


def _score_to_level(s: float) -> tuple[str, str, tuple]:
    for threshold, zh, en, col in _LEVELS:
        if s < threshold:
            return zh, en, col
    return "極度危險", "Critical", (0, 0, 200)


# ── FatigueFuser ──────────────────────────────────────────────────────────────

class FatigueFuser:
    """Stateful fuser that merges rPPG and behaviour metrics into one score.

    Call ``update(rppg, fatigue)`` each time either metric is refreshed.
    Either argument may be None (pillar will be skipped / down-weighted).
    """

    def __init__(self, config: Optional[FuserConfig] = None) -> None:
        self.cfg = config or FuserConfig()
        self._history: deque[tuple[float, float]] = deque()  # (t, score)
        self._last_level_idx: Optional[int] = None  # 等級遲滯狀態

    def _level_with_hysteresis(self, s: float) -> tuple[str, str, tuple]:
        """等級查表加降級遲滯：升級即時，降級需跌破上一級門檻減 level_hysteresis。"""
        idx = len(_LEVELS) - 1
        for i, (threshold, _zh, _en, _col) in enumerate(_LEVELS):
            if s < threshold:
                idx = i
                break
        last = self._last_level_idx
        if last is not None and idx < last:
            hold_bound = _LEVELS[last - 1][0] - self.cfg.level_hysteresis
            if s >= hold_bound:
                idx = last
        self._last_level_idx = idx
        _threshold, zh, en, col = _LEVELS[idx]
        return zh, en, col

    # ── rPPG pillar ───────────────────────────────────────────────────────────

    def _rppg_sub_score(self, r: "RppgMetrics") -> tuple[float, float, float, float]:
        """Returns (pillar_score, stress_score, bpm_score, sqi_weight)."""
        cfg = self.cfg

        # Signal quality discount factor
        sqi_w = _clamp(r.sqi / cfg.sqi_min_reliable) if cfg.sqi_min_reliable > 0 else 1.0
        quality_w = _clamp(getattr(r, "quality_score", 1.0) or 0.0)

        # Stress probability (0-1 direct)
        stress_s = _clamp(r.stress_prob)

        # BPM deviation
        if r.bpm <= 0:
            bpm_s = 0.0
        else:
            bpm_val = float(getattr(r, "bpm_calibrated", 0.0) or 0.0)
            if bpm_val <= 0:
                bpm_val = float(r.bpm)
            if bpm_val < cfg.bpm_normal_lo:
                dev = cfg.bpm_normal_lo - bpm_val
                bpm_s = _clamp(dev / cfg.bpm_max_dev)
            elif bpm_val > cfg.bpm_normal_hi:
                dev = bpm_val - cfg.bpm_normal_hi
                bpm_s = _clamp(dev / cfg.bpm_max_dev)
            else:
                bpm_s = 0.0

        # LF/HF
        if r.lf_hf > 0:
            lfhf_s = _clamp(
                (r.lf_hf - cfg.lfhf_neutral) / (cfg.lfhf_max - cfg.lfhf_neutral + 1e-6)
            )
        else:
            lfhf_s = 0.0

        raw = (cfg.rppg_w_stress * stress_s
               + cfg.rppg_w_bpm   * bpm_s
               + cfg.rppg_w_lfhf  * lfhf_s)
        pillar = _clamp(raw * sqi_w * quality_w)
        return pillar, stress_s, bpm_s, sqi_w

    # ── Behaviour pillar ──────────────────────────────────────────────────────

    def _behavior_sub_score(self, f: "FatigueMetrics") -> tuple[float, ...]:
        """Returns (pillar_score, perclos_s, blink_s, squint_s, micro_s, gaze_s, frown_s, yawn_s)."""
        cfg = self.cfg

        # PERCLOS：個人化門檻優先（engine 於 live+profile 時填入哨兵欄位），
        # 哨兵 < 0 表未設定 → 退回 cfg 常數（replay/golden 恆走此路徑 → 逐位元不變）。
        mild_th = f.perclos_mild_th_eff if f.perclos_mild_th_eff >= 0.0 else cfg.perclos_mild_th
        high_th = f.perclos_high_th_eff if f.perclos_high_th_eff >= 0.0 else cfg.perclos_high_th
        if f.perclos <= mild_th:
            perc_s = 0.0
        else:
            perc_s = _clamp(
                (f.perclos - mild_th)
                / (high_th - mild_th + 1e-6)
            )

        # Squinting
        if f.is_squinting:
            squint_s = _clamp(f.squint_duration / (cfg.squint_full_sec + 1e-6))
        else:
            squint_s = 0.0

        blink_s = _clamp(getattr(f, "blink_temporal_score", 0.0) or 0.0)

        # Microsleep / pitch nod
        micro_s = _clamp(f.microsleep_count * cfg.microsleep_per_event)

        # Gaze (fixation + low saccade)
        fix_s = _clamp(f.fixation_duration / (cfg.gaze_fix_full_sec + 1e-6))
        # 掃視窗未暖機時 saccade_freq_pm≈0 是「沒資料」不是「低掃視」，
        # 開機/掉臉後數秒內不得假性拉滿凝視分數（2026-07-03 審核 P2-1）
        if (
            f.saccade_freq_pm < cfg.gaze_saccade_low_pm
            and f.face_detected
            and getattr(f, "saccade_window_ready", False)
        ):
            low_sac_s = _clamp(
                1.0 - f.saccade_freq_pm / (cfg.gaze_saccade_low_pm + 1e-6)
            )
        else:
            low_sac_s = 0.0
        gaze_s = _clamp(max(fix_s, low_sac_s)
                        + (0.30 if f.gaze_mental_fatigue else 0.0))

        # Brow furrowing
        if f.is_frowning:
            frown_s = _clamp(
                (1.0 - f.brow_dist_norm) / (1.0 - cfg.frown_full_ratio + 1e-6)
            )
        else:
            frown_s = 0.0

        # Yawn (late-stage, low weight)
        yawn_s = _clamp(f.yawn_count / (cfg.yawn_full_count + 1e-6))

        pillar = _clamp(
            cfg.beh_w_perclos    * perc_s
            + cfg.beh_w_blink_temporal * blink_s
            + cfg.beh_w_squint   * squint_s
            + cfg.beh_w_microsleep * micro_s
            + cfg.beh_w_gaze     * gaze_s
            + cfg.beh_w_frown    * frown_s
            + cfg.beh_w_yawn     * yawn_s
        )
        return pillar, perc_s, blink_s, squint_s, micro_s, gaze_s, frown_s, yawn_s

    # ── Main update ───────────────────────────────────────────────────────────

    def update(
        self,
        rppg:    "Optional[RppgMetrics]"    = None,
        fatigue: "Optional[FatigueMetrics]" = None,
    ) -> FusedFatigueScore:
        cfg = self.cfg
        t_now = time.perf_counter()

        # ── Physiological pillar (rPPG) ──────────────────────────────────────
        rppg_avail   = False
        rppg_sub     = 0.0
        stress_s = bpm_s = 0.0

        physio = rppg
        if (
            physio is not None
            and physio.face_detected
            and physio.warmup_progress >= 1.0
            and physio.sqi >= cfg.sqi_min_reliable
            and getattr(physio, "quality_score", 0.0) >= cfg.rppg_min_quality
            and getattr(physio, "roi_valid_count", 0) >= cfg.rppg_min_roi_valid
        ):
            rppg_sub, stress_s, bpm_s, _ = self._rppg_sub_score(physio)
            rppg_avail = True

        # ── Behaviour pillar ──────────────────────────────────────────────────
        beh_avail    = False
        beh_sub      = 0.0
        perc_s = blink_s = squint_s = micro_s = gaze_s = frown_s = yawn_s = 0.0

        if fatigue is not None and fatigue.face_detected and fatigue.calibrated:
            out = self._behavior_sub_score(fatigue)
            beh_sub, perc_s, blink_s, squint_s, micro_s, gaze_s, frown_s, yawn_s = out
            beh_avail = True

        # Also use fatigue.fatigue_level as a cross-check blend
        if beh_avail and fatigue is not None:
            # blend engine composite with our own calculation
            beh_sub = _clamp(0.70 * beh_sub + 0.30 * fatigue.fatigue_level)

        # ── Effective weights ─────────────────────────────────────────────────
        if rppg_avail and beh_avail:
            rw, bw = cfg.rppg_weight, cfg.behavior_weight
            score = _clamp(rw * rppg_sub + bw * beh_sub)
        elif rppg_avail:
            rw, bw = 1.0, 0.0
            score = _clamp(rppg_sub)
        elif beh_avail:
            rw, bw = 0.0, 1.0
            score = _clamp(beh_sub)
        else:
            rw, bw = 0.0, 0.0
            score = 0.0

        # ── Trend (30-s sliding delta) ────────────────────────────────────────
        # 無資料期間不寫入 history，避免恢復時 trend 相對 0 產生假性上升
        if rppg_avail or beh_avail:
            self._history.append((t_now, score))
        cutoff = t_now - cfg.trend_window_sec
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        trend = 0.0
        if len(self._history) >= 2:
            _, s_old = self._history[0]
            trend    = score - s_old

        if trend > 0.03:
            trend_sym = "↑"
        elif trend < -0.03:
            trend_sym = "↓"
        else:
            trend_sym = "→"

        if rppg_avail or beh_avail:
            zh, en, col = self._level_with_hysteresis(score)
        else:
            # 兩 pillar 皆失效＝無資料，不得顯示「清醒」綠燈（2026-07-03 審核 P1-2）
            zh, en, col = "無資料", "NoData", (128, 128, 128)
            self._last_level_idx = None

        return FusedFatigueScore(
            score=score, level=zh, level_en=en, color_bgr=col,
            rppg_sub=rppg_sub, behavior_sub=beh_sub,
            rppg_weight_eff=rw, behavior_weight_eff=bw,
            trend=trend, trend_symbol=trend_sym,
            rppg_available=rppg_avail, behavior_available=beh_avail,
            rppg_stress_score=stress_s,   rppg_bpm_score=bpm_s,
            beh_perclos_score=perc_s,     beh_blink_temporal_score=blink_s,
            beh_squint_score=squint_s,
            beh_microsleep_score=micro_s, beh_gaze_score=gaze_s,
            beh_frown_score=frown_s,      beh_yawn_score=yawn_s,
            timestamp=t_now,
        )
