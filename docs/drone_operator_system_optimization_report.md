# 無人機操作員疲勞監測系統優化建議報告

更新日期：2026-06-11

本報告整理本專案在完成基本 GUI、MediaPipe 臉部特徵、rPPG、疲勞分數、SQLite 紀錄、Web dashboard 與 UTA-RLDD replay 後，除了持續收集驗證資料之外，還應優先進行的系統優化方向。核心觀點是：本系統下一階段不應只追求「更多資料」或「更高分數」，而應強化可信度、穩定性、流程整合、可解釋性與實際部署能力，讓系統從技術 demo 提升為可支援無人機操作安全管理的工程原型。

## 1. 優化目標

目前系統已具備即時臉部偵測、疲勞行為分析、rPPG 生理趨勢、錄影、資料庫與回放測試能力。下一階段優化目標應設定為：

- 讓系統知道「什麼時候可以相信輸出」。
- 讓使用者知道「疲勞分數為什麼上升」。
- 讓無人機任務流程能自然使用這套工具。
- 降低低頭、說話、眼鏡反光、光線不足與相機延遲造成的誤判。
- 讓任務後能產生可回顧、可稽核、可調校的報告。

因此，優化主軸可分為五類：

- 可信度與品質控管。
- 個人化校準與基準線。
- 飛前、飛中、飛後流程整合。
- 誤報與漏報情境修正。
- 報告、隱私與部署穩定性。

## 2. 第一優先：可信度與品質控管

疲勞監測系統不能只輸出一個分數。若使用者不知道目前畫面品質、臉部特徵穩定度與 rPPG 訊號是否可信，疲勞分數很容易被誤解。建議將系統輸出從單純分數改為：

```text
疲勞狀態 + 信心等級 + 造成分數上升的原因 + 資料品質診斷
```

例如：

```text
狀態：LOW_VIGILANCE
信心：中
原因：PERCLOS 上升、眨眼時間變長、低頭事件增加
rPPG：低可信，因光線不足暫不參與融合
```

### 2.1 建議新增或強化的品質指標

- 臉部偵測穩定度：連續 frame 是否穩定偵測到臉。
- Landmark 穩定度：眼睛、嘴巴、臉部 ROI 是否抖動過大。
- 頭部姿態品質：pitch、yaw、roll 是否超過可判讀範圍。
- 亮度與曝光品質：畫面是否太暗、過曝或曝光快速變化。
- 相機 FPS 品質：實際 FPS 是否低於演算法假設。
- rPPG SQI：心率與 HRV 趨勢是否有足夠品質。
- 有效輸出比例：任務中有多少時間可產生可信判讀。

### 2.2 建議 UI 顯示方式

GUI 與 Web dashboard 應避免只用單一大分數。建議加入：

- 狀態標籤：OK、LOW_VIGILANCE、DROWSY、CRITICAL、LOW_QUALITY。
- 信心等級：高、中、低。
- 主要原因：閉眼、長眨眼、低頭、哈欠、rPPG 壓力趨勢、品質不足。
- 品質燈號：Face、Eye、Pose、rPPG、Camera。
- 當品質不足時，顯示「目前資料品質不足，暫停高信心判讀」。

這能讓系統更誠實，也能降低老師或使用者看到異常分數時的疑問。

## 3. 第二優先：疲勞基準值、文獻依據與校準

疲勞偵測最大挑戰之一是個人差異。眼型、眨眼頻率、眼鏡、坐姿、臉部角度與平常心率都會不同。若使用固定門檻判斷所有人，容易造成誤報或漏報。經閱讀 `docs/` 內既有報告與目前程式碼後，可以確認本系統不是憑空設定一個疲勞分數，而是把文獻中常見的眼部閉合、眨眼時序、長閉眼、視線穩定、頭部姿態與 rPPG 輔助訊號，轉換成可即時運作的規則式工程基準。

但也必須精準說明：文獻足以支持「這些特徵可用於疲勞/嗜睡風險監測」，目前 UTA-RLDD 回放也證明「資料處理與人臉偵測管線穩定」，但還不足以宣稱「現有門檻已可可靠分類無人機操作員疲勞」。目前最合理的定位仍是可解釋疲勞監測原型與驗證資料管線。

### 3.1 建議校準內容

