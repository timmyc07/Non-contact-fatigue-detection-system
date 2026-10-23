import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('history shows relative elapsed time and later pages',
      (tester) async {
    final pages = <int>[];
    await tester.binding.setSurfaceSize(const Size(1200, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: PlaybackView(
      recordings: const [],
      selected: const {'session_name': 'test'},
      rows: const [
        {'timestamp': 1792641605.0, 'status': 'OK'}
      ],
      offset: 200,
      total: 401,
      startTimestamp: 1792641600.0,
      onPage: (offset) async => pages.add(offset),
      busy: false,
      state: const {},
      onCommand: (_, [__]) async {},
      onRefresh: () async {},
      onOpen: (_) async {},
      onClose: () {},
      onPickReplayFolder: () async => null,
    ))));
    expect(find.text('5.0 s'), findsOneWidget);
    expect(find.text('201–201 / 401 筆'), findsOneWidget);
    await tester.tap(find.text('下一頁'));
    expect(pages, [201]);
    await tester.tap(find.text('上一頁'));
    expect(pages, [201, 0]);
  });

  testWidgets('folder picker selection configures the replay path',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    var pickerCalls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PlaybackView(
            recordings: const [],
            selected: null,
            rows: const [],
            offset: 0,
            total: 0,
            startTimestamp: 0,
            onPage: (_) async {},
            busy: false,
            state: const <String, dynamic>{},
            onCommand: (command, [args]) async => calls.add((command, args)),
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async {
              pickerCalls += 1;
              return r'C:\datasets\UTA-RLDD';
            },
          ),
        ),
      ),
    );

    await tester.tap(find.byTooltip('選擇資料夾'));
    await tester.pumpAndSettle();

    expect(pickerCalls, 1);
    expect(calls, hasLength(1));
    expect(calls.single.$1, 'replay.configure');
    expect(calls.single.$2, <String, dynamic>{'path': r'C:\datasets\UTA-RLDD'});
  });

  testWidgets('cancelling the folder picker sends no command', (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PlaybackView(
            recordings: const [],
            selected: null,
            rows: const [],
            offset: 0,
            total: 0,
            startTimestamp: 0,
            onPage: (_) async {},
            busy: false,
            state: const <String, dynamic>{},
            onCommand: (command, [args]) async => calls.add((command, args)),
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async => null,
          ),
        ),
      ),
    );

    await tester.tap(find.byTooltip('選擇資料夾'));
    await tester.pumpAndSettle();

    expect(calls, isEmpty);
  });

  testWidgets('folder picker failure shows an error and sends no command',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PlaybackView(
            recordings: const [],
            selected: null,
            rows: const [],
            offset: 0,
            total: 0,
            startTimestamp: 0,
            onPage: (_) async {},
            busy: false,
            state: const <String, dynamic>{},
            onCommand: (command, [args]) async => calls.add((command, args)),
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async =>
                throw StateError('native picker unavailable'),
          ),
        ),
      ),
    );

    await tester.tap(find.byTooltip('選擇資料夾'));
    await tester.pumpAndSettle();

    expect(find.textContaining('native picker unavailable'), findsOneWidget);
    expect(calls, isEmpty);
  });

  testWidgets('manual replay path remains available as a fallback',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PlaybackView(
            recordings: const [],
            selected: null,
            rows: const [],
            offset: 0,
            total: 0,
            startTimestamp: 0,
            onPage: (_) async {},
            busy: false,
            state: const <String, dynamic>{},
            onCommand: (command, [args]) async => calls.add((command, args)),
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async => null,
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField).first, r'D:\replay\manual');
    await tester.tap(find.byTooltip('套用路徑'));
    await tester.pumpAndSettle();

    expect(calls, hasLength(1));
    expect(calls.single.$1, 'replay.configure');
    expect(calls.single.$2, <String, dynamic>{'path': r'D:\replay\manual'});
  });

  testWidgets('short narrow windows can scroll from controls to recordings',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 320));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2)),
        child: Scaffold(
          body: PlaybackView(
            recordings: const [
              {'session_name': '窄窗監測記錄', 'record_count': 20},
            ],
            selected: null,
            rows: const [],
            busy: false,
            state: const {},
            onCommand: (_, [__]) async {},
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async => null,
            offset: 0,
            total: 0,
            startTimestamp: 0,
            onPage: (_) async {},
          ),
        ),
      ),
    ));
    expect(tester.takeException(), isNull);

    await tester.scrollUntilVisible(find.text('窄窗監測記錄'), 180,
        scrollable: find.byType(Scrollable).first);
    expect(tester.takeException(), isNull);
    expect(find.text('窄窗監測記錄').hitTestable(), findsOneWidget);
  });

  testWidgets('large text wraps replay metrics and keeps pagination usable',
      (tester) async {
    final pages = <int>[];
    await tester.binding.setSurfaceSize(const Size(360, 360));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(2.25)),
        child: Scaffold(
          body: PlaybackView(
            recordings: const [],
            selected: const {'session_name': '回放指標'},
            rows: const [
              {
                'timestamp': 105.0,
                'status': 'CRITICAL',
                'ear': 0.18,
                'bpm': 72,
                'perclos': 0.125,
              },
            ],
            busy: false,
            state: const {},
            onCommand: (_, [__]) async {},
            onRefresh: () async {},
            onOpen: (_) async {},
            onClose: () {},
            onPickReplayFolder: () async => null,
            offset: 200,
            total: 401,
            startTimestamp: 100,
            onPage: (offset) async => pages.add(offset),
          ),
        ),
      ),
    ));
    expect(tester.takeException(), isNull);

    await tester.scrollUntilVisible(find.text('PERCLOS 12.5%'), 180,
        scrollable: find.byType(Scrollable).first);
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(find.text('下一頁'), 140,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('下一頁'));
    expect(pages, [201]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('recordings use lazy construction for long histories',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1200, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PlaybackView(
          recordings:
              List.generate(1000, (index) => {'session_name': '監測記錄 $index'}),
          selected: null,
          rows: const [],
          busy: false,
          state: const {},
          onCommand: (_, [__]) async {},
          onRefresh: () async {},
          onOpen: (_) async {},
          onClose: () {},
          onPickReplayFolder: () async => null,
          offset: 0,
          total: 0,
          startTimestamp: 0,
          onPage: (_) async {},
        ),
      ),
    ));

    expect(find.text('監測記錄 0'), findsOneWidget);
    expect(find.text('監測記錄 999'), findsNothing);
    expect(tester.widgetList<ListTile>(find.byType(ListTile)).length,
        lessThan(20));
    expect(tester.takeException(), isNull);
  });
}
