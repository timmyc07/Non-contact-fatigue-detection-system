"""UTA-RLDD golden-output 回歸基準工具。

把「這次改動有沒有動到數值行為？」變成機械檢查：
- create：對固定影片子集跑 replay，把關鍵數值欄位存成 baseline JSON（入版控）。
- check ：重跑同一子集，逐欄與 baseline 比對（容差在 config 定義），漂移即非零退出。

用法（重量級改動後必跑 check）：
    .venv\\Scripts\\python -m scripts.utarldd_golden check "<UTA-RLDD 資料夾>"
    .venv\\Scripts\\python -m scripts.utarldd_golden create "<UTA-RLDD 資料夾>" --force

退出碼：0=通過、1=數值漂移、2=執行失敗（影片缺失、replay 錯誤、baseline/config 問題）。
比對邏輯為純運算（不 import GUI），測試見 tests/test_utarldd_golden.py。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "tests" / "golden" / "utarldd_golden_config.json"
DEFAULT_BASELINE_PATH = _REPO_ROOT / "tests" / "golden" / "utarldd_golden_baseline.json"


@dataclass
class GoldenDiff:
    """單一比對差異。kind: drift / missing_video / unexpected_video / missing_field / bad_status"""

    kind: str
    video_key: str
    field: str = ""
    baseline: object = None
    current: object = None
    abs_tol: float = 0.0


def load_golden_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    subset = config.get("subset")
    fields = config.get("fields")
    if not isinstance(subset, dict) or not isinstance(fields, dict) or not fields:
        raise ValueError(f"golden config 缺少 subset/fields 區塊: {path}")
    for name, spec in fields.items():
        if "abs_tol" not in spec:
            raise ValueError(f"golden config 欄位 {name} 缺少 abs_tol")
    return config


def extract_golden_fields(summary: dict, field_names) -> dict:
    """從單片 summary（ReplayVideoSummary 的 asdict）取出要入 baseline 的欄位。"""
    missing = [name for name in field_names if name not in summary]
    if missing:
        raise KeyError(f"summary 缺少欄位: {missing}")
    return {name: summary[name] for name in field_names}


def summaries_to_videos(summaries: list, field_names) -> tuple[dict, list[GoldenDiff]]:
    """把 summary dict 清單整理成 {"subject/label": {field: value}}；status != done 記為 bad_status。"""
    videos: dict = {}
    diffs: list[GoldenDiff] = []
    for summary in summaries:
        key = f"{summary['subject']}/{summary['label']}"
        if summary.get("status") != "done":
            diffs.append(
                GoldenDiff(
                    kind="bad_status",
                    video_key=key,
                    field="status",
                    current=f"{summary.get('status')}: {summary.get('error', '')}",
                )
            )
            continue
        videos[key] = extract_golden_fields(summary, field_names)
    return videos, diffs


def compare_videos(baseline_videos: dict, current_videos: dict, field_specs: dict) -> list[GoldenDiff]:
    """逐片逐欄比對。回傳空清單即通過。"""
    diffs: list[GoldenDiff] = []
    for key in sorted(baseline_videos):
        if key not in current_videos:
            diffs.append(GoldenDiff(kind="missing_video", video_key=key))
            continue
        baseline_row = baseline_videos[key]
        current_row = current_videos[key]
        for field, spec in field_specs.items():
            if field not in baseline_row or field not in current_row:
                diffs.append(GoldenDiff(kind="missing_field", video_key=key, field=field))
                continue
            abs_tol = float(spec["abs_tol"])
            base_val = baseline_row[field]
            cur_val = current_row[field]
            if abs(float(cur_val) - float(base_val)) > abs_tol:
                diffs.append(
                    GoldenDiff(
                        kind="drift",
                        video_key=key,
                        field=field,
                        baseline=base_val,
                        current=cur_val,
                        abs_tol=abs_tol,
                    )
                )
    for key in sorted(current_videos):
        if key not in baseline_videos:
            diffs.append(GoldenDiff(kind="unexpected_video", video_key=key))
    return diffs


def format_report(diffs: list[GoldenDiff]) -> str:
    if not diffs:
        return "GOLDEN CHECK: PASS（所有欄位在容差內）"
    lines = [f"GOLDEN CHECK: FAIL（{len(diffs)} 項差異）"]
    for d in diffs:
        if d.kind == "drift":
            delta = float(d.current) - float(d.baseline)
            lines.append(
                f"  [drift] {d.video_key} {d.field}: baseline={d.baseline} current={d.current} "
                f"delta={delta:+.6g} tol={d.abs_tol}"
            )
        elif d.kind == "missing_video":
            lines.append(f"  [missing_video] {d.video_key}: baseline 有此片但本次未跑出結果")
        elif d.kind == "unexpected_video":
            lines.append(f"  [unexpected_video] {d.video_key}: 本次多出 baseline 沒有的片（config 與 baseline 不同步？）")
        elif d.kind == "missing_field":
            lines.append(f"  [missing_field] {d.video_key} {d.field}: 欄位不存在（schema 變了要重建 baseline）")
        elif d.kind == "bad_status":
            lines.append(f"  [bad_status] {d.video_key}: {d.current}")
        else:
            lines.append(f"  [{d.kind}] {d.video_key} {d.field}")
    lines.append("若漂移是本次改動的**預期**結果：在數值行為影響聲明中逐欄說明後，用 create --force 重建 baseline。")
    return "\n".join(lines)


def _run_subset(dataset_root: Path, config: dict, output_dir: Path | None):
    """實際執行 replay（重依賴 GUI/MediaPipe，延遲 import 以保持比對邏輯可獨立測試）。"""
    from gui.video_replay import run_replay_batch

    subset = config["subset"]
    if output_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = _REPO_ROOT / "recordings" / "utarldd_runs" / f"golden_{stamp}"
    logger.info("golden replay 開始: root=%s subset=%s output=%s", dataset_root, subset, output_dir)
    result = run_replay_batch(
        dataset_root,
        output_dir=output_dir,
        max_frames=int(subset.get("max_frames", 0)),
        subjects=list(subset.get("subjects", [])) or None,
        labels=list(subset.get("labels", [])) or None,
        jobs=int(subset.get("jobs", 1)),
        write_annotated_video=False,
    )
    return [asdict(s) for s in result.summaries]


def _cmd_create(args, config: dict) -> int:
    baseline_path = Path(args.baseline)
    if baseline_path.exists() and not args.force:
        logger.error("baseline 已存在，重建請加 --force: %s", baseline_path)
        return 2
    summaries = _run_subset(Path(args.dataset_root), config, args.output_dir)
    videos, bad = summaries_to_videos(summaries, list(config["fields"].keys()))
    if bad or not videos:
        print(format_report(bad or [GoldenDiff(kind="bad_status", video_key="(none)", current="無任何影片完成")]))
        return 2
    baseline = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "subset": config["subset"],
        "videos": videos,
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"baseline 已建立：{baseline_path}（{len(videos)} 片）")
    return 0


def _cmd_check(args, config: dict) -> int:
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        logger.error("找不到 baseline，請先執行 create: %s", baseline_path)
        return 2
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    if baseline.get("subset") != config["subset"]:
        logger.error("baseline 的 subset 與 config 不一致，請重建 baseline。baseline=%s config=%s",
                     baseline.get("subset"), config["subset"])
        return 2
    summaries = _run_subset(Path(args.dataset_root), config, args.output_dir)
    current_videos, bad = summaries_to_videos(summaries, list(config["fields"].keys()))
    diffs = bad + compare_videos(baseline.get("videos", {}), current_videos, config["fields"])
    print(format_report(diffs))
    if any(d.kind == "bad_status" for d in diffs):
        return 2
    return 1 if diffs else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="UTA-RLDD golden-output 回歸基準（create/check）")
    parser.add_argument("command", choices=["create", "check"])
    parser.add_argument("dataset_root", type=Path, help="UTA-RLDD 資料夾（例：.../Fold1_part1）")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--output-dir", default=None, type=Path, help="replay 輸出目錄（預設 recordings/utarldd_runs/golden_<時間戳>）")
    parser.add_argument("--force", action="store_true", help="create 時允許覆蓋既有 baseline")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_golden_config(Path(args.config))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("golden config 載入失敗: %s", exc)
        return 2
    try:
        if args.command == "create":
            return _cmd_create(args, config)
        return _cmd_check(args, config)
    except Exception as exc:  # replay / IO / schema 等非預期錯誤一律收斂為執行失敗碼 2，避免與「1=漂移」混淆
        logger.exception("golden %s 執行失敗: %s", args.command, exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
