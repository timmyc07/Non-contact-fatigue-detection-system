"""P6b-4：belt-truth 同步錄製的單元測試。

驗證重點：
1. ``rppg.belt_truth_capture``：writer/reader 往返一致（含 belt_bpm=None）、
   provider 例外/NaN/Inf 一律記為 None、關檔後寫入不丟例外、讀檔對壞行容錯略過、
   讀取不存在的檔案丟 FileNotFoundError（可行動訊息）。
2. ``rppg.hr_belt_ble.HrBeltConfig.capture_enabled``：預設 False、可從設定檔讀取、
   非法型別回退 False。
3. ``gui.belt_runtime.BeltRuntime.create_truth_capture_writer``：belt_bpm provider
   在未連線/未接觸/資料停滯時回傳 None，僅在連線良好且新鮮時回傳 BPM。
4. ``RppgWorker``/``CombinedWorker`` 的 ``set_belt_truth_capture`` 熱切換與
   ``_maybe_capture_belt_truth``：OFF（預設 None）時逐位元不變（不呼叫 writer），
   ON 時把本幀 per-ROI 均值轉送給 writer.record()；run() 原始碼守衛確認兩條
   worker 的呼叫點都在 push_roi_means 之後、per_roi_means 存在時才觸發。
5. ``gui.main_window.MainWindow._dispatch_belt_truth_capture``：轉發給兩個 worker、
   容忍兩者皆為 None。
"""

from __future__ import annotations

import json
import queue
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from rppg.belt_truth_capture import (  # noqa: E402
    BeltTruthCaptureRecord,
    BeltTruthCaptureWriter,
    default_capture_path,
    load_belt_truth_capture,
)
from rppg.hr_belt_ble import HrBeltConfig, HrBeltStatus, load_hr_belt_config  # noqa: E402


# ── BeltTruthCaptureWriter / load_belt_truth_capture ────────────────────────

def test_writer_reader_round_trip(tmp_path):
    path = tmp_path / "cap.jsonl"
    bpm_values = iter([70.0, None, 71.5])
    writer = BeltTruthCaptureWriter(path, belt_bpm_provider=lambda: next(bpm_values))

    writer.record(1.0, {"forehead": (10.0, 20.0, 30.0), "L_cheek": (11.0, 21.0, 31.0)})
    writer.record(2.0, {"forehead": (12.0, 22.0, 32.0)})
    writer.record(3.0, {"forehead": (13.0, 23.0, 33.0)})
    assert writer.record_count == 3
    writer.close()

    records = load_belt_truth_capture(path)
    assert len(records) == 3
    assert records[0] == BeltTruthCaptureRecord(
        t=1.0,
        roi_means={"forehead": (10.0, 20.0, 30.0), "L_cheek": (11.0, 21.0, 31.0)},
        belt_bpm=70.0,
    )
    assert records[1].belt_bpm is None
    assert records[2].belt_bpm == pytest.approx(71.5)


def test_writer_no_provider_defaults_to_none(tmp_path):
    path = tmp_path / "cap.jsonl"
    writer = BeltTruthCaptureWriter(path)
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(path)
    assert records[0].belt_bpm is None


def test_writer_provider_exception_records_none(tmp_path):
    def _raising():
        raise RuntimeError("boom")

    path = tmp_path / "cap.jsonl"
    writer = BeltTruthCaptureWriter(path, belt_bpm_provider=_raising)
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(path)
    assert records[0].belt_bpm is None


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_writer_provider_nan_inf_records_none(tmp_path, bad_value):
    path = tmp_path / "cap.jsonl"
    writer = BeltTruthCaptureWriter(path, belt_bpm_provider=lambda: bad_value)
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(path)
    assert records[0].belt_bpm is None


def test_writer_record_after_close_is_noop_not_raise(tmp_path):
    path = tmp_path / "cap.jsonl"
    writer = BeltTruthCaptureWriter(path)
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    writer.record(1.0, {"forehead": (4.0, 5.0, 6.0)})  # 不應丟例外
    assert writer.record_count == 1


def test_writer_context_manager_closes(tmp_path):
    path = tmp_path / "cap.jsonl"
    with BeltTruthCaptureWriter(path) as writer:
        writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    assert writer._closed is True
    records = load_belt_truth_capture(path)
    assert len(records) == 1


def test_load_missing_file_raises_filenotfounderror(tmp_path):
    missing = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(FileNotFoundError):
        load_belt_truth_capture(missing)


def test_load_skips_malformed_lines(tmp_path):
    path = tmp_path / "cap.jsonl"
    good = json.dumps({"t": 1.0, "roi_means": {"forehead": [1.0, 2.0, 3.0]}, "belt_bpm": 65.0})
    path.write_text(
        "not json at all\n"
        + good + "\n"
        + json.dumps({"t": 2.0}) + "\n"  # 缺 roi_means
        + "\n",  # 空行
        encoding="utf-8",
    )
    records = load_belt_truth_capture(path)
    assert len(records) == 1
    assert records[0].t == 1.0
    assert records[0].belt_bpm == 65.0


