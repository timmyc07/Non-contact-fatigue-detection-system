# BLE 藍牙協議國際標準與跨平台寫法整理

整理日期：2026-07-02

用途：作為本專案後續整合心跳帶、BLE 感測器或自訂外部生理訊號來源時的協議設計與跨平台實作參考。

涵蓋範圍：BLE/GATT 國際通用協議寫法，以及 Android、iOS/macOS、Web、Windows、Linux、Python、Node.js、Zephyr、ESP-IDF、ArduinoBLE 的主流落地語法。藍牙生態沒有「所有語言共用的一種語法」，真正共用的是 GATT profile 與 byte payload；各平台只是用不同 API 操作同一份協議。

## 核心結論

- 國際通用的藍牙協議寫法不是某一種程式語法，而是 Bluetooth SIG 定義的 Profile、Service、Characteristic、Descriptor、UUID、ATT/GATT 操作與二進位 payload 格式。
- 心跳帶、電量、裝置資訊這類感測器整合應優先使用 BLE GATT，不應先用 Classic Bluetooth SPP/RFCOMM 或 vendor-specific 私有 service。
- 標準 UUID 要以 Bluetooth SIG Assigned Numbers 為準。自訂功能使用 128-bit vendor-specific UUID，不自行編造 16-bit UUID。
- 跨平台最穩定的協議文件應同時寫出 GATT table、Characteristic properties、permissions、CCCD 設定、payload byte layout、endianness、錯誤與版本策略。
- 各系統 API 名稱不同，但動作相同：掃描、連線、探索 service、探索 characteristic、讀取、寫入、訂閱 notification/indication、解析 bytes。

## 2026-07-02 資料查核摘要

| 項目 | 目前可採用資料 | 對本專案的意義 |
| --- | --- | --- |
| Bluetooth Core | Bluetooth Core Specification 已有 6.3 adopted 版本。 | 核心標準持續更新，但 BLE GATT 的基本抽象仍是 Service/Characteristic/Descriptor。 |
| Assigned Numbers | Bluetooth SIG Assigned Numbers PDF 版本日期為 2026-06-23。 | UUID、appearance、company identifier、service/characteristic 名稱應查此來源。 |
| GATT Supplement | GATT Specification Supplement 版本日期為 2026-02-05。 | 標準 characteristic 格式、presentation format、descriptor 定義應查此來源。 |
| Heart Rate Service | Heart Rate Service 1.0 仍是心跳帶互通的核心規格，Bluetooth SIG 頁面標示包含 mandatory errata。 | 心跳帶優先訂閱 `2A37`，不要先解析私有通道。 |
| Web Bluetooth | MDN 標示 Web Bluetooth API 不是 Baseline，瀏覽器支援有限且需要安全環境。 | Web dashboard 若要直接連 BLE，只能作為選配，不可假設所有瀏覽器可用。 |
| Android | Android 12 之後藍牙權限拆分為 `BLUETOOTH_SCAN`、`BLUETOOTH_CONNECT`、`BLUETOOTH_ADVERTISE`。 | Android app 需要把 runtime permission 納入設計。 |
| Windows | Microsoft Learn 持續維護 UWP/WinRT GATT client/server 文件。 | Windows 桌面整合可用 WinRT GATT API 或跨平台 Python Bleak。 |
| Linux | BlueZ 以 D-Bus 暴露 GATT/Advertising API。 | Linux 原生整合要理解 BlueZ D-Bus object path 與 `StartNotify`/`WriteValue`。 |

## 名詞與分層

| 層級 | 國際標準概念 | 寫協議時要定義的內容 |
| --- | --- | --- |
| GAP | 裝置角色、廣播、掃描、連線、裝置名稱、appearance。 | 裝置名稱、advertising data、是否可連線、是否需要 bonding。 |
| ATT | Attribute Protocol，GATT 的底層讀寫單位。 | MTU、讀寫錯誤、long write/chunking 行為。 |
| GATT | Services、Characteristics、Descriptors。 | Service UUID、Characteristic UUID、properties、permissions、descriptors。 |
| GATT Profile | 多個 service 組合成一個應用協議。 | 例如 Heart Rate Profile 使用 Heart Rate Service、Device Information Service。 |
| SMP/Security | Pairing、bonding、encryption、MITM。 | 是否要求配對、是否保存 bond、未授權時回傳什麼錯誤。 |
| L2CAP | BLE 連線內的 channel。 | 一般 GATT 應用不直接處理，除非做高吞吐或自訂 channel。 |

## Classic Bluetooth 與 BLE 的選擇