- EAR 清醒基準：建立個人睜眼與閉眼門檻。
- 眨眼時長基準：建立清醒狀態下的眨眼時間、振幅與睜眼速度。
- PERCLOS 初始基準：確認清醒狀態下閉眼比例。
- 頭部姿態基準：記錄操作員正常看螢幕或看遙控器時的姿態。
- 嘴部開合基準：降低說話、咬合、張嘴與哈欠混淆。
- rPPG 基準：記錄初始 BPM、HRV 趨勢與訊號品質。

### 3.2 目前系統實際使用的疲勞基準值

目前實作主要來自 `gui/fatigue_engine.py` 與 `gui/fatigue_scorer.py`，可整理如下。

| 類別 | 目前基準值或邏輯 | 判讀意義 |
| --- | --- | --- |
| EAR 校準 | 啟動後 `calib_sec=5.0` 秒，至少 `min_calib_samples=20` 筆；閉眼門檻為個人 EAR 中位數乘上 `thresh_ratio=0.75`，不足時 fallback `base_th_default=0.18` | 不使用單一固定 EAR，先建立個人開眼基準 |
| 閉眼開啟遲滯 | `closed_open_hyst=1.06` | 避免眼睛開合在門檻附近抖動造成重複觸發 |
| PERCLOS | `perclos_window_sec=60.0` 秒 sliding window | 以一段時間內眼睛閉合比例估計警覺度下降 |
| 低警覺 PERCLOS | `low_vigilance_perclos_th=0.10` | 早期提醒工程門檻，不等於醫療診斷 |
| 明顯嗜睡 PERCLOS | `tired_perclos_th=0.25` | `DROWSY` 狀態主要門檻 |
| 長閉眼 | `long_closed_sec=1.5` 秒 | 觸發 `CRITICAL` 危急閉眼事件 |
| 眨眼事件 | `blink_min_sec=0.08` 到 `blink_max_sec=0.45` 秒 | 排除太短雜訊與太長閉眼，把有效 blink 納入基準 |
| 眨眼時序 baseline | 前 `blink_feature_calib_count=12` 次有效 blink 建立 duration、amplitude、opening velocity baseline | 用個人眨眼型態偏移偵測低警覺 |
| 眨眼時序警示 | `blink_duration_warn_z=1.5`、`blink_opening_velocity_warn_z=-1.5`，`blink_temporal_score >= 0.45` 進入早期警示條件 | 眨眼變長或睜眼速度變慢時提高低警覺分數 |
| 瞇眼 | `squint_ear_ratio=1.35`，持續 `squint_min_sec=3.0` 秒 | 長時間低 EAR 但非完整閉眼時視為早期疲勞/眼部負荷訊號 |
| 凝視與掃視 | `gaze_fixed_alert_sec=5.0`、`fixation_duration > 15.0`、低 saccade frequency | 作為早期警示輔助，不能單獨判定嗜睡 |
| 頭部姿態 | pitch 以 60 筆樣本建立 offset；`head_pitch_down_th=-15.0`、`head_microsleep_sec=1.5` | 用於點頭/微睡眠輔助判斷 |
| 哈欠 | `mar_yawn_th=0.60`、`mar_yawn_dur_sec=1.5`，搭配 mouth blendshape | late-stage 輔助，權重低，避免說話誤判 |
| 品質 gate | face area、roll、yaw ratio、nose speed、lid balance、mouth open noise；例如 fatigue face area 至少 `0.06`，roll 不超過 `25` 度 | 品質不足時降低或停止高信心判讀 |
| 行為/生理融合 | 行為疲勞 `behavior_weight=0.85`，rPPG `rppg_weight=0.15`；rPPG 需 SQI、quality 與 ROI 數足夠才參與 | 目前以行為疲勞為主，rPPG 僅作輔助 |

狀態分級目前如下：

| 狀態 | 主要觸發 |
| --- | --- |
| `OK` | 已校準，主要疲勞特徵未達警示 |
| `LOW_VIGILANCE` | PERCLOS >= 0.10、blink temporal score >= 0.45、瞇眼、凝視、皺眉或 blendshape 輔助訊號 |
| `DROWSY` | PERCLOS >= 0.25 |
| `CRITICAL` | 連續閉眼 >= 1.5 秒 |
| `MICROSLEEP` | head nod / microsleep rule 觸發，優先級最高 |

目前 `fatigue_level` 是工程加權分數，不是文獻直接給定的單一標準。程式中主要權重為：PERCLOS 0.40、micro/nod 0.30、blink temporal 0.10、squint 0.15，其他如皺眉、凝視、blendshape 與 yawn 為小權重輔助。融合器則另以 PERCLOS、blink temporal、microsleep、gaze、squint、yawn 等子分數計算行為 pillar，再與可用的 rPPG pillar 合併。

