"""Tests for rPPG BPM calibration store and apply helpers."""

from __future__ import annotations

import json
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
