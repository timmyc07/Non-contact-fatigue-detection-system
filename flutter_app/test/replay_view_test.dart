import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
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
}
