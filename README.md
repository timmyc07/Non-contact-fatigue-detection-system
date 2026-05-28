# rppg_mediapipe_system_v2

rPPG + MediaPipe based fatigue/physiology monitoring with a desktop GUI and a web dashboard.

## Features
- Live camera preview with MediaPipe annotations
- rPPG heart-rate and HRV metrics
- Fatigue/behavior analysis overlays
- Recording to SQLite (.db) and video (.mp4)
- Web dashboard for live metrics and playback
- MediaPipe 姿態補償、ROI 動態權重、遮擋降權與品質診斷
- Blendshape 個人化 baseline 校準與跨 session 持久化

## Requirements
- Python 3.10+ recommended
- Windows and Ubuntu Linux supported
- Ubuntu desktop/runtime libraries for Qt, OpenCV, and V4L2 cameras

## Setup
Windows:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Ubuntu:
```bash
bash scripts/setup_ubuntu.sh
```

If the virtual environment already exists, reinstall/update Python dependencies with:
```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Run
```bash
python main.py
```

Ubuntu:
```bash
.venv/bin/python main.py
```

Ubuntu GUI 若出現 `Could not load the Qt platform plugin "xcb"`，先重新執行 setup 補齊 Qt xcb runtime：

```bash
bash scripts/setup_ubuntu.sh
```

若仍需追蹤 Qt plugin 載入路徑，可用：

```bash
QT_DEBUG_PLUGINS=1 QT_QPA_PLATFORM=xcb .venv/bin/python main.py
```

本專案 GUI 使用 PySide6。程式啟動時會在建立 `QApplication` 前把 Qt platform plugin 路徑固定回 PySide6，避免 OpenCV wheel 的 `cv2/qt/plugins` 覆蓋 PySide6 的 xcb plugin。

若 `setup_ubuntu.sh` 在非互動環境因 sudo 密碼失敗，請在自己的終端機直接執行：

```bash
sudo apt-get update
sudo apt-get install -y libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 v4l-utils
```

Optional demo:
```bash
python -m rppg.demo_rppg_live
```

## MediaPipe tuning and calibration

可調參數集中在 `config/mediapipe_tuning.json`：

- `face_landmarker`：Face Landmarker 的 detection / presence / tracking confidence。
- `rppg_roi`：ROI 基礎權重、姿態懲罰、遮擋門檻、最小權重、ROI polygon EMA 平滑、landmark jitter 與 ROI 面積穩定度門檻。
- `quality`：rPPG / fatigue 統一品質分數的組合權重。
- `blendshape`：blendshape baseline 校準秒數、最小樣本、EMA 與眼眉嘴輔助閘門。
- `active_profile` / `profiles`：可切換 `default`、`stable_indoor`、`low_light`、`high_motion` 等 MediaPipe 場景 profile。切換後需重啟 worker / 應用程式，Face Landmarker options 不做熱更新。

`canonical_roi_warp_enabled` 是實驗開關，預設關閉。啟用後會做保守的姿態導向 ROI 幾何正規化；因會改變 ROI 取樣分布，正式比較前應保持關閉。

個人化 baseline 會自動儲存在 `config/mediapipe_calibration.json`，此檔案包含使用者/環境校準結果，不納入版本控制。

錄製後可用回放校準摘要工具檢查品質：

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
```

若有對應錄影檔，可用 profile sweep 比較不同 MediaPipe profile 的偵測率、ROI 可用數、landmark jitter 與 ROI 面積穩定度：

```bash
.venv/bin/python scripts/mediapipe_profile_sweep.py recordings/video_YYYYMMDD_HHMMSS.mp4 --csv reports/mediapipe_profile_sweep.csv
```

調整 tuning 會影響新錄製資料與舊錄製資料的可比性；需要比較精準度或穩定度時，請使用同一段錄影回放 sweep。

On Ubuntu, camera access uses V4L2 by default. If no camera appears, check device permissions:
```bash
ls -l /dev/video*
groups
```

Add your user to the `video` group if needed, then log out and back in:
```bash
sudo usermod -aG video "$USER"
```

若相機黑屏或 GUI 沒有畫面，先用專案診斷腳本分辨硬體/權限與程式問題：

```bash
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2
```

可追加檢查：

```bash
v4l2-ctl --list-devices
v4l2-ctl --all -d /dev/video0
ls -l /dev/v4l/by-id/
fuser /dev/video0
.venv/bin/python -m rppg.demo_rppg_live --list-cameras --backend v4l2
```

診斷判讀：
- `/dev/video*` 不存在：偏向硬體未枚舉、驅動或容器/權限隔離問題。
- OpenCV 無法開啟相機：偏向權限、裝置被占用、後端不相容或硬體/驅動問題。
- OpenCV 可讀幀但亮度接近全黑：偏向鏡頭蓋、隱私快門、光線不足或虛擬相機無來源。
- 診斷腳本可讀到非黑畫面但 GUI 黑屏：偏向 GUI 顯示或相機後端協商問題，請在 GUI 中切換「自動 / V4L2 / FFMPEG」後端再測。

## Project layout
- `rppg/`: rPPG-specific signal processing, MediaPipe ROI extraction, and the standalone live demo
- `gui/`: desktop GUI, fatigue analysis, recording, and web dashboard integration
- `config/mediapipe_tuning.json`: MediaPipe、ROI、quality score 與 blendshape 校準參數。
- `scripts/replay_calibration_summary.py`: 從錄製資料庫彙整 rPPG / fatigue 品質與 ROI 診斷。
- `scripts/mediapipe_profile_sweep.py`: 以錄影檔重跑 MediaPipe profiles，輸出偵測與 ROI 穩定度比較。
- `docs/rppg_technical_report.md`: rPPG 技術、演算法、模型與系統運作說明；可用 `scripts/build_rppg_pdf.py` 產生 PDF。
- `docs/2026-05-21-mediapipe-landmark-expansion-log.md`: 本次新增 MediaPipe 部位與精準度提升的更新紀錄。

## Notes
- Recordings are saved under the `recordings/` folder.
- If playback video is needed in the web dashboard, make sure ffmpeg is available (imageio-ffmpeg is supported via requirements).
- `pygrabber` is a Windows-only optional dependency for DirectShow camera names. On Ubuntu/Linux, camera access uses V4L2 and the guarded `pygrabber` imports are not executed.
