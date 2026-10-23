import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _pumpDashboard(
  WidgetTester tester, {
  required bool focus,
  required Future<void> Function(String, [Map<String, dynamic>?]) onCommand,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: DashboardView(
          metrics: const <String, dynamic>{
            'status': 'Ready',
            'stress_bpm': 72,
            'stress_sqi': 0.9,
            'fps': 30,
          },
          engineState: <String, dynamic>{
            'monitor_focus': focus,
            'pipeline_running': true,
            'cameras': <Map<String, dynamic>>[
              <String, dynamic>{'index': 0, 'label': 'Test camera'},
            ],
            'selected_camera_index': 0,
          },
          previewFrames: const Stream<String>.empty(),
          connected: true,
          busy: false,
          error: null,
          onRetry: () async {},
          onCommand: onCommand,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'recording finalization prevents restarting until ownership releases',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SingleChildScrollView(
                child: DesktopControlPanel(state: const {
      'pipeline_running': true,
      'recording': false,
      'recording_finalizing': true,
    }, busy: false, onCommand: (_, [__]) async {})))));
    final button = find.widgetWithText(OutlinedButton, '記錄收尾中…');
    expect(button, findsOneWidget);
    expect(tester.widget<OutlinedButton>(button).onPressed, isNull);
    expect(find.text('開始記錄'), findsNothing);
  });

  test('fatigue presentation maps severity and prioritizes the fusion result',
      () {
    for (final (status, label) in [
      ('LOW_VIGILANCE', '輕度疲勞'),
      ('DROWSY', '中度疲勞'),
      ('CRITICAL', '高度疲勞'),
      ('MICROSLEEP', '極度危險'),
    ]) {
      final (text, color) = fatiguePresentation({'status': status});
      expect(text, label);
      expect(color, isNot(kAccent));
    }
    expect(fatiguePresentation({'status': 'OK', 'fusion_state_zh': '極度危險'}).$1,
        '極度危險');
    expect(
        fatiguePresentation({'status': 'MICROSLEEP', 'fusion_state_zh': '清醒'})
            .$1,
        '極度危險');
    expect(
        fatiguePresentation({'status': 'CRITICAL', 'fusion_state_zh': '清醒'}).$1,
        '高度疲勞');
    expect(
        fatiguePresentation({'status': 'CALIBRATING', 'fusion_state_zh': '清醒'})
            .$1,
        '校準中');
    expect(
        fatiguePresentation({'status': 'NO_FACE', 'fusion_state_zh': '清醒'}).$1,
        '未偵測到臉部');
  });

  testWidgets('focus dashboard shows the fusion severity', (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: DashboardView(
      metrics: const {'status': 'OK', 'fusion_state_zh': '極度危險'},
      engineState: const {'monitor_focus': true, 'pipeline_running': true},
      previewFrames: const Stream<String>.empty(),
      connected: true,
      busy: false,
      error: null,
      onRetry: () async {},
      onCommand: (_, [__]) async {},
    ))));
    expect(find.text('極度危險'), findsOneWidget);
  });
  testWidgets('split dashboard keeps controls and metric sections',
      (tester) async {
    await _pumpDashboard(tester, focus: false, onCommand: (_, [__]) async {});

    expect(find.text('SYSTEM CONTROL'), findsOneWidget);
    expect(find.textContaining('基準測試'), findsNothing);
    expect(find.text('PHYSIOLOGY / rPPG'), findsOneWidget);
    expect(find.text('CURRENT STATE'), findsOneWidget);
    expect(find.byIcon(Icons.fullscreen_exit), findsNothing);
  });

  testWidgets('focus dashboard hides controls and exits through monitor.layout',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _pumpDashboard(
      tester,
      focus: true,
      onCommand: (command, [args]) async => calls.add((command, args)),
    );

    expect(find.text('FOCUS PREVIEW'), findsOneWidget);
    expect(find.text('LIVE CAMERA'), findsOneWidget);
    expect(find.text('SYSTEM CONTROL'), findsNothing);
    expect(find.text('PHYSIOLOGY / rPPG'), findsNothing);
    expect(find.text('CURRENT STATE'), findsNothing);

    await tester.tap(find.byIcon(Icons.fullscreen_exit));
    await tester.pump();

    expect(calls, hasLength(1));
    expect(calls.single.$1, 'monitor.layout');
    expect(calls.single.$2?['focus'], isFalse);
  });
}
