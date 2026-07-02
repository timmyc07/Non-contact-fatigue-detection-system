# rPPG 心跳校準器技術分析報告

> **歷史文件（已被取代）**：本文件描述的是 2026-06 的「手動手錶 HTTP 參考校準器」（`gui/rppg_calibration_dialog.py` + `POST /hr` :8080），該工具與「手錶模式」已於 2026-07-03 移除。現行版本改為 **BLE 心跳帶背景自動校準**（`rppg/adaptive_calibration.py` + `gui/belt_runtime.py`），以心跳帶實測心率為真值、線上低增益 EMA 自動微調 rPPG BPM offset 並自動存版本。offset 演算法（殘差中位數 → bias 校準）與品質 gate 概念仍延續，可作背景參考；GUI 流程與資料來源以現行版本為準（見 `README.md`「心跳帶真值校準」與 `docs/heart_rate_belt_bluetooth_gatt_profile.md`）。

日期：2026-06-19  
分析對象：目前 `main` 分支最新提交 `71baa5d feat(calibration): 新增 rPPG 心率校準器 GUI（測試版 beta）`

## 1. 摘要結論

本專案最新的心跳校準器不是新的心率估測模型，而是一個「rPPG BPM 偏移量校準器」。它用智慧手錶或外部心率來源在校準 session 期間提供參考 BPM，將參考 BPM 與本機 rPPG BPM 依時間窗配對，計算 `watch_median - rppg_median` 的殘差，再以殘差中位數作為後續日常監測的 BPM offset。

此設計的核心判斷是：目前 rPPG 主流程已能提供接近可用的心率估測，但在不同相機、光源、ROI、膚色、曝光與姿態條件下可能出現固定或半固定偏差。用單一偏移量修正可以降低個人與環境造成的系統性 bias，同時避免在校準資料不足時訓練過度複雜的模型。

系統目前仍應被定位為工程校準與趨勢輔助工具，不是醫療級心率驗證。若要宣稱可替代 ECG、胸帶或指夾式 PPG，仍需要以 Bland-Altman limits of agreement、MAE、95th percentile error、可用率與跨情境 replay 驗證。

## 2. 相關程式位置

| 類別 | 檔案 | 角色 |
|---|---|---|
| 校準資料模型與分析 | `rppg/calibration.py` | 版本資料、品質 gate、live feed、時間窗配對、offset 估計、套用校準 |
| 手錶 HTTP 接收 | `rppg/calibration_watch.py` | 背景 HTTP server，接收 `POST /hr` 的 BPM JSON |
| GUI 校準器 | `gui/rppg_calibration_dialog.py` | PySide6 校準視窗、session 控制、即時顯示、儲存與切換版本 |
| 主視窗入口 | `gui/main_window.py` | 「校準 -> 開啟 rPPG 心率校準器...」選單、版本套用、live feed 寫入 |
| 合併 worker | `gui/combined_worker.py` | 寫入未校準 rPPG live feed，並在輸出前套用 active calibration |
| rPPG 核心 | `rppg/rppg_worker.py` | MediaPipe ROI、POS、Butterworth、Welch、BPM guard、SQI/HRV |
| 測試 | `tests/test_rppg_calibration.py` | offset 套用、origin identity、quality gate、session analyzer、version store |
| 使用說明 | `README.md` | rPPG BPM 校準功能入口與資料儲存位置 |

## 3. 系統資料流

```text
主視窗相機管線
  -> MediaPipe Face Landmarker
  -> rPPG ROI RGB 取樣
  -> POS + Butterworth + Welch
  -> raw RppgMetrics
  -> write_live_feed() 寫入 config/rppg_live_feed.json

手錶或外部參考來源
  -> POST http://<PC_IP>:8080/hr
  -> WatchHrHttpServer
  -> WatchHrHub 暫存參考 BPM

校準視窗
  -> read_live_feed()
  -> CalibrationSessionAnalyzer.add_watch()
  -> CalibrationSessionAnalyzer.add_rppg()
  -> 固定時間窗取 watch/rPPG 中位數
  -> offset = median(watch_median - rppg_median)
  -> 儲存 CalibrationVersion
  -> manifest active_version_id 指向新版本

日常監測
  -> 讀取 active CalibrationVersion
  -> bpm_calibrated = bpm_scale * bpm + bpm_offset
  -> GUI / Web / SQLite 顯示與記錄校準後 BPM
```