| 類型 | 常見用途 | 是否適合本專案心跳帶 |
| --- | --- | --- |
| BLE GATT | 感測器、心跳帶、電量、低功耗通知、小量資料交換。 | 適合。優先採用。 |
| Classic Bluetooth SPP/RFCOMM | 序列埠替代、舊式模組、連續串流。 | 不適合心跳帶標準互通，除非裝置只提供 SPP。 |
| BLE L2CAP CoC | 較高吞吐的 BLE channel。 | 目前不需要。先用 GATT notification。 |
| Vendor-specific GATT | 廠商自訂功能、設定、韌體更新。 | 可保留但不要優先依賴，需有封包文件或實測資料。 |

## 國際通用 GATT Profile 寫法

一份可交給任何平台實作的 BLE 協議文件，至少要包含下列資訊。

### 1. Device / GAP

| 欄位 | 寫法範例 | 注意事項 |
| --- | --- | --- |
| Device Name | `R+2.0 2248` | 名稱可變，不應作為唯一身份。 |
| Appearance | `0x0341` 或查 Assigned Numbers | 沒有資料時不要猜。 |
| Advertising Service UUIDs | `180D`, `180F` | 讓 scanner 可用 service filter 找到裝置。 |
| Address 策略 | Public / Random Static / Resolvable Private Address | BLE privacy 可能導致 address 改變，正式綁定要靠 bond 或 app-level identity。 |
| Pairing | Not required / Just Works / Passkey / Numeric Comparison | 涉及個資或寫入設定時應要求 encryption。 |

### 2. Service Table

| 欄位 | 寫法 |
| --- | --- |
| Service name | `Heart Rate Service` |
| UUID | `0000180d-0000-1000-8000-00805f9b34fb` |
| Type | Primary / Secondary |
| Required | Required / Optional |
| Notes | 例如「心跳主要資料來源」。 |

### 3. Characteristic Table

| 欄位 | 寫法 |
| --- | --- |
| Characteristic name | `Heart Rate Measurement` |
| UUID | `00002a37-0000-1000-8000-00805f9b34fb` |
| Properties | `read`, `write`, `write_without_response`, `notify`, `indicate` |
| Permissions | `open`, `encrypted`, `authenticated`, `authorized` |
| Descriptor | `00002902-0000-1000-8000-00805f9b34fb` for CCCD |
| Payload | byte layout、endianness、欄位單位、有效範圍 |
| Error behavior | 不支援、未配對、長度錯誤、版本不符時如何回應 |

### 4. UUID 寫法

標準 16-bit UUID 展開為 128-bit UUID 時使用 Bluetooth Base UUID：

```text
0000xxxx-0000-1000-8000-00805f9b34fb
```

範例：

| 16-bit | 128-bit |
| --- | --- |
| `180D` | `0000180d-0000-1000-8000-00805f9b34fb` |
| `2A37` | `00002a37-0000-1000-8000-00805f9b34fb` |
| `2902` | `00002902-0000-1000-8000-00805f9b34fb` |

自訂 service/characteristic 應使用完整 128-bit UUID，例如：

```text
fce64000-7802-4392-b6b7-96b18deaad22
```

## 常用標準 Service

| Service | UUID | 用途 | 本專案建議 |
| --- | --- | --- | --- |
| Generic Access | `1800` | 裝置名稱、appearance、連線參數。 | 可讀，不作為主要資料來源。 |
| Generic Attribute | `1801` | Service Changed 等 GATT metadata。 | 若有 `2A05`，bond 後需處理 service changed。 |
| Device Information | `180A` | 製造商、型號、序號、韌體版本。 | 連線後讀取並記錄到 log。 |
| Heart Rate | `180D` | 心率、RR-Interval、感測器位置。 | 心跳帶主要來源。 |
| Battery Service | `180F` | 電量百分比。 | UI 與低電量提示可用。 |
| Current Time | `1805` | 裝置時間。 | 感測器需要校時才使用。 |
| Nordic DFU / `FE59` | `FE59` | 常見於 Nordic DFU。 | 無廠商文件時不要寫入。 |

## Properties、Permissions 與 CCCD

| 項目 | 意義 | 常見寫法 |
| --- | --- | --- |
| Read | Client 可讀取 value。 | 電量、裝置資訊、設定值。 |
| Write With Response | Client 寫入後等待 ATT response。 | 設定命令、需要確認的控制。 |
| Write Without Response | Client 寫入但不等待 response。 | 高頻低延遲命令，需自行做 flow control。 |
| Notify | Server 主動送 value，沒有 GATT 層 ACK。 | 心率、即時資料。 |
| Indicate | Server 主動送 value，有 GATT 層 ACK。 | 重要狀態、低頻可靠通知。 |
| CCCD `2902` | Client 訂閱 notify/indicate 的 descriptor。 | Enable notify = `0x01 0x00`；Enable indicate = `0x02 0x00`。 |

