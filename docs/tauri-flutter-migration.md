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

The production path starts `main.py --engine`. In this mode `MainWindow` no
longer constructs the legacy Qt menu, central dashboard, or Qt overlay, and the
engine path does not apply the visual QSS, window size, title bar, or status bar.
The remaining Qt `MainWindow` is an internal event-loop/runtime adapter. The
Qt-free `EngineController` is the product-state authority for camera
configuration, the desired analysis mode, active pipeline state, the
Combined/RPPG/Fatigue worker topology, recording and replay/shutdown lifecycle
state, and the injected BLE runtime. The desired analysis mode remains valid
while the pipeline is stopped; starting the pipeline consumes that controller
state instead of reading hidden Qt controls.
Overlay visibility, lock, group-enable, and opacity preferences now live in the
Qt-free `OverlayRuntimeState`. Engine mode does not construct the legacy Qt
overlay, overlay checkboxes/sliders, or a no-op Qt-shaped overlay adapter. The
legacy Qt widgets remain presentation mirrors only in the non-production path.
`MainWindow` still constructs the concrete QThreads, recording writers, Qt
multimedia alarm backend, calibration adapters, and signal callbacks. Its
`_pipeline_running` and `_recording` fields are transitional mirrors of concrete
Qt resource state, not command/API authorities. The legacy analysis checkboxes
are likewise presentation mirrors; settings load/save, `state.get`, worker
failure recovery, and auto-capture read the controller-owned analysis state.
The desktop command API exposes the controller-backed state to Flutter/Tauri.
Tauri overlay geometry is not yet part of this state model. Engine settings
continue to write an empty `overlay.geometry` only for backward schema
compatibility until a Tauri window-position bridge owns that preference.

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

## Rollout

The original Flask dashboard remains available at `http://127.0.0.1:5000` as a diagnostics fallback. Flutter/Tauri owns the visible live monitor, camera controls, recording, analysis modes, calibration toggles, settings, replay, notifications, and overlay. Qt remains only as an internal event-loop/worker runtime while the remaining runtime state is extracted behind the desktop command interface.
