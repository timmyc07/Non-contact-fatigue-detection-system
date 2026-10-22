# MediaPipe 疲勞偵測系統技術報告書

> 2026-10-22 更新：新下載使用固定版本與 SHA-256 驗證後原子寫入，實作見 `gui/model_assets.py`；本機既有自訂模型仍保留。

更新日期：2026-06-16

本報告整理本專案 MediaPipe 疲勞偵測子系統實際使用的 AI 模型、演算法、輸入輸出、可信度驗證方式與系統架構。依據檔案包含 `gui/combined_worker.py`、`gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、`gui/fatigue_worker.py`、`gui/mediapipe_tuning.py`、`config/mediapipe_tuning.json` 與 `tests/test_mediapipe_enhancements.py`。

## 1. 系統定位

MediaPipe 疲勞偵測系統使用 Face Landmarker 輸出的臉部特徵點（landmarks）、虹膜特徵點（iris landmarks）、表情係數（blendshape scores）與姿態資訊，估計使用者行為警覺狀態。疲勞判定本身是規則式、多門檻、個人化校準演算法，不是端到端 fatigue AI classifier。

主要輸出：

- `FatigueMetrics`：行為疲勞特徵與品質分數。
- `FusedFatigueScore`：行為疲勞與 rPPG 生理壓力融合後的整體疲勞分數。
- GUI overlay、Web dashboard 與 SQLite recorder 使用上述欄位顯示與回放。

## 2. AI 模型：MediaPipe Face Landmarker

唯一直接使用的 AI 模型是 `models/face_landmarker.task`。若模型不存在，程式會下載 Google MediaPipe model storage 的 `face_landmarker/float16/1/face_landmarker.task`。

官方文件說明 Face Landmarker 可輸出 3D 臉部特徵點（3D face landmarks）、表情係數（blendshape scores）與臉部姿態轉換矩陣（facial transformation matrices）。

官方文件：  
https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python

### 2.1 模型 input

```text
攝影機原始影像（OpenCV BGR frame，藍綠紅色彩順序）
  -> 轉成模型使用的 RGB 色彩順序（cv2.cvtColor(..., COLOR_BGR2RGB)）
  -> 包裝成 MediaPipe 影像物件（mp.Image，標示影像為 SRGB）
  -> 以影片模式執行偵測（detect_for_video，並附上每張 frame 的 timestamp_ms 毫秒時間戳記）
```

模型設定：

- 影片連續偵測模式（`running_mode=VIDEO`）：讓模型依照連續 frame 的時間順序處理。
- 單人臉偵測（`num_faces=1`）：只追蹤畫面中最主要的一張臉。
- 輸出表情係數（`output_face_blendshapes=True`）：提供眨眼、瞇眼、皺眉與張嘴判斷。
- 輸出臉部姿態矩陣（`output_facial_transformation_matrixes=True`）：提供姿態補償與品質診斷。
- 室內穩定設定檔（active profile `stable_indoor`）下，偵測、存在與追蹤信心門檻（detection/presence/tracking confidence）為 0.6、0.6、0.7。

### 2.2 模型 output

- 第一張臉的 478 個臉部特徵點（`face_landmarks[0]`，normalized landmarks，座標已正規化到影像比例範圍）。
- 52 類表情係數（`face_blendshapes[0]`，例如眨眼、瞇眼、皺眉、張嘴等強度），程式轉成小寫 key-value map。
- 臉部姿態轉換矩陣（`facial_transformation_matrixes[0]`，描述臉部相對鏡頭的旋轉與位移），給 rPPG ROI/姿態補償使用；疲勞系統主要用 solvePnP 自行估 head pose。

重要臉部特徵點（landmarks）：

| 類別 | indices | 用途 |
| --- | --- | --- |
| EAR right eye | `[33,160,158,133,153,144]` | 右眼開合 |
| EAR left eye | `[362,385,387,263,373,380]` | 左眼開合 |
| iris | left `468-472`、right `473-477` | gaze、iris ratio、saccade |
| brow | `55`、`285` | 皺眉 |
| MAR mouth | `[61,82,13,312,291,316,14,86]` | 張嘴、哈欠 |
| solvePnP | `[1,199,33,263,61,291]` | head pitch/yaw/roll |

重要表情係數（blendshapes）：

- `eye_blink_left`、`eye_blink_right`
- `eye_squint_left`、`eye_squint_right`
- `brow_down_left`、`brow_down_right`、`brow_inner_up`
- `jaw_open`、`mouth_stretch_left`、`mouth_stretch_right`

## 3. 系統架構

```text
攝影機影像擷取流程
  -> 即時 BGR 影像佇列
  -> 共用臉部偵測與疲勞分析流程
  -> MediaPipe 臉部特徵點影片模式偵測
  -> 臉部特徵點、表情係數與姿態轉換矩陣
  -> 疲勞特徵分析流程
       -> 眼部與認知狀態分析
       -> 視線穩定度與掃視頻率分析
       -> 頭部姿態、微睡眠與張嘴哈欠分析
  -> 行為疲勞特徵與品質分數
  -> 行為疲勞與可選 rPPG 生理指標融合
  -> 整體疲勞分數
  -> 桌面畫面疊圖、網頁儀表板與 SQLite 紀錄