注意：Characteristic properties 描述「可做什麼操作」，permissions 描述「什麼安全狀態才准做」。兩者要分開寫。

## Payload 協議寫法

### 通用原則

1. 一律寫明 byte order。BLE SIG 標準 characteristic 多採 little-endian。
2. 一律寫明欄位單位，例如 bpm、ms、1/1024 秒、百分比。
3. 固定長度 payload 要寫總長度；可變長度 payload 要寫 flags 或 length。
4. 第一版自訂 payload 建議放 `version` 與 `flags`，避免未來無法擴充。
5. 不要假設 notification payload 一定只有 20 bytes。ATT MTU 預設 23，value payload 預設可用 20 bytes，但實際連線可協商更大 MTU。
6. Notification 沒有應用層可靠性保證。重要資料要用 indication 或自行加 sequence number / ACK。
7. BLE link layer 已有 CRC，一般應用 payload 不需要再加 CRC；若資料需跨封包重組或落盤稽核，可另加 checksum。

### Heart Rate Measurement `2A37`

`2A37` 的 payload 第一個 byte 是 flags，後面依 flags 判斷欄位。

| 欄位 | 位置 | 說明 |
| --- | --- | --- |
| Flags | byte 0 | bit field。 |
| Heart Rate Value | byte 1 起 | flags bit 0 = `0` 時為 `uint8`；bit 0 = `1` 時為 little-endian `uint16`。 |
| Energy Expended | optional | flags bit 3 = `1` 時存在，little-endian `uint16`。 |
| RR-Interval | optional repeated | flags bit 4 = `1` 時存在，可有多組 little-endian `uint16`，單位 `1/1024` 秒。 |

解析範例：

```text
06 48
```

| Byte | 解讀 |
| --- | --- |
| `0x06` | flags：bit 1/2 表示 sensor contact 狀態，bit 0 = 0，所以 HR 是 uint8。 |
| `0x48` | BPM = 72。 |

### 自訂 Payload 範本

```text
Byte 0      protocol_version: uint8
Byte 1      message_type: uint8
Byte 2      flags: uint8
Byte 3      sequence: uint8
Byte 4..7   timestamp_ms: uint32 little-endian
Byte 8..9   value_1: int16 little-endian, scale = 0.01
Byte 10..11 value_2: int16 little-endian, scale = 0.01
```

對應文件應寫成：

| Offset | Size | Type | Field | Unit / Scale | Required | 說明 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | `uint8` | `protocol_version` | - | yes | 第一版固定 `1`。 |
| 1 | 1 | `uint8` | `message_type` | enum | yes | `1=sample`, `2=control_ack`。 |
| 2 | 1 | `uint8` | `flags` | bit field | yes | bit 0 表示 value_2 是否存在。 |
| 3 | 1 | `uint8` | `sequence` | modulo 256 | yes | 用於偵測遺失 notification。 |
| 4 | 4 | `uint32_le` | `timestamp_ms` | ms | yes | 裝置端 monotonic timestamp。 |
| 8 | 2 | `int16_le` | `value_1` | raw * 0.01 | yes | 主要量測值。 |
| 10 | 2 | `int16_le` | `value_2` | raw * 0.01 | no | flags bit 0 = 1 時存在。 |

## 協議文件範本

### Markdown 範本

```markdown
# <Device/Profile Name> BLE GATT Profile

Version: 1.0
Updated: YYYY-MM-DD
Owner: <team/vendor>

## GAP

- Device name:
- Appearance:
- Advertising service UUIDs:
- Pairing/bonding:
- Privacy/address policy:

## Services

| Service | UUID | Type | Required | Notes |
| --- | --- | --- | --- | --- |

## Characteristics

| Service UUID | Characteristic | UUID | Properties | Permissions | Descriptor | Payload |
| --- | --- | --- | --- | --- | --- | --- |

## Payloads

### <Characteristic name>

| Offset | Size | Type | Field | Unit | Required | Notes |
| --- | --- | --- | --- | --- | --- | --- |

## State Machine

1. Scan
2. Connect
3. Discover services
4. Subscribe notifications
5. Parse payload
6. Reconnect on disconnect

## Error Handling

| Error | Client behavior | Server behavior |
| --- | --- | --- |
```

### YAML 範本