def test_default_capture_path_creates_dir_and_timestamped_name(tmp_path):
    base = tmp_path / "belt_truth_capture"
    path = default_capture_path(base)
    assert path.parent == base
    assert base.exists()
    assert path.name.startswith("belt_truth_")
    assert path.suffix == ".jsonl"


# ── HrBeltConfig.capture_enabled ─────────────────────────────────────────────

def test_capture_enabled_defaults_false():
    assert HrBeltConfig().capture_enabled is False


def test_load_hr_belt_config_capture_enabled_true(tmp_path):
    path = tmp_path / "hr_belt.json"
    path.write_text(json.dumps({"capture_enabled": True}), encoding="utf-8")
    cfg = load_hr_belt_config(path)
    assert cfg.capture_enabled is True


def test_load_hr_belt_config_capture_enabled_invalid_type_falls_back(tmp_path):
    path = tmp_path / "hr_belt.json"
    path.write_text(json.dumps({"capture_enabled": "yes"}), encoding="utf-8")
    cfg = load_hr_belt_config(path)
    assert cfg.capture_enabled is False


def test_load_hr_belt_config_missing_file_defaults_false(tmp_path):
    cfg = load_hr_belt_config(tmp_path / "nope.json")
    assert cfg.capture_enabled is False


# ── BeltRuntime.create_truth_capture_writer ──────────────────────────────────

def _status(**overrides) -> HrBeltStatus:
    base = dict(state="connected", bpm=70, last_sample_at=time.time())
    base.update(overrides)
    return HrBeltStatus(**base)


def test_belt_runtime_provider_returns_bpm_when_connected_and_fresh(tmp_path):
    from gui.belt_runtime import BeltRuntime

    runtime = BeltRuntime()
    runtime.belt_status = lambda: _status(bpm=72)  # type: ignore[method-assign]
    writer = runtime.create_truth_capture_writer(tmp_path / "cap.jsonl")
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(tmp_path / "cap.jsonl")
    assert records[0].belt_bpm == pytest.approx(72.0)


def test_belt_runtime_provider_returns_none_when_not_connected(tmp_path):
    from gui.belt_runtime import BeltRuntime

    runtime = BeltRuntime()
    runtime.belt_status = lambda: _status(state="scanning")  # type: ignore[method-assign]
    writer = runtime.create_truth_capture_writer(tmp_path / "cap.jsonl")
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(tmp_path / "cap.jsonl")
    assert records[0].belt_bpm is None


def test_belt_runtime_provider_returns_none_when_status_is_none(tmp_path):
    from gui.belt_runtime import BeltRuntime

    runtime = BeltRuntime()
    runtime.belt_status = lambda: None  # type: ignore[method-assign]
    writer = runtime.create_truth_capture_writer(tmp_path / "cap.jsonl")
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(tmp_path / "cap.jsonl")
    assert records[0].belt_bpm is None


def test_belt_runtime_provider_returns_none_when_bpm_zero(tmp_path):
    from gui.belt_runtime import BeltRuntime

    runtime = BeltRuntime()
    runtime.belt_status = lambda: _status(bpm=0)  # type: ignore[method-assign]
    writer = runtime.create_truth_capture_writer(tmp_path / "cap.jsonl")
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(tmp_path / "cap.jsonl")
    assert records[0].belt_bpm is None


def test_belt_runtime_provider_returns_none_when_stale(tmp_path):
    from gui.belt_runtime import BeltRuntime

    runtime = BeltRuntime()
    runtime.belt_status = lambda: _status(last_sample_at=time.time() - 3600)  # type: ignore[method-assign]
    writer = runtime.create_truth_capture_writer(tmp_path / "cap.jsonl")
    writer.record(0.0, {"forehead": (1.0, 2.0, 3.0)})
    writer.close()
    records = load_belt_truth_capture(tmp_path / "cap.jsonl")
    assert records[0].belt_bpm is None


# ── RppgWorker / CombinedWorker：set_belt_truth_capture + _maybe_capture_belt_truth ──

pytest.importorskip("PySide6")

from rppg.rppg_worker import RppgWorker  # noqa: E402


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict]] = []

    def record(self, t: float, roi_means: dict) -> None:
        self.calls.append((t, dict(roi_means)))


class _ExplodingWriter:
    def record(self, t: float, roi_means: dict) -> None:  # pragma: no cover - 預期不會被呼叫
        raise AssertionError("OFF（無 writer）時不應呼叫 record()")


def test_rppg_worker_belt_truth_capture_none_by_default():
    worker = RppgWorker(queue.Queue())
    assert worker._belt_truth_capture is None


