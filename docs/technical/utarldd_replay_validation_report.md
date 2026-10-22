# UTA-RLDD 影片回放驗證系統技術報告

更新日期：2026-06-16

本報告說明本專案 UTA-RLDD 影片回放驗證系統的目的、資料流程、回測方法、可信度來源、演算法與輸出報表。此系統的核心功能，是把 UTA-RLDD 資料集影片當成「可重現的離線鏡頭」，逐幀送入本專案正式使用的 MediaPipe、疲勞分析、rPPG 與融合分數流程，輸出 SQLite、CSV、validation report、manifest 與 HTML 可視化報表。

本系統不是新訓練一個疲勞模型，也不是把資料集 label 直接當逐幀 ground truth。它的定位是：建立一套可重現、可稽核、可比較的回放驗證資料管線，協助判斷目前疲勞門檻是否合理、哪些影片有誤報或漏報風險、下一輪應優先優化哪些特徵。

## 1. 系統目的

目前專案主軸是無人機操作員疲勞與警覺度監測，但短期內難以大量募集真實無人機操作員、長時間任務與人工標註資料。因此，本專案使用 UTA-RLDD 作為早期回放驗證資料。UTA-RLDD 提供 Alert、Low Vigilant、Drowsy 三類長影片，可用來觀察本系統的 PERCLOS、眨眼時序、疲勞狀態比例與融合分數是否呈現合理趨勢。

回放驗證系統要回答的問題不是「分類準確率是否已經很高」，而是：

- 影片能否穩定被處理完成。
- MediaPipe 人臉偵測是否穩定。
- 疲勞特徵是否能被逐幀記錄。
- rPPG 品質與 ROI 是否可用。
- Drowsy 類影片是否比 Alert 類影片出現更多疲勞證據。
- 哪些影片可能造成 Alert 誤報或 Drowsy 漏報。
- 下一輪應調整 PERCLOS、眨眼時序、品質 gate 或融合權重的哪一部分。

## 2. 系統入口與實作位置

主要實作檔案：

- `gui/utarldd_replay.py`：回放核心，負責影片探索、逐幀處理、指標記錄、CSV/HTML 報表與 GUI worker。
- `scripts/utarldd_replay.py`：CLI 入口，可批次處理 UTA-RLDD 資料夾。
- `scripts/utarldd_csv_report.py`：將既有 summary CSV 轉成單檔 HTML 可視化報表。
- `gui/metrics_recorder.py`：SQLite 逐幀指標紀錄器。
- `gui/fatigue_engine.py`：行為疲勞與警覺度特徵計算。
- `rppg/rppg_worker.py`：rPPG ROI、POS 訊號、BPM、HRV 與品質診斷。
- `gui/fatigue_scorer.py`：行為疲勞與 rPPG 輔助訊號融合。

CLI 使用方式：

```bash
.venv/bin/python -m scripts.utarldd_replay <dataset_root> --jobs 4
```

從既有 CSV 產生 HTML 可視化報表：

```bash
.venv/bin/python scripts/utarldd_csv_report.py recordings/utarldd_runs/<timestamp>/utarldd_summary_<timestamp>.csv
```

已驗證的既有回測轉換範例：

```powershell
.\.venv\Scripts\python.exe scripts\utarldd_csv_report.py recordings\utarldd_runs\20260607_122601\utarldd_summary_20260607_122601.csv
```

輸出檔案為 `recordings/utarldd_runs/20260607_122601/utarldd_visual_report_20260607_122601.html`。

## 3. 回放資料如何被發現與分類

`discover_utarldd_videos()` 會遞迴掃描指定資料夾，尋找 `.mov`、`.MOV`、`.mp4` 影片。系統用影片檔名判斷 label：

| 檔名 | 資料集標籤 | 類別意義 |
| --- | --- | --- |
| `0.mov` / `0.mp4` | `0` | Alert |
| `5.mov` / `5.mp4` | `5` | Low Vigilant |
| `10.mov` / `10.mp4` | `10` | Drowsy |

受試者 ID 由影片所在資料夾名稱取得，例如 `01/0.mov` 代表 subject `01` 的 Alert 影片。系統排序規則為 subject、label、檔名，確保每次批次回放順序一致。

這個設計的好處是：

