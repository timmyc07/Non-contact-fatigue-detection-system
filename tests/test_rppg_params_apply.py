"""P6b-2：CalibrationParams.rppg_params 的 ROI base_weights 套用層測試。

驗證重點：
1. `resolve_roi_weights_override()`（純函式）：合法輸入 clamp+正規化正確；
   未知 ROI 名稱、缺 ROI、非正值、NaN/Inf、非 dict、非數值等異常輸入一律
   回傳 None，且不丟例外（不半套）。
2. `apply_roi_weights_override()`：override=None 時回傳同一個 tuning 物件
   （bit-identical、無複製）；override 非 None 時只替換 rppg_roi.base_weights，
   其餘欄位不變。
3. `resolve_effective_rppg_tuning()`：explicit_override 優先於 calibration_loader；
   calibration_loader 例外/回傳 None/rppg_params 為 None 時皆視為無覆寫；
   只呼叫 calibration_loader 一次。
4. 整合：`_roi_weights_from_pose()` 在 override=None 時與現行 ROI_BASE_WEIGHTS
   結果一致；override 非 None 時反映覆寫後的相對比例。
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from gui.mediapipe_tuning import load_mediapipe_tuning  # noqa: E402
from rppg.calibration import CalibrationParams, CalibrationVersion  # noqa: E402
from rppg.rppg_worker import (  # noqa: E402
    FOREHEAD_ROI_IDX,
    GLABELLA_ROI_IDX,
    LEFT_CHEEK_ROI_IDX,
    RIGHT_CHEEK_ROI_IDX,
    ROI_SPECS,
    ROI_WEIGHT_OVERRIDE_MAX_FRACTION,
    ROI_WEIGHT_OVERRIDE_MIN_FRACTION,
    RoiGeometryTracker,
    _roi_weights_from_pose,
    apply_roi_weights_override,
    collect_rppg_roi_sample,
    collect_rppg_roi_sample_with_means,
    resolve_effective_rppg_tuning,
    resolve_roi_weights_override,
)

_ROI_NAMES = {name for name, _ in ROI_SPECS}


def _fake_landmarks() -> list[SimpleNamespace]:
    """與 tests/test_mediapipe_enhancements.py 相同的合成臉部關鍵點。"""
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[1] = SimpleNamespace(x=0.50, y=0.45)
    pts[10] = SimpleNamespace(x=0.50, y=0.20)
    pts[152] = SimpleNamespace(x=0.50, y=0.82)
    pts[234] = SimpleNamespace(x=0.34, y=0.52)
    pts[454] = SimpleNamespace(x=0.66, y=0.52)
    pts[33] = SimpleNamespace(x=0.38, y=0.36)
    pts[263] = SimpleNamespace(x=0.62, y=0.38)
    for idx in (338, 297, 332, 284, 251, 389, 356, 323, 361, 288, 397, 365, 379, 378, 400, 377,
                148, 176, 149, 150, 136, 172, 58, 132, 93, 127, 162, 21, 54, 103, 67, 109):
        pts[idx] = SimpleNamespace(x=0.50, y=0.35)
    return pts


# ── resolve_roi_weights_override：合法輸入 ──────────────────────────────────

def test_resolve_none_or_empty_returns_none() -> None:
    assert resolve_roi_weights_override(None) is None
    assert resolve_roi_weights_override({}) is None


def test_resolve_missing_roi_weights_key_returns_none() -> None:
    assert resolve_roi_weights_override({"band": [0.65, 3.7]}) is None


def test_resolve_valid_weights_are_normalised() -> None:
    raw = {"roi_weights": {"forehead": 0.30, "L_cheek": 0.30, "R_cheek": 0.30, "glabella": 0.10}}
    out = resolve_roi_weights_override(raw)
    assert out is not None
    assert set(out.keys()) == _ROI_NAMES
    assert abs(sum(out.values()) - 1.0) < 1e-9
    # 輸入已在 clamp 範圍內，相對比例應保持一致（forehead == L_cheek == R_cheek）。
    assert abs(out["forehead"] - out["L_cheek"]) < 1e-9
    assert abs(out["forehead"] - out["R_cheek"]) < 1e-9
    assert out["glabella"] < out["forehead"]


def test_resolve_clamps_extreme_dominance() -> None:
    """單一 ROI 給極端大值，其餘給極小正值：正規化後應被 clamp 到
    ROI_WEIGHT_OVERRIDE_MAX_FRACTION / MIN_FRACTION 範圍內。"""
    raw = {"roi_weights": {"forehead": 1000.0, "L_cheek": 1e-6, "R_cheek": 1e-6, "glabella": 1e-6}}
    out = resolve_roi_weights_override(raw)
    assert out is not None
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["forehead"] <= ROI_WEIGHT_OVERRIDE_MAX_FRACTION + 1e-9
    for name in ("L_cheek", "R_cheek", "glabella"):
        assert out[name] >= ROI_WEIGHT_OVERRIDE_MIN_FRACTION - 1e-9


def test_resolve_clamps_two_sided_extreme_simultaneously() -> None:
    """兩個 ROI 給極端大值、兩個給極端小值：驗證投影演算法在「多個元素同時
    違反邊界」時仍收斂到界內且總和為 1.0（回歸測試：曾經的單輪同時 clamp
    寫法在此案例下總和會跑掉，見 docs/2026-07-04-p6b-handoff.md 的
    clamp/正規化語意討論）。"""
    raw = {"roi_weights": {"forehead": 500.0, "L_cheek": 500.0, "R_cheek": 1e-6, "glabella": 1e-6}}
    out = resolve_roi_weights_override(raw)
    assert out is not None
    assert abs(sum(out.values()) - 1.0) < 1e-9
    for name in ("forehead", "L_cheek"):
        assert out[name] <= ROI_WEIGHT_OVERRIDE_MAX_FRACTION + 1e-9
    for name in ("R_cheek", "glabella"):
        assert out[name] >= ROI_WEIGHT_OVERRIDE_MIN_FRACTION - 1e-9


# ── resolve_roi_weights_override：異常輸入一律回退 None、不丟例外 ──────────

def test_resolve_rejects_non_dict_rppg_params(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override("not_a_dict") is None  # type: ignore[arg-type]


def test_resolve_rejects_non_dict_roi_weights(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override({"roi_weights": "nope"}) is None


def test_resolve_rejects_incomplete_roi_set(caplog) -> None:
    raw = {"roi_weights": {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.3}}  # 缺 glabella
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw) is None


def test_resolve_rejects_unknown_roi_name(caplog) -> None:
    raw = {"roi_weights": {"forehead": 0.25, "L_cheek": 0.25, "R_cheek": 0.25, "chin": 0.25}}
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw) is None


def test_resolve_rejects_zero_or_negative_value(caplog) -> None:
    raw_zero = {"roi_weights": {"forehead": 0.0, "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.5}}
    raw_neg = {"roi_weights": {"forehead": -0.1, "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.6}}
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw_zero) is None
        assert resolve_roi_weights_override(raw_neg) is None


def test_resolve_rejects_nan_and_inf(caplog) -> None:
    raw_nan = {"roi_weights": {"forehead": math.nan, "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.25}}
    raw_inf = {"roi_weights": {"forehead": math.inf, "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.25}}
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw_nan) is None
        assert resolve_roi_weights_override(raw_inf) is None


def test_resolve_rejects_non_numeric_value(caplog) -> None:
    raw = {"roi_weights": {"forehead": "high", "L_cheek": 0.25, "R_cheek": 0.25, "glabella": 0.25}}
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw) is None


def test_resolve_no_partial_application_on_single_bad_field(caplog) -> None:
    """三個欄位合法、一個非法：整組覆寫失效（None），而非只丟掉壞的那個 ROI。"""
    raw = {"roi_weights": {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.3, "glabella": -1.0}}
    with caplog.at_level(logging.WARNING):
        assert resolve_roi_weights_override(raw) is None


# ── apply_roi_weights_override：None 逐位元不變 / 非 None 只換 base_weights ──

def test_apply_none_returns_same_object() -> None:
    tuning = load_mediapipe_tuning()
    out = apply_roi_weights_override(tuning, None)
    assert out is tuning


def test_apply_override_replaces_only_base_weights() -> None:
    tuning = load_mediapipe_tuning()
    override = {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.2, "glabella": 0.1}
    out = apply_roi_weights_override(tuning, override)

    assert out is not tuning
    assert out.rppg_roi.base_weights == override
    # 其餘 rppg_roi 欄位與 tuning 欄位不變。
    assert out.rppg_roi.roll_full_penalty_deg == tuning.rppg_roi.roll_full_penalty_deg
    assert out.rppg_roi.min_roi_weight == tuning.rppg_roi.min_roi_weight
    assert out.face_landmarker == tuning.face_landmarker
    assert out.quality == tuning.quality
    # 原始 tuning 物件未被就地修改。
    assert tuning.rppg_roi.base_weights != override


# ── resolve_effective_rppg_tuning：優先序與容錯 ─────────────────────────────

def test_effective_tuning_explicit_override_takes_priority() -> None:
    tuning = load_mediapipe_tuning()
    override = {"forehead": 0.5, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.1}
    calls = []

    def loader():
        calls.append(1)
        return None

    out = resolve_effective_rppg_tuning(tuning, override, loader)
    assert out.rppg_roi.base_weights == override
    assert calls == []  # explicit_override 非 None 時完全不呼叫 loader


def test_effective_tuning_no_override_no_loader_is_identity() -> None:
    tuning = load_mediapipe_tuning()
    out = resolve_effective_rppg_tuning(tuning, None, None)
    assert out is tuning


def test_effective_tuning_loader_returns_none_version_is_identity() -> None:
    tuning = load_mediapipe_tuning()
    calls = []

    def loader():
        calls.append(1)
        return None

    out = resolve_effective_rppg_tuning(tuning, None, loader)
    assert out is tuning
    assert calls == [1]  # 只呼叫一次


def test_effective_tuning_loader_exception_is_identity() -> None:
    tuning = load_mediapipe_tuning()

    def loader():
        raise RuntimeError("boom")

    out = resolve_effective_rppg_tuning(tuning, None, loader)
    assert out is tuning


def test_effective_tuning_version_without_rppg_params_is_identity() -> None:
    tuning = load_mediapipe_tuning()
    version = CalibrationVersion(id="v1", name="test", model="bias", params=CalibrationParams())

    out = resolve_effective_rppg_tuning(tuning, None, lambda: version)
    assert out is tuning


def test_effective_tuning_version_with_valid_rppg_params_overrides() -> None:
    tuning = load_mediapipe_tuning()
    override_raw = {"roi_weights": {"forehead": 0.4, "L_cheek": 0.3, "R_cheek": 0.2, "glabella": 0.1}}
    version = CalibrationVersion(
        id="v1", name="test", model="bias",
        params=CalibrationParams(rppg_params=override_raw),
    )

    out = resolve_effective_rppg_tuning(tuning, None, lambda: version)
    assert out is not tuning
    expected = resolve_roi_weights_override(override_raw)
    assert out.rppg_roi.base_weights == expected


def test_effective_tuning_version_with_invalid_rppg_params_is_identity() -> None:
    tuning = load_mediapipe_tuning()
    version = CalibrationVersion(
        id="v1", name="test", model="bias",
        params=CalibrationParams(rppg_params={"roi_weights": {"forehead": 0.5}}),  # 缺 ROI
    )

    out = resolve_effective_rppg_tuning(tuning, None, lambda: version)
    assert out is tuning


# ── 整合：_roi_weights_from_pose 在 override 下的行為 ───────────────────────

def test_roi_weights_from_pose_bit_identical_without_override() -> None:
    lm = _fake_landmarks()
    tuning = load_mediapipe_tuning()
    tuning_via_none_override = apply_roi_weights_override(tuning, None)

    w1 = _roi_weights_from_pose(8.0, 12.0, 4.0, lm, 640, 480, tuning)
    w2 = _roi_weights_from_pose(8.0, 12.0, 4.0, lm, 640, 480, tuning_via_none_override)
    assert w1 == w2


def test_roi_weights_from_pose_reflects_override() -> None:
    lm = _fake_landmarks()
    tuning = load_mediapipe_tuning()
    # 中性姿態角（0,0,0）讓 roll_q/yaw_q/pitch_q 皆為 1.0，只留下 left_bias/right_bias
    # 與 base_weights 比例的影響，方便斷言覆寫後 forehead 佔比明顯提高。
    override = {"forehead": 0.70, "L_cheek": 0.10, "R_cheek": 0.10, "glabella": 0.10}
    tuning_override = apply_roi_weights_override(tuning, override)

    w_default = _roi_weights_from_pose(0.0, 0.0, 0.0, lm, 640, 480, tuning)
    w_override = _roi_weights_from_pose(0.0, 0.0, 0.0, lm, 640, 480, tuning_override)

    assert w_override["forehead"] > w_default["forehead"]


# ── P6b-3a：collect_rppg_roi_sample_with_means 的 weighted_mix 分支 ──────────

import math  # noqa: E402  (集中於本區塊，多 ROI 幾何合成使用)


def _poly(center: tuple[float, float], rx: float, ry: float, k: int) -> list[tuple[float, float]]:
    cx, cy = center
    return [
        (cx + rx * math.cos(2 * math.pi * i / k), cy + ry * math.sin(2 * math.pi * i / k))
        for i in range(k)
    ]


def _multi_roi_landmarks() -> list[SimpleNamespace]:
    """把四個 ROI 的 landmark 群各自散佈到獨立、非退化的區域，讓四個 ROI 都能成功
    取樣（單 ROI 合成點會多數退化，見 test_rppg_worker_roi_buffer.py 說明）。姿態
    landmark 設為中性正面（roll/yaw/pitch≈0）。"""
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    pts[33] = SimpleNamespace(x=0.40, y=0.40)   # left eye
    pts[263] = SimpleNamespace(x=0.60, y=0.40)  # right eye
    pts[1] = SimpleNamespace(x=0.50, y=0.50)    # nose tip
    pts[234] = SimpleNamespace(x=0.32, y=0.50)  # left cheek pose ref
    pts[454] = SimpleNamespace(x=0.68, y=0.50)  # right cheek pose ref
    pts[10] = SimpleNamespace(x=0.50, y=0.22)   # forehead pose ref
    pts[152] = SimpleNamespace(x=0.50, y=0.80)  # chin

    def place(indices: list[int], center: tuple[float, float], rx: float, ry: float) -> None:
        for idx, (x, y) in zip(indices, _poly(center, rx, ry, len(indices))):
            pts[idx] = SimpleNamespace(x=x, y=y)

    place(FOREHEAD_ROI_IDX, (0.50, 0.25), 0.10, 0.05)
    place(LEFT_CHEEK_ROI_IDX, (0.30, 0.62), 0.07, 0.06)
    place(RIGHT_CHEEK_ROI_IDX, (0.70, 0.62), 0.07, 0.06)
    place(GLABELLA_ROI_IDX, (0.50, 0.44), 0.05, 0.04)
    return pts


def _gradient_frame(w: int = 640, h: int = 480) -> np.ndarray:
    """中間色域漸層（避開 obstruction 的過暗/過亮/低彩門檻），讓各 ROI 均值實質不同。"""
    xs = np.linspace(40, 210, w)
    ys = np.linspace(40, 210, h)
    xv, yv = np.meshgrid(xs, ys)
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[..., 0] = ((xv + yv) / 2).astype(np.uint8)  # B
    frame[..., 1] = yv.astype(np.uint8)                # G
    frame[..., 2] = xv.astype(np.uint8)                # R
    return frame


def test_weighted_mix_default_false_bit_identical_to_original() -> None:
    """weighted_mix=False（預設）與既有 collect_rppg_roi_sample() 逐位元相同——確保
    無 override 路徑（含 replay/golden、live worker）輸出完全不變。"""
    frame = _gradient_frame()
    lm = _multi_roi_landmarks()
    tuning = load_mediapipe_tuning()

    s_orig, w_orig, c_orig = collect_rppg_roi_sample(frame, lm, None, RoiGeometryTracker(), tuning)
    s_def, w_def, c_def, _ = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning
    )
    s_false, w_false, c_false, _ = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=False
    )

    assert s_def == s_orig == s_false
    assert w_def == w_orig == w_false
    assert c_def == c_orig == c_false


def test_weighted_mix_matches_manual_weighted_average() -> None:
    """weighted_mix=True：混合樣本 == 手算加權平均（用回傳的正規化有效權重 + per_roi_means）。
    正規化前/後權重等價，故用回傳的正規化權重手算即可驗證。同時證明加權 != 等權。"""
    frame = _gradient_frame()
    lm = _multi_roi_landmarks()
    tuning = load_mediapipe_tuning()

    s_eq, w_eq, c_eq, pm_eq = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=False
    )
    s_wt, w_wt, c_wt, pm_wt = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=True
    )

    # 需要 >=2 個 ROI 存活才能有意義地驗證「加權 != 等權」。
    contrib = [(name, pm_wt[name], w_wt[name]) for name, _ in ROI_SPECS
               if w_wt.get(name, 0.0) > 0.0 and name in pm_wt]
    assert len(contrib) >= 2

    w_total = sum(w for _, _, w in contrib)
    manual = tuple(sum(w * mean[ch] for _, mean, w in contrib) / w_total for ch in range(3))

    assert np.allclose(s_wt, manual, atol=1e-9)
    # 加權與等權在多 ROI、權重不均下必然不同（確定性差異，非浮點巧合）。
    assert not np.allclose(s_wt, s_eq, atol=1e-6)
    # per_roi_means 與存活計數不受 weighted_mix 影響（只有 sample 變）。
    assert c_wt == c_eq and pm_wt == pm_eq


def test_weighted_mix_reflects_forehead_heavy_override() -> None:
    """真實使用情境：forehead-heavy override → 加權混合樣本明顯偏向 forehead 的均值，
    比等權混合更接近（證明 override 的 base_weights 透過有效權重真正影響混合）。"""
    frame = _gradient_frame()
    lm = _multi_roi_landmarks()
    override = {"forehead": 0.70, "L_cheek": 0.10, "R_cheek": 0.10, "glabella": 0.10}
    tuning = apply_roi_weights_override(load_mediapipe_tuning(), override)

    s_eq, _, _, pm = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=False
    )
    s_wt, _, _, _ = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=True
    )

    assert "forehead" in pm
    # 以 G 通道為代表：加權樣本應比等權樣本更接近 forehead 均值。
    d_equal = abs(s_eq[1] - pm["forehead"][1])
    d_weighted = abs(s_wt[1] - pm["forehead"][1])
    assert d_weighted < d_equal


def test_weighted_mix_single_roi_degenerate_equals_equal_weight() -> None:
    """退化情形：只有一個 ROI 存活（其餘被門檻濾掉）時，加權平均 == 等權平均
    （單一貢獻者）== 該 ROI 均值，不丟例外。"""
    frame = _gradient_frame()
    lm = _fake_landmarks()  # 合成單點：多數 ROI 退化，實務上僅 forehead 存活
    tuning = load_mediapipe_tuning()

    s_eq, w_eq, c_eq, pm = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=False
    )
    s_wt, w_wt, c_wt, _ = collect_rppg_roi_sample_with_means(
        frame, lm, None, RoiGeometryTracker(), tuning, weighted_mix=True
    )

    assert c_eq == 1
    assert s_wt == s_eq  # 單一貢獻者：加權與等權恆等
    survivor = next(name for name, _ in ROI_SPECS if w_eq.get(name, 0.0) > 0.0)
    assert np.allclose(s_wt, pm[survivor], atol=1e-9)
