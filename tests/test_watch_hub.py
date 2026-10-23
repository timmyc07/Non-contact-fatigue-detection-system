"""心跳帶 90 秒視窗、異常時鐘及有界緩衝的契約。"""

from __future__ import annotations

from dataclasses import asdict
import threading

import numpy as np
import pytest

from rppg import calibration_watch as module
from rppg.watch_physio import compute_watch_physio


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    return now


def sample(timestamp, number=0):
    rr = 820.0 + 20.0 * np.sin(number / 10.0)
    return module.WatchSample(
        timestamp, round(60_000 / rr), number, 1000,
        motion_level=0.1, rr_intervals_ms=(rr,),
    )


def test_history_retains_only_current_window_and_lifetime_counters(clock):
    hub = module.WatchHrHub()
    for number in range(180):
        clock[0] = 1000.0 + number
        hub.add(sample(clock[0], number))

    rows = hub.snapshot()
    assert [row.ts_ms for row in rows] == list(range(89, 180))
    assert hub.latest() is rows[-1]
    assert hub.total_received == 180
    clock[0] += 91.0
    assert hub.snapshot() == []
    assert hub.latest().ts_ms == 179
    assert hub.total_received == 180


def test_window_boundary_and_out_of_order_samples_keep_arrival_order(clock):
    hub = module.WatchHrHub()
    for timestamp in (910.0, 950.0, 920.0, 1000.0, 900.0, 940.0):
        hub.add(sample(timestamp))
    assert [row.received_at for row in hub.snapshot()] == [910.0, 950.0, 920.0, 1000.0, 940.0]
    clock[0] = 1010.0
    assert [row.received_at for row in hub.snapshot()] == [950.0, 920.0, 1000.0, 940.0]
    hub.add(sample(850.0))
    assert [row.received_at for row in hub.snapshot()] == [950.0, 920.0, 1000.0, 940.0]
    assert hub.latest().received_at == 850.0
    assert hub.total_received == 7


@pytest.mark.parametrize("timestamp", [1100.0, float("nan"), float("inf"), -float("inf")])
def test_invalid_time_is_reported_without_evicting_valid_samples(clock, caplog, timestamp):
    hub = module.WatchHrHub()
    valid = sample(995.0)
    invalid = sample(timestamp)
    hub.add(valid)
    hub.add(invalid)
    assert hub.snapshot() == [valid]
    assert hub.latest() is invalid
    assert hub.total_received == 2
    assert caplog.records
    assert not hub.is_connected()


def test_clock_rollback_keeps_valid_intersection_and_reports_missing_coverage(clock, caplog):
    hub = module.WatchHrHub()
    for timestamp in (940.0, 950.0, 960.0, 970.0, 980.0, 990.0, 1000.0):
        hub.add(sample(timestamp))
    clock[0] = 970.0
    assert [row.received_at for row in hub.snapshot()] == [940.0, 950.0, 960.0, 970.0]
    assert "時間倒退" in caplog.text
    assert hub.latest().received_at == 1000.0
    assert not hub.is_connected()
    hub.add(sample(965.0))
    assert [row.received_at for row in hub.snapshot()] == [940.0, 950.0, 960.0, 970.0, 965.0]
    assert hub.total_received == 8
    assert hub.is_connected()


def test_frozen_clock_has_a_reported_hard_limit_and_clear_resets_counters(clock, caplog):
    hub = module.WatchHrHub()
    for number in range(10_005):
        hub.add(sample(clock[0], number))
    rows = hub.snapshot()
    assert len(rows) == 10_000
    assert rows[0].ts_ms == 5
    assert hub.latest() is rows[-1]
    assert hub.total_received == 10_005
    assert "10000" in caplog.text
    assert "最新" in caplog.text
    assert len(caplog.records) == 1
    hub.clear()
    assert hub.snapshot() == []
    assert hub.latest() is None
    assert hub.total_received == 0
    assert not hub.is_connected()


def test_current_window_preserves_physiology_exactly_over_a_two_hour_stream(clock):
    hub = module.WatchHrHub()
    history = []
    for number in range(7200):
        clock[0] = 1000.0 + number
        row = sample(clock[0], number)
        history.append(row)
        hub.add(row)
        if number in (89, 899, 3599, 7199):
            actual = hub.snapshot()
            assert len(actual) <= 91
            expected = [row for row in history if clock[0] - row.received_at <= 90.0]
            assert actual == expected
            assert asdict(compute_watch_physio(actual)) == asdict(compute_watch_physio(history))
    assert hub.total_received == 7200


def test_parallel_producers_and_readers_do_not_restore_data_cleared_midstream(clock):
    hub = module.WatchHrHub()
    phase = threading.Barrier(4)

    def produce(producer):
        for epoch in range(2):
            for number in range(300):
                hub.add(sample(clock[0], epoch * 10_000 + producer * 1000 + number))
                hub.snapshot()
            phase.wait(timeout=3.0)
            phase.wait(timeout=3.0)

    threads = [threading.Thread(target=produce, args=(producer,)) for producer in range(3)]
    for thread in threads:
        thread.start()
    complete = False
    try:
        phase.wait(timeout=3.0)
        assert hub.total_received == 900
        hub.clear()
        phase.wait(timeout=3.0)
        phase.wait(timeout=3.0)
        rows = hub.snapshot()
        assert len(rows) == hub.total_received == 900
        assert all(row.ts_ms >= 10_000 for row in rows)
        assert hub.latest() is rows[-1]
        phase.wait(timeout=3.0)
        complete = True
    finally:
        if not complete:
            phase.abort()
        for thread in threads:
            thread.join(timeout=3.0)
    assert not any(thread.is_alive() for thread in threads)
