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

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import numpy as np

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


RoiWindow = tuple[Sequence[float], Sequence[float], Sequence[float], Sequence[float]]


def recompute_raw_bpm_from_roi_windows(
    roi_windows: Mapping[str, RoiWindow],
    roi_weights: Mapping[str, float],
    *,
    min_samples: int = 64,
    min_duration_sec: float = 6.0,
) -> float | None:
    """P6b-3a：以一組**靜態** ROI 權重，對同一段 per-ROI (t, r, g, b) 緩衝離線重算
    rPPG 的「原始 BPM」（raw，不套任何 BPM 穩定器/EMA/跳變護欄後處理）。

    輸入
    ----
    roi_windows
        ``{roi_name: (t, r, g, b)}``，即 :meth:`RppgEngine.get_roi_window` 的回傳格式
        （四條等長序列，t 為秒、r/g/b 為該 ROI 每幀遮罩區域的通道均值）。
    roi_weights
        ``{roi_name: weight}`` 靜態權重。只有 ``weight > 0`` 且在 roi_windows 中有
        非空資料的 ROI 會參與；其餘略過。權重不需預先正規化（加權平均
        ``sum(w*x)/sum(w)`` 對權重同比例縮放不變）。

    多 ROI 時間對齊
    --------------
    取所有參與 ROI 的**共同時間戳交集**，不做插值（使用者定案）。精確浮點比對即可：
    per-ROI 緩衝的時間戳皆來自同一幀的全域 ``t_now``（見
    :meth:`RppgEngine.push_roi_means`），跨 ROI 逐位元相同，故交集用精確相等為正確的
    join key。任一參與 ROI 在某時間戳缺格，該時間戳即被排除（不補值）。**已知行為**：
    同一 ROI 內若出現重複時間戳（正常流程下不會發生，因每幀 t_now 各自不同），
    ``{t: (r,g,b) for ...}`` 的 dict comprehension 會靜默保留最後一筆、覆蓋較早的
    重複樣本；本函式不對此另行報錯或去重。

    取樣頻率
    --------
    fs 沿用 :meth:`RppgEngine._fs` 的公式語意（來源：rppg/rppg_worker.py）：
    ``dt = (t[-1] - t[0]) / (n - 1)``、``fs = clip(1/dt, 8.0, 90.0)`` Hz。與 live 不同的是
    live 在樣本不足/退化時回退 ``target_fps``；離線角色改為直接回傳 ``None``（見下）。

    重算管線重用 rppg/rppg_worker.py 的既有 module-level 純函式
    ``pos_pulse`` → ``butter_bandpass``（頻帶 0.65/3.7 Hz 沿用，不改寫）→ ``welch_peak_hz``，
    確保與 live BPM 走同一套訊號處理。

    回傳
    ----
    重算得到的 raw BPM（float）；資料不足（參與 ROI 為空、交集為空、樣本數 < min_samples、
    時長 < min_duration_sec、時間戳退化、或 Welch 在心率頻帶找不到峰）時回傳 ``None``，
    不丟例外。

    設計註記（重要）
    ----------------
    本函式使用「**靜態**」權重，**不含**逐幀 pose 懲罰與品質門檻——因為 per-ROI 緩衝
    只保存每幀 ROI 均值，沒有保存逐幀的 pose/遮蔽/品質資訊。因此它**不是** live 混合
    管線（``collect_rppg_roi_sample_with_means`` + ``RppgEngine.compute``）的精確複製，
    也不保證與 live BPM 完全一致。它的角色是 **A/B 比較器**：current 與 candidate 兩組
    ROI 權重都用「同一套重算方法、同一段訊號」重算 BPM，只要比較公平（同法同料）即可
    據此判斷候選是否更接近心跳帶真值，不需與 live 逐位元對齊。
    """
    # 惰性匯入 rppg_worker 的純訊號函式：rppg_worker 於 module 頂層匯入 PySide6/cv2/
    # mediapipe，於此惰性匯入可維持本模組（純運算、無 Qt）的 import-time 輕量與可攜性。
    from rppg.rppg_worker import butter_bandpass, pos_pulse, welch_peak_hz

    # 參與 ROI：權重 > 0 且緩衝非空。
    per_roi: dict[str, dict[float, tuple[float, float, float]]] = {}
    active_weights: dict[str, float] = {}
    for name, window in roi_windows.items():
        try:
            weight = float(roi_weights.get(name, 0.0))
        except (TypeError, ValueError):
            continue
        if not (weight > 0.0) or not np.isfinite(weight):
            continue
        t_seq, r_seq, g_seq, b_seq = window
        n_pts = min(len(t_seq), len(r_seq), len(g_seq), len(b_seq))
        if n_pts == 0:
            continue
        mapping = {
            float(t_seq[i]): (float(r_seq[i]), float(g_seq[i]), float(b_seq[i]))
            for i in range(n_pts)
        }
        if not mapping:
            continue
        per_roi[name] = mapping
        active_weights[name] = weight

    if not per_roi:
        return None

    # 共同時間戳交集（精確浮點比對，不插值）。
    common: set[float] | None = None
    for mapping in per_roi.values():
        keys = set(mapping.keys())
        common = keys if common is None else (common & keys)
    if not common:
        return None

    common_sorted = sorted(common)
    n = len(common_sorted)
    if n < max(int(min_samples), 5):
        return None
    duration = common_sorted[-1] - common_sorted[0]
    if duration < float(min_duration_sec):
        return None

    dt = duration / (n - 1)
    if dt <= 1e-6:
        return None
    fs = float(np.clip(1.0 / dt, 8.0, 90.0))

    w_total = sum(active_weights.values())
    if w_total <= 0.0:
        return None

    r_mix = np.empty(n, dtype=np.float64)
    g_mix = np.empty(n, dtype=np.float64)
    b_mix = np.empty(n, dtype=np.float64)
    for i, tt in enumerate(common_sorted):
        acc_r = acc_g = acc_b = 0.0
        for name, weight in active_weights.items():
            rgb = per_roi[name][tt]
            acc_r += weight * rgb[0]
            acc_g += weight * rgb[1]
            acc_b += weight * rgb[2]
        r_mix[i] = acc_r / w_total
        g_mix[i] = acc_g / w_total
        b_mix[i] = acc_b / w_total

    # 防護：任一來源樣本含 NaN/Inf 會透過加權混合污染 r_mix/g_mix/b_mix，進而讓
    # pos_pulse/butter_bandpass 的輸出也含非有限值。np.argmax（welch_peak_hz 內部
    # 用於選頻譜峰）在含 NaN 的陣列上行為不穩定，可能選到某個仍為有限值的
    # peak_hz，繞過下方 `peak_hz <= 0.0` 護欄、靜默回傳錯誤 BPM。因此在混合完成後
    # 立刻擋一次，不讓非有限輸入進入 pos_pulse。
    if not (np.all(np.isfinite(r_mix)) and np.all(np.isfinite(g_mix)) and np.all(np.isfinite(b_mix))):
        return None

    pulse = pos_pulse(r_mix, g_mix, b_mix)
    filt = butter_bandpass(pulse, fs, 0.65, 3.7)
    peak_hz, _freqs, _pxx = welch_peak_hz(filt, fs)
    # 第二道防護：即便混合輸入有限，pos_pulse/butter_bandpass 內部運算理論上也可能
    # 因極端數值產生非有限中間結果；最終 BPM 算出前再次確認為有限值，避免任何來源
    # 的 NaN/Inf 悄悄流入回傳值。
    if not np.isfinite(peak_hz) or peak_hz <= 0.0:
        return None
    bpm = float(peak_hz * 60.0)
    if not np.isfinite(bpm):
        return None
    return bpm


