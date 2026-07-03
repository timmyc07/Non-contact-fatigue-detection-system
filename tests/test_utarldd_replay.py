from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
import json

import numpy as np

from gui.video_replay import (
    UNLABELED_LABEL,
    UNLABELED_LABEL_NAME,
    ReplayVideo,
    ReplayVideoSummary,
    _bgr_to_qimage,
    discover_replay_videos,
    discover_utarldd_videos,
    parse_utarldd_label,
    run_replay_batch,
    write_full_summary_csv,
    write_summary_csv,
    write_validation_report_csv,
    write_visual_report_html,
    write_visual_report_html_from_csv,
)
from scripts.utarldd_replay import _split_csv


def test_parse_utarldd_label() -> None:
    assert parse_utarldd_label(Path("0.mov")) == ("0", "Alert")
    assert parse_utarldd_label(Path("5.MOV")) == ("5", "Low Vigilant")
    assert parse_utarldd_label(Path("10.mp4")) == ("10", "Drowsy")


def test_parse_utarldd_label_rejects_unknown_label() -> None:
    try:
        parse_utarldd_label(Path("1.mov"))
    except ValueError as exc:
        assert "UTA-RLDD" in str(exc)
    else:
        raise AssertionError("unknown UTA-RLDD label should raise ValueError")


def test_discover_utarldd_videos_handles_case_insensitive_extensions(tmp_path: Path) -> None:
    for name in ("0.mov", "5.mov", "10.MOV", "note.txt"):
        p = tmp_path / "01" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"stub")
    p = tmp_path / "02" / "0.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"stub")

    videos = discover_utarldd_videos(tmp_path)

    assert [(v.subject, v.label, v.path.name) for v in videos] == [
        ("01", "0", "0.mov"),
        ("01", "5", "5.mov"),
        ("01", "10", "10.MOV"),
        ("02", "0", "0.mp4"),
    ]


def test_discover_utarldd_videos_filters_subject_and_label(tmp_path: Path) -> None:
    for subject in ("01", "02"):
        for label in ("0", "5", "10"):
            p = tmp_path / subject / f"{label}.mov"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"stub")

    videos = discover_utarldd_videos(tmp_path, subjects=["02"], labels=["10"])

    assert len(videos) == 1
    assert videos[0].subject == "02"
    assert videos[0].label == "10"
    assert videos[0].label_name == "Drowsy"


def test_discover_utarldd_videos_missing_root_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    try:
        discover_utarldd_videos(missing)
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing root should raise FileNotFoundError")


def test_write_summary_csv(tmp_path: Path) -> None:
    out = tmp_path / "summary.csv"
    summary = ReplayVideoSummary(
        subject="01",
        label="0",
        label_name="Alert",
        video_path="C:/video/01/0.mov",
        frames=10,
        face_frames=9,
        face_rate=0.9,
        status="done",
        perclos_low_frames=4,
        behavior_available_frames=8,
        rppg_available_frames=7,
        primary_fatigue_evidence="",
    )

    write_summary_csv(out, [summary])

    text = out.read_text(encoding="utf-8-sig")
    assert "受試者,資料集標籤,警覺類別,快速判讀" in text
    assert "標籤對齊判讀" in text
    assert "主要判斷依據" in text
    assert "建議修正方向" in text
    assert "優化旗標" in text
    assert "01,0,Alert,未見明顯疲勞" in text
    assert "PERCLOS>=0.10" in text


def test_write_full_summary_csv_keeps_machine_readable_fields(tmp_path: Path) -> None:
    out = tmp_path / "summary_full.csv"
    summary = ReplayVideoSummary(
        subject="01",
        label="10",
        label_name="Drowsy",
        video_path="C:/video/01/10.mov",
        frames=10,
        face_frames=9,
        face_rate=0.9,
        status="done",
    )

    write_full_summary_csv(out, [summary])

    text = out.read_text(encoding="utf-8-sig")
    assert "subject,label,label_name" in text
    assert "label_alignment" in text
    assert "optimization_flags_json" in text
    assert "01,10,Drowsy" in text


