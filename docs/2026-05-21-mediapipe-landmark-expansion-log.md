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

## 影響範圍

- `gui/fatigue_engine.py`
- `gui/fatigue_worker.py`
- `gui/preview_overlay_window.py`

## 驗證規劃

- `python -m compileall`
- `pytest`
- 實機預覽檢查新增提示是否正常顯示

## 備註

- 這次擴充只使用現有 MediaPipe Face Landmarker 的 landmark，沒有更換模型。
- rPPG 的 POS / 濾波 / Welch / IBI 主流程沒有更動。
