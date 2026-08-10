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
          previewFrame: null,
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
  testWidgets('split dashboard keeps controls and metric sections',
      (tester) async {
    await _pumpDashboard(tester, focus: false, onCommand: (_, [__]) async {});

    expect(find.text('SYSTEM CONTROL'), findsOneWidget);
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