```

共用臉部偵測與疲勞分析流程是主流程，單一 Face Landmarker 同時供應 rPPG 與疲勞偵測，避免重複推論與畫面疊圖競爭。

內部模組：

- 眼部與認知狀態分析：EAR、blink、PERCLOS、squint、brow、iris ratio、表情係數個人基準值（blendshape baseline）。
- 視線穩定度與掃視頻率分析：gaze position、gaze stability、saccadic velocity、fixation duration、saccade frequency。
- 頭部姿態、微睡眠與張嘴哈欠分析：solvePnP head pose、microsleep、MAR、mouth open ratio、yawn。

效能策略：

- EAR、blink、gaze、iris 每 frame 執行。
- head pose 與 brow furrowing 預設每 3 frames 執行一次。
- 無臉時 reset 眼部 transient state、gaze 與部分 head/mouth state。

## 4. 品質 gate

疲勞系統會先判斷 frame 是否適合解讀：

- face area 必須夠大。
- roll 過大會降低 blink/fatigue 判讀。
- yaw ratio 過大代表轉頭太多。
- nose speed 過大代表頭部或畫面移動太快。
- lid balance 過大代表左右眼開合差異不可信。
- mouth open ratio 過大會干擾眼部品質。
- pitch-up gate：強烈抬頭時抑制 blink/fatigue 判讀。

`quality_score` 目前等於 `fatigue_q`，範圍 0 到 1。

## 5. EAR、眨眼與 PERCLOS

### 5.1 EAR

`eye_aspect_ratio(pts6)`：

```text
EAR = (dist(p2,p6) + dist(p3,p5)) / (2 * dist(p1,p4))
```

左右眼 EAR 取平均後以 EMA 平滑，`ear_ema_alpha=0.40`。

### 5.2 個人化校準

- `calib_sec=5.0`
- `min_calib_samples=20`
- 收集品質可接受且 `ear_smooth > calib_ear_min=0.15` 的樣本。
- 樣本足夠時 `base_ear_th = median(calib_ears) * thresh_ratio`，`thresh_ratio=0.75`。
- 樣本不足時使用 `base_th_default=0.18`。

### 5.3 眨眼

眨眼 state machine：

- EAR 低於 close threshold 進入閉眼。
- EAR 平滑值高於 `close_threshold * closed_open_hyst` 離開閉眼。
- 閉眼時間介於 `blink_min_sec=0.08` 與 `blink_max_sec=0.45` 才計為 blink。
- 60 秒 sliding window 內 blink 數為 `blink_rate_pm`。

### 5.4 PERCLOS

PERCLOS 使用 60 秒 sliding window：

```text
PERCLOS = window 內閉眼時間加權總和 / 有效觀察時間
```

設定：

- `perclos_window_sec=60.0`
- `tired_perclos_th=0.25`
- `long_closed_sec=1.5`

PERCLOS 達低警覺門檻時狀態為 `LOW_VIGILANCE`，達明顯嗜睡門檻時狀態為 `DROWSY`；連續閉眼超過 `long_closed_sec` 時狀態為 `CRITICAL`。

## 6. 瞇眼、皺眉與表情係數校準

### 6.1 表情係數個人基準值

不同使用者與光線下表情係數個人基準值（blendshape baseline）不同，因此系統做個人化校準：

- `blend_calib_sec=4.0`
- `blend_min_samples=24`
- quality 足夠且 blink_ok 時收集 blink/squint/brow 原始分數。
- baseline 使用 median。
- 結果可寫入 `config/mediapipe_calibration.json`。

正規化：

```text
norm = clamp((raw - baseline) / (1 - baseline), 0, 1)
```

### 6.2 瞇眼 squint

觸發條件：

- EAR 已校準。
- `base_ear_th < ear_smooth < base_ear_th * squint_ear_ratio`，`squint_ear_ratio=1.35`。
- 不是 blink。
- `lid_balance < lid_balance_gate_th`。
- `blend_eye_blink < blend_blink_gate=0.20`。
- 持續超過 `squint_min_sec=3.0`。

### 6.3 皺眉 brow furrowing

幾何特徵：

- 左右內眉距離除以眼角距離。
- 收集 `brow_calib_frames=120` 建立 baseline。

觸發條件：

- `brow_dist_norm < brow_furrow_ratio=0.85`，或
- `blend_brow_down > blend_brow_gate=0.18`。

## 7. Iris、gaze、saccade 與 fixation

若臉部特徵點（landmarks）數量達 478，系統使用虹膜特徵點（iris landmarks）。

Iris ratio：

```text
iris_ratio = iris_radius / (eye_height / 2)
```

Gaze：

```text
gx = mean((iris_x - eye_center_x) / eye_width)
gy = mean((iris_y - eye_center_y) / eye_height)
```

Gaze stability 在 3 秒 window 內計算：

```text
std = sqrt(var(gaze_x) + var(gaze_y))
gaze_stability_index = clamp(1 - std / (gaze_fixed_std_th * 4), 0, 1)
```

Saccade：

- `saccadic_velocity = displacement(gaze) / dt`
- 大於 `saccade_velocity_th=0.08` 視為 saccade。
- 60 秒 window 內換算 `saccade_freq_pm`。
- 非 saccade 持續時間為 `fixation_duration`。

`gaze_mental_fatigue` 觸發：

- gaze fixed 持續超過 `gaze_fixed_alert_sec=5.0`，或
- fixation duration 大於 10 秒且 saccade frequency 低於 1 次/分鐘。

## 8. Head pose、microsleep 與 yawn

### 8.1 solvePnP head pose

`solve_head_pose()` 使用 OpenCV `solvePnP`：

- 2D 臉部特徵點（2D landmarks）：`[1,199,33,263,61,291]`。
- 3D template：程式內 `_HEAD_POSE_3D`。
- camera matrix：以影像寬度為 focal length，principal point 為影像中心。
- distortion：零矩陣。
- 輸出：pitch、yaw、roll。

### 8.2 Microsleep

前 60 筆 head pitch 建立 baseline offset：

```text
pitch_rel = head_pitch - pitch_offset
```

若 `pitch_rel < -15.0` 且持續超過 1.5 秒，觸發 `microsleep_alert` 並增加 `microsleep_count`。同一次低頭只觸發一次。

### 8.3 MAR 與 yawn

`mouth_aspect_ratio(pts8)`：

```text
MAR = (dist(p2,p8) + dist(p3,p7) + dist(p4,p6)) / (2 * dist(p1,p5))
```

Yawn 條件：

- `mar > 0.60`
- `mouth_open_ratio > 0.24`
- `mouth_blend_stretch > 0.20`
- 持續超過 1.5 秒

Yawn 是晚期、低權重指標，以降低說話或一般張嘴造成的誤判。

## 9. FatigueMetrics 與狀態

狀態：

- `NO_FACE`
- `CALIBRATING`
- `OK`
- `LOW_VIGILANCE`
- `DROWSY`
- `CRITICAL`
- `MICROSLEEP`

`fatigue_level`：

```text
0.40 * PERCLOS
+ 0.30 * microsleep_alert
+ 0.15 * squint_duration/30
+ 0.15 * frowning
+ 0.10 * gaze_mental_fatigue
+ 0.05 * blend_eye_squint
+ 0.05 * blend_brow_down
+ 0.05 * yawn_count/10
```

結果 clamp 到 0 到 1。

## 10. rPPG 與行為疲勞融合

`FatigueFuser` 產生 `FusedFatigueScore`。

預設權重：

- rPPG：15%
- behavior：85%

若其中一個 pillar 不可用，可用者承接 100%；兩者都不可用時 score 為 0。

rPPG 可用條件：

- face detected。
- warmup 完成。
- `sqi >= 0.45`。
- `quality_score >= 0.55`。
- `roi_valid_count >= 3`。

behavior 可用條件：

- face detected。
- EAR calibrated。

Behavior sub-score 權重：

- PERCLOS：35%
- blink temporal：25%
- microsleep：20%
- gaze：10%
- squint：5%
- yawn：5%
- frown：0%

分數等級：

| score | level_en |
| --- | --- |
| 0.00 到 0.20 | Alert |
| 0.20 到 0.40 | Mild |
| 0.40 到 0.60 | Moderate |
| 0.60 到 0.80 | High |
| 0.80 到 1.00 | Critical |

## 11. 數值可信度驗證

### 11.1 測試

目前測試涵蓋：

- tuning profiles 載入。
- 表情係數個人基準值正規化（blendshape baseline normalization）。
- face quality motion penalty。
- ROI jitter 與 ROI area stability。
- rPPG/behavior 同時可用時融合權重為 15% / 85%。
- 低 SQI rPPG 會被忽略。
- SQLite metrics recorder schema 包含 MediaPipe diagnostics 欄位。

必要驗證：

```bash
.venv/bin/python -m pytest -q
```

若修改 Python：

```bash
.venv/bin/python -m compileall -q main.py gui rppg tests scripts
.venv/bin/python -m pip check
```

### 11.2 現場驗證

建議情境：

1. 清醒注視螢幕 2 分鐘，確認 `OK` 為主、PERCLOS 低、microsleep 為 0。
2. 自然眨眼與快速眨眼，確認 blink count 增加但不觸發 squint/DROWSY。
3. 持續瞇眼 5 到 10 秒，確認 squint 與 early_warning 上升。
4. 閉眼 2 秒，確認 long closed 或 DROWSY。
5. 低頭 2 秒，確認 microsleep 只觸發一次。
6. 說話、張嘴與哈欠分開測試，確認 yawn 需要 MAR、mouth ratio、blend jaw gate 與持續時間同時成立。
7. 轉頭、抬頭、快速晃動，確認 quality score 下降且不產生高信心疲勞判讀。

### 11.3 人工標註比對

若要驗證數值可信度，建議建立錄影資料集並人工標註：

- blink event。
- closed-eye interval。
- microsleep/nod event。
- yawn event。
- turn head / occlusion / lighting change。

指標：

- blink count error。
- PERCLOS MAE。
- microsleep precision/recall/F1。
- yawn precision/recall/F1。
- false alarm rate per hour。

### 11.4 回放與 profile sweep

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
.venv/bin/python scripts/mediapipe_profile_sweep.py recordings/video_YYYYMMDD_HHMMSS.mp4 --csv reports/mediapipe_profile_sweep.csv
```

