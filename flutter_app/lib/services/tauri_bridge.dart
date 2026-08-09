import 'dart:js_interop';

@JS('window.__TAURI__.core.invoke')
external JSPromise<JSAny?> _tauriInvoke(String command, JSAny? args);

/// Thin interop layer for Flutter Web running inside Tauri v2.
/// Browser development falls back with a clear error instead of crashing at startup.
class TauriBridge {
  const TauriBridge._();

  static final TauriBridge instance = TauriBridge._();

  Future<dynamic> invoke(String command, [Map<String, dynamic>? args]) async {
    try {
      final result = await _tauriInvoke(command, (args ?? <String, dynamic>{}).jsify()).toDart;
      return result?.dartify();
    } catch (error) {
      throw StateError('Tauri bridge unavailable or command failed: $error');
    }
  }

  Future<void> minimizeWindow() async {
    await invoke('minimize_window');
  }

  Future<void> toggleMaximizeWindow() async {
    await invoke('toggle_maximize_window');
  }

  Future<void> closeWindow() async {
    await invoke('close_window');
  }

  Future<void> startDragging() async {
    await invoke('start_dragging');
  }

  Future<bool> toggleAlwaysOnTop() async {
    final value = await invoke('toggle_always_on_top');
    return value == true;
  }

  Future<Map<String, dynamic>> getSystemInfo() async {
    final value = await invoke('get_system_info');
    if (value is Map) {
      return Map<String, dynamic>.from(value);
    }
    return <String, dynamic>{};
  }
}
