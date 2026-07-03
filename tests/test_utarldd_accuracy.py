"""scripts/utarldd_accuracy.py 純運算指標測試（不觸碰 GUI / 相機 / MediaPipe）。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.utarldd_accuracy import (  # noqa: E402
    auc_bootstrap_ci,
    compute_accuracy_report,
    is_monotonic_increasing,
    label_score_stats,
    pairwise_auc,
    spearman_rho,
    status_active_fraction,
)


def test_auc_ci_perfect_separation_is_tight_and_high():
    lo, hi = auc_bootstrap_ci([0.8, 0.9, 0.95], [0.1, 0.2, 0.15], n_boot=500, seed=1)
    assert lo >= 0.9 and hi == 1.0


def test_auc_ci_overlapping_includes_half():
    # 小樣本、分佈重疊：CI 應涵蓋 0.5（未達顯著）
    lo, hi = auc_bootstrap_ci([0.3, 0.5, 0.6], [0.2, 0.55, 0.45], n_boot=500, seed=1)
    assert lo <= 0.5 <= hi


def test_auc_ci_deterministic_with_seed():
    a = auc_bootstrap_ci([0.8, 0.9], [0.1, 0.2], n_boot=300, seed=7)
    b = auc_bootstrap_ci([0.8, 0.9], [0.1, 0.2], n_boot=300, seed=7)
    assert a == b


def test_auc_ci_empty_returns_half():
    assert auc_bootstrap_ci([], [0.1]) == (0.5, 0.5)


def test_spearman_perfect_positive():
    assert spearman_rho([0, 5, 10], [0.1, 0.2, 0.3]) == 1.0


def test_spearman_perfect_negative():
    assert spearman_rho([0, 5, 10], [0.3, 0.2, 0.1]) == -1.0


def test_spearman_handles_zero_variance():
    assert spearman_rho([0, 5, 10], [0.2, 0.2, 0.2]) == 0.0


def test_spearman_too_few_samples():
    assert spearman_rho([0], [0.1]) == 0.0


def test_pairwise_auc_perfect_separation():
    assert pairwise_auc([0.8, 0.9], [0.1, 0.2]) == 1.0


def test_pairwise_auc_no_separation():
    assert pairwise_auc([0.1, 0.2], [0.8, 0.9]) == 0.0


def test_pairwise_auc_ties_count_half():
    assert pairwise_auc([0.5], [0.5]) == 0.5


def test_pairwise_auc_empty_returns_half():
    assert pairwise_auc([], [0.1]) == 0.5


def test_label_score_stats_groups_by_label():
    stats = label_score_stats([(0.0, 0.1), (0.0, 0.3), (10.0, 0.8)])
    assert stats[0.0]["n"] == 2
    assert stats[0.0]["mean"] == 0.2
    assert stats[10.0]["mean"] == 0.8


def test_is_monotonic_increasing():
    stats = {0.0: {"mean": 0.1}, 5.0: {"mean": 0.2}, 10.0: {"mean": 0.3}}
    assert is_monotonic_increasing(stats) is True
    stats_bad = {0.0: {"mean": 0.1}, 5.0: {"mean": 0.3}, 10.0: {"mean": 0.2}}
    assert is_monotonic_increasing(stats_bad) is False


def _summary(label, fatigue, fused=0.0, **extra):
    base = {
        "status": "done", "label": str(label),
        "avg_fatigue_score": fatigue, "p95_fatigue_score": fatigue,
        "avg_fused_score": fused, "p95_fused_score": fused, "avg_perclos": 0.0,
        "frames": 600, "calibrating_frames": 100, "no_face_frames": 0,
        "low_vigilance_frames": 0, "drowsy_frames": 0,
        "critical_frames": 0, "microsleep_frames": 0,
    }
    base.update(extra)
    return base


def test_compute_accuracy_report_collapse_detection():
    # 模擬「尺度塌陷」：Drowsy 片分數也遠低於 0.20
    summaries = [
        _summary(0, 0.00), _summary(0, 0.00),
        _summary(5, 0.01), _summary(5, 0.02),
        _summary(10, 0.03), _summary(10, 0.05),
    ]
    report = compute_accuracy_report(summaries, ["avg_fatigue_score"])
    m = report["fields"]["avg_fatigue_score"]
    assert m["monotonic_mean"] is True
    assert m["spearman_rho"] > 0.9
    assert m["collapse_below_mild"] == 1.0     # 全部 Drowsy 片到不了 0.20
    assert report["n_videos"] == 6


def test_compute_accuracy_report_good_separation():
    summaries = [
        _summary(0, 0.05), _summary(0, 0.08),
        _summary(10, 0.55), _summary(10, 0.62),
    ]
    report = compute_accuracy_report(summaries, ["avg_fatigue_score"])
    m = report["fields"]["avg_fatigue_score"]
    assert m["auc_drowsy_vs_alert"] == 1.0
    assert m["collapse_below_mild"] == 0.0


def test_compute_accuracy_report_excludes_failed():
    summaries = [_summary(0, 0.0), {"status": "failed", "label": "10"}]
    report = compute_accuracy_report(summaries, ["avg_fatigue_score"])
    assert report["n_videos"] == 1
    assert report["n_failed"] == 1


def test_status_active_fraction():
    s = _summary(10, 0.0, frames=600, calibrating_frames=100,
                 no_face_frames=0, low_vigilance_frames=200, drowsy_frames=50)
    # 有效幀 = 600-100 = 500；非清醒 = 250 → 0.5
    assert status_active_fraction(s) == 0.5


def test_status_active_fraction_zero_valid():
    s = _summary(10, 0.0, frames=100, calibrating_frames=100, no_face_frames=0)
    assert status_active_fraction(s) == 0.0


def test_build_status_active_report_separates_labels():
    from scripts.utarldd_accuracy import build_status_active_report
    summaries = [
        _summary(0, 0.0, low_vigilance_frames=50),    # 有效 500 → 0.10
        _summary(10, 0.0, low_vigilance_frames=300),  # 有效 500 → 0.60
    ]
    rep = build_status_active_report(summaries, [0.0, 10.0])
    assert rep["by_label"]["0.0"]["mean"] == 0.10
    assert rep["by_label"]["10.0"]["mean"] == 0.60
    assert rep["auc_drowsy_vs_alert"] == 1.0
    assert "auc_ci95" in rep
