"""``gui.metrics_recorder.MetricsRecorder`` 背景 writer thread 改造的單元測試。

驗證重點：
1. ``record()`` 多筆（跨多個 BATCH_SIZE 批次）+ ``close()`` 後，所有資料皆已
   落盤（close() 保證 writer thread 排空佇列後才回傳，語意不變）。
2. ``close()`` 完成後會在 db 旁寫一份 ``<db>.meta.json`` sidecar，內容符合
   固定契約：``{"schema_version": 1, "rows": int, "ts_min": float|None,
   "ts_max": float|None}``。
3. 寫入失敗（不支援的欄位型別）時 ``close()``/``record()`` 都不拋出例外，
   改記 logger warning（不再靜默吞掉）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.metrics_recorder import MetricsRecorder  # noqa: E402


def _blank_payload(**overrides) -> dict:
    payload = {col: None for col in MetricsRecorder.COLUMNS}
    payload.update(overrides)
    return payload


def test_record_and_close_flushes_all_rows(tmp_path):
    db_path = tmp_path / "metrics.db"
    recorder = MetricsRecorder(str(db_path))

    n = 250  # 跨多個 BATCH_SIZE(100) 批次，涵蓋背景 writer thread 的批次邏輯
    for i in range(n):
        recorder.record(_blank_payload(timestamp=float(i), bpm=60.0 + i))
    recorder.close()

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        first_bpm = conn.execute(
            "SELECT bpm FROM metrics ORDER BY timestamp ASC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == n
    assert first_bpm == 60.0


def test_close_writes_meta_sidecar_with_expected_contract(tmp_path):
    db_path = tmp_path / "metrics_sidecar.db"
    recorder = MetricsRecorder(str(db_path))

    for ts in (1.5, 3.5, 2.5):
        recorder.record(_blank_payload(timestamp=ts))
    recorder.close()

    meta_path = Path(f"{db_path}.meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "schema_version": 1,
        "rows": 3,
        "ts_min": 1.5,
        "ts_max": 3.5,
    }


def test_close_with_no_records_writes_empty_sidecar(tmp_path):
    db_path = tmp_path / "metrics_empty.db"
    recorder = MetricsRecorder(str(db_path))
    recorder.close()

    meta_path = Path(f"{db_path}.meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "schema_version": 1,
        "rows": 0,
        "ts_min": None,
        "ts_max": None,
    }


def test_write_failure_logs_warning_and_does_not_raise(tmp_path, caplog):
    db_path = tmp_path / "metrics_bad.db"
    recorder = MetricsRecorder(str(db_path))

    # camera_label 欄位是 TEXT，塞一個 sqlite3 無法綁定的物件觸發批次寫入失敗。
    bad_payload = _blank_payload(timestamp=1.0, camera_label=object())

    with caplog.at_level(logging.WARNING, logger="gui.metrics_recorder"):
        recorder.record(bad_payload)  # 不應拋出例外
        recorder.close()  # 不應拋出例外，即使背景批次寫入失敗

    assert any("batch write failed" in r.message for r in caplog.records)

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    finally:
        conn.close()
    assert count == 0  # 失敗的整批未落盤（與原本行為一致：整批捨棄不重試）


def test_record_after_close_is_noop_not_raise(tmp_path):
    db_path = tmp_path / "metrics_afterclose.db"
    recorder = MetricsRecorder(str(db_path))
    recorder.close()

    recorder.record(_blank_payload(timestamp=99.0))  # 不應拋出例外

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_failed_batch_is_rolled_back_before_next_success(tmp_path, monkeypatch):
    failed = threading.Event()

    class SignalHandler(logging.Handler):
        def emit(self, record):
            if "batch write failed" in record.getMessage():
                failed.set()

    handler = SignalHandler()
    log = logging.getLogger("gui.metrics_recorder")
    log.addHandler(handler)
    monkeypatch.setattr(MetricsRecorder, "BATCH_SIZE", 2)
    db_path = tmp_path / "rollback.db"
    recorder = MetricsRecorder(str(db_path))
    try:
        recorder.record(_blank_payload(timestamp=1.0))
        recorder.record(_blank_payload(timestamp=2.0, camera_label=object()))
        assert failed.wait(2.0)
        recorder.record(_blank_payload(timestamp=3.0))
    finally:
        recorder.close()
        log.removeHandler(handler)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT timestamp FROM metrics").fetchall() == [(3.0,)]
    assert recorder.get_recording_stats()[0] == 1
    meta = json.loads(Path(f"{db_path}.meta.json").read_text())
    assert (meta["rows"], meta["ts_min"], meta["ts_max"]) == (1, 3.0, 3.0)


def test_conn_available_synchronously_after_init_for_schema_introspection(tmp_path):
    # gui/main_window.py 與既有測試（test_mediapipe_enhancements.py）在建構後
    # 立即同步存取 recorder.conn 做 schema introspection；背景 writer thread
    # 化後仍須保留這個同步保證（__init__ 內等待 writer thread ready）。
    db_path = tmp_path / "metrics_conn.db"
    recorder = MetricsRecorder(str(db_path))
    try:
        cols = {
            row[1]
            for row in recorder.conn.execute("PRAGMA table_info(metrics)").fetchall()
        }
    finally:
        recorder.close()
    assert "timestamp" in cols
    assert "bpm" in cols


def test_request_close_retains_finalization_until_sidecar_is_complete(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = MetricsRecorder._write_meta_sidecar

    def delayed_sidecar(self, *args):
        entered.set()
        assert release.wait(2.0)
        original(self, *args)

    monkeypatch.setattr(MetricsRecorder, "_write_meta_sidecar", delayed_sidecar)
    monkeypatch.setattr(MetricsRecorder, "JOIN_TIMEOUT_SEC", 0.01)
    recorder = MetricsRecorder(str(tmp_path / "finalizing.db"))
    try:
        recorder.record(_blank_payload(timestamp=1.0))
        recorder.request_close()
        assert entered.wait(2.0)
        assert not recorder.wait_closed(timeout_seconds=0.01)
        assert not recorder.close()
        assert not recorder.is_finalized
    finally:
        release.set()
        recorder.close()

    assert recorder.wait_closed(timeout_seconds=2.0)
    assert recorder.is_finalized
    assert recorder.close()
    assert json.loads(Path(f"{recorder.db_path}.meta.json").read_text())["rows"] == 1


def test_initialization_timeout_stops_late_writer(tmp_path, monkeypatch):
    release = threading.Event()
    original = MetricsRecorder._writer_main

    def delayed_start(self):
        assert release.wait(2.0)
        original(self)

    monkeypatch.setattr(MetricsRecorder, "INIT_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(MetricsRecorder, "_writer_main", delayed_start)
    recorder = MetricsRecorder.__new__(MetricsRecorder)
    try:
        with pytest.raises(RuntimeError, match="startup timed out"):
            recorder.__init__(str(tmp_path / "late.db"))
        assert recorder._closed
        assert recorder._stop_event.is_set()
    finally:
        release.set()
        recorder.close()
    assert recorder.wait_closed(timeout_seconds=2.0)
    assert recorder.conn is None


def test_record_preparation_cannot_enqueue_after_close(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class SlowPayload(dict):
        def get(self, key, default=None):
            if key == "timestamp":
                entered.set()
                assert release.wait(2.0)
            return super().get(key, default)

    recorder = MetricsRecorder(str(tmp_path / "closing_race.db"))
    producer = threading.Thread(target=recorder.record, args=(SlowPayload(timestamp=1.0),))
    producer.start()
    try:
        assert entered.wait(2.0)
        recorder.close()
    finally:
        release.set()
        producer.join(timeout=2.0)
        recorder.close()
    assert not producer.is_alive()
    assert recorder._queue.empty()
    assert recorder.get_recording_stats()[0] == 0