- 不需要手動建立影片清單。
- 可用 `--subject` 或 `--label` 篩選特定受試者或類別。
- 同一資料夾重跑時順序固定，利於 A/B 比較。

## 4. 影片如何被當成離線鏡頭

每支影片由 OpenCV `VideoCapture` 開啟，讀取：

- FPS。
- 影片寬度。
- 影片高度。
- frame count。
- codec FourCC。

回放系統不是用真實時間睡眠等待，而是用影片 frame index 與 FPS 建立 deterministic timestamp：

```text
timestamp_sec = (frame_index - 1) / fps
timestamp_ms = max(previous_timestamp_ms + 1, int(timestamp_sec * 1000))
```

這樣做有三個目的：

1. **可重現**：同一支影片每次回放會得到相同時間軸。
2. **符合 MediaPipe VIDEO mode**：MediaPipe `detect_for_video()` 需要單調遞增的毫秒 timestamp。
3. **保留時序演算法意義**：PERCLOS、眨眼時間、rPPG buffer、fixation duration 與融合分數 trend 都依影片時間計算，而不是依電腦跑得快慢計算。

## 5. 單支影片回放流程

單支影片的核心流程如下：

```text
OpenCV VideoCapture 讀取影片
  -> 逐幀讀取 BGR frame
  -> BGR 轉 RGB
  -> MediaPipe Image
  -> Face Landmarker detect_for_video()
  -> 若有臉：
       -> FatigueEngine 計算 EAR/PERCLOS/眨眼/視線/頭部/哈欠
       -> collect_rppg_roi_sample() 擷取額頭、雙頰、眉間 ROI
       -> RppgEngine 更新 POS/rPPG buffer 與品質指標
       -> FatigueFuser 融合行為疲勞與 rPPG 輔助分數
       -> MetricsRecorder 寫入 SQLite
       -> 更新 summary 統計
  -> 若無臉：
       -> 重設 ROI tracker 與 rPPG buffer
       -> FatigueEngine on_no_face()
       -> 記錄 NO_FACE 與融合不可用狀態
  -> 批次結束後輸出 CSV、HTML、manifest
```

重要的是，回放系統重用正式即時系統的 `FatigueEngine`、`RppgEngine`、`FatigueFuser` 與 `MetricsRecorder`，而不是另寫一套離線判斷邏輯。這讓回放結果更能代表實際 GUI 執行時的行為。

## 6. 使用 MediaPipe Face Landmarker 的原因

本系統使用 MediaPipe Face Landmarker，原因如下：

- 可輸出臉部 3D landmarks，用於 EAR、MAR、gaze、head pose 與 rPPG ROI。
- 可輸出 blendshape scores，用於眨眼、瞇眼、眉部與嘴部輔助判斷。
- 可輸出 facial transformation matrices，用於姿態診斷與 ROI 補償。
- 支援 `RunningMode.VIDEO`，適合處理影片連續 frame。

在回放中，Face Landmarker 使用 VIDEO mode 的 `detect_for_video()`。這讓模型能利用影片時序追蹤假設，也避免把每張 frame 都當成完全獨立圖片。對疲勞分析而言，時序穩定性很重要，因為 PERCLOS、眨眼時長、凝視時間與 rPPG buffer 都不是單張影像能判斷的。

## 7. 行為疲勞演算法與原理

### 7.1 EAR 與閉眼判定

EAR（Eye Aspect Ratio）使用眼睛 6 點幾何比例計算眼睛開合程度。當眼睛閉上時，上下眼瞼距離變小，EAR 下降。

本系統不使用單一固定 EAR，而是先做個人化校準：

- `calib_sec=5.0` 秒。
- 至少 `min_calib_samples=20` 筆。
- 取校準 EAR 中位數乘上 `thresh_ratio=0.75` 作為閉眼門檻。
- 若校準不足，fallback 到 `base_th_default=0.18`。

選擇 EAR 的原因：

- 可解釋。
- 不需額外模型。
- 已被大量疲勞/眨眼研究使用。
- 可直接由 MediaPipe landmarks 計算。

### 7.2 PERCLOS

PERCLOS 是一段時間內眼睛閉合比例。本系統用 60 秒 sliding window：

- `perclos_window_sec=60.0`。
- `low_vigilance_perclos_th=0.10` 作為低警覺工程門檻。
- `tired_perclos_th=0.25` 作為 DROWSY 工程門檻。

