import 'dart:async';
import 'dart:js_interop';

@JS('window.__TAURI__.core.invoke')
external JSPromise<JSAny?> _tauriInvoke(String command, JSAny? args);

@JS('window.__TAURI__')
external JSAny? get _tauriGlobal;

@JS('window.__TAURI__.event.listen')
external JSPromise<JSFunction> _tauriListen(String event, JSFunction callback);

extension type _TauriEvent(JSObject _) implements JSObject {
  external JSAny? get payload;
}

/// Thin interop layer for Flutter Web running inside Tauri v2.
/// Browser development falls back with a clear error instead of crashing at startup.
class TauriBridge {
  const TauriBridge._();

  static final TauriBridge instance = TauriBridge._();

  bool get isAvailable => _tauriGlobal != null;

  Stream<bool> overlayVisibilityChanges() {
    late StreamController<bool> events;
    JSFunction? unlisten;
    var cancelled = false;
    var changes = 0;

    Future<void> removeListener() async {
      final callback = unlisten;
      unlisten = null;
      if (callback != null) {
        await (callback.callAsFunction() as JSPromise<JSAny?>).toDart;
      }
    }

    events = StreamController<bool>(onListen: () async {
      try {
        unlisten = await _tauriListen(
                'ncfd-overlay-visibility',
                ((JSObject event) {
                  final visible = _TauriEvent(event).payload.dartify();
                  if (!cancelled && visible is bool) {
                    changes++;
                    events.add(visible);
                  }
                }).toJS)
            .toDart;
        if (cancelled) {
          await removeListener();
          return;
        }
        final beforeQuery = changes;
        final visible = await invoke('get_overlay_visibility');
        if (!cancelled && changes == beforeQuery && visible is bool) {
          events.add(visible);
        }
      } catch (error, stack) {
        if (!cancelled) events.addError(error, stack);
      }
    }, onCancel: () async {
      cancelled = true;
      await removeListener();
    });
    return events.stream;
  }

  Future<dynamic> invoke(String command, [Map<String, dynamic>? args]) async {
    try {
      final result =
          await _tauriInvoke(command, (args ?? <String, dynamic>{}).jsify())
              .toDart;
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

  Future<String?> pickReplayFolder() async {
    final value = await invoke('pick_replay_folder');
    return value is String && value.isNotEmpty ? value : null;
  }

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
    if (value is! Map) return null;
    final raw = Map<String, dynamic>.from(value);
    final normalized = <String, dynamic>{};
    for (final key in const ['x', 'y', 'width', 'height']) {
      final item = raw[key];
      if (item is! num || !item.isFinite || item != item.roundToDouble()) {
        return null;
      }
      normalized[key] = item.toInt();
    }
    return normalized;
  }
}