```yaml
profile:
  name: Example Heart Rate Collector
  version: 1.0.0
  updated: 2026-07-02
  gap:
    advertised_services:
      - 0000180d-0000-1000-8000-00805f9b34fb
      - 0000180f-0000-1000-8000-00805f9b34fb
    pairing: optional
    address_policy: do_not_use_ble_address_as_only_identity
  services:
    - name: Heart Rate Service
      uuid: 0000180d-0000-1000-8000-00805f9b34fb
      type: primary
      characteristics:
        - name: Heart Rate Measurement
          uuid: 00002a37-0000-1000-8000-00805f9b34fb
          properties: [notify]
          permissions: [open]
          descriptors:
            - uuid: 00002902-0000-1000-8000-00805f9b34fb
              name: Client Characteristic Configuration
          payload:
            endian: little
            fields:
              - offset: 0
                type: uint8
                name: flags
              - offset: 1
                type: uint8_or_uint16_le
                name: heart_rate_bpm
                condition: flags.bit0
    - name: Battery Service
      uuid: 0000180f-0000-1000-8000-00805f9b34fb
      type: primary
      characteristics:
        - name: Battery Level
          uuid: 00002a19-0000-1000-8000-00805f9b34fb
          properties: [read, notify]
          permissions: [open]
          payload:
            fields:
              - offset: 0
                type: uint8
                name: battery_percent
                range: 0..100
```

### JSON 範本

```json
{
  "profile": "Example Heart Rate Collector",
  "version": "1.0.0",
  "services": [
    {
      "uuid": "0000180d-0000-1000-8000-00805f9b34fb",
      "characteristics": [
        {
          "uuid": "00002a37-0000-1000-8000-00805f9b34fb",
          "properties": ["notify"],
          "payload": {
            "byte_order": "little",
            "format": "Bluetooth SIG Heart Rate Measurement"
          }
        }
      ]
    }
  ]
}
```

## 各系統與語法寫法

以下範例都以「連線到 Heart Rate Service `180D`，訂閱 Heart Rate Measurement `2A37`」為同一個目標。

### Android Kotlin / Java

適用：Android BLE Central / GATT Client。Android 12 之後要處理 runtime permission。

Manifest 範例：

```xml
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30" />
```

Kotlin GATT client 範例：

```kotlin
private val HR_SERVICE = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
private val HR_MEASUREMENT = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
private val CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

private val scanFilter = ScanFilter.Builder()
    .setServiceUuid(ParcelUuid(HR_SERVICE))
    .build()

private val scanSettings = ScanSettings.Builder()
    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
    .build()

bluetoothAdapter.bluetoothLeScanner.startScan(
    listOf(scanFilter),
    scanSettings,
    scanCallback,
)

private val gattCallback = object : BluetoothGattCallback() {
    override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
        if (status != BluetoothGatt.GATT_SUCCESS) return

        val characteristic = gatt
            .getService(HR_SERVICE)
            ?.getCharacteristic(HR_MEASUREMENT)
            ?: return

        gatt.setCharacteristicNotification(characteristic, true)
        val cccd = characteristic.getDescriptor(CCCD) ?: return

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        } else {
            @Suppress("DEPRECATION")
            cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(cccd)
        }
    }

    override fun onCharacteristicChanged(
        gatt: BluetoothGatt,
        characteristic: BluetoothGattCharacteristic,
        value: ByteArray,
    ) {
        if (characteristic.uuid == HR_MEASUREMENT) {
            val bpm = parseHeartRateMeasurement(value)
        }
    }
}

private fun parseHeartRateMeasurement(value: ByteArray): Int {
    require(value.isNotEmpty())
    val flags = value[0].toInt() and 0xff
    return if ((flags and 0x01) == 0) {
        value[1].toInt() and 0xff
    } else {
        (value[1].toInt() and 0xff) or ((value[2].toInt() and 0xff) shl 8)
    }
}
```

Android 注意事項：

- Android 12+ 掃描與連線分別需要 `BLUETOOTH_SCAN`、`BLUETOOTH_CONNECT`。
- 舊版 Android 若掃描 BLE，通常還需要 location permission。
- `writeCharacteristic`、`writeDescriptor` 在 Android 13/API 33 後有帶 `ByteArray` 的新 overload，應優先使用新 API。
- 若 app 仍支援 API 32 以下，`BluetoothGattCallback` 需同時覆寫舊版 `onCharacteristicChanged(gatt, characteristic)`，再從 characteristic 取值。
- BLE callback 不在 UI thread，更新 UI 前要切回主執行緒。

### iOS / macOS Swift Core Bluetooth

適用：iOS、iPadOS、macOS 的 BLE Central / Peripheral。App 需要在 `Info.plist` 提供藍牙使用說明。

Central 範例：