# ── P6b-3b：rPPG 參數線上協調層（belt 殘差 → 候選 ROI 權重 → A/B → adopt）──────

# 協調層狀態機的四個相位常數。GATED 與 IDLE 語意相同（皆代表「本輪未觸發，可
# 重新檢查」），拆開純為讓 GUI/測試能區分「從未檢查過」與「檢查過但未觸發」。
COORD_IDLE = "idle"
COORD_GATED = "gated"
COORD_EVALUATING = "evaluating"
COORD_ADOPT = "adopt"
COORD_ROLLBACK = "rollback"
COORD_COOLDOWN = "cooldown"


@dataclass(frozen=True)
class RppgParamCoordinatorState:
    """:class:`RppgParamCoordinator` 狀態快照（GUI 輪詢/記錄用，immutable）。"""

    phase: str = COORD_IDLE
    candidate_roi_weights: Optional[dict[str, float]] = None
    verdict: Optional[RppgParamAbVerdict] = None
    adopted_roi_weights: Optional[dict[str, float]] = None
    cooldown_until: float = 0.0
    updated_at: float = field(default_factory=time.time)


def propose_roi_weight_candidate(
    current_weights: Mapping[str, float],
    per_roi_residual_hint: Mapping[str, float],
    *,
    step: float = 0.05,
) -> dict[str, float]:
    """P6b-3b：純函式、確定性——由目前 ROI 權重與（可選的）單 ROI 對心跳帶殘差
    提示，產生下一輪候選 ROI 權重。

    演算法：把 ``current_weights`` 正規化為比例後，挑一個 ROI 加固定 ``step``、
    其餘 ROI 依原比例等比縮減以維持總和為 1，最後投影進
    ``rppg.rppg_worker._project_fractions_onto_bounds`` 的護欄範圍
    （``ROI_WEIGHT_OVERRIDE_MIN_FRACTION``/``MAX_FRACTION``，目前 [0.05, 0.70]）。

    加重目標挑選規則（依 ``per_roi_residual_hint`` 是否提供有效資料分兩種情況）：
    - **有提示**（至少一個 ROI 有有限數值的殘差提示）：挑殘差**最小**（對心跳帶
      表現最好）的 ROI 加重，符合使用者裁決的「往表現好的 ROI 加小步長」語意。
    - **無提示**（``per_roi_residual_hint`` 為空，或所有值皆非有限數值）：挑目前
      **權重最小**的 ROI 加重（探索性 fallback，見下方「已知限制」）。

    引數
    ----
    current_weights
        目前生效的 ROI 權重（鍵需與 ``rppg.rppg_worker.ROI_SPECS`` 的 4 個 ROI
        名稱一致；缺鍵視為 0，多餘鍵忽略）。不需預先正規化。
    per_roi_residual_hint
        ``{roi_name: 該 ROI 對心跳帶的殘差絕對值}``（越小越好）。允許空字典或
        缺鍵——見上方「無提示」規則。

    回傳
    ----
    正規化（總和 1.0）且落在護欄範圍內的 4-ROI 權重 dict，鍵與
    ``rppg.rppg_worker.ROI_SPECS`` 完全一致。

    已知限制（**待使用者裁決**，見任務回報）：目前 GUI 尚未接上任何「單 ROI 對
    心跳帶真值」的即時探測管線——``candidate_bpm_ready`` 訊號僅回傳「現行 vs
    候選」兩個整體 BPM，不含逐 ROI 分解——因此 live 呼叫端目前恆定傳入空
    ``per_roi_residual_hint``，一律落入「無提示」fallback（權重最小者優先探索）。
    這保證協調層仍會依心跳帶真值做 adopt/rollback（護欄仍在），但候選**方向**的
    選擇目前是啟發式而非證據驅動；若要做到「以真實逐 ROI 殘差排序」，需額外
    seam（例如逐 ROI 呼叫 ``recompute_raw_bpm_from_roi_windows`` 並各自對心跳帶
    算殘差），超出本次 P6b-3b 明確要求的 worker 訊號介面，留待後續 P6b-3c 決定
    是否值得為此增加成本。
    """
    # 惰性匯入：避免把 rppg_worker（拉入 PySide6/cv2/mediapipe）掛進本模組
    # import-time 依賴，維持 adaptive_calibration 純運算、輕量、可攜。
    from rppg.rppg_worker import (
        ROI_SPECS,
        ROI_WEIGHT_OVERRIDE_MAX_FRACTION,
        ROI_WEIGHT_OVERRIDE_MIN_FRACTION,
        _project_fractions_onto_bounds,
    )

    names = [name for name, _ in ROI_SPECS]

    base_raw = {name: max(float(current_weights.get(name, 0.0)), 0.0) for name in names}
    total = sum(base_raw.values())
    if total <= 0.0:
        # 全零/缺失退化輸入：均分作為安全回退（不丟例外）。
        base = {name: 1.0 / len(names) for name in names}
    else:
        base = {name: v / total for name, v in base_raw.items()}

    valid_hints = {
        name: float(per_roi_residual_hint[name])
        for name in names
        if name in per_roi_residual_hint
        and per_roi_residual_hint[name] is not None
        and math.isfinite(float(per_roi_residual_hint[name]))
    }
    if valid_hints:
        # 有證據：挑殘差最小（表現最好）者加重；同值以名稱排序打破平手，確保確定性。
        boost_name = min(valid_hints, key=lambda n: (valid_hints[n], n))
    else:
        # 無證據 fallback：挑目前權重最小者做探索性加重；同值以名稱排序打破平手。
        boost_name = min(names, key=lambda n: (base[n], n))

    step = float(step)
    boosted = dict(base)
    boosted[boost_name] = base[boost_name] + step
    remaining_names = [n for n in names if n != boost_name]
    remaining_total_before = sum(base[n] for n in remaining_names)
    if remaining_total_before > 0.0:
        shrink_factor = max(0.0, 1.0 - boosted[boost_name]) / remaining_total_before
        for n in remaining_names:
            boosted[n] = base[n] * shrink_factor
    # else：全部權重原就集中在 boost_name（理論上不會發生，因護欄上限 < 1），
    # 其餘 ROI 維持 0，交由下方投影處理。

    boosted_total = sum(boosted.values()) or 1.0
    boosted = {n: v / boosted_total for n, v in boosted.items()}

    return _project_fractions_onto_bounds(
        boosted, ROI_WEIGHT_OVERRIDE_MIN_FRACTION, ROI_WEIGHT_OVERRIDE_MAX_FRACTION
    )


