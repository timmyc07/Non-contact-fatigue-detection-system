"""UTA-RLDD 疲勞判斷準確度量測工具。

與 golden（回歸偵測「數值有沒有變」）不同，本工具量測「數值對不對」：
把 UTA-RLDD 的整段標籤（0=Alert / 5=Low Vigilant / 10=Drowsy）當作序位真值，
量測系統輸出分數能否隨標籤單調上升、以及能否把 Drowsy 與 Alert 分開。

指標（純運算，見 tests/test_utarldd_accuracy.py）：
- 各標籤的分數分佈（n / mean / median / min / max）
- Spearman 序位相關（標籤 vs 分數，理想接近 +1）
- 成對 AUC（label-10 分數 > label-0 分數的機率，0.5=亂猜、1.0=完美分離）
- 尺度塌陷診斷：多少比例的 Drowsy 影片連第一道等級門檻都到不了

用法：
    .venv\\Scripts\\python -m scripts.utarldd_accuracy "<UTA-RLDD 資料夾>" \\
        --subjects 01,02,03,04,05,06 --max-frames 1200 --jobs 4 --out report.json

本工具是「量測/報告」工具，不做 pass/fail gate（AUC 多低都不會非 0 退出）。
退出碼僅：0=完成、2=執行失敗或找不到任何符合的影片。準確度數字須自行判讀，
或搭配 --out 的 JSON 自行做門檻檢查。若要「改動後自動偵測數值漂移」請改用 scripts.utarldd_golden。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]

# 系統的第一道與第二道等級門檻（對齊 gui/fatigue_scorer.py _LEVELS），用於尺度塌陷診斷
LEVEL_MILD_TH = 0.20      # 「輕度疲勞」下界
LEVEL_MODERATE_TH = 0.40  # 「中度疲勞」下界


def _rank(values: np.ndarray) -> np.ndarray:
    """平均排名（處理並列），供 Spearman 使用。"""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(1, len(values) + 1, dtype=np.float64)
    # 並列取平均排名
    _, inv, counts = np.unique(values, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts), dtype=np.float64)
    np.add.at(sums, inv, ranks)
    means = sums / counts
    return means[inv]


def spearman_rho(labels: list[float], scores: list[float]) -> float:
    """標籤與分數的 Spearman 序位相關；樣本不足或零變異回傳 0.0。"""
    if len(labels) < 2:
        return 0.0
    lr = _rank(np.asarray(labels, dtype=np.float64))
    sr = _rank(np.asarray(scores, dtype=np.float64))
    if np.std(lr) < 1e-12 or np.std(sr) < 1e-12:
        return 0.0
    return float(np.corrcoef(lr, sr)[0, 1])


def pairwise_auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    """Mann-Whitney AUC：隨機一個 pos 分數 > 隨機一個 neg 分數的機率（並列算 0.5）。

    pos=較疲勞標籤（如 label 10），neg=較清醒標籤（如 label 0）。無樣本回傳 0.5。
    """
    if not scores_pos or not scores_neg:
        return 0.5
    pos = np.asarray(scores_pos, dtype=np.float64)
    neg = np.asarray(scores_neg, dtype=np.float64)
    wins = 0.0
    for p in pos:
        wins += np.sum(p > neg) + 0.5 * np.sum(p == neg)
    return float(wins / (len(pos) * len(neg)))


def auc_bootstrap_ci(scores_pos: list[float], scores_neg: list[float],
                     n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """AUC 的 bootstrap 信賴區間（對 pos/neg 各自重抽樣）。

    小樣本（每組 n=6）下 AUC 點估計不確定度很大；回傳 (lo, hi) 讓報告不把方向性
    證據講成定論。空集回 (0.5, 0.5)。seed 固定以確保可重現。
    """
    if not scores_pos or not scores_neg:
        return (0.5, 0.5)
    rng = np.random.default_rng(seed)
    pos = np.asarray(scores_pos, dtype=np.float64)
    neg = np.asarray(scores_neg, dtype=np.float64)
    aucs = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        bp = rng.choice(pos, size=pos.size, replace=True)
        bn = rng.choice(neg, size=neg.size, replace=True)
        aucs[i] = pairwise_auc(list(bp), list(bn))
    lo = float(np.percentile(aucs, 100.0 * alpha / 2.0))
    hi = float(np.percentile(aucs, 100.0 * (1.0 - alpha / 2.0)))
    return (lo, hi)


def label_score_stats(pairs: list[tuple[float, float]]) -> dict:
    """pairs=[(label, score)...] → {label: {n, mean, median, min, max}}。"""
    out: dict = {}
    by_label: dict[float, list[float]] = {}
    for label, score in pairs:
        by_label.setdefault(label, []).append(score)
    for label in sorted(by_label):
        arr = np.asarray(by_label[label], dtype=np.float64)
        out[label] = {
            "n": int(arr.size),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }
    return out


def is_monotonic_increasing(stats: dict, key: str = "mean") -> bool:
    """各標籤（升序）的指定統計量是否單調不減。"""
    labels = sorted(stats)
    vals = [stats[l][key] for l in labels]
    return all(b >= a for a, b in zip(vals, vals[1:]))


def collapse_fraction(pairs: list[tuple[float, float]], drowsy_label: float,
                      threshold: float) -> float:
    """Drowsy 影片中，分數連 threshold 都到不到的比例（尺度塌陷指標，越低越好）。"""
    scores = [s for l, s in pairs if l == drowsy_label]
    if not scores:
        return float("nan")
    below = sum(1 for s in scores if s < threshold)
    return below / len(scores)


def compute_accuracy_report(summaries: list[dict], score_fields: list[str]) -> dict:
    """對每個分數欄位計算完整準確度指標。summaries 為 UtaRlddVideoSummary 的 asdict 清單。"""
    done = [s for s in summaries if s.get("status") == "done"]
    report: dict = {
        "n_videos": len(done),
        "n_failed": len(summaries) - len(done),
        "labels_present": sorted({float(s["label"]) for s in done}),
        "fields": {},
    }
    labels_present = report["labels_present"]
    alert_label = min(labels_present) if labels_present else 0.0
    drowsy_label = max(labels_present) if labels_present else 10.0

    for field in score_fields:
        pairs = [(float(s["label"]), float(s.get(field, 0.0))) for s in done]
        stats = label_score_stats(pairs)
        labels = [l for l, _ in pairs]
        scores = [s for _, s in pairs]
        pos = [s for l, s in pairs if l == drowsy_label]
        neg = [s for l, s in pairs if l == alert_label]
        ci_lo, ci_hi = auc_bootstrap_ci(pos, neg)
        report["fields"][field] = {
            "by_label": {str(k): v for k, v in stats.items()},
            "monotonic_mean": is_monotonic_increasing(stats, "mean"),
            "spearman_rho": spearman_rho(labels, scores),
            "auc_drowsy_vs_alert": pairwise_auc(pos, neg),
            "auc_ci95": [ci_lo, ci_hi],
            "collapse_below_mild": collapse_fraction(pairs, drowsy_label, LEVEL_MILD_TH),
            "collapse_below_moderate": collapse_fraction(pairs, drowsy_label, LEVEL_MODERATE_TH),
        }
    return report


def format_report(report: dict) -> str:
    lines = [
        f"UTA-RLDD 準確度報告（{report['n_videos']} 片完成, {report['n_failed']} 失敗）",
        f"標籤: {report['labels_present']}",
        "",
    ]
    for field, m in report["fields"].items():
        lines.append(f"■ {field}")
        for label, st in m["by_label"].items():
            lines.append(
                f"    label {label:>4}: n={st['n']} mean={st['mean']:.4f} "
                f"median={st['median']:.4f} min={st['min']:.4f} max={st['max']:.4f}"
            )
        ci = m.get("auc_ci95", [float("nan"), float("nan")])
        lines.append(
            f"    單調(mean隨標籤上升)={m['monotonic_mean']}  "
            f"Spearman={m['spearman_rho']:+.3f}  "
            f"AUC(Drowsy>Alert)={m['auc_drowsy_vs_alert']:.3f} "
            f"[95%CI {ci[0]:.2f}~{ci[1]:.2f}]"
        )
        cbm = m["collapse_below_mild"]
        cbmod = m["collapse_below_moderate"]
        lines.append(
            f"    尺度塌陷: {cbm*100:.0f}% 的 Drowsy 片到不了『輕度』門檻({LEVEL_MILD_TH})、"
            f"{cbmod*100:.0f}% 到不了『中度』({LEVEL_MODERATE_TH})"
        )
        lines.append("")
    return "\n".join(lines)


# 狀態分佈式的準確度：某標籤影片有多少比例的有效幀落在「非清醒」狀態
def status_active_fraction(summary: dict) -> float:
    """(低警覺+嗜睡+危急+微睡) / (有效判讀幀)；有效幀排除校準中與無臉。"""
    active = (
        summary.get("low_vigilance_frames", 0)
        + summary.get("drowsy_frames", 0)
        + summary.get("critical_frames", 0)
        + summary.get("microsleep_frames", 0)
    )
    valid = (
        summary.get("frames", 0)
        - summary.get("calibrating_frames", 0)
        - summary.get("no_face_frames", 0)
    )
    if valid <= 0:
        return 0.0
    return active / valid


def build_status_active_report(summaries: list[dict], labels_present: list[float]) -> dict:
    """狀態分佈式準確度彙總（純運算，可單測）：各標籤的非清醒有效幀比例 + AUC。"""
    pairs = [(float(s["label"]), status_active_fraction(s))
             for s in summaries if s.get("status") == "done"]
    stats = label_score_stats(pairs)
    drowsy = max(labels_present) if labels_present else 10.0
    alert = min(labels_present) if labels_present else 0.0
    pos = [v for l, v in pairs if l == drowsy]
    neg = [v for l, v in pairs if l == alert]
    return {
        "by_label": {str(k): v for k, v in stats.items()},
        "monotonic_mean": is_monotonic_increasing(stats, "mean"),
        "auc_drowsy_vs_alert": pairwise_auc(pos, neg),
        "auc_ci95": list(auc_bootstrap_ci(pos, neg)),
    }


def _run_batch(dataset_root: Path, subjects, labels, max_frames, jobs, output_dir):
    from gui.utarldd_replay import run_replay_batch

    if output_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = _REPO_ROOT / "recordings" / "utarldd_runs" / f"accuracy_{stamp}"
    logger.info("準確度 replay 開始: subjects=%s labels=%s max_frames=%s jobs=%s",
                subjects, labels, max_frames, jobs)
    result = run_replay_batch(
        dataset_root,
        output_dir=output_dir,
        max_frames=int(max_frames),
        subjects=list(subjects) if subjects else None,
        labels=list(labels) if labels else None,
        jobs=int(jobs),
        write_annotated_video=False,
    )
    return [asdict(s) for s in result.summaries], output_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="UTA-RLDD 疲勞判斷準確度量測")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--subjects", default=None,
                        help="逗號分隔的受試者，如 01,02,03；預設全部")
    parser.add_argument("--labels", default="0,5,10")
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output-dir", default=None, type=Path)
    parser.add_argument("--out", default=None, type=Path, help="準確度報告 JSON 輸出路徑")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # 對前導零穩健：'1' 與 '01' 都補成兩位數，對齊 UTA-RLDD 目錄命名（避免 PowerShell
    # 把 01,02 當整數陣列去零導致對不上目錄）
    def _norm_subject(tok: str) -> str:
        tok = tok.strip()
        return tok.zfill(2) if tok.isdigit() else tok

    subjects = [_norm_subject(s) for s in args.subjects.split(",")] if args.subjects else None
    labels = [s.strip() for s in args.labels.split(",")] if args.labels else None

    score_fields = ["avg_fatigue_score", "p95_fatigue_score", "avg_fused_score",
                    "p95_fused_score", "avg_perclos"]
    try:
        summaries, _ = _run_batch(
            Path(args.dataset_root), subjects, labels, args.max_frames, args.jobs, args.output_dir
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("準確度 replay 失敗: %s", exc)
        return 2

    report = compute_accuracy_report(summaries, score_fields)
    if report["n_videos"] == 0:
        # 比照 scripts.utarldd_golden：找不到影片是誤用（subject/路徑打錯），
        # 不可回成功碼讓自動化誤判為「準確度良好」
        logger.error("找不到任何符合 subjects=%s labels=%s 的影片；請檢查路徑與過濾條件",
                     subjects, labels)
        return 2
    report["status_active_fraction"] = build_status_active_report(summaries, report["labels_present"])

    print(format_report(report))
    print("■ status_active_fraction（非清醒狀態幀比例）")
    for label, st in report["status_active_fraction"]["by_label"].items():
        print(f"    label {label:>4}: mean={st['mean']:.3f} median={st['median']:.3f}")
    print(f"    單調={report['status_active_fraction']['monotonic_mean']}  "
          f"AUC={report['status_active_fraction']['auc_drowsy_vs_alert']:.3f}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n報告已寫入: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
