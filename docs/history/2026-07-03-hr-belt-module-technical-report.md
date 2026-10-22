# 心跳帶模組技術報告：信號擷取、rPPG 校準與精準度保障

> 撰於 2026-07-03。涵蓋心跳帶（BLE Heart Rate belt）模組的信號擷取方式、
> 各 GATT 服務／特徵碼用途、線上自適應校準如何幫 rPPG 微調、為何能邊讀邊調而無自我回饋、
> 精準度如何確定、所用技術與參考文獻。
> 本報告區分「文獻／規範明載」與「本專案工程決定」；不確定或未實作處明確標註。
> 所有事實均附 `檔案:行號`，以程式碼為準。

---

## 0. 模組定位（能做什麼、不能做什麼）

心跳帶（實測硬體 Scosche R+2.0 2248）在本系統只扮演一個角色：**rPPG 心率的背景真值來源**。

- **能做**：以藍牙讀進真實 BPM，運行時線上比對 rPPG 攝影機估出的心率，低增益慢速微調 rPPG 的校準
  offset；收斂後存成新校準版本，跨 session 持續改善 rPPG 心率準確度（`rppg/adaptive_calibration.py`、
  `rppg/calibration.py`）。同時保留 RR-Interval 供未來 HRV 比對（預留接口）。
- **不做（紅線）**：心跳帶**原始數值**永不直接進入疲勞融合分數。系統只有兩種配置：行為+rPPG 判斷疲勞、
  行為+rPPG+心跳帶校正 rPPG（`CLAUDE.md`）。手錶融合模式已移除。

> **誠實揭露（重要）**：紅線「原始數值不進融合」為真，但存在一條**間接弱路徑**——見 §7，
> 心跳帶透過改變 rPPG 校準後 BPM，對疲勞分數的間接影響上限約 **4.5%**。報告勿把紅線講成「零影響」。

---

## 1. 信號怎麼擷取（BLE 連線與背景執行緒）

**函式庫**：`bleak`（選配依賴），僅在 `HrBeltBleClient.start()` 時才 `import bleak`，模組匯入不強制安裝
（`rppg/hr_belt_ble.py:369`）。

**執行緒模型**：`HrBeltBleClient._run()`（`hr_belt_ble.py:424`）在獨立 daemon thread 內建立自己的 asyncio
event loop 跑 `_main()`（`:456`），內含無窮迴圈：**掃描 → 連線 → 訂閱 notify → 斷線偵測 → 延遲後重新掃描**，
直到 `stop_event` 被設。

流程各步驟：

| 步驟 | 行為 | 檔案:行號 |
|---|---|---|
| 掃描 | `BleakScanner.discover(service_uuids=[0x180D])` 過濾廣播含心率服務的裝置 | `hr_belt_ble.py:516` |
| 挑裝置 | `pick_heart_rate_device()`：指定 address 相符 → 名稱前綴相符（RSSI 高者優先）→ 廣播 HRS（RSSI 高者優先） | `hr_belt_ble.py:247` |
| 連線 | `BleakClient(device, disconnected_callback=..., timeout=15.0)` | `hr_belt_ble.py:487` |
| 初始化 | `_prime_connection()`：best-effort 讀 `2A38`、讀+訂閱 `2A19`，**必要**訂閱 `2A37`（8 秒逾時，失敗即拋例外觸發重連） | `hr_belt_ble.py:548` |
| 停止 | `stop()` 透過 `loop.call_soon_threadsafe` 取消主任務，`stop_event` 設置後 handler 拒絕再寫入 hub | `hr_belt_ble.py:382,579` |

**資料推播機制**：心率走 GATT **notify**（裝置主動推，非輪詢）。每筆進 callback `_on_hr_notification()`
（`:578`）解析、更新 `HrBeltStatus`（加鎖）、轉成 `WatchSample`、`self._hub.add(sample)` 推入
`WatchHrHub`（`calibration_watch.py:69`，加鎖 append）。

---

## 2. 各服務／特徵碼個別用途

