import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('dashboard remains usable with narrow and enlarged text layouts',
      (tester) async {
    addTearDown(() => tester.binding.setSurfaceSize(null));
    for (final (width, scale) in [(360.0, 1.6), (760.0, 2.25), (1024.0, 1.0)]) {
      await tester.binding.setSurfaceSize(Size(width, 720));
      await tester.pumpWidget(MaterialApp(
          home: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(scale)),
        child: Scaffold(
            body: DashboardView(
          metrics: const {'status': 'MICROSLEEP', 'fusion_state_zh': '清醒'},
          engineState: const {
            'cameras': [
              {
                'index': 0,
                'label': 'External USB Camera with a long device name'
              }
            ],
            'selected_camera_index': 0,
          },
          previewFrames: const Stream<String>.empty(),
          connected: true,
          busy: false,
          error: null,
          onRetry: () async {},
          onCommand: (_, [__]) async {},
        )),
      )));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: '$width / $scale');
      expect(find.text('極度危險'), findsOneWidget);
      expect(find.text('開始監測'), findsOneWidget);
      await tester.ensureVisible(find.text('自動採集').first);
      await tester.tap(find.text('自動採集').first);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull,
          reason: 'expanded $width / $scale');
    }
  });

  testWidgets('window controls do not trigger window dragging', (tester) async {
    var drags = 0;
    var closes = 0;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: AppTitleBar(
      onDrag: () => drags++,
      onMinimize: () {},
      onMaximize: () {},
      onClose: () => closes++,
    ))));
    await tester.tap(find.byTooltip('關閉'));
    await tester.pump();
    expect(closes, 1);
    expect(drags, 0);
  });

  testWidgets('navigation reflects connection and selected destination',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: NavigationRailPanel(
      selectedIndex: 2,
      onSelected: (_) {},
      alwaysOnTop: false,
      onAlwaysOnTop: () {},
    ))));
    expect(find.text('等待引擎連線'), findsOneWidget);
    expect(find.text('ENGINE ONLINE'), findsNothing);
    expect(
        tester.getSemantics(find.bySemanticsLabel('歷史回放').first),
        matchesSemantics(
          isSelected: true,
          hasSelectedState: true,
          isButton: true,
          isFocusable: true,
          label: '歷史回放',
          hasTapAction: true,
          hasFocusAction: true,
        ));
    semantics.dispose();
  });
}