```swift
import CoreBluetooth

let heartRateService = CBUUID(string: "180D")
let heartRateMeasurement = CBUUID(string: "2A37")

final class HeartRateCentral: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: nil)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else { return }
        central.scanForPeripherals(withServices: [heartRateService], options: nil)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String : Any], rssi RSSI: NSNumber) {
        self.peripheral = peripheral
        peripheral.delegate = self
        central.stopScan()
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([heartRateService])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        peripheral.services?
            .filter { $0.uuid == heartRateService }
            .forEach { peripheral.discoverCharacteristics([heartRateMeasurement], for: $0) }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        service.characteristics?
            .filter { $0.uuid == heartRateMeasurement }
            .forEach { peripheral.setNotifyValue(true, for: $0) }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard characteristic.uuid == heartRateMeasurement, let data = characteristic.value else { return }
        let bpm = parseHeartRateMeasurement(data)
    }
}

func parseHeartRateMeasurement(_ data: Data) -> Int {
    let bytes = [UInt8](data)
    let flags = bytes[0]
    if (flags & 0x01) == 0 {
        return Int(bytes[1])
    }
    return Int(bytes[1]) | (Int(bytes[2]) << 8)
}
```

Peripheral/server 範例：

```swift
let service = CBMutableService(type: CBUUID(string: "180D"), primary: true)
let measurement = CBMutableCharacteristic(
    type: CBUUID(string: "2A37"),
    properties: [.notify],
    value: nil,
    permissions: []
)
service.characteristics = [measurement]
peripheralManager.add(service)
```

iOS/macOS 注意事項：

- iOS 不允許一般 app 直接取得穩定 BLE MAC address。
- 背景掃描/連線需配置 background mode，且行為受系統節電影響。
- Core Bluetooth 會自動處理 CCCD，通常使用 `setNotifyValue(true, for:)` 即可。

### Web JavaScript / Web Bluetooth

適用：支援 Web Bluetooth 的 Chromium 系瀏覽器。需 HTTPS 或 localhost，且通常要由使用者手勢觸發。

```javascript
const HEART_RATE_SERVICE = "heart_rate";
const HEART_RATE_MEASUREMENT = "heart_rate_measurement";

const device = await navigator.bluetooth.requestDevice({
  filters: [{ services: [HEART_RATE_SERVICE] }],
  optionalServices: ["battery_service"],
});

const server = await device.gatt.connect();
const service = await server.getPrimaryService(HEART_RATE_SERVICE);
const characteristic = await service.getCharacteristic(HEART_RATE_MEASUREMENT);

characteristic.addEventListener("characteristicvaluechanged", (event) => {
  const value = event.target.value;
  const bpm = parseHeartRateMeasurement(value);
});

await characteristic.startNotifications();

function parseHeartRateMeasurement(dataView) {
  const flags = dataView.getUint8(0);
  if ((flags & 0x01) === 0) {
    return dataView.getUint8(1);
  }
  return dataView.getUint16(1, true);
}
```

寫入範例：

```javascript
const payload = new Uint8Array([0x01, 0x02, 0x03]);
await characteristic.writeValueWithResponse(payload);
```

Web 注意事項：

- Web Bluetooth 不是所有瀏覽器都支援，不可作為唯一方案。
- 網頁不能無提示任意掃描附近所有 BLE 裝置，通常需要使用者選取裝置。
- Browser API 只適合作為 GATT client；要做 GATT server 應使用原生 app 或嵌入式韌體。

### Windows C# / WinRT

適用：Windows app、UWP/WinUI、可呼叫 WinRT API 的 .NET 程式。

```csharp
using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.GenericAttributeProfile;
using Windows.Storage.Streams;

static readonly Guid HeartRateService =
    Guid.Parse("0000180d-0000-1000-8000-00805f9b34fb");
static readonly Guid HeartRateMeasurement =
    Guid.Parse("00002a37-0000-1000-8000-00805f9b34fb");

GattDeviceServicesResult services =
    await device.GetGattServicesForUuidAsync(HeartRateService);

GattDeviceService service = services.Services[0];
GattCharacteristicsResult characteristics =
    await service.GetCharacteristicsForUuidAsync(HeartRateMeasurement);

GattCharacteristic characteristic = characteristics.Characteristics[0];
characteristic.ValueChanged += (sender, args) =>
{
    var reader = DataReader.FromBuffer(args.CharacteristicValue);
    byte[] bytes = new byte[(int)args.CharacteristicValue.Length];
    reader.ReadBytes(bytes);
    int bpm = ParseHeartRateMeasurement(bytes);
};

await characteristic.WriteClientCharacteristicConfigurationDescriptorAsync(
    GattClientCharacteristicConfigurationDescriptorValue.Notify);

static int ParseHeartRateMeasurement(byte[] value)
{
    int flags = value[0];
    if ((flags & 0x01) == 0)
    {
        return value[1];
    }
    return value[1] | (value[2] << 8);
}
```

Windows 注意事項：

