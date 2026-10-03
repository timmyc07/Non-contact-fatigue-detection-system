import 'dart:async';
import 'dart:typed_data';

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

MobileRuntimeAdapter createMobileRuntime(PlatformCapabilities platform) {
  return UnsupportedMobileRuntimeAdapter(platform);
}
