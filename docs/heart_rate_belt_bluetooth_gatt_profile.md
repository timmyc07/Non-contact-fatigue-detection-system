# R+2.0 2248 心跳帶 BLE GATT 資訊整理

整理日期：2026-07-02
資料來源：`C:\Users\USER\Desktop\專題書面\r20_bt.pdf`（僅為內部資料來源標記，非程式引用路徑）。
PDF 型態：影像型 PDF，共 8 頁，無可抽取文字；本文件依 8 倍渲染後的頁面圖逐段讀取整理。
用途：作為心跳帶接入本專案 watch/HR 參考來源的 GATT 對照文件。

## 實作狀態（2026-07-02）

本文件描述的整合已實作於：

- `rppg/hr_belt_ble.py` — `2A37` payload 解析（flags / uint8 / uint16 / Energy Expended / RR-Interval）、`2A19` 電量、`2A38` 配戴位置解析，與 `HrBeltBleClient`（bleak 掃描 → 連線 → 訂閱 → 自動重連）。
- `gui/watch_runtime.py` + `gui/main_window.py` — GUI「心跳帶模式」，樣本推入 `WatchHrHub` 沿用 watch pillar 融合與 Web dashboard 可視化。
- `tests/test_hr_belt_ble.py` — 協定邊界案例、裝置挑選、hub 整合與 client 生命週期單元測試。

整合僅使用標準 Heart Rate Service 路徑；`FE59` 與 `fce6xxxx` vendor-specific service 依本文件建議**不讀不寫**。

## 裝置概況

| 欄位 | PDF 顯示資訊 | 備註 |
| --- | --- | --- |
| Device Name | `R+2.0 2248` | Chrome Bluetooth Internals 頁面標題與 Status 區顯示。 |
| BLE Address | `C1:3B:74:B8:F7:40` | BLE address 可能是隨機位址，正式整合時不建議只依賴此值綁定裝置。 |
| GATT 狀態 | `Connected` | PDF 擷取時已連線。 |
| Latest RSSI | `-60 dBm` | 中等訊號強度；實測整合時仍需處理斷線與訊號波動。 |
| Manufacturer Data | 空白 | PDF 未顯示 manufacturer data。 |

## Services 總覽

| Service UUID | 標準名稱 / 推定用途 | PDF 讀到的 characteristic | 整合重點 |
| --- | --- | --- | --- |
| `00001800-0000-1000-8000-00805f9b34fb` | Generic Access | `2A00`, `2A01`, `2A04`, `2AA6` | 裝置名稱、外觀、連線參數與 address resolution。 |
| `00001801-0000-1000-8000-00805f9b34fb` | Generic Attribute | PDF 顯示 `No Characteristics Found` | 此 PDF 未看到 Service Changed characteristic。 |
| `0000180a-0000-1000-8000-00805f9b34fb` | Device Information | `2A24`, `2A25`, `2A26`, `2A28`, `2A29` | 型號、序號、韌體、軟體、製造商字串。 |
| `0000180d-0000-1000-8000-00805f9b34fb` | Heart Rate | `2A37`, `2A38` | 主要心率資料來源，訂閱 `2A37` notification。 |
| `0000180f-0000-1000-8000-00805f9b34fb` | Battery Service | `2A19` | 可讀取/訂閱電量。 |
| `0000fe59-0000-1000-8000-00805f9b34fb` | Nordic Semiconductor assigned service | `8EC90003-F315-4F60-9FB8-838830DAEA50` | 推定為 Nordic DFU/Buttonless DFU 類 service；一般心率整合不應寫入。 |
| `fce61000-7802-4392-b6b7-96b18deaad22` | Vendor-specific custom service | `fce61002`, `fce61003` | 兩個 Write + Notify 自訂通道；payload 未知。 |
| `fce64000-7802-4392-b6b7-96b18deaad22` | Vendor-specific custom service | `fce64001` 到 `fce64016` 的多個 Read + Notify 通道 | 自訂資料/狀態通道；payload 未知。 |

## Characteristic 明細

### Generic Access Service `1800`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | PDF Value 狀態 |
| --- | --- | --- | --- | --- |
| `00002a00-0000-1000-8000-00805f9b34fb` | Device Name | Read, Write | 無 | PDF 未顯示實際 value；Status 顯示名稱為 `R+2.0 2248`。 |
| `00002a01-0000-1000-8000-00805f9b34fb` | Appearance | Read | 無 | PDF 未顯示 value。 |
| `00002a04-0000-1000-8000-00805f9b34fb` | Peripheral Preferred Connection Parameters | Read | 無 | PDF 未顯示 value。 |
| `00002aa6-0000-1000-8000-00805f9b34fb` | Central Address Resolution | Read | 無 | PDF 未顯示 value。 |

