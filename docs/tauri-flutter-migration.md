# Tauri + Flutter UI migration

## Decision

The application keeps the existing Python process as the domain and data engine. Flask/Socket.IO remains the local transport, while Flutter Web becomes the presentation layer and Tauri v2 supplies the native window shell.

```text
Python workers / MediaPipe / rPPG / SQLite
                 |
                 +-- Flask HTTP + Socket.IO (127.0.0.1:5000)
                                      |
                                Flutter Web UI
                                      |
                                Tauri v2 WebView
```

This boundary is deliberately additive. The numeric paths in `rppg/`, `gui/fatigue_engine.py`, and `gui/fatigue_scorer.py` are unchanged.

## Gemini prompt verification

- Tauri v2 uses `build.frontendDist`; `distDir` is the v1 spelling.
- The global API is `window.__TAURI__`, not `window.**TAURI**`.
- Window permissions belong in `src-tauri/capabilities/default.json`.
- Flutter Web in a Tauri WebView is different from Flutter's native desktop runner.
- CanvasKit, transparency, and blur are platform/WebView dependent. The UI therefore has a solid dark fallback and does not treat blur as a functional dependency.
- Python remains the owner of camera lifecycle, scoring, calibration, replay, alarms, and persistence. Tauri commands are limited to shell operations and small host capabilities.

## Files

- `src-tauri/tauri.conf.json`: frameless opaque 1280x820 main window, transparent overlay, CSP, and Flutter build hooks.
- `src-tauri/capabilities/default.json`: least-privilege window manipulation permissions.
- `src-tauri/src/main.rs`: window commands plus `get_system_info` and always-on-top support.
- `src-tauri/icons/icon.ico`: placeholder shell icon; replace it with the product mark before release.
- `flutter_app/lib/services/tauri_bridge.dart`: Dart to Tauri IPC bridge.
- `flutter_app/lib/services/backend_service.dart`: Socket.IO stream with `/api/metrics` polling fallback.
- `flutter_app/lib/main.dart`: new dashboard shell and stateful UI surfaces.

## Headless engine status

