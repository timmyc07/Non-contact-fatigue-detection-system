# R+2.0 2248 心跳帶 BLE GATT 資訊整理

整理日期：2026-07-02  
資料來源：使用者提供的 Bluetooth/GATT 截圖（畫面疑似 Chrome `chrome://bluetooth-internals`）。  
用途：作為後續將心跳帶接入本專案 watch/HR 參考來源時的 GATT 對照文件。

## 裝置概況

| 欄位 | 截圖資訊 | 備註 |
| --- | --- | --- |
| Device Name | `R+2.0 2248` | 截圖顯示於頁面標題與狀態區。 |
| BLE Address | `C1:3B:74:B8:F7:40` | BLE address 可能是隨機位址，正式整合時不建議只依賴此值綁定裝置。 |
| GATT 狀態 | `Connected` | 截圖時已連線。 |
| Latest RSSI | `-60 dBm` | 中等訊號強度；實測整合時仍需處理斷線與訊號波動。 |
| Manufacturer Data | 空白 | 截圖未顯示 manufacturer data。 |

## 已列出的 Services

| Service UUID | 標準名稱 / 推定用途 | 截圖狀態 | 整合備註 |
| --- | --- | --- | --- |
| `00001800-0000-1000-8000-00805f9b34fb` | Generic Access | 有截到 characteristics | 提供裝置名稱、外觀、連線偏好等基本資訊。 |
| `00001801-0000-1000-8000-00805f9b34fb` | Generic Attribute | 只在 service list 中出現 | 截圖未展開；常見 characteristic 為 Service Changed。 |
| `0000180a-0000-1000-8000-00805f9b34fb` | Device Information | 有截到 characteristics | 可讀取型號、序號、韌體、軟體版本、製造商。 |
| `0000180d-0000-1000-8000-00805f9b34fb` | Heart Rate | 有截到 characteristics | 主要心率資料來源，應訂閱 `2A37` notification。 |
| `0000180f-0000-1000-8000-00805f9b34fb` | Battery Service | 只在 service list 中出現 | 截圖未展開；需再確認是否提供 Battery Level `2A19`。 |
| `0000fe59-0000-1000-8000-00805f9b34fb` | Nordic Semiconductor assigned service | 有截到 characteristic | 推定與 Nordic DFU / firmware update 有關；一般心率讀取不應寫入。 |
| `fce61000-7802-4392-b6b7-96b18deaad22` | Vendor-specific custom service | 有截到 characteristics | UUID 為裝置商自訂格式；截圖可見 write/notify 通道，但 payload 未知。 |
| `fce64000-7802-4392-b6b7-96b18deaad22` | Vendor-specific custom service | 只在 service list 中出現 | 截圖未展開，功能未知。 |

> 注意：上表中 `fce61000` 與 `fce64000` 的 UUID 來自截圖文字。若後續用程式掃描，請以實際掃描到的完整 UUID 為準，避免截圖縮放造成字元誤讀。

## Characteristic 明細

### Generic Access Service `1800`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | 備註 |
| --- | --- | --- | --- | --- |
| `00002a00-0000-1000-8000-00805f9b34fb` | Device Name | Read, Write | 無 | 目前名稱應為 `R+2.0 2248`。不建議在整合程式中寫入改名。 |
| `00002a01-0000-1000-8000-00805f9b34fb` | Appearance | Read | 無 | 可讀取裝置外觀分類；截圖未顯示 value。 |
| `00002a04-0000-1000-8000-00805f9b34fb` | Peripheral Preferred Connection Parameters | Read | 無 | 可讀取裝置偏好的 connection interval / latency / timeout；截圖未顯示 value。 |
| `00002aa6-0000-1000-8000-00805f9b34fb` | Central Address Resolution | Read | 無 | 可讀取是否支援 central address resolution；截圖未顯示 value。 |

### Generic Attribute Service `1801`

截圖的 service list 有列出 `00001801-0000-1000-8000-00805f9b34fb`，但未提供展開後的 characteristic 畫面。若後續要做完整 GATT cache 處理，建議補掃此 service 是否包含 `2A05` Service Changed。

### Device Information Service `180A`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | 備註 |
| --- | --- | --- | --- | --- |
| `00002a24-0000-1000-8000-00805f9b34fb` | Model Number String | Read | 無 | 型號字串；截圖未顯示 value。 |
| `00002a25-0000-1000-8000-00805f9b34fb` | Serial Number String | Read | 無 | 序號字串；截圖未顯示 value。 |
| `00002a26-0000-1000-8000-00805f9b34fb` | Firmware Revision String | Read | 無 | 韌體版本；截圖未顯示 value。 |
| `00002a28-0000-1000-8000-00805f9b34fb` | Software Revision String | Read | 無 | 軟體版本；截圖未顯示 value。 |
| `00002a29-0000-1000-8000-00805f9b34fb` | Manufacturer Name String | Read | 無 | 製造商名稱；截圖未顯示 value。 |

### Heart Rate Service `180D`

