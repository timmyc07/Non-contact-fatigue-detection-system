"""個人清醒基線 profile（純運算層，無 Qt / 無 thread）。

用途：把行為/表情疲勞門檻從「寫死絕對常數」改為「相對每位駕駛員的清醒基線」。
本模組只負責資料結構、持久化與基線蒐集，門檻的實際消費在
`gui/fatigue_engine.py` / `gui/fatigue_scorer.py`。

**向後相容鐵律**：所有 `*_th(fallback)` 解析函式在「無有效基線」時，一律回傳
與傳入 fallback 逐位元相等的值——確保未注入 profile 的路徑（replay / golden /
utarldd_accuracy）輸出與現況完全一致。此鐵律的單一實作點為 `_resolve()`。
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # 僅型別檢查用，避免與 fatigue_engine 循環匯入
    from gui.fatigue_engine import FatigueMetrics

log = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parents[1]
PERSONAL_PROFILE_PATH = ROOT / "config" / "personal_profile" / "active.json"

SCHEMA_VERSION = 1

# ── 門檻推導常數（把清醒基線映射到門檻；對「典型清醒者」會還原成現行預設值） ──
#   PERCLOS：清醒者 PERCLOS 中位數趨近 0，p90 約 0.01；margin 讓門檻落在現行預設附近。
PERCLOS_LOW_MARGIN = 0.01      # low_th ≈ awake_p90 + 此值（典型 → ~0.02，對齊預設）
PERCLOS_TIRED_MARGIN = 0.04    # tired_th ≈ awake_p90 + 此值（典型 → ~0.05，對齊預設）
GAZE_STD_FACTOR = 1.5          # gaze 固定門檻 ≈ 清醒 gaze 位置 std × 此值（典型 → ~0.015）
SACCADE_LOW_FACTOR = 0.6       # 低掃視門檻 ≈ 清醒掃視頻率 × 此值（典型 → ~1.0/min）
#   防呆：個人化門檻夾在 [fallback × LO, fallback × HI]，避免異常基線把系統拉歪。
CLAMP_LO_FACTOR = 0.5
CLAMP_HI_FACTOR = 3.0

# ── 蒐集器護欄 ──
DEFAULT_WINDOW_SEC_AUTO = 75.0
DEFAULT_WINDOW_SEC_MANUAL = 60.0
DEFAULT_MIN_FRAMES = 150          # 低於此視為樣本不足 → profile.valid = False
MIN_FIELD_SAMPLES = 30            # 單一欄位低於此樣本數 → 該欄位為 None（退回 fallback）
MIN_BLINK_SAMPLES = 3             # blink-temporal 基線需要的最少眨眼次數


def _clamp(value: float, lo: float, hi: float) -> float:
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, value))


def _percentile(values: list[float], q: float) -> Optional[float]:
    """線性插值百分位（q 為 0~100）。樣本不足回 None。"""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (q / 100.0) * (len(ordered) - 1)
    lo_i = int(math.floor(rank))
    hi_i = int(math.ceil(rank))
    if lo_i == hi_i:
        return float(ordered[lo_i])
    frac = rank - lo_i
    return float(ordered[lo_i] * (1.0 - frac) + ordered[hi_i] * frac)


def _median_or_none(values: list[float]) -> Optional[float]:
    if len(values) < MIN_FIELD_SAMPLES:
        return None
    return float(statistics.median(values))


def _mean_std(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    if len(values) < MIN_BLINK_SAMPLES:
        return None, None
    mean = float(statistics.fmean(values))
    std = float(statistics.pstdev(values)) if len(values) > 1 else 0.0
    return mean, std


@dataclass
class PersonalProfile:
    """一位駕駛員的清醒基線。所有基線欄位皆 Optional；缺欄一律退回 fallback。"""

    profile_id: str = "default"
    schema_version: int = SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    source: str = "auto"           # "auto" | "manual"
    sample_sec: float = 0.0
    n_frames: int = 0
    valid: bool = False            # 樣本是否足量；False 時所有門檻退回 fallback

    # 清醒基線欄位（皆 Optional）
    perclos_awake_median: Optional[float] = None
    perclos_awake_p90: Optional[float] = None
    gaze_fix_std_awake: Optional[float] = None
    saccade_freq_awake_pm: Optional[float] = None
    fixation_dur_awake: Optional[float] = None
    brow_dist_norm_awake: Optional[float] = None
    blink_dur_mean: Optional[float] = None
    blink_dur_std: Optional[float] = None
    blink_openvel_mean: Optional[float] = None
    blink_openvel_std: Optional[float] = None

    # ── fallback 鐵律的單一實作點 ──────────────────────────────────────────
    def _resolve(self, value: Optional[float], fallback: float) -> float:
        """有有效基線就用個人值，否則逐位元回傳 fallback。"""
        if self.valid and value is not None:
            return value
        return fallback

    # ── PERCLOS 門檻（P1 消費）────────────────────────────────────────────
    def perclos_low_th(self, fallback: float) -> float:
        if not (self.valid and self.perclos_awake_p90 is not None):
            return fallback
        personalized = self.perclos_awake_p90 + PERCLOS_LOW_MARGIN
        return _clamp(personalized, fallback * CLAMP_LO_FACTOR, fallback * CLAMP_HI_FACTOR)

    def perclos_tired_th(self, fallback: float) -> float:
        if not (self.valid and self.perclos_awake_p90 is not None):
            return fallback
        personalized = self.perclos_awake_p90 + PERCLOS_TIRED_MARGIN
        return _clamp(personalized, fallback * CLAMP_LO_FACTOR, fallback * CLAMP_HI_FACTOR)

    def perclos_composite_full(self, fallback: float) -> float:
        # composite 飽和點與 tired 門檻同語意（現行兩者皆 0.05）
        if not (self.valid and self.perclos_awake_p90 is not None):
            return fallback
        personalized = self.perclos_awake_p90 + PERCLOS_TIRED_MARGIN
        return _clamp(personalized, fallback * CLAMP_LO_FACTOR, fallback * CLAMP_HI_FACTOR)

    # ── Gaze 門檻（P2 消費）───────────────────────────────────────────────
    def gaze_fixed_std_th(self, fallback: float) -> float:
        if not (self.valid and self.gaze_fix_std_awake is not None):
            return fallback
        personalized = self.gaze_fix_std_awake * GAZE_STD_FACTOR
        return _clamp(personalized, fallback * CLAMP_LO_FACTOR, fallback * CLAMP_HI_FACTOR)

    def saccade_low_pm(self, fallback: float) -> float:
        if not (self.valid and self.saccade_freq_awake_pm is not None):
            return fallback
        personalized = self.saccade_freq_awake_pm * SACCADE_LOW_FACTOR
        return _clamp(personalized, fallback * CLAMP_LO_FACTOR, fallback * CLAMP_HI_FACTOR)

    # ── 序列化 ────────────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PersonalProfile":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class PersonalProfileStore:
    """個人 profile 的極簡 JSON store（仿 CalibrationStore）。

    存於 config/personal_profile/active.json（不入版控）。單一 active + factory_reset。
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or PERSONAL_PROFILE_PATH

    def load(self) -> Optional[PersonalProfile]:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            return PersonalProfile.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 — 容錯載入，壞檔視為無 profile
            log.warning("個人 profile 讀取失敗：%s", exc)
            return None

    def save(self, profile: PersonalProfile) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("個人 profile 寫入失敗：%s", exc)

    def factory_reset(self) -> None:
        """刪除 active profile，回到無個人基線（=現行寫死門檻）狀態。"""
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception as exc:  # noqa: BLE001
            log.warning("個人 profile 刪除失敗：%s", exc)