### Generic Attribute Service `1801`

PDF 末頁顯示：

| Service UUID | 結果 |
| --- | --- |
| `00001801-0000-1000-8000-00805f9b34fb` | `No Characteristics Found` |

### Device Information Service `180A`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | PDF Value 狀態 |
| --- | --- | --- | --- | --- |
| `00002a24-0000-1000-8000-00805f9b34fb` | Model Number String | Read | 無 | PDF 未顯示 value。 |
| `00002a25-0000-1000-8000-00805f9b34fb` | Serial Number String | Read | 無 | PDF 未顯示 value。 |
| `00002a26-0000-1000-8000-00805f9b34fb` | Firmware Revision String | Read | 無 | PDF 未顯示 value。 |
| `00002a28-0000-1000-8000-00805f9b34fb` | Software Revision String | Read | 無 | PDF 未顯示 value。 |
| `00002a29-0000-1000-8000-00805f9b34fb` | Manufacturer Name String | Read | 無 | PDF 未顯示 value。 |

### Heart Rate Service `180D`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | PDF Value 狀態 |
| --- | --- | --- | --- | --- |
| `00002a37-0000-1000-8000-00805f9b34fb` | Heart Rate Measurement | Notify | `00002902-0000-1000-8000-00805f9b34fb` | PDF 顯示 `Value cannot be read or written`；需透過 notification 收資料。 |
| `00002a38-0000-1000-8000-00805f9b34fb` | Body Sensor Location | Read | 無 | PDF 未顯示 value。 |

#### `2A37` Heart Rate Measurement payload 解讀

`2A37` 是 notification 型 characteristic。收到的 bytes 依 Heart Rate Service 規格解析：

| 欄位 | 說明 |
| --- | --- |
| Byte 0 | Flags。 |
| Flags bit 0 | Heart Rate Value Format。`0` 表示心率為 `uint8`，`1` 表示心率為 little-endian `uint16`。 |
| Flags bit 1 | Sensor Contact Status。搭配 bit 2 判斷是否偵測到皮膚接觸。 |
| Flags bit 2 | Sensor Contact Feature Support。表示裝置是否支援 contact detection。 |
| Flags bit 3 | Energy Expended 欄位是否存在；若存在，為 little-endian `uint16`。 |
| Flags bit 4 | RR-Interval 欄位是否存在；若存在，後續可有多組 little-endian `uint16`，單位為 `1/1024` 秒。 |

實機 notification 實測（2026-07-03，R+2.0 2248，Windows 11 + bleak/WinRT，抓取原始 payload 40 筆）：

- payload 固定 2 bytes：`flags=0x06`（bit1+bit2：支援且偵測到皮膚接觸）+ `uint8` BPM，例如 `06 4E` = 78 BPM。
- **未帶 RR-Interval**（bit 4 恆為 0）、無 Energy Expended；HRV 因此走 60000/BPM 反推路徑（`rppg/watch_physio.py`），與手錶模式一致。
- notification 頻率約 2 Hz（同一 BPM 值連續重複約 2 筆）。
- Body Sensor Location `2A38` 實測回報 `Wrist`（韌體標示與實際胸帶配戴不符，僅供顯示參考）。
- Battery Level `2A19` 可正常讀取（實測 91%）。

整合此心跳帶時，最小可用流程是：

1. 掃描或連線到裝置。
2. 找到 Heart Rate Service `0000180d-0000-1000-8000-00805f9b34fb`。
3. 訂閱 Heart Rate Measurement `00002a37-0000-1000-8000-00805f9b34fb` notification。
4. 解析 notification payload 取得 BPM，若 payload 有 RR-Interval，再換算 HRV。
5. 若需要顯示配戴位置，讀取 Body Sensor Location `00002a38-0000-1000-8000-00805f9b34fb`。

