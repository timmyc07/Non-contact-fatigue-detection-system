# rPPG 系統技術報告書

更新日期：2026-05-31

本報告整理本專案 rPPG 子系統實際使用的模型、演算法、技術、輸入輸出、可信度驗證方式與系統架構。依據檔案包含 `rppg/rppg_worker.py`、`rppg/demo_rppg_live.py`、`gui/combined_worker.py`、`gui/mediapipe_tuning.py`、`config/mediapipe_tuning.json` 與 `tests/test_rppg_signal_processing.py`。

## 1. 系統定位

rPPG（remote photoplethysmography）使用一般 RGB 攝影機觀察臉部皮膚顏色的微小週期變化，推估心跳頻率與心率變異度。本專案的 rPPG 不使用心率 AI 模型；AI 只用於臉部 landmark/ROI 定位，BPM、HRV、SQI 與壓力指標皆由訊號處理與 heuristic 產生。

此子系統輸出：

- `bpm`：Welch PSD peak 對應的每分鐘心跳數。
- `rmssd`、`sdnn`：由 rPPG peak IBI 推估的 time-domain HRV。
- `lf_hf`：由 IBI tachogram 推估的 LF/HF。
- `sqi`：訊號品質指標。
- `stress_prob`、`stress_status`：以 LF/HF 與 RMSSD 估計的壓力 heuristic。
- `hrv_confidence`、`ibi_artifact_ratio`：HRV 可信度與 IBI 異常比例。
- `quality_score`、姿態、ROI 權重、ROI 可用數、landmark 抖動與 ROI 面積穩定度：可信度診斷欄位。

## 2. 使用模型與技術

### 2.1 MediaPipe Face Landmarker

本專案唯一 AI 模型是 MediaPipe Face Landmarker，模型檔為 `models/face_landmarker.task`。若缺少模型，`ensure_face_model()` 會下載 Google MediaPipe model storage 的 `face_landmarker/float16/latest/face_landmarker.task`。

模型 input：

- OpenCV BGR frame 轉為 RGB。
- 以 `mp.Image(image_format=mp.ImageFormat.SRGB, data=...)` 包裝。
- `RunningMode.VIDEO` 需要單調遞增的 `timestamp_ms`。

模型 output：

- `face_landmarks[0]`：478 點 normalized face landmarks，rPPG 用來建立皮膚 ROI polygon。
- `facial_transformation_matrixes[0]`：用於 roll 補償、姿態估計與 ROI 診斷。
- `face_blendshapes[0]`：在 `CombinedWorker` 中傳給疲勞系統；rPPG 心率估算本身不使用 blendshape。

本專案設定：

- `running_mode=VIDEO`
- `num_faces=1`
- `output_face_blendshapes=True`
- `output_facial_transformation_matrixes=True`
- `active_profile=stable_indoor` 時 detection/presence/tracking confidence 分別為 0.6、0.6、0.7。

官方文件：MediaPipe Face Landmarker Python guide  
https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python

### 2.2 OpenCV

OpenCV 負責 frame 轉色、ROI mask、ROI 平均色與 overlay：

- `cv2.cvtColor`：BGR/RGB 轉換。
- `cv2.fillConvexPoly`：依 ROI polygon 建立 mask。
- `cv2.GaussianBlur`：以 5x5 blur 降低 ROI pixel noise。
- `cv2.mean`：計算 mask 內平均 BGR，再轉為 `(R, G, B)`。
- `cv2.polylines`：在 preview 上繪製 ROI。

### 2.3 SciPy 與 NumPy

rPPG 訊號處理使用：

- `scipy.signal.butter`：Butterworth band-pass filter。
- `scipy.signal.sosfiltfilt`：second-order sections 零相位濾波。
- `scipy.signal.welch`：power spectral density。
- `scipy.signal.find_peaks`：由 pulse waveform 找 IBI。
- `scipy.interpolate.interp1d`：IBI tachogram 4 Hz 重採樣。

官方文件：

- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.interp1d.html

## 3. 系統架構

```text
攝影機影像擷取流程
  -> 即時 BGR 影像佇列
  -> 共用臉部偵測分流流程或單獨 rPPG 分析流程
  -> MediaPipe 臉部特徵點影片模式偵測
  -> 臉部特徵點與姿態轉換矩陣
  -> 臉部皮膚 ROI 取樣
  -> rPPG 時序訊號緩衝區
  -> POS 脈波訊號分離
  -> Butterworth 帶通濾波
  -> Welch 頻譜峰值搜尋
  -> 心率、心率變異度、訊號品質與壓力指標
  -> 桌面畫面疊圖、網頁儀表板與 SQLite 紀錄
```