應檢查 detection rate、fatigue quality score、landmark jitter、ROI area stability 與不同 profile 對追蹤穩定度的影響。

## 12. 限制

- Face Landmarker 是通用臉部 landmark/表情模型，不是疲勞醫療模型。
- EAR、MAR、PERCLOS 對相機角度、眼鏡、遮擋、眼型與照明敏感。
- Iris/gaze 在一般 webcam 上容易受解析度與反光影響。
- solvePnP 使用簡化 3D template 與估計 camera matrix，head pose 是近似值。
- 表情係數個人基準值（blendshape baseline）若在不自然表情下校準，後續分數會偏移。
- 本系統不應作為醫療診斷、安全執法或單獨自動決策依據。

## 13. 維運建議

- 修改 landmark index、EAR/MAR 門檻、PERCLOS window、solvePnP template 或融合權重時，必須保留固定錄影回放比較。
- 修改 `config/mediapipe_tuning.json` active profile 時，應跑 profile sweep。
- 新增 AI 模型時，必須記錄模型檔名、來源、版本、input/output、推論模式與 fallback。
- `config/mediapipe_calibration.json` 是個人/環境校準結果，不應提交版本控制。

## 14. 參考資料與本系統採用技術

1. MediaPipe Face Landmarker Python guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python  
   本系統參考技術：Face Landmarker 設定物件（`FaceLandmarkerOptions`）、影片連續偵測模式（`RunningMode.VIDEO`）、影片模式偵測呼叫（`detect_for_video()`）、表情係數輸出（`output_face_blendshapes`）、臉部姿態矩陣輸出（`output_facial_transformation_matrixes`）、信心門檻（confidence threshold）與單人臉偵測數量（`num_faces`）設定。

