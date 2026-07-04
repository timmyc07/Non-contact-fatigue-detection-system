"""P6b-4：scripts/rppg_param_replay.py 的單元測試。

驗證重點：
1. ``compare_roi_weights``（純運算）：合成已知頻率訊號 + 已知心跳帶 BPM，驗證
   MAE 計算正確（候選較優 / 資料不足兩種情境）；``window_sec``/``step_sec``
   非正數與空 records 一律丟 ``ValueError``。
2. ``format_report``：輸出格式包含關鍵欄位；「資料不足」分支不假裝有 MAE。
3. ``_parse_weights_arg``：合法/非法 JSON 皆有正確行為。
4. ``main()`` CLI：缺檔、空檔、belt 全 None、候選權重非法 JSON、視窗全不足，
   皆回傳可行動錯誤與退出碼 1；正常情境退出碼 0 且 ``--out`` 落檔內容正確。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rppg.belt_truth_capture import BeltTruthCaptureRecord, BeltTruthCaptureWriter  # noqa: E402
from scripts import rppg_param_replay as replay  # noqa: E402


def _pulse_channels(t: np.ndarray, f0: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """與 tests/test_rppg_param_coordinator_wiring.py 相同的合成 rPPG 訊號：
    三通道不同振幅/相位讓 POS 算法能重建出乾淨的脈搏波。"""
    r = 0.5 * np.sin(2 * np.pi * f0 * t)
    g = 2.0 * np.sin(2 * np.pi * f0 * t + 0.4)
    b = 0.2 * np.sin(2 * np.pi * f0 * t + 0.8)
    return r, g, b


def _synthetic_records(
    *, fs: float = 30.0, duration_sec: float = 20.0,
    f_forehead: float = 1.2, f_cheek: float = 1.7,
    belt_bpm: float | None = 72.0,
) -> list[BeltTruthCaptureRecord]:
    n = int(fs * duration_sec)
    t = np.arange(n) / fs
    rf, gf, bf = _pulse_channels(t, f_forehead)
    rc, gc, bc = _pulse_channels(t, f_cheek)
    records = []
    for i in range(n):
        records.append(
            BeltTruthCaptureRecord(
                t=float(t[i]),
                roi_means={
                    "forehead": (float(rf[i]), float(gf[i]), float(bf[i])),
                    "L_cheek": (float(rc[i]), float(gc[i]), float(bc[i])),
                },
                belt_bpm=belt_bpm,
            )
        )
    return records


# ── compare_roi_weights（純運算）─────────────────────────────────────────────

def test_compare_roi_weights_candidate_better_when_it_matches_belt_truth():
    """forehead 訊號頻率(72 bpm)與 belt_bpm 一致，L_cheek 訊號頻率(102 bpm)不一致。
    current_weights 重壓 L_cheek（壞 ROI）、candidate_weights 重壓 forehead（好 ROI）。
    候選應在心跳帶真值上明顯較優。"""
    records = _synthetic_records(f_forehead=1.2, f_cheek=1.7, belt_bpm=72.0)
    current_weights = {"forehead": 0.1, "L_cheek": 0.9}
    candidate_weights = {"forehead": 0.9, "L_cheek": 0.1}

    result = replay.compare_roi_weights(records, current_weights, candidate_weights)

    assert result.windows_evaluated >= 3
    assert result.current_mae is not None and result.candidate_mae is not None
    assert result.candidate_mae < result.current_mae
    assert result.candidate_mae < 5.0
    assert result.current_mae > 15.0
    assert result.verdict == "candidate_better"


def test_compare_roi_weights_insufficient_data_when_no_belt_truth():
    records = _synthetic_records(belt_bpm=None)
    result = replay.compare_roi_weights(
        records, {"forehead": 1.0}, {"forehead": 1.0},
    )
    assert result.windows_evaluated == 0
    assert result.current_mae is None
    assert result.candidate_mae is None
    assert result.verdict == "insufficient_data"


def test_compare_roi_weights_insufficient_data_when_windows_too_strict():
    records = _synthetic_records(belt_bpm=72.0)
    result = replay.compare_roi_weights(
        records, {"forehead": 0.5, "L_cheek": 0.5}, {"forehead": 0.9, "L_cheek": 0.1},
        min_samples=1_000_000,  # 遠超任何視窗可能的樣本數
    )
    assert result.windows_evaluated == 0
    assert result.verdict == "insufficient_data"


def test_compare_roi_weights_rejects_nonpositive_window_sec():
    records = _synthetic_records()
    with pytest.raises(ValueError):
        replay.compare_roi_weights(records, {"forehead": 1.0}, {"forehead": 1.0}, window_sec=0.0)


def test_compare_roi_weights_rejects_nonpositive_step_sec():
    records = _synthetic_records()
    with pytest.raises(ValueError):
        replay.compare_roi_weights(records, {"forehead": 1.0}, {"forehead": 1.0}, step_sec=-1.0)


def test_compare_roi_weights_rejects_empty_records():
    with pytest.raises(ValueError):
        replay.compare_roi_weights([], {"forehead": 1.0}, {"forehead": 1.0})


# ── format_report ────────────────────────────────────────────────────────────

def test_format_report_insufficient_data_branch():
    result = replay.ReplayComparisonResult(
        total_windows=2, windows_with_belt_truth=0, windows_evaluated=0,
        current_mae=None, candidate_mae=None, verdict="insufficient_data",
        window_results=[],
    )
    text = replay.format_report(result, {"forehead": 1.0}, {"forehead": 0.5}, Path("cap.jsonl"))
    assert "資料不足" in text
    assert "MAE" not in text  # 不假裝有 MAE 數字


def test_format_report_candidate_better_branch():
    result = replay.ReplayComparisonResult(
        total_windows=5, windows_with_belt_truth=5, windows_evaluated=5,
        current_mae=20.0, candidate_mae=2.0, verdict="candidate_better",
        window_results=[],
    )
    text = replay.format_report(result, {"forehead": 0.1}, {"forehead": 0.9}, Path("cap.jsonl"))
    assert "現行 MAE：20.00 BPM" in text
    assert "候選 MAE：2.00 BPM" in text
    assert "候選權重較優" in text


# ── _parse_weights_arg ───────────────────────────────────────────────────────

def test_parse_weights_arg_valid():
    out = replay._parse_weights_arg('{"forehead": 0.5, "L_cheek": 0.5}', "--x")
    assert out == {"forehead": 0.5, "L_cheek": 0.5}


def test_parse_weights_arg_invalid_json_raises():
    with pytest.raises(ValueError):
        replay._parse_weights_arg("not json", "--x")


def test_parse_weights_arg_empty_object_raises():
    with pytest.raises(ValueError):
        replay._parse_weights_arg("{}", "--x")


def test_parse_weights_arg_non_numeric_value_raises():
    with pytest.raises(ValueError):
        replay._parse_weights_arg('{"forehead": "a lot"}', "--x")


# ── main() CLI ───────────────────────────────────────────────────────────────

def _write_capture(path: Path, records: list[BeltTruthCaptureRecord]) -> None:
    writer = BeltTruthCaptureWriter(path)
    for r in records:
        # BeltTruthCaptureWriter 的 belt_bpm 來自 provider；這裡直接寫檔繞過
        # provider，改用固定 provider 回傳每筆記錄各自的 belt_bpm。
        writer._provider = (lambda bpm=r.belt_bpm: bpm)
        writer.record(r.t, r.roi_means)
    writer.close()


def test_main_missing_capture_file_exits_1(tmp_path, capsys):
    missing = tmp_path / "nope.jsonl"
    rc = replay.main([str(missing), "--candidate-weights", '{"forehead": 1.0}'])
    assert rc == 1
    captured = capsys.readouterr()
    assert "不存在" in captured.err


def test_main_empty_capture_file_exits_1(tmp_path, capsys):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    rc = replay.main([str(path), "--candidate-weights", '{"forehead": 1.0}'])
    assert rc == 1
    captured = capsys.readouterr()
    assert "沒有任何可解析的記錄" in captured.err


def test_main_belt_all_none_exits_1(tmp_path, capsys):
    path = tmp_path / "cap.jsonl"
    _write_capture(path, _synthetic_records(belt_bpm=None, duration_sec=2.0))
    rc = replay.main([str(path), "--candidate-weights", '{"forehead": 1.0}'])
    assert rc == 1
    captured = capsys.readouterr()
    assert "沒有任何有效心跳帶 BPM" in captured.err


def test_main_invalid_candidate_weights_json_exits_1(tmp_path, capsys):
    path = tmp_path / "cap.jsonl"
    _write_capture(path, _synthetic_records(duration_sec=2.0))
    rc = replay.main([str(path), "--candidate-weights", "not json"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "不是合法 JSON" in captured.err


def test_main_windows_too_strict_exits_1(tmp_path, capsys):
    path = tmp_path / "cap.jsonl"
    _write_capture(path, _synthetic_records(belt_bpm=72.0))
    rc = replay.main([
        str(path), "--candidate-weights", '{"forehead": 0.9, "L_cheek": 0.1}',
        "--min-samples", "1000000",
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "所有滑動視窗都無法同時算出" in captured.err


def test_main_success_prints_report_and_writes_json(tmp_path, capsys):
    path = tmp_path / "cap.jsonl"
    _write_capture(path, _synthetic_records(f_forehead=1.2, f_cheek=1.7, belt_bpm=72.0))
    out_path = tmp_path / "report.json"

    rc = replay.main([
        str(path),
        "--current-weights", '{"forehead": 0.1, "L_cheek": 0.9}',
        "--candidate-weights", '{"forehead": 0.9, "L_cheek": 0.1}',
        "--out", str(out_path),
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "結論" in captured.out
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "candidate_better"
    assert payload["current_weights"] == {"forehead": 0.1, "L_cheek": 0.9}
    assert payload["candidate_weights"] == {"forehead": 0.9, "L_cheek": 0.1}
    assert isinstance(payload["windows"], list)
    assert len(payload["windows"]) == payload["windows_with_belt_truth"]