共用臉部偵測分流流程是 GUI 主流程。它只建立一個 Face Landmarker，將同一份臉部特徵點同時送給 rPPG 與疲勞偵測，避免同一 frame 重複推論。無臉時會重設 rPPG 訊號緩衝區與 ROI 幾何追蹤狀態，避免舊 buffer 影響下一段量測。

## 4. ROI 取樣

使用四個 MediaPipe 478 點 face mesh ROI：

| ROI | Landmark indices |
| --- | --- |
| forehead | `[107, 66, 69, 109, 10, 338, 299, 296, 336, 9]` |
| L_cheek | `[118, 119, 100, 126, 209, 49, 129, 203, 205, 50]` |
| R_cheek | `[347, 348, 329, 355, 429, 279, 358, 423, 425, 280]` |
| glabella | `[151, 108, 107, 55, 8, 285, 336, 337]` |

流程：

1. 將 normalized landmark 轉為 pixel。
2. 若有 transformation matrix，估計 roll/yaw/pitch，並對 ROI 做 roll 補償。
3. `canonical_roi_warp_enabled` 預設關閉；開啟時才做實驗性姿態導向 ROI 幾何正規化。
4. `RoiGeometryTracker` 使用 EMA 平滑 ROI polygon。
5. polygon mask 面積少於 30 pixel 時視為無效。
6. 對 frame 做 5x5 Gaussian blur，計算 mask 內平均 `(R, G, B)`。
7. 以亮度、chroma、姿態與遮擋估計 ROI 診斷權重。
8. 實際送入 POS 的 RGB sample 使用「有效 ROI 等權平均」；姿態/遮擋權重保留為診斷與 ROI 可用性判斷。

診斷欄位：

- `roi_valid_count`
- `roi_weight_forehead`、`roi_weight_l_cheek`、`roi_weight_r_cheek`、`roi_weight_glabella`
- `landmark_jitter_norm`
- `roi_area_stability`
- `roi_area_jitter_ratio`
- `roi_smoothing_applied`
- `canonical_roi_warp_used`

## 5. POS 演算法

`pos_pulse(r, g, b)` 使用 POS（Plane-Orthogonal-to-Skin）從 RGB 時序萃取 pulse waveform。

輸入：ROI 平均後的 R/G/B 時序。

計算：

```text
R' = (R - mean(R)) / (std(R) + 1e-8)
G' = (G - mean(G)) / (std(G) + 1e-8)
B' = (B - mean(B)) / (std(B) + 1e-8)

X = 3R' - 2G'
Y = 1.5R' + G' - 1.5B'
alpha = std(X) / (std(Y) + 1e-8)
pulse = X - alpha * Y
```

輸出：一維 pulse waveform。

原理：血容量變化造成皮膚反射光有週期性 RGB 微變化；POS 透過色彩投影降低光照與膚色基線的共同變動，保留與脈搏較相關的頻率成分。

## 6. Buffer、取樣率與暖機

`RppgEngine` 預設 `buffer_sec=12.0`、`target_fps=30.0`。實際取樣率由 timestamp 推估：

```text
dt = (t_last - t_first) / (n - 1)
fs = clip(1 / dt, 8, 90)
```

資料少於 4 秒時只輸出暖機、亮度、姿態與品質欄位，不輸出 BPM/HRV。完整暖機進度以 `max(6 秒, buffer_sec * 0.5)` 對應樣本數估算。

## 7. Band-pass filter

`butter_bandpass(sig, fs, low=0.65, high=3.7, order=3)` 使用 3 階 Butterworth band-pass：

- 0.65 Hz 約 39 BPM。
- 3.7 Hz 約 222 BPM。

優先使用 `butter(..., output="sos")` 與 `sosfiltfilt` 做零相位濾波；失敗時 fallback 到 `butter` + `filtfilt`。SOS 格式可降低 IIR filter 數值不穩定風險。

## 8. Welch PSD 與 BPM

`welch_peak_hz(filt, fs)`：

- `nperseg = min(256, max(32, n // 2))`
- `noverlap = nperseg // 2`
- `nfft = max(2048, nperseg * 4)`
- peak 搜尋頻帶：0.7 到 3.5 Hz，約 42 到 210 BPM。

找到最大 PSD peak 後，對 peak 前後三點做 log-power parabolic interpolation，提升 71/72/73 BPM 這類細節解析度。最後 `BPM = peak_hz * 60`。