def test_write_visual_report_html_from_summary_csv(tmp_path: Path) -> None:
    summary_csv = tmp_path / "utarldd_summary_20260611_010203.csv"
    html_out = tmp_path / "report.html"
    summaries = [
        ReplayVideoSummary(
            subject="01",
            label="0",
            label_name="Alert",
            video_path="C:/video/01/0.mov",
            frames=100,
            face_frames=100,
            face_rate=1.0,
            status="done",
            low_vigilance_frames=30,
            perclos_low_frames=30,
            max_perclos=0.12,
            behavior_available_frames=90,
        ),
        ReplayVideoSummary(
            subject="01",
            label="10",
            label_name="Drowsy",
            video_path="C:/video/01/10.mov",
            frames=100,
            face_frames=100,
            face_rate=1.0,
            status="done",
            drowsy_frames=20,
            perclos_drowsy_frames=20,
            max_perclos=0.32,
            p95_fused_score=0.42,
            behavior_available_frames=95,
        ),
    ]
    write_summary_csv(summary_csv, summaries)

    write_visual_report_html_from_csv(summary_csv, html_out)

    text = html_out.read_text(encoding="utf-8")
    assert "UTA-RLDD 疲勞驗證可視化報表" in text
    assert "逐影片判讀與修正建議" in text
    assert "Alert 誤報風險" in text
    assert "PERCLOS" in text


def test_write_validation_report_csv_summarizes_label_and_subject_trends(tmp_path: Path) -> None:
    out = tmp_path / "validation.csv"
    summaries = [
        ReplayVideoSummary(
            subject="01",
            label="0",
            label_name="Alert",
            video_path="C:/video/01/0.mov",
            status="done",
            frames=100,
            face_frames=100,
            face_rate=1.0,
            p95_fused_score=0.05,
            p95_fatigue_score=0.04,
            ok_frames=95,
            low_vigilance_frames=5,
        ),
        ReplayVideoSummary(
            subject="01",
            label="5",
            label_name="Low Vigilant",
            video_path="C:/video/01/5.mov",
            status="done",
            frames=100,
            face_frames=100,
            face_rate=1.0,
            p95_fused_score=0.15,
            p95_fatigue_score=0.10,
            ok_frames=70,
            low_vigilance_frames=30,
        ),
        ReplayVideoSummary(
            subject="01",
            label="10",
            label_name="Drowsy",
            video_path="C:/video/01/10.mov",
            status="done",
            frames=100,
            face_frames=100,
            face_rate=1.0,
            p95_fused_score=0.30,
            p95_fatigue_score=0.20,
            low_vigilance_frames=30,
            drowsy_frames=60,
            critical_frames=5,
        ),
    ]

    write_validation_report_csv(out, summaries)

    text = out.read_text(encoding="utf-8-sig")
    assert "列類型,受試者,資料集標籤" in text
    assert "run_summary" in text
    assert "label_summary" in text
    assert "subject_trend" in text
    assert "完整上升" in text


def test_split_csv_accepts_repeated_and_comma_values() -> None:
    assert _split_csv(["01, 02", "03"]) == ["01", "02", "03"]
    assert _split_csv(["", "  "]) is None
    assert _split_csv(None) is None


def test_bgr_to_qimage_resizes_preview_with_aspect_ratio() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    image = _bgr_to_qimage(frame, max_width=960, max_height=540)

    assert image.width() == 960
    assert image.height() == 540