class PersonalBaselineCollector:
    """在一段「已知清醒」時間內蒐集行為指標，finalize 成 PersonalProfile。

    只在 metrics.calibrated 且 metrics.face_detected 時採樣。純運算，不涉時間來源，
    時間戳由呼叫端傳入（與 replay deterministic 設計一致）。
    """

    def __init__(
        self,
        *,
        window_sec: float = DEFAULT_WINDOW_SEC_AUTO,
        min_frames: int = DEFAULT_MIN_FRAMES,
        now_iso: str = "",
    ) -> None:
        self.window_sec = float(window_sec)
        self.min_frames = int(min_frames)
        self._now_iso = now_iso
        self._start_t: Optional[float] = None
        self._last_t: Optional[float] = None
        self._n_frames = 0
        self._last_blink_count: Optional[int] = None

        self._perclos: list[float] = []
        self._gaze_x: list[float] = []
        self._gaze_y: list[float] = []
        self._saccade_pm: list[float] = []
        self._fixation: list[float] = []
        self._brow: list[float] = []
        self._blink_dur: list[float] = []
        self._blink_openvel: list[float] = []

    @property
    def elapsed_sec(self) -> float:
        if self._start_t is None or self._last_t is None:
            return 0.0
        return max(0.0, self._last_t - self._start_t)

    @property
    def progress(self) -> float:
        if self.window_sec <= 0:
            return 1.0
        return _clamp(self.elapsed_sec / self.window_sec, 0.0, 1.0)

    def is_full(self) -> bool:
        return self.elapsed_sec >= self.window_sec and self._n_frames >= self.min_frames

    def observe(self, metrics: "FatigueMetrics", t_now: float) -> None:
        if not (getattr(metrics, "calibrated", False) and getattr(metrics, "face_detected", False)):
            return
        if self._start_t is None:
            self._start_t = t_now
        self._last_t = t_now
        self._n_frames += 1

        self._perclos.append(float(metrics.perclos))
        self._gaze_x.append(float(metrics.gaze_x))
        self._gaze_y.append(float(metrics.gaze_y))
        self._brow.append(float(metrics.brow_dist_norm))
        if getattr(metrics, "saccade_window_ready", False):
            self._saccade_pm.append(float(metrics.saccade_freq_pm))
        if float(metrics.fixation_duration) > 0.0:
            self._fixation.append(float(metrics.fixation_duration))

        # 眨眼為事件性指標：只在 blink_count 遞增時記錄該次眨眼特徵
        bc = int(getattr(metrics, "blink_count", 0))
        if self._last_blink_count is not None and bc > self._last_blink_count:
            if float(metrics.blink_duration_sec) > 0.0:
                self._blink_dur.append(float(metrics.blink_duration_sec))
            if float(metrics.blink_opening_velocity) > 0.0:
                self._blink_openvel.append(float(metrics.blink_opening_velocity))
        self._last_blink_count = bc

    def finalize(self, source: str = "auto", profile_id: str = "default") -> PersonalProfile:
        gaze_std: Optional[float] = None
        if len(self._gaze_x) >= MIN_FIELD_SAMPLES and len(self._gaze_y) >= MIN_FIELD_SAMPLES:
            gaze_std = float(math.sqrt(
                statistics.pvariance(self._gaze_x) + statistics.pvariance(self._gaze_y)
            ))

        blink_dur_mean, blink_dur_std = _mean_std(self._blink_dur)
        blink_ov_mean, blink_ov_std = _mean_std(self._blink_openvel)

        valid = self._n_frames >= self.min_frames

        return PersonalProfile(
            profile_id=profile_id,
            schema_version=SCHEMA_VERSION,
            created_at=self._now_iso,
            updated_at=self._now_iso,
            source=source,
            sample_sec=round(self.elapsed_sec, 3),
            n_frames=self._n_frames,
            valid=valid,
            perclos_awake_median=_median_or_none(self._perclos),
            perclos_awake_p90=(_percentile(self._perclos, 90.0)
                               if len(self._perclos) >= MIN_FIELD_SAMPLES else None),
            gaze_fix_std_awake=gaze_std,
            saccade_freq_awake_pm=_median_or_none(self._saccade_pm),
            fixation_dur_awake=_median_or_none(self._fixation),
            brow_dist_norm_awake=_median_or_none(self._brow),
            blink_dur_mean=blink_dur_mean,
            blink_dur_std=blink_dur_std,
            blink_openvel_mean=blink_ov_mean,
            blink_openvel_std=blink_ov_std,
        )


def resolve_active_baseline(
    manual: Optional[PersonalProfile],
    auto_finalized: Optional[PersonalProfile],
) -> Optional[PersonalProfile]:
    """優先序：manual（持久化）> auto（本 session finalized）> None。

    只採用 valid 的 profile；非 valid 者視同不存在。
    """
    if manual is not None and manual.valid:
        return manual
    if auto_finalized is not None and auto_finalized.valid:
        return auto_finalized
    return None