class RppgParamCoordinator:
    """P6b-3b：串起「belt 殘差 → 候選 ROI 權重 → A/B → adopt/rollback」的線上
    協調層。純運算：無 Qt / 無執行緒 / 無 I/O，不寫檔、不觸碰 rPPG 引擎、不呼叫
    ``CalibrationVersionStore``——那些是 GUI 呼叫端收到 adopt 判決後才執行的動作。

    狀態機（單向流轉，每次呼叫最多前進一步）::

        idle/gated ──(觸發判準成立)──▶ evaluating
        evaluating ──(observe_ab 判 adopt)───▶ adopt
        evaluating ──(observe_ab 判 rollback)─▶ rollback
        adopt/rollback ──(下次 tick)──▶ cooldown
        cooldown ──(冷卻期滿的下次 tick)──▶ idle（同次 tick 內可再檢查觸發判準）

    觸發 gate（使用者裁決 1，2026-07-04）：**只看 offset 是否已穩定**——
    ``OnlineBpmCalibrator.state().confidence != CONF_LOW`` 即可進入 evaluating；
    **殘差大小不再是觸發前置**。理由：`RppgParamAbEvaluator` 已提供「候選對心跳帶
    真值明確更好且連續 N 次才 adopt、變差回退」的護欄，那才是唯一安全篩子——
    一旦 offset 估計穩定就允許產候選、交由 A/B 裁決，配合冷卻期防抖即可。

    為何用 ``confidence != CONF_LOW`` 而非 ``converged``：``converged`` 定義本身要求
    ``abs(corrected_residual_bpm) <= converge_residual_bpm``（預設 3.0），會**排除**
    「offset 估計已穩定但仍有系統性殘差」的情境——而那正是 ROI 權重最可能有問題、
    最該嘗試調整的時候。``confidence``（基於配對數與離散度，見
    :meth:`OnlineBpmCalibrator._confidence`）表達「offset 估計是否可信/穩定」而**不**
    耦合殘差大小，故 ``!= CONF_LOW`` 是貼合原始動機的「offset 已穩定」訊號。
    （前一版依規格用 ``converged==True 且 corrected 殘差 >= 4.0``，兩條件數學互斥、
    ON 路徑恆為死碼；本版依使用者裁決 1 移除殘差前置與 ``trigger_residual_bpm``。）

    冷卻期（預設 120 秒，設計取捨）：adopt 或 rollback 之後強制冷卻，
    避免連續產生候選造成參數震盪；冷卻期內即使 offset 穩定也不會觸發新一輪。
    A/B pending 期間（evaluating）本身也不重複產候選（tick 在 evaluating 直接
    return），故不會狂產候選。

    GUI 典型用法（每 ~1 秒一次）::

        candidate = coord.tick(now, cal.state(), current_roi_weights)
        if candidate is not None:
            worker.set_candidate_roi_weights(candidate)   # 下發候選

        # worker candidate_bpm_ready 訊號到達時：
        verdict = coord.observe_ab(t_now, belt_bpm, cur_raw_bpm, cand_raw_bpm)
        if verdict is not None and verdict.verdict == "adopt":
            ...  # 存成新校準版本、更新 current_roi_weights
    """

    def __init__(
        self,
        *,
        evaluator: Optional[RppgParamAbEvaluator] = None,
        step_size: float = 0.05,
        cooldown_sec: float = 120.0,
    ) -> None:
        self.evaluator = evaluator if evaluator is not None else RppgParamAbEvaluator()
        self.step_size = float(step_size)
        self.cooldown_sec = float(cooldown_sec)
        self._phase = COORD_IDLE
        self._candidate: Optional[dict[str, float]] = None
        self._last_verdict: Optional[RppgParamAbVerdict] = None
        self._adopted: Optional[dict[str, float]] = None
        self._cooldown_until = 0.0
        self._updated_at = time.time()

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def candidate_roi_weights(self) -> Optional[dict[str, float]]:
        return dict(self._candidate) if self._candidate is not None else None

    def state(self) -> RppgParamCoordinatorState:
        return RppgParamCoordinatorState(
            phase=self._phase,
            candidate_roi_weights=dict(self._candidate) if self._candidate is not None else None,
            verdict=self._last_verdict,
            adopted_roi_weights=dict(self._adopted) if self._adopted is not None else None,
            cooldown_until=self._cooldown_until,
            updated_at=self._updated_at,
        )

    def tick(
        self,
        t_now: float,
        calib_state: AdaptiveCalibState,
        current_roi_weights: Mapping[str, float],
        per_roi_residual_hint: Optional[Mapping[str, float]] = None,
    ) -> Optional[dict[str, float]]:
        """推進狀態機一步；只在 idle/gated 且未在評估/冷卻中時可能產生新候選。

        回傳非 None 表示本次呼叫新產生了候選（呼叫端應下發給 worker）；回傳
        None 表示本次未產生新候選（仍在 evaluating 等待 A/B 觀測、仍在冷卻中、
        或本輪觸發判準不成立）。
        """
        self._updated_at = t_now

        if self._phase in (COORD_ADOPT, COORD_ROLLBACK):
            # 上一輪判決已由 observe_ab 定案，這裡才真正進入冷卻，讓呼叫端至少有
            # 一次機會讀到 adopt/rollback 這個終態（例如透過 state()）。
            self._enter_cooldown(t_now)
            return None

        if self._phase == COORD_COOLDOWN:
            if t_now < self._cooldown_until:
                return None
            self._phase = COORD_IDLE  # 冷卻期滿，落回 idle 後繼續本次 tick 的觸發檢查

        if self._phase == COORD_EVALUATING:
            # 已在評估中，等待 observe_ab 的觀測與判決，tick 本身不重新觸發。
            return None

        # phase ∈ {idle, gated}：每次 tick 重新檢查觸發 gate（使用者裁決 1）。
        # 只看 offset 是否已穩定（confidence != CONF_LOW），殘差大小不再是前置；
        # 候選好壞交由後續 A/B（RppgParamAbEvaluator）護欄裁決。
        if calib_state.confidence == CONF_LOW:
            self._phase = COORD_GATED
            return None

        candidate = propose_roi_weight_candidate(
            current_roi_weights, per_roi_residual_hint or {}, step=self.step_size
        )
        self._candidate = candidate
        self._phase = COORD_EVALUATING
        return dict(candidate)

    def observe_ab(
        self,
        t_now: float,
        belt_bpm: float,
        rppg_current_bpm: float,
        rppg_candidate_bpm: float,
    ) -> Optional[RppgParamAbVerdict]:
        """轉發一筆三方配對給內部 :class:`RppgParamAbEvaluator` 並依判決推進狀態機。

        只在 ``evaluating`` 階段生效；非評估階段呼叫視為 no-op（回傳 None），
        避免冷卻期或 idle 階段殘留的觀測污染下一輪評估。
        """
        self._updated_at = t_now
        if self._phase != COORD_EVALUATING:
            return None
        self.evaluator.observe(t_now, belt_bpm, rppg_current_bpm, rppg_candidate_bpm)
        verdict = self.evaluator.evaluate()
        self._last_verdict = verdict
        if verdict.verdict == "adopt":
            self._adopted = dict(self._candidate) if self._candidate is not None else None
            self._phase = COORD_ADOPT
        elif verdict.verdict == "rollback":
            self._phase = COORD_ROLLBACK
        return verdict

    def _enter_cooldown(self, t_now: float) -> None:
        self._cooldown_until = t_now + self.cooldown_sec
        self._phase = COORD_COOLDOWN
        self._candidate = None
        self.evaluator.reset()

    def reset(self) -> None:
        self._phase = COORD_IDLE
        self._candidate = None
        self._last_verdict = None
        self._adopted = None
        self._cooldown_until = 0.0
        self.evaluator.reset()


__all__ = [
    "ADAPTIVE_QUALITY_GATES",
    "AdaptiveCalibState",
    "OnlineBpmCalibrator",
    "RppgParamAbEvaluator",
    "RppgParamAbVerdict",
    "RppgParamCoordinator",
    "RppgParamCoordinatorState",
    "propose_roi_weight_candidate",
    "recompute_raw_bpm_from_roi_windows",
    "COORD_IDLE",
    "COORD_GATED",
    "COORD_EVALUATING",
    "COORD_ADOPT",
    "COORD_ROLLBACK",
    "COORD_COOLDOWN",
    "CONF_HIGH",
    "CONF_MED",
    "CONF_LOW",
]
