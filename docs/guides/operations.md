<div align="center">

# Operations & Validation Guide

### Run the workspace. Diagnose inputs. Reproduce results.

**Non-contact Fatigue Detection System**

[Product overview](../../README.md) &nbsp; | &nbsp; [Documentation index](../README.md) &nbsp; | &nbsp; [Camera diagnostics](#camera-diagnostics) &nbsp; | &nbsp; [Replay and validation](#replay-and-validation) &nbsp; | &nbsp; [Native packaging](#native-packaging-and-acceptance)

</div>

---

## Using this guide

This guide covers operation after installation: desktop integration, camera troubleshooting, tuning, BLE reference calibration, reproducible replay, performance measurements, and native-package acceptance. For first installation and platform readiness, start with the [product README](../../README.md).

Run commands from the **repository root** unless a section explicitly changes directories. Examples use the project virtual environment and Python 3.12. Replace `.venv/bin/python` with `.\.venv\Scripts\python` on Windows; PowerShell examples retain their Windows paths. Control names below are English descriptions; the current application may display Traditional Chinese labels.

| Your next task | Go to |
| :--- | :--- |
| Prepare assets or resolve a native-runtime mismatch | [Prepare the runtime](#prepare-the-runtime) |
| Launch the console or configure overlays | [Launch and desktop controls](#launch-and-desktop-controls) |
| Investigate a missing, black, slow, or delayed camera feed | [Camera diagnostics](#camera-diagnostics) |
| Compare tuning profiles or calibrate against a belt | [Tuning and calibration](#tuning-and-calibration) |
| Replay videos or assess numerical changes | [Replay and validation](#replay-and-validation) |
| Inspect API access and LAN behavior | [Diagnostics and network access](#diagnostics-and-network-access) |
| Measure the engine or check a camera pipeline | [Performance and hardware checks](#performance-and-hardware-checks) |
| Build and validate an installer | [Native packaging and acceptance](#native-packaging-and-acceptance) |
| Create diagrams or generate local reports | [Supporting tools and reports](#supporting-tools-and-reports) |

## Prepare the runtime

### Dependencies and local assets

Use `requirements.txt` for the core engine. Tests, packaging, and PDF generation additionally need `requirements-dev.txt`.

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.prepare_local_assets --download-model
.venv/bin/python -m scripts.runtime_preflight
```

The asset helper creates only missing icons and preserves local custom artwork. With `--download-model`, it obtains the missing model from a fixed official version, verifies SHA-256, and publishes the complete file atomically. Existing models are preserved.

Source analysis workers also retain a fixed-version download fallback for a missing model. Prepare all assets before attempting offline use. Images, icons, model files, and personal calibration remain local; a Git checkout alone does not supply every runtime or report asset.

<details>
<summary><strong>Resolve MediaPipe or OpenCV compatibility problems</strong></summary>

The project pins **MediaPipe 0.10.35** and the single **opencv-contrib-python 5.0.0.93** distribution. Do not install `opencv-python` alongside it: both distributions write the `cv2` namespace.

If the macOS engine disappears when monitoring starts, check the installed version and rerun preflight:

```bash
.venv/bin/python -c "import mediapipe; print(mediapipe.__version__)"
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.runtime_preflight
```

MediaPipe `1.0.1` can abort the current macOS Face Landmarker process inside the native `DrishtiMetalHelper` Metal path with `SIGABRT`. Python exception handling cannot catch this native termination.

If preflight reports conflicting OpenCV installations:

```bash
.venv/bin/python -m pip uninstall -y opencv-python
.venv/bin/python -m pip install --force-reinstall -r requirements.txt
```

</details>

## Launch and desktop controls

### Start the desktop console

Complete asset preparation and runtime checks first. Run `npm ci` before the first direct development launch; `npm run desktop` is the shared Tauri entry point. Platform scripts check the Python engine and resolve the desktop tooling.

| Platform | Launch behavior |
| :--- | :--- |
| Windows | The launcher sets the Flutter PATH, checks the Python engine, and starts Tauri. Native global hotkeys are implemented on Windows. |
| macOS | The launcher uses the macOS backend configuration. Grant camera access, and Bluetooth access when enabling a belt. Global hotkeys report `supported=false`; monitoring, recording, replay, overlay, and BLE use their existing runtime paths. |
| Linux | Use the Linux launcher and target-native dependencies; see the Linux packaging section for platform acceptance limits. |

<details>
<summary><strong>Windows launch</strong></summary>

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_desktop.ps1
```

</details>

<details>
<summary><strong>macOS launch</strong></summary>

```bash
bash scripts/start_desktop_macos.sh
```

</details>

For Linux, run `bash scripts/start_desktop_linux.sh`. To diagnose the engine without opening the desktop console:

```bash
.venv/bin/python main.py --engine
```

The visible product consists of the **Tauri v2 + Flutter Web console and overlay**. Python/MediaPipe/rPPG runs in the background. PySide6 supplies hidden Qt workers, threads, image/audio handling, and Windows hotkeys; engine mode does not construct a legacy Qt dashboard, menu, or overlay.

### Native actions, replay selection, and overlays

- **Folder and browser actions:** Flutter/Tauri dispatches native actions. Python returns validated action intents. If Flutter runs in a browser alone, external desktop actions show that the Tauri shell is required.
- **Replay folder selection:** Tauri provides the native picker. Canceling preserves the current selection. If the picker fails, the same section accepts a manually entered full folder path.
- **Overlay windows:** Enable camera and/or metrics overlays, then start the pipeline. Tauri creates independent transparent WebViews sharing the engine's current preview and metrics.
- **Overlay controls:** Locking enables native click-through; unlocking permits dragging. Position and size changes update runtime settings. Save settings to restore them on the next launch, including negative coordinates on multi-monitor setups.

### Runtime and platform boundaries

| Component | Responsibility |
| :--- | :--- |
| `gui/platforms/windows.py`, `gui/platforms/macos.py` | Platform policies, camera-backend preferences, and MediaPipe delegate decisions |
| `gui/camera_devices.py` | Shared camera enumeration and opening |
| `gui/platforms/registry.py` | Runtime, capability, and artifact contracts across five platforms |
| Shared model, tuning, rPPG, and fatigue code | Common analysis behavior across desktop platforms |

Launchers run `python -m scripts.runtime_preflight` before monitoring so incompatible native packages fail early. Windows, macOS, and Linux use the Python/Tauri desktop engine. Android and iOS remain `planned`: native inference runtimes, APK/IPA delivery, and device acceptance are unfinished. Desktop packages cannot be copied to a phone as a substitute.

## Camera diagnostics

### Choose the right diagnostic path

When the preview is black or absent, first distinguish input/permission failures from display or IPC failures with the standalone camera diagnostic.

<details>
<summary><strong>macOS: AVFoundation and permissions</strong></summary>

Camera enumeration prefers AVFoundation with OpenCV `CAP_ANY` fallback. If no camera is detected, use the console's camera-permission settings action to open **System Settings > Privacy & Security > Camera**. The app bundle declares camera and Bluetooth usage descriptions.

```bash
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend avfoundation
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend avfoundation --width 1280 --height 720 --fps 60 --seconds 5
```

</details>

<details>
<summary><strong>Windows: camera backend and increasing latency</strong></summary>

```powershell
.venv\Scripts\python scripts\diagnose_camera.py --camera 0 --backend auto
```

If input reaches 30 FPS but displayed latency grows over time, camera or analysis queues may be retaining old frames. The engine reduces OpenCV buffering, consumes the latest available frame, and throttles Flutter/Tauri preview events to limit IPC accumulation.

Automatic capture prefers `DSHOW`, then falls back to `MSMF`. Compare the available backends in the desktop camera settings when a specific camera remains unstable.

</details>

<details>
<summary><strong>Ubuntu/Linux: devices, permissions, formats, and Qt</strong></summary>

V4L2 is the default camera backend. If no camera appears, inspect devices and permissions:

```bash
ls -l /dev/video*
groups
```

If needed, add the user to the `video` group, then log out and back in:

```bash
sudo usermod -aG video "$USER"
```

Test capture:

```bash
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2
```

A USB UVC camera may support only about 10 FPS at `1280x720 YUYV`, while supporting 30 FPS at `1280x720 MJPG`. The Linux engine requests MJPG first. Confirm formats and negotiated input:

```bash
v4l2-ctl --list-formats-ext -d /dev/video0
.venv/bin/python scripts/diagnose_camera.py --camera 0 --backend v4l2 --width 1280 --height 720 --fps 30
```

Additional device checks:

```bash
v4l2-ctl --list-devices
v4l2-ctl --all -d /dev/video0
ls -l /dev/v4l/by-id/
fuser /dev/video0
.venv/bin/python -m rppg.demo_rppg_live --list-cameras --backend v4l2
```

If the engine reports `Could not load the Qt platform plugin "xcb"`, rerun setup to install the Qt xcb runtime:

```bash
bash scripts/setup_ubuntu.sh
```

For plugin-path diagnostics:

```bash
QT_DEBUG_PLUGINS=1 QT_QPA_PLATFORM=xcb .venv/bin/python main.py --engine
```

Python fixes the Qt plugin path to PySide6 **before** constructing `QApplication`, preventing an OpenCV wheel's `cv2/qt/plugins` path from replacing the PySide6 xcb plugin.

If setup fails because a non-interactive shell cannot supply the sudo password, install the required runtime packages in your own terminal:

```bash
sudo apt-get update
sudo apt-get install -y libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 v4l-utils
```

</details>

### Interpret the result

| Observation | Likely boundary to investigate |
| :--- | :--- |
| No `/dev/video*` devices | Hardware enumeration, driver support, or container/permission isolation |
| OpenCV cannot open the camera | Permissions, another process using the device, backend compatibility, or hardware/driver behavior |
| Frames arrive but are almost black | Lens cap, privacy shutter, insufficient lighting, or a virtual camera with no source |
| Repeated `Camera index out of range` or `VIDIOC_QBUF` messages | Scanning missing indices or treating metadata nodes as cameras; Linux scanning is limited to existing devices with Video Capture capability |
| Diagnostic frames are usable but Flutter remains black | IPC/WebView presentation or capture negotiation; retest with an available platform backend in camera settings |
| A 60 FPS request yields about 30 FPS | The camera/resolution/backend may not accept the requested rate; also check decode cost, USB bandwidth, and system load |

`driver_fps` is the rate declared by the camera backend. `measured_fps` is calculated from received-frame timing. The preview transport remains capped at **30 FPS** to limit WebView JPEG/IPC load.

Production desktop camera settings use **30 FPS**. The 60 FPS option is diagnostic-only, for checking hardware negotiation. Keeping production capture fixed makes analysis comparisons consistent without changing the model or algorithm.

To compare backend input cost:

```bash
.venv/bin/python -m scripts.camera_backend_benchmark --backends ffmpeg auto avfoundation --seconds 5
```

On macOS, the `ffmpeg` compatibility setting prefers AVFoundation directly. The Windows DSHOW-to-MSMF order remains unchanged.

**Mirror correction:** The horizontal-flip control in camera settings applies to preview, recording, and analysis input together.

For the independent rPPG diagnostic demo:

```bash
.venv/bin/python -m rppg.demo_rppg_live
```

`pygrabber` supplies DirectShow device names on Windows only; platform-specific imports are guarded. macOS uses AVFoundation and Linux uses V4L2. Video transcoding is supported through `imageio-ffmpeg`; API playback and actual decoding still require validation in the packaged environment.

## Tuning and calibration

### MediaPipe profiles and individual baselines

The default `active_profile` is `stable_indoor`. It increases Face Landmarker tracking confidence and smooths ROI polygons to reduce indoor webcam landmark/ROI jitter. For dim light or larger head motion, compare `low_light` or `high_motion` against the same recorded video.

Parameters are centralized in `config/mediapipe_tuning.json`:

| Section | Parameters and purpose |
| :--- | :--- |
| `face_landmarker` | Detection, presence, and tracking confidence |
| `rppg_roi` | Base weights, pose penalties, obstruction thresholds, minimum weight, polygon EMA smoothing, landmark jitter, and ROI area stability |
| `quality` | Weights composing the unified rPPG/fatigue quality scores |
| `blendshape` | Baseline duration, minimum samples, EMA, and eye/brow/mouth support gates |
| `active_profile` / `profiles` | `default`, `stable_indoor`, `low_light`, and `high_motion` |

Profile changes require restarting the worker or application; Face Landmarker options are not updated live. `canonical_roi_warp_enabled` is experimental and **off by default**. Enabling its conservative pose-guided ROI normalization changes the sampling distribution; keep it off before formal comparisons unless that change is the experiment.

Personalized baseline results are saved automatically to `config/mediapipe_calibration.json`. This user/environment-specific file is excluded from Git.

### rPPG processing and calibration versions

By default, valid skin ROIs are mixed with equal weight, passed through the color-projection implementation named `pos_pulse`, band-pass filtering, and Welch peak estimation, then processed with spectral peak interpolation, smoothing, and jump confirmation. The function Z-scores each RGB channel before projection; its name does not establish a complete reproduction of the original POS paper. The [product README](../../README.md#technical-design) gives the implemented formula.

Displaying BPM and admitting physiology into fatigue fusion use different quality conditions. A visible BPM value does not establish that the signal passed the fusion gate.

BPM correction uses `scale*bpm+offset`. Routine monitoring does not require wearing a belt. The engine reads the active version in `config/rppg_calibration/manifest.json` and applies the correction. Calibration versions remain local in `config/rppg_calibration/`.

The current reference workflow is background BLE belt calibration. Once confidence is sufficient, stopping calibration saves a new active version. The former phone/watch HTTP `:8080` manual-calibration dialog and watch mode have been removed.

Review recorded calibration data:

```bash
.venv/bin/python scripts/replay_calibration_summary.py recordings/metrics_YYYYMMDD_HHMMSS.db
```

When the corresponding video exists, compare MediaPipe profiles using detection rate, valid ROI count, landmark jitter, and ROI area stability:

```bash
.venv/bin/python scripts/mediapipe_profile_sweep.py recordings/video_YYYYMMDD_HHMMSS.mp4 --csv reports/mediapipe_profile_sweep.csv
```

Tuning changes affect the comparability of earlier and later recordings. Use a sweep over the **same video** when comparing accuracy or stability.

### BLE heart-rate reference workflow

A compatible Heart Rate Service belt, such as the Scosche Rhythm+ 2.0, provides a reference for rPPG correction. **Belt BPM never enters the fatigue fusion score directly.** It is used for calibration and confidence assessment.

1. Wear the belt.
2. Enable rPPG through the stress/HRV heart-rate-estimation control.
3. Enable background heart-rate-belt calibration.
4. Start monitoring and follow the scan, connection, convergence, and converged states.

rPPG must be active before comparisons begin. The console shows connection state, BPM, RR count, battery, contact state, current correction, and convergence/divergence. A connected belt with no valid heart rate for more than **5 seconds** produces a no-heart-rate-data warning; check placement and contact.

<details>
<summary><strong>BLE protocol, device selection, and calibration safeguards</strong></summary>

| Detail | Behavior |
| :--- | :--- |
| Heart Rate Service | `0x180D` |
| Measurement notifications | `0x2A37`, parsed for BPM and RR-Interval at 1/1024-second resolution |
| Additional reads | Best-effort battery `0x2A19` and body sensor location `0x2A38` |
| Device selection | Prefer names starting with `R+`; otherwise choose the strongest device advertising Heart Rate Service |
| Reconnection | Rescan and reconnect automatically after disconnection |

See the [device GATT profile](../technical/heart_rate_belt_bluetooth_gatt_profile.md) for the measured Scosche Rhythm+ 2.0 / R+2.0 2248 characteristics.

`OnlineBpmCalibrator` in `rppg/adaptive_calibration.py` uses the median residual between belt BPM and **raw rPPG BPM** as the target for a slow, low-gain EMA offset update. The underlying `rppg/calibration.py` model remains `scale*bpm+offset`; the online flow updates only the offset.

Samples must pass rPPG SQI, quality, warm-up, and ROI gates, plus belt contact and freshness checks. The offset has an absolute limit. Comparing raw BPM avoids feeding the correction back into its own reference.

A session starts from the current active offset. When calibration is disabled, the pipeline stops, or the application closes, a sufficiently confident result is saved as a new adaptive-calibration version and activated for the next session.

On the measured Scosche Rhythm+ 2.0, a triple press enables HRV mode: `2A37` then includes measured RR-Intervals with `flags=0x16`. Normal heart-rate mode sends BPM only with `flags=0x06`. BPM calibration does not depend on HRV mode.

</details>

<details>
<summary><strong>Optional device configuration and engine-independent BLE diagnostics</strong></summary>

The engine rereads the machine-specific, ignored `config/hr_belt.json` whenever it starts the belt runtime. Example:

```json
{
  "name_prefix": "R+",
  "address": "C1:3B:74:B8:F7:40",
  "scan_timeout_sec": 6,
  "reconnect_delay_sec": 3
}
```

Replace the example address with the intended device. An explicit `address` matches directly and bypasses name matching, useful when several belts are nearby. Every field is optional; omitted fields use defaults.

The standalone monitor shares the engine's BLE connection component:

```powershell
.venv\Scripts\python -m scripts.hr_belt_monitor                     # Scan the default R+ name prefix
.venv\Scripts\python -m scripts.hr_belt_monitor --address C1:3B:74:B8:F7:40 --duration 60
.venv\Scripts\python -m scripts.hr_belt_monitor --use-config        # Read config/hr_belt.json
```

It prints each BPM/RR notification, scan/connection/reconnection transitions, battery, and contact warnings. If it receives no heart-rate notifications, it exits with a nonzero status.

</details>

## Replay and validation

### Treat a video as an offline camera

Replay feeds video frames into the same core fatigue engine without modifying live camera workers. Timestamps are deterministic, derived from video FPS. Fatigue calibration starts at the first valid face frame; roughly the first **5 seconds** are `CALIBRATING`, followed by statistics for `OK / LOW_VIGILANCE / DROWSY / CRITICAL`.

UTA-RLDD is a dataset preset for threshold calibration and reproducibility, rather than the purpose of the replay module.

<details>
<summary><strong>Replay any video or folder</strong></summary>

Use `scripts.video_replay` with a file or arbitrary video folder. No UTA-RLDD structure or `0/5/10` filename labels are required; unrecognized labels appear as `Unlabeled`.

Accepted extensions: `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, and `.webm`. Output defaults to `recordings/replay_runs/<timestamp>/`. Without labels, the validation-trend report is skipped. A path containing no usable video produces an actionable error rather than an empty report.

```powershell
.\.venv\Scripts\python.exe -m scripts.video_replay "C:\path\to\clip.mp4" --max-frames 300
.\.venv\Scripts\python.exe -m scripts.video_replay "C:\path\to\videos_folder" --jobs 4
```

</details>

<details>
<summary><strong>Replay the UTA-RLDD dataset</strong></summary>

The [official dataset](https://sites.google.com/view/utarldd/home) defines `0=Alert`, `5=Low Vigilant`, and `10=Drowsy`. This preset discovers subject/label folders and produces additional validation-trend reports using those values as ordinal labels.

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "$env:USERPROFILE\Downloads\Fold1_part1" --max-videos 1 --max-frames 300
```

Filter subjects/labels, choose output, request annotation, or select parallel processing:

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "$env:USERPROFILE\Downloads\Fold1_part1" --subject '01,02' --label '0,5,10'
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "$env:USERPROFILE\Downloads\Fold1_part1" --output-dir recordings\utarldd_runs\test --write-annotated-video
.\.venv\Scripts\python.exe -m scripts.utarldd_replay "$env:USERPROFILE\Downloads\Fold1_part1" --jobs 4
```

**PowerShell:** Quote comma-separated subjects, such as `'01,02'`. Otherwise PowerShell can interpret them as an integer array and remove the leading zeroes needed to match directories.

</details>

### Output and parallel execution

UTA-RLDD output defaults to `recordings/utarldd_runs/<timestamp>/`:

| Artifact | Contents |
| :--- | :--- |
| `metrics_utarldd_<subject>_<label>_<timestamp>.db` | Frame-level metrics for each video |
| `utarldd_summary_<timestamp>.csv` | Readable summary |
| `utarldd_validation_report_<timestamp>.csv` | Validation trends |
| `utarldd_summary_full_<timestamp>.csv` | Complete summary fields |
| `utarldd_visual_report_<timestamp>.html` | Visual report |
| `utarldd_manifest_<timestamp>.json` | Batch manifest |

The readable summary includes valid-decision frame counts, rPPG availability, low-quality ratios, PERCLOS/blink/squint/fixation/yawn activation counts, label-aligned interpretation, principal decision evidence, suggested corrections, and optimization flags. The validation report compares label-level averages and whether each subject's three videos show an increasing fatigue trend.

Annotated video is written only with `--write-annotated-video`. Existing summary CSV files can produce HTML without replaying the videos again:

```bash
.venv/bin/python scripts/utarldd_csv_report.py recordings/utarldd_runs/<timestamp>/utarldd_summary_<timestamp>.csv
```

| Execution path | Behavior |
| :--- | :--- |
| CLI `--jobs N` | Multiple videos run in separate processes; start with `--jobs 2` or `--jobs 4` and adjust for CPU, memory, and temperature |
| Each individual video | Frames remain sequential, preserving MediaPipe VIDEO-mode timestamps and tracking assumptions |
| Desktop batch start | Single-worker processing; supports annotated video output |
| Desktop parallel validation | Uses the configured job count, capped at 4; disables annotation and preview to avoid process/video-writer contention |

The desktop replay section supports folder selection, batch start/stop, job count, annotation, and progress by subject/label/video, completion count, parallel state, and summary path. If a child process terminates unexpectedly, the batch stops dispatching new work, marks unfinished videos as `failed`, and preserves CSV/manifest outputs.

These controls change orchestration and presentation, not per-frame analysis values in SQLite, CSV, or the manifest. UTA-RLDD labels describe entire videos, **not frame-level ground truth**, and do not replace tests with real UAV operators.

### Numerical regression

`scripts/utarldd_golden.py` checks a fixed subset of videos. `tests/golden/utarldd_golden_config.json` defines subjects, labels, frame counts, fields, and tolerances; `tests/golden/utarldd_golden_baseline.json` stores the tracked baseline.

Run `check` after changes to rPPG, fatigue logic, filtering, ROIs, or scoring:

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_golden check "$env:USERPROFILE\Downloads\UTA_test\Fold1_part1"    # 0=pass, 1=numerical drift, 2=execution failure
.\.venv\Scripts\python.exe -m scripts.utarldd_golden create "$env:USERPROFILE\Downloads\UTA_test\Fold1_part1" --force   # Rebuild the baseline only when drift is expected
```

Both configuration and baseline are versioned. If drift is intended, explain the changed fields in the commit description **before** rebuilding with `create --force`.

### Label association and historical evidence

Golden checks answer whether outputs changed. `scripts/utarldd_accuracy.py` examines their association with labels: score monotonicity across `0/5/10`, Drowsy-vs-Alert AUC, and score-range collapse. Use it after changes to fatigue decisions, thresholds, or weights to assess regression in the evaluated dataset.

```powershell
.\.venv\Scripts\python.exe -m scripts.utarldd_accuracy "$env:USERPROFILE\Downloads\UTA_test\Fold1_part1" --subjects '01,02,03,04,05,06' --max-frames 1200 --jobs 4 --out report.json
```

| Historical record | What was measured | Interpretation |
| :--- | :--- | :--- |
| [2026-07-03 calibration](../history/2026-07-03-fatigue-accuracy-calibration.md) | Reweighted PERCLOS/scoring thresholds changed the reported Drowsy-vs-Alert AUC from 0.53 to 0.75 on the calibration set and 0.69 on the holdout set | Results apply to that data, configuration, and version; they are not current-version accuracy claims |
| [2026-06-07 replay analysis](../history/2026-06-07-utarldd-analysis.md) | 36 videos, 100% processing completion, about 99.93% average face detection; fused scores did not consistently rise across `0 -> 5 -> 10` | Processing and face detection success do not imply near-100% three-class fatigue accuracy |

If still present locally, `recordings/utarldd_runs/20260607_122601/utarldd_summary_20260607_122601.csv` can be converted to `utarldd_visual_report_20260607_122601.html` for historical limitations analysis and later threshold work. Historical results do not substitute for testing the current version.

## Diagnostics and network access

The engine provides **diagnostic JSON and data APIs**, while the visible interface is Tauri + Flutter. Visiting `/` returns service information; `/api/metrics` and Socket.IO expose current measurements. There is no legacy Flask HTML dashboard.

| Access boundary | Contract |
| :--- | :--- |
| Default endpoint | Windows/Linux: `127.0.0.1:5000`; macOS: `127.0.0.1:5055` |
| Console action | The diagnostic-service settings button opens the service JSON; settings also control LAN access |
| LAN authentication | Use the complete displayed URL, including `?token=`; the root and APIs require the shared token for remote requests, or accept `X-Dashboard-Token` |
| Local authentication | Loopback requests do not require the LAN token |
| Socket.IO | Origins are restricted to local/LAN sources |
| Desktop control and File Browser | Desktop control APIs and `/api/fb/*` remain local-only |

LAN uses **unencrypted HTTP**. Images, metrics, and tokens may be intercepted on the network; enable it only on a trusted network. Do not infer a port or omit the token from the displayed URL.

Core monitoring requires no API key or `.env`. Operational preferences belong in Flutter settings; use the save-settings action to persist supported preferences.

## Performance and hardware checks

### Engine and synthetic-preview benchmark

These commands do not require a camera and produce JSON:

```powershell
.\.venv\Scripts\python.exe -m scripts.desktop_engine_benchmark
.\.venv\Scripts\python.exe -m scripts.desktop_engine_benchmark --port 5001 --samples 10
.\.venv\Scripts\python.exe -m scripts.desktop_engine_benchmark --synthetic-only --samples 10
```

The default benchmark measures engine startup-to-control-API readiness, RSS at readiness, read-only `state.get` latency, and fixed synthetic-image JPEG payload size, encoding latency, and Socket.IO server dispatch rate.

The preview figures are **in-process microbenchmarks**. They exclude actual networking, Tauri WebView decoding, Flutter rendering, and physical camera capture. Use the same machine, Python/package versions, and `--samples` for before/after comparisons. Ensure the target port is not occupied; engine defaults are 5000 on Windows/Linux and 5055 on macOS.

### Camera pipeline smoke

These commands exercise the desktop API, engine, and worker lifecycle without saving settings or recording:

```powershell
.\.venv\Scripts\python.exe -m scripts.desktop_hardware_smoke --camera-index 0 --analysis-mode combined
.\.venv\Scripts\python.exe -m scripts.desktop_hardware_smoke --analysis-mode raw --output docs\benchmarks\desktop-hardware-smoke.json
```

Supported modes are `raw`, `fatigue`, `rppg`, and `combined`. The script starts a source engine, selects a camera, checks FPS/resolution and frame origin, then stops the pipeline and engine. It does **not** assess rPPG or fatigue accuracy. Use `scripts.hr_belt_monitor` separately to verify actual BLE heart-rate notifications.

## Native packaging and acceptance

PyInstaller builds the native engine first, then Tauri includes the engine, MediaPipe model, and immutable tuning resources in the application. Installed builds keep settings, recordings, and calibration in the user data directory; they do not require a repository checkout or `.venv`.

| Runtime | Engine selection |
| :--- | :--- |
| Development/debug | Checkout source; `NCFD_ENGINE_ROOT` and `NCFD_ENGINE_PYTHON` can select the development engine |
| Release | Bundled engine only; development overrides do not silently fall back to a checkout |

Build the virtual environment, sidecar, Flutter, and Rust artifacts on the target OS. PyInstaller is not a cross-platform compiler.

<details>
<summary><strong>Windows: NSIS installer and acceptance</strong></summary>

Build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

The engine is prepared at `dist/ncfd-engine/`; installer output is under `src-tauri/target/release/bundle/nsis/`.

Full installed-application smoke covers isolated installation, API v2, engine shutdown, normal Tauri-window closure, and silent uninstall:

```powershell
.\.venv\Scripts\python.exe -m scripts.installed_desktop_smoke
```

</details>

<details>
<summary><strong>macOS: Apple Silicon app/DMG and acceptance</strong></summary>

Build:

```bash
bash scripts/build_desktop_macos.sh
```

Outputs are `src-tauri/target/release/bundle/macos/` and `src-tauri/target/release/bundle/dmg/`. Current packages target Apple Silicon arm64. Local builds use ad-hoc signing; external distribution requires Apple Developer ID signing, codesign, and notarization.

Check the bundled API and engine shutdown:

```bash
.venv/bin/python -m scripts.installed_desktop_smoke_macos
```

</details>

<details>
<summary><strong>Ubuntu/Linux: AppImage/deb and acceptance</strong></summary>

Development launch and native packaging:

```bash
bash scripts/start_desktop_linux.sh
bash scripts/build_desktop_linux.sh
```

Outputs are `src-tauri/target/release/bundle/appimage/` and `src-tauri/target/release/bundle/deb/`. Build on the target Linux distribution; copying macOS/Windows sidecars or Flutter/Rust artifacts is not an equivalent validation.

Run the AppImage smoke on Linux:

```bash
.venv/bin/python -m scripts.installed_desktop_smoke_linux
```

Set `APPIMAGE_EXTRACT_AND_RUN=1` on runners without FUSE. AppImage portability still depends on target WebKitGTK/system-library compatibility; deb declares GTK/WebKitGTK runtime dependencies.

Record native-build, installed-startup, camera, and data-directory results on the target Ubuntu/Linux machine. A macOS build does not establish Linux acceptance.

</details>

## Supporting tools and reports

### Canva flowchart application

The optional `tools/canva-flowchart/` app inserts a locally selected system flowchart into Canva. Diagram labels describe system functions: image input, shared face inference, behavioral analysis, rPPG, quality gates, fusion, alerts, recording, diagnostics, and replay, rather than source filenames.

From the repository root:

```powershell
cd tools/canva-flowchart
npm install
npm start
```

App ID: `AAHAACArWJM`. Check its configuration in the [Canva Developer Portal](https://www.canva.com/developers/app/AAHAACArWJM).

Select a local **PNG or JPEG**, inspect the preview, then insert it into the current Canva design. No fixed filename or source-code image import is required. Selection and preview are local; insertion uploads the image to Canva, so choose material suitable for sharing.

Run tool checks from `tools/canva-flowchart/`:

```powershell
npm run lint
npm run lint:types
npm test -- --runInBand
npm run build
canva apps config status --lite
canva apps doctor --ci
```

If the existing startup test treats the stale Browserslist warning on stderr as a failure, the [REA report](../reviews/2026-10-22-rea-report.md) records the verified `BROWSERSLIST_IGNORE_OLD_DATA=true` test/build invocation. This suppresses the data-age warning without changing dependencies.

Return to the repository root before running the report commands below.

### Generate local technical reports

Markdown sources live in `docs/technical/`; the [documentation index](../README.md) organizes current guides and historical evidence. Generated PDFs are local artifacts in `docs/exports/` and are excluded from Git.

```bash
# Original rPPG technical report
.venv/bin/python scripts/build_rppg_pdf.py

# System, rPPG, behavior, application, optimization, and replay reports
.venv/bin/python scripts/build_technical_report_pdfs.py

# Formal practical-project report
.venv/bin/python scripts/build_practical_project_report_pdf.py
```

The formal report generator reads existing replay CSVs and local artwork. Without the corresponding data, its output cannot be presented as a new experiment. Confirm Chinese-font availability on the target machine because the technical-report sources remain in Traditional Chinese.

The [poster design source](../technical/rppg_fatigue_monitoring_poster_design.md) describes the poster workflow; its previews also remain local.

## Local data reference

Paths below are relative to the checkout in development. Installed builds resolve writable files under the application user data directory.

| Path | Role |
| :--- | :--- |
| `config/mediapipe_tuning.json` | Shared, versioned development tuning |
| `config/mediapipe_calibration.json` | Local user/environment baseline |
| `config/personal_profile/` | Local individual awake-baseline profiles |
| `config/rppg_calibration/` | Local calibration versions and active manifest |
| `config/hr_belt.json` | Optional machine-specific BLE device selection |
| `recordings/` | Recorded metrics/video and replay CSV/HTML/manifest outputs |
| `docs/images/` | Local artwork and source diagrams |
| `docs/exports/` | Local PDFs, presentations, and document exports |

Images, recordings, databases, models, personal calibration, `.env`, `AGENTS.md`, and `CLAUDE.md` remain outside version control. Ignore rules do not remove previous Git history. Share diagnostic outputs only after checking faces, identifiers, tokens, and device data.