BPM 穩定化：

- 只接受 42 到 210 BPM。
- 與目前穩定 BPM 相差超過 25 BPM 時，需在 2 秒內累積 4 個候選且彼此落在 8 BPM 內才確認。
- 最近 10 秒候選值取 median，再用 EMA alpha 0.18 平滑。

## 9. SQI 與品質分數

`compute_sqi(sig, fs)`：

```text
SQI = PSD power(0.6 Hz 到 4.0 Hz) / total PSD power
```

`quality_score` 合併：

- face quality：roll/yaw/pitch、face area、face motion、ROI valid ratio。
- signal quality：`0.60 * sqi + 0.40 * (1 - ibi_artifact_ratio)`。
- stability quality：`landmark_jitter_norm` 與 `roi_area_stability`。

非暖機階段：

```text
quality_score = 0.42 * face_quality + 0.38 * signal_quality + 0.20 * stability_quality
```

疲勞融合採用 rPPG 的條件：

- face detected。
- warmup 完成。
- `sqi >= 0.45`。
- `quality_score >= 0.55`。
- `roi_valid_count >= 3`。

## 10. IBI 與 HRV

`ibi_from_peaks(filt, fs)`：

- peak distance：`fs * 0.35`。
- prominence：`std(sig) * 0.35 + 1e-6`。
- IBI：相鄰 peak 時間差，單位 ms。

`validate_ibi_intervals()`：

1. 移除 NaN/inf。
2. 保留 300 到 2000 ms。
3. 以 local median 與 adaptive threshold 移除離群 IBI。
4. 再用 30% local median 規則做第二層過濾。

HRV：

- `RMSSD = sqrt(mean(diff(IBI)^2))`
- `SDNN = std(IBI, ddof=1)`
- LF/HF：IBI tachogram 線性插值到 4 Hz，Welch PSD 後計算 LF 0.04 到 0.15 Hz、HF 0.15 到 0.4 Hz。

HRV confidence：

- LOW：IBI 少於 6、SQI 低於 0.25 或 artifact ratio 高於 0.35。
- MEDIUM：IBI 少於 12、SQI 低於 0.45 或 artifact ratio 高於 0.15。
- HIGH：其餘較可信狀態。

## 11. 壓力 heuristic

`stress_heuristic(lf_hf, rmssd)` 不是 AI 模型。

```text
lf_term = clip((lf_hf - 1.2) / 2.5, 0, 1)
rm_term = clip((65.0 - rmssd) / 65.0, 0, 1)
stress_prob = clip(0.45 * lf_term + 0.55 * rm_term, 0, 1)
```

LF/HF 或 RMSSD 不可用時輸出 `stress_prob=0.0`、`stress_status="calibrating"`。

## 12. 數值可信度驗證

### 12.1 測試

目前單元測試涵蓋：

- 合成 72 BPM 訊號，band-pass + Welch 誤差小於 4 BPM。
- 合成 73 BPM 訊號，Welch peak 細節誤差小於 2 BPM。
- IBI outlier 清理。
- artifact ratio。
- buffer channel 對齊。
- BPM stabilizer 抑制短暫突跳、確認持續突跳、拒絕不合理 BPM。
- ROI 權重正規化、motion quality penalty、ROI jitter 與 area stability。

必要驗證：

```bash
.venv/bin/python -m pytest -q
```

若修改 Python：

```bash
.venv/bin/python -m compileall -q main.py gui rppg tests scripts
.venv/bin/python -m pip check
```

### 12.2 現場與回放驗證

建議以指夾式 PPG、胸帶或智慧手錶作為參考儀器：

1. 固定光源、坐姿與相機曝光。
2. 前 10 到 15 秒視為暖機，不納入統計。
3. 每段 60 到 120 秒，比較 rPPG BPM 與參考 BPM。
4. 計算 MAE、median absolute error、95th percentile error 與可用率。
5. 同步檢查 SQI、quality score、ROI valid count、landmark jitter 與 ROI area stability。

