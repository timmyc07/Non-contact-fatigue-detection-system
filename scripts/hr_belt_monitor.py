"""BLE 心跳帶免 GUI 診斷工具：掃描 → 連線 → 即時列印 BPM / RR / 電量 / 狀態。

用途：驗證心跳帶硬體與 BLE 環境（bleak / WinRT / BlueZ）是否正常，
不需啟動完整桌面 GUI。與 GUI「心跳帶模式」共用 ``HrBeltBleClient``，
此處能連線代表 GUI 也能連線。

範例：

    # 預設掃描名稱前綴 R+ 或任何廣播 Heart Rate Service 的裝置
    .venv\\Scripts\\python -m scripts.hr_belt_monitor

    # 指定裝置位址、監看 60 秒後自動結束
    .venv\\Scripts\\python -m scripts.hr_belt_monitor --address C1:3B:74:B8:F7:40 --duration 60

    # 使用 config/hr_belt.json 的設定（與 GUI 相同）
    .venv\\Scripts\\python -m scripts.hr_belt_monitor --use-config
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rppg.calibration_watch import WatchHrHub, WatchSample  # noqa: E402
from rppg.hr_belt_ble import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    HrBeltBleClient,
    HrBeltConfig,
    hr_is_stale,
    load_hr_belt_config,
)

_STATE_LABELS = {
    "idle": "待命",
    "scanning": "掃描中",
    "connecting": "連線中",
    "connected": "已連線",
    "reconnecting": "斷線重連中",
    "error": "錯誤",
    "stopping": "停止中",
    "stopped": "已停止",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BLE 心跳帶連線診斷（Heart Rate Service 0x180D / 0x2A37）",
    )
    parser.add_argument("--name-prefix", default=None, help="裝置名稱前綴（預設 R+）")
    parser.add_argument("--address", default=None, help="裝置 BLE 位址；指定時跳過名稱比對")
    parser.add_argument("--scan-timeout", type=float, default=None, help="單次掃描秒數（預設 6）")
    parser.add_argument("--reconnect-delay", type=float, default=None, help="斷線重試間隔秒數（預設 3）")
    parser.add_argument(
        "--duration", type=float, default=0.0,
        help="監看秒數；0 表示持續執行直到 Ctrl+C（預設 0）",
    )
    parser.add_argument(
        "--use-config", action="store_true",
        help=f"讀取 {DEFAULT_CONFIG_PATH.name} 作為基底設定（命令列參數優先）",
    )
    parser.add_argument("--verbose", action="store_true", help="輸出 bleak / 模組 debug log")
    return parser.parse_args(argv)


def _resolve_config(args: argparse.Namespace) -> HrBeltConfig:
    base = load_hr_belt_config() if args.use_config else HrBeltConfig()
    return HrBeltConfig(
        name_prefix=base.name_prefix if args.name_prefix is None else args.name_prefix,
        address=base.address if args.address is None else args.address,
        scan_timeout_sec=base.scan_timeout_sec if args.scan_timeout is None else args.scan_timeout,
        reconnect_delay_sec=(
            base.reconnect_delay_sec if args.reconnect_delay is None else args.reconnect_delay
        ),
    )


def _print_sample(sample: WatchSample) -> None:
    stamp = time.strftime("%H:%M:%S", time.localtime(sample.received_at))
    rr_text = (
        " RR=" + "/".join(f"{rr:.0f}ms" for rr in sample.rr_intervals_ms)
        if sample.rr_intervals_ms else ""
    )
    print(f"[{stamp}] {sample.bpm:3d} BPM{rr_text}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")

    cfg = _resolve_config(args)
    target = (
        f"位址 {cfg.address}" if cfg.address
        else f"名稱前綴「{cfg.name_prefix}」" if cfg.name_prefix
        else "任何 Heart Rate Service 裝置"
    )
    print(f"掃描目標：{target}（掃描 {cfg.scan_timeout_sec:.0f}s / 重試間隔 {cfg.reconnect_delay_sec:.0f}s）")
    print("按 Ctrl+C 結束。")

    hub = WatchHrHub()
    client = HrBeltBleClient(
        hub,
        name_prefix=cfg.name_prefix,
        address=cfg.address,
        scan_timeout=cfg.scan_timeout_sec,
        reconnect_delay=cfg.reconnect_delay_sec,
        on_sample=_print_sample,
    )
    err = client.start()
    if err:
        print(f"啟動失敗：{err}", file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    last_state = ""
    last_battery: int | None = None
    stale_warned = False
    exit_code = 0
    try:
        while deadline is None or time.monotonic() < deadline:
            time.sleep(1.0)
            st = client.status()
            if st.state != last_state:
                label = _STATE_LABELS.get(st.state, st.state)
                detail = ""
                if st.state == "connected":
                    name = st.device_name or st.device_address or "未知裝置"
                    detail = f"：{name}"
                    if st.sensor_location:
                        detail += f"（{st.sensor_location}）"
                elif st.state == "error" and st.last_error:
                    detail = f"：{st.last_error}"
                print(f"—— {label}{detail}", flush=True)
                last_state = st.state
            if st.battery_level is not None and st.battery_level != last_battery:
                print(f"—— 電量 {st.battery_level}%", flush=True)
                last_battery = st.battery_level
            if st.state == "connected" and st.sensor_contact_supported and not st.sensor_contact_detected:
                print("—— ⚠ 感測器接觸不良（請確認穿戴與濕潤電極）", flush=True)
            if hr_is_stale(st):
                if not stale_warned:
                    print("—— ⚠ 連線中但無心率資料（裝置可能未正確配戴）", flush=True)
                    stale_warned = True
            else:
                stale_warned = False
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，停止中…")
    finally:
        client.stop()

    st = client.status()
    if st.notifications == 0:
        print("結束：未收到任何心率 notification。", file=sys.stderr)
        exit_code = max(exit_code, 1)
    else:
        print(f"結束：共收到 {st.notifications} 筆 notification，最後 BPM={st.bpm}。")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