### Battery Service `180F`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | PDF Value 狀態 |
| --- | --- | --- | --- | --- |
| `00002a19-0000-1000-8000-00805f9b34fb` | Battery Level | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` | PDF 未顯示 value；可讀取或訂閱電量變化。 |

### Nordic / DFU Service `FE59`

| Characteristic UUID | 推定用途 | Properties | Descriptor | PDF Value 狀態 |
| --- | --- | --- | --- | --- |
| `8ec90003-f315-4f60-9fb8-838830daea50` | Nordic buttonless DFU 類 characteristic | Write, Indicate | `00002902-0000-1000-8000-00805f9b34fb` | PDF 未顯示 value；一般心率讀取流程不需要使用。 |

> 風險：`FE59` 與 `8ec90003` 通常和 firmware update / DFU 相關。沒有廠商文件或明確更新需求時，不要對此 characteristic 寫入資料，避免裝置進入 DFU 或更新模式。

### Vendor-specific Service `fce61000`

| Characteristic UUID | Properties | Descriptor | PDF Value 狀態 | 備註 |
| --- | --- | --- | --- | --- |
| `fce61002-7802-4392-b6b7-96b18deaad22` | Write, Notify | `00002902-0000-1000-8000-00805f9b34fb` | PDF 未顯示 value。 | 自訂通道，payload 未知。 |
| `fce61003-7802-4392-b6b7-96b18deaad22` | Write, Notify | `00002902-0000-1000-8000-00805f9b34fb` | PDF 未顯示 value。 | 自訂通道，payload 未知。 |

### Vendor-specific Service `fce64000`

PDF 顯示此 service 內有多個 Read + Notify characteristic，且每個 characteristic 都有 CCCD `00002902-0000-1000-8000-00805f9b34fb`。PDF 未顯示任何 value。

| Characteristic UUID | Properties | Descriptor |
| --- | --- | --- |
| `fce64001-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64002-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64003-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64004-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64005-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64006-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64007-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64008-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64009-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce6400a-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce6400b-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce6400c-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce6400d-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64010-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64011-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64012-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64013-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64014-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64015-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |
| `fce64016-7802-4392-b6b7-96b18deaad22` | Read, Notify | `00002902-0000-1000-8000-00805f9b34fb` |

> PDF 中可見 `fce6400d` 後下一個為 `fce64010`；本文件未列出 `fce6400e`、`fce6400f`，因 PDF 未顯示這兩個 characteristic。

## CCCD / Notification 設定

PDF 中所有 Notify 或 Indicate characteristic 都有 Client Characteristic Configuration Descriptor：

`00002902-0000-1000-8000-00805f9b34fb`

常見設定值如下：

| 目標 | 寫入 CCCD value | 備註 |
| --- | --- | --- |
| Enable Notification | `0x01 0x00` | 用於 `2A37`, `2A19`, `fce610xx`, `fce640xx` 等 Notify characteristic。 |
| Enable Indication | `0x02 0x00` | 用於 `FE59` 的 Indicate characteristic。 |
| Disable Notification/Indication | `0x00 0x00` | 取消訂閱。 |

多數 BLE library 會用 `start_notify()`、`subscribe()` 或類似 API 自動處理 CCCD，不一定需要手動寫 descriptor。

## 對本專案的整合建議

1. 以標準 Heart Rate Service `180D` 為主，不先碰 vendor-specific service。
2. 連線後優先訂閱 `2A37`，把 notification BPM 當作外部 HR 參考來源。
3. 若 `2A37` payload 帶 RR-Interval，可同步導入 HRV；若沒有 RR-Interval，只使用 BPM。
4. 可讀取或訂閱 `2A19` Battery Level，作為 UI 顯示或低電量警示來源。
5. 讀取 `2A38` 補充配戴位置，但不要把未讀到的值硬編成 Chest。
6. 避免對 `FE59` 或 `fce610xx/fce640xx` 寫入任何資料，除非已取得廠商協議或實測封包。
7. 連線識別建議同時使用 device name、Heart Rate Service 是否存在、必要時再加上 address；不要只依賴 `C1:3B:74:B8:F7:40`。

## 待補驗證清單

- [x] 讀取 `2A38` Body Sensor Location — 已由 `HrBeltBleClient._prime_connection` 於連線時 best-effort 讀取並顯示。
- [x] 讀取 `2A19` Battery Level — 已於連線時讀取並訂閱 notification，GUI 與 dashboard 顯示電量。
- [x] 訂閱 `2A37` 並解析 flags / BPM 格式 / RR-Interval — 解析器 `parse_heart_rate_measurement` 依 HRS 1.0 實作，單元測試覆蓋各 flags 組合；2026-07-03 已配戴實測：`flags=0x06` + `uint8` BPM、約 2 Hz、無 RR-Interval（詳見上方「實機 notification 實測」）。
- [ ] 若要使用自訂 service，需先收集 `fce61002/fce61003` 與 `fce640xx` notification 原始 bytes，建立協議文件（目前整合不使用）。
- [ ] 用程式重新掃描一次 GATT profile，確認 PDF 影像判讀的 `fce640xx` 清單是否與實機完全一致（不影響標準 HRS 整合）。

## 參考資料

- Bluetooth SIG Assigned Numbers: <https://www.bluetooth.com/specifications/assigned-numbers/>
- Bluetooth Heart Rate Service specification: <https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/>
- Bluetooth GATT Specification Supplement: <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement-7/>