### 3.3 文獻支持程度判斷

目前技術路線不是憑空想像，文獻支持可分成三層：

1. **高度支持的特徵方向**：PERCLOS 是疲勞/嗜睡被動偵測中長期使用且驗證較多的指標；EAR 與 facial landmarks 可用一般相機估計眼睛開合與眨眼；UTA-RLDD 提供 Alert、Low Vigilant、Drowsy 三類長影片，支持用時序特徵而非單張影像判斷早期嗜睡。
2. **中度支持但需場域校正的工程門檻**：PERCLOS 0.10/0.25、長閉眼 1.5 秒、blink temporal z-score、凝視與掃視頻率等門檻，符合文獻方向與工程安全邏輯，但不是所有場景通用的保證值。這些門檻必須用本專案資料與無人機操作情境校正。
3. **目前只能作輔助的訊號**：rPPG、皺眉、視線穩定、哈欠與頭部姿態都能提供風險線索，但容易受到光線、任務負荷、說話、轉頭查看現場與相機品質影響，因此不應單獨作為疲勞主判定。

換句話說，目前可以篤定的是「使用這些特徵做疲勞風險監測有文獻與工程依據」；還不能篤定的是「現有固定門檻已經能在無人機操作員場域達到可靠分類」。報告與簡報應避免把系統包裝成高準確率分類器，應強調它是可解釋、可回放、可調校的疲勞監測原型。

### 3.4 UTA-RLDD 回放系統目前證明了什麼

本專案新增的 UTA-RLDD 回放系統會把資料集影片當成離線鏡頭，逐幀輸入 MediaPipe Face Landmarker，再輸出疲勞行為特徵、rPPG 指標、融合分數、SQLite 與 CSV 報表。這套系統的價值是建立可重現的驗證與門檻校正資料管線。

目前 docs 紀錄的最新 36 支影片測試結果顯示：

- 影片處理完成率 100%。
- 三類影片平均人臉偵測率約 99.93%。
- Drowsy 類別的平均 PERCLOS 與最高 PERCLOS 較高，嗜睡/危急 frame 比例也高於 Alert 與 Low Vigilant。
- 但平均疲勞分數與融合分數沒有隨 `0 -> 5 -> 10` 單調上升。
- Alert 類別 `LOW_VIGILANCE` 偏高，表示早期警示誤報風險仍存在。
- Drowsy 影片若沒有明顯長閉眼或 PERCLOS 上升，現有規則可能漏報。

因此，UTA-RLDD 目前最有力的證據是「管線穩定、可大量回放、可產生可稽核指標」，不是「疲勞分類已可靠」。這一點需要在優化報告、畢專報告與簡報中保持一致。

### 3.5 目前還缺少什麼

經閱讀既有報告後，最需要補上的不是單純更多影片，而是更精準的驗證設計：

- 有效 frame 分母：summary 應分開列出全影片、face-detected、post-calibration、behavior-available 等分母，避免 `CALIBRATING` 或 `NO_FACE` 稀釋平均值。
- Replay calibration 隔離：UTA-RLDD replay 不應讀到真人 webcam 的持久化 blendshape baseline，建議建立 replay 專用 calibration namespace 或在 replay 模式停用持久化校準。
- 門檻 sweep：用 UTA-RLDD 與自錄標註資料批次掃描 PERCLOS、blink temporal、LOW_VIGILANCE 條件與融合權重，輸出 false alarm rate、miss rate、Drowsy recall 與 Alert 誤報率。
- 逐事件標註：UTA-RLDD label 是整段影片類別，不是逐幀 ground truth；若要調長閉眼、哈欠、低頭、轉頭或凝視，仍需要自己標註事件時間。
- 無人機場域資料：目前文獻多來自汽車駕駛或一般嗜睡資料集，仍缺少無人機操作員看遙控器、看平板、看天空、轉頭觀察現場、任務壓力上升等專用情境。
- 原因碼輸出：每次 `LOW_VIGILANCE`、`DROWSY` 或 `CRITICAL` 應記錄觸發原因，例如 PERCLOS、blink temporal、long closed、gaze 或 quality issue，方便回放時確認判斷是否合理。
- 報告一致性：技術報告、優化報告與簡報要使用同一套說法：目前是疲勞監測原型與驗證管線，不是已完成泛化驗證的三分類模型。

