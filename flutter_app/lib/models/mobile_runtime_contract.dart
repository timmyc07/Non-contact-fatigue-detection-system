import 'dart:async';

import 'package:flutter/services.dart';

import 'platform_contract.dart';

/// Permission categories that a native mobile adapter may request.
enum RuntimePermission {
  camera,
  storage,
}

enum PermissionState {
  unknown,
  denied,
  restricted,
  granted,
}

enum ForegroundState {
  active,
  inactive,
  background,
  terminated,
}

enum ModelRuntimeState {
  unloaded,
  loading,
  ready,
  failed,
}

enum CameraPixelFormat {
  rgba8888,
  bgra8888,
  yuv420,
}

/// Stable names shared by the Dart adapter and the Android/iOS plugin stubs.
class MobileRuntimeChannelContract {
  const MobileRuntimeChannelContract._();

  static const methodChannelName = 'tw.fatigue_monitor/mobile_runtime';
  static const eventChannelName = 'tw.fatigue_monitor/mobile_runtime/events';

  static const getPermissionState = 'getPermissionState';
  static const requestPermission = 'requestPermission';
  static const startCamera = 'startCamera';
  static const stopCamera = 'stopCamera';
  static const getModelState = 'getModelState';
  static const loadModel = 'loadModel';
  static const unloadModel = 'unloadModel';
  static const getForegroundState = 'getForegroundState';
  static const setForegroundState = 'setForegroundState';
  static const readLocal = 'readLocal';
  static const writeLocal = 'writeLocal';
  static const deleteLocal = 'deleteLocal';
  static const dispose = 'dispose';

  static const cameraFrameEvent = 'camera_frame';
  static const foregroundEvent = 'foreground';
}

class CameraConfiguration {
  const CameraConfiguration({
    required this.width,
    required this.height,
    required this.fps,
    this.frontFacing = true,
  });

  final int width;
  final int height;
  final int fps;
  final bool frontFacing;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'width': width,
        'height': height,
        'fps': fps,
        'front_facing': frontFacing,
      };
}

/// A platform adapter must provide monotonic frame timestamps in microseconds.
class CameraFrame {
  CameraFrame({
    required Uint8List bytes,
    required this.width,
    required this.height,
    required this.timestampMicros,
    required this.format,
  }) : bytes = Uint8List.fromList(bytes);

  final Uint8List bytes;
  final int width;
  final int height;
  final int timestampMicros;
  final CameraPixelFormat format;

  static CameraFrame? fromPayload(dynamic raw) {
    if (raw is! Map) return null;
    final width = _positiveInt(raw['width']);
    final height = _positiveInt(raw['height']);
    final timestamp = _nonNegativeInt(
      raw['timestamp_micros'] ?? raw['timestampMicros'],
    );
    final bytes = _decodeBytes(raw['bytes']);
    final format = cameraPixelFormatFromName(raw['format']);
    if (width == null ||
        height == null ||
        timestamp == null ||
        bytes == null ||
        format == null) {
      return null;
    }
    return CameraFrame(
      bytes: bytes,
      width: width,
      height: height,
      timestampMicros: timestamp,
      format: format,
    );
  }
}

String enumName(Object value) => value.toString().split('.').last;

String runtimePermissionName(RuntimePermission permission) =>
    enumName(permission);

String permissionStateName(PermissionState state) => enumName(state);

String foregroundStateName(ForegroundState state) => enumName(state);

String modelRuntimeStateName(ModelRuntimeState state) => enumName(state);

String cameraPixelFormatName(CameraPixelFormat format) => enumName(format);

PermissionState permissionStateFromName(dynamic raw) =>
    PermissionState.values.byName(raw is String ? raw : 'unknown');

ForegroundState foregroundStateFromName(dynamic raw) =>
    ForegroundState.values.byName(raw is String ? raw : 'terminated');

ModelRuntimeState modelRuntimeStateFromName(dynamic raw) =>
    ModelRuntimeState.values.byName(raw is String ? raw : 'failed');