UUID 常數定義於 `rppg/hr_belt_ble.py:35-39`。程式實際使用 4 個特徵、分屬 3 個 Service：

| Service / Characteristic | UUID | 存取方式 | 這個模組拿它做什麼 |
|---|---|---|---|
| **Heart Rate Service** | `0x180D` | 掃描過濾 | 廣播含此 Service 才視為心跳帶（`:527,274`） |
| └ Heart Rate Measurement | `0x2A37` | **notify** | **核心**。即時推播 BPM ＋（可選）RR-Interval（`:572`） |
| └ Body Sensor Location | `0x2A38` | read（一次） | 感測位置（手腕/胸口…），純顯示（`:551`） |
| **Battery Service** | `0x180F` | — | 電池服務容器 |
| └ Battery Level | `0x2A19` | read + notify | 剩餘電量，GUI/dashboard 低電量警示（`:557,564,610`） |

**未實作的特徵碼**（裝置端有、程式沒讀，屬文件與實作的已知落差）：

- `0x2A39` Heart Rate Control Point（重設能量消耗計數）— 本系統只被動接收，不需下控制命令。
- `0x180A` Device Information（型號/序號/韌體字串）— 未讀取（`docs/technical/heart_rate_belt_bluetooth_gatt_profile.md:35,61`）。
- Vendor-specific `FE59`（DFU）、`fce6xxxx` — 文件明確建議**不讀不寫**，程式零引用（`docs/...gatt_profile.md:17,180`）。

---

## 3. `0x2A37` 封包怎麼解析（`parse_heart_rate_measurement`, `hr_belt_ble.py:149`）

第一個 byte 是 flags，決定後面欄位怎麼讀（bit 定義於 `hr_belt_ble.py:56-60`）：

| Bit | 常數 | 意義 | 程式行為 |
|---|---|---|---|
| 0 | `_FLAG_HR_UINT16` | BPM 格式 | 0→uint8（`buf[offset]`，`:168`）；1→uint16 little-endian（`:165`） |
| 1 | `_FLAG_CONTACT_DETECTED` | 接觸偵測結果 | 只有 bit2 支援時才採信（`contact_supported and bit1`，`:171`） |
| 2 | `_FLAG_CONTACT_SUPPORTED` | 是否支援接觸偵測 | 同上 |
| 3 | `_FLAG_ENERGY_PRESENT` | 能量消耗欄位存在（uint16, kJ） | 讀 2 bytes（`:174`） |
| 4 | `_FLAG_RR_PRESENT` | RR-Interval 存在（可多組 uint16） | 迴圈讀到 buffer 耗盡（`:181`） |

- **RR-Interval 單位**：原始值為 1/1024 秒解析度，換算 `rr_ms = raw * 1000.0 / 1024.0`（`:186`）；
  只保留生理合理範圍 `_RR_MIN_MS=200` ~ `_RR_MAX_MS=3000`（`:63,187`），超出丟棄；末端不足 2 bytes 記 debug 忽略。
- **防呆**：payload 長度不足丟 `ValueError`（`:156,163,176`），測試涵蓋截斷情境（`tests/test_hr_belt_ble.py:108`）。
- **實機實測（2026-07-03，R+2.0 2248）**：一般模式 payload 固定 2 bytes、`flags=0x06`（接觸支援+偵測到）
  + uint8 BPM、約 2Hz notify，**不帶 RR-Interval**（三連按進 HRV 模式才有，本專案未使用）。
  故 RR 解析碼雖完整且有測試，**生產路徑目前吃不到 RR**——HRV 比對是預留接口而非現行功能
  （`docs/technical/heart_rate_belt_bluetooth_gatt_profile.md:91`）。

其他特徵解析：`0x2A38` 用 `body_sensor_location_label()`（`:213`）對照 0=Other…6=Foot；
`0x2A19` 用 `parse_battery_level()`（`:202`）做 0–100 範圍校驗。

---

## 4. 這些數值怎麼用來幫 rPPG 調整

