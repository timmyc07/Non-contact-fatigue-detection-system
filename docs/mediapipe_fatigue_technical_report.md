# MediaPipe 疲勞偵測系統技術報告書

更新日期：2026-05-31

本報告整理本專案 MediaPipe 疲勞偵測子系統實際使用的 AI 模型、演算法、輸入輸出、可信度驗證方式與系統架構。依據檔案包含 `gui/combined_worker.py`、`gui/fatigue_engine.py`、`gui/fatigue_scorer.py`、`gui/fatigue_worker.py`、`gui/mediapipe_tuning.py`、`config/mediapipe_tuning.json` 與 `tests/test_mediapipe_enhancements.py`。

## 1. 系統定位

MediaPipe 疲勞偵測系統使用 Face Landmarker 輸出的臉部 landmarks、iris landmarks、blendshape scores 與姿態資訊，估計使用者行為警覺狀態。疲勞判定本身是規則式、多門檻、個人化校準演算法，不是端到端 fatigue AI classifier。

主要輸出：

- `FatigueMetrics`：行為疲勞特徵與品質分數。
- `FusedFatigueScore`：行為疲勞與 rPPG 生理壓力融合後的整體疲勞分數。
- GUI overlay、Web dashboard 與 SQLite recorder 使用上述欄位顯示與回放。

## 2. AI 模型：MediaPipe Face Landmarker

唯一直接使用的 AI 模型是 `models/face_landmarker.task`。若模型不存在，程式會下載 Google MediaPipe model storage 的 `face_landmarker/float16/latest/face_landmarker.task`。

官方文件說明 Face Landmarker 可輸出 3D face landmarks、blendshape scores 與 facial transformation matrices。

官方文件：  
https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python

### 2.1 模型 input

```text
OpenCV BGR frame
  -> cv2.cvtColor(..., COLOR_BGR2RGB)
  -> mp.Image(image_format=SRGB)
  -> detect_for_video(mp_img, timestamp_ms)
```

模型設定：

- `running_mode=VIDEO`
- `num_faces=1`
- `output_face_blendshapes=True`
- `output_facial_transformation_matrixes=True`
- active profile `stable_indoor` 時 detection/presence/tracking confidence 為 0.6、0.6、0.7。

### 2.2 模型 output

- `face_landmarks[0]`：第一張臉的 478 點 normalized landmarks。
- `face_blendshapes[0]`：52 類表情係數，程式轉成小寫 key-value map。
- `facial_transformation_matrixes[0]`：給 rPPG ROI/姿態補償使用；疲勞系統主要用 solvePnP 自行估 head pose。

重要 landmarks：

| 類別 | indices | 用途 |
| --- | --- | --- |
| EAR right eye | `[33,160,158,133,153,144]` | 右眼開合 |
| EAR left eye | `[362,385,387,263,373,380]` | 左眼開合 |
| iris | left `468-472`、right `473-477` | gaze、iris ratio、saccade |
| brow | `55`、`285` | 皺眉 |
| MAR mouth | `[61,82,13,312,291,316,14,86]` | 張嘴、哈欠 |
| solvePnP | `[1,199,33,263,61,291]` | head pitch/yaw/roll |

重要 blendshapes：

- `eye_blink_left`、`eye_blink_right`
- `eye_squint_left`、`eye_squint_right`
- `brow_down_left`、`brow_down_right`、`brow_inner_up`
- `jaw_open`、`mouth_stretch_left`、`mouth_stretch_right`

## 3. 系統架構

```text
CameraStreamWorker
  -> BGR frame queue
  -> CombinedWorker
  -> FaceLandmarker.detect_for_video
  -> landmarks / blendshapes / transformation matrix
  -> FatigueEngine.step
       -> EyeCognitiveModule
       -> GazeTrackingModule
       -> HeadMouthModule
  -> FatigueMetrics
  -> FatigueFuser + optional RppgMetrics
  -> FusedFatigueScore
  -> GUI overlay / Web dashboard / SQLite recorder
```

`CombinedWorker` 是主流程，單一 Face Landmarker 同時供應 rPPG 與疲勞偵測，避免重複推論與 overlay 競爭。

內部模組：

- `EyeCognitiveModule`：EAR、blink、PERCLOS、squint、brow、iris ratio、blendshape baseline。
- `GazeTrackingModule`：gaze position、gaze stability、saccadic velocity、fixation duration、saccade frequency。
- `HeadMouthModule`：solvePnP head pose、microsleep、MAR、mouth open ratio、yawn。

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

PERCLOS 達門檻時狀態為 `TIRED`；連續閉眼超過 `long_closed_sec` 時狀態為 `DROWSY`。

## 6. 瞇眼、皺眉與 blendshape 校準

### 6.1 Blendshape baseline

不同使用者與光線下 blendshape baseline 不同，因此系統做個人化校準：

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

若 landmarks 數量達 478，系統使用 iris landmarks。

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

- 2D landmarks：`[1,199,33,263,61,291]`。
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
- `ALERT`
- `TIRED`
- `DROWSY`
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
- blendshape baseline normalization。
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
- blendshape baseline 若在不自然表情下校準，後續分數會偏移。
- 本系統不應作為醫療診斷、安全執法或單獨自動決策依據。

## 13. 維運建議

- 修改 landmark index、EAR/MAR 門檻、PERCLOS window、solvePnP template 或融合權重時，必須保留固定錄影回放比較。
- 修改 `config/mediapipe_tuning.json` active profile 時，應跑 profile sweep。
- 新增 AI 模型時，必須記錄模型檔名、來源、版本、input/output、推論模式與 fallback。
- `config/mediapipe_calibration.json` 是個人/環境校準結果，不應提交版本控制。