PERCLOS 的優點是能反映一段時間內的閉眼累積，而不是只看單次眨眼。這適合疲勞監測，因為疲勞通常是時間累積現象。

但 PERCLOS 也有限制：若受試者主觀嗜睡但沒有明顯閉眼，PERCLOS 可能偏低。因此本系統同時加入眨眼時序、凝視、瞇眼、頭部姿態與哈欠作為輔助。

### 7.3 眨眼時序

系統會記錄每次有效 blink 的：

- blink duration。
- blink amplitude。
- opening velocity。

前 12 次有效 blink 建立個人 baseline。後續若 blink duration z-score 偏高，或 opening velocity z-score 偏低，會提高 `blink_temporal_score`。目前 `blink_temporal_score >= 0.45` 會成為 LOW_VIGILANCE 的早期警示條件之一。

使用眨眼時序的原因是：早期低警覺不一定馬上出現長閉眼，但眼瞼動作可能變慢、眨眼時間變長。這比只看 PERCLOS 更早捕捉警覺度變化。

### 7.4 視線、凝視與掃視

系統用虹膜 landmarks 估計 gaze position，並計算：

- gaze stability。
- fixation duration。
- saccadic velocity。
- saccade frequency。

若 gaze 長時間穩定且掃視頻率很低，系統會標記 gaze mental fatigue。這類訊號只作早期警示輔助，不單獨判定 DROWSY。原因是無人機操作員可能因任務需要長時間注視螢幕，不能把所有凝視都視為疲勞。

### 7.5 頭部姿態與微睡眠

系統使用臉部 2D landmarks 與簡化 3D 臉部模板，透過 OpenCV `solvePnP` 估算 pitch、yaw、roll。頭部 pitch 會建立個人 offset，再判斷低頭/點頭事件。

頭部姿態的用途：

- 品質 gate：頭太偏、roll/yaw 過大時，降低眼部與 rPPG 判讀信心。
- 微睡眠輔助：若低頭/點頭持續超過門檻，可觸發 `MICROSLEEP`。

頭部姿態不能單獨代表疲勞，因為無人機操作員常低頭看遙控器或平板。因此系統把它視為輔助訊號，而不是主判定。

### 7.6 MAR 與哈欠

MAR（Mouth Aspect Ratio）用嘴部 landmarks 估計嘴巴開合。系統目前以：

- `mar_yawn_th=0.60`。
- `mar_yawn_dur_sec=1.5`。
- mouth blendshape 輔助。

哈欠是疲勞常見行為，但在無人機任務中，操作員可能說話、下指令、咳嗽或與旁人溝通，因此哈欠在本系統中是 late-stage、低權重輔助訊號。

## 8. rPPG 回放演算法與用途

回放系統同時執行 rPPG，但 rPPG 在 UTA-RLDD 中的定位是品質與生理負荷輔助，不是疲勞主判定。

rPPG 流程包含：

1. 從 MediaPipe landmarks 建立額頭、左臉頰、右臉頰與眉間 ROI。
2. 取 ROI 平均 RGB。
3. 使用 POS 方法從 RGB 時間序列分離脈波訊號。
4. 使用 band-pass filter 保留合理心率頻帶。
5. 使用 Welch 頻譜分析尋找主要心率峰值。
6. 使用 peak detection 估算 IBI、HRV 與品質指標。

使用 rPPG 的原因：

- 不需穿戴設備。
- 可提供 BPM、HRV、SQI 與品質診斷。
- 可判斷目前影像是否足以做生理訊號分析。
- 可作為疲勞/壓力輔助 pillar。

但 UTA-RLDD 沒有同步 PPG/ECG ground truth，因此不能用此資料集宣稱 BPM 絕對準確。回放報表中的 rPPG 應解讀為「品質可用性與輔助生理趨勢」，而不是醫療級心率驗證。

## 9. 融合分數

`FatigueFuser` 將行為疲勞與 rPPG 輔助訊號融合：

- 行為疲勞權重：`0.85`。
- rPPG 權重：`0.15`。

行為 pillar 包含：

- PERCLOS。
- blink temporal。
- microsleep。
- gaze。
- squint。
- yawn。

rPPG pillar 包含：

- stress probability。
- BPM deviation。
- LF/HF。
- SQI 與 quality discount。

