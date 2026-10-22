# 文件索引

首次使用請從[專案首頁](../README.md)開始；進階命令、相機疑難、回放與封裝驗收集中於[操作與驗證手冊](guides/operations.md)。

## 依用途閱讀

| 想了解的內容 | 文件 |
| --- | --- |
| 系統輸入輸出、核心方法與限制 | [系統總技術報告](technical/system_overview_technical_report.md) |
| 資料流、模組與演算法的關係 | [架構與演算法地圖](technical/system_architecture_algorithm_map.md) |
| ROI、脈波分離、濾波、BPM 與 HRV | [rPPG 技術報告 v2](technical/rppg_technical_report_v2.md)；實際 `pos_pulse` 公式與名稱限制見[首頁](../README.md)，[早期版本](technical/rppg_technical_report.md)供沿革參考 |
| EAR、PERCLOS、視線、表情與融合 | [MediaPipe 行為疲勞報告](technical/mediapipe_fatigue_technical_report.md) |
| 校準模型、品質 gate 與參考量測 | [心率校準技術分析](technical/rppg_heart_rate_calibrator_technical_analysis.md)；內含早期手錶流程，現行 BLE 操作依手冊 |
| BLE 通訊與真實裝置服務 | [心跳帶 GATT 對照](technical/heart_rate_belt_bluetooth_gatt_profile.md)、[Bluetooth／BLE 通訊指南](technical/bluetooth_ble_protocol_global_guide.md) |
| 離線回放、報表與驗證限制 | [UTA-RLDD 回放驗證報告](technical/utarldd_replay_validation_report.md) |
| 無人機操作情境與後續方向 | [應用定位](technical/drone_operator_fatigue_application_report.md)、[系統優化建議](technical/drone_operator_system_optimization_report.md) |
| 海報與介面研究素材 | [海報製作稿](technical/rppg_fatigue_monitoring_poster_design.md)、[Pavise UI 分析](technical/pavise-ui-analysis.md) |
| 本次實際產物分析與落地修正 | [2026-10-22 REA 分析報告](reviews/2026-10-22-rea-report.md) |

## 目錄約定

| 目錄 | 保存內容 | 使用方式 |
| --- | --- | --- |
| [`guides/`](guides/) | 目前操作、安裝後診斷與驗證命令 | 執行前核對平台、硬體與必要資產 |
| [`technical/`](technical/) | 系統與子系統技術報告 | 部分文件保存設計沿革，現行操作以首頁及手冊為準 |
| [`reviews/`](reviews/) | REA 發現、證據範圍與改善紀錄 | 區分實際驗證、推論及未驗證項目 |
| [`benchmarks/`](benchmarks/) | 已保存的測試與效能 JSON | 比較前核對日期、平台、測試模式與量測限制 |
| [`history/`](history/) | 有日期的校準、實驗與開發紀錄 | 用於追溯當時版本，不視為目前通用準確度承諾 |
| [`plans/`](plans/) | 遷移、平台分層與後續工作規劃 | 計畫存在不代表功能已完成 |

`docs/images/` 保存本機圖片與圖稿，`docs/exports/` 保存本機 PDF／簡報／文件輸出；兩者不納入 Git。`recordings/` 的影片、SQLite、CSV／HTML 回放產物，以及個人基線／校準亦保留本機。不要以報告中的本機素材路徑推定 fresh checkout 已包含該素材。

選用的 [Canva 流程圖 App](../tools/canva-flowchart/README.md) 位於 `tools/canva-flowchart/`，使用時選取本機 PNG／JPEG、確認預覽，再上傳並插入 Canva 設計；圖片不需要加入 Git。

## 驗證紀錄怎麼讀

歷史實驗見 [2026-06-07 UTA-RLDD 分析](history/2026-06-07-utarldd-analysis.md)與[2026-07-03 疲勞準確度校準](history/2026-07-03-fatigue-accuracy-calibration.md)。數字僅適用於文中資料、設定與版本；人臉偵測率、影片完成率、AUC、golden 零漂移與實體相機 smoke 各自回答不同問題。

調整數值路徑時需重新驗證對應資料；沒有資料集或硬體時，應明示未執行項目。正式 PDF 可由手冊列出的報告腳本重建，PDF 不作為版本控制中的主要來源。