The production path starts `main.py --engine`. It creates an internal
`EngineApplication(QObject)` runtime adapter, not a `QMainWindow` or QWidget,
and does not apply the legacy QSS, window size, title bar, or status bar.
Qt-free `EngineController` is the product-state authority for camera
configuration, the desired analysis mode, active pipeline state, the
Combined/RPPG/Fatigue worker topology, recording and replay/shutdown lifecycle
state, and the injected BLE runtime. The desired analysis mode remains valid
while the pipeline is stopped; starting the pipeline consumes that controller
state instead of reading hidden Qt controls.
Camera discovery, selection, resolution, FPS, backend, and horizontal-flip
commands update the controller directly. Camera combo boxes and the flip
checkbox presentation mirrors have been removed.
Overlay visibility, lock, group-enable, and opacity preferences now live in the
Qt-free `OverlayRuntimeState`. Engine mode does not construct the legacy Qt
overlay, overlay checkboxes/sliders, or a no-op Qt-shaped overlay adapter. The
legacy Qt widget presentation mirrors have been removed.
Replay folder, jobs, annotated-output preference, and progress text/counts now
live in the Qt-free `ReplayRuntimeState`. Engine mode no longer constructs the
replay spinbox, checkbox, folder/current/result/status labels, or replay buttons.
`EngineController` still owns replay lifecycle, while the application-owned
`EngineRuntime` now owns the existing QThread and `VideoReplayWorker`.
Auto-record, belt-calibration, and auto-capture preferences now live in the
Qt-free `CapturePreferencesState`. Engine mode no longer constructs their
legacy checkboxes, duration spinbox, or auto-capture button. Auto-record and
belt-calibration retain the existing settings JSON toggle contract; duration
and include-belt remain session-scoped. `EngineRuntime` owns the belt tick and
auto-capture timers, while `EngineApplication` still performs BLE, calibration,
recording, and callback side effects and rolls preference state back when an
adapter fails.
`EngineRuntime` constructs and owns the concrete QThreads and workers, plus the
`FatigueAlarmController` and Qt multimedia `QtAlarmPlaybackBackend`/
`QMediaPlayer`/`QAudioOutput`. `EngineApplication` still constructs recording writers,
calibration adapters, and worker-specific signal callbacks, and only routes alarm
configure, preview, and metrics calls. Its
`_pipeline_running` and `_recording` fields are transitional mirrors of concrete
Qt resource state, not command/API authorities. Analysis checkbox stand-ins and
their presentation mirrors have been removed. Settings load/save, `state.get`, worker
failure recovery, and auto-capture read the controller-owned analysis state.
Web LAN access now lives in the Qt-free `WebPreferencesState`. Engine mode does
not construct a QAction stand-in; settings load/save, desktop state, bind-host
selection, and dashboard URL formatting read the state directly. The existing
web-server thread, shared-token URL, and non-blocking restart coordination stay
in the `EngineApplication` runtime adapter, with localhost-only remaining the default.
Engine-mode runtime messages now go directly to the Python logger instead of a
QTextEdit-shaped no-op sink. The rich-text log console and status-bar projection
source have been removed.
Engine-mode global hotkeys now use sequence-and-callback bindings instead of
QAction-shaped stand-ins. The application-level `GlobalHotkeyRuntime` registers
Windows thread-queue hotkeys, dispatches native events, and cleans up successful
registrations without a QWidget HWND or `nativeEvent()`.
Legacy menu shortcut and fake `statusBar()` source has been removed.
Engine mode no longer creates hidden monitor labels, progress bars, sparklines,
or the legacy REC-pill timer.
The remaining dormant Qt visual modules (`PreviewOverlayWindow`, the old settings
dialogs, and the alarm dialog) were removed on 2026-08-18. `HotkeyConfig` and
`UserProfile` now live in the Qt-free `gui/desktop_models.py`; this keeps the
engine import graph focused on runtime services while Flutter owns all forms and
visible overlay rendering.
The rPPG, behavior, and fusion callbacks retain their snapshot, alarm, baseline,
recording, and Web-metrics side effects; Flutter renders the shared metrics payload.
Engine mode also omits hidden belt labels, banners, device status, sparklines, and
calibration bars. The `EngineRuntime`-owned one-second belt timer remains active
because it drives new rPPG/belt calibration observations and the ROI coordinator;
Flutter renders the BLE, HRV, and calibration fields already carried by Web metrics.
Engine mode no longer creates a generic `_HeadlessControl` or fake pipeline,
recording, camera, or profile buttons, labels, and tags. Shared
lifecycle callbacks keep controller snapshots, recording resources, camera
telemetry, baseline collection, notifications, and Web metrics intact; Qt text
and button updates are restricted to the non-production legacy path.
The desktop state/command contract and Flutter controls no longer expose the
demo benchmark that only toggled UI text. Repeatable performance measurement
remains available through `scripts.desktop_engine_benchmark`.
The desktop command API exposes the controller-backed state to Flutter/Tauri.
Tauri overlay geometry is part of the same state model as a platform-neutral
physical-pixel `{x, y, width, height}` object. The shell applies geometry when
it creates the overlay or when Python's authoritative value explicitly changes.
Normal polling only reports actual native geometry, so manual movement is not
reset. Flutter updates Python runtime state only when the native value changes.
Persisting still occurs through the existing explicit `settings.save`
transaction. Legacy Qt base64 geometry/state is retained as an opaque payload
and round-trips unchanged; the production engine no longer calls QWidget
save/restore APIs.
Replay configuration remains session-scoped as before; this extraction does
not add a settings JSON schema. Worker parameters, deterministic timestamps,
annotated output, UTA-RLDD validation reports, and analysis values are unchanged.
The capture-preference extraction likewise leaves camera capture, worker
topology, BLE samples, calibration math, recording workers, rPPG output, and
fatigue scores unchanged.
Engine `app.shutdown` preserves the active-replay stop/defer gate; once the
replay thread finishes, shutdown re-enters. Every other engine shutdown calls
the re-entrant `_cleanup_runtime()` directly, then `QApplication.quit()`, rather
than requiring a widget close event. Cleanup is ordered: hotkeys,
pending auto-capture, belt calibration/timer/BLE, Web restart/server, recording,
camera/analysis producers, alarm, then overlay; failed cleanup can be retried.
Alarm close is idempotent and releases the runtime controller before best-effort
player stop. The production adapter exposes explicit `close_runtime()` teardown
and has no `closeEvent()`. An application-owned
`EngineRuntime(QObject)` now owns the live camera and combined/rPPG/fatigue
adapter threads and workers, including common signal wiring, the existing stop
timeouts, join-before-release, and stale-finish protection. `EngineApplication` retains only worker-specific
callbacks, queue/routing work, and headless state side effects. Recording
and replay QThread/worker ownership is also held by `EngineRuntime`: recording
retains cooperative stop plus the existing 2000 ms join timeout and late-finish
cleanup, while replay sends only a cooperative stop request and completes its
controller/shutdown deferral from the released-adapter callback. `EngineRuntime`
also owns desktop-command drain, belt tick, auto-capture, and shutdown defer/retry
timers; the legacy REC presentation timer has been removed, while Web restart and
Overlay scheduling remain with their existing owners. Alarm/multimedia ownership is
application-owned; the production adapter no longer inherits `QMainWindow`, and
the `MainWindow` compatibility alias has been removed. The next major boundary is
parity/performance acceptance followed by further reduction of Qt engine-only dependencies. This ownership
change does not alter alarm conditions, volume, fallback, strict validation, error
mapping, metrics ordering, camera, worker topology, recording, BLE, replay, rPPG,
fatigue, ROI, calibration, or any measurement values.
Cleanup is stepwise best-effort: non-thread step failures are logged and later
steps continue; the main event loop retries once after 100ms, then logs and
best-effort quits if that second attempt still fails. If a video,
camera, or analysis-adapter thread wait times out while ownership remains, the
engine does not quit; the `EngineRuntime.adapter_released` callback schedules
shutdown to re-enter. Tauri waits six seconds before its final child-process
kill fallback.

