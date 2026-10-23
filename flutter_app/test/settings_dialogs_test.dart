import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _openDialog(
  WidgetTester tester,
  String label,
  List<(String, Map<String, dynamic>?)> calls, {
  Size size = const Size(360, 640),
  double textScale = 2.25,
  Map<String, dynamic> state = const {},
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context)
          .copyWith(textScaler: TextScaler.linear(textScale)),
      child: child!,
    ),
    home: Scaffold(
      body: SettingsView(
        state: state,
        busy: false,
        onCommand: (command, [args]) async => calls.add((command, args)),
      ),
    ),
  ));
  await tester.ensureVisible(find.text(label));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
  expect(find.byType(AlertDialog), findsOneWidget);
  expect(tester.takeException(), isNull);
}

void main() {
  testWidgets(
      'profile fields and apply stay reachable in a small large-text dialog',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _openDialog(tester, '使用者資料', calls,
        size: const Size(320, 560),
        state: const {
          'user_profile': {'age': 40, 'height_cm': 180, 'weight_kg': 90.0},
        });

    await tester.ensureVisible(find.text('BMI 27.8'));
    expect(tester.takeException(), isNull);
    final weight = find.byType(TextField).at(2);
    await tester.ensureVisible(weight);
    await tester.enterText(weight, '85');
    await tester.ensureVisible(find.text('套用使用者資料'));
    await tester.tap(find.text('套用使用者資料'));
    await tester.pumpAndSettle();

    expect(calls.single.$1, 'user_profile.configure');
    expect(calls.single.$2?['user_profile'],
        {'age': 40, 'height_cm': 180, 'weight_kg': 85.0});
    expect(tester.takeException(), isNull);
  });

  testWidgets('all hotkey fields and cancel remain reachable with large text',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _openDialog(tester, '快捷鍵', calls,
        size: const Size(360, 500),
        state: const {
          'hotkey_registration': {'supported': true}
        });

    final lastField = find.byType(TextField).last;
    await tester.ensureVisible(lastField);
    await tester.enterText(lastField, 'Alt+6');
    expect(tester.takeException(), isNull);
    expect(find.text('套用快捷鍵').hitTestable(), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, '取消'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(calls, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow alarm scenarios keep draft testing and apply payloads',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _openDialog(tester, '警報器', calls,
        size: const Size(400, 640),
        textScale: 1.6,
        state: const {
          'alarm': {
            'enabled': true,
            'volume': 70,
            'trigger_delay_sec': 1.0,
            'repeat_interval_sec': 20.0,
          },
        });

    final delay = find.byKey(const ValueKey('alarm-delay'));
    await tester.ensureVisible(delay);
    await tester.enterText(delay, '0.5');
    await tester.ensureVisible(find.byTooltip('測試 critical'));
    await tester.tap(find.byTooltip('測試 critical'));
    await tester.pumpAndSettle();
    expect(calls.single.$1, 'alarm.test');
    expect(calls.single.$2?['scenario'], 'critical');
    expect((calls.single.$2?['alarm'] as Map)['trigger_delay_sec'], 0.5);
    expect(tester.takeException(), isNull);

    await tester.ensureVisible(find.text('套用警報設定'));
    await tester.tap(find.text('套用警報設定'));
    await tester.pumpAndSettle();
    expect(calls.last.$1, 'alarm.configure');
    expect((calls.last.$2?['alarm'] as Map)['volume'], 70);
    expect((calls.last.$2?['alarm'] as Map)['scenarios'], hasLength(4));
    expect(tester.takeException(), isNull);
  });

  testWidgets('reset confirmation remains cancellable in a narrow dialog',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await _openDialog(tester, '全部重設', calls, size: const Size(320, 480));

    expect(find.text('確認重設').hitTestable(), findsWidgets);
    await tester.tap(find.widgetWithText(TextButton, '取消'));
    await tester.pumpAndSettle();
    expect(calls, isEmpty);
    expect(find.byType(AlertDialog), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
