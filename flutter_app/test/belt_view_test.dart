import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _metrics = <String, dynamic>{
  'belt_state': 'connected',
  'belt_device_name': 'Polar H10 — 長時間監測用心跳帶裝置',
  'belt_device_address': 'AE12BC34-DE56-78FA-9012-ABCDEF345678',
  'belt_sensor_location': '胸部',
  'belt_bpm': 72.4,
  'belt_signal_age_sec': 0.3,
  'belt_contact_supported': true,
  'belt_contact_detected': true,
  'belt_battery': 81,
  'belt_rssi': -52,
  'belt_rr_count': 512,
  'belt_notifications': 64,
  'belt_connected_duration_sec': 125,
  'belt_hrv_rmssd': 33.1,
  'belt_hrv_sdnn': 42.3,
  'belt_hrv_lf_hf': 1.234,
  'calib_offset_bpm': 1.2,
  'calib_raw_residual_bpm': 3.4,
  'calib_residual_bpm': 2.2,
  'calib_confidence': 0.88,
  'calib_converged': true,
  'calib_pairs_used': 99,
};

Future<void> _showBelt(
  WidgetTester tester, {
  Map<String, dynamic> state = const {},
  Map<String, dynamic> metrics = _metrics,
  bool busy = false,
  Future<void> Function(String, [Map<String, dynamic>?])? onCommand,
}) async {
  await tester.pumpWidget(MaterialApp(
      home: Scaffold(
          body: ChestBeltView(
              metrics: metrics,
              state: state,
              busy: busy,
              onCommand: onCommand ?? (_, [__]) async {}))));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'belt details and HRV remain readable in a narrow large text view',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(360, 780);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(MaterialApp(
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(1.8)),
            child: child!),
        home: Scaffold(
            body: ChestBeltView(
                metrics: _metrics,
                state: const {
                  'belt_calibration': true,
                  'belt_config': {
                    'name_prefix': 'Polar H10 — 配對用裝置名稱前綴',
                    'address': 'AE12BC34-DE56-78FA-9012-ABCDEF345678',
                    'rppg_param_tuning_enabled': true,
                    'capture_enabled': false,
                  },
                },
                busy: false,
                onCommand: (_, [__]) async {}))));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('已連線'), findsOneWidget);
    for (final value in ['72', '0.3', '已接觸', '81', '-52', '512', '64', '2.1']) {
      expect(find.text(value), findsOneWidget);
    }
    expect(find.text('RMSSD 33.1 ms'), findsOneWidget);
    expect(find.text('SDNN 42.3 ms'), findsOneWidget);
    expect(find.text('LF/HF 1.23'), findsOneWidget);
    expect(find.text('1.2 BPM'), findsOneWidget);
    expect(find.text('3.4 BPM'), findsOneWidget);
    expect(find.text('2.2 BPM'), findsOneWidget);
    expect(find.text('0.88 / 已收斂'), findsOneWidget);
    expect(find.text('99'), findsOneWidget);
    expect(find.text('Polar H10 — 配對用裝置名稱前綴'), findsOneWidget);
    expect(find.textContaining('config/hr_belt.json'), findsNothing);

    await tester.ensureVisible(find.text('LF/HF 1.23'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('設備偏好'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    for (final text in tester.widgetList<Text>(find.byType(Text))) {
      expect(text.overflow, isNot(TextOverflow.ellipsis));
    }
  });

  testWidgets(
      'wide belt view uses the available space for readings and details',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1440, 900);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await _showBelt(tester);
    final calibration = tester.getTopLeft(find.text('rPPG 校準'));
    final preferences = tester.getTopLeft(find.text('設備偏好'));
    expect(preferences.dy, calibration.dy);
    expect(preferences.dx, greaterThan(calibration.dx));
    expect(tester.getTopLeft(find.text('心率')).dy,
        tester.getTopLeft(find.text('擷取訊號')).dy);
    expect(tester.takeException(), isNull);
  });

  testWidgets('enabling requires both monitoring and rPPG', (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    for (final (running, rppg) in [
      (false, false),
      (false, true),
      (true, false),
      (true, true),
    ]) {
      await _showBelt(tester,
          state: {'pipeline_running': running, 'rppg_enabled': rppg},
          onCommand: (command, [args]) async => calls.add((command, args)));
      final button = tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, '啟用心跳帶'));
      if (running && rppg) {
        expect(button.onPressed, isNotNull);
        await tester.tap(find.text('啟用心跳帶'));
        expect(calls.single.$1, 'preferences.configure');
        expect(calls.single.$2, {'belt_calibration': true});
      } else {
        expect(button.onPressed, isNull);
      }
    }
  });

  testWidgets('an enabled belt can still be stopped after monitoring stops',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _showBelt(tester,
        state: const {
          'belt_calibration': true,
          'pipeline_running': false,
          'rppg_enabled': false,
        },
        onCommand: (command, [args]) async => calls.add((command, args)));
    await tester.tap(find.text('停用心跳帶'));
    expect(calls.single.$1, 'preferences.configure');
    expect(calls.single.$2, {'belt_calibration': false});
  });

  testWidgets('busy belt actions cannot send another command', (tester) async {
    for (final enabled in [false, true]) {
      await _showBelt(tester, busy: true, state: {
        'belt_calibration': enabled,
        'pipeline_running': true,
        'rppg_enabled': true,
      });
      final button = tester.widget<FilledButton>(
          find.widgetWithText(FilledButton, enabled ? '停用心跳帶' : '啟用心跳帶'));
      expect(button.onPressed, isNull);
    }
  });

  testWidgets('stale signals override connected presentation', (tester) async {
    await _showBelt(tester,
        metrics: {..._metrics, 'belt_stale': true},
        state: const {'belt_calibration': true});
    expect(find.text('訊號停滯'), findsOneWidget);
    expect(find.text('已連線'), findsNothing);
  });
}