重要設計點：

- 手錶只在校準 session 使用。日常監測不需要手錶，只讀取 `config/rppg_calibration/manifest.json` 的 active 版本。
- 校準器讀取的是未校準 raw rPPG live feed，避免「已校準結果再次校準」的回授錯誤。
- `config/rppg_calibration/`、`config/rppg_live_feed.json` 與 feed flag 已在 `.gitignore` 中排除，不會提交個人校準資料。

## 4. 使用的技術與演算法

### 4.1 rPPG 上游心率估測

校準器依賴既有 rPPG pipeline，核心位於 `rppg/rppg_worker.py`：

1. 使用 MediaPipe Face Landmarker 定位臉部 landmark、blendshape 與 facial transformation matrix。
2. 從額頭、左右臉頰、眉間等皮膚 ROI 擷取 RGB 平均值。
3. 用 POS（Plane-Orthogonal-to-Skin）將 RGB 時序投影成 pulse waveform：

```text
R, G, B 先做 temporal normalization
X = 3R - 2G
Y = 1.5R + G - 1.5B
alpha = std(X) / std(Y)
pulse = X - alpha * Y
```

4. 使用 3 階 Butterworth band-pass，保留約 `0.65-3.7 Hz` 的心跳相關頻帶。
5. 使用 Welch PSD 在約 `0.7-3.5 Hz` 搜尋頻譜 peak，換算 BPM。
6. 使用 peak detection 推估 IBI、RMSSD、SDNN 與 LF/HF，但本報告重點是 BPM 校準。
7. 使用 SQI、ROI valid count、quality score、姿態與 landmark/ROI 穩定度作為可信度診斷。
8. 使用 BPM guard 抑制短暫跳值或不合理生理範圍。

### 4.2 校準 session 品質 gate

`rppg/calibration.py` 定義兩組 gate：

| gate | 日常預設 | 校準 session | 設計理由 |
|---|---:|---:|---|
| `min_sqi` | 0.45 | 0.35 | 校準 session 有時間窗與中位數保護，允許略低 SQI |
| `min_quality_score` | 0.55 | 0.45 | 避免過嚴造成沒有有效窗口 |
| `min_roi_valid` | 3 | 2 | 允許部分 ROI 暫時失效 |
| `require_warmup` | True | False | session 已另有 warmup 秒數 |
| `reject_bpm_guarded` | True | False | 校準時可取 `raw_bpm`，避免 guard 鎖住舊值 |

這個設計是保守折衷：校準不能收太髒的 rPPG 資料，但也不能因短暫 guard 或少量 ROI 失效就完全無法建立版本。

### 4.3 固定時間窗與中位數配對

`CalibrationSessionAnalyzer` 的主要流程：

1. 使用 `warmup_sec` 跳過前段資料。
2. 以 `window_sec` 切成固定窗口。
3. 每個窗口內計算 watch BPM 中位數。
4. 每個窗口內先套用 rPPG quality gate，再計算 rPPG BPM 中位數。
5. 若兩者皆存在，該窗口 accepted。
6. 殘差定義為：

```text
residual = watch_median - rppg_median
```

7. 最終偏移量：

```text
offset_bpm = median(residuals)
```

8. 評估指標：

```text
MAE before = mean(abs(rppg - watch))
MAE after  = mean(abs((rppg + offset) - watch))
```

選用中位數的原因是 rPPG 與腕式 PPG 都可能有短暫 artifact。若用平均值，單一錯誤窗口可能把 offset 拉偏；中位數對短暫極端值較穩健，更適合目前樣本數有限的 GUI 校準 session。

### 4.4 偏移量模型

目前儲存格式支援：

```text
bpm_calibrated = bpm_scale * bpm + bpm_offset
```

但 GUI 目前實際建立的是 `model="bias"`，也就是：

```text
bpm_scale = 1.0
bpm_calibrated = bpm + bpm_offset
```

選用 additive bias 的原因：