def test_run_replay_batch_writes_summary_and_manifest(tmp_path: Path, monkeypatch) -> None:
    videos = [
        ReplayVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        ReplayVideo("01", "10", "Drowsy", tmp_path / "01" / "10.MOV"),
    ]

    def fake_discover(root, *, subjects=None, labels=None):
        assert root == tmp_path / "dataset"
        return videos

    def fake_replay(video, output_dir, run_stamp, **kwargs):
        return ReplayVideoSummary(
            subject=video.subject,
            label=video.label,
            label_name=video.label_name,
            video_path=str(video.path),
            db_path=str(output_dir / f"metrics_utarldd_{video.subject}_{video.label}_{run_stamp}.db"),
            status="done" if video.label == "0" else "failed",
            frames=10,
            face_frames=8,
            face_rate=0.8,
        )

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.video_replay.run_replay_video", fake_replay)

    result = run_replay_batch(tmp_path / "dataset", output_dir=tmp_path / "out", max_videos=2)

    assert result.videos_total == 2
    assert result.videos_done == 1
    assert result.videos_failed == 1
    assert result.summary_csv.exists()
    assert result.full_summary_csv.exists()
    assert result.validation_report_csv.exists()
    assert result.visual_report_html.exists()
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_url"] == "https://sites.google.com/view/utarldd/home"
    assert manifest["summary_csv"] == str(result.summary_csv)
    assert manifest["full_summary_csv"] == str(result.full_summary_csv)
    assert manifest["validation_report_csv"] == str(result.validation_report_csv)
    assert manifest["visual_report_html"] == str(result.visual_report_html)
    assert manifest["labels"] == {"0": "Alert", "5": "Low Vigilant", "10": "Drowsy"}
    assert len(manifest["summaries"]) == 2


def test_run_replay_batch_parallel_keeps_video_order(tmp_path: Path, monkeypatch) -> None:
    videos = [
        ReplayVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        ReplayVideo("01", "5", "Low Vigilant", tmp_path / "01" / "5.mov"),
        ReplayVideo("01", "10", "Drowsy", tmp_path / "01" / "10.mov"),
    ]

    def fake_discover(root, *, subjects=None, labels=None):
        return videos

    def fake_process_job(args):
        video, output_dir, run_stamp, _max_frames, _write_annotated_video, _labeled = args
        return ReplayVideoSummary(
            subject=video.subject,
            label=video.label,
            label_name=video.label_name,
            video_path=str(video.path),
            db_path=str(Path(output_dir) / f"metrics_utarldd_{video.subject}_{video.label}_{run_stamp}.db"),
            status="done",
            frames=10,
        )

    class FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers
            self.futures = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, args):
            future = FakeFuture(fn(args))
            self.futures.append(future)
            return future

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.video_replay._run_replay_video_process_job", fake_process_job)
    monkeypatch.setattr("gui.video_replay.ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr("gui.video_replay.wait", lambda futures, timeout, return_when: (set(futures), set()))

    result = run_replay_batch(tmp_path / "dataset", output_dir=tmp_path / "out", jobs=2)

    assert [(s.subject, s.label) for s in result.summaries] == [
        ("01", "0"),
        ("01", "5"),
        ("01", "10"),
    ]
    assert result.videos_total == 3
    assert result.videos_done == 3


def test_run_replay_batch_parallel_handles_broken_process_pool(tmp_path: Path, monkeypatch) -> None:
    videos = [
        ReplayVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        ReplayVideo("01", "5", "Low Vigilant", tmp_path / "01" / "5.mov"),
        ReplayVideo("01", "10", "Drowsy", tmp_path / "01" / "10.mov"),
    ]
    events = []

    def fake_discover(root, *, subjects=None, labels=None):
        return videos

    class BrokenFuture:
        def result(self):
            raise BrokenProcessPool("worker died")

        def cancel(self):
            return True

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, args):
            return BrokenFuture()

    def fake_wait(futures, timeout, return_when):
        first = next(iter(futures))
        remaining = set(futures)
        remaining.remove(first)
        return {first}, remaining

    def progress(event, current, total, summary):
        if event == "video_done" and summary is not None:
            events.append((current, total, summary.subject, summary.label, summary.status, summary.error))

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.video_replay.ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr("gui.video_replay.wait", fake_wait)

    result = run_replay_batch(
        tmp_path / "dataset",
        output_dir=tmp_path / "out",
        jobs=2,
        progress_cb=progress,
    )

    assert result.videos_total == 3
    assert result.videos_done == 0
    assert result.videos_failed == 3
    assert all(summary.status == "failed" for summary in result.summaries)
    assert all("平行處理子行程異常中止" in summary.error for summary in result.summaries)
    assert result.summary_csv.exists()
    assert result.full_summary_csv.exists()
    assert result.validation_report_csv.exists()
    assert result.manifest_path.exists()
    assert events