既有工具：

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
.venv/bin/python scripts/mediapipe_profile_sweep.py recordings/video_YYYYMMDD_HHMMSS.mp4 --csv reports/mediapipe_profile_sweep.csv
```

注意：profile sweep 只能比較偵測率、ROI 可用數與幾何穩定度，不等同 BPM ground truth 驗證。

## 13. 限制

- rPPG 對光源、頭部動作、相機 FPS、自動曝光、遮擋與膚色敏感。
- 12 秒 buffer 對 BPM 可用，但對 LF/HF 等 HRV 指標偏短。
- 週期性動作或光源閃爍可能被 Welch peak 誤判為心率。
- `stress_prob` 是 heuristic，不是醫療或臨床 AI 模型。
- 本系統輸出不應用於醫療診斷或安全關鍵單點決策。

## 14. 參考資料與本系統採用技術

1. MediaPipe Face Landmarker Python guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python  
   本系統參考技術：`FaceLandmarkerOptions`、`RunningMode.VIDEO`、`detect_for_video()`、`output_face_blendshapes`、`output_facial_transformation_matrixes`、face landmarks 與 transformation matrix 的輸入輸出定義。

2. MediaPipe Face Landmarks Detection guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker  
   本系統參考技術：Face Landmarker 可輸出 3D face landmarks、blendshape scores 與 facial transformation matrices；本專案將 landmarks 用於 ROI，matrix 用於姿態與 ROI roll 補償。

3. Camillo Lugaresi et al., "MediaPipe: A Framework for Building Perception Pipelines", arXiv:1906.08172, 2019  
   https://arxiv.org/abs/1906.08172  
   本系統參考技術：MediaPipe perception pipeline 的即時推論概念；本專案以單一 Face Landmarker worker 共用 landmarks，降低重複推論成本。

4. W. Wang, A. C. den Brinker, S. Stuijk, G. de Haan, "Algorithmic Principles of Remote PPG", IEEE Transactions on Biomedical Engineering, 2017  
   https://doi.org/10.1109/TBME.2016.2609282  
   本系統參考技術：POS（Plane-Orthogonal-to-Skin）rPPG 方法；本專案採用 RGB 時序正規化、`X = 3R - 2G`、`Y = 1.5R + G - 1.5B` 與 `pulse = X - alpha * Y` 的色彩投影概念。

5. Peter D. Welch, "The Use of Fast Fourier Transform for the Estimation of Power Spectra", IEEE Transactions on Audio and Electroacoustics, 1967  
   https://doi.org/10.1109/TAU.1967.1161901  
   本系統參考技術：以分段、重疊與平均估計 power spectral density；本專案使用 Welch PSD 在心率頻帶尋找 peak 估算 BPM，並用 PSD band power 計算 SQI。

6. SciPy `scipy.signal.welch` API reference  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html  
   本系統參考技術：`fs`、`nperseg`、`noverlap`、`nfft` 參數與 PSD 輸出；本專案用於 BPM peak、SQI 與 LF/HF 頻域估計。

7. Stephen Butterworth, "On the Theory of Filter Amplifiers", Wireless Engineer, 1930  
   https://www.changpuak.ch/electronics/downloads/On_the_Theory_of_Filter_Amplifiers.pdf  
   本系統參考技術：Butterworth filter 的平坦 passband 概念；本專案用 3 階 Butterworth band-pass 保留心跳頻帶並削弱漂移與高頻雜訊。

8. SciPy `scipy.signal.butter` API reference  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html  
   本系統參考技術：Butterworth IIR filter 設計與 SOS 輸出；本專案以 `output="sos"` 建立 band-pass filter。

9. SciPy `scipy.signal.sosfiltfilt` API reference  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html  
   本系統參考技術：second-order sections forward-backward 零相位濾波；本專案用於降低相位延遲對 peak timing 的影響。

10. SciPy `scipy.signal.find_peaks` API reference  
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html  
    本系統參考技術：以 distance 與 prominence 找 local maxima；本專案用於 pulse waveform peak detection 與 IBI 估算。

11. SciPy `scipy.interpolate.interp1d` API reference  
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.interp1d.html  
    本系統參考技術：一維線性插值；本專案將不等間隔 IBI tachogram 重採樣到 4 Hz 以計算 LF/HF。

12. Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology, "Heart rate variability: standards of measurement, physiological interpretation and clinical use", Circulation, 1996  
    https://pubmed.ncbi.nlm.nih.gov/8598068/  
    本系統參考技術：RMSSD、SDNN、LF/HF 的 HRV 指標定義與頻帶概念；本專案採用這些指標名稱與計算方向，但因 rPPG 短窗限制，僅作趨勢參考。

13. OpenCV VideoCapture documentation  
    https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html  
    本系統參考技術：相機 frame 擷取；本專案由 camera worker 取得 BGR frame 並餵入 rPPG pipeline。

14. OpenCV image filtering documentation  
    https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html  
    本系統參考技術：Gaussian blur；本專案在 ROI mean color 前做 5x5 blur 降低 pixel noise。
