"""Background watch HTTP receiver / BLE heart-rate belt for watch fatigue mode."""

from __future__ import annotations

import logging
from typing import Callable

from rppg.calibration_watch import WatchHrHub, WatchHrHttpServer
from rppg.hr_belt_ble import DEFAULT_NAME_PREFIX, HrBeltBleClient, HrBeltStatus
from rppg.rppg_worker import RppgMetrics
from rppg.watch_adapter import build_watch_rppg_metrics
from rppg.watch_metrics import WatchMetrics, metrics_from_hub

logger = logging.getLogger(__name__)


class WatchRuntime:
    """Owns hub + HTTP server / BLE belt client used in watch/belt fatigue mode.

    兩種來源共用同一個 :class:`WatchHrHub`，下游 physio / fusion / dashboard
    路徑完全一致；切換來源時由呼叫端負責 ``hub.clear()`` 避免混樣。
    """

    DEFAULT_PORT = 8080

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.hub = WatchHrHub()
        self._http = WatchHrHttpServer(self.hub, port=int(port))
        self.port = int(port)
        self._belt: HrBeltBleClient | None = None

    # ── HTTP 手錶來源 ─────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._http.running

    def start(self) -> str:
        if self.running:
            return ""
        try:
            self._http.start()
            return ""
        except OSError as exc:
            return str(exc)

    def stop(self) -> None:
        self._http.stop()

    # ── BLE 心跳帶來源 ────────────────────────────────────────────────────────

    @property
    def belt_running(self) -> bool:
        return self._belt is not None and self._belt.running

    def start_belt(
        self,
        name_prefix: str = DEFAULT_NAME_PREFIX,
        address: str = "",
    ) -> str:
        """啟動 BLE 心跳帶背景連線；成功回傳空字串，失敗回傳錯誤訊息。"""
        if self.belt_running:
            return ""
        if self._belt is not None:
            self._belt.stop()
        self._belt = HrBeltBleClient(self.hub, name_prefix=name_prefix, address=address)
        err = self._belt.start()
        if err:
            logger.error("心跳帶 BLE 啟動失敗：%s", err)
            self._belt = None
        return err

    def stop_belt(self) -> None:
        if self._belt is None:
            return
        self._belt.stop()
        self._belt = None

    def belt_status(self) -> HrBeltStatus | None:
        if self._belt is None:
            return None
        return self._belt.status()

    # ── 共用輸出 ─────────────────────────────────────────────────────────────

    def latest_metrics(self) -> WatchMetrics:
        return metrics_from_hub(self.hub)

    def latest_rppg_metrics(
        self,
        calibration_loader: Callable[[], object] | None = None,
    ) -> RppgMetrics:
        version = None
        if calibration_loader is not None:
            try:
                version = calibration_loader()
            except Exception:
                version = None
        return build_watch_rppg_metrics(self.hub, calibration_version=version)
