class TauriBridge {
  const TauriBridge._();

  static final TauriBridge instance = TauriBridge._();

  bool get isAvailable => false;

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

  Future<void> openExternalPath(String path) async {
    await invoke('open_external_path', <String, dynamic>{'path': path});
  }

  Future<void> openExternalUrl(String url) async {
    await invoke('open_external_url', <String, dynamic>{'url': url});
  }

  Future<void> openCameraPrivacySettings() async {
    await invoke('open_camera_privacy_settings');
  }

  Future<void> setOverlayWindow({
    required bool visible,
    required bool locked,
    Map<String, dynamic>? geometry,
    bool resetGeometry = false,
  }) async {
    await invoke('set_overlay_window', <String, dynamic>{
      'visible': visible,
      'locked': locked,
      'geometry': geometry,
      'resetGeometry': resetGeometry,
    });
  }

  Future<Map<String, dynamic>?> getOverlayGeometry() async {
    final value = await invoke('get_overlay_geometry');
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }
}
