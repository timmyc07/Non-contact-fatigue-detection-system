# Flutter presentation layer

This directory is the new presentation layer. It runs as Flutter Web inside the Tauri v2 WebView; it is not the native Flutter desktop runner.

## Local development

1. Install the Flutter SDK and make sure `flutter --version` works.
2. Run `flutter pub get` in this directory. The repository already contains the Flutter Web scaffold; do not run `flutter create` over it.
3. Run `npm run desktop` from the repository root. Tauri starts the hidden Python engine and the Flutter Web panel together.
4. For browser-only work, start the engine from the repository root in a separate terminal:

   - Windows: `.venv\Scripts\python main.py --engine`
   - macOS/Linux: `.venv/bin/python main.py --engine`

   From this directory, use `flutter run -d chrome --web-port 1420 --web-hostname 127.0.0.1`.
   On macOS, also pass `--dart-define=NCFD_BACKEND_URL=http://127.0.0.1:5055`.
   Port 1420 matches the engine's desktop Origin allowlist.

The browser build keeps the same layout and uses the HTTP snapshot fallback when Socket.IO is unavailable. Inside Tauri, `lib/services/tauri_bridge.dart` calls `window.__TAURI__.core.invoke`.

## Phase 3 mobile runtime boundary

The shared mobile contract lives in
`lib/models/mobile_runtime_contract.dart`. `MobileRuntimeChannelAdapter` uses:

- Method channel: `tw.fatigue_monitor/mobile_runtime`
- Event channel: `tw.fatigue_monitor/mobile_runtime/events`
- Methods for permission, camera lifecycle, model lifecycle, foreground state,
  and local string storage
- Typed camera frame events with width, height, pixel format, and monotonic
  microsecond timestamps

`createMobileRuntime` selects this channel adapter only for Android/iOS. Desktop
and unsupported platforms keep the fail-closed adapter and never fall back to
the Python desktop engine. The matching Kotlin and Swift channel stubs are in
`native/mobile_runtime/`; they expose lifecycle/storage transport while
returning `runtime_unavailable` for camera, permission, and inference until
Phases 4 and 5 implement the native runtimes. Android/iOS are therefore not
declared runnable by the current app.

The Android runner scaffold compiles the canonical Kotlin stub through its
Gradle main source set and registers it from `MainActivity`. This makes the
Phase 3 channels reachable in an Android runner while preserving the
fail-closed behavior; it does not add camera, permission, or inference support.
An Android SDK and Java runtime are required to build the APK.
