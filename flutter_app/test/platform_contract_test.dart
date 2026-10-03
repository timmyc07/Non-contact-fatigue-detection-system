import 'package:fatigue_monitor_ui/models/backend_contract.dart';
import 'package:fatigue_monitor_ui/models/platform_contract.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('desktop and mobile capabilities stay fail-closed', () {
    expect(PlatformCapabilities.macos.canStartMonitoring, isTrue);
    expect(PlatformCapabilities.macos.supports('tauri_shell'), isTrue);
    expect(PlatformCapabilities.android.canStartMonitoring, isFalse);
    expect(PlatformCapabilities.ios.requiresNativeRuntime, isTrue);
    expect(PlatformCapabilities.android.unavailableReason, contains('原生推論'));
  });

  test('platform detection keeps web desktop separate from mobile', () {
    expect(
      currentPlatformCapabilities(isWeb: true, isAndroid: true, isIos: false)
          .platform,
      AppPlatform.webDesktop,
    );
    expect(
      currentPlatformCapabilities(isWeb: false, isAndroid: true, isIos: false)
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
}