核心是 `OnlineBpmCalibrator`（`rppg/adaptive_calibration.py`，純運算、無 Qt、無 I/O）。策略是
**低增益 EMA 慢速微調 offset**：

1. **配對**（`observe()`, `:115`）：每次拿一組同時刻的（心跳帶真值 BPM, rPPG 原始 BPM）。
   接受條件：心跳帶 `bpm>0` 且 fresh（非 stale）且 `contact_ok`；rPPG 需通過 `ADAPTIVE_QUALITY_GATES`；
   兩者差距超過 `max_pair_bpm_gap=40` 的離群配對直接排除。
2. **算殘差**：在滾動視窗 `window_sec=45` 秒內取**中位數殘差** `median(belt - rppg)`（`:172`）；
   中位數而非平均，是為了抗離群。
3. **EMA 更新 offset**（`_maybe_update()`, `:157`）：`offset += alpha * (target - offset)`，`alpha=0.08`；
   `target = clamp(raw_residual, ±25)`。需累積 `≥ min_pairs=6` 且距上次更新 `≥ 2` 秒才觸發。
4. **只動 offset、不動 scale**：bias 模型為 `scale*bpm+offset`，線上校準把 scale 固定 1.0，只調 offset
   （`:243`）。理由：線上資料不足以穩健估斜率，只修系統性偏移最安全。
5. **收斂/持久化**：corrected 殘差 `≤ 3.0` 判收斂，`≥ 8.0` 且樣本夠多才判分歧。停止校準時若累積觀測 `≥12`
   且信心非最低，存成新 `CalibrationVersionStore` 版本並設為使用中，跨 session 生效。

**主要數值常數**（`adaptive_calibration.py:82-104` 建構子預設）：

| 常數 | 值 | 作用 |
|---|---|---|
| `alpha` | 0.08 | EMA 增益（低=慢而穩） |
| `window_sec` | 45.0 | 殘差滾動視窗 |
| `min_pairs` | 6 | 觸發微調最少配對數 |
| `max_abs_offset_bpm` | 25.0 | offset 絕對值上限（防裝置故障拉歪） |
| `update_min_interval_sec` | 2.0 | 兩次微調最短間隔 |
| `converge_residual_bpm` | 3.0 | 收斂門檻 |
| `diverge_residual_bpm` | 8.0 | 分歧門檻 |
| `max_pair_bpm_gap` | 40.0 | 離群配對排除 |
| `min_sqi` / `min_quality_score` / `min_roi_valid` | 0.45 / 0.55 / 3 | rPPG 品質門檻（`:37-39`） |

**套用鏈路**：`_load_rppg_calibration_version()`（`main_window.py:2340`）→ 校準器運行中回傳即時
`live_version()`（`id="v_adaptive_live"`），否則回傳 store 的 active 版本 → 傳給 `CombinedWorker` →
每幀 `apply_calibration_to_metrics()` 把校準值填進 `RppgMetrics.bpm_calibrated`（`calibration.py:143`）。

**跨 session 是「seed 接續」**：開始新一輪校準時，用目前 active 版本的 `bpm_offset` 當新校準器的起點
（`main_window.py:2058`），不是從零開始——每次配戴接著上次的收斂結果繼續微調。

---

## 5. 為什麼能「邊讀取邊調整」而不會自我回饋

若拿「已被 offset 修正過的 rPPG BPM」去跟心跳帶比，會形成正回饋迴圈越調越偏。系統避免的方式是：
**比對永遠用 rPPG 的原始 BPM（尚未套 offset 的值）**。

- `adaptive_calibration.py:138`：`rppg_bpm = calibration_rppg_bpm(rppg_sample)`。
- `calibration_rppg_bpm`（`calibration.py:170`）優先取 `sample["raw_bpm"]` 或 `sample["bpm"]`——
  都是校準前欄位，**不是** `bpm_calibrated`。
- 餵進來的 `r` 是 `_latest_rppg_metrics`（套校準前的原始物件，`main_window.py:2127`），
  且以物件同一性 `r is not self._last_calib_fed_metrics` 判斷是否為新樣本，避免同一幀重複餵入放大權重。