- 校準 session 通常只有數分鐘，不足以穩定估計斜率、非線性或情境模型。
- 若 rPPG 主流程已接近準確，常見問題更像固定偏移而非比例錯誤。
- 偏移量容易解釋、容易回滾，也能直接顯示 `offset +x.x BPM`。
- `bpm_scale` 已保留在資料模型中，未來若有多心率區間校準資料，可擴充為線性模型。

### 4.5 版本化與回滾

`CalibrationVersionStore` 會建立：

```text
config/rppg_calibration/
  manifest.json
  versions/
    v000_origin.json
    vYYYYMMDD_HHMMSS.json
```

`v000_origin` 是未校準 identity 版本。每次儲存新校準會：

- 寫入獨立版本 JSON。
- 在 manifest 記錄版本清單。
- 把 `active_version_id` 切到新版本。
- 允許 GUI 切回 `v000_origin` 或刪除非 builtin 版本。

這種版本化設計符合校準資料的維運需求：不同光源、相機、距離或使用者可能需要不同版本，而且錯誤校準必須能快速回退。

## 5. 文獻與官方文件支持

### 5.1 rPPG 與 POS 的文獻支持

Wang、den Brinker、Stuijk 與 de Haan 的 POS/rPPG 論文建立皮膚反射模型，並提出 POS（Plane-Orthogonal-to-Skin）方法。本專案的 `pos_pulse()` 直接採用 temporally normalized RGB 與 `X/Y/alpha` 投影概念，對應該文獻的「以正交於 skin-tone 的平面抽取 pulse」技術方向。

Verkruysse 等人的 ambient-light rPPG 研究支持「一般 RGB 影像可觀察皮膚反射光中的脈搏相關變化」這個基本前提。Poh、McDuff 與 Picard 的 video-based pulse measurement 則支持低成本攝影機、臉部 ROI 與訊號處理可取得非接觸式心率估測。

2025 年 npj Digital Medicine 的 ROI 系統性回顧指出，ROI 選擇會影響 HR estimation accuracy，額頭與臉頰區域在多數研究中表現較好；2024 年針對活動與認知情境的 facial region 研究也指出 glabella、forehead、malar 等區域表現穩定。這支持本專案選用額頭、雙頰與眉間作為 rPPG ROI 的方向。

### 5.2 官方技術文件支持

MediaPipe Face Landmarker 官方文件說明此 task 可處理 image/video/live stream，輸出 3D face landmarks、blendshape scores 與 transformation matrices。本專案使用這些輸出來定位 ROI、估計姿態與避免重複建立多個 Face Landmarker。

SciPy 官方文件支持本專案使用的訊號處理 API：

- `scipy.signal.butter`：Butterworth filter 具平坦 passband；官方文件也建議使用 SOS representation 降低 IIR filter 數值問題。
- `scipy.signal.sosfiltfilt`：以 cascaded second-order sections 做 forward-backward filtering，可降低相位延遲。
- `scipy.signal.welch`：以重疊分段與 periodogram 平均估計 PSD，適合在心率頻帶找主要頻譜峰。
- `scipy.signal.find_peaks`：可用 distance、prominence 等 peak properties 選取 waveform local maxima，用於 IBI 估算。

### 5.3 校準與驗證方法支持

Bland 與 Altman 的 method comparison 文獻指出，兩種量測方法的比較不應只看 correlation，還要看 bias 與 limits of agreement。校準器目前已計算 MAE before/after 與 median residual，但尚未輸出 Bland-Altman plot 或 LoA；若要把此校準器升級成正式驗證工具，應補上該分析。

2026 年 npj Digital Medicine 的 rPPG clinical translation roadmap 強調 rPPG 走向臨床/真實部署需要更完整的資料集、硬體、濾波與 evaluation metrics。這支持本專案目前將校準器定位為工程可靠性工具，而不是單靠一次校準就宣稱醫療等效。

Apple Watch 心率準確度的 2025/2026 系統性回顧顯示，消費型手錶的 HR mean bias 可很小，但 limits of agreement 仍可能有數 BPM 等級的變異。因此手錶可作為方便的校準參考，但不是臨床 gold standard。若要做嚴謹驗證，應優先使用 ECG 胸帶、醫療級 PPG 或指夾式脈搏血氧儀作為 criterion method。

## 6. 為什麼要這樣實現