CameraPixelFormat? cameraPixelFormatFromName(dynamic raw) {
  if (raw is! String) return null;
  for (final format in CameraPixelFormat.values) {
    if (format.name == raw) return format;
  }
  return null;
}

int? _positiveInt(dynamic value) {
  final parsed = _asInt(value);
  return parsed != null && parsed > 0 ? parsed : null;
}

int? _nonNegativeInt(dynamic value) {
  final parsed = _asInt(value);
  return parsed != null && parsed >= 0 ? parsed : null;
}

int? _asInt(dynamic value) {
  if (value is int) return value;
  if (value is num && value == value.roundToDouble()) return value.toInt();
  return null;
}

Uint8List? _decodeBytes(dynamic value) {
  if (value is Uint8List) return Uint8List.fromList(value);
  if (value is List) {
    try {
      final values = value.map((item) => _asInt(item)).toList();
      if (values.any((item) => item == null || item < 0 || item > 255)) {
        return null;
      }
      return Uint8List.fromList(values.cast<int>());
    } catch (_) {
      return null;
    }
  }
  return null;
}

/// Native Android/iOS implementations will satisfy this contract through a
/// Flutter plugin without changing the shared UI or analysis data models.
abstract interface class MobileRuntimeAdapter {
  PlatformCapabilities get platform;

  bool get isAvailable;

  Stream<CameraFrame> get cameraFrames;

  Stream<ForegroundState> get foregroundStates;

  Future<PermissionState> permissionState(RuntimePermission permission);

  Future<PermissionState> requestPermission(RuntimePermission permission);

  Future<void> startCamera(CameraConfiguration configuration);

  Future<void> stopCamera();

  ModelRuntimeState get modelState;

  Future<ModelRuntimeState> loadModel(String modelId);

  Future<void> unloadModel();

  ForegroundState get foregroundState;

  Future<void> setForegroundState(ForegroundState state);

  Future<String?> readLocal(String key);

  Future<void> writeLocal(String key, String value);

  Future<void> deleteLocal(String key);

  Future<void> dispose();
}

/// Safe default until a native inference plugin is installed for the platform.
class UnsupportedMobileRuntimeAdapter implements MobileRuntimeAdapter {
  UnsupportedMobileRuntimeAdapter(this.platform)
      : _cameraFrames = StreamController<CameraFrame>.broadcast(),
        _foregroundStates = StreamController<ForegroundState>.broadcast();

  @override
  final PlatformCapabilities platform;

  final StreamController<CameraFrame> _cameraFrames;
  final StreamController<ForegroundState> _foregroundStates;
  ForegroundState _foregroundState = ForegroundState.terminated;

  @override
  bool get isAvailable => false;

  @override
  Stream<CameraFrame> get cameraFrames => _cameraFrames.stream;

  @override
  Stream<ForegroundState> get foregroundStates => _foregroundStates.stream;

  @override
  Future<PermissionState> permissionState(RuntimePermission permission) {
    return Future<PermissionState>.error(
      UnsupportedPlatformRuntimeError(platform),
    );
  }

  @override
  Future<PermissionState> requestPermission(RuntimePermission permission) {
    return Future<PermissionState>.error(
      UnsupportedPlatformRuntimeError(platform),
    );
  }

  @override
  Future<void> startCamera(CameraConfiguration configuration) {
    return Future<void>.error(UnsupportedPlatformRuntimeError(platform));
  }

  @override
  Future<void> stopCamera() async {}

  @override
  ModelRuntimeState get modelState => ModelRuntimeState.unloaded;

  @override
  Future<ModelRuntimeState> loadModel(String modelId) {
    return Future<ModelRuntimeState>.error(
      UnsupportedPlatformRuntimeError(platform),
    );
  }

  @override
  Future<void> unloadModel() async {}

  @override
  ForegroundState get foregroundState => _foregroundState;

  @override
  Future<void> setForegroundState(ForegroundState state) async {
    _foregroundState = state;
    if (!_foregroundStates.isClosed) _foregroundStates.add(state);
  }

  @override
  Future<String?> readLocal(String key) {
    return Future<String?>.error(UnsupportedPlatformRuntimeError(platform));
  }

