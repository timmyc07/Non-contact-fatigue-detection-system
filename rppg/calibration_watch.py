"""心率參考樣本容器：BLE 心跳帶樣本的執行緒安全 hub 與樣本型別。

原本亦內含手錶 HTTP 接收器（watch mode），該模式已移除；此檔現只保留
:class:`WatchSample` 與 :class:`WatchHrHub`。`HrBeltBleClient` 把 `2A37` 量測
轉成 `WatchSample` 推入 hub，下游 `rppg/watch_physio.py` 使用最近 90 秒計算 HRV。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque


logger = logging.getLogger(__name__)
WATCH_PHYSIO_WINDOW_SEC = 90.0
# 90 秒可容納超過 111 Hz 的通知；凍結時鐘或異常高頻仍不得無界累積。
WATCH_HUB_MAX_SAMPLES = 10_000


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
    """執行緒安全的 [now-90, now] 心率歷史，維持原本通知到達順序。

    latest/total_received 仍代表最後通知及 clear 後累計，不受歷史過期影響。
    未來或非有限時間不進 HRV 歷史；時鐘倒退只保留現存有效交集並警告覆蓋不足。
    超過 10000 筆時保留最新到達的通知並警告，不宣稱異常過量時仍具完整數值等價性。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: deque[WatchSample] = deque(maxlen=WATCH_HUB_MAX_SAMPLES)
        self._last: WatchSample | None = None
        self.total_received: int = 0
        self._time_ordered = True
        self._last_clock: float | None = None
        self._overflow_count = 0

    def _prune(self, now: float) -> None:
        clock_reversed = self._last_clock is not None and now < self._last_clock
        if clock_reversed:
            logger.warning("心率系統時間倒退；保留現存有效樣本，90 秒歷史覆蓋可能不足")
        self._last_clock = now
        if clock_reversed or not self._time_ordered:
            retained: deque[WatchSample] = deque(maxlen=WATCH_HUB_MAX_SAMPLES)
            self._time_ordered = True
            for sample in self._samples:
                if 0.0 <= now - sample.received_at <= WATCH_PHYSIO_WINDOW_SEC:
                    if retained and sample.received_at < retained[-1].received_at:
                        self._time_ordered = False
                    retained.append(sample)
            self._samples = retained
        else:
            while self._samples and now - self._samples[0].received_at > WATCH_PHYSIO_WINDOW_SEC:
                self._samples.popleft()

    def add(self, sample: WatchSample) -> None:
        with self._lock:
            now = time.time()
            self._prune(now)
            self._last = sample
            self.total_received += 1
            age = now - sample.received_at
            if not math.isfinite(age) or age < 0.0:
                logger.warning("心率通知含未來或非有限時間，不納入 HRV 歷史：%r", sample.received_at)
                return
            if age > WATCH_PHYSIO_WINDOW_SEC:
                return
            if len(self._samples) == WATCH_HUB_MAX_SAMPLES:
                self._overflow_count += 1
                if self._overflow_count == 1 or self._overflow_count % 1000 == 0:
                    logger.warning(
                        "心率歷史超過 %d 筆，只保留最新到達通知（已捨棄 %d 筆）",
                        WATCH_HUB_MAX_SAMPLES, self._overflow_count,
                    )
            if self._samples and sample.received_at < self._samples[-1].received_at:
                self._time_ordered = False
            self._samples.append(sample)

    def latest(self) -> WatchSample | None:
        with self._lock:
            return self._last

    def snapshot(self) -> list[WatchSample]:
        with self._lock:
            self._prune(time.time())
            return list(self._samples)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._last = None
            self.total_received = 0
            self._time_ordered = True
            self._last_clock = None
            self._overflow_count = 0

    def is_connected(self, stale_multiplier: float = 6.0) -> bool:
        last = self.latest()
        if last is None:
            return False
        interval_sec = max(0.5, last.interval_ms / 1000.0)
        return 0.0 <= time.time() - last.received_at <= interval_sec * stale_multiplier