當 rPPG 品質不足、ROI 不足或 SQI 不可靠時，rPPG 權重會降為 0，由行為疲勞承擔主要判斷。這是保守設計，避免低品質 rPPG 造成疲勞分數亂跳。

## 10. SQLite 逐幀紀錄

每一幀會寫入 `metrics_utarldd_<subject>_<label>_<timestamp>.db`。SQLite schema 沿用正式錄製系統，包含：

- 影片資訊：timestamp、fps、frame_width、frame_height、codec。
- rPPG 指標：BPM、raw BPM、BPM guard、RMSSD、SDNN、LF/HF、SQI、ROI 權重、ROI valid count、亮度。
- 疲勞指標：status、fatigue_level、EAR、PERCLOS、blink、gaze、head pose、MAR、yawn、quality score。
- 融合指標：fused score、level、behavior/rPPG sub-score、effective weights、trend。

使用 SQLite 的原因：

- 每幀資料可查詢、可回放、可稽核。
- 可被 Web dashboard 直接讀取。
- 可與一般 live camera 錄製資料使用同一套 schema。
- 支援後續用 SQL 或 Python 分析特定時間段。

## 11. CSV 與 HTML 報表

批次完成後會輸出：

| 檔案 | 用途 |
| --- | --- |
| `utarldd_summary_<timestamp>.csv` | 給人工快速檢視的中文摘要 |
| `utarldd_summary_full_<timestamp>.csv` | 保留所有 dataclass 欄位，供程式分析 |
| `utarldd_validation_report_<timestamp>.csv` | 依 label 與 subject 比較趨勢支持度 |
| `utarldd_visual_report_<timestamp>.html` | 單檔可視化報表 |
| `utarldd_manifest_<timestamp>.json` | 記錄執行參數、輸出路徑、資料集資訊與 summaries |

summary CSV 新增欄位包含：

- post-calibration frames。
- behavior-available frames。
- rPPG available frames。
- low-quality frames。
- PERCLOS 低警覺觸發幀數。
- PERCLOS 嗜睡觸發幀數。
- 眨眼時序警示幀數。
- 瞇眼幀數。
- 凝視疲勞幀數。
- 哈欠幀數。
- 標籤對齊判讀。
- 主要判斷依據。
- 建議修正方向。
- 優化旗標。

HTML 報表會整理：

- 總覽卡片：影片總數、完成數、平均人臉偵測率、Alert 誤報風險、Drowsy 漏報風險與有效幀不足。
- Label 分組長條圖：平均 PERCLOS、最高 PERCLOS、95 分位融合分數、低警覺比例、嗜睡/危急比例、行為有效率與低品質比例。
- 逐影片表格：快速判讀、標籤對齊、主要判斷依據、建議修正方向與優化旗標。

這讓使用者不用只看原始 CSV，就能快速看出系統目前主要靠哪些訊號判斷疲勞、哪一類影片最容易誤報或漏報、下一步應調整哪個門檻。

2026-06-16 補充：`20260607_122601` 這批正式完整回測已從既有 summary CSV 補產 HTML 可視化報表；不需要重新跑 36 支影片即可更新展示報表。需注意的是，這批 CSV 是較早輸出的欄位版本，尚未包含新版 post-calibration / behavior-available 等有效分母欄位；若要讓 HTML 報表顯示完整有效分母，需要用目前程式重跑 replay。

## 12. 回測數據為什麼可信

本系統的可信度來自六個工程設計。

### 12.1 可重現時間軸

回放不依賴電腦執行速度，而是以影片 FPS 建立 deterministic timestamp。同一影片、同一設定下，PERCLOS、blink duration、rPPG buffer 與 fusion trend 的時間基準一致。

### 12.2 重用正式 live pipeline

回放系統重用正式 GUI 會用到的 `FatigueEngine`、`RppgEngine`、`FatigueFuser` 與 `MetricsRecorder`。因此回放不是另一套離線算法，而是把同一套系統套到可重現影片上。

### 12.3 逐幀保存原始指標

SQLite 保存每一幀的疲勞、rPPG、融合分數與品質資料。若 summary 結論有疑問，可回到逐幀資料檢查觸發時間、品質分數、PERCLOS 或 blink temporal。

### 12.4 有效分母與品質欄位

summary 不只輸出平均分數，也輸出：