2. MediaPipe Face Landmarks Detection guide  
   https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker  
   本系統參考技術：Face Landmarker 的 3D 臉部特徵點（3D landmarks）、表情係數（blendshape scores）、臉部姿態轉換矩陣（facial transformation matrices）輸出；本專案以臉部特徵點建立 EAR/MAR/gaze/head pose 特徵，以表情係數輔助 blink、squint、brow 與 jaw 判斷。

3. Camillo Lugaresi et al., "MediaPipe: A Framework for Building Perception Pipelines", arXiv:1906.08172, 2019  
   https://arxiv.org/abs/1906.08172  
   本系統參考技術：即時感知處理流程（perception pipeline）與 graph-based 處理概念；本專案以單一 Face Landmarker 產生共同臉部特徵點，分流給 rPPG 與疲勞分析流程。

4. Tereza Soukupova and Jan Cech, "Real-Time Eye Blink Detection using Facial Landmarks", 21st Computer Vision Winter Workshop, 2016  
   https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf  
   本系統參考技術：Eye Aspect Ratio（EAR，眼睛長寬比例）六點眼睛模型；本專案用左右眼 6 個特徵點（landmarks）計算 EAR、眨眼與閉眼狀態。

5. Grace, R., Byrne, V. E., Bierman, D. M., Legrand, J. M., Gricourt, D., Davis, B. K., Staszewski, J. J., Carnahan, B., "A Drowsy Driver Detection System for Heavy Vehicles", Digital Avionics Systems Conference, 1998  
   https://doi.org/10.1109/DASC.1998.741493  
   本系統參考技術：以眼睛閉合比例作為駕駛嗜睡偵測指標的概念；本專案用 PERCLOS sliding window 計算疲勞程度。

6. National Highway Traffic Safety Administration, "Development of a Drowsy Driver Detection System", DOT HS 808 247, 1998  
   https://rosap.ntl.bts.gov/view/dot/1644  
   本系統參考技術：PERCLOS 作為 drowsiness detection 的工程驗證概念；本專案將 PERCLOS 與長閉眼事件作為 LOW_VIGILANCE/DROWSY/CRITICAL 判斷依據。

7. OpenCV `solvePnP` documentation  
   https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html  
   本系統參考技術：以 3D 物體點（3D object points）與 2D 影像點（2D image points）求解相機姿態（camera pose）；本專案用 6 個臉部特徵點（landmarks）與簡化 3D 臉部模板估算 pitch/yaw/roll。

8. OpenCV camera calibration and 3D reconstruction module  
   https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html  
   本系統參考技術：Rodrigues、camera matrix 與 pose decomposition 的基本工具；本專案將 solvePnP 的 rotation vector 轉為 rotation matrix 後估角度。

9. W. Wang, A. C. den Brinker, S. Stuijk, G. de Haan, "Algorithmic Principles of Remote PPG", IEEE Transactions on Biomedical Engineering, 2017  
   https://doi.org/10.1109/TBME.2016.2609282  
   本系統參考技術：rPPG POS 生理訊號估計；本專案在融合分數中使用 rPPG pillar 作為 15% 輔助疲勞/壓力訊號。

10. Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology, "Heart rate variability: standards of measurement, physiological interpretation and clinical use", Circulation, 1996  
    https://pubmed.ncbi.nlm.nih.gov/8598068/  
    本系統參考技術：HRV 指標 RMSSD、SDNN、LF/HF 的定義；本專案在融合器中使用 rPPG stress、BPM deviation 與 LF/HF 作為輔助生理 pillar。

11. SciPy `scipy.signal.find_peaks` API reference  
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html  
    本系統參考技術：rPPG IBI peak detection；本報告中的融合說明引用此 rPPG pipeline 產生的生理指標。

12. OpenCV drawing and image processing documentation  
    https://docs.opencv.org/4.x/d6/d6e/group__imgproc__draw.html  
    本系統參考技術：畫面疊圖標註（overlay annotation）與臉部特徵點/取樣區域（landmarks/ROI）繪製；本專案將疲勞特徵畫到 GUI preview。