- App manifest 需要宣告 Bluetooth capability。
- 使用 `BluetoothLEAdvertisementWatcher` 可先掃描廣播，再連線。
- `WriteClientCharacteristicConfigurationDescriptorAsync` 用於開啟 notify/indicate。
- 若用一般 Python 桌面程式，通常用 Bleak 比直接操作 WinRT 更簡潔。

### Linux BlueZ D-Bus

適用：Linux 原生藍牙堆疊。BlueZ 透過 D-Bus 暴露 GATT API。

GATT characteristic D-Bus 介面重點：

| 操作 | D-Bus method / property |
| --- | --- |
| Read | `org.bluez.GattCharacteristic1.ReadValue` |
| Write | `org.bluez.GattCharacteristic1.WriteValue` |
| Subscribe | `org.bluez.GattCharacteristic1.StartNotify` |
| Unsubscribe | `org.bluez.GattCharacteristic1.StopNotify` |
| Value update | `org.freedesktop.DBus.Properties.PropertiesChanged` |
| UUID | `UUID` property |
| Properties | `Flags` property，例如 `read`, `write`, `notify` |

概念範例：

```bash
bluetoothctl
scan on
connect <DEVICE_ADDRESS>
menu gatt
list-attributes
select-attribute <CHARACTERISTIC_PATH>
notify on
```

D-Bus 程式通常流程：

```text
1. 透過 org.bluez.Adapter1 啟動 discovery。
2. 找到 org.bluez.Device1 且 UUIDs 包含 180D。
3. 呼叫 Device1.Connect。
4. 取得 ObjectManager 內的 GattService1/GattCharacteristic1。
5. 對 2A37 對應 object path 呼叫 StartNotify。
6. 監聽 PropertiesChanged 的 Value。
```

Linux server 端要匯出：

- `org.bluez.GattService1`
- `org.bluez.GattCharacteristic1`
- `org.bluez.GattDescriptor1`
- `org.bluez.LEAdvertisement1`

Linux 注意事項：

- BlueZ object path 會因 adapter、device address、handle 而變，不應硬編。
- 一般使用者權限、systemd service 權限與 D-Bus policy 會影響是否能掃描/連線。
- 若只做跨平台 GATT client，Python Bleak 通常比直接寫 D-Bus 快。

### Python Bleak

適用：Windows、macOS、Linux 跨平台 BLE GATT client。適合本專案桌面 Python 架構。

```python
import asyncio
from bleak import BleakClient, BleakScanner

HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_heart_rate_measurement(data: bytearray) -> int:
    flags = data[0]
    if flags & 0x01 == 0:
        return data[1]
    return data[1] | (data[2] << 8)


async def main() -> None:
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: HR_SERVICE.lower() in [s.lower() for s in adv.service_uuids]
    )
    if device is None:
        raise RuntimeError("找不到 Heart Rate Service 裝置")

    async with BleakClient(device) as client:
        def on_hr(_, data: bytearray) -> None:
            bpm = parse_heart_rate_measurement(data)
            print(f"BPM={bpm}")

        await client.start_notify(HR_MEASUREMENT, on_hr)
        await asyncio.sleep(30)
        await client.stop_notify(HR_MEASUREMENT)


asyncio.run(main())
```

Bleak 注意事項：

- Bleak 是 GATT client library，不是完整 GATT server framework。
- macOS 端回傳的 device address 可能是 Core Bluetooth UUID，不是 BLE MAC。
- callback 在 asyncio 流程中執行，整合 Qt/PySide 時要設計 thread/queue 邊界。

### Node.js

Node.js 沒有像 Web Bluetooth 那樣的官方跨平台核心 API。若在 browser 內，使用 Web Bluetooth；若在 Node runtime，通常依賴第三方 BLE central library，例如 `@abandonware/noble` 類型 API。

概念範例：

```javascript
const noble = require("@abandonware/noble");

const HR_SERVICE = "180d";
const HR_MEASUREMENT = "2a37";

noble.on("stateChange", async (state) => {
  if (state === "poweredOn") {
    await noble.startScanningAsync([HR_SERVICE], false);
  }
});

noble.on("discover", async (peripheral) => {
  await noble.stopScanningAsync();
  await peripheral.connectAsync();

  const { characteristics } =
    await peripheral.discoverSomeServicesAndCharacteristicsAsync(
      [HR_SERVICE],
      [HR_MEASUREMENT],
    );

  const hr = characteristics[0];
  hr.on("data", (data) => {
    const bpm = parseHeartRateMeasurement(data);
  });
  await hr.subscribeAsync();
});

function parseHeartRateMeasurement(buffer) {
  const flags = buffer.readUInt8(0);
  return (flags & 0x01) === 0 ? buffer.readUInt8(1) : buffer.readUInt16LE(1);
}
```

Node 注意事項：

