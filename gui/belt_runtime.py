"""Background BLE heart-rate belt runtime for rPPG truth calibration.

擁有心率參考 hub 與 BLE 心跳帶背景連線。心跳帶樣本推入 :class:`WatchHrHub`，
供 rPPG 真值校準（讀 ``belt_status()``）與未來 HRV 比對（讀 hub 樣本）使用。
原手錶 HTTP 來源已移除。
"""

from __future__ import annotations

import logging

from rppg.calibration_watch import WatchHrHub
from rppg.hr_belt_ble import HrBeltBleClient, HrBeltConfig, HrBeltStatus

logger = logging.getLogger(__name__)


class BeltRuntime:
    """Owns the HR-reference hub + BLE belt client used for rPPG calibration.

    心跳帶樣本沉澱在同一個 :class:`WatchHrHub`；校準讀 ``belt_status()``，
    HRV 接口（未來）讀 ``hub`` 樣本。切換用途時由呼叫端負責 ``hub.clear()``。
    """

    def __init__(self) -> None:
        self.hub = WatchHrHub()
        self._belt: HrBeltBleClient | None = None

    @property
    def belt_running(self) -> bool:
        return self._belt is not None and self._belt.running

    def start_belt(self, config: HrBeltConfig | None = None) -> str:
        """啟動 BLE 心跳帶背景連線；成功回傳空字串，失敗回傳錯誤訊息。"""
        if self.belt_running:
            return ""
        if self._belt is not None:
            self._belt.stop()
        cfg = config if config is not None else HrBeltConfig()
        self._belt = HrBeltBleClient(
            self.hub,
            name_prefix=cfg.name_prefix,
            address=cfg.address,
            scan_timeout=cfg.scan_timeout_sec,
            reconnect_delay=cfg.reconnect_delay_sec,
        )
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
