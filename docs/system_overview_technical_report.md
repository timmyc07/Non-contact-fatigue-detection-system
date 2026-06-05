# 系統總技術報告書

更新日期：2026-05-31

本報告整理本系統的整體目的、AI 模型、訊號處理、疲勞分析、輸入輸出、系統架構、可信度驗證方式與限制。內容以聽眾能理解的用途名稱描述流程；必要技術術語會以括號補充，例如臉部特徵點（landmarks）與皮膚取樣區域（ROI）。

## 1. 系統定位

本系統是一套以一般攝影機進行即時臉部生理與行為狀態分析的桌面工具。它同時提供兩種判讀：

- 生理訊號判讀：使用 rPPG（remote photoplethysmography，遠端光體積變化描記）從臉部皮膚顏色微小變化估計心率、心率變異度與壓力趨勢。
- 行為疲勞判讀：使用臉部特徵點、眼睛開合、視線穩定度、頭部姿態與張嘴哈欠等特徵估計疲勞程度。
- 融合判讀：將行為疲勞分數與可用的 rPPG 生理壓力訊號合併，輸出整體疲勞分數。

本系統不是醫療診斷工具，也不是安全關鍵場景中的單點決策系統。所有分數都應視為趨勢提示與工程診斷資訊。

## 2. 使用模型與核心技術

### 2.1 臉部 AI 模型

系統唯一直接使用的 AI 模型是 MediaPipe Face Landmarker（臉部特徵點偵測模型）。它的用途是從每張攝影機影像中找出臉部位置、臉部特徵點、表情係數與臉部姿態資訊。

模型 input：

- 攝影機原始影像（OpenCV BGR frame，OpenCV 預設的藍綠紅色彩順序）會先轉成 RGB（紅綠藍色彩順序）。
- 影像會包裝成 MediaPipe 影像物件（mp.Image，表示要送入 MediaPipe 模型的影像資料）。
- 系統使用影片連續偵測模式（RunningMode.VIDEO），每張影像都帶有毫秒時間戳記（timestamp_ms，用來表示 frame 的時間順序）。

模型 output：

- 臉部特徵點（face landmarks）：478 個臉部位置點，用於皮膚取樣、眼睛開合、嘴部開合、視線與頭部姿態分析。
- 表情係數（blendshape scores）：例如眨眼、瞇眼、皺眉與張嘴等表情強度，用於輔助疲勞判讀。
- 臉部姿態轉換矩陣（facial transformation matrix）：描述臉部相對鏡頭的旋轉與位移，用於姿態補償與品質診斷。

### 2.2 訊號處理技術

rPPG 生理訊號不使用心率 AI 模型，而是由訊號處理產生：

- POS 脈波分離法（Plane-Orthogonal-to-Skin，皮膚色彩正交投影法）：從 RGB 顏色時間序列萃取較接近脈搏的波形。
- Butterworth 帶通濾波（band-pass filter）：保留合理心跳頻帶，降低低頻漂移與高頻雜訊。
- Welch 頻譜分析（Welch PSD，分段平均頻譜估計）：在心率頻帶中找主要峰值估算 BPM。
- 峰值偵測（peak detection）：從脈波波形找出相鄰心跳間隔，用於推估心率變異度。

### 2.3 行為疲勞分析技術

行為疲勞判讀是規則式、多門檻、個人化校準流程，不是端到端 fatigue AI classifier。核心特徵包含：

- EAR（Eye Aspect Ratio，眼睛長寬比例）：用於判斷睜眼、閉眼與眨眼。
- PERCLOS（眼睛閉合時間比例）：用於估計長時間閉眼與嗜睡趨勢。
- Iris / gaze（虹膜與視線）：用於估計視線穩定度、掃視頻率與注視狀態。
- Head pose（頭部姿態）：估計 pitch/yaw/roll，也就是上下點頭、左右轉頭與左右傾斜。
- MAR（Mouth Aspect Ratio，嘴部開合比例）：用於判斷張嘴與哈欠。
- Blendshape baseline（表情係數個人基準值）：用於降低不同使用者與不同光線下的表情係數偏移。

## 3. 系統架構

```text
攝影機影像擷取流程
  -> 即時 BGR 影像佇列
  -> 共用臉部偵測與分流流程
  -> MediaPipe 臉部特徵點影片模式偵測
  -> 臉部特徵點、表情係數與姿態資訊
  -> rPPG 生理訊號分析流程
       -> 臉部皮膚 ROI 取樣
       -> POS 脈波訊號分離
       -> 帶通濾波與頻譜峰值搜尋
       -> 心率、心率變異度、訊號品質與壓力趨勢
  -> 行為疲勞分析流程
       -> 眼部開合與 PERCLOS
       -> 視線穩定度與掃視頻率
       -> 頭部姿態、微睡眠與張嘴哈欠
       -> 行為疲勞特徵與品質分數
  -> 分數融合流程
  -> 桌面畫面疊圖、網頁儀表板與 SQLite 紀錄
```