The repeatable benchmark supports a non-default loopback port so it can run
without stopping an active desktop session:

```powershell
.venv\Scripts\python -m scripts.desktop_engine_benchmark --port 5001 --samples 10
```

On the same Windows host, commit `4106977` (hidden full Qt dashboard) measured
270.0 MiB process-tree RSS and 1844.8 ms to API readiness. The headless visual
shell measured 256.3 MiB and 1843.5 ms: 13.7 MiB (5.1%) less memory with no
startup regression. Preview encoding stayed within benchmark noise. These are
microbenchmarks; they exclude a physical camera and Flutter WebView rendering.

Latest verification run (Windows, Python 3.11, 10 samples, port 5003) measured
255.359 MiB process-tree RSS at readiness, 2454.079 ms startup to API ready,
`state.get` p50 20.312 ms / p95 40.408 ms, and synthetic JPEG encode mean
1.347 ms. Startup and latency are environment-sensitive; retain the command
and sample settings when comparing future changes rather than treating these
values as hard product limits.
The raw result and capture metadata are retained in
`docs/benchmarks/desktop-engine-2026-08-10.json`.

After removing the UI-only demo benchmark on 2026-08-15, two equivalent runs
measured 257.383/257.023 MiB RSS, 1847.185/1830.502 ms startup,
`state.get` p50 19.993/20.101 ms and p95 40.366/40.234 ms, with synthetic JPEG
encode p50 1.189/1.168 ms and p95 1.486/1.480 ms. Startup and latency remained
flat; the roughly 2.3 MiB RSS difference from the previous 254.711 MiB repeat
is below one percent and treated as process-allocation noise, not a regression.
The local raw captures remain under ignored `build/` output.

