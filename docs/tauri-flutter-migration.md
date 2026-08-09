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

The Dart bridge uses the Tauri global API exposed by `withGlobalTauri`, so a JavaScript `@tauri-apps/api` import is not required for the Flutter Web build.

`npm run desktop` starts the Python engine automatically through Tauri. For browser-only Flutter work, start `.venv\Scripts\python main.py --engine` separately. `flutter build web --release` is invoked by Tauri's `beforeBuildCommand`.

## Rollout

The original Flask dashboard remains available at `http://127.0.0.1:5000` as a diagnostics fallback. The Flutter panel now owns live monitoring, camera selection, pipeline/recording controls, analysis modes, calibration toggles, settings, and camera preview. Advanced batch replay tools remain reachable through the legacy panel command until their Flutter workflows are migrated.