## 15. 2026-06-05 修訂：駕駛疲勞文獻導入與基準值定義

本次修訂的目標，是把汽車駕駛疲勞偵測中較成熟的行為特徵，轉換成適合無人機駕駛員監測的即時規則式判定。重要原則如下：文獻提供「哪些特徵與疲勞/嗜睡有關」與「常見建模方向」，但本系統的實際警示門檻必須經由個人化校準、回放驗證與場域測試決定，不把論文中的資料集結果直接當成所有使用者的固定閾值。

### 15.1 本次實作調整

- 新增 `LOW_VIGILANCE` 低警覺狀態：在 PERCLOS 尚未達明顯嗜睡門檻前，若 PERCLOS 升高、眨眼時序異常、長時間凝視、瞇眼或其他早期訊號出現，先進入低警覺提醒。
- 新增 `CRITICAL` 危急狀態：連續閉眼達 `long_closed_sec=1.5` 秒時，視為需要旁人即時介入的危急訊號；若同時出現 head nod / microsleep，仍由 `MICROSLEEP` 優先輸出。
- 新增眨眼時序特徵：每次有效 blink 會記錄 `blink_duration_sec`、`blink_amplitude`、`blink_opening_velocity`，並以前 12 次有效眨眼建立個人 baseline，再計算 `blink_duration_z`、`blink_opening_velocity_z` 與 `blink_temporal_score`。
- 融合分數調整：行為疲勞分數提高 PERCLOS 與 blink temporal 的比重，皺眉不再作為疲勞主權重；皺眉在無人機操作情境更可能代表 workload / stress，應作為輔助觀察而非疲勞主因。
- Web dashboard、preview overlay、SQLite recorder 與 playback API 已串接新增欄位，讓門檻觸發與後續回放分析可追蹤。

### 15.2 如何定義疲勞

本系統把疲勞定義為「操作員警覺度下降到可能影響監控、判斷或操控反應的狀態」，而不是醫療診斷。實作上分成五個層級：

| 狀態 | 本系統意義 | 主要觸發 |
| --- | --- | --- |
| `OK` | 目前行為特徵接近個人清醒基準 | EAR/PERCLOS/眨眼/頭部/嘴部皆未達警示 |
| `LOW_VIGILANCE` | 早期低警覺，應觀察或口頭提醒 | PERCLOS >= 0.10、blink temporal score >= 0.45、長凝視、瞇眼等 |
| `DROWSY` | 明顯嗜睡風險 | PERCLOS >= 0.25 |
| `CRITICAL` | 危急閉眼事件，旁人應立即介入 | 連續閉眼 >= 1.5 秒 |
| `MICROSLEEP` | 微睡眠/點頭事件，最高優先級 | head nod / microsleep rule 觸發 |

### 15.3 臉部特徵疲勞基準值如何決定

- EAR / 閉眼：本系統不使用單一固定 EAR 門檻。啟動後先取得個人開眼 EAR baseline，再由 baseline 推導 blink close/open 與閉眼判定，降低眼型、眼鏡、鏡頭角度造成的個體差異。
- PERCLOS：參考駕駛疲勞文獻中「一段時間內眼睛高度閉合比例」的概念，本系統以 60 秒 sliding window 計算閉眼時間比例。`0.10` 是低警覺工程門檻，`0.25` 是明顯嗜睡工程門檻；它們不是論文保證值，後續必須用本專案錄影回放調整。
- 眨眼時序：參考早期嗜睡會出現較慢、較長眼瞼閉合與開眼動態變化的概念。本系統用前 12 次有效 blink 建立個人 blink duration / amplitude / opening velocity baseline。當 duration z-score 偏高或 opening velocity z-score 偏低時，提高 `blink_temporal_score`。
- 長閉眼與微睡眠：`long_closed_sec=1.5` 秒是本系統安全導向的危急保護門檻；微睡眠則結合 head pitch offset 與持續時間判斷，用來捕捉點頭/低頭事件。
- Gaze / fixation：長時間凝視、低 saccade frequency 或 gaze stability 過高，可能代表警覺下降，也可能代表專注操作。因此只作為早期警示輔助，不單獨把人判成嗜睡。
- MAR / yawn：張嘴與哈欠是疲勞常見行為訊號，但在說話、咳嗽、操作溝通時容易誤判，因此權重較低，作為 late-stage 輔助訊號。
- Brow / frown：皺眉更接近認知負荷、壓力或操作困難，不作為 fatigue 主權重。本次融合權重已降為 0。

### 15.4 本機五份論文與採用內容

1. Mohamed W. Gomaa, Rasha O. Mahmoud, Amany M. Sarhan, "A CNN-LSTM-based Deep Learning Approach for Driver Drowsiness Prediction", Journal of Engineering Research, 2022.
   網路來源：https://digitalcommons.aaru.edu.jo/erjeng/vol6/iss3/7
   本系統參考內容：CNN 擷取影像特徵、LSTM 學習時序依賴，以及 NTHU driver drowsiness dataset 作為駕駛疲勞時序建模背景。本次沒有導入 CNN-LSTM 模型，因目前專案需要可解釋且可即時調整的規則式基準。