  @override
  Future<void> writeLocal(String key, String value) {
    return Future<void>.error(UnsupportedPlatformRuntimeError(platform));
  }

  @override
  Future<void> deleteLocal(String key) async {}

  @override
  Future<void> dispose() async {
    await _cameraFrames.close();
    await _foregroundStates.close();
  }
}

/// A MethodChannel adapter for the Android/iOS contract boundary.
///
/// The adapter remains fail-closed when the native plugin is missing or reports
/// that inference is unavailable. It never falls back to the desktop engine.
class MobileRuntimeChannelAdapter implements MobileRuntimeAdapter {
  MobileRuntimeChannelAdapter(
    this.platform, {
    MethodChannel? methodChannel,
    EventChannel? eventChannel,
    Stream<dynamic>? eventStream,
  })  : _methodChannel = methodChannel ??
            const MethodChannel(MobileRuntimeChannelContract.methodChannelName),
        _cameraFrames = StreamController<CameraFrame>.broadcast(),
        _foregroundStates = StreamController<ForegroundState>.broadcast() {
    try {
      final stream = eventStream ??
          (eventChannel ??
                  const EventChannel(
                    MobileRuntimeChannelContract.eventChannelName,
                  ))
              .receiveBroadcastStream();
      _eventSubscription = stream.listen(
        _handleEvent,
        onError: (_, __) {},
      );
    } catch (_) {
      // A desktop unit test or web host may not have a ServicesBinding.
      _eventSubscription = const Stream<dynamic>.empty().listen((_) {});
    }
  }

  @override
  final PlatformCapabilities platform;

  final MethodChannel _methodChannel;
  final StreamController<CameraFrame> _cameraFrames;
  final StreamController<ForegroundState> _foregroundStates;
  late final StreamSubscription<dynamic> _eventSubscription;
  ForegroundState _foregroundState = ForegroundState.terminated;
  ModelRuntimeState _modelState = ModelRuntimeState.unloaded;
  bool _disposed = false;

  @override
  bool get isAvailable => platform.nativeInferenceReady && !_disposed;

  @override
  Stream<CameraFrame> get cameraFrames => _cameraFrames.stream;

  @override
  Stream<ForegroundState> get foregroundStates => _foregroundStates.stream;

  @override
  Future<PermissionState> permissionState(RuntimePermission permission) async {
    final value = await _invoke<dynamic>(
      MobileRuntimeChannelContract.getPermissionState,
      <String, dynamic>{'permission': runtimePermissionName(permission)},
    );
    return _parsePermissionState(value);
  }

  @override
  Future<PermissionState> requestPermission(
      RuntimePermission permission) async {
    final value = await _invoke<dynamic>(
      MobileRuntimeChannelContract.requestPermission,
      <String, dynamic>{'permission': runtimePermissionName(permission)},
    );
    return _parsePermissionState(value);
  }

  @override
  Future<void> startCamera(CameraConfiguration configuration) async {
    if (configuration.width <= 0 ||
        configuration.height <= 0 ||
        configuration.fps <= 0) {
      throw ArgumentError('Camera dimensions and fps must be positive.');
    }
    await _invoke<void>(
      MobileRuntimeChannelContract.startCamera,
      configuration.toJson(),
    );
  }

  @override
  Future<void> stopCamera() async {
    await _invoke<void>(MobileRuntimeChannelContract.stopCamera);
  }

  @override
  ModelRuntimeState get modelState => _modelState;

  @override
  Future<ModelRuntimeState> loadModel(String modelId) async {
    if (modelId.trim().isEmpty) throw ArgumentError.value(modelId, 'modelId');
    _modelState = ModelRuntimeState.loading;
    try {
      final value = await _invoke<dynamic>(
        MobileRuntimeChannelContract.loadModel,
        <String, dynamic>{'model_id': modelId},
      );
      _modelState = modelRuntimeStateFromName(value);
      return _modelState;
    } catch (_) {
      _modelState = ModelRuntimeState.failed;
      rethrow;
    }
  }