系統採用共用臉部偵測流程，讓同一份臉部特徵點同時供應 rPPG 與疲勞分析。這樣可以避免同一張影像重複跑模型，也能降低畫面疊圖與指標更新互相競爭的風險。

## 4. 主要輸入與輸出

### 4.1 輸入

- 攝影機影像：一般 webcam 或相機裝置輸出的連續 frame。
- 臉部 AI 模型輸出：臉部特徵點、表情係數與姿態資訊。
- 校準與設定參數：包含信心門檻、ROI 品質門檻、眼睛與表情校準參數、融合權重與品質 gate。

### 4.2 rPPG 輸出

- BPM（beats per minute，每分鐘心跳數）：由頻譜峰值估算。
- HRV（heart rate variability，心率變異度）：包含 RMSSD、SDNN 與 LF/HF 等趨勢指標。
- SQI（signal quality index，訊號品質指標）：表示目前 rPPG 訊號可用程度。
- 壓力趨勢：以 HRV 與 LF/HF 建立的工程 heuristic，不是臨床壓力診斷。
- ROI 診斷：包含取樣區域可用數、穩定度、姿態與遮擋相關資訊。

### 4.3 疲勞輸出

- 行為疲勞特徵：眨眼、長閉眼、PERCLOS、瞇眼、皺眉、視線穩定度、頭部點頭、張嘴與哈欠。
- 品質分數：表示當前 frame 是否適合進行疲勞判讀。
- 整體疲勞分數：行為疲勞為主，rPPG 生理壓力訊號可用時作為輔助。
- 狀態標籤：例如正常、疲勞提醒或明顯嗜睡狀態。

## 5. 關鍵判讀邏輯

### 5.1 rPPG 判讀

1. 從臉部特徵點建立額頭、左右臉頰與眉心附近的皮膚取樣區域。
2. 將每個可用 ROI 的平均顏色轉成 RGB 時間序列。
3. 使用 POS 方法降低光照共同變動，保留與脈搏較相關的色彩變化。
4. 使用 Butterworth 帶通濾波保留合理心率頻帶。
5. 使用 Welch 頻譜分析尋找主要頻率峰值，換算成 BPM。
6. 若脈波峰值足夠穩定，估算 HRV 與壓力趨勢。

### 5.2 行為疲勞判讀

1. 以左右眼 6 個特徵點計算 EAR，建立個人化閉眼門檻。
2. 以滑動時間窗計算 PERCLOS，估計閉眼比例。
3. 用虹膜位置與視線移動估計視線穩定度、注視時間與掃視頻率。
4. 用頭部姿態偵測點頭、轉頭、抬頭與快速移動造成的品質下降。
5. 用嘴部比例與表情係數判斷張嘴與哈欠。
6. 將上述特徵轉成行為疲勞分數，再與可用的 rPPG 生理訊號融合。

## 6. 品質控管與可信度

系統會先判斷畫面與特徵是否可信，再決定是否更新指標：

- 臉部必須足夠大，避免解析度不足造成特徵點不穩。
- 頭部轉動或左右傾斜過大時，降低眼睛與 ROI 判讀信心。
- 快速移動、遮擋、光線不足或相機曝光變動會降低品質分數。
- rPPG 需要穩定光源、穩定頭部與足夠長的有效 buffer。
- 疲勞判讀需要個人化校準，避免眼型、眼鏡與表情基準差異造成誤判。

可信度驗證應包含自動測試、固定錄影回放、人工標註比對與現場情境測試。

## 7. 測試與驗證

目前驗證重點包含：

- rPPG 訊號處理函式：濾波、頻譜、峰值、HRV 與品質分數。
- MediaPipe 疲勞特徵：眼部、視線、頭部、嘴部與融合分數。
- Ubuntu/Linux 相機支援：相機列舉、V4L2 後端與 pygrabber 平台隔離。
- 技術報告 PDF：由 Markdown 來源重新產生 PDF，確保文件可重現。

建議現場驗證情境：