2. Gulin Tufekci, Alper Kayabasi, Erdem Akagunduz, Ilkay Ulusoy, "Detecting Driver Drowsiness as an Anomaly Using LSTM Autoencoders", arXiv:2209.05269, 2022.
   網路來源：https://arxiv.org/abs/2209.05269
   本系統參考內容：只用正常駕駛表徵建立個人/單人 baseline，將偏離正常的時序特徵視為 anomaly。這支持本系統用個人化 EAR 與 blink temporal baseline，而不是套用所有人的固定門檻。

3. Reza Ghoddoosian, "Human Behavior Modeling in Long Videos: Drowsiness Detection and Action Segmentation", PhD Dissertation, University of Texas at Arlington, 2022；其中包含 "A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection".
   網路來源：https://mavmatrix.uta.edu/cse_dissertations/316 與 https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html
   本系統參考內容：`alert / low vigilant / drowsy` 三階段概念，以及早期疲勞應重視時間序列變化而非單幀表情。本次因此新增 `LOW_VIGILANCE` 分級。

4. Shirisha Vadlamudi, "Driver Drowsiness Detection on Raspberry Pi 4", California State University San Marcos, 2020.
   網路來源：https://scholarworks.calstate.edu/concern/theses/jm214v860
   本系統參考內容：即時邊緣裝置上的駕駛疲勞工程實作思路，包含攝影機輸入、臉部/眼部行為特徵與低延遲部署。本次保留規則式與輕量計算，避免導入高成本模型造成 GUI 延遲。

5. 王奕鈞（Yi-Chun Wang），《應用電腦視覺於臉部膚色變化與心率關係之探討》，國立清華大學碩士論文，2026。
   本系統參考內容：MediaPipe Face Mesh 定位前額與雙頰 ROI、多色彩空間比較、GRU/LOSO 驗證，以及雙頰與 Lab 色彩空間在動態情境下較穩健的結論。本次沒有替換既有 rPPG 主流程，只把它列為後續 rPPG ROI/color-space 優化方向。

### 15.5 其他主要技術來源

- MediaPipe Face Landmarker Python guide：https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
  參考 Face Landmarker 的 478 landmarks、blendshape scores、facial transformation matrix、`RunningMode.VIDEO` 與 `detect_for_video()`。
- Tereza Soukupova and Jan Cech, "Real-Time Eye Blink Detection using Facial Landmarks", 2016：https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf
  參考 EAR 六點眼睛比例與 blink detection 思路。
- PERCLOS-based technologies for detecting drowsiness: current evidence and future directions, Sleep Advances, 2023：https://pmc.ncbi.nlm.nih.gov/articles/PMC10108649/
  參考 PERCLOS 作為 established drowsiness measure，以及常見「眼睛高度閉合時間比例」定義差異。
- National Highway Traffic Safety Administration, "Assessment of Drowsy Driver Algorithms", DOT HS 809 884：https://www-nrd.nhtsa.dot.gov/departments/Human%20Factors/810594/pages/AppC.htm
  參考 drowsiness observer rating、長閉眼、PERCLOS 與嚴重嗜睡行為描述。
- OpenCV `solvePnP` documentation：https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html
  參考 3D object points 與 2D image points 推估 camera pose 的技術，用於 head pitch/yaw/roll。

### 15.6 現在還應該做什麼

1. 建立無人機操作員專用標註資料：至少錄製清醒、長時間專注、低警覺、閉眼、打哈欠、轉頭、光線變化等情境，標註事件時間。
2. 用 recorder 新增欄位回放比較：觀察 `perclos`、`blink_temporal_score`、`blink_duration_z`、`blink_opening_velocity_z`、`status` 與旁人標註是否一致。
3. 以 false alarm rate per hour、低警覺提前量、危急事件 recall 作為門檻調整指標。
4. 暫時不要把 rPPG 當疲勞主判定；rPPG 保留為生理負荷/壓力輔助，等有同步心率參考與疲勞標註後再提高權重。
## 16. 2026-06-06 UTA-RLDD 回放驗證與門檻校正資料

本次新增 UTA-RLDD 影片回放測試，實作檔案為 `gui/utarldd_replay.py` 與 `scripts/utarldd_replay.py`，GUI 入口位於主視窗「UTA-RLDD 影片測試」區塊。它把資料集影片當作離線鏡頭逐幀餵入 MediaPipe Face Landmarker，再依序產生疲勞行為特徵、rPPG 指標與 fused score。此流程不改 live camera worker，也不直接更動現有疲勞門檻。回放模式使用影片 FPS 產生 timestamp；`FatigueEngine` 的 EAR / blendshape 校準起點對齊第一個有效人臉 frame，因此 replay 與 live camera 可共用同一套校準邏輯，避免離線影片因 timestamp 從 0 秒開始而整段停留在 `CALIBRATING`。

資料集標籤依 UTA-RLDD 官方定義：

- `0 = Alert`
- `5 = Low Vigilant`
- `10 = Drowsy`

出處：

- UTA-RLDD official site, https://sites.google.com/view/utarldd/home
- Reza Ghoddoosian, Marnim Galib, Vassilis Athitsos, "A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection", CVPR Workshops, 2019, https://openaccess.thecvf.com/content_CVPRW_2019/html/AMFG/Ghoddoosian_A_Realistic_Dataset_and_Baseline_Temporal_Model_for_Early_Drowsiness_CVPRW_2019_paper.html