After extracting pipeline, analysis topology, recording/replay state, shutdown
sequencing, and BLE ownership into the Qt-free controller, the 2026-08-11 run
measured 254.746 MiB RSS, 1848.248 ms startup, `state.get` p50 20.636 ms / p95
40.728 ms, and JPEG encode mean 1.222 ms. A later single run measured 255.059
MiB RSS, 2476.652 ms startup, `state.get` p50 19.789 ms / p95 40.929 ms, and
JPEG encode mean 1.473 ms. This small sample is suitable for detecting large
lifecycle regressions only; startup and encoding variance must not be treated
as a performance improvement or regression without repeated measurements. Raw
baseline data is retained in
`docs/benchmarks/desktop-engine-lifecycle-2026-08-11.json`.

After moving live camera and analysis adapter ownership into `EngineRuntime`,
two final 2026-08-15 runs measured 257.625/257.410 MiB RSS,
1848.390/1837.974 ms startup, `state.get` p50 20.048/20.436 ms and p95
40.894/40.436 ms, with synthetic JPEG encode p50 1.213/1.220 ms and p95
1.478/1.493 ms. These values remain within the prior shutdown-slice range and
are treated as normal process/startup noise rather than a regression. Raw
captures and limitations are retained in
`docs/benchmarks/desktop-engine-runtime-ownership-2026-08-15-run1.json` and
`docs/benchmarks/desktop-engine-runtime-ownership-2026-08-15-run2.json`.

After moving recording and replay QThread/worker ownership into `EngineRuntime`,
two 2026-08-17 runs measured 255.660/256.367 MiB RSS,
1852.892/1843.677 ms startup, `state.get` p50 20.034/20.180 ms and p95
40.615/40.010 ms, with synthetic JPEG encode p50 1.148/1.214 ms and p95
1.341/1.666 ms. These results remain within the previous ownership-slice range
and do not indicate a regression in engine startup, process-tree RSS, localhost
`state.get`, or synthetic JPEG encode/dispatch. They do not measure a physical
camera, network transport, Tauri WebView decode, or Flutter rendering. Raw
captures are retained in
`docs/benchmarks/desktop-engine-recording-replay-ownership-2026-08-17-run1.json`
and `docs/benchmarks/desktop-engine-recording-replay-ownership-2026-08-17-run2.json`.
The rebuilt PyInstaller bundle input and isolated NSIS installation both exposed
desktop API v2 and completed `app.shutdown`; the bundle input exited with code 0.
Evidence is retained in
`docs/benchmarks/packaged-engine-recording-replay-ownership-2026-08-17.json`.

After moving production desktop-command, belt-tick, auto-capture, and shutdown
timer ownership into `EngineRuntime`, two later 2026-08-17 runs measured
256.473/256.059 MiB RSS, 1848.305/1846.954 ms startup, `state.get` p50
20.342/20.529 ms and p95 40.437/39.684 ms, with synthetic JPEG encode p50
1.229/1.211 ms and p95 1.480/1.480 ms. These values remain within the prior
ownership-slice range and do not indicate a regression in the measured startup,
process-tree RSS, localhost `state.get`, or synthetic JPEG path. Raw captures
are retained in
`docs/benchmarks/desktop-engine-runtime-timer-ownership-2026-08-17-run1.json`
and `docs/benchmarks/desktop-engine-runtime-timer-ownership-2026-08-17-run2.json`.
The rebuilt bundle input and isolated NSIS installation exposed desktop API v2,
completed `app.shutdown`, and exited normally; hashes and smoke details are in
`docs/benchmarks/packaged-engine-runtime-timer-ownership-2026-08-17.json`.

After moving alarm controller and Qt multimedia ownership into `EngineRuntime`,
two later 2026-08-17 runs measured 256.434/256.199 MiB RSS,
1845.500/1850.936 ms startup, `state.get` p50 20.121/20.207 ms, and synthetic
JPEG encode p50 1.157/1.146 ms. These results remain within the prior ownership
slice range. Raw captures are retained in
`docs/benchmarks/desktop-engine-runtime-alarm-ownership-2026-08-17-run1.json`
and `docs/benchmarks/desktop-engine-runtime-alarm-ownership-2026-08-17-run2.json`.
Python completed `737 passed, 2 skipped` with the focused alarm/runtime/settings
slice at `156 passed`; compileall and pip check passed. Flutter completed 28 tests,
analyze, and release Web build; Rust completed 8 tests; PyInstaller sidecar, Tauri
release/NSIS, bundle-input smoke, and isolated installed smoke all passed. Hashes
and smoke details are retained in
`docs/benchmarks/packaged-engine-runtime-alarm-ownership-2026-08-17.json`.
Golden/replay was not run because no UTA-RLDD dataset path was available. The
benchmarks do not cover a physical camera, BLE device, or Flutter WebView rendering.

