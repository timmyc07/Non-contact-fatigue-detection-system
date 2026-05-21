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
  - 已建立 `quality_score`，整合姿態、face area、motion proxy、ROI 可用率、SQI 與 artifact ratio。
  - `quality_score` 已同步接到 GUI、Web metrics、SQLite 錄製與融合分數。
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
- `tests/test_mediapipe_enhancements.py`

## 驗證規劃

- `python -m compileall`
- `pytest`
- 實機預覽檢查新增提示是否正常顯示

## 備註

- 這次擴充只使用現有 MediaPipe Face Landmarker 的 landmark，沒有更換模型。
- rPPG 的 POS / 濾波 / Welch / IBI 主流程沒有更動。
- 參數調整原則仍採保守策略，優先降低誤判與提升穩定度。
- 目前 transformation matrix 補償以 roll 為主，尚未做完整 3D ROI warp。

## 參考文獻

- MediaPipe Face Landmarker Python 官方文件：https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python
- MediaPipe Face Landmarker 官方概覽：https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker
- MediaPipe 官方文件首頁：https://ai.google.dev/edge/mediapipe