本專案參考此資料集與論文的部分，是 `alert / low vigilant / drowsy` 三階段警覺度標籤、長影片時序驗證思路，以及用資料集影片比較疲勞趨勢的做法。第一版不把 UTA-RLDD label 當逐幀 ground truth；同一支影片只視為整段類別，用於檢查本系統在三種警覺度影片中的統計趨勢是否合理。

回放摘要會輸出：

- `utarldd_summary_<timestamp>.csv`：給人工快速檢視的好讀摘要，包含中文欄位、百分比化的 face rate/PERCLOS、快速判讀、主要疲勞/rPPG 指標與狀態分布。
- `utarldd_validation_report_<timestamp>.csv`：整批驗證趨勢報表，包含 `label_summary` 與 `subject_trend`，用於檢查 label 0/5/10 是否呈現疲勞趨勢上升；此報表比逐支影片摘要更適合回答「這批資料是否支持系統」。
- `utarldd_summary_full_<timestamp>.csv`：完整欄位版本，保留原始 summary dataclass 欄位供 notebook、統計分析與稽核。
- `utarldd_visual_report_<timestamp>.html`：由 summary CSV 產生的單檔可視化報表，用於快速檢視標籤對齊、主要判斷依據、優化旗標與誤報/漏報風險。
- 行為疲勞：`avg_fatigue_score`、`p95_fatigue_score`、`avg_perclos`、`max_perclos`、`avg_blink_temporal`、`max_blink_temporal`、`LOW_VIGILANCE/DROWSY/CRITICAL/MICROSLEEP/NO_FACE` frame counts。
- 融合分數：`avg_fused_score`、`p95_fused_score`。
- 可用性：frames、face_frames、face_rate、duration_sec、fps、width、height。
- rPPG 診斷：`avg_rppg_quality`、`avg_sqi`、`avg_bpm`、`bpm_guard_count`。

GUI replay 會同步顯示 MediaPipe 人臉特徵與 rPPG ROI 標註預覽，目的在於讓操作者一邊跑批次一邊確認偵測是否正常。預覽影像會限制尺寸並以最高約 20 FPS 顯示，降低 GUI 主執行緒負擔；這個預覽不改變 DB 與 CSV 的逐幀數值計算，也不會取代完整 SQLite 回放。

即時 Web dashboard 預覽與 UTA-RLDD replay 預覽需分開解讀。2026-06-16 後，live camera 與即時分析 worker 的 preview producer 目標為 30 FPS，Web 端使用 `QImageWriter` 編成 JPEG base64 後推送 `frame_update`；UTA-RLDD 離線 replay 預覽仍維持約 20 FPS，避免批次處理時 Qt 主執行緒負擔過高。兩者都只影響畫面顯示，不改變疲勞指標、rPPG 指標、融合分數、DB 或 CSV/HTML 報表。

大量驗證時不建議用 GUI 一支一支觀察完整影片，而應使用 CLI `--jobs N` 或 GUI「平行驗證」做多進程批次。GUI「開始批次」保留單工標註預覽，適合確認 MediaPipe 偵測是否正常；GUI「平行驗證」依「平行數」設定跑多進程並停用預覽，適合正式跑 60 位受試者。平行驗證期間，GUI 的「處理清單」會顯示目前進行中的 subject/label、已完成數/總數，以及最近完成影片的 frame 數、狀態與 face rate，讓操作者可直接確認批次處理到哪些影片。為降低 Windows 多進程、OpenCV 影片解碼與 MediaPipe 初始化造成的資源壓力，GUI 平行數上限為 4，且平行模式會自動停用標註影片輸出；若子行程異常中止，系統會把未完成影片標成 `failed` 並保留摘要檔，讓驗證流程可追蹤而不是只留下英文 pool 錯誤。此平行化只在不同影片之間進行；單支影片內仍逐幀順序分析，使 EAR、PERCLOS、眨眼時序、rPPG buffer 與 MediaPipe VIDEO timestamp 維持可重現。這能在不改變疲勞門檻與逐幀輸出的前提下，提高資料集驗證效率。

臉部特徵疲勞基準值的決定方式維持原則：

1. 文獻與資料集提供「哪些特徵應該看」以及分類趨勢，例如 PERCLOS、EAR/閉眼時間、blink temporal、gaze、head pose、yawn 與 low vigilant/drowsy 分層。
2. 系統目前的工程門檻仍保守維持，不因 UTA-RLDD 單一資料集自動覆蓋。
3. 使用 UTA-RLDD replay 後，先比較 `0/5/10` 三類影片的分布：Drowsy 影片理論上應有較高 `p95_fatigue_score`、PERCLOS、blink temporal score 與 drowsy/critical frame ratio；Alert 影片應有較低比例。
4. 若統計趨勢不符合預期，再回到固定錄影與真人標註做 A/B 校正，門檻調整需同時檢查 false alarm rate、miss rate 與 no-face/low-quality 占比。

因此，本次新增的是「校正與驗證資料管線」，不是新的疲勞判定門檻。它能補足受試者不足時的早期測試，但最終仍需無人機駕駛員現場資料確認。

## 17. 無人機駕駛員場域定位

