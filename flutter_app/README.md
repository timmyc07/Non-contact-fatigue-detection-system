# Flutter presentation layer

This directory is the new presentation layer. It runs as Flutter Web inside the Tauri v2 WebView; it is not the native Flutter desktop runner.

## Local development

1. Install the Flutter SDK and make sure `flutter --version` works.
2. Run `flutter pub get` in this directory. The repository already contains the Flutter Web scaffold; do not run `flutter create` over it.
3. Run `npm run desktop` from the repository root. Tauri starts the hidden Python engine and the Flutter Web panel together.
4. For browser-only work, start `.venv\Scripts\python main.py --engine` separately, then use `flutter run -d chrome`.

The browser build keeps the same layout and uses the HTTP snapshot fallback when Socket.IO is unavailable. Inside Tauri, `lib/services/tauri_bridge.dart` calls `window.__TAURI__.core.invoke`.