- face rate。
- post-calibration frames。
- behavior-available frames。
- rPPG available frames。
- low-quality frames。

這避免把校準期、無臉、低品質 frame 混在一起誤解成演算法失敗或成功。舊版已輸出的 CSV 不會自動補齊這些欄位；從既有 CSV 轉 HTML 時會以現有欄位呈現，欄位版本需在報告中註明。

### 12.5 批次輸出 manifest

manifest 保存 dataset root、輸出路徑、run timestamp、jobs、是否輸出標註影片、label 對照與每支影片 summary。這讓回放結果能被追蹤與重跑。

### 12.6 自動測試

目前測試涵蓋：

- UTA-RLDD label 解析。
- 影片探索與篩選。
- summary CSV 輸出。
- full summary CSV 輸出。
- validation report 趨勢輸出。
- HTML 可視化報表輸出。
- batch manifest 輸出。
- 平行處理順序。
- broken process pool 錯誤處理。
- 平行模式自動停用標註影片。

這些測試保證報表欄位與批次流程不會因後續修改輕易壞掉。

## 13. 回測數據不能代表什麼

回放系統也有明確限制：

- UTA-RLDD label 是整段影片類別，不是逐幀疲勞 ground truth。
- UTA-RLDD 是駕駛嗜睡資料集，不是無人機操作員資料集。
- 不能用 UTA-RLDD 驗證 rPPG BPM 絕對準確率，因為缺少同步 PPG/ECG 參考。
- 若影片中 Drowsy 狀態沒有明顯閉眼，PERCLOS 可能不會大幅上升。
- Alert 影片可能因眼型、姿態、光線或眨眼 baseline 造成 LOW_VIGILANCE 誤報。
- 回放結果只能說明目前門檻在這批影片上的趨勢支持度，不能直接宣稱真實無人機場域分類準確率。

因此，本系統輸出應解讀為「特徵與門檻的回放驗證結果」，不是臨床診斷、法規認證或安全關鍵自動決策。

## 14. 平行批次處理

系統支援 `--jobs N` 以多進程處理多支影片。平行化策略是「不同影片之間平行，單支影片內仍逐幀順序處理」。

這樣設計的原因：

- PERCLOS、blink temporal、rPPG buffer 與 MediaPipe VIDEO mode 都依賴同一支影片內的時間順序。
- 不同影片彼此獨立，可以平行處理節省時間。
- 單支影片不打散 frame，避免時序指標失真。

平行模式會自動停用標註影片輸出，降低多進程同時編碼 mp4 造成的記憶體與 codec 壓力。若子行程異常中止，系統會把未完成影片標成 `failed`，並在 summary、validation report 與 manifest 保留錯誤訊息。

## 15. GUI 預覽與標註影片

GUI replay 可顯示即時預覽。預覽內容包含：

- MediaPipe 人臉特徵。
- 疲勞狀態疊圖。
- rPPG ROI 標註。

預覽會限制最大尺寸與最高約 20 FPS，避免 Qt 主執行緒負擔過重。這只影響畫面顯示，不影響 SQLite、CSV 與 manifest 的逐幀分析結果。

此處的 20 FPS 只指 UTA-RLDD 離線 replay 預覽。live camera 與 Web dashboard 即時 preview 已在 2026-06-16 調整為 30 FPS 目標，且以 `QImageWriter` 產生 JPEG base64 後透過 Socket.IO 推送；兩者目的不同，不能混為同一條 FPS 限制。

若使用 `--write-annotated-video` 或 GUI 勾選標註影片，系統會輸出標註後 mp4。標註影片適合展示與人工檢查，但正式批次驗證不建議大量輸出，避免容量與編碼壓力。

## 16. 為什麼不用直接訓練新模型

目前系統沒有把 UTA-RLDD 拿來訓練 CNN/LSTM/Transformer，原因如下：

- 畢業專題目前重點是可解釋監測原型，不是黑盒分類器。
- UTA-RLDD 不是無人機操作員資料集，直接訓練可能學到汽車駕駛場景偏差。
- 目前 label 是整段影片類別，不是逐幀事件標註，直接訓練逐幀分類容易誤導。
- 現有規則式特徵更容易解釋每次警示的原因。
- 回放系統的價值在於校正門檻、比較趨勢、發現誤報/漏報，而不是立即追求高準確率模型。