def test_run_replay_batch_parallel_disables_annotated_video(tmp_path: Path, monkeypatch) -> None:
    videos = [
        ReplayVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        ReplayVideo("01", "5", "Low Vigilant", tmp_path / "01" / "5.mov"),
    ]
    annotated_flags = []

    def fake_discover(root, *, subjects=None, labels=None):
        return videos

    def fake_process_job(args):
        video, output_dir, run_stamp, _max_frames, write_annotated_video, _labeled = args
        annotated_flags.append(write_annotated_video)
        return ReplayVideoSummary(
            subject=video.subject,
            label=video.label,
            label_name=video.label_name,
            video_path=str(video.path),
            db_path=str(Path(output_dir) / f"metrics_utarldd_{video.subject}_{video.label}_{run_stamp}.db"),
            status="done",
            frames=10,
        )

    class FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, args):
            return FakeFuture(fn(args))

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.video_replay._run_replay_video_process_job", fake_process_job)
    monkeypatch.setattr("gui.video_replay.ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr("gui.video_replay.wait", lambda futures, timeout, return_when: (set(futures), set()))

    result = run_replay_batch(
        tmp_path / "dataset",
        output_dir=tmp_path / "out",
        jobs=2,
        write_annotated_video=True,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.videos_done == 2
    assert annotated_flags == [False, False]
    assert manifest["write_annotated_video_requested"] is True
    assert manifest["write_annotated_video_effective"] is False


def test_discover_replay_videos_accepts_single_video_file(tmp_path: Path) -> None:
    video_path = tmp_path / "clips" / "my_drive.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"stub")

    videos = discover_replay_videos(video_path)

    assert len(videos) == 1
    assert videos[0].path == video_path
    assert videos[0].subject == "clips"
    assert videos[0].label == UNLABELED_LABEL
    assert videos[0].label_name == UNLABELED_LABEL_NAME


def test_discover_replay_videos_treats_unrecognized_filenames_as_unlabeled(tmp_path: Path) -> None:
    for name in ("session_a.mp4", "0.mov", "flight_log.avi"):
        p = tmp_path / "pilot01" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"stub")

    videos = discover_replay_videos(tmp_path)

    by_name = {v.path.name: v for v in videos}
    assert len(videos) == 3
    assert by_name["session_a.mp4"].label == UNLABELED_LABEL
    assert by_name["session_a.mp4"].label_name == UNLABELED_LABEL_NAME
    assert by_name["flight_log.avi"].label == UNLABELED_LABEL
    # 已知 UTA-RLDD 檔名仍可正常解析出 label，不被通用探索改壞
    assert by_name["0.mov"].label == "0"
    assert by_name["0.mov"].label_name == "Alert"


def test_run_replay_batch_raises_actionable_error_on_zero_videos(tmp_path: Path, monkeypatch) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    try:
        run_replay_batch(empty_dir, output_dir=tmp_path / "out", labeled=False)
    except ValueError as exc:
        message = str(exc)
        assert "找不到可回放的影片" in message
        assert str(empty_dir) in message
    else:
        raise AssertionError("empty root with no videos should raise ValueError")

    try:
        run_replay_batch(empty_dir, output_dir=tmp_path / "out2", labeled=True)
    except ValueError as exc:
        message = str(exc)
        assert "找不到可回放的影片" in message
        assert "0、5 或 10" in message
    else:
        raise AssertionError("empty root with no videos should raise ValueError (labeled mode)")


def test_run_replay_batch_labeled_true_uses_utarldd_discovery_and_output_dir(
    tmp_path: Path, monkeypatch
) -> None:
    videos = [ReplayVideo("01", "0", "Alert", tmp_path / "01" / "0.mov")]
    calls = {"utarldd": 0, "generic": 0}

    def fake_utarldd_discover(root, *, subjects=None, labels=None):
        calls["utarldd"] += 1
        return videos

    def fake_generic_discover(root, *, subjects=None, labels=None):
        calls["generic"] += 1
        return videos

    def fake_replay(video, output_dir, run_stamp, **kwargs):
        return ReplayVideoSummary(
            subject=video.subject,
            label=video.label,
            label_name=video.label_name,
            video_path=str(video.path),
            status="done",
            frames=5,
        )

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_utarldd_discover)
    monkeypatch.setattr("gui.video_replay.discover_replay_videos", fake_generic_discover)
    monkeypatch.setattr("gui.video_replay.run_replay_video", fake_replay)

    result = run_replay_batch(tmp_path / "dataset")

    assert calls == {"utarldd": 1, "generic": 0}
    assert result.output_dir.parent.name == "utarldd_runs"
    assert result.summary_csv.name.startswith("utarldd_summary_")
    assert result.validation_report_csv.exists()


