<div align="center">

# Non-contact Fatigue Detection System

### Camera-based vigilance monitoring for remote operators.

Observe behavior. Assess signal quality. Review the evidence.

**Live monitoring &nbsp; / &nbsp; Physiological insights &nbsp; / &nbsp; Reproducible replay**

[Explore capabilities](#capabilities) &nbsp; | &nbsp; [Get started](#get-started) &nbsp; | &nbsp; [Technical design](#technical-design) &nbsp; | &nbsp; [Documentation](#documentation)

</div>

---

## Operator awareness, in one workspace

Built for sustained UAV operation and monitoring, this desktop system combines facial behavior analysis with remote photoplethysmography (rPPG). A standard RGB camera provides the input; the workspace brings together fatigue indicators, estimated heart rate, signal quality, alerts, and recordings.

Analysis runs in a **local Python engine**, with **Tauri v2 + Flutter Web** providing the desktop console and overlay. An optional Bluetooth LE heart-rate belt supplies a reference for BPM calibration.

**Project status:** A working research and engineering prototype. Fatigue scores and stress indicators support observation and evaluation; the system has no medical or flight-safety certification and should not determine fitness for duty on its own.

## Capabilities

| Capability | What the workspace delivers |
| :--- | :--- |
| **Observe in real time** | Camera preview, facial landmarks, behavioral fatigue, estimated heart rate, and signal quality. Run behavior analysis, rPPG, or both. |
| **Follow changes in vigilance** | Eye closure, PERCLOS, blink timing, squinting, gaze, and head-pose indicators, combined with trends, graded scores, and configurable audio alerts. |
| **Keep monitoring in view** | Independent transparent preview and metrics overlays, with position, size, opacity, and click-through controls where supported. |
| **Build a reviewable record** | SQLite metrics, MP4 recordings, and optional automatic recording for later inspection and calibration. |
| **Replay an observation** | Individual videos or UTA-RLDD batches, with CSV summaries, HTML reports, manifests, and frame-level databases. |
| **Personalize the baseline** | Eye and expression calibration, an individual awake baseline, and optional background BPM calibration against a BLE belt. |
| **Inspect the system** | Desktop settings, local control API v2, HTTP/Socket.IO diagnostics, camera checks, and packaged-runtime smoke tools. |

## From observation to evidence

| 1. Prepare | 2. Monitor | 3. Review |
| :--- | :--- | :--- |
| Select a camera, choose analysis modes, and look naturally toward the lens while the baseline is collected. | Follow behavior, heart-rate estimates, and quality together. Use the overlay and audio alerts as needed. | Inspect recordings, replay the same video under controlled settings, and compare outputs before changing thresholds. |

Stable lighting and a usable face view matter. A visible BPM value alone does not establish reliable HRV, and a completed replay does not establish fatigue-classification accuracy.

## Get started

### Requirements

- **Python 3.12** is the recommended, validated runtime.
- **Node.js/npm, Rust stable, and Flutter SDK** are required for the desktop application.
- **Platform tools:** Microsoft C++ Build Tools on Windows; Xcode Command Line Tools on macOS; the provided system-dependency setup on Ubuntu.
- **Hardware:** an RGB camera; a Bluetooth LE adapter and compatible belt only if reference calibration is needed.

The Python runtime pins `mediapipe==0.10.35` and `opencv-contrib-python==5.0.0.93`. Install only this OpenCV distribution to avoid conflicting `cv2` packages. MediaPipe `1.0.1` is known to terminate the current macOS Face Landmarker process inside the native Metal path.

### Install for your platform

Clone this repository, open its root directory, and use the instructions for your operating system.

<details>
<summary><strong>Windows / PowerShell</strong></summary>

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m scripts.prepare_local_assets --download-model
npm ci
.\.venv\Scripts\python -m scripts.runtime_preflight
```

Launch the desktop console:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_desktop.ps1
```

</details>

<details>
<summary><strong>macOS / Apple Silicon</strong></summary>

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.prepare_local_assets --download-model
npm ci
.venv/bin/python -m scripts.runtime_preflight
```

Launch the desktop console:

```bash
bash scripts/start_desktop_macos.sh
```

Grant camera access when requested, and Bluetooth access if using a belt.

</details>

<details>
<summary><strong>Ubuntu 24.04+ / Linux</strong></summary>

```bash
PYTHON_BIN=python3.12 bash scripts/setup_ubuntu.sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.prepare_local_assets --download-model
npm ci
.venv/bin/python -m scripts.runtime_preflight
```

Launch the desktop console:

```bash
bash scripts/start_desktop_linux.sh
```

</details>

`requirements-dev.txt` includes runtime, testing, packaging, and report tools. For the engine alone, install `requirements.txt`. The launch scripts resolve Flutter packages, check the runtime, and start the console through `npm run desktop`.

**Local assets:** The preparation command creates missing application icons. With `--download-model`, it downloads the pinned Face Landmarker v1 model and verifies its SHA-256 before saving to `models/face_landmarker.task` if absent; existing files are preserved. Images, icons, and model files stay outside Git. Source workers also retain a verified, fixed-version download fallback when a model is missing.

### Your first session

1. Select the camera and enable behavior analysis, rPPG, or both.
2. Start monitoring, face the camera, and allow baseline calibration to finish.
3. Record an awake personal baseline under stable lighting when appropriate.
4. Adjust camera, overlay, alarm, and LAN options in the desktop settings; save to persist supported settings.
5. Enable a BLE belt only when reference BPM calibration is required.

Core monitoring needs **no API key or `.env` file**. Everyday controls belong in the settings area. Advanced development tuning is in `config/mediapipe_tuning.json`: `stable_indoor` is the default profile, alongside `default`, `low_light`, and `high_motion`. Profile changes require restarting the analysis worker; experimental `canonical_roi_warp_enabled` remains off by default.

## Platform readiness

| Platform | Current scope | Delivery |
| :--- | :--- | :--- |
| **Windows x64** | Desktop, camera, and installer validation records exist. DirectShow is preferred, with MSMF fallback. Native global hotkeys are currently Windows-only. | NSIS installer |
| **macOS 15+** | Apple Silicon build flow and source-engine camera/combined-mode smoke records exist. Uses AVFoundation and the MediaPipe CPU delegate. Camera and Bluetooth permissions apply. | arm64 `.app` / `.dmg` |
| **Ubuntu 24.04+ / Linux** | V4L2 and WebKitGTK 4.1 integration and build scripts are implemented. Installation, camera, and data-directory acceptance still require a target Linux host. BLE and overlay support are not declared in the capability registry. | AppImage / deb |
| **Android / iOS** | Planned. Platform contracts and partial native bridges exist; native inference runtime and device acceptance are incomplete. | No validated mobile release |

The capability contract lives in `gui/platforms/registry.py`. Camera smoke tests establish pipeline behavior and frame origin; they do not validate fatigue accuracy, BLE, the Tauri interface, or the entire product. Validation on one platform does not validate another.

### Build a native package

| Target | Run from the repository root | Output under `src-tauri/target/release/bundle/` |
| :--- | :--- | :--- |
| Windows | `powershell -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1` | `nsis/` |
| macOS | `bash scripts/build_desktop_macos.sh` | `macos/`, `dmg/` |
| Linux | `bash scripts/build_desktop_linux.sh` | `appimage/`, `deb/` |

PyInstaller packages the engine; Tauri bundles it with the model and tuning resources. Release builds use the bundled engine, while development uses the checkout source. Rebuild virtual environments, Flutter, Rust, and sidecar artifacts on each target OS rather than copying them between platforms.

Current macOS local packages use ad-hoc signing. Public distribution still requires Developer ID signing and notarization. See the [operations guide](docs/guides/operations.md) for packaging, diagnostics, and acceptance procedures.

macOS 主面板會在建立 WebView 前解除 WebKit 偏好 60fps 的限制，讓捲動可配合 ProMotion／高刷新率螢幕；實際頻率仍由系統與負載決定。此功能使用 WebKit 私有 API，API 不可用時保留預設刷新策略，因此不適用 Mac App Store 發佈。測量與限制見 [ProMotion 捲動審查](docs/technical/promotion_scroll_2026-10-23.md)。

啟動／收尾、預覽回壓、背景 Overlay 與計算重用的修正、量測及未完項目見 [全系統優化追蹤](docs/technical/system_optimization_2026-10-23.md)。

The [macOS REA and module audit](docs/technical/macos_rea_audit_2026-10-22.md) records the installed binary evidence, module contracts, fixes, and remaining hardware validation. The validated Web stack requires `Flask-SocketIO>=5.6.1`, `python-socketio>=5.16.4`, and `python-engineio>=4.14.0`. File Browser uploads require recording and video finalization to finish; databases are uploaded through a consistent SQLite snapshot.

Socket.IO diagnostic consumers must acknowledge `metrics_update`, `frame_update`, and `fb_upload_progress` after accepting each payload. Each client and event keeps one unacknowledged payload and one latest pending snapshot; intermediate upload progress may be replaced. Upload completion and errors remain in the `/api/fb/upload` HTTP response, and `metrics_history` keeps its request/response contract.

## Technical design

### One camera, two complementary analysis paths

```text
RGB camera -> latest-frame queue -> MediaPipe Face Landmarker
                                      |
                     +----------------+----------------+
                     |                                 |
              Eyes / gaze / pose                 Facial skin ROIs
              Behavioral fatigue                 Color projection
                     |                           Filtering / spectrum
                     |                                 |
                     +---------- Quality gates --------+
                                      |
                             Fusion score / alerts
                                      |
                    Flutter console / overlay / SQLite / MP4

BLE heart-rate belt -> reference quality checks -> rPPG BPM calibration
```

When both analysis modes are active, `CombinedWorker` shares one Face Landmarker instance across the two engines. Computation is separated from presentation: PySide6 supplies the hidden runtime, worker threads, and audio; Flask/Socket.IO provides diagnostics and data transport. Tauri owns native window, folder, and browser actions.

<details>
<summary><strong>Behavioral fatigue and quality-gated fusion</strong></summary>

Face Landmarker provides **478 facial landmarks**, blendshapes, and pose information. Fatigue estimation uses rules, time windows, and personal baselines rather than an end-to-end fatigue classifier.

Primary observations are eye aspect ratio (EAR), PERCLOS, and sustained eye closure. Blink timing, squinting, gaze, nodding, frowning, and mouth aspect ratio (MAR)/yawning add context. Pose and downward-gaze gates reduce false eye-closure accumulation when looking down at instruments.

The default fusion is **85% behavior + 15% rPPG**. The physiological contribution requires:

- A detected face and completed warm-up.
- `SQI >= 0.45` and `quality >= 0.55`.
- At least **3 valid ROIs**.

Behavioral evidence requires valid face tracking and baseline calibration. If only one pillar is usable, it receives the full weight; if neither is usable, the result is **No data**.

Scores span **0-1**, with five presentation levels from alert to extreme danger, downgrade hysteresis, and trend information. These levels are engineering prompts, not clinically validated severity grades.

</details>

<details>
<summary><strong>rPPG signal processing, HRV, and confidence</strong></summary>

The system samples RGB time series from the forehead, left/right cheeks, and glabella. By default, ROIs passing pose and obstruction checks are mixed with equal weight.

The implementation named `pos_pulse` applies a Z-score to each RGB channel, then computes:

```text
x     = 3R - 2G
y     = 1.5R + G - 1.5B
pulse = x - [std(x) / (std(y) + epsilon)] * y
```

This describes the implemented color projection; the function name does not establish a complete reproduction of the original POS paper.

A **0.65-3.7 Hz Butterworth band-pass** and **Welch spectral peak** estimate BPM, followed by peak interpolation, smoothing, and jump confirmation. ROI weights, landmark jitter, area stability, and signal quality remain available for diagnostics.

HRV uses pulse-peak intervals with median absolute deviation (MAD) artifact rejection to estimate **RMSSD, SDNN, and LF/HF**, with confidence reporting. It attempts calculation after approximately **30 seconds** of accumulated signal by default.

Camera sampling rate, exposure, motion, and lighting constrain interval precision. A valid BPM estimate does not guarantee reliable HRV; short-window LF/HF and stress heuristics remain exploratory.

</details>

<details>
<summary><strong>Optional BLE reference calibration</strong></summary>

Compatible belts use the standard Heart Rate Service: `0x180D` / `0x2A37`. Calibration compares belt BPM with **raw rPPG BPM**, checks quality, and slowly adjusts the correction offset using a low-gain adaptive update.

The calibration model is `scale * bpm + offset`; the current online flow updates only the offset and saves a version when confidence is sufficient. Belt measurements **never enter the fatigue fusion score directly**. RR-Interval availability depends on the device and operating mode.

</details>

## Data and privacy

| Boundary | Behavior |
| :--- | :--- |
| **Local computation** | Core inference runs on the host. Release Flutter builds use `--no-web-resources-cdn` to bundle renderer resources; initial dependency/model preparation still needs a network connection. Fully offline operation requires acceptance on the target machine. |
| **Local records** | Development stores recordings in `recordings/`, with settings, personal baselines, and calibration kept locally. Installed builds use the user data directory and do not need the repository or a virtual environment. |
| **Local control** | HTTP/Socket.IO defaults to `127.0.0.1:5000` on Windows/Linux and `127.0.0.1:5055` on macOS to avoid the AirPlay Receiver port. The root endpoint returns diagnostic JSON. Desktop control API and `/api/fb/*` File Browser endpoints accept local requests only. |
| **Optional LAN access** | Settings can expose remote APIs/streams, protected by a shared token and origin restrictions. Use the complete URL shown by the console. HTTP has **no TLS encryption**; enable this only on a trusted network and treat token URLs as sensitive. |
| **Repository hygiene** | Images, recordings, databases, models, personal calibration, `.env`, `AGENTS.md`, and `CLAUDE.md` are excluded from version control. Ignore rules do not erase previous Git history. Inspect diagnostic reports for faces, identifiers, and device data before sharing. |

## Validation and replay

Replay uses deterministic timestamps derived from video FPS and the same core analysis engine. Annotated videos are produced only when requested.

The examples below use macOS/Linux paths. On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python`.

```bash
# Automated checks
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py gui rppg scripts tests
.venv/bin/python -m pip check

# Any video: results go to recordings/replay_runs/
.venv/bin/python -m scripts.video_replay /path/to/clip.mp4 --max-frames 300

# UTA-RLDD: databases and reports go to recordings/utarldd_runs/
.venv/bin/python -m scripts.utarldd_replay /path/to/UTA-RLDD --jobs 2

# Numerical regression and label association: provide your own dataset
.venv/bin/python -m scripts.utarldd_golden check /path/to/UTA-RLDD
.venv/bin/python -m scripts.utarldd_accuracy /path/to/UTA-RLDD --subjects '01,02,03,04,05,06' --max-frames 1200 --jobs 2 --out report.json
```

UTA-RLDD labels `0 / 5 / 10` mean **Alert / Low Vigilant / Drowsy** at the video level. Golden checks detect numerical drift; the accuracy tool examines score ordering, Spearman correlation, Drowsy-vs-Alert AUC, and score-range collapse. These checks answer different questions and do not replace evaluation in real UAV operations.

| Check | Scope |
| :--- | :--- |
| `scripts.desktop_hardware_smoke` | Camera pipeline lifecycle and frame origin |
| `scripts.hr_belt_monitor` | Actual BLE notifications from a connected device |
| `scripts.installed_desktop_smoke` | Windows installation/runtime acceptance |
| `scripts.installed_desktop_smoke_macos` | macOS packaged-runtime acceptance |
| `scripts.installed_desktop_smoke_linux` | Linux packaged-runtime acceptance |
| `scripts.desktop_engine_benchmark` | Engine and synthetic-preview measurements; includes loopback polling and ACK, excludes physical camera capture and Flutter rendering |

For engine-only diagnostics, run `.venv/bin/python main.py --engine`; this does not create the desktop console. Existing measurement records are in [docs/benchmarks](docs/benchmarks/).

## Documentation

The product overview, documentation index, and operations guide are available in English. Technical reports and historical records remain primarily in Traditional Chinese.

| Resource | Start here for |
| :--- | :--- |
| [Documentation index](docs/README.md) | All guides, reports, history, and plans |
| [Operations guide](docs/guides/operations.md) | Camera/permission troubleshooting, overlays, LAN, BLE, replay options, packaging checks, and local PDF generation |
| [System overview](docs/technical/system_overview_technical_report.md) | Inputs, outputs, system responsibilities, and limitations |
| [Architecture and algorithm map](docs/technical/system_architecture_algorithm_map.md) | Data flow, computation, and runtime boundaries |
| [rPPG technical report](docs/technical/rppg_technical_report_v2.md) | Signal processing, quality, and physiological estimation |
| [Behavioral fatigue report](docs/technical/mediapipe_fatigue_technical_report.md) | Features, fatigue estimation, and methodology |
| [Replay validation report](docs/technical/utarldd_replay_validation_report.md) | Reproducibility and interpretation of dataset results |
| [REA analysis and improvements](docs/reviews/2026-10-22-rea-report.md) | Artifact evidence, findings, delivered changes, and analysis coverage |

<details>
<summary><strong>Repository map</strong></summary>

```text
main.py                    Python engine entry point
gui/                       Engine orchestration, behavior, recording, replay, APIs
  platforms/               Platform-specific hardware and runtime policies
rppg/                      ROIs, pulse processing, HRV, BLE, calibration
flutter_app/               Desktop console and overlay
src-tauri/                 Native windows, desktop integration, engine packaging
config/                    Shared tuning; personal data remains local
scripts/                   Setup, assets, diagnostics, replay, reports
tests/                     Automated tests and golden baselines
tools/canva-flowchart/      Optional Canva flowchart application
docs/
  guides/                  Setup and operations
  technical/               System, algorithm, and validation reports
  reviews/                 REA analysis and improvement records
  benchmarks/              Saved measurements
  history/                 Dated experiments and development records
  plans/                   Designs and future work
```

</details>

Historical documents may describe earlier interfaces or experiments. Use the source, tests, and version-specific evidence to assess current behavior. Generalization still requires evaluation across people, lighting, cameras, and real operating conditions.