未來若資料足夠，可把目前 SQLite/CSV 輸出的可解釋特徵作為 supervised learning 或 threshold optimization 的基礎，但不建議在缺少無人機場域標註前直接導入深度分類模型。

## 17. 可視化報表如何判斷修正方向

HTML 報表與 summary CSV 會輸出 `optimization_flags_json`，目前包含：

- `face_detection_unstable`：人臉偵測率低，應先修正相機、光線或 tracking。
- `behavior_effective_frames_low`：行為有效幀不足，應檢查校準期或品質 gate。
- `fatigue_quality_low`：疲勞品質偏低，應檢查 roll/yaw/鼻尖速度/嘴部開合。
- `alert_false_alarm_risk`：Alert 影片出現過多 LOW_VIGILANCE 或 PERCLOS 觸發。
- `drowsy_miss_risk`：Drowsy 影片未出現足夠嗜睡證據。
- `low_vigilance_insensitive`：Low Vigilant 影片偏不敏感。
- `low_vigilance_too_severe`：Low Vigilant 影片被判得太嚴重。
- `rppg_unavailable`：rPPG 無可用幀，需檢查 ROI、光線或 SQI。

這些旗標讓報表不只是展示分數，而是直接告訴使用者下一步該修哪裡。

## 18. 建議後續優化

依目前報告與程式碼，後續優先順序如下：

1. 為 replay 建立獨立 calibration namespace，避免本機 webcam baseline 影響資料集回放。
2. 加入門檻 sweep 工具，批次比較 PERCLOS、blink temporal、LOW_VIGILANCE 條件與融合權重。
3. 加入逐事件人工標註欄位，例如閉眼、哈欠、轉頭、低頭、說話、遮擋與光線變化。
4. 將 HTML 報表擴充成可比較兩次 run 的 A/B 報表。
5. 加入無人機場域自錄影片，建立看遙控器、看平板、看天空、任務壓力上升等專用情境。
6. 建立 false alarm rate per hour、miss rate、Drowsy recall 與低警覺提前量等評估指標。

## 19. 結論

UTA-RLDD 影片回放驗證系統讓本專案從單純即時 demo，提升成可重現、可稽核、可比較的疲勞監測驗證平台。它用 OpenCV 逐幀讀影片，用 deterministic timestamp 餵入 MediaPipe VIDEO mode，重用正式疲勞、rPPG 與融合分數流程，再把逐幀資料保存到 SQLite，最後輸出 CSV、validation report、manifest 與 HTML 可視化報表。

這套系統可信的地方在於工程流程可重現、同一套 live pipeline 可回放、逐幀資料可追查、summary 有有效分母與品質欄位、報表能指出誤報/漏報風險。但它也必須保守解讀：UTA-RLDD 只能作為早期驗證與門檻校正資料，不能取代無人機操作員場域測試，也不能直接宣稱疲勞分類已可靠。

因此，本系統最適合放在畢專報告的「驗證方法」與「資料分析」章節，說明本專題不只做即時偵測，也建立了可回放、可檢查、可優化的工程驗證管線。

## 20. 參考資料

1. MediaPipe Face Landmarker  
   https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker  
   參考用途：臉部 landmarks、blendshape scores、facial transformation matrices 與 VIDEO mode。

2. OpenCV VideoCapture documentation  
   https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html  
   參考用途：影片逐幀讀取、FPS、frame count、解析度與 codec 屬性。

3. OpenCV solvePnP documentation  
   https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html  
   參考用途：以 3D 模板與 2D landmarks 估算頭部姿態。

4. Python csv documentation  
   https://docs.python.org/3/library/csv.html  
   參考用途：summary CSV、validation report 與 full summary 的輸出。

5. Python sqlite3 documentation  
   https://docs.python.org/3/library/sqlite3.html  
   參考用途：逐幀 metrics SQLite 紀錄。

6. UTA-RLDD official site  
   https://sites.google.com/view/utarldd/home  
   參考用途：Alert、Low Vigilant、Drowsy 三類資料集標籤。

7. Reza Ghoddoosian, Marnim Galib, Vassilis Athitsos, A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection, CVPR Workshops, 2019  
   https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html  
   參考用途：長影片早期嗜睡偵測與 UTA-RLDD 三階段標籤。
