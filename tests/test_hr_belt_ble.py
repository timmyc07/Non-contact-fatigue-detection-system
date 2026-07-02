"""Tests for BLE heart-rate belt (0x2A37) protocol parsing and hub integration."""

from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from rppg.calibration_watch import WatchHrHub, WatchSample
from rppg.hr_belt_ble import (
    HEART_RATE_SERVICE_UUID,
    HeartRateMeasurement,
    HrBeltBleClient,
    body_sensor_location_label,
    measurement_to_watch_sample,
    parse_battery_level,
    parse_heart_rate_measurement,
    pick_heart_rate_device,
)
from rppg.watch_adapter import build_watch_rppg_metrics
from rppg.watch_physio import ibis_from_watch_samples


# ── 2A37 Heart Rate Measurement 解析 ─────────────────────────────────────────

def test_parse_uint8_bpm_minimal_payload():
    m = parse_heart_rate_measurement(bytes([0x00, 72]))
    assert m.bpm == 72
    assert m.sensor_contact_supported is False
    assert m.sensor_contact_detected is False
    assert m.energy_expended_kj is None
    assert m.rr_intervals_ms == ()


def test_parse_uint16_bpm():
    m = parse_heart_rate_measurement(bytes([0x01, 0x2C, 0x01]))
    assert m.bpm == 300


def test_parse_sensor_contact_supported_and_detected():
    m = parse_heart_rate_measurement(bytes([0x06, 65]))
    assert m.sensor_contact_supported is True
    assert m.sensor_contact_detected is True


def test_parse_sensor_contact_supported_not_detected():
    m = parse_heart_rate_measurement(bytes([0x04, 65]))
    assert m.sensor_contact_supported is True
    assert m.sensor_contact_detected is False


def test_parse_contact_bit_ignored_when_not_supported():
    # bit1 只有在 bit2（支援）為 1 時才有意義
    m = parse_heart_rate_measurement(bytes([0x02, 65]))
    assert m.sensor_contact_supported is False
    assert m.sensor_contact_detected is False


def test_parse_energy_expended():
    m = parse_heart_rate_measurement(bytes([0x08, 70, 0x10, 0x27]))
    assert m.bpm == 70
    assert m.energy_expended_kj == 10000


def test_parse_rr_intervals_1024_resolution():
    # 1024 → 1000 ms、800 → 781.25 ms
    payload = bytes([0x10, 60, 0x00, 0x04, 0x20, 0x03])
    m = parse_heart_rate_measurement(payload)
    assert m.bpm == 60
    assert len(m.rr_intervals_ms) == 2
    assert m.rr_intervals_ms[0] == pytest.approx(1000.0)
    assert m.rr_intervals_ms[1] == pytest.approx(781.25)


def test_parse_full_flags_combination():
    # uint16 BPM + contact + energy + 1 組 RR
    payload = bytes([0x1F, 72, 0x00, 0x34, 0x12, 0x00, 0x04])
    m = parse_heart_rate_measurement(payload)
    assert m.bpm == 72
    assert m.sensor_contact_supported and m.sensor_contact_detected
    assert m.energy_expended_kj == 0x1234
    assert m.rr_intervals_ms == (pytest.approx(1000.0),)


def test_parse_rr_out_of_physiological_range_dropped():
    # raw 100 → 97.66 ms（< 200 ms 下限）應被過濾
    payload = bytes([0x10, 60, 100, 0x00, 0x00, 0x04])
    m = parse_heart_rate_measurement(payload)
    assert m.rr_intervals_ms == (pytest.approx(1000.0),)


def test_parse_trailing_odd_byte_ignored():
    payload = bytes([0x10, 60, 0x00, 0x04, 0x99])
    m = parse_heart_rate_measurement(payload)
    assert m.rr_intervals_ms == (pytest.approx(1000.0),)


@pytest.mark.parametrize(
    "payload",
    [b"", bytes([0x00]), bytes([0x01, 72]), bytes([0x08, 72, 0x01])],
)
def test_parse_truncated_payload_raises(payload):
    with pytest.raises(ValueError):
        parse_heart_rate_measurement(payload)


# ── 2A19 / 2A38 解析 ─────────────────────────────────────────────────────────

def test_parse_battery_level():
    assert parse_battery_level(bytes([85])) == 85
    assert parse_battery_level(bytes([0])) == 0
    assert parse_battery_level(bytes([101])) is None
    assert parse_battery_level(b"") is None


def test_body_sensor_location_label():
    assert body_sensor_location_label(bytes([1])) == "Chest"
    assert body_sensor_location_label(bytes([2])) == "Wrist"
    assert body_sensor_location_label(bytes([200])) == "Reserved(200)"
    assert body_sensor_location_label(b"") == ""


# ── measurement → WatchSample 轉換 ───────────────────────────────────────────

def test_measurement_to_watch_sample_uses_rr_sum_as_interval():
    m = HeartRateMeasurement(bpm=60, rr_intervals_ms=(1000.0, 980.0))
    sample = measurement_to_watch_sample(m, received_at=1000.0)
    assert sample is not None
    assert sample.bpm == 60
    assert sample.interval_ms == 1980
    assert sample.rr_intervals_ms == (1000.0, 980.0)
    assert sample.has_rr is True


def test_measurement_to_watch_sample_defaults_to_1hz_without_rr():
    m = HeartRateMeasurement(bpm=72)
    sample = measurement_to_watch_sample(m, received_at=1000.0)
    assert sample is not None
    assert sample.interval_ms == 1000
    assert sample.rr_intervals_ms is None
    assert sample.has_rr is False