### 6.1 為什麼不是直接訓練 AI 心率模型

目前專案的 rPPG 主流程已是可解釋訊號處理 pipeline。若直接導入 AI/深度模型，會帶來：

- 需要大量含 ground truth HR 的訓練資料。
- 需要跨光源、膚色、相機、姿態、FPS、壓縮格式的泛化驗證。
- 會降低即時 GUI 的可解釋性與除錯性。
- 可能破壞既有使用者已觀察到「接近準確」的 POS 行為。

因此目前以 bias calibration 修正系統性偏差，是風險較低且符合資料量現況的做法。

### 6.2 為什麼使用手錶 HTTP POST

HTTP `POST /hr` 的優點：

- 不綁定特定手錶 SDK 或藍牙堆疊。
- PC 只需要開一個本機 LAN receiver。
- watch app、手機 app 或測試腳本都能用同一格式送資料。
- GUI 可即時顯示連線、POST 計數與 session 樣本數。

缺點是目前沒有身份驗證與加密，因此只適合可信任區域網路與校準用途，不應暴露到公開網路。

### 6.3 為什麼校準時使用 raw BPM

`calibration_rppg_bpm()` 在 `bpm_guarded=True` 且 `raw_bpm > 0` 時會使用 `raw_bpm`。原因是 BPM guard 的用途是日常顯示穩定化，可能短暫保留舊 BPM。校準若拿 guarded BPM 學 offset，可能學到 guard 的延遲，而不是 rPPG 原始估測對參考心率的偏差。

這是合理但需要注意的設計：若 raw BPM 本身是 artifact，仍需靠 SQI、quality score、ROI valid count 與時間窗中位數降低影響。

### 6.4 為什麼需要版本管理

校準偏移不是全域真理。它可能受以下因素影響：

- 相機型號與鏡頭曝光。
- 室內光源頻閃與色溫。
- 使用者與相機距離。
- ROI 被頭髮、眼鏡、口罩、陰影遮擋。
- 使用者膚色、臉部角度與姿態。
- 手錶本身的 PPG 品質與佩戴鬆緊。

版本管理讓操作者可以為不同情境保留校準版本，也能回到未校準原始值。

## 7. 三重審查結果

### 審查 1：官方文件與主要文獻

結論：通過。

- MediaPipe Face Landmarker 的輸出能力與本專案使用方式相容。
- SciPy `butter`、`sosfiltfilt`、`welch`、`find_peaks` 的用途與本專案 rPPG pipeline 相符。
- POS、ROI 選擇、Welch PSD、HRV 指標與 method comparison 的文獻可支持目前技術路線。
- 風險：文獻支持 rPPG 與校準驗證方法，但不等於本系統已完成臨床驗證。

### 審查 2：程式、部署與潛在錯誤

結論：工程架構合理，但仍有 beta 限制。

已確認：

- 校準資料不提交版本控制。
- live feed 與 active version 已串到 main window、combined worker、solo rPPG worker。
- 單元測試涵蓋 offset 套用、quality gate、session analyzer 與 version store。
- no-face 時會輸出 `RppgMetrics(face_detected=False)`，避免用舊 buffer。

限制：

- Analyzer 使用 `received_at` 對齊 watch 與 rPPG，未使用手錶 payload 的 `ts_ms` 做跨裝置時間同步。LAN 延遲通常小，但若手錶端批次傳送或網路抖動，窗口配對可能受影響。
- 目前只需要 `windows_used >= 1` 就可儲存版本。正式場域建議提高到至少 3 個有效窗口，或在 UI 顯示可信度等級。
- 目前只輸出 MAE before/after，尚未輸出 Bland-Altman bias/LoA、95th percentile error 或可用率。
- HTTP receiver 無驗證，應只在可信任 LAN 使用。

### 審查 3：專案慣例、文件與維運

結論：符合目前專案方向。

- 沒有改動 rPPG 核心演算法，只新增校準與套用層。
- 文件已在 README 描述功能入口與資料儲存位置。
- 個人/環境校準資料放在 `config/rppg_calibration/`，符合不提交使用者資料的安全規範。
- 後續若修改安裝、依賴或執行命令，才需要同步更新 setup 文件；本報告僅補技術分析。

## 8. 可信度與限制