def test_run_replay_batch_labeled_false_uses_generic_discovery_and_skips_validation(
    tmp_path: Path, monkeypatch
) -> None:
    videos = [ReplayVideo("clips", UNLABELED_LABEL, UNLABELED_LABEL_NAME, tmp_path / "clips" / "a.mp4")]
    calls = {"utarldd": 0, "generic": 0}

    def fake_utarldd_discover(root, *, subjects=None, labels=None):
        calls["utarldd"] += 1
        return videos

    def fake_generic_discover(root, *, subjects=None, labels=None):
        calls["generic"] += 1
        return videos

    def fake_replay(video, output_dir, run_stamp, **kwargs):
        return ReplayVideoSummary(
            subject=video.subject,
            label=video.label,
            label_name=video.label_name,
            video_path=str(video.path),
            status="done",
            frames=5,
        )

    monkeypatch.setattr("gui.video_replay.discover_utarldd_videos", fake_utarldd_discover)
    monkeypatch.setattr("gui.video_replay.discover_replay_videos", fake_generic_discover)
    monkeypatch.setattr("gui.video_replay.run_replay_video", fake_replay)

    result = run_replay_batch(tmp_path / "dataset", labeled=False)

    assert calls == {"utarldd": 0, "generic": 1}
    assert result.output_dir.parent.name == "replay_runs"
    assert result.summary_csv.name.startswith("replay_summary_")
    assert not result.validation_report_csv.exists()
    assert result.summary_csv.exists()
    assert result.full_summary_csv.exists()
    assert result.visual_report_html.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"] == "generic-video"
    assert manifest["validation_report_csv"] == ""


def test_visual_report_generic_mode_has_no_utarldd_wording(tmp_path: Path) -> None:
    labeled_summaries = [
        ReplayVideoSummary(subject="01", label="0", label_name="Alert", video_path="/d/01/0.mov",
                           status="done", frames=100, face_frames=90, face_rate=0.9),
        ReplayVideoSummary(subject="01", label="10", label_name="Drowsy", video_path="/d/01/10.mov",
                           status="done", frames=100, face_frames=80, face_rate=0.8),
    ]
    generic_summaries = [
        ReplayVideoSummary(subject="clips", label=UNLABELED_LABEL, label_name=UNLABELED_LABEL_NAME,
                           video_path="/d/clips/my_drive_home.mp4", status="done",
                           frames=100, face_frames=90, face_rate=0.9),
        ReplayVideoSummary(subject="clips", label=UNLABELED_LABEL, label_name=UNLABELED_LABEL_NAME,
                           video_path="/d/clips/night_run.mp4", status="done",
                           frames=100, face_frames=70, face_rate=0.7),
    ]
    lab_path, gen_path = tmp_path / "lab.html", tmp_path / "gen.html"
    write_visual_report_html(lab_path, labeled_summaries, labeled=True)
    write_visual_report_html(gen_path, generic_summaries, labeled=False)
    lab = lab_path.read_text(encoding="utf-8")
    gen = gen_path.read_text(encoding="utf-8")

    # labeled=True（UTA-RLDD preset）維持既有樣貌
    assert "UTA-RLDD" in lab
    assert "0 Alert" in lab and "10 Drowsy" in lab
    assert "Alert 誤報風險" in lab and "Drowsy 漏報風險" in lab

    # labeled=False（通用模式）完全中性、按影片名分組
    assert "UTA-RLDD" not in gen
    assert "0 Alert" not in gen and "5 Low Vigilant" not in gen and "10 Drowsy" not in gen
    assert "Alert 誤報風險" not in gen and "Drowsy 漏報風險" not in gen
    assert "my_drive_home.mp4" in gen and "night_run.mp4" in gen
    assert "影片回測可視化報表" in gen