- Library 維護狀態、OS 權限、藍牙 adapter 支援差異很大。
- 不建議把 Node BLE 作為本專案主要桌面整合層；Python Bleak 或原生平台 API 更可控。

### C / Zephyr RTOS

適用：自製 BLE peripheral 韌體。Zephyr 與 Nordic nRF Connect SDK 常用這種 GATT service 宣告方式。

```c
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>

static void hr_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    bool notify_enabled = (value == BT_GATT_CCC_NOTIFY);
}

BT_GATT_SERVICE_DEFINE(hrs_svc,
    BT_GATT_PRIMARY_SERVICE(BT_UUID_HRS),
    BT_GATT_CHARACTERISTIC(BT_UUID_HRS_MEASUREMENT,
        BT_GATT_CHRC_NOTIFY,
        BT_GATT_PERM_NONE,
        NULL, NULL, NULL),
    BT_GATT_CCC(hr_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE)
);

void send_heart_rate(uint8_t bpm)
{
    uint8_t payload[] = { 0x00, bpm };
    const struct bt_gatt_attr *value_attr = &hrs_svc.attrs[2];
    bt_gatt_notify(NULL, value_attr, payload, sizeof(payload));
}
```

Zephyr 注意事項：

- `BT_GATT_CHARACTERISTIC` 會展開 characteristic declaration 與 value attribute，通知時要傳 value attribute。
- 量產前要正確設定廣播資料、device name、security、bonding 與 connection parameter。

### C / ESP-IDF

適用：ESP32 系列作為 BLE peripheral 或 central。ESP-IDF GATT server 通常透過 callback event 建立 service/characteristic/descriptor。

概念流程：

```c
esp_ble_gatts_register_callback(gatts_event_handler);
esp_ble_gap_register_callback(gap_event_handler);
esp_ble_gatts_app_register(PROFILE_APP_ID);

// ESP_GATTS_REG_EVT:
esp_ble_gatts_create_service(gatts_if, &service_id, handle_count);

// ESP_GATTS_CREATE_EVT:
esp_ble_gatts_start_service(service_handle);
esp_ble_gatts_add_char(
    service_handle,
    &char_uuid,
    ESP_GATT_PERM_READ,
    ESP_GATT_CHAR_PROP_BIT_NOTIFY,
    &char_value,
    NULL
);

// ESP_GATTS_ADD_CHAR_EVT:
esp_ble_gatts_add_char_descr(
    service_handle,
    &cccd_uuid,
    ESP_GATT_PERM_READ | ESP_GATT_PERM_WRITE,
    NULL,
    NULL
);

// Notify:
esp_ble_gatts_send_indicate(
    gatts_if,
    conn_id,
    char_handle,
    payload_len,
    payload,
    false
);
```

ESP-IDF 注意事項：

- `esp_ble_gatts_send_indicate(..., false)` 在 ESP-IDF API 中常用於 notify；`true` 表示 indication 需要 confirmation。
- GATT server event 很多，建議用狀態機管理 handle 與連線。
- 廣播資料要放 service UUID，client 才能用 service filter 掃描。

### C++ / ArduinoBLE

適用：Arduino 相容開發板作為 BLE peripheral。

```cpp
#include <ArduinoBLE.h>

BLEService heartRateService("180D");
BLECharacteristic heartRateMeasurement("2A37", BLENotify, 20);

void setup() {
  BLE.begin();
  BLE.setLocalName("Example HR Belt");
  BLE.setAdvertisedService(heartRateService);

  heartRateService.addCharacteristic(heartRateMeasurement);
  BLE.addService(heartRateService);

  BLE.advertise();
}

void loop() {
  BLEDevice central = BLE.central();
  if (!central) {
    return;
  }

  uint8_t payload[] = {0x00, 72};
  heartRateMeasurement.writeValue(payload, sizeof(payload));
  delay(1000);
}
```

ArduinoBLE 注意事項：

- 適合原型驗證，不適合直接代表量產韌體架構。
- 仍需依 SIG 規格正確定義 payload，不要只讓 app 端硬猜。

## 各語言 Heart Rate Parser 對照

同一個 `2A37` payload 在不同語言的解析方式如下。

### Python

```python
def parse_hr(data: bytes) -> int:
    flags = data[0]
    return data[1] if flags & 0x01 == 0 else int.from_bytes(data[1:3], "little")
```

### JavaScript

```javascript
function parseHr(view) {
  const flags = view.getUint8(0);
  return (flags & 0x01) === 0 ? view.getUint8(1) : view.getUint16(1, true);
}
```

### Kotlin

```kotlin
fun parseHr(data: ByteArray): Int {
    val flags = data[0].toInt() and 0xff
    return if ((flags and 0x01) == 0) {
        data[1].toInt() and 0xff
    } else {
        (data[1].toInt() and 0xff) or ((data[2].toInt() and 0xff) shl 8)
    }
}
```

