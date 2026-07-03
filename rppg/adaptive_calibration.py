"""線上自適應 rPPG BPM 校正：以心跳帶真值為參考，持續微調 rPPG 的 BPM offset。

設計原則（見專案記憶 belt-is-rppg-reference-not-fusion-weight）：
- 心跳帶（Scosche Rhythm+ 2.0 等標準 Heart Rate Service 裝置）為「真值參考」，
  **不進**疲勞融合分數。
- rPPG 為疲勞判斷主體；本模組只在背景比對心跳帶 HR 與 rPPG **原始** BPM，
  以低增益 EMA 慢速微調 offset，讓 rPPG 逐漸趨近真值（沿用既有 bias 模型
  ``scale * bpm + offset``，本階段只動 offset、scale 固定 1.0，風險最低）。
- 純運算：無 Qt / 無執行緒 / 無 I/O。GUI 以固定節奏呼叫 :meth:`observe`
  餵入配對觀測、以 :meth:`state` 輪詢狀態、以 :meth:`live_version` 取得即時校準版本。

殘差定義：
- ``raw_residual`` = median(belt_bpm − rppg_raw_bpm)：offset 應趨近的目標值。
- ``corrected_residual`` = median(belt_bpm − (rppg_raw_bpm + offset))：套用目前 offset
  後的剩餘偏差，收斂時應趨近 0。UI 的「分歧警告」以 raw_residual 判斷。
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping

from rppg.calibration import (
    CalibrationParams,
    CalibrationVersion,
    calibration_rppg_bpm,
    rppg_sample_quality_ok,
)

# 線上校正專用品質門檻：沿用預設但允許暖機後的一般樣本；不接受 guarded 樣本，
# 避免穩定器鎖住的舊值污染殘差。
ADAPTIVE_QUALITY_GATES = {
    "min_sqi": 0.45,
    "min_quality_score": 0.55,
    "min_roi_valid": 3,
    "require_warmup": True,
    "reject_bpm_guarded": True,
}

CONF_LOW = "LOW"
CONF_MED = "MED"
CONF_HIGH = "HIGH"


@dataclass(frozen=True)
class AdaptiveCalibState:
    """線上校正狀態快照（GUI 輪詢用，immutable 跨執行緒安全）。"""

    offset_bpm: float = 0.0
    raw_residual_bpm: float = 0.0
    corrected_residual_bpm: float = 0.0
    pairs_used: int = 0
    total_observations: int = 0
    accepted_observations: int = 0
    confidence: str = CONF_LOW
    converged: bool = False
    diverged: bool = False
    updated_at: float = field(default_factory=time.time)


class OnlineBpmCalibrator:
    """以心跳帶真值為參考，線上慢速微調 rPPG BPM offset。

    典型用法（GUI 主執行緒，每 ~1 秒一次）::

        cal.observe(now, belt_bpm, belt_contact_ok, belt_fresh, rppg_sample_dict)
        st = cal.state()          # 顯示 offset / 殘差 / 信心 / 收斂
        version = cal.live_version()  # 交給 rPPG worker 的 calibration_loader

    參數說明：
        alpha: EMA 增益（每次更新往目標殘差移動的比例）。越小越穩、收斂越慢。
        window_sec: 計算中位殘差的滾動配對視窗長度。
        min_pairs: 觸發微調所需的最少配對數。
        max_abs_offset_bpm: offset 絕對值上限（防呆，避免異常真值把 rPPG 拉歪）。
        update_min_interval_sec: 兩次微調之間的最短間隔。
        converge_residual_bpm / diverge_residual_bpm: 收斂 / 分歧判斷門檻。
    """

    def __init__(
        self,
        *,
        initial_offset: float = 0.0,
        alpha: float = 0.08,
        window_sec: float = 45.0,
        min_pairs: int = 6,
        max_abs_offset_bpm: float = 25.0,
        update_min_interval_sec: float = 2.0,
        converge_residual_bpm: float = 3.0,
        diverge_residual_bpm: float = 8.0,
        max_pair_bpm_gap: float = 40.0,
        quality_gates: Mapping[str, Any] | None = None,
    ) -> None:
        self.alpha = float(alpha)
        self.window_sec = float(window_sec)
        self.min_pairs = int(min_pairs)
        self.max_abs_offset_bpm = float(max_abs_offset_bpm)
        self.update_min_interval_sec = float(update_min_interval_sec)
        self.converge_residual_bpm = float(converge_residual_bpm)
        self.diverge_residual_bpm = float(diverge_residual_bpm)
        self.max_pair_bpm_gap = float(max_pair_bpm_gap)
        self._gates = {**ADAPTIVE_QUALITY_GATES, **(quality_gates or {})}

        self._offset = _clamp_abs(float(initial_offset), self.max_abs_offset_bpm)
        self._pairs: deque[tuple[float, float, float]] = deque()  # (ts, belt, rppg_raw)
        self._last_update_ts: float = 0.0
        self._total_obs = 0
        self._accepted_obs = 0
        self._updated_at = time.time()

    # ── 觀測輸入 ─────────────────────────────────────────────────────────────

    def observe(
        self,
        now: float,
        belt_bpm: float,
        belt_contact_ok: bool,
        belt_fresh: bool,
        rppg_sample: Mapping[str, Any],
    ) -> bool:
        """餵入一筆配對觀測；符合條件時可能觸發一次 offset 微調。

        回傳 True 表示本次呼叫實際更新了 offset（僅供上層記錄，非必要）。
        觀測被接受的條件：心跳帶 BPM>0、資料新鮮、接觸良好，且 rPPG 樣本通過
        品質門檻且原始 BPM>0，兩者差距不超過 ``max_pair_bpm_gap``（防離群配對）。
        """
        self._total_obs += 1
        self._updated_at = now

        if belt_bpm <= 0 or not belt_fresh or not belt_contact_ok:
            self._prune(now)
            return False
        if not rppg_sample_quality_ok(rppg_sample, self._gates):
            self._prune(now)
            return False
        rppg_bpm = calibration_rppg_bpm(rppg_sample)
        if rppg_bpm <= 0:
            self._prune(now)
            return False
        if abs(float(belt_bpm) - rppg_bpm) > self.max_pair_bpm_gap:
            # 差距過大通常是 rPPG 鎖到諧波或心跳帶假影，不納入校正配對。
            self._prune(now)
            return False

        self._accepted_obs += 1
        self._pairs.append((float(now), float(belt_bpm), float(rppg_bpm)))
        self._prune(now)
        return self._maybe_update(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._pairs and self._pairs[0][0] < cutoff:
            self._pairs.popleft()

    def _maybe_update(self, now: float) -> bool:
        if len(self._pairs) < self.min_pairs:
            return False
        if (now - self._last_update_ts) < self.update_min_interval_sec:
            return False
        target = _clamp_abs(self._raw_residual(), self.max_abs_offset_bpm)
        self._offset = _clamp_abs(
            self._offset + self.alpha * (target - self._offset),
            self.max_abs_offset_bpm,
        )
        self._last_update_ts = now
        return True

    # ── 殘差 / 信心計算 ─────────────────────────────────────────────────────

    def _raw_residual(self) -> float:
        if not self._pairs:
            return 0.0
        return float(statistics.median(belt - rppg for _, belt, rppg in self._pairs))

    def _corrected_residual(self) -> float:
        if not self._pairs:
            return 0.0
        return float(
            statistics.median(belt - (rppg + self._offset) for _, belt, rppg in self._pairs)
        )

    def _confidence(self) -> str:
        n = len(self._pairs)
        if n < self.min_pairs:
            return CONF_LOW
        spread = 0.0
        if n >= 2:
            spread = float(statistics.pstdev(belt - rppg for _, belt, rppg in self._pairs))
        if n >= 2 * self.min_pairs and spread <= 4.0:
            return CONF_HIGH
        if spread <= 8.0:
            return CONF_MED
        return CONF_LOW

    # ── 對外狀態 ─────────────────────────────────────────────────────────────

    @property
    def offset(self) -> float:
        return self._offset

    def state(self) -> AdaptiveCalibState:
        corrected = self._corrected_residual()
        raw = self._raw_residual()
        n = len(self._pairs)
        conf = self._confidence()
        converged = (
            n >= self.min_pairs
            and conf != CONF_LOW
            and abs(corrected) <= self.converge_residual_bpm
        )
        # 分歧判斷用「校正後」殘差：offset 收斂後系統性偏差已被抵銷，
        # corrected 會趨近 0；唯有累積足夠配對後 corrected 仍偏大（例如 rPPG
        # 鎖到諧波、或真值差距超過 offset 上限而無法校平）才視為分歧。
        # 用 raw 殘差會讓穩定的系統性偏差在收斂後仍永遠顯示分歧（誤導）。
        diverged = (
            n >= 3 * self.min_pairs and abs(corrected) >= self.diverge_residual_bpm
        )
        return AdaptiveCalibState(
            offset_bpm=self._offset,
            raw_residual_bpm=raw,
            corrected_residual_bpm=corrected,
            pairs_used=n,
            total_observations=self._total_obs,
            accepted_observations=self._accepted_obs,
            confidence=conf,
            converged=converged,
            diverged=diverged,
            updated_at=self._updated_at,
        )

    def live_version(
        self,
        version_id: str = "v_adaptive_live",
        name: str = "自適應校準（即時）",
    ) -> CalibrationVersion:
        """回傳套用目前 offset 的即時校準版本，供 rPPG worker 的 loader 使用。"""
        return CalibrationVersion(
            id=version_id,
            name=name,
            model="bias",
            params=CalibrationParams(bpm_offset=self._offset, bpm_scale=1.0),
            note="心跳帶真值線上自適應（未落地）",
        )


def _clamp_abs(value: float, limit: float) -> float:
    if value > limit:
        return limit
    if value < -limit:
        return -limit
    return value


# ── P6：rPPG 解析參數有護欄 A/B 評估（純運算）──────────────────────────────

@dataclass(frozen=True)
class RppgParamAbVerdict:
    """A/B 評估快照。verdict ∈ {"pending", "adopt", "rollback"}。"""

    verdict: str = "pending"
    current_residual_bpm: float | None = None
    candidate_residual_bpm: float | None = None
    pairs_used: int = 0
    improve_streak: int = 0
    worsen_streak: int = 0


class RppgParamAbEvaluator:
    """有護欄的 rPPG 解析參數 A/B 評估。

    對**同一段訊號**分別以「現行參數」與「候選參數」重算的 BPM，各自對心跳帶真值算
    中位殘差。候選需在心跳帶上**明確更好**（殘差低於現行達 improve_margin）且連續
    confirm_windows 次評估才判 ``adopt``；**明確更差**（高於現行達 worsen_margin）連續
    confirm_windows 次則 ``rollback``；否則 ``pending``（維持現行）。

    這是使用者要的護欄核心「只採用被真值證明更好的參數、變差則回退」的決策層。
    本類別**不**產生候選參數內容、**不**套用參數、**不**觸碰 rPPG 引擎——那些屬 live
    自適應協調層，依專案護欄需在離線驗證管線落地後才啟用（見 CLAUDE.md P6）。

    純運算：無 Qt / 無執行緒 / 無 I/O；時間戳由呼叫端傳入。
    """

    def __init__(
        self,
        *,
        window_sec: float = 45.0,
        min_pairs: int = 6,
        improve_margin_bpm: float = 1.5,
        worsen_margin_bpm: float = 2.0,
        confirm_windows: int = 3,
        max_pair_bpm_gap: float = 40.0,
    ) -> None:
        self.window_sec = float(window_sec)
        self.min_pairs = int(min_pairs)
        self.improve_margin_bpm = float(improve_margin_bpm)
        self.worsen_margin_bpm = float(worsen_margin_bpm)
        self.confirm_windows = int(confirm_windows)
        self.max_pair_bpm_gap = float(max_pair_bpm_gap)
        # (ts, |belt−current|, |belt−candidate|)
        self._pairs: deque[tuple[float, float, float]] = deque()
        self._improve_streak = 0
        self._worsen_streak = 0

    def observe(
        self,
        t_now: float,
        belt_bpm: float,
        rppg_current_bpm: float,
        rppg_candidate_bpm: float,
    ) -> None:
        """餵入一筆三方配對（心跳帶真值、現行參數 BPM、候選參數 BPM）。"""
        if belt_bpm <= 0 or rppg_current_bpm <= 0 or rppg_candidate_bpm <= 0:
            return
        res_cur = abs(float(belt_bpm) - float(rppg_current_bpm))
        res_cand = abs(float(belt_bpm) - float(rppg_candidate_bpm))
        # 離群保護：任一殘差超過門檻視為壞樣本，不計入
        if res_cur > self.max_pair_bpm_gap or res_cand > self.max_pair_bpm_gap:
            return
        self._pairs.append((float(t_now), res_cur, res_cand))
        cutoff = float(t_now) - self.window_sec
        while self._pairs and self._pairs[0][0] < cutoff:
            self._pairs.popleft()

    def evaluate(self) -> RppgParamAbVerdict:
        """依目前視窗內的配對計算一次 A/B 判決並更新遲滯計數。"""
        n = len(self._pairs)
        if n < self.min_pairs:
            return RppgParamAbVerdict(
                verdict="pending", pairs_used=n,
                improve_streak=self._improve_streak, worsen_streak=self._worsen_streak,
            )
        cur = statistics.median(res_cur for _, res_cur, _ in self._pairs)
        cand = statistics.median(res_cand for _, _, res_cand in self._pairs)
        if cand + self.improve_margin_bpm <= cur:
            self._improve_streak += 1
            self._worsen_streak = 0
        elif cand >= cur + self.worsen_margin_bpm:
            self._worsen_streak += 1
            self._improve_streak = 0
        else:
            self._improve_streak = 0
            self._worsen_streak = 0
        verdict = "pending"
        if self._improve_streak >= self.confirm_windows:
            verdict = "adopt"
        elif self._worsen_streak >= self.confirm_windows:
            verdict = "rollback"
        return RppgParamAbVerdict(
            verdict=verdict,
            current_residual_bpm=float(cur),
            candidate_residual_bpm=float(cand),
            pairs_used=n,
            improve_streak=self._improve_streak,
            worsen_streak=self._worsen_streak,
        )

    def reset(self) -> None:
        self._pairs.clear()
        self._improve_streak = 0
        self._worsen_streak = 0


__all__ = [
    "ADAPTIVE_QUALITY_GATES",
    "AdaptiveCalibState",
    "OnlineBpmCalibrator",
    "RppgParamAbEvaluator",
    "RppgParamAbVerdict",
    "CONF_HIGH",
    "CONF_MED",
    "CONF_LOW",
]
