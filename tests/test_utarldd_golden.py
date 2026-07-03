"""scripts/utarldd_golden.py 純比對邏輯測試（不觸碰 GUI / 相機 / MediaPipe）。"""

import json

import pytest

from scripts.utarldd_golden import (
    DEFAULT_CONFIG_PATH,
    GoldenDiff,
    compare_videos,
    extract_golden_fields,
    format_report,
    load_golden_config,
    summaries_to_videos,
)


FIELD_SPECS = {
    "frames": {"abs_tol": 0},
    "avg_fatigue_score": {"abs_tol": 0.01},
    "avg_bpm": {"abs_tol": 2.0},
}


def _row(frames=600, score=0.02, bpm=70.0):
    return {"frames": frames, "avg_fatigue_score": score, "avg_bpm": bpm}


def test_compare_identical_passes():
    baseline = {"04/0": _row()}
    assert compare_videos(baseline, {"04/0": _row()}, FIELD_SPECS) == []


def test_compare_within_tolerance_passes():
    baseline = {"04/0": _row(score=0.020, bpm=70.0)}
    current = {"04/0": _row(score=0.028, bpm=71.9)}
    assert compare_videos(baseline, current, FIELD_SPECS) == []


def test_compare_delta_exactly_at_tolerance_passes():
    # 比對用嚴格大於：差距「等於」容差視為通過
    baseline = {"04/0": _row(bpm=70.0)}
    current = {"04/0": _row(bpm=72.0)}  # delta == abs_tol == 2.0
    assert compare_videos(baseline, current, FIELD_SPECS) == []


def test_compare_drift_exceeds_tolerance():
    baseline = {"04/0": _row(bpm=70.0)}
    current = {"04/0": _row(bpm=72.5)}
    diffs = compare_videos(baseline, current, FIELD_SPECS)
    assert len(diffs) == 1
    d = diffs[0]
    assert (d.kind, d.video_key, d.field) == ("drift", "04/0", "avg_bpm")
    assert d.baseline == 70.0 and d.current == 72.5


def test_compare_exact_tolerance_zero_int():
    baseline = {"04/0": _row(frames=600)}
    current = {"04/0": _row(frames=599)}
    diffs = compare_videos(baseline, current, FIELD_SPECS)
    assert [d.field for d in diffs] == ["frames"]


def test_compare_missing_and_unexpected_video():
    baseline = {"04/0": _row(), "04/5": _row()}
    current = {"04/5": _row(), "04/10": _row()}
    kinds = {(d.kind, d.video_key) for d in compare_videos(baseline, current, FIELD_SPECS)}
    assert ("missing_video", "04/0") in kinds
    assert ("unexpected_video", "04/10") in kinds


def test_compare_missing_field():
    baseline = {"04/0": _row()}
    current = {"04/0": {"frames": 600, "avg_bpm": 70.0}}  # 少 avg_fatigue_score
    diffs = compare_videos(baseline, current, FIELD_SPECS)
    assert [(d.kind, d.field) for d in diffs] == [("missing_field", "avg_fatigue_score")]


def test_extract_golden_fields_missing_raises():
    with pytest.raises(KeyError):
        extract_golden_fields({"frames": 600}, ["frames", "avg_bpm"])


def test_summaries_to_videos_marks_bad_status():
    summaries = [
        {"subject": "04", "label": "0", "status": "done", **_row()},
        {"subject": "04", "label": "10", "status": "failed", "error": "boom", **_row()},
    ]
    videos, bad = summaries_to_videos(summaries, list(FIELD_SPECS.keys()))
    assert set(videos) == {"04/0"}
    assert len(bad) == 1 and bad[0].kind == "bad_status" and "boom" in str(bad[0].current)


def test_format_report_pass_and_fail():
    assert "PASS" in format_report([])
    report = format_report(
        [GoldenDiff(kind="drift", video_key="04/0", field="avg_bpm", baseline=70.0, current=75.0, abs_tol=2.0)]
    )
    assert "FAIL" in report and "avg_bpm" in report and "+5" in report


def test_repo_golden_config_is_valid():
    config = load_golden_config(DEFAULT_CONFIG_PATH)
    assert config["subset"]["jobs"] == 1
    assert "avg_fatigue_score" in config["fields"]


def test_load_golden_config_rejects_missing_fields(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"subset": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_golden_config(bad)


def _write_config_and_baseline(tmp_path):
    subset = {"subjects": ["04"], "labels": ["0"], "max_frames": 10, "jobs": 1}
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps({"subset": subset, "fields": {"frames": {"abs_tol": 0}}}), encoding="utf-8"
    )
    baseline_path = tmp_path / "base.json"
    baseline_path.write_text(
        json.dumps({"subset": subset, "videos": {"04/0": {"frames": 10}}}), encoding="utf-8"
    )
    return config_path, baseline_path


def test_main_check_returns_2_when_replay_raises(tmp_path, monkeypatch):
    # replay 執行期例外（如資料夾不存在）必須收斂為退出碼 2，不得與「1=漂移」混淆
    import scripts.utarldd_golden as golden

    config_path, baseline_path = _write_config_and_baseline(tmp_path)

    def _boom(*args, **kwargs):
        raise FileNotFoundError("dataset missing")

    monkeypatch.setattr(golden, "_run_subset", _boom)
    rc = golden.main(
        ["check", str(tmp_path), "--config", str(config_path), "--baseline", str(baseline_path)]
    )
    assert rc == 2


def test_main_create_returns_2_when_replay_raises(tmp_path, monkeypatch):
    import scripts.utarldd_golden as golden

    config_path, baseline_path = _write_config_and_baseline(tmp_path)
    baseline_path.unlink()  # create 不覆蓋既有 baseline

    monkeypatch.setattr(
        golden, "_run_subset", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("replay failed"))
    )
    rc = golden.main(
        ["create", str(tmp_path), "--config", str(config_path), "--baseline", str(baseline_path)]
    )
    assert rc == 2
