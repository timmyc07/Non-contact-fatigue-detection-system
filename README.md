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

Optional demo:
```bash
python -m rppg.demo_rppg_live
```

## MediaPipe tuning and calibration

可調參數集中在 `config/mediapipe_tuning.json`：

- `face_landmarker`：Face Landmarker 的 detection / presence / tracking confidence。
- `rppg_roi`：ROI 基礎權重、姿態懲罰、遮擋門檻與最小權重。
- `quality`：rPPG / fatigue 統一品質分數的組合權重。
- `blendshape`：blendshape baseline 校準秒數、最小樣本、EMA 與眼眉嘴輔助閘門。

個人化 baseline 會自動儲存在 `config/mediapipe_calibration.json`，此檔案包含使用者/環境校準結果，不納入版本控制。

錄製後可用回放校準摘要工具檢查品質：

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
```

On Ubuntu, camera access uses V4L2 by default. If no camera appears, check device permissions:
```bash
ls -l /dev/video*
groups
```

Add your user to the `video` group if needed, then log out and back in:
```bash
sudo usermod -aG video "$USER"
```

## Project layout
- `rppg/`: rPPG-specific signal processing, MediaPipe ROI extraction, and the standalone live demo
- `gui/`: desktop GUI, fatigue analysis, recording, and web dashboard integration
- `config/mediapipe_tuning.json`: MediaPipe、ROI、quality score 與 blendshape 校準參數。
- `scripts/replay_calibration_summary.py`: 從錄製資料庫彙整 rPPG / fatigue 品質與 ROI 診斷。
- `docs/rppg_technical_report.md`: rPPG 技術、演算法、模型與系統運作說明；可用 `scripts/build_rppg_pdf.py` 產生 PDF。
- `docs/2026-05-21-mediapipe-landmark-expansion-log.md`: 本次新增 MediaPipe 部位與精準度提升的更新紀錄。

## Notes
- Recordings are saved under the `recordings/` folder.
- If playback video is needed in the web dashboard, make sure ffmpeg is available (imageio-ffmpeg is supported via requirements).
- `pygrabber` is a Windows-only optional dependency for DirectShow camera names. On Ubuntu/Linux, camera access uses V4L2 and the guarded `pygrabber` imports are not executed.