### 3.6 建議校準流程

飛前先進行 30 到 60 秒校準，系統檢查：

- 臉部是否位於鏡頭可判讀位置。
- 光線是否穩定。
- 眼睛與嘴部特徵是否可用。
- rPPG 是否有足夠品質。
- 操作員是否處於明顯低品質或疑似疲勞狀態。

校準完成後，系統不只記錄固定門檻，而是記錄「個人清醒基準」。後續任務中應判斷偏離程度，而不是只判斷是否超過全域門檻。

## 4. 第三優先：整合無人機任務流程

如果系統只是即時顯示疲勞分數，會比較像一般臉部偵測 demo。要凸顯無人機應用價值，建議把系統包裝成三階段流程：

```text
飛前檢查 -> 任務中監測 -> 飛後報告
```

### 4.1 飛前檢查

飛前檢查應包含：

- 相機、FPS、解析度與後端確認。
- 臉部可見度與光線品質。
- 個人化 baseline 是否完成。
- 初始疲勞狀態是否偏高。
- 是否建議重新校準、休息或更換操作員。

這能補足傳統無人機飛前檢查只看機體、電池、GPS、空域與天氣，較少檢查操作員狀態的缺口。

### 4.2 任務中監測

任務中應避免過度干擾操作員。建議採用分級提醒：

- 低風險：只記錄，不跳出干擾。
- 中風險：以小型提示提醒注意狀態。
- 高風險：提示休息、換手或暫停任務。
- 低品質：提示調整光線、坐姿或相機位置。

提醒內容應清楚說明原因，例如「長閉眼事件增加」比「疲勞分數過高」更容易被接受。

### 4.3 飛後報告

飛後報告是本系統很重要的差異化。建議輸出：

- 任務總時長。
- 有效判讀比例。
- 平均疲勞分數與最高疲勞分數。
- 低警覺、嗜睡、低品質時間比例。
- 高風險事件時間軸。
- rPPG 可用比例與品質趨勢。
- 操作員自評疲勞與系統分數對照。
- 建議下次改善事項，例如光線、相機角度、休息時間。

這能讓系統從即時偵測工具變成任務安全回顧工具。

## 5. 第四優先：降低誤報與漏報

疲勞系統最重要的不是單次分數好看，而是避免常見情境誤判。建議建立「情境測試清單」，逐項驗證。

### 5.1 低頭看遙控器與打瞌睡低頭

無人機操作員常低頭看遙控器、平板或地面站。系統不能只因低頭就判定疲勞。建議加入：

- 低頭是否伴隨長閉眼。
- 低頭後是否快速恢復注視。
- 視線是否仍在任務螢幕或遙控器區域。
- 低頭事件是否頻繁且持續變長。

### 5.2 說話張嘴與哈欠

哈欠不能只看嘴巴張大，因為操作員可能說話、下指令或與旁人溝通。建議哈欠判斷需要同時滿足：

- 嘴部開合比例夠大。
- 持續時間夠長。
- 眼部狀態或臉部表情有疲勞輔助訊號。
- 不在短時間連續語音溝通情境中直接判高風險。

### 5.3 轉頭觀察現場與注意力不集中

民用無人機常需要觀察天空、旁人、障礙物與現場環境。轉頭不一定是疲勞。建議把轉頭視為品質或任務行為訊號，不直接視為疲勞主因。

### 5.4 眼鏡反光與光線不足

眼鏡反光、背光、暗光和自動曝光變化會造成眼部與 rPPG 不穩。建議：

- 眼部品質低時降低 EAR/PERCLOS 權重。
- rPPG 品質低時不參與融合分數。
- 顯示明確的低品質原因。
- 允許操作員重新校準或調整鏡頭。

## 6. 第五優先：任務情境標記

除了收集驗證資料，還應收集任務情境資料。疲勞不是只由臉部表情決定，也與任務時間、環境、壓力與工作安排有關。

建議每次任務記錄：

- 任務類型：訓練、巡檢、農業、搜救、測繪、空拍。
- 第幾趟飛行。
- 飛行前等待時間。
- 飛行時長與任務總時長。
- 是否戶外、高溫、夜間或強光。
- 是否發生警報、失誤、返航或通訊中斷。
- 操作員自評疲勞程度。
- 是否換手或休息。

