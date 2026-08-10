import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('overlay opacity preserves the 0..100 contract', () {
    expect(overlayOpacityPercent({'overlay_opacity': 0}), 0);
    expect(overlayOpacityPercent({'overlay_opacity': 150}), 100);
    expect(overlayOpacityPercent({}), 55);
  });

  testWidgets('overlay shell renders without a backend frame', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: OverlayShell()),
    );

    expect(find.text('NCFD 監測 Overlay'), findsOneWidget);
  });
}
