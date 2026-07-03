"""個人清醒基線 profile 純運算層測試（P0）。

重點守護「向後相容鐵律」：無有效基線時，每個門檻解析函式必須逐位元回傳 fallback。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.fatigue_engine import FatigueMetrics  # noqa: E402
from gui.personal_profile import (  # noqa: E402
    PersonalBaselineCollector,
    PersonalProfile,
    PersonalProfileStore,
    resolve_active_baseline,
)


# ── 門檻解析：向後相容鐵律 ────────────────────────────────────────────────

_TH_METHODS = [
    ("perclos_low_th", 0.02),
    ("perclos_tired_th", 0.05),
    ("perclos_composite_full", 0.05),
    ("perclos_score_mild_th", 0.015),
    ("perclos_score_high_th", 0.07),
    ("gaze_fixed_std_th", 0.015),
    ("saccade_low_pm", 1.0),
]

_ODD_FALLBACKS = [0.017345, 0.5, 1.0, 42.0, 0.0]


def test_invalid_profile_returns_fallback_bit_identical() -> None:
    # valid=False：即使欄位有值，也必須回傳 fallback 本身。
    p = PersonalProfile(
        valid=False,
        perclos_awake_p90=0.9,
        gaze_fix_std_awake=0.9,
        saccade_freq_awake_pm=99.0,
    )
    for name, _default in _TH_METHODS:
        method = getattr(p, name)
        for fb in _ODD_FALLBACKS:
            assert method(fb) == fb, f"{name}({fb}) 應逐位元回傳 fallback"


def test_valid_profile_with_none_fields_returns_fallback() -> None:
    # valid=True 但相關欄位為 None：仍必須回傳 fallback。
    p = PersonalProfile(valid=True)  # 所有基線欄位皆 None
    for name, _default in _TH_METHODS:
        method = getattr(p, name)
        for fb in _ODD_FALLBACKS:
            assert method(fb) == fb


def test_typical_awake_baseline_reproduces_defaults() -> None:
    # 典型清醒者（p90≈0.01、gaze std≈0.01、saccade≈1.667）→ 門檻應還原到現行預設附近。
    p = PersonalProfile(
        valid=True,
        perclos_awake_p90=0.01,
        gaze_fix_std_awake=0.01,
        saccade_freq_awake_pm=1.6667,
    )
    assert abs(p.perclos_low_th(0.02) - 0.02) < 1e-9
    assert abs(p.perclos_tired_th(0.05) - 0.05) < 1e-9
    assert abs(p.gaze_fixed_std_th(0.015) - 0.015) < 1e-9
    assert abs(p.saccade_low_pm(1.0) - 1.0) < 1e-3


def test_droopy_baseline_raises_perclos_threshold() -> None:
    # 清醒時 PERCLOS 本就偏高的人：門檻應被拉高（減少誤報），但夾在 fallback×3 內。
    p = PersonalProfile(valid=True, perclos_awake_p90=0.03)
    low = p.perclos_low_th(0.02)
    assert low > 0.02
    assert low <= 0.02 * 3.0 + 1e-9


def test_perclos_score_map_methods_reproduce_defaults_and_clamp() -> None:
    # 典型清醒者 → scorer PERCLOS 映射門檻還原到現行預設（0.015 / 0.07）。
    p = PersonalProfile(valid=True, perclos_awake_p90=0.01)
    assert abs(p.perclos_score_mild_th(0.015) - 0.015) < 1e-9
    assert abs(p.perclos_score_high_th(0.07) - 0.07) < 1e-9
    # 異常基線夾在 fallback×3。
    ext = PersonalProfile(valid=True, perclos_awake_p90=0.9)
    assert ext.perclos_score_mild_th(0.015) == 0.015 * 3.0
    assert ext.perclos_score_high_th(0.07) == 0.07 * 3.0


def test_extreme_baseline_is_clamped() -> None:
    # 異常基線不得把門檻拉到失控：夾在 [fallback×0.5, fallback×3]。
    p = PersonalProfile(valid=True, perclos_awake_p90=0.9, gaze_fix_std_awake=0.9)
    assert p.perclos_low_th(0.02) == 0.02 * 3.0
    assert p.gaze_fixed_std_th(0.015) == 0.015 * 3.0


# ── 蒐集器 ────────────────────────────────────────────────────────────────

def _feed(collector: PersonalBaselineCollector, n: int, *, fps: float = 30.0,
          perclos: float = 0.008, blinks: int = 5,
          calibrated: bool = True, face: bool = True) -> None:
    dt = 1.0 / fps
    blink_at = set()
    if blinks > 0:
        step = max(1, n // (blinks + 1))
        blink_at = {step * (k + 1) for k in range(blinks)}
    bc = 0
    for i in range(n):
        if i in blink_at:
            bc += 1
        m = FatigueMetrics(
            face_detected=face,
            calibrated=calibrated,
            perclos=perclos,
            gaze_x=0.5 + (0.002 if i % 2 else -0.002),
            gaze_y=0.5 + (0.001 if i % 3 else -0.001),
            brow_dist_norm=1.0,
            saccade_freq_pm=1.5,
            saccade_window_ready=True,
            fixation_duration=0.4,
            blink_count=bc,
            blink_duration_sec=0.12,
            blink_amplitude=0.3,
            blink_opening_velocity=0.8,
        )
        collector.observe(m, i * dt)


def test_collector_finalize_populates_fields() -> None:
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=50, now_iso="2026-07-04T00:00:00")
    _feed(c, 90)
    prof = c.finalize(source="manual")
    assert prof.valid is True
    assert prof.n_frames == 90
    assert prof.source == "manual"
    assert prof.perclos_awake_median is not None
    assert prof.perclos_awake_p90 is not None
    assert prof.gaze_fix_std_awake is not None
    assert prof.saccade_freq_awake_pm is not None
    assert prof.fixation_dur_awake is not None
    assert prof.blink_dur_mean is not None
    assert abs(prof.blink_dur_mean - 0.12) < 1e-6


def test_collector_populates_blink_amplitude() -> None:
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=50)
    _feed(c, 90)
    prof = c.finalize()
    assert prof.blink_amp_mean is not None
    assert prof.blink_openvel_mean is not None


def test_blink_feature_baseline_helper() -> None:
    # 欄位齊全 → 回結構完整 dict；缺 amplitude → None；invalid → None。
    full = PersonalProfile(
        valid=True, blink_dur_mean=0.12, blink_dur_std=0.02,
        blink_amp_mean=0.3, blink_amp_std=0.05,
        blink_openvel_mean=0.8, blink_openvel_std=0.1,
    )
    base = full.blink_feature_baseline()
    assert base is not None
    assert set(base.keys()) == {"duration", "amplitude", "opening_velocity"}
    assert base["duration"] == (0.12, 0.02)

    missing_amp = PersonalProfile(
        valid=True, blink_dur_mean=0.12, blink_dur_std=0.02,
        blink_openvel_mean=0.8, blink_openvel_std=0.1,
    )
    assert missing_amp.blink_feature_baseline() is None

    invalid = PersonalProfile(
        valid=False, blink_dur_mean=0.12, blink_dur_std=0.02,
        blink_amp_mean=0.3, blink_amp_std=0.05,
        blink_openvel_mean=0.8, blink_openvel_std=0.1,
    )
    assert invalid.blink_feature_baseline() is None


def test_brow_baseline_helper() -> None:
    assert PersonalProfile(valid=True, brow_dist_norm_awake=0.42).brow_baseline() == 0.42
    assert PersonalProfile(valid=False, brow_dist_norm_awake=0.42).brow_baseline() is None
    assert PersonalProfile(valid=True).brow_baseline() is None


def test_collector_insufficient_samples_is_invalid() -> None:
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=50)
    _feed(c, 20, blinks=0)
    prof = c.finalize()
    assert prof.valid is False
    assert prof.n_frames == 20


def test_collector_ignores_uncalibrated_frames() -> None:
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=10)
    _feed(c, 30, calibrated=False)
    prof = c.finalize()
    assert prof.n_frames == 0
    assert prof.valid is False


def test_collector_is_full_requires_window_and_frames() -> None:
    c = PersonalBaselineCollector(window_sec=1.0, min_frames=20)
    _feed(c, 40, fps=30.0)  # 40 幀 / 30fps ≈ 1.3s ≥ 1.0s，且 40 ≥ 20
    assert c.is_full() is True


# ── Store round-trip / factory_reset ─────────────────────────────────────

def test_store_round_trip(tmp_path: Path) -> None:
    store = PersonalProfileStore(path=tmp_path / "active.json")
    assert store.load() is None  # 尚無檔
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=50)
    _feed(c, 90)
    prof = c.finalize(source="manual")
    store.save(prof)
    loaded = store.load()
    assert loaded is not None
    assert loaded.to_dict() == prof.to_dict()


def test_store_factory_reset(tmp_path: Path) -> None:
    store = PersonalProfileStore(path=tmp_path / "active.json")
    c = PersonalBaselineCollector(window_sec=2.0, min_frames=50)
    _feed(c, 90)
    store.save(c.finalize())
    assert store.load() is not None
    store.factory_reset()
    assert store.load() is None


def test_store_corrupt_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "active.json"
    path.write_text("{ not json", encoding="utf-8")
    assert PersonalProfileStore(path=path).load() is None


# ── 優先序 ────────────────────────────────────────────────────────────────

def test_resolve_priority_manual_over_auto() -> None:
    manual = PersonalProfile(valid=True, source="manual", perclos_awake_p90=0.02)
    auto = PersonalProfile(valid=True, source="auto", perclos_awake_p90=0.01)
    assert resolve_active_baseline(manual, auto) is manual
    assert resolve_active_baseline(None, auto) is auto
    assert resolve_active_baseline(None, None) is None


def test_resolve_skips_invalid() -> None:
    manual_invalid = PersonalProfile(valid=False, source="manual")
    auto = PersonalProfile(valid=True, source="auto", perclos_awake_p90=0.01)
    assert resolve_active_baseline(manual_invalid, auto) is auto
    assert resolve_active_baseline(manual_invalid, None) is None