After replacing the hidden `QMainWindow` instance with `EngineApplication(QObject)`,
two 2026-08-17 runs measured 256.172/256.113 MiB RSS,
1839.081/2453.306 ms startup, `state.get` p50 20.302/20.048 ms, and synthetic
JPEG encode p50 1.173/1.163 ms. RSS, IPC, and JPEG encode remained within the
previous ownership slice range. The second startup sample is retained as
environment-sensitive variance, not claimed as an improvement or regression.
Raw captures are in
`docs/benchmarks/desktop-engine-qmainwindow-removal-2026-08-17-run1.json` and
`docs/benchmarks/desktop-engine-qmainwindow-removal-2026-08-17-run2.json`.
Python completed `739 passed, 2 skipped`; Flutter completed 28 tests, analyze,
and release Web build; Rust completed 8 tests; compileall, pip check,
PyInstaller, Tauri release/NSIS, and bundle-input API/shutdown smoke passed.
The isolated installer exposed API v2, accepted `app.shutdown`, exited the Tauri
shell with code 0, uninstalled silently, and removed its installation directory.
The reusable smoke targets only the top-level `Tauri Window`; sending WM_CLOSE
to Tao event-pump helper windows prevents normal event-loop exit. Evidence and hashes are in
`docs/benchmarks/packaged-engine-qmainwindow-removal-2026-08-17.json`.

After removing the remaining legacy presentation helpers, widget imports, and
the `MainWindow` compatibility alias, two later 2026-08-17 runs measured
254.062/253.805 MiB RSS, 1846.225/1843.543 ms startup, `state.get` p50
20.610/20.327 ms, and synthetic JPEG encode p50 1.166/1.263 ms. Compared with
the preceding `QMainWindow` removal samples, process-tree RSS was about
2.1-2.3 MiB lower. Startup, IPC, and JPEG differences remain within observed
noise and are not claimed as improvements. Raw captures are in
`docs/benchmarks/desktop-engine-legacy-ui-cleanup-2026-08-17-run1.json` and
`docs/benchmarks/desktop-engine-legacy-ui-cleanup-2026-08-17-run2.json`.
After removing the dormant Qt visual modules, two repeat runs measured
252.98/253.297 MiB RSS, 2438.245/2464.125 ms startup, `state.get` p50
20.255/20.355 ms, and synthetic JPEG p50 1.314/1.305 ms. The runs are retained
as `docs/benchmarks/desktop-engine-headless-qt-visual-removal-2026-08-18-run1.json`
and `run2.json`; these remain noisy local baselines rather than a claim of a
numeric improvement.
The clean follow-up validation completed `757 passed, 2 skipped`; `compileall`
and `pip check` passed. Flutter completed 28 tests, analyze, and release Web
build; Rust completed 8 tests; PyInstaller, Tauri release/NSIS, and isolated
installed smoke all passed. The installed application exposed desktop API v2,
created exactly one visible `Tauri Window`, accepted `app.shutdown`, exited
normally, uninstalled with code 0, and left no installation directory. The
release shell was also directly observed starting with the title
`疲勞監測操作台`, a WebView2 child process, and the bundled `ncfd-engine.exe`
sidecar; normal window close exited with code 0. A native release-window visual
smoke also rendered the Flutter main dashboard and successfully navigated by
click to the heart-rate belt, replay, and system-settings sections. This proves
the packaged WebView is rendering and the top-level navigation is interactive;
it is not a substitute for exhaustive camera, overlay, BLE, and replay-data
interaction with physical inputs.
Golden/replay was not run because the UTA-RLDD dataset is not present on this
machine. This slice did not modify camera routing, worker topology, recording,
alarm, BLE, replay, rPPG, fatigue scoring, ROI, calibration, or numeric
thresholds.

