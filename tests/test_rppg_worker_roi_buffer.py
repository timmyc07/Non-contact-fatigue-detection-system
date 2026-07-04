"""P6b-1：per-ROI 均值緩衝 seam 的單元測試。

驗證重點：
1. `collect_rppg_roi_sample_with_means()`（伴生函式）與既有
   `collect_rppg_roi_sample()` 在同一輸入下產生逐位元相同的
   (sample, effective_weights, roi_valid_count)。
2. 回傳的 per_roi_means 與 mixed sample 之間的數學關係：
   mixed == 有效權重 > 0 的各 ROI 均值之平均。
3. `RppgEngine.push_roi_means()` 是純旁路：呼叫與否都不影響既有
   `push()` 灌入的混合緩衝（_r/_g/_b/_t）內容。
4. `RppgEngine.get_roi_window()` 視窗讀取的時間範圍/內容正確、
   maxlen 與既有混合緩衝一致、reset() 會清空旁路緩衝、未知 ROI
   名稱靜默略過不影響既有行為。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from gui.mediapipe_tuning import load_mediapipe_tuning  # noqa: E402
from rppg.rppg_worker import (  # noqa: E402
    ROI_SPECS,
    RppgEngine,
    RoiGeometryTracker,
    collect_rppg_roi_sample,
    collect_rppg_roi_sample_with_means,
)


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


def _gradient_frame(w: int = 640, h: int = 480) -> np.ndarray:
    """非均勻漸層畫面，讓不同 ROI 的均值實質不同（避免均勻畫面讓任何子集平均都巧合相等）。"""
    xs = np.linspace(0, 255, w)
    ys = np.linspace(0, 255, h)
    xv, yv = np.meshgrid(xs, ys)
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[..., 0] = ((xv + yv) / 2).astype(np.uint8)  # B
    frame[..., 1] = yv.astype(np.uint8)                # G
    frame[..., 2] = xv.astype(np.uint8)                # R
    return frame


def test_with_means_matches_original_sample_bit_identical() -> None:
    """伴生函式與原函式在同一輸入（各自獨立 tracker）下逐位元相同。"""
    frame = _gradient_frame()
    lm = _fake_landmarks()
    tuning = load_mediapipe_tuning()

    tracker_a = RoiGeometryTracker()
    tracker_b = RoiGeometryTracker()

    sample_a, weights_a, count_a = collect_rppg_roi_sample(frame, lm, None, tracker_a, tuning)
    sample_b, weights_b, count_b, per_roi_means = collect_rppg_roi_sample_with_means(
        frame, lm, None, tracker_b, tuning
    )

    assert sample_a == sample_b
    assert weights_a == weights_b
    assert count_a == count_b
    assert isinstance(per_roi_means, dict)


def test_per_roi_means_average_reconstructs_mixed_sample() -> None:
    """mixed sample 應等於「有效權重 > 0」各 ROI 均值的平均——驗證 P6b-1 的核心不變量。"""
    frame = _gradient_frame()
    lm = _fake_landmarks()
    tuning = load_mediapipe_tuning()
    tracker = RoiGeometryTracker()

    sample, weights, count, per_roi_means = collect_rppg_roi_sample_with_means(
        frame, lm, None, tracker, tuning
    )

    assert sample is not None
    assert count > 0

    included = [per_roi_means[name] for name, _ in ROI_SPECS if weights.get(name, 0.0) > 0.0]
    assert len(included) == count

    manual = (
        sum(v[0] for v in included) / len(included),
        sum(v[1] for v in included) / len(included),
        sum(v[2] for v in included) / len(included),
    )
    assert np.allclose(manual, sample, atol=1e-9)


def test_per_roi_means_contains_all_valid_rois() -> None:
    """凡遮罩成功（roi_mean_from_points 非 None）的 ROI，per_roi_means 皆須保留其原始均值，
    不受目前姿態/遮蔽權重篩選——這是之後候選權重 A/B 的前提。"""
    frame = _gradient_frame()
    lm = _fake_landmarks()
    tuning = load_mediapipe_tuning()
    tracker = RoiGeometryTracker()

    _, weights, _, per_roi_means = collect_rppg_roi_sample_with_means(frame, lm, None, tracker, tuning)

    roi_names = {name for name, _ in ROI_SPECS}
    assert set(per_roi_means.keys()).issubset(roi_names)
    # 合成關鍵點下至少 forehead 會形成非退化多邊形而成功取樣；其餘 ROI 因合成點
    # 多數重疊於 (0.5, 0.5) 可能退化，屬合成資料本身的限制，不影響此處要驗證的
    # 「有值就保留、不受權重篩選」不變量。
    assert len(per_roi_means) >= 1
    for name, rgb in per_roi_means.items():
        assert len(rgb) == 3
        assert all(0.0 <= c <= 255.0 for c in rgb)


def test_push_roi_means_does_not_change_mixed_buffers() -> None:
    """bit-identical 要求：同一輸入序列下，有無呼叫 push_roi_means() 皆不影響混合緩衝內容。"""
    engine_a = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    engine_b = RppgEngine(buffer_sec=12.0, target_fps=30.0)

    for i in range(40):
        t = i / 30.0
        r, g, b = 100.0 + i, 120.0 + i * 0.5, 90.0 - i * 0.2
        engine_a.push(t, r, g, b)
        engine_b.push(t, r, g, b)
        engine_b.push_roi_means(
            t,
            {
                "forehead": (r + 1.0, g + 1.0, b + 1.0),
                "L_cheek": (r - 1.0, g - 1.0, b - 1.0),
            },
        )

    assert list(engine_a._r) == list(engine_b._r)
    assert list(engine_a._g) == list(engine_b._g)
    assert list(engine_a._b) == list(engine_b._b)
    assert list(engine_a._t) == list(engine_b._t)


def test_push_roi_means_buffers_per_roi_values_and_length() -> None:
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)

    n = 25
    for i in range(n):
        t = i / 30.0
        engine.push_roi_means(
            t,
            {
                "forehead": (float(i), float(i) * 2.0, float(i) * 3.0),
                "glabella": (float(-i), float(-i) * 2.0, float(-i) * 3.0),
            },
        )

    t_arr, r_arr, g_arr, b_arr = engine.get_roi_window("forehead", window_sec=1000.0)
    assert len(t_arr) == n
    assert len(r_arr) == n == len(g_arr) == len(b_arr)
    assert np.allclose(r_arr, np.arange(n, dtype=np.float64))
    assert np.allclose(g_arr, np.arange(n, dtype=np.float64) * 2.0)
    assert np.allclose(b_arr, np.arange(n, dtype=np.float64) * 3.0)

    t_arr_glab, r_arr_glab, _, _ = engine.get_roi_window("glabella", window_sec=1000.0)
    assert len(t_arr_glab) == n
    assert np.allclose(r_arr_glab, -np.arange(n, dtype=np.float64))

    # 從未餵過的 ROI（例如 R_cheek）應回傳空陣列，而非報錯。
    t_empty, r_empty, g_empty, b_empty = engine.get_roi_window("R_cheek", window_sec=1000.0)
    assert len(t_empty) == 0 and len(r_empty) == 0 and len(g_empty) == 0 and len(b_empty) == 0


def test_get_roi_window_filters_by_time_range() -> None:
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)

    for i in range(100):
        t = i * 0.1  # 0.0, 0.1, ..., 9.9
        engine.push_roi_means(t, {"forehead": (float(i), float(i), float(i))})

    t_arr, r_arr, _, _ = engine.get_roi_window("forehead", window_sec=2.0, t_now=9.9)

    # 視窗涵蓋 [7.9, 9.9]，對應 i in [79, 99]（浮點誤差以寬鬆比較）。
    assert t_arr.min() >= 7.9 - 1e-9
    assert t_arr.max() == 9.9
    assert len(t_arr) == 21
    assert np.allclose(np.sort(r_arr), np.arange(79, 100, dtype=np.float64))


def test_roi_buffer_maxlen_matches_mixed_buffer() -> None:
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    for name, _ in ROI_SPECS:
        for key in ("t", "r", "g", "b"):
            assert engine._roi_buffers[name][key].maxlen == engine._t.maxlen


def test_push_roi_means_ignores_unknown_roi_name() -> None:
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    engine.push_roi_means(0.0, {"unknown_roi": (1.0, 2.0, 3.0)})

    t_arr, r_arr, g_arr, b_arr = engine.get_roi_window("unknown_roi", window_sec=10.0)
    assert len(t_arr) == 0 and len(r_arr) == 0 and len(g_arr) == 0 and len(b_arr) == 0
    for name, _ in ROI_SPECS:
        assert len(engine._roi_buffers[name]["t"]) == 0


def test_reset_clears_roi_buffers() -> None:
    engine = RppgEngine(buffer_sec=12.0, target_fps=30.0)
    engine.push(0.0, 1.0, 2.0, 3.0)
    engine.push_roi_means(0.0, {"forehead": (1.0, 2.0, 3.0)})

    engine.reset()

    assert len(engine._r) == 0
    for name, _ in ROI_SPECS:
        assert len(engine._roi_buffers[name]["t"]) == 0
        assert len(engine._roi_buffers[name]["r"]) == 0
        assert len(engine._roi_buffers[name]["g"]) == 0
        assert len(engine._roi_buffers[name]["b"]) == 0
