# 面板呈現效能與操作體驗優化（2026-10-23）

本次僅修改 Flutter 呈現層、前端連線生命週期與測試；不修改 Python engine、rPPG、疲勞判定、ROI、校準、HRV、錄影與資料庫行為。任務分級為中量：同一前端子系統，不變更數值路徑、依賴或 API 契約。

## 可見變更

- 統一深色背景、青綠重點色、字級、欄距、表單與按鈕；減少裝飾陰影、裁切及無操作意義的 hover 位移。
- 即時頁把狀態與心率置頂，將攝影機預覽和主要操作並排；自動採集選項可展開，仍保留全部原有操作。
- 側欄依寬度與文字比例縮成圖示導航，提供選取語意及提示。連線狀態改為實際狀態，不再固定顯示成功。
- 狀態卡移除沒有量測依據的固定環形進度。缺少 EAR、PERCLOS 或俯仰資料時顯示 `--`；有效值格式與原本一致。
- 心跳帶讀值自適應排列；裝置名稱、位址、HRV 與錯誤可完整換行。校準與設備卡在窄窗改為單欄。
- 歷史頁採單一捲動區與惰性列表；小視窗可將回測控制區捲走，完整保留 200 筆分頁、相對時間與原有數值格式。
- 設定分為分析、擷取、Overlay、個人化、資料連線與重設；儲存狀態清楚可見，重設保留二次確認。
- 使用者、警報、快捷鍵及重設對話框可在窄窗與放大文字下捲動；原本驗證與完整 payload 保留。
- 視窗拖曳手勢限制於標題區，避免與最小化、最大化、關閉操作競爭。
- 載入錯誤在所有頁面可見；重試會針對失敗的清單或目前指標頁執行，成功後清除提示。

## 效能改動與證據

| 改動 | 可驗證的範圍 |
| --- | --- |
| `LivePreviewImage` 自行訂閱與更新，獨立 `RepaintBoundary` | 影格更新不再呼叫主 Shell 或 Overlay Shell 的 `setState`；未顯示預覽的頁面不訂閱／解碼影像 |
| 同一繪製週期只解碼最新待處理影格 | 測試送入 100 筆事件，只排程一次、實際解碼最後一張，父元件 build 次數保持 1 |
| 淘汰已顯示過的 `MemoryImage` 快取 | 20 張逐次解碼後，每輪 image cache / live image 皆為 1，pending 為 0；卸載後皆為 0 |
| metrics 使用局部 `ValueListenableBuilder` | 串流更新只影響當前監測／心跳帶內容；設定、歷史與導覽不再隨每筆 metrics 重建 |
| 相同 control state 不觸發 Shell 重建 | 保留原有一秒輪詢與狀態同步，不降低後端資料更新頻率 |
| 移除監測頁 `IntrinsicHeight` | 攝影機及控制區不再進行額外 intrinsic layout pass |
| 共用 metrics broadcast controller | 多訂閱只註冊一組 socket listeners，最後取消才釋放；dispose 關閉串流 |
| 過期 HTTP polling 回覆檢查來源 | 重新連線後，舊輪詢的回覆不會覆蓋新連線資料；原本兩秒備援輪詢及逾時維持不變 |
| 歷史頁 `SliverList.builder` | 1000 筆記錄測試驗證不會一次建構所有列 |

這些證據限定於重建、排程、生命週期、快取與惰性建構，不等同實機 FPS、CPU／GPU 百分比或長時間記憶體壓測。

## 驗證

- 完整 `flutter test`：76 項通過；包括即時／專注模式、Overlay、設定、對話框、歷史、心跳帶、連線與影格測試。
- `flutter analyze`：No issues found。
- 對應 Python 契約測試：`test_flutter_command_contract.py`、`test_desktop_shell_config.py`、`test_desktop_control_api.py`、`test_desktop_settings_api.py`，共 166 項通過。
- `python -m compileall -q main.py gui rppg scripts tests`、`pip check`、`git diff --check` 通過。
- 小窗與文字比例：即時頁 360／760／1024 寬、最高 2.25 倍；心跳帶 360 寬／1.8 倍；歷史 360 寬／最高 2.25 倍；設定 400 寬／1.6 倍；對話框最低 320 寬／最高 2.25 倍；Overlay 原有 320×180／2.25 倍驗證保留。
- macOS arm64 `.app` release 建置成功，`codesign --verify --deep --strict` 通過；沿用既有本機 ad-hoc 簽章。
- 本機已安裝新版並保留舊版備份；實際巡覽即時、心跳帶、歷史頁。設定頁另以相同 release Web 產物確認排版、導航與離線提示；獨立 HTTP 預覽來源無後端存取權，未更改 CORS 或安全設定。
- 完成獨立程式審查、命令集合比對與 read-back。Dart library 拆為 `part` 後，Python command-contract 測試同步讀取宣告的 parts，仍要求全部原有命令集合完全相同。

## 版本與文件依據

本機 Flutter 3.47.2／Dart 3.13.2；socket_io_client 3.1.6、http 1.6.0；Tauri CLI 2.11.4。不新增或升級依賴。

開始前已搜尋 GitHub 開源桌面 dashboard 及 Flutter 官方範例；使用現有 Material 元件，沒有複製或新增第三方 dashboard 套件。Context7 `/flutter/website` 僅提供 main 索引，未提供 3.47.2 專屬版本；因此另對照本機該版 SDK 的 `ValueListenableBuilder`、排程取消、image eviction 與 sliver 實作。

- [Flutter 官方效能建議](https://docs.flutter.dev/perf/best-practices)：局部重建、重用 widget、避免 intrinsic layout。
- [Flutter 官方 sliver 文件](https://docs.flutter.dev/ui/layout/scrolling/slivers)：單一捲動區與惰性內容。
- [socket_io_client 3.1.6](https://pub.dev/packages/socket_io_client/versions/3.1.6)：另對照已安裝來源的 dispose／listener 清理；Context7 未索引對應 Dart 套件版本。

## 數值行為與驗證界限

有效樣本的演算法、模型、濾波、ROI、閾值、融合權重、校準、HRV、警報條件與資料 schema 均未修改。UI 只調整顯示缺值與視覺狀態，不回寫或改造量測值。心跳帶的安全啟用條件、停止與 busy 禁用、設定驗證及 payload 保持原有契約。

未執行真人攝影機／BLE 精度或長時效能壓測，也未宣稱推論加速。完整 Python 演算法 pytest 與 UTA-RLDD golden 不屬本次前端改動的驗證範圍；數值程式沒有改動。本機相機目前未被封裝程式偵測到，需另確認權限／硬體後才可進行監測驗收。
