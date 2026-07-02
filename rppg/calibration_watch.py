"""心率參考樣本容器：BLE 心跳帶樣本的執行緒安全 hub 與樣本型別。

原本亦內含手錶 HTTP 接收器（watch mode），該模式已移除；此檔現只保留
:class:`WatchSample` 與 :class:`WatchHrHub`——它們是心跳帶校準與「未來 HRV 比對」
的共用資料結構（`HrBeltBleClient` 把 `2A37` 量測轉成 `WatchSample` 推入 hub，
下游 `rppg/watch_physio.py` 可由 hub 樣本計算 HRV）。
"""

from __future__ import annotations

import threading
import time


class WatchSample:
    __slots__ = (
        "received_at",
        "bpm",
        "ts_ms",
        "interval_ms",
        "ax",
        "ay",
        "az",
        "motion_level",
        "rr_intervals_ms",
    )

    def __init__(
        self,
        received_at: float,
        bpm: int,
        ts_ms: int,
        interval_ms: int,
        ax: float | None = None,
        ay: float | None = None,
        az: float | None = None,
        motion_level: float | None = None,
        rr_intervals_ms: "tuple[float, ...] | list[float] | None" = None,
    ) -> None:
        self.received_at = received_at
        self.bpm = int(bpm)
        self.ts_ms = int(ts_ms)
        self.interval_ms = int(interval_ms)
        self.ax = float(ax) if ax is not None else None
        self.ay = float(ay) if ay is not None else None
        self.az = float(az) if az is not None else None
        self.motion_level = float(motion_level) if motion_level is not None else None
        # BLE 心跳帶（2A37）可回報實測 RR-Interval（ms）；無 RR 時為 None。
        self.rr_intervals_ms = tuple(float(rr) for rr in rr_intervals_ms) if rr_intervals_ms else None

    @property
    def has_imu(self) -> bool:
        return self.motion_level is not None

    @property
    def has_rr(self) -> bool:
        return bool(self.rr_intervals_ms)


class WatchHrHub:
    """Thread-safe store for heart-rate reference samples (BLE belt)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[WatchSample] = []
        self._last: WatchSample | None = None
        self.total_received: int = 0

    def add(self, sample: WatchSample) -> None:
        with self._lock:
            self._samples.append(sample)
            self._last = sample
            self.total_received += 1

    def latest(self) -> WatchSample | None:
        with self._lock:
            return self._last

    def snapshot(self) -> list[WatchSample]:
        with self._lock:
            return list(self._samples)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._last = None
            self.total_received = 0

    def is_connected(self, stale_multiplier: float = 6.0) -> bool:
        last = self.latest()
        if last is None:
            return False
        interval_sec = max(0.5, last.interval_ms / 1000.0)
        return (time.time() - last.received_at) <= interval_sec * stale_multiplier
