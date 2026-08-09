import 'dart:js_util' as js_util;

/// Thin interop layer for Flutter Web running inside Tauri v2.
/// Browser development falls back with a clear error instead of crashing at startup.
class TauriBridge {
  const TauriBridge._();

  static final TauriBridge instance = TauriBridge._();

  Future<dynamic> invoke(String command, [Map<String, dynamic>? args]) async {
    final tauri = js_util.getProperty(js_util.globalThis, '__TAURI__');
    if (tauri == null) {
      throw StateError('Tauri bridge is unavailable; running in browser fallback mode.');
    }
    final core = js_util.getProperty(tauri, 'core');
    final promise = js_util.callMethod(core, 'invoke', <dynamic>[
      command,
      args ?? <String, dynamic>{},
    ]);
    return js_util.promiseToFuture<dynamic>(promise);
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