  @override
  Future<void> unloadModel() async {
    await _invoke<void>(MobileRuntimeChannelContract.unloadModel);
    _modelState = ModelRuntimeState.unloaded;
  }

  @override
  ForegroundState get foregroundState => _foregroundState;

  @override
  Future<void> setForegroundState(ForegroundState state) async {
    await _invoke<void>(
      MobileRuntimeChannelContract.setForegroundState,
      <String, dynamic>{'state': foregroundStateName(state)},
    );
    _publishForegroundState(state);
  }

  @override
  Future<String?> readLocal(String key) async {
    if (key.isEmpty) throw ArgumentError.value(key, 'key');
    final value = await _invoke<dynamic>(
      MobileRuntimeChannelContract.readLocal,
      <String, dynamic>{'key': key},
    );
    return value is String ? value : null;
  }

  @override
  Future<void> writeLocal(String key, String value) async {
    if (key.isEmpty) throw ArgumentError.value(key, 'key');
    await _invoke<void>(
      MobileRuntimeChannelContract.writeLocal,
      <String, dynamic>{'key': key, 'value': value},
    );
  }

  @override
  Future<void> deleteLocal(String key) async {
    if (key.isEmpty) throw ArgumentError.value(key, 'key');
    await _invoke<void>(
      MobileRuntimeChannelContract.deleteLocal,
      <String, dynamic>{'key': key},
    );
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await _eventSubscription.cancel();
    try {
      await _methodChannel.invokeMethod<void>(
        MobileRuntimeChannelContract.dispose,
      );
    } on MissingPluginException {
      // The native side may not be registered on web or desktop test hosts.
    } on PlatformException {
      // Disposal is best-effort; stream ownership still must be released.
    }
    await _cameraFrames.close();
    await _foregroundStates.close();
  }

  Future<T?> _invoke<T>(String method, [dynamic arguments]) async {
    if (_disposed) throw StateError('Mobile runtime adapter is disposed.');
    try {
      return await _methodChannel.invokeMethod<T>(method, arguments);
    } on MissingPluginException {
      throw UnsupportedPlatformRuntimeError(platform);
    } on PlatformException catch (error) {
      if (error.code == 'runtime_unavailable' ||
          error.code == 'unavailable' ||
          error.code == 'not_implemented') {
        throw UnsupportedPlatformRuntimeError(platform);
      }
      throw MobileRuntimeChannelError(
        code: error.code,
        message: error.message ?? 'Mobile runtime channel failed.',
        details: error.details,
      );
    }
  }

  void _handleEvent(dynamic raw) {
    if (raw is! Map) return;
    final type = raw['type'];
    if (type == MobileRuntimeChannelContract.cameraFrameEvent ||
        raw.containsKey('bytes')) {
      final frame = CameraFrame.fromPayload(raw);
      if (frame != null && !_cameraFrames.isClosed) _cameraFrames.add(frame);
      return;
    }
    if (type == MobileRuntimeChannelContract.foregroundEvent ||
        raw.containsKey('state')) {
      try {
        _publishForegroundState(foregroundStateFromName(raw['state']));
      } catch (_) {
        // Ignore malformed native lifecycle events.
      }
    }
  }

  void _publishForegroundState(ForegroundState state) {
    if (_foregroundState == state) return;
    _foregroundState = state;
    if (!_foregroundStates.isClosed) _foregroundStates.add(state);
  }

  PermissionState _parsePermissionState(dynamic value) {
    try {
      return permissionStateFromName(value);
    } catch (_) {
      return PermissionState.unknown;
    }
  }
}

class MobileRuntimeChannelError extends StateError {
  MobileRuntimeChannelError({
    required this.code,
    required String message,
    this.details,
  }) : super(message);

  final String code;
  final dynamic details;
}

MobileRuntimeAdapter createMobileRuntime(PlatformCapabilities platform) {
  if (platform.platform == AppPlatform.android ||
      platform.platform == AppPlatform.ios) {
    return MobileRuntimeChannelAdapter(platform);
  }
  return UnsupportedMobileRuntimeAdapter(platform);
}
