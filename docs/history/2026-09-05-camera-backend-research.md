# 相機 backend 與每秒資訊量研究基線

## 網路資料

- FFmpeg 官方裝置文件：<https://ffmpeg.org/ffmpeg-devices.html>。文件將 `avfoundation` 定義為 macOS stream-grabbing framework，將 `dshow` 定義為 Windows DirectShow input device；兩者都是原生裝置輸入路徑，不代表 OpenCV 的 `CAP_FFMPEG` 對整數 camera index 一定可用。
- OpenCV Video I/O backend 文件：<https://docs.opencv.org/4.x/d0/da7/videoio_overview.html>。`VideoCapture` 會透過 backend、作業系統與驅動協商屬性；`CAP_PROP_FPS` 是 backend 回報值，實際 delivery rate 仍應以影格時間量測。
- Apple AVFoundation：<https://developer.apple.com/documentation/avfoundation>。AVFoundation 是 Apple 的影音擷取框架，macOS 內建鏡頭應優先使用此原生路徑。
- Microsoft Media Foundation architecture：<https://learn.microsoft.com/en-us/windows/win32/medfound/media-foundation-architecture>。Windows camera pipeline 由 Media Foundation 元件與 media source／transform／sink 組成；專案仍保留 MSMF 作 Windows fallback，並維持既有 DSHOW 優先策略。
- MediaPipe Face Landmarker Python guide：<https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python>。Face Landmarker 的 VIDEO／LIVE_STREAM 模式依時間戳處理影像；固定 30 FPS 可讓時間戳、追蹤與分析負載在跨平台比較時一致。

## 本機驗證

在 macOS 內建「MacBook Pro 相機」、OpenCV 5.0.0、1280×720、要求 30 FPS、連續 5 秒量測：

| 邏輯設定 | 實際 OpenCV backend | 幀數 | 實測 FPS | CPU（讀取程序） |
|---|---:|---:|---:|---:|
| `ffmpeg`（相容設定） | `1200` AVFoundation | 150 | 29.90 | 17.71% |
| `avfoundation` | `1200` AVFoundation | 150 | 29.90 | 17.44% |
| `auto` | `1200` AVFoundation | 150 | 29.91 | 17.59% |

連續重開測試（`ffmpeg` 相容設定、2 秒 × 3 次）皆成功，實測為 29.32、29.81、29.51 FPS。`CAP_PROP_FPS` 是協商回報值，曾有一次回報 15 FPS 但實測仍為 29.96 FPS；因此診斷與效能比較以影格時間計算的 `measured_fps` 為準，不能只看 `reported_fps`。

`ffmpeg` 是為了相容既有設定名稱保留的 logical backend；現在 macOS 會直接優先 AVFoundation，避免先嘗試不適合整數 camera index 的 CAP_FFMPEG。Windows 的原有 DSHOW → MSMF → CAP_ANY 與 FFmpeg fallback 順序不變。

## 每秒資訊量與精準度

目前最安全的提升方式是先固定 30 FPS、維持每幀 timestamp，並量測「相機實收幀率、analysis worker 處理時間、丟幀率、Face Landmarker face-present rate、rPPG SQI」。不能只用預覽 FPS 推論精準度；預覽本來就有 30 FPS 傳輸上限。

精準度研究應採受控 replay／真人資料集，逐項比較：原始輸入、光照與姿態分層、臉部追蹤成功率、ROI 有效比例、rPPG SQI、疲勞標籤的 sensitivity／specificity／AUROC，以及每秒 CPU／丟幀率。未有配對標註資料前，不直接調整門檻、ROI 權重或模型參數，避免看似提升而破壞既有數值契約。

可用 benchmark：

```bash
.venv/bin/python -m scripts.camera_backend_benchmark --backends ffmpeg auto avfoundation --seconds 5
```

輸出中的 `measured_fps`、`interval_ms_p95`、`cpu_percent` 與 `backend_id` 可作為後續平台比較基線。
另外，`megapixels_per_second` 量化固定 30 FPS 下每秒送入管線的畫素量，`read_success_ratio`／`read_failures` 用來辨識驅動或 USB 造成的丟幀；這些指標只觀測輸入，不改分析模型或門檻。