def test_rppg_worker_set_belt_truth_capture_hotswap():
    worker = RppgWorker(queue.Queue())
    writer = _FakeWriter()
    worker.set_belt_truth_capture(writer)  # type: ignore[arg-type]
    assert worker._belt_truth_capture is writer
    worker.set_belt_truth_capture(None)
    assert worker._belt_truth_capture is None


def test_rppg_worker_maybe_capture_belt_truth_off_is_noop():
    worker = RppgWorker(queue.Queue())
    worker._maybe_capture_belt_truth(1.0, {"forehead": (1.0, 2.0, 3.0)})  # 不應丟例外，OFF 早退


def test_rppg_worker_maybe_capture_belt_truth_off_after_clear_does_not_touch_old_writer():
    worker = RppgWorker(queue.Queue())
    exploding = _ExplodingWriter()
    worker.set_belt_truth_capture(exploding)  # type: ignore[arg-type]
    worker.set_belt_truth_capture(None)
    worker._maybe_capture_belt_truth(1.0, {"forehead": (1.0, 2.0, 3.0)})  # 不應呼叫 exploding.record


def test_rppg_worker_maybe_capture_belt_truth_on_forwards_to_writer():
    worker = RppgWorker(queue.Queue())
    writer = _FakeWriter()
    worker.set_belt_truth_capture(writer)  # type: ignore[arg-type]
    means = {"forehead": (1.0, 2.0, 3.0), "L_cheek": (4.0, 5.0, 6.0)}
    worker._maybe_capture_belt_truth(2.5, means)
    assert writer.calls == [(2.5, means)]


def test_rppg_worker_run_source_calls_maybe_capture_after_push_roi_means():
    import inspect

    src = inspect.getsource(RppgWorker.run)
    push_idx = src.index("engine.push_roi_means(ts, per_roi_means)")
    capture_idx = src.index("self._maybe_capture_belt_truth(ts, per_roi_means)")
    assert capture_idx > push_idx


def test_combined_worker_belt_truth_capture_none_by_default_and_hotswap():
    cw_mod = pytest.importorskip("gui.combined_worker")
    worker = cw_mod.CombinedWorker(queue.Queue())
    assert worker._belt_truth_capture is None
    writer = _FakeWriter()
    worker.set_belt_truth_capture(writer)  # type: ignore[arg-type]
    assert worker._belt_truth_capture is writer
    worker.set_belt_truth_capture(None)
    assert worker._belt_truth_capture is None


def test_combined_worker_maybe_capture_belt_truth_off_is_noop():
    cw_mod = pytest.importorskip("gui.combined_worker")
    worker = cw_mod.CombinedWorker(queue.Queue())
    worker._maybe_capture_belt_truth(1.0, {"forehead": (1.0, 2.0, 3.0)})  # 不應丟例外


def test_combined_worker_maybe_capture_belt_truth_on_forwards_to_writer():
    cw_mod = pytest.importorskip("gui.combined_worker")
    worker = cw_mod.CombinedWorker(queue.Queue())
    writer = _FakeWriter()
    worker.set_belt_truth_capture(writer)  # type: ignore[arg-type]
    means = {"forehead": (7.0, 8.0, 9.0)}
    worker._maybe_capture_belt_truth(3.0, means)
    assert writer.calls == [(3.0, means)]


def test_combined_worker_run_source_calls_maybe_capture_after_push_roi_means():
    cw_mod = pytest.importorskip("gui.combined_worker")
    import inspect

    src = inspect.getsource(cw_mod.CombinedWorker.run)
    push_idx = src.index("rppg_engine.push_roi_means(ts, per_roi_means)")
    capture_idx = src.index("self._maybe_capture_belt_truth(ts, per_roi_means)")
    assert capture_idx > push_idx


# ── gui.main_window._dispatch_belt_truth_capture（fake self）─────────────────

def test_dispatch_belt_truth_capture_forwards_to_both_workers():
    from gui.main_window import MainWindow

    calls = {"combined": [], "rppg": []}
    fake = SimpleNamespace(
        _combined_worker=SimpleNamespace(set_belt_truth_capture=lambda w: calls["combined"].append(w)),
        _rppg_worker=SimpleNamespace(set_belt_truth_capture=lambda w: calls["rppg"].append(w)),
    )
    writer = _FakeWriter()

    MainWindow._dispatch_belt_truth_capture(fake, writer)  # type: ignore[arg-type]

    assert calls["combined"] == [writer]
    assert calls["rppg"] == [writer]


def test_dispatch_belt_truth_capture_tolerates_no_active_worker():
    from gui.main_window import MainWindow

    fake = SimpleNamespace(_combined_worker=None, _rppg_worker=None)
    MainWindow._dispatch_belt_truth_capture(fake, None)  # 不應丟例外