| Characteristic UUID | 標準名稱 | Properties | Descriptor | 備註 |
| --- | --- | --- | --- | --- |
| `00002a37-0000-1000-8000-00805f9b34fb` | Heart Rate Measurement | Notify | `00002902-0000-1000-8000-00805f9b34fb` | 核心心率資料；截圖顯示 value cannot be read or written，需透過 notification 收資料。 |
| `00002a38-0000-1000-8000-00805f9b34fb` | Body Sensor Location | Read | 無 | 可讀取配戴位置；胸帶通常預期為 Chest，但截圖未顯示實際 value，需實測確認。 |

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

整合此心跳帶時，最小可用流程是：

1. 掃描或連線到裝置。
2. 找到 Heart Rate Service `0000180d-0000-1000-8000-00805f9b34fb`。
3. 訂閱 Heart Rate Measurement `00002a37-0000-1000-8000-00805f9b34fb` notification。
4. 解析 notification payload 取得 BPM，若有 RR-Interval 再換算 HRV。
5. 若需要顯示配戴位置，讀取 Body Sensor Location `00002a38-0000-1000-8000-00805f9b34fb`。

### Battery Service `180F`

截圖 service list 有列出 `0000180f-0000-1000-8000-00805f9b34fb`，但未截到 characteristic。標準 Battery Service 常用 Battery Level `00002a19-0000-1000-8000-00805f9b34fb`，但本裝置是否提供、以及 properties 是否包含 Read/Notify，仍需補掃確認。

### Nordic / DFU Service `FE59`

| Characteristic UUID | 推定用途 | Properties | Descriptor | 備註 |
| --- | --- | --- | --- | --- |
| `8ec90003-f315-4f60-9fb8-838830daea50` | Nordic buttonless DFU 類 characteristic | Write, Indicate | `00002902-0000-1000-8000-00805f9b34fb` | 此 service 通常與 firmware update 相關。一般心率讀取流程不需要使用，避免誤寫造成裝置進入 DFU 或更新模式。 |

### Vendor-specific Service `fce61000`

| Characteristic UUID | Properties | Descriptor | 截圖資訊 | 備註 |
| --- | --- | --- | --- | --- |
| `fce61002-7802-4392-b6b7-96b18deaad22` | Write, Notify | `00002902-0000-1000-8000-00805f9b34fb` | 有 write 欄位與 notify property | 自訂通道，payload 未知；不建議在沒有廠商文件或封包樣本前寫入。 |
| `fce61003-7802-4392-b6b7-96b18deaad22` | Write, Notify | `00002902-0000-1000-8000-00805f9b34fb` | 有 write 欄位與 notify property | 自訂通道，payload 未知；可能是設定、同步或非標準資料通道。 |

> 上述 vendor-specific UUID 依截圖整理，後續仍建議用程式掃描結果覆核一次。

### Vendor-specific Service `fce64000`

截圖的 service list 有列出 `fce64000-7802-4392-b6b7-96b18deaad22`，但未提供展開畫面。功能未知，需補掃 characteristics 後才能判斷。

## CCCD / Notification 設定

截圖中多個 Notify 或 Indicate characteristic 都有 Client Characteristic Configuration Descriptor：

`00002902-0000-1000-8000-00805f9b34fb`

常見設定值如下：

| 目標 | 寫入 CCCD value | 備註 |
| --- | --- | --- |
| Enable Notification | `0x01 0x00` | 用於 `2A37` Heart Rate Measurement 與自訂 Notify characteristic。 |
| Enable Indication | `0x02 0x00` | 用於 `FE59` 的 indicate characteristic。 |
| Disable Notification/Indication | `0x00 0x00` | 取消訂閱。 |

多數 BLE library 會用 `start_notify()`、`subscribe()` 或類似 API 自動處理 CCCD，不一定需要手動寫 descriptor。

## 對本專案的整合建議

1. 以標準 Heart Rate Service 為主，不先碰 vendor-specific service。
2. 連線後優先訂閱 `2A37`，把 notification BPM 當作外部 HR 參考來源。
3. 若 `2A37` payload 帶 RR-Interval，可同步導入 HRV；若沒有 RR-Interval，只使用 BPM。
4. 讀取 `2A38` 補充配戴位置，但不要把未讀到的值硬編成 Chest。
5. 補掃 Battery Service `180F`，確認是否有 `2A19`，再決定 UI 是否顯示心跳帶電量。
6. 避免對 `FE59` 或 `fce610xx/fce640xx` 寫入任何資料，除非已取得廠商協議或實測封包。
7. 連線識別建議同時使用 device name、Heart Rate Service 是否存在、必要時再加上 address；不要只依賴 `C1:3B:74:B8:F7:40`。

## 待補驗證清單

- 讀取 `2A38` Body Sensor Location 的實際 value。
- 補掃 `180F` Battery Service characteristics，確認是否有 `2A19` Battery Level。
- 補掃 `1801` Generic Attribute Service characteristics。
- 補掃 `fce64000` service 的 characteristics。
- 實際訂閱 `2A37` 並保存數筆 notification 原始 bytes，確認 flags、BPM 格式與是否含 RR-Interval。
- 若要使用自訂 service，需先收集 `fce61002/fce61003` notification 與 write payload 樣本，建立協議文件。

## 參考資料

- Bluetooth SIG Assigned Numbers: <https://www.bluetooth.com/specifications/assigned-numbers/>
- Bluetooth Heart Rate Service specification: <https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/>
- Bluetooth GATT Specification Supplement: <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement-7/>
