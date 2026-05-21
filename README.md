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

## Notes
- Recordings are saved under the `recordings/` folder.
- If playback video is needed in the web dashboard, make sure ffmpeg is available (imageio-ffmpeg is supported via requirements).