### Swift

```swift
func parseHr(_ data: Data) -> Int {
    let bytes = [UInt8](data)
    if (bytes[0] & 0x01) == 0 {
        return Int(bytes[1])
    }
    return Int(bytes[1]) | (Int(bytes[2]) << 8)
}
```

### C

```c
#include <stdint.h>

uint16_t parse_hr(const uint8_t *data, uint16_t len)
{
    if (len < 2) {
        return 0;
    }
    if ((data[0] & 0x01) == 0) {
        return data[1];
    }
    if (len < 3) {
        return 0;
    }
    return (uint16_t)data[1] | ((uint16_t)data[2] << 8);
}
```

## 本專案建議落地策略

1. `docs/technical/heart_rate_belt_bluetooth_gatt_profile.md` 作為 R+2.0 2248 實機 profile 對照。
2. 本文件作為跨平台與協議撰寫總指南。
3. Python 桌面整合優先使用 Bleak，避免同時維護 Windows/macOS/Linux 三套原生 GATT client。
4. 實作時只依賴標準 `180D`、`2A37`、`2A38`、`180F`、`2A19`，不先寫入 `FE59` 或 vendor-specific service。
5. 解析層寫成純函式，例如 `parse_heart_rate_measurement(data: bytes)`，讓 GUI、watch runtime、測試都能共用。
6. BLE callback 到本專案 worker/thread 邊界時，使用 queue 或 Qt signal 傳遞已解析資料，不在 callback 直接更新 UI。
7. 資料庫記錄建議保存：
   - `timestamp`
   - `source = ble_hr_belt`
   - `bpm`
   - `rr_intervals_ms`
   - `battery_percent`
   - `rssi`
   - `raw_payload_hex`

## 實作前檢查清單

- 已確認裝置廣播或 GATT profile 真的包含 `180D`。
- 已確認 Android/iOS/Windows/Linux 的權限與使用者授權流程。
- 已確認 notification callback 可穩定收到 `2A37`。
- 已保存至少 30 秒 raw payload hex，驗證 flags 與 RR-Interval。
- 已處理斷線、重連、停止掃描、省電模式。
- 已處理無電量資料、無 RR-Interval、無 Body Sensor Location 的狀況。
- 已避免把 BLE address 當唯一身份。
- 若要上架或量產，已確認 Bluetooth SIG qualification 與商標使用要求。

## 參考資料

- Bluetooth SIG - Specifications: <https://www.bluetooth.com/specifications/specs/>
- Bluetooth SIG - Assigned Numbers: <https://www.bluetooth.com/specifications/assigned-numbers/>
- Bluetooth SIG - Heart Rate Service 1.0: <https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/>
- Bluetooth SIG - GATT Specification Supplement: <https://www.bluetooth.com/specifications/specs/gatt-specification-supplement-7/>
- Bluetooth SIG - Qualification Program: <https://www.bluetooth.com/develop-with-bluetooth/qualification-listing/>
- Android Developers - Bluetooth Low Energy: <https://developer.android.com/develop/connectivity/bluetooth/ble/ble-overview>
- Android Developers - Bluetooth permissions: <https://developer.android.com/develop/connectivity/bluetooth/bt-permissions>
- Apple Developer - Core Bluetooth: <https://developer.apple.com/documentation/corebluetooth>
- Apple Developer - Performing Common Central Role Tasks: <https://developer.apple.com/library/archive/documentation/NetworkingInternetWeb/Conceptual/CoreBluetooth_concepts/PerformingCommonCentralRoleTasks.html>
- Microsoft Learn - Bluetooth Low Energy: <https://learn.microsoft.com/windows/uwp/devices-sensors/bluetooth-low-energy-overview>
- Microsoft Learn - GATT client: <https://learn.microsoft.com/windows/uwp/devices-sensors/gatt-client>
- BlueZ - GATT API: <https://bluez.readthedocs.io/en/latest/gatt-api/>
- BlueZ - LE Advertising API: <https://bluez.readthedocs.io/en/latest/advertising-api/>
- MDN - Web Bluetooth API: <https://developer.mozilla.org/en-US/docs/Web/API/Web_Bluetooth_API>
- Web Bluetooth Community Group Specification: <https://webbluetoothcg.github.io/web-bluetooth/>
- Bleak documentation: <https://bleak.readthedocs.io/>
- Zephyr Project - Bluetooth GATT: <https://docs.zephyrproject.org/latest/connectivity/bluetooth/api/gatt.html>
- ESP-IDF - Bluetooth API: <https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/bluetooth/index.html>
- ArduinoBLE reference: <https://docs.arduino.cc/libraries/arduinoble/>