本分析對「程式目前做了什麼」的信心值高於 90%，因為已直接閱讀最新提交、核心檔案與測試。

本分析對「這些技術有文獻支持」的信心值高於 90%，因為 POS、ROI、Welch、Butterworth、Face Landmarker、Bland-Altman 與 wearable HR validation 都有官方或主要文獻來源。

本分析不宣稱「本校準器已達醫療級準確度」。目前缺少：

- ECG/胸帶/醫療 PPG 對照資料。
- 多人、多膚色、多光源、多相機、多姿態驗證。
- Bland-Altman LoA。
- 校準前後跨 session drift 分析。
- 手錶參考裝置本身的品質標記。

## 9. 建議後續工作

1. 將 `windows_used` 儲存門檻從 1 提高到 3，並在 UI 標示 `LOW/MEDIUM/HIGH` 校準可信度。
2. 儲存每個 accepted window 的 watch/rPPG median、residual、SQI、quality score、ROI valid count，方便回放與審計。
3. 新增校準報告輸出：MAE before/after、median absolute error、95th percentile error、bias、LoA、有效窗口率。
4. 加入 Bland-Altman CSV/圖表輸出，避免只用平均誤差判斷 agreement。
5. 若要支援 scale/regression，必須要求校準 session 覆蓋低、中、高心率區間，否則容易過擬合。
6. 若手錶端能提供 monotonic timestamp 或 NTP 同步時間，應優先用裝置時間對齊，而不是只用 PC receive time。
7. 為 HTTP receiver 加入可選 token 或只綁定指定網卡/IP，降低 LAN 誤送資料風險。

## 10. 參考資料

1. MediaPipe Face Landmarker Python guide, Google AI Edge  
   https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
2. MediaPipe Face Landmarker guide, Google AI Edge  
   https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
3. Wang, W., den Brinker, A. C., Stuijk, S., de Haan, G. Algorithmic Principles of Remote PPG. IEEE Transactions on Biomedical Engineering, 2017.  
   https://doi.org/10.1109/TBME.2016.2609282  
   https://research.tue.nl/en/publications/algorithmic-principles-of-remote-ppg/
4. Verkruysse, W., Svaasand, L. O., Nelson, J. S. Remote plethysmographic imaging using ambient light. Optics Express, 2008.  
   https://doi.org/10.1364/OE.16.021434
5. Poh, M.-Z., McDuff, D. J., Picard, R. W. Non-contact, automated cardiac pulse measurements using video imaging and blind source separation. Optics Express, 2010.  
   https://doi.org/10.1364/OE.18.010762
6. Bondarenko, M., Menon, C., Elgendi, M. The role of face regions in remote photoplethysmography for contactless heart rate monitoring. npj Digital Medicine, 2025.  
   https://www.nature.com/articles/s41746-025-01814-9
7. Optimal facial regions for remote heart rate measurement during physical and cognitive activities. npj Imaging, 2024.  
   https://www.nature.com/articles/s44325-024-00033-7
8. SciPy `scipy.signal.butter` API reference  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html
9. SciPy `scipy.signal.sosfiltfilt` API reference  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html
10. SciPy `scipy.signal.welch` API reference  
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html
11. SciPy `scipy.signal.find_peaks` API reference  
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html
12. Welch, P. D. The use of fast Fourier transform for the estimation of power spectra. IEEE Transactions on Audio and Electroacoustics, 1967.  
    https://doi.org/10.1109/TAU.1967.1161901
13. Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology. Heart rate variability: standards of measurement, physiological interpretation and clinical use. Circulation, 1996.  
    https://pubmed.ncbi.nlm.nih.gov/8598068/
14. Bland, J. M., Altman, D. G. Statistical methods for assessing agreement between two methods of clinical measurement. The Lancet, 1986.  
    https://pubmed.ncbi.nlm.nih.gov/2868172/
15. Roadmap of remote photoplethysmography from heart rate measurement toward clinical translation. npj Digital Medicine, 2026.  
    https://pubmed.ncbi.nlm.nih.gov/42106569/
16. The accuracy of Apple Watch measurements: a living systematic review and meta-analysis. npj Digital Medicine, 2026.  
    https://www.nature.com/articles/s41746-025-02238-1
