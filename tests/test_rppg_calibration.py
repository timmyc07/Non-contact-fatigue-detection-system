"""Tests for rPPG BPM calibration store and apply helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rppg.calibration import (
    ORIGIN_VERSION_ID,
    CalibrationParams,
    CalibrationSessionAnalyzer,
    CalibrationVersion,
    CalibrationVersionStore,
    apply_bpm_calibration,
    apply_calibration_to_metrics,
    effective_bpm,
    is_live_feed_enabled,
    origin_version,
    read_live_feed,
    rppg_sample_quality_ok,
    set_live_feed_enabled,
    write_live_feed,
)
from rppg.rppg_worker import RppgMetrics


def test_apply_bpm_bias_offset():
    version = CalibrationVersion(
        id="v_test",
        name="test",
        model="bias",
        params=CalibrationParams(bpm_offset=-5.0, bpm_scale=1.0),
    )
    assert apply_bpm_calibration(76.0, version) == pytest.approx(71.0)


def test_origin_version_is_identity():
    version = origin_version()
    assert version.is_identity
    assert apply_bpm_calibration(80.0, version) == pytest.approx(80.0)


def test_apply_calibration_to_rppg_metrics():
    version = CalibrationVersion(
        id="v_test",
        name="test",
        model="bias",
        params=CalibrationParams(bpm_offset=3.0),
    )
    raw = RppgMetrics(bpm=70.0, raw_bpm=72.0, face_detected=True)
    out = apply_calibration_to_metrics(raw, version)
    assert out.bpm_calibrated == pytest.approx(73.0)
    assert out.calibration_version_id == "v_test"
    assert out.peak_freq_hz_calibrated == pytest.approx(73.0 / 60.0)


def test_effective_bpm_prefers_calibrated():
    metrics = RppgMetrics(bpm=70.0, bpm_calibrated=68.0)
    assert effective_bpm(metrics) == pytest.approx(68.0)


def test_quality_gate_rejects_low_sqi():
    sample = {
        "bpm": 72.0,
        "warmup_progress": 1.0,
        "sqi": 0.2,
        "quality_score": 0.8,
        "roi_valid_count": 4,
        "bpm_guarded": False,
    }
    assert rppg_sample_quality_ok(sample) is False


def test_calibration_rppg_bpm_prefers_raw_when_guarded():
    from rppg.calibration import calibration_rppg_bpm

    sample = {"bpm": 70.0, "raw_bpm": 78.0, "bpm_guarded": True}
    assert calibration_rppg_bpm(sample) == pytest.approx(78.0)


def test_session_analyzer_uses_calibration_gates(tmp_path: Path):
    analyzer = CalibrationSessionAnalyzer(window_sec=10.0, warmup_sec=0.0)
    start = 1000.0
    for i in range(20):
        ts = start + i
        analyzer.add_watch(ts, 72.0)
        analyzer.add_rppg(
            ts,
            {
                "bpm": 77.0,
                "warmup_progress": 1.0,
                "sqi": 0.6,
                "quality_score": 0.7,
                "roi_valid_count": 4,
                "bpm_guarded": False,
            },
        )
    result = analyzer.estimate(start, start + 20.0)
    assert result["windows_used"] >= 1
    assert result["offset_bpm"] == pytest.approx(-5.0, abs=0.5)


def test_version_store_save_and_switch(tmp_path: Path):
    store = CalibrationVersionStore(root=tmp_path / "rppg_calibration")
    version = store.save_new_version("測試", offset_bpm=-4.0, note="unit")
    assert version.id != ORIGIN_VERSION_ID
    assert store.get_active_version_id() == version.id
    store.set_active_version(ORIGIN_VERSION_ID)
    active = store.get_active_version()
    assert active.is_identity

    manifest = json.loads((tmp_path / "rppg_calibration" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["versions"]) >= 2


def test_version_cache_avoids_repeated_disk_reads_without_sharing_mutable_values(tmp_path, monkeypatch):
    store = CalibrationVersionStore(root=tmp_path)
    saved = store.save_new_version(
        "cached", offset_bpm=3.0,
        rppg_params={"roi_weights": {"forehead": 0.4}},
        session={"samples": [1, 2]}, metrics={"errors": [3]},
    )
    reads = []
    read_json = store._read_json

    def read(path):
        reads.append(path)
        return read_json(path)

    monkeypatch.setattr(store, "_read_json", read)
    first = store.get_active_version()
    assert first.to_dict() == saved.to_dict()
    first.name = "mutated"
    first.params.bpm_offset = 100.0
    first.params.rppg_params["roi_weights"]["forehead"] = 1.0
    first.session["samples"].append(9)
    first.metrics["errors"].clear()
    for _ in range(30):
        assert store.get_active_version().to_dict() == saved.to_dict()
    assert reads == [store.versions_dir / f"{saved.id}.json"]


@pytest.mark.parametrize("changed_field", ["mtime", "size"])
def test_version_cache_reloads_external_file_updates(tmp_path, changed_field):
    store = CalibrationVersionStore(root=tmp_path)
    saved = store.save_new_version("cached", offset_bpm=3.0)
    assert store.get_active_version().params.bpm_offset == 3.0
    path = store.versions_dir / f"{saved.id}.json"
    before = path.stat()
    data = json.loads(path.read_text())
    data["params"]["bpm_offset"] = 4.0 if changed_field == "mtime" else 100.0
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + (1 if changed_field == "mtime" else 0)))
    if changed_field == "mtime":
        assert path.stat().st_size == before.st_size
    else:
        assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert store.get_active_version().params.bpm_offset == data["params"]["bpm_offset"]


def test_version_cache_tracks_active_version_and_manifest_file_path(tmp_path):
    store = CalibrationVersionStore(root=tmp_path)
    first = store.save_new_version("first", offset_bpm=1.0)
    second = store.save_new_version("second", offset_bpm=2.0)
    assert store.get_active_version().params.bpm_offset == 2.0
    store.set_active_version(first.id)
    assert store.get_active_version().params.bpm_offset == 1.0
    path = store.versions_dir / f"{second.id}.json"
    target = tmp_path / "replacement.json"
    target.write_bytes(path.read_bytes())
    manifest = json.loads(store.manifest_path.read_text())
    for entry in manifest["versions"]:
        if entry["id"] == first.id:
            entry["file"] = target.name
    store._write_json(store.manifest_path, manifest)
    assert store.get_active_version().params.bpm_offset == 2.0


@pytest.mark.parametrize("origin", [False, True])
def test_version_cache_detects_missing_files_and_recovers(tmp_path, origin):
    store = CalibrationVersionStore(root=tmp_path)
    saved = origin_version() if origin else store.save_new_version("cached", offset_bpm=3.0)
    path = store.versions_dir / f"{saved.id}.json"
    contents = path.read_bytes()
    assert store.get_version(saved.id).to_dict() == saved.to_dict()
    path.unlink()
    if origin:
        assert store.get_version(saved.id).is_identity
    else:
        with pytest.raises(FileNotFoundError, match="校準版本檔案不存在"):
            store.get_version(saved.id)
    path.write_bytes(contents)
    assert store.get_version(saved.id).to_dict() == saved.to_dict()


def test_version_cache_does_not_hide_corruption_and_recovers(tmp_path):
    store = CalibrationVersionStore(root=tmp_path)
    saved = store.save_new_version("cached", offset_bpm=3.0)
    path = store.versions_dir / f"{saved.id}.json"
    assert store.get_active_version().params.bpm_offset == 3.0
    path.write_text("invalid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.get_active_version()
    data = saved.to_dict()
    data["params"]["bpm_offset"] = 7.0
    store._write_json(path, data)
    assert store.get_active_version().params.bpm_offset == 7.0


def test_versions_saved_in_same_second_keep_both_parameter_sets(tmp_path, monkeypatch):
    from datetime import datetime
    import rppg.calibration as calibration

    frozen = datetime(2026, 10, 22, 12, 0, 0)

    class FrozenClock:
        @staticmethod
        def now():
            return frozen

    monkeypatch.setattr(calibration, "datetime", FrozenClock)
    store = CalibrationVersionStore(root=tmp_path)
    first = store.save_new_version("first", offset_bpm=1.0)
    second = store.save_new_version("second", offset_bpm=2.0)

    assert first.id != second.id
    assert store.get_version(first.id).params.bpm_offset == 1.0
    assert store.get_version(second.id).params.bpm_offset == 2.0
    assert len({row["id"] for row in store.list_versions()}) == 3


def test_atomic_calibration_write_keeps_old_file_on_replace_failure(tmp_path, monkeypatch):
    import rppg.calibration as calibration

    path = tmp_path / "manifest.json"
    path.write_text('{"active_version_id":"old"}')

    def fail_replace(*_):
        raise OSError("disk failure")

    monkeypatch.setattr(calibration.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        CalibrationVersionStore._write_json(path, {"active_version_id": "new"})
    assert json.loads(path.read_text()) == {"active_version_id": "old"}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("action", ["save", "activate", "delete"])
def test_failed_manifest_write_does_not_publish_cache_or_delete_version(tmp_path, monkeypatch, action):
    import rppg.calibration as calibration

    store = CalibrationVersionStore(root=tmp_path)
    existing = store.save_new_version("existing", offset_bpm=1.0)
    before = json.loads(store.manifest_path.read_text())
    replace = calibration.os.replace

    def fail_manifest(source, target):
        if Path(target) == store.manifest_path:
            raise OSError("manifest failure")
        return replace(source, target)

    monkeypatch.setattr(calibration.os, "replace", fail_manifest)
    with pytest.raises(OSError, match="manifest failure"):
        if action == "save":
            store.save_new_version("new", offset_bpm=2.0)
        elif action == "activate":
            store.set_active_version(ORIGIN_VERSION_ID)
        else:
            store.delete_version(existing.id)
    assert store.get_active_version_id() == before["active_version_id"]
    assert store.list_versions() == before["versions"]
    assert json.loads(store.manifest_path.read_text()) == before
    assert store.get_version(existing.id).params.bpm_offset == 1.0


def test_default_store_and_live_feed_use_configured_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "runtime-data"
    monkeypatch.setenv("NCFD_DATA_ROOT", str(data_root))

    store = CalibrationVersionStore()
    assert store.root == data_root / "config" / "rppg_calibration"
    assert store.manifest_path.exists()
    assert (store.versions_dir / f"{ORIGIN_VERSION_ID}.json").exists()

    set_live_feed_enabled(True)
    assert is_live_feed_enabled() is True
    flag = data_root / "config" / "rppg_calibration_feed.enabled"
    assert flag.read_text(encoding="utf-8") == "enabled\n"

    metrics = RppgMetrics(bpm=72.0, raw_bpm=71.0, face_detected=True)
    write_live_feed(metrics)
    feed_path = data_root / "config" / "rppg_live_feed.json"
    assert feed_path.exists()
    assert read_live_feed() is not None

    set_live_feed_enabled(False)
    assert is_live_feed_enabled() is False


def test_live_feed_publishes_complete_snapshot_atomically(tmp_path, monkeypatch):
    from rppg import calibration

    monkeypatch.setenv("NCFD_DATA_ROOT", str(tmp_path))
    write_live_feed(RppgMetrics(bpm=71.0), enabled=True)
    feed = tmp_path / "config" / "rppg_live_feed.json"
    replace = os.replace
    swaps = []

    def checked_replace(source, target):
        assert Path(source).parent == feed.parent
        assert Path(target) == feed
        assert read_live_feed()["bpm"] == 71.0
        assert json.loads(Path(source).read_text())["bpm"] == 72.0
        swaps.append(Path(source))
        replace(source, target)

    monkeypatch.setattr(calibration.os, "replace", checked_replace)
    write_live_feed(RppgMetrics(bpm=72.0), enabled=True)
    assert len(swaps) == 1
    assert read_live_feed()["bpm"] == 72.0
    assert list(feed.parent.iterdir()) == [feed]


def test_live_feed_io_failure_preserves_previous_data_and_bounds_logs(tmp_path, monkeypatch, caplog):
    from rppg import calibration

    monkeypatch.setenv("NCFD_DATA_ROOT", str(tmp_path))
    write_live_feed(RppgMetrics(bpm=71.0), enabled=True)
    feed = tmp_path / "config" / "rppg_live_feed.json"
    replace = os.replace

    def fail_replace(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(calibration.os, "replace", fail_replace)
    for _ in range(3):
        write_live_feed(RppgMetrics(bpm=72.0), enabled=True)
    assert read_live_feed()["bpm"] == 71.0
    assert list(feed.parent.iterdir()) == [feed]
    assert len(caplog.records) == 1
    monkeypatch.setattr(calibration.os, "replace", replace)
    write_live_feed(RppgMetrics(bpm=72.0), enabled=True)
    assert read_live_feed()["bpm"] == 72.0
    monkeypatch.setattr(calibration.os, "replace", fail_replace)
    write_live_feed(RppgMetrics(bpm=73.0), enabled=True)
    assert len(caplog.records) == 2


def test_optional_live_feed_io_failure_does_not_interrupt_rppg_metrics(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gui.main_window import EngineApplication

    monkeypatch.setenv("NCFD_DATA_ROOT", str(tmp_path))
    set_live_feed_enabled(True)
    (tmp_path / "config" / "rppg_live_feed.json").mkdir()
    events = []
    application = SimpleNamespace(
        _combined_worker=None,
        _apply_rppg_calibration=lambda metrics: metrics,
        _record_metrics=lambda: events.append("recorded"),
        _emit_web_metrics=lambda: events.append("published"),
    )
    metrics = RppgMetrics(bpm=72.0)
    EngineApplication._on_rppg_metrics(application, metrics)
    assert application._latest_rppg_metrics is metrics
    assert events == ["recorded", "published"]


# ── P6：rppg_params 向後相容擴充 ───────────────────────────────────────────

def test_calibration_params_default_rppg_params_is_none():
    assert CalibrationParams().rppg_params is None


def test_version_without_rppg_params_serializes_bit_identical():
    # 不帶 rppg_params 的版本，序列化的 params 只有 bpm_offset/bpm_scale（無 null 噪音）。
    v = CalibrationVersion(id="v1", name="n", model="bias",
                           params=CalibrationParams(bpm_offset=2.0, bpm_scale=1.0))
    params = v.to_dict()["params"]
    assert set(params.keys()) == {"bpm_offset", "bpm_scale"}
    assert "rppg_params" not in params


def test_version_with_rppg_params_round_trip():
    rp = {"roi_weights": {"forehead": 0.4, "L_cheek": 0.2, "R_cheek": 0.2, "glabella": 0.2},
          "band": [0.65, 3.7]}
    v = CalibrationVersion(id="v2", name="learned", model="bias",
                           params=CalibrationParams(bpm_offset=1.0, rppg_params=rp))
    restored = CalibrationVersion.from_dict(v.to_dict())
    assert restored.params.rppg_params == rp
    assert restored.params.bpm_offset == 1.0
    # 帶 rppg_params 的版本即使 BPM 修正微小也非 identity
    assert restored.is_identity is False


def test_old_version_dict_without_rppg_params_loads_as_none():
    # 舊版本檔（無 rppg_params 欄位）載入後 rppg_params 為 None，向後相容。
    old = {"id": "v0", "name": "old", "model": "bias",
           "params": {"bpm_offset": 3.0, "bpm_scale": 1.0}}
    v = CalibrationVersion.from_dict(old)
    assert v.params.rppg_params is None


def test_save_new_version_persists_rppg_params(tmp_path: Path):
    store = CalibrationVersionStore(root=tmp_path / "rppg_calibration")
    rp = {"roi_weights": {"forehead": 0.5}}
    version = store.save_new_version("learned", offset_bpm=1.5, rppg_params=rp)
    reloaded = CalibrationVersionStore(root=tmp_path / "rppg_calibration").get_active_version()
    assert reloaded.id == version.id
    assert reloaded.params.rppg_params == rp
