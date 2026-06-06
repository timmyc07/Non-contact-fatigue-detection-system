from __future__ import annotations

from pathlib import Path
import json

import numpy as np

from gui.utarldd_replay import (
    UtaRlddVideo,
    UtaRlddVideoSummary,
    _bgr_to_qimage,
    discover_utarldd_videos,
    parse_utarldd_label,
    run_replay_batch,
    write_full_summary_csv,
    write_summary_csv,
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
    summary = UtaRlddVideoSummary(
        subject="01",
        label="0",
        label_name="Alert",
        video_path="C:/video/01/0.mov",
        frames=10,
        face_frames=9,
        face_rate=0.9,
        status="done",
    )

    write_summary_csv(out, [summary])

    text = out.read_text(encoding="utf-8-sig")
    assert "受試者,資料集標籤,警覺類別,快速判讀" in text
    assert "01,0,Alert,未見明顯疲勞" in text


def test_write_full_summary_csv_keeps_machine_readable_fields(tmp_path: Path) -> None:
    out = tmp_path / "summary_full.csv"
    summary = UtaRlddVideoSummary(
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
    assert "01,10,Drowsy" in text


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
        UtaRlddVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        UtaRlddVideo("01", "10", "Drowsy", tmp_path / "01" / "10.MOV"),
    ]

    def fake_discover(root, *, subjects=None, labels=None):
        assert root == tmp_path / "dataset"
        return videos

    def fake_replay(video, output_dir, run_stamp, **kwargs):
        return UtaRlddVideoSummary(
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

    monkeypatch.setattr("gui.utarldd_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.utarldd_replay.run_replay_video", fake_replay)

    result = run_replay_batch(tmp_path / "dataset", output_dir=tmp_path / "out", max_videos=2)

    assert result.videos_total == 2
    assert result.videos_done == 1
    assert result.videos_failed == 1
    assert result.summary_csv.exists()
    assert result.full_summary_csv.exists()
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_url"] == "https://sites.google.com/view/utarldd/home"
    assert manifest["summary_csv"] == str(result.summary_csv)
    assert manifest["full_summary_csv"] == str(result.full_summary_csv)
    assert manifest["labels"] == {"0": "Alert", "5": "Low Vigilant", "10": "Drowsy"}
    assert len(manifest["summaries"]) == 2


def test_run_replay_batch_parallel_keeps_video_order(tmp_path: Path, monkeypatch) -> None:
    videos = [
        UtaRlddVideo("01", "0", "Alert", tmp_path / "01" / "0.mov"),
        UtaRlddVideo("01", "5", "Low Vigilant", tmp_path / "01" / "5.mov"),
        UtaRlddVideo("01", "10", "Drowsy", tmp_path / "01" / "10.mov"),
    ]

    def fake_discover(root, *, subjects=None, labels=None):
        return videos

    def fake_process_job(args):
        video, output_dir, run_stamp, _max_frames, _write_annotated_video = args
        return UtaRlddVideoSummary(
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

    monkeypatch.setattr("gui.utarldd_replay.discover_utarldd_videos", fake_discover)
    monkeypatch.setattr("gui.utarldd_replay._run_replay_video_process_job", fake_process_job)
    monkeypatch.setattr("gui.utarldd_replay.ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr("gui.utarldd_replay.wait", lambda futures, timeout, return_when: (set(futures), set()))

    result = run_replay_batch(tmp_path / "dataset", output_dir=tmp_path / "out", jobs=2)

    assert [(s.subject, s.label) for s in result.summaries] == [
        ("01", "0"),
        ("01", "5"),
        ("01", "10"),
    ]
    assert result.videos_total == 3
    assert result.videos_done == 3