這些資料會讓後續分析更有價值，因為可以回答「什麼情境下疲勞風險上升」，而不只是回答「這張臉看起來累不累」。

## 7. 第六優先：Web dashboard 與報告輸出

目前系統已有 Web dashboard 與 SQLite 紀錄，這是重要優勢。建議進一步強化成任務報告平台。

### 7.1 Dashboard 建議

- 疲勞分數趨勢圖。
- PERCLOS、眨眼、長閉眼事件圖。
- rPPG BPM、HRV 與 SQI 圖。
- 品質分數趨勢圖。
- 高風險事件時間軸。
- 低品質原因統計。
- 可依任務、操作員、日期與場景篩選。

### 7.2 匯出報告建議

建議支援一鍵匯出：

- 任務摘要 PDF。
- CSV 指標資料。
- 高風險事件列表。
- 低品質片段列表。
- 系統版本與設定檔摘要。

這有助於口試展示、教學回顧、演算法調校與後續研究。

### 7.3 UTA-RLDD CSV 可視化報表

已新增 UTA-RLDD summary CSV 的可視化報表流程。Replay 批次完成後會輸出 `utarldd_visual_report_<timestamp>.html`，也可用 `scripts/utarldd_csv_report.py` 將既有 `utarldd_summary_<timestamp>.csv` 轉成單檔 HTML 報表。報表內容包含：

- 總覽卡片：影片總數、完成數、平均人臉偵測率、Alert 誤報風險、Drowsy 漏報風險與有效幀不足數量。
- Label 分組圖表：平均 PERCLOS、最高 PERCLOS、95 分位融合分數、低警覺比例、嗜睡/危急比例、行為有效率與低品質比例。
- 逐影片表格：快速判讀、標籤對齊判讀、主要判斷依據、建議修正方向與優化旗標。

這份 HTML 報表的目的不是取代 validation report，而是讓使用者能快速回答三個問題：系統這次主要靠哪些數值判斷疲勞、哪些影片可能是誤報或漏報、下一輪門檻調整應優先看哪一類特徵。

## 8. 第七優先：相機與部署穩定性

實際使用時，最常出問題的往往不是疲勞演算法，而是相機與環境。OpenCV `VideoCapture` 支援不同平台與後端，但 Windows、Ubuntu、DirectShow、MSMF、V4L2、FFMPEG 的行為可能不同。

建議優化：

- 啟動時顯示實際 FPS、解析度、後端與延遲。
- 自動偵測黑畫面、低亮度與過曝。
- 顯示相機是否持續掉 frame。
- Linux 保持 V4L2 流程，Windows 保持 DirectShow/MSMF 流程，不混用平台邏輯。
- 提供相機診斷報告，方便現場排錯。
- 避免分析端與 GUI 預覽端堆積舊 frame。

這類優化會直接提升展示穩定性，也能降低系統在不同電腦上失效的風險。

## 9. 第八優先：資料隱私與倫理

本系統會拍攝臉部、推估心率趨勢、記錄疲勞狀態，這些都可能涉及個人資料與被評價風險。即使是畢業專題，也應建立基本資料治理。

建議補足：

- 測試前告知受測者會收集哪些資料。
- 明確區分是否保存原始影片。
- 若只需研究指標，優先保存去識別化資料。
- 匯出資料時移除姓名、學號、裝置序號等個資。
- SQLite 與錄影檔不要放入公開 repo。
- 報告中說明系統不作為醫療診斷、懲處或單一安全決策依據。

這能讓系統在訓練與研究場域更容易被接受。

## 10. 建議實作優先順序

### 10.1 短期優化

短期目標是讓展示與報告更可信。

- 新增 UTA-RLDD replay 的有效 frame 分母：全影片、face-detected、post-calibration、behavior-available 分開統計。
- 隔離 replay calibration：避免資料集回放讀到本機真人 webcam 的持久化 baseline。
- 新增狀態觸發原因碼：記錄每次 `LOW_VIGILANCE`、`DROWSY`、`CRITICAL` 的主要原因。
- 製作門檻 sweep 報表：比較 PERCLOS、blink temporal、長閉眼與融合權重對 Alert 誤報和 Drowsy 漏報的影響。
- 新增疲勞分數的原因解釋。
- 強化品質 gate 與信心等級。
- 飛前校準流程可視化。
- 任務後摘要報告。
- 相機 FPS、亮度、臉部品質診斷。

### 10.2 中期優化

