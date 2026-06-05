# MediaPipe 疲勞偵測系統技術報告書

更新日期：2026-05-31

本報告整理本專案 MediaPipe 疲勞偵測子系統實際使用的 AI 模型、演算法、輸入輸出、可信度驗證方式與系統架構。依據檔案包含 `gui/combined_worker.py`、`gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、`gui/fatigue_worker.py`、`gui/mediapipe_tuning.py`、`config/mediapipe_tuning.json` 與 `tests/test_mediapipe_enhancements.py`。

## 1. 系統定位

MediaPipe 疲勞偵測系統使用 Face Landmarker 輸出的臉部特徵點（landmarks）、虹膜特徵點（iris landmarks）、表情係數（blendshape scores）與姿態資訊，估計使用者行為警覺狀態。疲勞判定本身是規則式、多門檻、個人化校準演算法，不是端到端 fatigue AI classifier。

主要輸出：

- `FatigueMetrics`：行為疲勞特徵與品質分數。
- `FusedFatigueScore`：行為疲勞與 rPPG 生理壓力融合後的整體疲勞分數。
- GUI overlay、Web dashboard 與 SQLite recorder 使用上述欄位顯示與回放。

## 2. AI 模型：MediaPipe Face Landmarker

唯一直接使用的 AI 模型是 `models/face_landmarker.task`。若模型不存在，程式會下載 Google MediaPipe model storage 的 `face_landmarker/float16/latest/face_landmarker.task`。

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

- PERCLOS：25%
- squint：20%
- microsleep：20%
- gaze：20%
- frown：10%
- yawn：5%

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

2. Gülin Tüfekci, Alper Kayabaşi, Erdem Akagündüz, İlkay Ulusoy, "Detecting Driver Drowsiness as an Anomaly Using LSTM Autoencoders", arXiv:2209.05269, 2022.
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
- Tereza Soukupová and Jan Čech, "Real-Time Eye Blink Detection using Facial Landmarks", 2016：https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf
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
