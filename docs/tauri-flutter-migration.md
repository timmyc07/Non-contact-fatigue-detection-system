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

- `src-tauri/tauri.conf.json`: frameless 1280x820 window, transparency, CSP, and Flutter build hooks.
- `src-tauri/capabilities/default.json`: least-privilege window manipulation permissions.
- `src-tauri/src/main.rs`: window commands plus `get_system_info` and always-on-top support.
- `src-tauri/icons/icon.ico`: placeholder shell icon; replace it with the product mark before release.
- `flutter_app/lib/services/tauri_bridge.dart`: Dart to Tauri IPC bridge.
- `flutter_app/lib/services/backend_service.dart`: Socket.IO stream with `/api/metrics` polling fallback.
- `flutter_app/lib/main.dart`: new dashboard shell and stateful UI surfaces.

## Headless engine status

The production path starts `main.py --engine`. In this mode `MainWindow` no
longer constructs the legacy Qt menu, central dashboard, or Qt overlay. A
state-only adapter preserves the desktop command interface while camera,
workers, recording, alarms, BLE, replay, rPPG, fatigue scoring, and calibration
continue to use the existing runtime paths.

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

## Build prerequisites

Development requires Node, Rust, and Flutter/Dart. The Python engine remains a separate runtime and must be present beside the source tree (or configured explicitly) when running a packaged shell:

```powershell
Set-Location flutter_app
flutter pub get
flutter build web --release
Set-Location ..
npm install --save-dev @tauri-apps/cli
npm run desktop
```

For an installed Tauri build, set `NCFD_ENGINE_ROOT` to the directory containing `main.py`, `gui/`, `rppg/`, `models/`, and the Python environment, and optionally set `NCFD_ENGINE_PYTHON` to its interpreter. The shell also searches install-relative directories for `main.py`; it never relies on a developer machine path when those variables are provided. Set `NCFD_BACKEND_PORT` consistently and pass `--dart-define=NCFD_BACKEND_URL=http://127.0.0.1:<port>` when using a non-default port.

The current NSIS artifact packages the Tauri/Flutter shell but not a frozen
Python runtime. It is therefore a shell installer, not yet a standalone product
installer. A release is standalone only after the engine, model, immutable
tuning assets, and writable per-user calibration/config paths are packaged and
verified outside the repository checkout.

The Dart bridge uses the Tauri global API exposed by `withGlobalTauri`, so a JavaScript `@tauri-apps/api` import is not required for the Flutter Web build.

`npm run desktop` starts the Python engine automatically through Tauri. For browser-only Flutter work, start `.venv\Scripts\python main.py --engine` separately. `flutter build web --release` is invoked by Tauri's `beforeBuildCommand`.

## Rollout

The original Flask dashboard remains available at `http://127.0.0.1:5000` as a diagnostics fallback. Flutter/Tauri owns the visible live monitor, camera controls, recording, analysis modes, calibration toggles, settings, replay, notifications, and overlay. Qt remains only as an internal event-loop/worker runtime while the remaining runtime state is extracted behind the desktop command interface.