中期目標是讓系統更適合實際無人機任務。

- 建立無人機操作情境標註資料：清醒監控、低頭看遙控器、轉頭看天空、長時間凝視螢幕、閉眼、打哈欠、說話、眼鏡反光與光線變化。
- 用 false alarm rate per hour、miss rate、Drowsy recall、低警覺提前量作為門檻調校指標。
- 加入任務情境標記。
- 建立誤報/漏報情境測試集。
- 強化 dashboard 趨勢圖與事件時間軸。
- 讓低頭看遙控器、說話張嘴、轉頭觀察現場不被直接誤判。
- 建立操作員自評疲勞與系統分數對照。

### 10.3 長期優化

長期目標是讓系統具備研究與部署延伸能力。

- 多操作員長期趨勢分析。
- 不同任務類型的門檻調整。
- 半自動門檻校正工具。
- 匿名化資料集管理。
- 未來支援 BVLOS 或多機監控中心的人因風險管理。

## 11. 可放入簡報的重點句

本系統下一階段不只需要更多驗證資料，更需要優化「可相信、可解釋、可回顧、可部署」四個面向。具體來說，系統應從單純輸出疲勞分數，進一步提供信心等級、品質診斷、疲勞原因、飛前校準、任務中分級提醒與飛後報告。現有 PERCLOS、EAR、眨眼時序、長閉眼與 UTA-RLDD 三階段資料集有文獻依據，證明技術路線不是憑空想像；但目前門檻仍是工程基準，必須透過有效 frame 分母、replay calibration 隔離、門檻 sweep 與無人機場域標註資料校正。這樣才能把技術 demo 提升為無人機操作員人因安全輔助平台。

## 12. 結論

本專案已具備疲勞監測原型的主要功能，但下一階段的核心不只是增加資料量，而是讓系統在真實使用情境下更可信、更穩定、更容易解釋。建議優先優化信心等級、品質 gate、個人化 baseline、UTA-RLDD replay 有效分母、replay calibration 隔離、門檻 sweep、飛前/飛中/飛後流程、誤報漏報情境處理、dashboard 報告輸出、相機穩定性與資料隱私。

若能完成上述優化，系統的定位會更清楚：它不是單純的臉部疲勞偵測程式，也不是已完成泛化驗證的高準確率分類器，而是一套可支援民用專業無人機訓練、巡檢、演練與研究的人因安全輔助平台。

## 13. 參考資料

1. Google AI Edge, MediaPipe Face Landmarker  
   https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker  
   參考用途：臉部 landmarks、blendshape scores、facial transformation matrices 與影片/即時影像輸入能力。

2. OpenCV, cv::VideoCapture Class Reference  
   https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html  
   參考用途：跨平台相機擷取、相機後端與影像來源管理。

3. FAA, Summary Final Report for Unmanned Aircraft Systems in Air Carrier Operations: UAS Operator Fatigue, 2021  
   https://www.faa.gov/sites/faa.gov/files/data_research/research/med_humanfacs/oamtechreports/202116.pdf  
   參考用途：UAS 操作員疲勞、工作負荷、值勤與人因安全脈絡。

4. CDC/NIOSH, Work Schedules: Shift Work and Long Work Hours  
   https://www.cdc.gov/niosh/work-hour-training-for-nurses/longhours/index.html  
   參考用途：長工時、輪班、疲勞風險與工作安排管理脈絡。

5. Tereza Soukupova and Jan Cech, Real-Time Eye Blink Detection using Facial Landmarks, 2016  
   https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf  
   參考用途：EAR 六點眼睛模型與 facial landmarks 眨眼偵測思路。

6. PERCLOS-based technologies for detecting drowsiness: current evidence and future directions, Sleep Advances, 2023  
   https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/  
   參考用途：PERCLOS 作為嗜睡偵測指標的證據、限制與未來方向。

7. Reza Ghoddoosian, Marnim Galib, Vassilis Athitsos, A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection, CVPR Workshops, 2019  
   https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html  
   參考用途：UTA-RLDD、Alert / Low Vigilant / Drowsy 三階段標籤與長影片早期嗜睡偵測。

8. National Highway Traffic Safety Administration, Assessment of Drowsy Driver Algorithms  
   https://www-nrd.nhtsa.dot.gov/departments/Human%20Factors/810594/pages/AppC.htm  
   參考用途：PERCLOS、長閉眼與嗜睡行為觀察的工程評估背景。
