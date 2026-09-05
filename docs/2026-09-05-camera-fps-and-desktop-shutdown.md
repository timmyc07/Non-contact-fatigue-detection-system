# 相機 FPS 與桌面關閉程序修正（2026-09-05）

## 問題

- 相機設定選擇 60 FPS，但監測值維持約 30 FPS。
- Flutter 主視窗右上角關閉按鈕只關閉視窗，Tauri、Python engine 或開發期 Flutter 程序可能繼續存活。

## 實機結果

測試裝置為 macOS 內建「MacBook Pro 相機」，OpenCV 5.0.0、AVFoundation backend。每組連續讀取 5 秒：

| 要求格式 | 驅動協商 | 實際收到影格 |
|---|---:|---:|
| 1920×1080 @ 30 | 30.0 FPS | 149 幀 / 5 秒 |
| 1920×1080 @ 60 | 30.0 FPS | 149 幀 / 5 秒 |
| 1280×720 @ 30 | 30.0 FPS | 149 幀 / 5 秒 |
| 1280×720 @ 60 | 30.0 FPS | 149 幀 / 5 秒 |
| 640×480 @ 60 | 30.0 FPS | 149 幀 / 5 秒 |

因此此裝置在目前 AVFoundation 格式下沒有接受 60 FPS。程式的相機擷取迴圈沒有把 60 限制成 30；Flutter/WebView 預覽傳輸另有 30 FPS 上限，用來控制 JPEG 與 IPC 負載，不代表分析輸入一定被同樣限速。

`scripts/diagnose_camera.py` 現在同時顯示：

- `driver_fps`：相機 backend 宣告的協商值。
- `measured_fps`：依第一幀至最後一幀的實際時間差計算值。

若要求值明顯高於穩定後的實測值，腳本與 engine log 都會提示檢查相機格式、backend、解碼、USB 頻寬與系統負載。

## 關閉流程

Flutter 標題列的關閉按鈕仍呼叫 Tauri `close_window`，但此 command 現在直接執行完整 desktop shutdown：

1. 對 Tauri 啟動且持有的 Python engine 傳送 `app.shutdown`。
2. 在背景清理執行緒中最多等待 6 秒讓 worker、相機與 Web server 正常釋放，不阻塞 Tauri 主事件迴圈。
3. 逾時才使用 process-tree kill fallback；Unix 以獨立 process group 收尾，Windows 以 `taskkill /T` 收掉 engine 後代程序。
4. 明確呼叫 `AppHandle::exit(0)` 結束 Tauri shell。

原生主視窗 `CloseRequested` 也攔截到同一條流程，避免 macOS「關閉最後一個視窗但應用程式仍存活」的預設語意造成殘留。Windows 仍沿用相同的 backend shutdown、等待與 kill fallback，未變更 Windows 相機 backend 或 child process 建立旗標。

## 數值行為影響

- 未修改 MediaPipe 模型、tuning、ROI、rPPG、疲勞分數、門檻、濾波或校準。
- 未提高或降低正式預覽的 30 FPS 傳輸上限。
- 新增內容只改善 FPS 可觀測性與桌面程序生命週期；分析數值輸出不變。
