"""BLE 心跳帶（R+2.0 等標準 Heart Rate Service 裝置）協定解析與連線管理。

協定依據：
- Bluetooth SIG Heart Rate Service 1.0（service ``0x180D``）
- Heart Rate Measurement characteristic ``0x2A37``（notification）
- Body Sensor Location ``0x2A38``、Battery Service ``0x180F`` / ``0x2A19``
- 實機 GATT 對照：``docs/heart_rate_belt_bluetooth_gatt_profile.md``（R+2.0 2248）

模組分兩層：
1. 純解析函式（無 I/O、無執行緒），供測試與離線驗證。
2. :class:`HrBeltBleClient` 背景執行緒，內部跑 asyncio + bleak，
   把 notification 轉成 :class:`WatchSample` 推入 :class:`WatchHrHub`，
   讓既有 watch pillar（physio / fusion / dashboard）路徑完全重用。

bleak 為選配依賴：模組匯入不需要 bleak，僅在 ``HrBeltBleClient.start()``
時檢查；未安裝時回傳錯誤訊息而不丟例外。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from rppg.calibration_watch import WatchHrHub, WatchSample

logger = logging.getLogger(__name__)

# ── GATT UUID 常數（16-bit 標準 UUID 展開為 128-bit）─────────────────────────
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
BODY_SENSOR_LOCATION_UUID = "00002a38-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# R+2.0 2248 的預設裝置名稱前綴（Chrome bluetooth-internals 實測）。
DEFAULT_NAME_PREFIX = "R+"

# 2A38 Body Sensor Location 值對照（GATT Specification Supplement）。
BODY_SENSOR_LOCATION_LABELS: dict[int, str] = {
    0: "Other",
    1: "Chest",
    2: "Wrist",
    3: "Finger",
    4: "Hand",
    5: "Ear Lobe",
    6: "Foot",
}

# 2A37 flags bit 定義（HRS 1.0 §3.1.1.1）
_FLAG_HR_UINT16 = 0x01        # bit0：0=uint8、1=uint16（little-endian）
_FLAG_CONTACT_DETECTED = 0x02  # bit1：sensor contact 狀態
_FLAG_CONTACT_SUPPORTED = 0x04  # bit2：sensor contact 功能支援
_FLAG_ENERGY_PRESENT = 0x08    # bit3：Energy Expended（uint16, kJ）存在
_FLAG_RR_PRESENT = 0x10        # bit4：RR-Interval（uint16, 1/1024 s）存在

# RR-Interval 物理上合理範圍（ms）；超出者視為雜訊丟棄。
_RR_MIN_MS = 200.0
_RR_MAX_MS = 3000.0


@dataclass(frozen=True)
class HeartRateMeasurement:
    """單筆 ``0x2A37`` notification 的解析結果。"""

    bpm: int
    sensor_contact_supported: bool = False
    sensor_contact_detected: bool = False
    energy_expended_kj: int | None = None
    rr_intervals_ms: tuple[float, ...] = ()
    flags: int = 0


def parse_heart_rate_measurement(data: bytes | bytearray | memoryview) -> HeartRateMeasurement:
    """依 Heart Rate Service 規格解析 ``0x2A37`` notification payload。

    Raises:
        ValueError: payload 長度不足以容納 flags 宣告的欄位。
    """
    buf = bytes(data)
    if len(buf) < 2:
        raise ValueError(f"2A37 payload 過短：{len(buf)} bytes")

    flags = buf[0]
    offset = 1

    if flags & _FLAG_HR_UINT16:
        if len(buf) < offset + 2:
            raise ValueError("2A37 flags 宣告 uint16 BPM 但 payload 不足")
        bpm = int.from_bytes(buf[offset:offset + 2], "little")
        offset += 2
    else:
        bpm = buf[offset]
        offset += 1

    contact_supported = bool(flags & _FLAG_CONTACT_SUPPORTED)
    contact_detected = contact_supported and bool(flags & _FLAG_CONTACT_DETECTED)

    energy: int | None = None
    if flags & _FLAG_ENERGY_PRESENT:
        if len(buf) < offset + 2:
            raise ValueError("2A37 flags 宣告 Energy Expended 但 payload 不足")
        energy = int.from_bytes(buf[offset:offset + 2], "little")
        offset += 2

    rrs: list[float] = []
    if flags & _FLAG_RR_PRESENT:
        while offset + 2 <= len(buf):
            raw = int.from_bytes(buf[offset:offset + 2], "little")
            offset += 2
            rr_ms = raw * 1000.0 / 1024.0
            if _RR_MIN_MS <= rr_ms <= _RR_MAX_MS:
                rrs.append(rr_ms)
        if offset != len(buf):
            logger.debug("2A37 payload 末端有 %d byte 無法組成 RR-Interval，忽略", len(buf) - offset)

    return HeartRateMeasurement(
        bpm=int(bpm),
        sensor_contact_supported=contact_supported,
        sensor_contact_detected=contact_detected,
        energy_expended_kj=energy,
        rr_intervals_ms=tuple(rrs),
        flags=flags,
    )


def parse_battery_level(data: bytes | bytearray | memoryview) -> int | None:
    """解析 ``0x2A19`` Battery Level（0-100）；格式不符時回傳 ``None``。"""
    buf = bytes(data)
    if not buf:
        return None
    level = buf[0]
    if 0 <= level <= 100:
        return int(level)
    return None


def body_sensor_location_label(data: bytes | bytearray | memoryview) -> str:
    """解析 ``0x2A38`` Body Sensor Location 並回傳標籤字串。"""
    buf = bytes(data)
    if not buf:
        return ""
    return BODY_SENSOR_LOCATION_LABELS.get(buf[0], f"Reserved({buf[0]})")


def measurement_to_watch_sample(
    measurement: HeartRateMeasurement,
    received_at: float | None = None,
) -> WatchSample | None:
    """把一筆心跳帶量測轉成 watch pillar 相容的 :class:`WatchSample`。

    BPM ≤ 0（例如接觸不良時部分裝置回報 0）回傳 ``None``，不進 hub。
    ``interval_ms`` 優先取 RR 總和（= 本筆 notification 覆蓋的實際時間），
    否則使用 HRS 常見的 1 Hz 週期假設。
    """
    if measurement.bpm <= 0:
        return None
    now = time.time() if received_at is None else float(received_at)
    if measurement.rr_intervals_ms:
        interval_ms = max(100, int(round(sum(measurement.rr_intervals_ms))))
    else:
        interval_ms = 1000
    return WatchSample(
        received_at=now,
        bpm=int(measurement.bpm),
        ts_ms=int(now * 1000),
        interval_ms=interval_ms,
        rr_intervals_ms=measurement.rr_intervals_ms or None,
    )


def pick_heart_rate_device(
    candidates: Iterable[tuple[Any, Any]],
    *,
    name_prefix: str = DEFAULT_NAME_PREFIX,
    address: str = "",
) -> Any | None:
    """從掃描結果 ``(BLEDevice, AdvertisementData)`` 中挑選目標心跳帶。

    優先序：指定 address 完全相符 > 名稱前綴相符（RSSI 高者優先）>
    廣播 Heart Rate Service 的裝置（RSSI 高者優先）。
    純函式：不依賴 bleak 型別，僅使用 duck typing，方便單元測試。
    """
    addr_want = address.strip().lower()
    prefix = (name_prefix or "").strip().lower()

    named: list[tuple[float, Any]] = []
    hrs_adv: list[tuple[float, Any]] = []
    for device, adv in candidates:
        dev_addr = str(getattr(device, "address", "") or "").lower()
        if addr_want and dev_addr == addr_want:
            return device
        name = str(getattr(device, "name", "") or getattr(adv, "local_name", "") or "")
        rssi = float(getattr(adv, "rssi", -127) or -127)
        if prefix and name.lower().startswith(prefix):
            named.append((rssi, device))
            continue
        service_uuids = [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]
        if HEART_RATE_SERVICE_UUID in service_uuids:
            hrs_adv.append((rssi, device))

    if addr_want:
        return None
    for pool in (named, hrs_adv):
        if pool:
            pool.sort(key=lambda item: item[0], reverse=True)
            return pool[0][1]
    return None


@dataclass(frozen=True)
class HrBeltStatus:
    """心跳帶連線狀態快照（GUI 以輪詢方式讀取，跨執行緒安全）。"""

    state: str = "idle"  # idle/scanning/connecting/connected/reconnecting/error/stopped
    device_name: str = ""
    device_address: str = ""
    rssi: float = 0.0
    battery_level: int | None = None
    sensor_location: str = ""
    bpm: int = 0
    rr_count: int = 0
    sensor_contact_supported: bool = False
    sensor_contact_detected: bool = False
    notifications: int = 0
    last_error: str = ""
    connected_since: float | None = None
    updated_at: float = field(default_factory=time.time)


class HrBeltBleClient:
    """背景執行緒中以 bleak 連線心跳帶，將 BPM/RR 樣本推入 hub。

    生命週期：``start()`` 啟動 → 內部 asyncio 迴圈負責
    掃描 → 連線 → 訂閱 ``2A37``（含電量/配戴位置 best-effort 讀取）→
    斷線後自動重連 → ``stop()`` 結束。
    """

    def __init__(
        self,
        hub: WatchHrHub,
        *,
        name_prefix: str = DEFAULT_NAME_PREFIX,
        address: str = "",
        scan_timeout: float = 6.0,
        reconnect_delay: float = 3.0,
        on_sample: Callable[[WatchSample], None] | None = None,
    ) -> None:
        self._hub = hub
        self._name_prefix = name_prefix
        self._address = address
        self._scan_timeout = float(scan_timeout)
        self._reconnect_delay = float(reconnect_delay)
        self._on_sample = on_sample

        self._lock = threading.Lock()
        self._status = HrBeltStatus()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_stop: asyncio.Event | None = None
        self._main_task: "asyncio.Task[None] | None" = None

    # ── 對外 API（GUI 執行緒呼叫）────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> HrBeltStatus:
        with self._lock:
            return self._status

    def start(self) -> str:
        """啟動背景連線執行緒；成功回傳空字串，失敗回傳錯誤訊息。"""
        try:
            import bleak  # noqa: F401  (僅檢查依賴存在)
        except ImportError:
            msg = "未安裝 bleak 套件，請執行 pip install bleak"
            logger.error(msg)
            return msg
        if self.running:
            return ""
        self._stop_event.clear()
        self._set_status(state="scanning", last_error="")
        self._thread = threading.Thread(target=self._run, name="HrBeltBle", daemon=True)
        self._thread.start()
        return ""

    def stop(self, join_timeout: float = 5.0) -> None:
        """停止背景連線執行緒。

        直接取消 asyncio 主任務：取消會中斷卡在 discover/connect 的
        await，`async with BleakClient` 的 ``__aexit__`` 仍會執行 GATT
        斷線收尾，因此典型停止時間 < 1 秒；join 逾時時不誤報 stopped，
        且 notification handler 會因 stop 旗標拒絕再寫入 hub。
        """
        self._stop_event.set()
        loop = self._loop
        stop_evt = self._async_stop
        task = self._main_task
        if loop is not None and loop.is_running():
            try:
                if stop_evt is not None:
                    loop.call_soon_threadsafe(stop_evt.set)
                if task is not None:
                    loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning("HrBeltBle 執行緒未能在 %.1fs 內結束，背景仍在收尾", join_timeout)
                self._set_status(
                    state="stopping",
                    connected_since=None,
                    last_error="停止逾時，背景執行緒仍在收尾（已拒絕新樣本寫入）",
                )
                return
        self._set_status(state="stopped", connected_since=None)

    # ── 內部：狀態管理 ───────────────────────────────────────────────────────

    def _set_status(self, **changes: Any) -> None:
        with self._lock:
            self._status = replace(self._status, updated_at=time.time(), **changes)

    # ── 內部：執行緒 / asyncio 主體 ─────────────────────────────────────────

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._main_task = loop.create_task(self._main())
            loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            logger.info("HrBeltBle 主任務已取消（stop 逼停）")
        except Exception as exc:  # pragma: no cover - 防禦性
            logger.exception("HrBeltBle 主迴圈異常結束")
            self._set_status(state="error", last_error=str(exc))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()
            self._loop = None
            self._async_stop = None
            self._main_task = None

    async def _wait_stop(self, timeout: float) -> bool:
        """等待 stop 訊號最多 ``timeout`` 秒；收到訊號回傳 True。"""
        assert self._async_stop is not None
        try:
            await asyncio.wait_for(self._async_stop.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return self._stop_event.is_set()

    async def _main(self) -> None:
        from bleak import BleakClient, BleakScanner

        self._async_stop = asyncio.Event()
        if self._stop_event.is_set():
            return

        while not self._stop_event.is_set():
            self._set_status(state="scanning", bpm=0, rr_count=0, connected_since=None)
            device = await self._discover(BleakScanner)
            if self._stop_event.is_set():
                break
            if device is None:
                if await self._wait_stop(self._reconnect_delay):
                    break
                continue

            name = str(getattr(device, "name", "") or "")
            addr = str(getattr(device, "address", "") or "")
            self._set_status(state="connecting", device_name=name, device_address=addr)
            logger.info("心跳帶連線中：%s (%s)", name or "unknown", addr)

            disconnected = asyncio.Event()

            def _on_disconnect(_client: Any) -> None:
                disconnected.set()

            try:
                async with BleakClient(
                    device,
                    disconnected_callback=_on_disconnect,
                    timeout=15.0,
                ) as client:
                    await self._prime_connection(client)
                    self._set_status(state="connected", connected_since=time.time(), last_error="")
                    logger.info("心跳帶已連線並訂閱 2A37：%s", name or addr)
                    # disconnected 於 while 條件重新檢查，這裡只需以 1s 節奏
                    # 等待 stop 訊號即可。
                    while not self._stop_event.is_set() and not disconnected.is_set():
                        try:
                            await asyncio.wait_for(self._async_stop.wait(), timeout=1.0)
                            break
                        except asyncio.TimeoutError:
                            continue
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("心跳帶連線失敗或中斷：%s", exc)
                self._set_status(state="error", last_error=str(exc), connected_since=None)

            if self._stop_event.is_set():
                break
            self._set_status(state="reconnecting", connected_since=None)
            logger.info("心跳帶斷線，%.1fs 後重新掃描", self._reconnect_delay)
            if await self._wait_stop(self._reconnect_delay):
                break

    async def _discover(self, scanner_cls: Any) -> Any | None:
        """掃描並挑選目標裝置；掃不到回傳 None。

        指定 address 時不套 service UUID 過濾：部分裝置的廣播封包
        不含 0x180D，OS 層過濾會讓 address 精確比對永遠掃不到目標。
        """
        scan_kwargs: dict[str, Any] = {
            "timeout": self._scan_timeout,
            "return_adv": True,
        }
        if not self._address.strip():
            scan_kwargs["service_uuids"] = [HEART_RATE_SERVICE_UUID]
        try:
            found = await scanner_cls.discover(**scan_kwargs)
        except Exception as exc:
            logger.warning("BLE 掃描失敗：%s", exc)
            self._set_status(state="error", last_error=str(exc))
            return None
        device = pick_heart_rate_device(
            found.values(),
            name_prefix=self._name_prefix,
            address=self._address,
        )
        if device is None:
            logger.debug("掃描完成，未找到符合的心跳帶（%d 個候選）", len(found))
            return None
        for dev, adv in found.values():
            if dev is device:
                self._set_status(rssi=float(getattr(adv, "rssi", 0) or 0))
                break
        return device

    async def _prime_connection(self, client: Any) -> None:
        """連線後初始化：best-effort 讀取配戴位置/電量，訂閱 2A37 與 2A19。"""
        try:
            raw = await asyncio.wait_for(client.read_gatt_char(BODY_SENSOR_LOCATION_UUID), timeout=4.0)
            self._set_status(sensor_location=body_sensor_location_label(raw))
        except Exception as exc:
            logger.debug("讀取 Body Sensor Location 失敗（忽略）：%s", exc)

        try:
            raw = await asyncio.wait_for(client.read_gatt_char(BATTERY_LEVEL_UUID), timeout=4.0)
            self._set_status(battery_level=parse_battery_level(raw))
        except Exception as exc:
            logger.debug("讀取 Battery Level 失敗（忽略）：%s", exc)

        try:
            await asyncio.wait_for(
                client.start_notify(BATTERY_LEVEL_UUID, self._on_battery_notification),
                timeout=4.0,
            )
        except Exception as exc:
            logger.debug("訂閱 Battery Level notification 失敗（忽略）：%s", exc)

        # 心率 notification 為必要功能，失敗或逾時直接拋出讓外層重連。
        await asyncio.wait_for(
            client.start_notify(HEART_RATE_MEASUREMENT_UUID, self._on_hr_notification),
            timeout=8.0,
        )

    # ── 內部：notification handlers（asyncio 執行緒呼叫）────────────────────

    def _on_hr_notification(self, _characteristic: Any, data: bytearray) -> None:
        if self._stop_event.is_set():
            # stop() 之後不再寫入共用 hub，避免孤兒執行緒污染下一個來源。
            return
        try:
            measurement = parse_heart_rate_measurement(data)
        except ValueError as exc:
            logger.debug("2A37 payload 解析失敗：%s", exc)
            return
        sample = measurement_to_watch_sample(measurement)
        with self._lock:
            self._status = replace(
                self._status,
                updated_at=time.time(),
                bpm=measurement.bpm,
                rr_count=len(measurement.rr_intervals_ms),
                sensor_contact_supported=measurement.sensor_contact_supported,
                sensor_contact_detected=measurement.sensor_contact_detected,
                notifications=self._status.notifications + 1,
            )
        if sample is None:
            return
        self._hub.add(sample)
        if self._on_sample is not None:
            try:
                self._on_sample(sample)
            except Exception:
                logger.debug("on_sample callback 失敗", exc_info=True)

    def _on_battery_notification(self, _characteristic: Any, data: bytearray) -> None:
        if self._stop_event.is_set():
            return
        level = parse_battery_level(data)
        if level is not None:
            self._set_status(battery_level=level)


__all__ = [
    "BATTERY_LEVEL_UUID",
    "BATTERY_SERVICE_UUID",
    "BODY_SENSOR_LOCATION_LABELS",
    "BODY_SENSOR_LOCATION_UUID",
    "DEFAULT_NAME_PREFIX",
    "HEART_RATE_MEASUREMENT_UUID",
    "HEART_RATE_SERVICE_UUID",
    "HeartRateMeasurement",
    "HrBeltBleClient",
    "HrBeltStatus",
    "body_sensor_location_label",
    "measurement_to_watch_sample",
    "parse_battery_level",
    "parse_heart_rate_measurement",
    "pick_heart_rate_device",
]
