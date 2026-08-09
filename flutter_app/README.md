# Flutter presentation layer

This directory is the new presentation layer. It runs as Flutter Web inside the Tauri v2 WebView; it is not the native Flutter desktop runner.

## Local development

1. Install the Flutter SDK and make sure `flutter --version` works.
2. Run `flutter pub get` in this directory. The repository already contains the Flutter Web scaffold; do not run `flutter create` over it.
3. Start the existing Python application so its Flask/Socket.IO service listens on `127.0.0.1:5000`.
4. Use `flutter run -d chrome` for browser-only work, or run the Tauri dev command from the repository root.

The browser build keeps the same layout and uses the HTTP snapshot fallback when Socket.IO is unavailable. Inside Tauri, `lib/services/tauri_bridge.dart` calls `window.__TAURI__.core.invoke`.