For repeatable physical-camera lifecycle verification, `scripts.desktop_hardware_smoke`
starts the source engine on a loopback port, selects a camera through desktop API v2,
configures one of `raw`, `fatigue`, `rppg`, or `combined` worker modes, waits for live
metrics, and then stops the pipeline and engine without saving settings or recording.
On 2026-08-18, `WebCamera` passed the `combined` smoke at 1280x720 and 30 FPS with
`frame_source=combined`; the API version, camera selection, start/stop, and metrics
checks all passed. The combined capture is
`docs/benchmarks/desktop-hardware-smoke-2026-08-18.json`; the raw camera capture is
`docs/benchmarks/desktop-hardware-smoke-2026-08-18-raw.json`. These validate lifecycle
and routing only, not rPPG/fatigue numeric accuracy or Tauri WebView rendering. BLE remains
separately diagnosable through `scripts.hr_belt_monitor`; this host entered scanning but
received no heart-rate notification in a four-second sample, so end-to-end BLE evidence
is still pending a worn, in-range belt.

## Build prerequisites

Development requires Node, Rust, Flutter/Dart, and the repository Python
environment. The development shell starts the source engine from this checkout:

```powershell
Set-Location flutter_app
flutter pub get
flutter build web --release
Set-Location ..
npm install --save-dev @tauri-apps/cli
npm run desktop
```

Installed builds use the bundled sidecar automatically. `NCFD_ENGINE_ROOT` and
`NCFD_ENGINE_PYTHON` remain development/custom-runtime overrides for a source
engine. Set `NCFD_BACKEND_PORT` consistently and pass
`--dart-define=NCFD_BACKEND_URL=http://127.0.0.1:<port>` when using a non-default
port during development.

`scripts/build_engine_sidecar.ps1` creates a PyInstaller `--onedir` engine under
`dist/ncfd-engine/`. `scripts/build_desktop.ps1` runs that step before the
Flutter/Tauri build, and `src-tauri/tauri.conf.json` embeds it under the
installer's `engine/` resource directory. At runtime Tauri injects
`NCFD_RESOURCE_ROOT` for immutable bundled assets and `NCFD_DATA_ROOT` for
per-user settings, recordings, and calibration. The resulting NSIS artifact is
a standalone product installer and no longer depends on a checkout or `.venv`.
The NSIS build embeds the offline WebView2 installer, so first launch does not
depend on network access. Release executables are not Authenticode-signed until
a project signing certificate is configured; SmartScreen trust remains a
distribution release gate rather than a runtime dependency.
On 2026-08-10, the generated NSIS package was silently installed into an
isolated temporary directory and launched successfully: the bundled engine
returned desktop API v2, created the per-user calibration data root, and its
child process exited after a normal shell close. This is a packaging smoke
check, not a camera or sensor accuracy run. The observed checks are retained in
`docs/benchmarks/packaged-smoke-2026-08-10.json`.

The Dart bridge uses the Tauri global API exposed by `withGlobalTauri`, so a JavaScript `@tauri-apps/api` import is not required for the Flutter Web build.

`npm run desktop` starts the Python engine automatically through Tauri. For
browser-only Flutter work, start `.venv\Scripts\python main.py --engine`
separately. `flutter build web --release` is invoked by Tauri's
`beforeBuildCommand`.
Debug Tauri builds deliberately ignore any stale sidecar copied under
`src-tauri/target/debug/engine` and launch the current checkout through its
source Python environment. Release builds continue to resolve and launch the
bundled sidecar from the application resource directory.

## Rollout

The original Flask dashboard remains available at `http://127.0.0.1:5000` as a diagnostics fallback. Flutter/Tauri owns the visible live monitor, camera controls, recording, analysis modes, calibration toggles, settings, replay, notifications, and overlay. Qt remains only as an internal event-loop/worker runtime while the remaining runtime state is extracted behind the desktop command interface.
