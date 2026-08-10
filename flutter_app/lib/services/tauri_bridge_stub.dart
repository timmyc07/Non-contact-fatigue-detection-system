class TauriBridge {
  const TauriBridge._();

  static final TauriBridge instance = TauriBridge._();

  Future<dynamic> invoke(String command, [Map<String, dynamic>? args]) async {
    throw UnsupportedError(
        'Tauri command "$command" is only available on Web.');
  }

  Future<void> minimizeWindow() async => invoke('minimize_window');

  Future<void> toggleMaximizeWindow() async => invoke('toggle_maximize_window');

  Future<void> closeWindow() async => invoke('close_window');

  Future<void> startDragging() async => invoke('start_dragging');

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

  Future<String?> pickReplayFolder() async => null;
}