def test_measurement_to_watch_sample_rejects_zero_bpm():
    assert measurement_to_watch_sample(HeartRateMeasurement(bpm=0)) is None


# ── IBI 計算：RR 優先、BPM 反推為後援 ───────────────────────────────────────

def test_ibis_prefer_real_rr_intervals():
    now = time.time()
    samples = [
        WatchSample(now, 60, 0, 1000, rr_intervals_ms=(990.0, 1010.0)),
        WatchSample(now, 75, 0, 1000),  # 無 RR → 60000/75 = 800
    ]
    ibis = ibis_from_watch_samples(samples)
    assert ibis.tolist() == pytest.approx([990.0, 1010.0, 800.0])


def test_ibis_bpm_fallback_matches_legacy_behavior():
    now = time.time()
    samples = [WatchSample(now, bpm, 0, 1000) for bpm in (60, 72, 80)]
    ibis = ibis_from_watch_samples(samples)
    expected = np.asarray([60000.0 / 60, 60000.0 / 72, 60000.0 / 80])
    assert np.allclose(ibis, expected)


# ── 掃描結果挑選 ─────────────────────────────────────────────────────────────

def _fake_candidate(name, address, rssi, service_uuids=()):
    device = SimpleNamespace(name=name, address=address)
    adv = SimpleNamespace(local_name=name, rssi=rssi, service_uuids=list(service_uuids))
    return device, adv


def test_pick_device_by_exact_address():
    a = _fake_candidate("Other HR", "AA:BB:CC:DD:EE:01", -40, [HEART_RATE_SERVICE_UUID])
    b = _fake_candidate("R+2.0 2248", "C1:3B:74:B8:F7:40", -80)
    picked = pick_heart_rate_device([a, b], address="c1:3b:74:b8:f7:40")
    assert picked is b[0]


def test_pick_device_by_name_prefix_prefers_stronger_rssi():
    a = _fake_candidate("R+2.0 1111", "AA:00:00:00:00:01", -90)
    b = _fake_candidate("R+2.0 2248", "AA:00:00:00:00:02", -55)
    c = _fake_candidate("Some Watch", "AA:00:00:00:00:03", -30, [HEART_RATE_SERVICE_UUID])
    picked = pick_heart_rate_device([a, b, c], name_prefix="R+")
    assert picked is b[0]


def test_pick_device_falls_back_to_hrs_advertiser():
    a = _fake_candidate("Generic Strap", "AA:00:00:00:00:01", -60, [HEART_RATE_SERVICE_UUID])
    b = _fake_candidate(None, "AA:00:00:00:00:02", -50)
    picked = pick_heart_rate_device([a, b], name_prefix="R+")
    assert picked is a[0]


def test_pick_device_none_when_no_match():
    b = _fake_candidate("Speaker", "AA:00:00:00:00:02", -50)
    assert pick_heart_rate_device([b], name_prefix="R+") is None
    assert pick_heart_rate_device([], name_prefix="R+") is None


def test_pick_device_address_specified_but_absent_returns_none():
    a = _fake_candidate("R+2.0 2248", "AA:00:00:00:00:01", -40)
    assert pick_heart_rate_device([a], address="C1:3B:74:B8:F7:40") is None


# ── hub 整合：心跳帶樣本 → watch pillar 指標 ────────────────────────────────

def test_belt_samples_flow_through_watch_pipeline():
    hub = WatchHrHub()
    now = time.time()
    for i in range(12):
        m = HeartRateMeasurement(bpm=70 + (i % 3), rr_intervals_ms=(850.0 + i * 2,))
        sample = measurement_to_watch_sample(m, received_at=now - (12 - i) * 0.9)
        assert sample is not None
        hub.add(sample)
    metrics = build_watch_rppg_metrics(hub)
    assert metrics.physio_source == "watch"
    assert metrics.face_detected is True
    assert metrics.bpm > 0
    assert metrics.roi_valid_count >= 1


# ── HrBeltBleClient 生命週期（不觸碰真實 BLE 硬體）──────────────────────────

def test_belt_client_initial_status_and_stop_without_start():
    client = HrBeltBleClient(WatchHrHub())
    st = client.status()
    assert st.state == "idle"
    assert client.running is False
    client.stop()  # 未啟動時 stop 應為安全 no-op
    assert client.status().state == "stopped"


def test_belt_client_hr_notification_updates_hub_and_status():
    hub = WatchHrHub()
    client = HrBeltBleClient(hub)
    payload = bytearray([0x16, 68, 0x00, 0x04])  # contact ok + 1 組 RR(1000ms)
    client._on_hr_notification(None, payload)
    st = client.status()
    assert st.bpm == 68
    assert st.rr_count == 1
    assert st.sensor_contact_detected is True
    assert st.notifications == 1
    latest = hub.latest()
    assert latest is not None
    assert latest.bpm == 68
    assert latest.rr_intervals_ms == (pytest.approx(1000.0),)


def test_belt_client_zero_bpm_notification_not_added_to_hub():
    hub = WatchHrHub()
    client = HrBeltBleClient(hub)
    client._on_hr_notification(None, bytearray([0x00, 0x00]))
    assert hub.latest() is None
    assert client.status().notifications == 1


def test_belt_client_battery_notification():
    client = HrBeltBleClient(WatchHrHub())
    client._on_battery_notification(None, bytearray([77]))
    assert client.status().battery_level == 77


def test_belt_client_rejects_notifications_after_stop():
    hub = WatchHrHub()
    client = HrBeltBleClient(hub)
    client.stop()
    client._on_hr_notification(None, bytearray([0x00, 70]))
    client._on_battery_notification(None, bytearray([50]))
    assert hub.latest() is None
    assert client.status().battery_level is None
