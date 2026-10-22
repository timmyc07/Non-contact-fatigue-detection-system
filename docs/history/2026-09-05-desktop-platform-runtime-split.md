# Windows / macOS desktop runtime 分層與 MediaPipe 崩潰修復

## 問題

macOS 桌面面板可正常啟動，但按下「開始監測」後 Python engine 直接結束，畫面尚未送到
Flutter。macOS crash report 顯示 `SIGABRT` 位於 MediaPipe
`DrishtiMetalHelper` / `TensorsToDetectionsCalculator` 初始化。當時環境因
`requirements.txt` 使用無上限的 `mediapipe>=0.10.14`，安裝到 `mediapipe 1.0.1`。

即使透過 `BaseOptions.Delegate.CPU` 明確指定 CPU，`1.0.1` 仍會建立該 Metal helper 並在
原生層 abort，因此不能靠 Python `try/except` 修復。

## 修復

- Windows 與 macOS 共用固定的 `mediapipe 0.10.35`，避免套件升級改變推論 runtime。
- 只安裝 `opencv-contrib-python 5.0.0.93`，避免它與 `opencv-python` 覆寫同一個 `cv2`
  namespace；preflight 會拒絕重複 distribution。
- 啟動腳本新增 `scripts.runtime_preflight`，先檢查核心套件、MediaPipe 版本與平台相機後端。
- preflight 會在隔離子程序實際建立並關閉 Face Landmarker；即使 native runtime abort，
  也只會終止檢查子程序，不會帶走桌面 engine。
- 所有 Face Landmarker 入口在讀取既有模型前先驗證 runtime；即使繞過啟動腳本，也會以
  可讀錯誤停止該 worker，而不是進入已知會 abort 的版本。
- 三種 live analysis worker 對未預期初始化例外統一 fail-closed，必定送出 `failed` 與
  `finished`，避免 QThread 永久存活。
- `gui/platforms/windows.py` 保存既有 DSHOW → MSMF → ANY 順序與既有 delegate 行為。
- `gui/platforms/macos.py` 保存 AVFoundation → ANY 順序，並對已驗證的 0.10.35 明確指定
  CPU delegate。實測 log 仍為 XNNPACK CPU，沒有改變模型或數值參數。
- Ubuntu 支援保留於 `gui/platforms/linux.py`，不改 V4L2 行為。
- Windows 正式支援目標為 x64；MediaPipe 雖提供 Windows ARM64 wheel，但其 OpenCV 依賴鏈
  目前沒有對應的 PyPI ARM64 wheel。
- `npm run desktop:build` 會先經跨平台 Node wrapper 強制重建 PyInstaller sidecar，並對
  封裝後 executable 再執行 dependency 與 Face Landmarker 初始化檢查，避免沿用舊 `dist/`。

## 共用與平台專用邊界

這次先建立平台 policy 層，集中相機 API 偏好順序、probe 上限與 MediaPipe delegate；既有
相機列舉與開啟機制仍由 `gui/camera_devices.py` 共用，而不是複製兩套完整 camera stack。
以下模型與數值邏輯仍共用：

- `models/face_landmarker.task`
- `config/mediapipe_tuning.json`
- `gui/fatigue_engine.py`
- `gui/fatigue_scorer.py`
- `rppg/` 的 ROI、濾波、BPM、HRV 與校準數值路徑

## 數值行為影響聲明

沒有修改模型、confidence、ROI、濾波、疲勞門檻、融合權重或校準參數。Windows 保留原有
MediaPipe delegate 建構方式；macOS 從無法啟動的 1.0.1 回復到 0.10.35 的 XNNPACK CPU
路徑。可產生輸出的既有 0.10.35 環境，其演算法輸入、參數與輸出計算路徑不變。
