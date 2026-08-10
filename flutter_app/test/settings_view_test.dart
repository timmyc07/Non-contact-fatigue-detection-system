import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('overlay opacity sends one command when dragging ends', (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SettingsView(
            state: const <String, dynamic>{'overlay_opacity': 55},
            busy: false,
            onCommand: (command, [args]) async {
              calls.add((command, args));
            },
          ),
        ),
      ),
    );

    final slider = find.byType(Slider);
    await tester.ensureVisible(slider);
    await tester.pumpAndSettle();
    await tester.drag(slider, const Offset(120, 0));
    await tester.pumpAndSettle();

    final opacityCalls = calls.where((call) => call.$1 == 'overlay.configure').toList();
    expect(opacityCalls, hasLength(1));
    expect(opacityCalls.single.$2?['opacity'], greaterThan(55));
  });
}
