import 'package:fatigue_monitor_ui/models/backend_contract.dart';
import 'package:fatigue_monitor_ui/models/mobile_runtime_contract.dart';
import 'package:fatigue_monitor_ui/models/platform_contract.dart';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('desktop and mobile capabilities stay fail-closed', () {
    expect(PlatformCapabilities.macos.canStartMonitoring, isTrue);
    expect(PlatformCapabilities.macos.supports('tauri_shell'), isTrue);
    expect(PlatformCapabilities.macos.supports('python_sidecar'), isTrue);
    expect(PlatformCapabilities.macos.supportsAny(const [
      PlatformCapabilityNames.globalHotkey,
      PlatformCapabilityNames.desktopOverlay,
    ]), isTrue);
    expect(PlatformCapabilities.android.canStartMonitoring, isFalse);
    expect(PlatformCapabilities.android.isMobile, isTrue);
    expect(PlatformCapabilities.android.supports('tauri_shell'), isFalse);
    expect(PlatformCapabilities.android.supports('python_sidecar'), isFalse);
    expect(PlatformCapabilities.ios.requiresNativeRuntime, isTrue);
    expect(PlatformCapabilities.android.unavailableReason, contains('原生推論'));
  });

  test('platform detection keeps web desktop separate from mobile', () {
    expect(
      currentPlatformCapabilities(
              isWeb: true,
              isAndroid: true,
              isIos: false,
              isWindows: false,
              isMacos: false,
              isLinux: false)
          .platform,
      AppPlatform.webDesktop,
    );
    expect(
      currentPlatformCapabilities(
              isWeb: false,
              isAndroid: true,
              isIos: false,
              isWindows: false,
              isMacos: false,
              isLinux: false)
          .platform,
      AppPlatform.android,
    );
  });

  test('typed contracts preserve unknown backend fields', () {
    final metrics = MetricsSnapshot.fromJson(const {
      'fps': 30,
      'future_metric': 'kept',
    });
    expect(metrics.number('fps'), 30);
    expect(metrics.toJson()['future_metric'], 'kept');

    final recording = RecordingMetadata.fromJson(const {
      'path': '/tmp/a.db',
      'session_name': 'demo',
      'duration_str': '1 分 2 秒',
      'record_count': 4.8,
      'future_field': true,
    });
    expect(recording.path, '/tmp/a.db');
    expect(recording.recordCount, 4);
    expect(recording.toJson()['future_field'], isTrue);
  });

  test('structured and legacy errors share one contract', () {
    final structured = ApiError.fromPayload(
      const {
        'error': {'code': 'invalid_settings', 'message': 'Bad value'}
      },
      400,
    );
    final legacy =
        ApiError.fromPayload(const {'error': 'Engine is starting.'}, 503);
    expect(structured.code, 'invalid_settings');
    expect(structured.message, 'Bad value');
    expect(legacy.code, 'http_503');
    expect(legacy.message, 'Engine is starting.');
  });

  test('unsupported mobile runtime fails closed without desktop fallback',
      () async {
    final adapter =
        UnsupportedMobileRuntimeAdapter(PlatformCapabilities.android);
    expect(adapter.isAvailable, isFalse);
    expect(adapter.platform.platform, AppPlatform.android);
    expect(adapter.modelState, ModelRuntimeState.unloaded);

    await expectLater(
      adapter.startCamera(
          const CameraConfiguration(width: 640, height: 480, fps: 30)),
      throwsA(isA<UnsupportedPlatformRuntimeError>()),
    );
    await expectLater(
      adapter.loadModel('face_landmarker'),
      throwsA(isA<UnsupportedPlatformRuntimeError>()),
    );
    await expectLater(
      adapter.requestPermission(RuntimePermission.camera),
      throwsA(isA<UnsupportedPlatformRuntimeError>()),
    );
    await adapter.dispose();
  });

  test('mobile frame contract preserves bytes and timing metadata', () {
    final frame = CameraFrame(
      bytes: Uint8List.fromList(const [1, 2, 3]),
      width: 2,
      height: 1,
      timestampMicros: 1234,
      format: CameraPixelFormat.rgba8888,
    );
    expect(frame.bytes, orderedEquals(const [1, 2, 3]));
    expect(frame.timestampMicros, 1234);
    expect(frame.format, CameraPixelFormat.rgba8888);
  });

  test('unsupported adapter still reports lifecycle state changes', () async {
    final adapter = UnsupportedMobileRuntimeAdapter(PlatformCapabilities.ios);
    final states = <ForegroundState>[];
    final subscription = adapter.foregroundStates.listen(states.add);

    await adapter.setForegroundState(ForegroundState.active);
    expect(adapter.foregroundState, ForegroundState.active);
    expect(states, contains(ForegroundState.active));

    await subscription.cancel();
    await adapter.dispose();
  });
}