1. 清醒注視螢幕 2 分鐘，確認疲勞分數低且 rPPG 指標逐步穩定。
2. 自然眨眼、快速眨眼與閉眼 2 秒，確認眨眼與長閉眼事件可區分。
3. 持續瞇眼 5 到 10 秒，確認瞇眼與早期疲勞提醒上升。
4. 張嘴說話與真正哈欠分開測試，確認哈欠需要持續時間與嘴部比例共同成立。
5. 轉頭、抬頭、快速晃動與遮擋，確認品質分數下降且不輸出高信心判讀。

## 8. 部署與維運重點

- Windows 使用 DirectShow 相機列舉；Linux 使用 V4L2 相機後端。平台專用後端應保持隔離。
- 模型檔是必要執行資產，載入方式需維持相對路徑可攜性。
- 校準結果屬於個人與環境資料，不應提交版本控制。
- 修改門檻、ROI、融合權重或模型設定時，應保留固定錄影回放比較。
- 新增模型或更換模型時，必須記錄模型來源、版本、input/output、推論模式與 fallback。

## 9. 限制與風險

- rPPG 對光線、頭部動作、自動曝光、遮擋、膚色與相機 FPS 敏感。
- 目前 rPPG 短窗較適合心率與趨勢提示，對 LF/HF 等 HRV 指標只適合作為趨勢參考。
- 疲勞判讀會受眼鏡、瀏海、眼型、鏡頭角度與反光影響。
- 表情係數若在不自然表情下校準，後續判讀會偏移。
- 本系統不應作為醫療診斷、執法、安全控制或單獨自動決策依據。

## 10. 參考資料與本系統採用技術

1. MediaPipe Face Landmarker Python guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python  
   本系統參考技術：臉部特徵點、表情係數、臉部姿態矩陣、影片連續偵測模式與每張 frame 的時間戳記。

2. MediaPipe Face Landmarks Detection guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker  
   本系統參考技術：3D 臉部特徵點（3D face landmarks）、表情係數（blendshape scores）與臉部姿態轉換矩陣（facial transformation matrices）的輸出定義。

3. Camillo Lugaresi et al., "MediaPipe: A Framework for Building Perception Pipelines", arXiv:1906.08172, 2019  
   https://arxiv.org/abs/1906.08172  
   本系統參考技術：即時感知處理流程（perception pipeline）與 graph-based 處理概念；本系統以單一臉部偵測流程分流給生理與疲勞分析。

4. W. Wang, A. C. den Brinker, S. Stuijk, G. de Haan, "Algorithmic Principles of Remote PPG", IEEE Transactions on Biomedical Engineering, 2017  
   https://doi.org/10.1109/TBME.2016.2609282  
   本系統參考技術：POS（Plane-Orthogonal-to-Skin）rPPG 方法與 RGB 色彩投影概念。

5. Peter D. Welch, "The Use of Fast Fourier Transform for the Estimation of Power Spectra", IEEE Transactions on Audio and Electroacoustics, 1967  
   https://doi.org/10.1109/TAU.1967.1161901  
   本系統參考技術：以分段、重疊與平均估計 power spectral density；本系統用於心率頻帶峰值搜尋。

6. SciPy scipy.signal API reference  
   https://docs.scipy.org/doc/scipy/reference/signal.html  
   本系統參考技術：Butterworth 濾波、Welch 頻譜分析、峰值偵測與一維插值。

7. OpenCV VideoCapture documentation  
   https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html  
   本系統參考技術：相機 frame 擷取與不同平台相機後端支援。

8. OpenCV image processing documentation  
   https://docs.opencv.org/4.x/d6/d6e/group__imgproc__draw.html  
   本系統參考技術：畫面疊圖標註、ROI 繪製與影像處理工具。
## 11. 2026-06-05 修訂：疲勞判定與 rPPG 保守更新

本次修訂以「汽車駕駛疲勞偵測技術可遷移到無人機駕駛員監測」為方向，但採保守落地策略：行為疲勞作為主判定，rPPG 作為生理壓力/負荷輔助。疲勞定義為操作員警覺度下降到可能影響監控、判斷或操控反應的狀態，不作醫療診斷。

### 11.1 行為疲勞新增能力

- 狀態分級加入 `LOW_VIGILANCE` 與 `CRITICAL`，形成 `OK -> LOW_VIGILANCE -> DROWSY -> CRITICAL / MICROSLEEP` 的介入流程。
- 新增眨眼時序基準：以個人前 12 次有效眨眼建立 duration / amplitude / opening velocity baseline，再用 z-score 判斷是否偏離個人清醒眨眼型態。
- PERCLOS 改為分層解讀：`0.10` 作為低警覺工程門檻，`0.25` 作為明顯嗜睡工程門檻。這些不是論文固定值，需用本專案錄影回放持續校正。
- 皺眉不再作為 fatigue 主權重，因無人機操作情境中皺眉更可能代表任務負荷或壓力。