- 程式註解明說「比對用的是 rPPG 原始 BPM，不會自我回饋」（`main_window.py:2341`、`adaptive_calibration.py:6`）。

因此殘差衡量的永遠是「攝影機原始估計 vs 真值」的固定關係，offset 只是把這固定偏移補掉，數學上不會發散。

---

## 6. 精準度怎麼確定（驗證）

驗證靠 pytest 對純運算層的斷言，不依賴實體硬體：

- **封包解析正確性**（`tests/test_hr_belt_ble.py`）：uint8/uint16 BPM、RR 的 1/1024 秒解析度、
  完整 flag 組合、超生理範圍 RR 丟棄、截斷封包拋錯、依 RSSI 挑裝置、hub 流水線、stale 判定、設定檔載入。
- **校準行為正確性**（`tests/test_adaptive_calibration.py`）：offset 收斂到真殘差、系統性偏移收斂而非誤判
  分歧、超上限觸發分歧旗標、心跳帶不新鮮/無接觸時拒絕、離群排除、最短間隔節流、視窗裁舊、
  `live_version` 套用當前 offset。

**多重品質保障機制**：

- **接觸雙重把關**：`belt_contact_ok = contact_detected or not contact_supported`（`main_window.py:1249`）——
  只有「聲明支援且偵測失敗」才判不合格，避免不支援該功能的裝置被誤殺；不合格樣本整批拒收。
- **離群過濾**：`max_pair_bpm_gap=40` 排除 rPPG 鎖到諧波或心跳帶假影的配對。
- **統計穩健**：中位數殘差抗離群、`pstdev` 計信心分級、EMA 低增益（0.08）平滑收斂。
- **offset 上限**：`±25` 防異常真值把 rPPG 拉歪；無法校平時 `diverged` 明確警示而非靜默套錯。
- **落地門檻**：`confidence != LOW` 且 `accepted_observations ≥ 12` 才寫入新版本，避免低品質 session 污染。

**誠實限制**：沒有「對照臨床心電圖的絕對精準度基準測試」。`compute_mae`（`calibration.py:201`）屬手動校準
session 用途，非自動化 accuracy benchmark。測試保證的是「校準邏輯正確」而非「絕對誤差 ≤ X BPM」；
後者需真人配戴實測。

---

## 7. 心跳帶對疲勞分數的影響（誠實揭露）

**結論：心跳帶原始數值不進疲勞融合，但有一條透過 rPPG 自身校準值的間接弱路徑，上限約 4.5%。**

- **直接（不進）**：`gui/fatigue_scorer.py`、`gui/fatigue_engine.py` 全文搜尋 `belt`/`WatchHrHub`/`hr_belt`
  **零匹配**（已 Grep 驗證）。`FatigueFuser` 只讀 rPPG 引擎傳入的 `RppgMetrics`，完全不碰 `BeltRuntime`/hub。
  多處註解與文件佐證（`main_window.py:295`、`adaptive_calibration.py:5`、`CLAUDE.md`）。
- **間接（弱）**：`_rppg_sub_score()`（`fatigue_scorer.py:222`）算 BPM 偏離時取 `r.bpm_calibrated`，
  而校準啟用時該值已被心跳帶推導的 offset 修正。權重極小：rPPG 子權重 `0.30`（`:53`）× 整體 pillar 權重
  `0.15`（`:46`）＝總分約 **4.5%**，且僅在 BPM 偏離 60–100 正常區間時非零。此比例已由
  `docs/history/2026-07-03-project-audit.md` 對抗驗證審核獨立確認。
- **佐證**：`rppg/watch_adapter.py:1` 標註「手錶融合模式已移除，本模組目前無生產呼叫者」——
  唯一可能讓心跳帶原始數值偽裝成 rPPG 指標進融合的介面，目前只存在於單元測試，未接入生產流程。

**建議表述**：「心跳帶原始數值不參與疲勞判斷；它只優化 rPPG 心率準確度，而 rPPG 心率在融合分數裡僅佔約
4.5%，因此心跳帶對疲勞分數的間接影響上限就是這 4.5%。」

