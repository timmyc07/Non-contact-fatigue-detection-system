"""比較不同 rPPG ROI 權重方案對心跳帶真值的擬合優劣（P6b-4 離線驗證工具）。

背景（見 CLAUDE.md「心跳帶」段 P6b、docs/2026-07-04-p6b-handoff.md 第 101-104 行）：
P6a/P6b 已建立「有護欄自適應」基礎層——``rppg.adaptive_calibration.RppgParamAbEvaluator``
以心跳帶真值對現行 vs 候選 ROI 權重的 rPPG BPM 做 A/B——但 live 自適應迴圈開啟前，
需要能在**沒有心跳帶硬體連線的情況下**離線驗證候選 ROI 權重是否真的更準。本腳本
就是這個離線驗證工具。

輸入：``rppg/belt_truth_capture.py`` 錄製的 belt-truth 同步錄製檔（JSONL，一行一筆
per-ROI RGB 均值 + 心跳帶 BPM，可能為 null）。做法：把整段錄製切成多個滑動視窗，
各視窗內以 ``rppg.adaptive_calibration.recompute_raw_bpm_from_roi_windows``（與線上
A/B 評估同一顆純運算重算函式，確保比較方法一致）分別用「現行權重」與「候選權重」
重算 rPPG 原始 BPM；取視窗內心跳帶 BPM 中位數為真值，對兩者各算絕對殘差；彙總所有
「現行與候選皆可重算」的視窗算 MAE，比較誰更接近心跳帶真值。

用法：
    .venv\\Scripts\\python -m scripts.rppg_param_replay <capture 檔路徑> \\
        --candidate-weights "{\\"forehead\\":0.5,\\"L_cheek\\":0.2,\\"R_cheek\\":0.2,\\"glabella\\":0.1}"

已知限制：``recompute_raw_bpm_from_roi_windows`` 於函式內部惰性匯入
``rppg.rppg_worker``（拉入 PySide6/cv2/mediapipe），本腳本因此只能在裝有這些套件
的環境執行；讀取 capture 檔（``load_belt_truth_capture``）本身不依賴它們。

退出碼：0=完成比較（含「兩者無顯著差異」的合法結果）、1=資料不足或輸入錯誤
（附可行動訊息）、2=未預期例外。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from rppg.adaptive_calibration import recompute_raw_bpm_from_roi_windows
from rppg.belt_truth_capture import BeltTruthCaptureRecord, load_belt_truth_capture

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SEC = 12.0
DEFAULT_STEP_SEC = 3.0
DEFAULT_MIN_SAMPLES = 64
DEFAULT_MIN_DURATION_SEC = 6.0
DEFAULT_IMPROVE_MARGIN_BPM = 0.5

RoiWindowSeries = tuple[list[float], list[float], list[float], list[float]]


@dataclass(frozen=True)
class WindowResult:
    """單一滑動視窗的比較結果。"""

    window_start: float
    window_end: float
    belt_bpm_truth: float
    current_bpm: Optional[float]
    candidate_bpm: Optional[float]
    current_abs_error: Optional[float]
    candidate_abs_error: Optional[float]


@dataclass(frozen=True)
class ReplayComparisonResult:
    """整段錄製的比較彙總。

    ``verdict`` ∈ {"candidate_better", "current_better", "inconclusive",
    "insufficient_data"}——最後一種代表沒有任何視窗能同時算出現行與候選 BPM，
    ``current_mae``/``candidate_mae`` 皆為 ``None``。
    """

    total_windows: int
    windows_with_belt_truth: int
    windows_evaluated: int  # 現行與候選皆可重算 BPM 的視窗數（MAE 分母）
    current_mae: Optional[float]
    candidate_mae: Optional[float]
    verdict: str
    window_results: list[WindowResult]


def _slice_records(
    records: Sequence[BeltTruthCaptureRecord], start: float, end: float
) -> list[BeltTruthCaptureRecord]:
    return [r for r in records if start <= r.t <= end]


def _build_roi_windows(
    records: Sequence[BeltTruthCaptureRecord],
) -> dict[str, RoiWindowSeries]:
    """把一段 records 轉成 :func:`recompute_raw_bpm_from_roi_windows` 需要的
    ``{roi_name: (t, r, g, b)}`` 格式（各序列依 records 原始順序，呼叫端須確保
    records 已依時間排序）。"""
    names: set[str] = set()
    for r in records:
        names.update(r.roi_means.keys())
    windows: dict[str, RoiWindowSeries] = {}
    for name in names:
        t_list: list[float] = []
        r_list: list[float] = []
        g_list: list[float] = []
        b_list: list[float] = []
        for rec in records:
            rgb = rec.roi_means.get(name)
            if rgb is None:
                continue
            t_list.append(rec.t)
            r_list.append(rgb[0])
            g_list.append(rgb[1])
            b_list.append(rgb[2])
        windows[name] = (t_list, r_list, g_list, b_list)
    return windows


def _belt_ground_truth(records: Sequence[BeltTruthCaptureRecord]) -> Optional[float]:
    values = [r.belt_bpm for r in records if r.belt_bpm is not None]
    if not values:
        return None
    return float(statistics.median(values))


def compare_roi_weights(
    records: Sequence[BeltTruthCaptureRecord],
    current_weights: Mapping[str, float],
    candidate_weights: Mapping[str, float],
    *,
    window_sec: float = DEFAULT_WINDOW_SEC,
    step_sec: float = DEFAULT_STEP_SEC,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_duration_sec: float = DEFAULT_MIN_DURATION_SEC,
    improve_margin_bpm: float = DEFAULT_IMPROVE_MARGIN_BPM,
) -> ReplayComparisonResult:
    """對整段錄製做滑動視窗比較。呼叫端須先確保 ``records`` 非空。

    Raises:
        ValueError: ``window_sec``/``step_sec`` 非正數（避免無窮迴圈）。
    """
    if window_sec <= 0 or step_sec <= 0:
        raise ValueError(
            f"window_sec/step_sec 必須為正數，收到 window_sec={window_sec}, step_sec={step_sec}"
        )
    if not records:
        raise ValueError("records 為空，無法比較")

    ordered = sorted(records, key=lambda r: r.t)
    t0 = ordered[0].t
    t_last = ordered[-1].t

    total_windows = 0
    window_results: list[WindowResult] = []

    start = t0
    while start <= t_last:
        end = start + window_sec
        sub = _slice_records(ordered, start, end)
        if sub:
            total_windows += 1
            belt_gt = _belt_ground_truth(sub)
            if belt_gt is not None:
                roi_windows = _build_roi_windows(sub)
                cur_bpm = recompute_raw_bpm_from_roi_windows(
                    roi_windows, current_weights,
                    min_samples=min_samples, min_duration_sec=min_duration_sec,
                )
                cand_bpm = recompute_raw_bpm_from_roi_windows(
                    roi_windows, candidate_weights,
                    min_samples=min_samples, min_duration_sec=min_duration_sec,
                )
                cur_err = abs(cur_bpm - belt_gt) if cur_bpm is not None else None
                cand_err = abs(cand_bpm - belt_gt) if cand_bpm is not None else None
                window_results.append(
                    WindowResult(
                        window_start=start,
                        window_end=end,
                        belt_bpm_truth=belt_gt,
                        current_bpm=cur_bpm,
                        candidate_bpm=cand_bpm,
                        current_abs_error=cur_err,
                        candidate_abs_error=cand_err,
                    )
                )
        start += step_sec

    windows_with_belt_truth = len(window_results)
    paired = [
        (w.current_abs_error, w.candidate_abs_error)
        for w in window_results
        if w.current_abs_error is not None and w.candidate_abs_error is not None
    ]
    windows_evaluated = len(paired)
    if windows_evaluated > 0:
        current_mae: Optional[float] = float(statistics.mean(a for a, _ in paired))
        candidate_mae: Optional[float] = float(statistics.mean(b for _, b in paired))
        if candidate_mae + improve_margin_bpm <= current_mae:
            verdict = "candidate_better"
        elif candidate_mae >= current_mae + improve_margin_bpm:
            verdict = "current_better"
        else:
            verdict = "inconclusive"
    else:
        current_mae = None
        candidate_mae = None
        verdict = "insufficient_data"

    return ReplayComparisonResult(
        total_windows=total_windows,
        windows_with_belt_truth=windows_with_belt_truth,
        windows_evaluated=windows_evaluated,
        current_mae=current_mae,
        candidate_mae=candidate_mae,
        verdict=verdict,
        window_results=window_results,
    )


def format_report(
    result: ReplayComparisonResult,
    current_weights: Mapping[str, float],
    candidate_weights: Mapping[str, float],
    capture_path: Path | str,
) -> str:
    lines = [
        f"belt-truth 離線比較報告：{capture_path}",
        f"現行權重：{dict(current_weights)}",
        f"候選權重：{dict(candidate_weights)}",
        (
            f"滑動視窗：共 {result.total_windows} 個，含心跳帶真值 {result.windows_with_belt_truth} 個，"
            f"雙方皆可重算 BPM {result.windows_evaluated} 個"
        ),
    ]
    if result.verdict == "insufficient_data":
        lines.append("結論：資料不足，無法比較（見上方視窗統計）。")
        return "\n".join(lines)

    assert result.current_mae is not None and result.candidate_mae is not None
    lines.append(f"現行 MAE：{result.current_mae:.2f} BPM")
    lines.append(f"候選 MAE：{result.candidate_mae:.2f} BPM")
    verdict_text = {
        "candidate_better": f"候選權重較優（MAE 低 {result.current_mae - result.candidate_mae:.2f} BPM）",
        "current_better": f"現行權重較優（候選 MAE 高 {result.candidate_mae - result.current_mae:.2f} BPM）",
        "inconclusive": "兩者差異在誤差邊際內，無法判定何者更優",
    }.get(result.verdict, result.verdict)
    lines.append(f"結論：{verdict_text}")
    return "\n".join(lines)


def _default_current_weights() -> dict[str, float]:
    # 惰性匯入：避免未指定 --current-weights 以外的用法（例如 --help）也拉入
    # PySide6/cv2/mediapipe。
    from rppg.rppg_worker import ROI_BASE_WEIGHTS

    return dict(ROI_BASE_WEIGHTS)


def _parse_weights_arg(raw: str, label: str) -> dict[str, float]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} 不是合法 JSON：{exc}") from exc
    if not isinstance(obj, dict) or not obj:
        raise ValueError(f'{label} 須為非空 JSON object，例如 \'{{"forehead":0.4,"L_cheek":0.2,"R_cheek":0.2,"glabella":0.2}}\'')
    out: dict[str, float] = {}
    for k, v in obj.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 的 {k}={v!r} 不是數值") from exc
    return out


def _write_json_report(
    path: Path,
    result: ReplayComparisonResult,
    current_weights: Mapping[str, float],
    candidate_weights: Mapping[str, float],
) -> None:
    payload = {
        "current_weights": dict(current_weights),
        "candidate_weights": dict(candidate_weights),
        "total_windows": result.total_windows,
        "windows_with_belt_truth": result.windows_with_belt_truth,
        "windows_evaluated": result.windows_evaluated,
        "current_mae": result.current_mae,
        "candidate_mae": result.candidate_mae,
        "verdict": result.verdict,
        "windows": [asdict(w) for w in result.window_results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="離線比較 rPPG ROI 權重方案對心跳帶真值的擬合優劣（P6b-4）。"
    )
    parser.add_argument("capture_path", type=Path, help="belt-truth 同步錄製 JSONL 檔路徑")
    parser.add_argument(
        "--candidate-weights", required=True,
        help='候選 ROI 權重 JSON，例如 \'{"forehead":0.5,"L_cheek":0.2,"R_cheek":0.2,"glabella":0.1}\'',
    )
    parser.add_argument(
        "--current-weights", default=None,
        help="現行 ROI 權重 JSON；省略時使用 rppg.rppg_worker.ROI_BASE_WEIGHTS",
    )
    parser.add_argument("--window-sec", type=float, default=DEFAULT_WINDOW_SEC, help="滑動視窗長度（秒）")
    parser.add_argument("--step-sec", type=float, default=DEFAULT_STEP_SEC, help="滑動視窗步進（秒）")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES, help="單視窗最少樣本數")
    parser.add_argument(
        "--min-duration-sec", type=float, default=DEFAULT_MIN_DURATION_SEC, help="單視窗最短時長（秒）"
    )
    parser.add_argument(
        "--improve-margin-bpm", type=float, default=DEFAULT_IMPROVE_MARGIN_BPM,
        help="判定「明確更優/更差」所需的 MAE 差距門檻（BPM）",
    )
    parser.add_argument("--out", type=Path, default=None, help="選填：把完整比較結果寫成 JSON")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)

    try:
        candidate_weights = _parse_weights_arg(args.candidate_weights, "--candidate-weights")
        current_weights = (
            _parse_weights_arg(args.current_weights, "--current-weights")
            if args.current_weights is not None
            else _default_current_weights()
        )
    except ValueError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    try:
        records = load_belt_truth_capture(args.capture_path)
    except FileNotFoundError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    if not records:
        print(
            f"錯誤：capture 檔 {args.capture_path} 沒有任何可解析的記錄，無法比較。"
            "請確認錄製時有實際跑過一段（心跳帶已連線、rPPG 已偵測到臉部）。",
            file=sys.stderr,
        )
        return 1

    if all(r.belt_bpm is None for r in records):
        print(
            f"錯誤：capture 檔 {args.capture_path} 沒有任何有效心跳帶 BPM（全為 null），"
            "無法算殘差。請確認錄製當下心跳帶已連線並收到心率樣本。",
            file=sys.stderr,
        )
        return 1

    try:
        result = compare_roi_weights(
            records, current_weights, candidate_weights,
            window_sec=args.window_sec, step_sec=args.step_sec,
            min_samples=args.min_samples, min_duration_sec=args.min_duration_sec,
            improve_margin_bpm=args.improve_margin_bpm,
        )
    except ValueError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    except Exception:
        logger.exception("比較過程發生未預期例外")
        print("錯誤：比較過程發生未預期例外，詳見上方 log。", file=sys.stderr)
        return 2

    if result.windows_evaluated == 0:
        print(
            "錯誤：所有滑動視窗都無法同時算出現行與候選 BPM（樣本不足、時長不足、或"
            "心跳帶真值缺失）。可嘗試縮小 --window-sec、放寬 --min-samples/"
            "--min-duration-sec，或確認錄製時長是否足夠（建議至少數分鐘）。",
            file=sys.stderr,
        )
        return 1

    report = format_report(result, current_weights, candidate_weights, args.capture_path)
    print(report)

    if args.out is not None:
        _write_json_report(args.out, result, current_weights, candidate_weights)
        print(f"完整比較結果已寫入：{args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
