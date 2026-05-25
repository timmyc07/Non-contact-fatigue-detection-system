# 2026-05-21 MediaPipe 部位擴充更新紀錄

## 變更內容

- 新增鼻部穩定特徵：
  - 使用鼻尖與鼻樑參考點估算鼻部穩定度。
  - 將鼻動量作為疲勞品質閘門的一部分，降低頭動對判定的干擾。
- 新增眼瞼精細特徵：
  - 明確輸出左右眼瞼開合度。
  - 增加左右眼瞼差異，讓單側半閉眼或偏斜更容易被辨識。
- 新增嘴部活動特徵：
  - 由嘴唇內緣與嘴角計算嘴部開合比例。
  - 在哈欠判定前加入嘴部開合條件，降低短暫說話或動嘴造成的誤判。
- 視覺化更新：
  - 疲勞預覽疊圖新增鼻部、眼瞼差、嘴部開合的提示。
- MediaPipe 輸出擴充：
  - `output_face_blendshapes=True` 與 `output_facial_transformation_matrixes=True` 已同步開啟到 rPPG 與 fatigue worker。
  - blendshape 已加入個人化 baseline 正規化，現在用於眼、眉、嘴的輔助閘門，幾何 landmark 仍是主訊號。
- rPPG 精準度提升：
  - 已加入 transformation matrix 驅動的 ROI roll 補償。
  - 已加入 ROI 動態權重，依 yaw / roll / pitch 調整 forehead、左右 cheek、glabella 的取樣比重。
  - 已加入 ROI 遮擋降權，依亮度、色度與極端值偵測降低異常 ROI 權重。
  - 已加入 ROI polygon EMA 平滑，降低 MediaPipe landmark 微抖造成的 ROI 取樣跳動。
  - 已加入 landmark jitter 與 ROI 面積穩定度診斷，並納入 rPPG quality score。
  - 已新增實驗性 canonical ROI warp 開關，預設關閉，僅供固定錄影回放比較。
  - 已建立 `quality_score`，整合姿態、face area、motion proxy、ROI 可用率、SQI 與 artifact ratio。
  - `quality_score` 已同步接到 GUI、Web metrics、SQLite 錄製與融合分數。
- 個人化校準：
  - blendshape baseline 已支援跨 session 持久化，校準結果儲存在 `config/mediapipe_calibration.json`。
  - 該檔案已加入 `.gitignore`，避免提交個人或環境特徵。
- 參數外部化：
  - 新增 `config/mediapipe_tuning.json`，集中管理 Face Landmarker confidence、ROI 權重、遮擋門檻、quality score 權重與 blendshape gate。
  - 已新增 `active_profile` / `profiles`，可用 `default`、`stable_indoor`、`low_light`、`high_motion` 做場景化調參；切換後需重啟 worker / 應用程式。
- 回放與診斷：
  - SQLite 錄製欄位新增 rPPG quality、pose、ROI 權重、fatigue quality 與 blend calibration progress。
  - SQLite 錄製欄位新增 landmark jitter、ROI 面積穩定度、ROI smoothing 與 canonical ROI warp 狀態。
  - Web dashboard live/playback 已顯示新增診斷欄位。
  - 新增 `scripts/replay_calibration_summary.py`，可從錄製資料庫彙整品質與 ROI 權重狀態。
  - 新增 `scripts/mediapipe_profile_sweep.py`，可用同一段錄影比較不同 MediaPipe profile 的偵測率與 ROI 穩定度。
- 參數調整與優化方向：
  - 已採用保守值：`min_face_detection_confidence=0.55`、`min_face_presence_confidence=0.55`、`min_tracking_confidence=0.60`。
  - 已補上後續調參建議與可再擴充方向。

## 影響範圍

- `gui/fatigue_engine.py`
- `gui/fatigue_worker.py`
- `gui/preview_overlay_window.py`
- `gui/combined_worker.py`
- `rppg/rppg_worker.py`
- `rppg/demo_rppg_live.py`
- `docs/rppg_technical_report.md`
- `gui/fatigue_scorer.py`
- `gui/main_window.py`
- `gui/metrics_recorder.py`
- `gui/mediapipe_tuning.py`
- `gui/web_server.py`
- `gui/web_ui/templates/dashboard.html`
- `gui/web_ui/static/dashboard.js`
- `config/mediapipe_tuning.json`
- `scripts/replay_calibration_summary.py`
- `scripts/mediapipe_profile_sweep.py`
- `tests/test_mediapipe_enhancements.py`

## 驗證紀錄

- `.venv/bin/python -m py_compile rppg/rppg_worker.py rppg/demo_rppg_live.py gui/fatigue_engine.py gui/combined_worker.py gui/fatigue_worker.py gui/fatigue_scorer.py gui/main_window.py gui/metrics_recorder.py gui/preview_overlay_window.py gui/web_server.py gui/mediapipe_tuning.py scripts/replay_calibration_summary.py tests/test_mediapipe_enhancements.py`
- `.venv/bin/python -m compileall -q main.py gui rppg tests scripts`
- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m pip check`

## 備註

- 這次擴充只使用現有 MediaPipe Face Landmarker 的 landmark，沒有更換模型。
- rPPG 的 POS / 濾波 / Welch / IBI 主流程沒有更動。
- 參數調整原則仍採保守策略，優先降低誤判與提升穩定度。
- transformation matrix 目前落地為 roll 補償與姿態導向 ROI 權重；完整 3D mesh warp 仍屬下一階段精修項目，避免在未驗證資料集前大幅改變 rPPG 數值行為。
- canonical ROI warp 目前是預設關閉的實驗開關；正式啟用前需附固定錄影回放比較，不以即時觀察作為唯一依據。

## 參考文獻

- MediaPipe Face Landmarker Python 官方文件：https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python
- MediaPipe Face Landmarker 官方概覽：https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker
- MediaPipe 官方文件首頁：https://ai.google.dev/edge/mediapipe