---

## 8. 用了什麼技術、參考了什麼文獻

**技術**：BLE GATT notify 訂閱、asyncio 背景 event loop、中位數殘差濾除離群、低增益 EMA 平滑、
版本化校準持久化（bias 模型 `scale*bpm+offset`）。

**參考文獻／規範**（皆為 repo 文件明載出處，非訓練記憶）：

| 文獻／規範 | 參考了它的什麼 | 出處 |
|---|---|---|
| Bluetooth SIG, *Heart Rate Service 1.0* | `0x180D`/`0x2A37` 封包格式與 flags byte 解析依據 | `docs/technical/heart_rate_belt_bluetooth_gatt_profile.md:194`、`hr_belt_ble.py:4` |
| Bluetooth SIG, *GATT Specification Supplement* | `0x2A38` Body Sensor Location 值定義 | 同文件 `:195` |
| Wang, den Brinker, Stuijk & de Haan (2017), *Algorithmic Principles of Remote PPG*, IEEE TBME, doi:10.1109/TBME.2016.2609282 | POS 演算法／RGB 投影抽脈搏訊號（文件誠實標註實作實際偏 CHROM） | `docs/technical/rppg_heart_rate_calibrator_technical_analysis.md:316`、`rppg_technical_report_v2.md:324` |
| de Haan & Jeanne (2013), CHROM, IEEE TBME | 色度法抽 rPPG 訊號 | `docs/history/2026-07-03-fatigue-methodology-and-references.md:89` |
| Welch (1967), doi:10.1109/TAU.1967.1161901 | Welch PSD 求 BPM 峰值 | 方法學文件 |
| Butterworth (1930) | 帶通濾波器設計依據 | 方法學文件 |
| Task Force ESC/NASPE (1996), HRV Standards | RMSSD/SDNN/LF-HF 定義（供 RR-Interval 的 HRV 比對） | 方法學文件 |
| Bland & Altman (1986) | 校準器 bias／一致性界限方法論（文件自陳 Bland-Altman plot 尚未實作） | `docs/technical/rppg_heart_rate_calibrator_technical_analysis.md` |

**明確未查到引用（避免誤植）**：

- Bluetooth SIG「Heart Rate **Profile**」（profile 層規範本身）：僅查到 Service 1.0 與 GATT Supplement。
- 心跳帶硬體官方 datasheet：來源為使用者私人 PDF，無公開連結。
- **線上自適應校準（EMA offset 收斂）演算法本身：無學術文獻依據，屬工程設計決定。**
  即：校準的「訊號處理環節」（rPPG 抽訊號、PSD、HRV）有文獻背書，「線上調整策略」是自製的。

---

## 附錄：關鍵檔案索引

| 檔案 | 職責 |
|---|---|
| `rppg/hr_belt_ble.py` | BLE 掃描/連線/訂閱、`2A37`/`2A38`/`2A19` 解析、`HrBeltBleClient` 背景執行緒、stale 判定 |
| `rppg/adaptive_calibration.py` | `OnlineBpmCalibrator` 線上自適應 offset 微調（純運算） |
| `rppg/calibration.py` | bias 模型、`CalibrationVersionStore` 版本存檔/套用、原始 BPM 取值 |
| `rppg/calibration_watch.py` | `WatchHrHub` / `WatchSample` 共用資料結構（HRV 預留接口） |
| `gui/belt_runtime.py` | `BeltRuntime`：hub + belt client 與 GUI 之間唯一介面 |
| `gui/main_window.py` | GUI 勾選框啟停、每秒輪詢校準、狀態列/dashboard 警示、版本落地 |
| `scripts/hr_belt_monitor.py` | 免 GUI 診斷腳本 |
| `tests/test_hr_belt_ble.py` / `tests/test_adaptive_calibration.py` | 協定與校準行為單元測試 |
| `docs/technical/heart_rate_belt_bluetooth_gatt_profile.md` | 實機 GATT 逐特徵對照與 Bluetooth SIG 規範連結 |
