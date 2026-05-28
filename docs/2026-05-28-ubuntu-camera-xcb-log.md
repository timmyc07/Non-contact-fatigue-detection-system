# 2026-05-28 Ubuntu Qt xcb 與相機黑屏診斷更新

## 背景

Ubuntu 執行 `python main.py` 可能出現 Qt `xcb` platform plugin 載入失敗，錯誤路徑指向 `.venv/.../cv2/qt/plugins`。另有使用者回報相機黑屏，但原本 GUI 無法明確分辨是硬體、權限、相機後端或程式顯示問題。

## 更新內容

- `main.py` 在建立 `QApplication` 前將 `QT_QPA_PLATFORM_PLUGIN_PATH` 指向 PySide6 的 `platforms` 目錄，避免 OpenCV wheel 改寫 Qt plugin 搜尋路徑。
- `scripts/setup_ubuntu.sh` 補齊 Qt xcb 常見 runtime 套件與 `v4l-utils`，供 Ubuntu 桌面與相機診斷使用。
- `gui/camera_devices.py` 找不到相機時不再回傳可選的假裝置，避免 GUI 顯示「偵測 1 台」但實際無硬體。
- `gui/camera_stream_worker.py` 增加黑幀亮度診斷與連續讀取失敗偵測，只輸出診斷與錯誤，不改 rPPG 或疲勞演算法。
- `scripts/diagnose_camera.py` 新增 Ubuntu 相機診斷入口，可檢查 `/dev/video*`、V4L2、權限、占用、OpenCV 讀幀與黑畫面亮度統計。
- `main.py` 啟動前會檢查 `libxcb-cursor0`；若系統缺套件，會先輸出 Ubuntu apt 安裝指令並結束，避免 Qt 在建立 `QApplication` 時 core dump。
- Linux 相機設定會優先要求 MJPG，再協商解析度與 FPS，避免部分 UVC webcam 在 720p YUYV 模式只剩 10 FPS。

## 操作建議

```bash
bash scripts/setup_ubuntu.sh
.venv/bin/python main.py
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2 --width 1280 --height 720 --fps 30
```

若診斷腳本可讀到非黑畫面但 GUI 仍黑屏，優先在 GUI 切換相機後端並回報診斷輸出。若診斷腳本也無法開啟相機或沒有 `/dev/video*`，優先處理硬體枚舉、video 群組權限或裝置占用。
若 GUI 顯示約 10 FPS，先用 `v4l2-ctl --list-formats-ext -d /dev/video0` 檢查該解析度的 YUYV/MJPG 支援幀率，再用診斷腳本確認 OpenCV 實際協商格式。