### 11.2 rPPG 保守更新

本次未替換 rPPG 核心演算法。POS、濾波、Welch、IBI/HRV 與 stress heuristic 全部維持既有行為，只新增 `raw_bpm`、`bpm_delta`、`bpm_guarded`、`bpm_guard_reason`，讓偶發大幅波動可以被診斷與回放。

### 11.3 主要參考依據

- MediaPipe Face Landmarker 官方文件：採用 478 landmarks、blendshape scores 與 transformation matrix 作為臉部特徵來源。
- Soukupová and Čech, 2016：採用 EAR 與 facial landmarks 進行眼部開合/眨眼偵測的思路。
- PERCLOS 駕駛嗜睡研究與 NHTSA 相關報告：採用「時間窗內眼睛閉合比例」作為警覺度下降指標。
- Ghoddoosian, 2019/2022：參考 `alert / low vigilant / drowsy` 三階段與 temporal model 思路，因此新增低警覺分級。
- Tüfekci et al., 2022：參考以正常表徵建立 baseline、偏離正常視為 anomaly 的概念，因此採用個人化眨眼時序 baseline。
- 王奕鈞，2026：參考 MediaPipe ROI、雙頰與 Lab 色彩空間在 rPPG 動態情境下的後續優化方向；本次未直接替換已接近精準的 POS 主流程。
## 12. 2026-06-06 UTA-RLDD 影片回放測試系統

本次新增 `scripts/utarldd_replay.py` 與 GUI「UTA-RLDD 影片測試」入口，讓 UTA-RLDD 影片可被當作可重現的離線鏡頭輸入。此功能不改動 live camera worker；回放核心位於 `gui/utarldd_replay.py`，逐幀讀取 `.mov/.MOV/.mp4`，使用影片 FPS 產生 deterministic timestamp，再共用同一條 `FatigueEngine`、`RppgEngine`、`FatigueFuser` 與 `MetricsRecorder` 記錄流程。

資料集 label 依 UTA-RLDD 官方定義：

- `0 = Alert`
- `5 = Low Vigilant`
- `10 = Drowsy`

來源與引用：

- UTA-RLDD official site, https://sites.google.com/view/utarldd/home
- Reza Ghoddoosian, Marnim Galib, Vassilis Athitsos, "A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection", CVPR Workshops, 2019, https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html

本專案參考上述資料的部分，是其三分類警覺度標籤與「以長影片觀察 alert / low vigilant / drowsy 時序趨勢」的驗證思路。第一版不把 label 當作逐幀 ground truth，也不自動覆寫目前工程門檻；它的定位是蒐集趨勢統計，用來比較本系統在 Alert、Low Vigilant、Drowsy 三類影片中的 `LOW_VIGILANCE/DROWSY/CRITICAL` frame ratio、PERCLOS、blink temporal score、fused score、face rate、rPPG quality、SQI 與 BPM guard 次數。

CLI 範例：

```bash
python -m scripts.utarldd_replay <dataset_root> --max-videos 1 --max-frames 300
```

輸出預設位於 `recordings/utarldd_runs/<run_timestamp>/`：

- `metrics_utarldd_<subject>_<label>_<timestamp>.db`：沿用 `MetricsRecorder` schema，`camera_label` 寫入 `UTA-RLDD subject=<id> label=<0|5|10>`。
- `utarldd_summary_<timestamp>.csv`：給人工檢視的好讀摘要，使用中文欄位、百分比欄位與快速判讀。
- `utarldd_summary_full_<timestamp>.csv`：保留每支影片的完整 summary 欄位，供後續 notebook、統計與稽核使用。
- `utarldd_manifest_<timestamp>.json`：run metadata、來源 URL、label 對應與每支影片摘要。
- 可選 `video_utarldd_<subject>_<label>_<timestamp>.mp4`：只有啟用 `--write-annotated-video` 或 GUI 勾選輸出標註影片時產生。

GUI 版本會在批次進行時顯示 MediaPipe 人臉特徵與 rPPG ROI 標註預覽，讓操作者可直接確認影片是否被正確偵測，而不必等回放結束後再開標註影片。

Web playback 已支援列出 `recordings/utarldd_runs/*/metrics_*.db`，因此 replay DB 可以與一般錄影 DB 一樣被 dashboard 讀取。這項測試可補足目前無法短時間募集大量真人受試者的問題，但仍不能完全取代無人機駕駛員場域真人測試；最終門檻仍應用本場域資料做校正。