本專題主旨為監測無人機駕駛員疲勞狀態。MediaPipe 疲勞子系統應被放在「遠端操作員長時間監控與操控任務」的情境下解讀：操作員可能持續注視地面站畫面、頻繁切換注意力、承受任務負荷或低刺激監控造成的警覺下降。此時 PERCLOS、眨眼時序、長閉眼、head pose、gaze dynamics 與 yawn 是行為疲勞主特徵，rPPG 只作為生理負荷與訊號品質輔助。

汽車駕駛與 UTA-RLDD 文獻只提供可借用的疲勞特徵與長影片驗證方法，不代表本專題目標改為汽車駕駛分類。後續若要提高可信度，最重要的是建立無人機操作員專用標註資料：清醒監控、長時間專注、低警覺、閉眼、轉頭查看其他螢幕、任務壓力上升、打哈欠與遮擋等情境，並以這些資料校正無人機場域的門檻。

## 18. 2026-06-07 UTA-RLDD 最新測試分析

最新測試使用 `recordings/utarldd_runs/20260607_122601/utarldd_summary_20260607_122601.csv` 與同批次 validation report。批次共 36 支影片，12 位受試者，每位受試者各含 Alert、Low Vigilant、Drowsy 三段影片；36 支皆成功完成，沒有 failed 影片。

本次測試最強的結果是管線穩定性，而不是分類準確率。三類影片平均人臉偵測率分別為 Alert 99.98%、Low Vigilant 99.89%、Drowsy 99.93%，整體約 99.93%。因此若報告中使用「滿分」或「接近 100%」說法，只能指影片處理完成率與人臉偵測率，不能指疲勞分類準確率。

從疲勞特徵看，PERCLOS 指標有部分支持：平均 PERCLOS 在 Alert、Low Vigilant、Drowsy 分別約為 2.46%、2.68%、5.10%；最高 PERCLOS 平均約為 6.67%、12.69%、17.03%。Drowsy 類別的嗜睡/危急 frame 比例約 3.99%，高於 Alert 與 Low Vigilant 的約 0.03%。這表示閉眼比例與較嚴重狀態對部分 Drowsy 影片有反應。

但融合分數沒有跟著資料集標籤穩定上升：平均融合分數在 Alert、Low Vigilant、Drowsy 分別約為 0.060、0.048、0.054；95 分位融合分數約為 0.156、0.144、0.134。這與 `0 -> 5 -> 10` 的理論警覺度下降方向不一致，validation report 因此判定「目前不支持分類有效」。

若依展示需求把 UTA-RLDD 影片級標籤整理成清醒、低警覺、疲勞三類，並把本系統 `快速判讀` 對應為清醒、低警覺、疲勞，本批 36 支影片的粗略三分類對照為：UTA 清醒 12 支中，本系統判清醒 2 支、低警覺 10 支、疲勞 0 支；UTA 低警覺 12 支中，本系統判清醒 1 支、低警覺 8 支、疲勞 3 支；UTA 疲勞 12 支中，本系統判清醒 2 支、低警覺 6 支、疲勞 4 支。對角線相符合計 14/36。此數字只代表影片級粗略對齊，不是逐幀 accuracy、precision、recall 或正式三分類準確率；完整表格與分析見 `docs/history/2026-06-07-utarldd-analysis.md` 的「UTA-RLDD 影片級三分類對照表」。

這份結果暴露三個需要在畢專報告誠實揭露的限制：

1. `LOW_VIGILANCE` 對 Alert 影片偏敏感，容易造成早期警示誤報。
2. Drowsy 影片若沒有長閉眼或明顯 PERCLOS 上升，現有規則可能漏報。
3. UTA-RLDD label 是整段影片類別，不是逐幀標註，因此不能直接換算逐幀 accuracy、precision 或 recall。
4. 2026-06-07 舊批次 summary 平均值會受到 `CALIBRATING`、`NO_FACE` 與尚未完成行為校準的 frame 影響；新版 replay schema 已加入有效 frame 分母，但舊批次若不重跑，只能依既有欄位與 HTML 報表標註限制。
5. replay 若讀到本機持久化 blendshape baseline，可能影響資料集可重現性；下一版應使用 replay 專用 calibration namespace 或停用持久化讀寫。

畢專展示時，建議將本系統定位為「可即時運作的疲勞監測原型與驗證資料管線」。已完成部分包含 MediaPipe 特徵擷取、個人化 EAR baseline、PERCLOS、眨眼時序、head pose、rPPG 輔助融合、GUI、Web dashboard、SQLite 紀錄與 UTA-RLDD replay。尚未完成部分是以標註資料做門檻校正與三分類泛化驗證。詳細收尾建議見 `docs/history/2026-06-07-utarldd-analysis.md` 。

## 19. 2026-06-16 專案審視補充

本輪審視確認近期小修集中在顯示同步與工程品質：Web dashboard 會在初始連線與 `request_metrics` 時補送 GUI 最新狀態，Web preview 改用 `QImageWriter` 推送 JPEG 並以 30 FPS 為 live 目標，`20260607_122601` 回測結果已轉成 HTML 可視化報表。這些修正不更動 EAR、PERCLOS、眨眼時序、head pose、yawn、rPPG 或融合權重。

最新工程驗證紀錄為 `npx pyright` 0 errors / 0 warnings，完整 `pytest` 為 `68 passed`。後續若調整疲勞門檻，仍應以固定 replay、人工標註與 false alarm / miss rate 指標做 A/B 比較。
