# rppg_mediapipe_system_v2

rPPG + MediaPipe based fatigue/physiology monitoring with a desktop GUI and a web dashboard.

## Features
- Live camera preview with MediaPipe annotations
- rPPG heart-rate and HRV metrics
- Fatigue/behavior analysis overlays
- Recording to SQLite (.db) and video (.mp4)
- Web dashboard for live metrics and playback

## Requirements
- Python 3.10+ recommended
- Windows supported (camera backend)

## Setup
```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run
```bash
python main.py
```

Optional demo:
```bash
python -m rppg.demo_rppg_live
```

## Project layout
- `rppg/`: rPPG-specific signal processing, MediaPipe ROI extraction, and the standalone live demo
- `gui/`: desktop GUI, fatigue analysis, recording, and web dashboard integration

## Notes
- Recordings are saved under the `recordings/` folder.
- If playback video is needed in the web dashboard, make sure ffmpeg is available (imageio-ffmpeg is supported via requirements).
