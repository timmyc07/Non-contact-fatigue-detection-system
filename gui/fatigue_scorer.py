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

Watch mode (``fatigue_mode="watch"``):
    Behaviour pillar: 70 %
    Watch pillar    : 30 %  (HR + IMU gate; rPPG disabled)

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
    from rppg.watch_metrics import WatchMetrics


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class FuserConfig:
    # Fusion mode: "rppg" (default) or "watch"
    fatigue_mode:     str   = "rppg"

    # Pillar weights (must sum to 1.0 for active mode)
    rppg_weight:      float = 0.15
    behavior_weight:  float = 0.85
    watch_weight:     float = 0.30

    # Watch-mode behaviour weight (watch_weight + behavior_weight_watch = 1.0)
    behavior_weight_watch: float = 0.70

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
    beh_w_perclos:    float = 0.35
    beh_w_blink_temporal: float = 0.25
    beh_w_microsleep: float = 0.20
    beh_w_gaze:       float = 0.10
    beh_w_squint:     float = 0.05
    beh_w_yawn:       float = 0.05
    beh_w_frown:      float = 0.00

    # PERCLOS tiers
    perclos_mild_th:  float = 0.10   # below = 0 score
    perclos_high_th:  float = 0.25   # above = 1.0 score

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

    # ── Watch pillar (HR + HRV + IMU gate) ──────────────────────────────────
    motion_still_max: float = 0.35
    motion_active_min: float = 1.5
    watch_w_bpm:      float = 0.35
    watch_w_hrv:      float = 0.35
    watch_w_motion:   float = 0.30
    watch_rmssd_low:  float = 25.0   # below → elevated fatigue contribution

    @classmethod
    def for_rppg(cls) -> "FuserConfig":
        return cls(fatigue_mode="rppg")

    @classmethod
    def for_watch(cls) -> "FuserConfig":
        return cls(fatigue_mode="watch")


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
    watch_sub:     float = 0.0    # 0–1

    # Effective weights (may differ from config when data unavailable)
    rppg_weight_eff:     float = 0.15
    behavior_weight_eff: float = 0.85
    watch_weight_eff:    float = 0.0

    # Trend
    trend:         float = 0.0    # delta per 30 s; positive = worsening
    trend_symbol:  str   = "→"

    # Data availability flags
    rppg_available:     bool = False
    behavior_available: bool = False
    watch_available:    bool = False
    fatigue_mode:       str   = "rppg"

    # Component breakdown (for detailed display)
    rppg_stress_score:  float = 0.0
    rppg_bpm_score:     float = 0.0
    watch_bpm_score:    float = 0.0
    watch_motion_score: float = 0.0
    watch_hrv_score:    float = 0.0
    watch_imu_gate:     float = 1.0
    watch_rmssd:        float = 0.0
    watch_lf_hf:        float = 0.0
    watch_hrv_ready:    bool = False
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

    def _watch_sub_score(self, w: "WatchMetrics") -> tuple[float, float, float, float, float]:
        """Returns (pillar_score, bpm_score, motion_score, imu_gate, hrv_score)."""
        cfg = self.cfg
        bpm_s = float(getattr(w, "bpm_score", 0.0) or 0.0)
        motion_s = float(getattr(w, "motion_score", 0.0) or 0.0)
        gate = float(getattr(w, "imu_gate", 1.0) or 1.0)
        hrv_ready = bool(getattr(w, "hrv_ready", False))
        hrv_s = float(getattr(w, "hrv_score", 0.0) or getattr(w, "stress_prob", 0.0) or 0.0)
        if not hrv_ready:
            hrv_s = 0.0
        if getattr(w, "watch_sub", 0.0) and hrv_ready == bool(getattr(w, "hrv_ready", False)):
            pillar = _clamp(float(w.watch_sub))
        else:
            if hrv_ready:
                raw = cfg.watch_w_bpm * bpm_s + cfg.watch_w_hrv * hrv_s + cfg.watch_w_motion * motion_s
            else:
                bw = cfg.watch_w_bpm + cfg.watch_w_hrv
                denom = bw + cfg.watch_w_motion
                raw = ((bw / denom) * bpm_s + (cfg.watch_w_motion / denom) * motion_s) if denom > 0 else 0.0
            pillar = _clamp(raw * gate)
        return pillar, bpm_s, motion_s, gate, hrv_s

    # ── Behaviour pillar ──────────────────────────────────────────────────────

    def _behavior_sub_score(self, f: "FatigueMetrics") -> tuple[float, ...]:
        """Returns (pillar_score, perclos_s, blink_s, squint_s, micro_s, gaze_s, frown_s, yawn_s)."""
        cfg = self.cfg

        # PERCLOS
        if f.perclos <= cfg.perclos_mild_th:
            perc_s = 0.0
        else:
            perc_s = _clamp(
                (f.perclos - cfg.perclos_mild_th)
                / (cfg.perclos_high_th - cfg.perclos_mild_th + 1e-6)
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
        if f.saccade_freq_pm < cfg.gaze_saccade_low_pm and f.face_detected:
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
        watch:   "Optional[WatchMetrics]"   = None,
    ) -> FusedFatigueScore:
        cfg = self.cfg
        t_now = time.perf_counter()
        watch_mode = cfg.fatigue_mode == "watch"
        _ = watch  # legacy arg; watch mode uses rppg-shaped metrics

        # ── Physiological pillar (rPPG or watch-as-rPPG) ─────────────────────
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

        watch_avail = False
        watch_sub = 0.0
        watch_bpm_s = watch_motion_s = watch_hrv_s = 0.0
        watch_gate = 1.0
        watch_rmssd = watch_lf_hf = 0.0
        watch_hrv_ready = False

        if watch_mode and physio is not None and physio.face_detected and physio.bpm > 0:
            sub, stress_s_w, bpm_s_w, _ = self._rppg_sub_score(physio)
            watch_bpm_s = bpm_s_w
            watch_hrv_s = stress_s_w
            watch_rmssd = float(physio.rmssd)
            watch_lf_hf = float(physio.lf_hf)
            watch_hrv_ready = physio.rmssd > 0 and physio.hrv_confidence != "LOW"
            motion = float(getattr(physio, "landmark_jitter_norm", 0.0) or 0.0)
            watch_gate = _clamp(1.0 - motion / 1.5) if motion > 0 else 1.0
            watch_motion_s = _clamp(motion / 1.5)
            watch_sub = sub if rppg_avail else _clamp(sub * max(0.35, physio.warmup_progress))
            watch_avail = True

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
        if watch_mode:
            bw_cfg = cfg.behavior_weight_watch
            ww_cfg = cfg.watch_weight
            if watch_avail and beh_avail:
                ww, bw, rw = ww_cfg, bw_cfg, 0.0
            elif watch_avail:
                ww, bw, rw = 1.0, 0.0, 0.0
            elif beh_avail:
                ww, bw, rw = 0.0, 1.0, 0.0
            else:
                ww, bw, rw = 0.0, 0.0, 0.0
            score = _clamp(ww * watch_sub + bw * beh_sub)
        elif rppg_avail and beh_avail:
            rw, bw, ww = cfg.rppg_weight, cfg.behavior_weight, 0.0
            score = _clamp(rw * rppg_sub + bw * beh_sub)
        elif rppg_avail:
            rw, bw, ww = 1.0, 0.0, 0.0
            score = _clamp(rppg_sub)
        elif beh_avail:
            rw, bw, ww = 0.0, 1.0, 0.0
            score = _clamp(beh_sub)
        else:
            rw, bw, ww = 0.0, 0.0, 0.0
            score = 0.0

        # ── Trend (30-s sliding delta) ────────────────────────────────────────
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

        zh, en, col = _score_to_level(score)

        return FusedFatigueScore(
            score=score, level=zh, level_en=en, color_bgr=col,
            rppg_sub=rppg_sub, behavior_sub=beh_sub, watch_sub=watch_sub,
            rppg_weight_eff=rw, behavior_weight_eff=bw, watch_weight_eff=ww,
            trend=trend, trend_symbol=trend_sym,
            rppg_available=rppg_avail, behavior_available=beh_avail,
            watch_available=watch_avail, fatigue_mode=cfg.fatigue_mode,
            rppg_stress_score=stress_s,   rppg_bpm_score=bpm_s,
            watch_bpm_score=watch_bpm_s, watch_motion_score=watch_motion_s,
            watch_hrv_score=watch_hrv_s,
            watch_imu_gate=watch_gate,
            watch_rmssd=watch_rmssd, watch_lf_hf=watch_lf_hf,
            watch_hrv_ready=watch_hrv_ready,
            beh_perclos_score=perc_s,     beh_blink_temporal_score=blink_s,
            beh_squint_score=squint_s,
            beh_microsleep_score=micro_s, beh_gaze_score=gaze_s,
            beh_frown_score=frown_s,      beh_yawn_score=yawn_s,
            timestamp=t_now,
        )
