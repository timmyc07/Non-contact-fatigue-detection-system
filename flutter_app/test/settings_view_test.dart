import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('unsupported macOS hotkeys cannot be configured', (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SettingsView(
      state: const {
        'hotkey_registration': {'supported': false}
      },
      busy: false,
      onCommand: (_, [__]) async {},
    ))));
    final button = tester
        .widget<OutlinedButton>(find.widgetWithText(OutlinedButton, '快捷鍵'));
    expect(button.onPressed, isNull);
  });

  testWidgets('overlay opacity sends one command when dragging ends',
      (tester) async {
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

    final opacityCalls =
        calls.where((call) => call.$1 == 'overlay.configure').toList();
    expect(opacityCalls, hasLength(1));
    expect(opacityCalls.single.$2?['opacity'], greaterThan(55));
  });

  testWidgets('analysis switches can select raw camera mode', (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 900,
            child: SettingsView(
              state: const <String, dynamic>{
                'behavior_enabled': false,
                'rppg_enabled': false,
              },
              busy: false,
              onCommand: (command, [args]) async => calls.add((command, args)),
            ),
          ),
        ),
      ),
    );

    final switches = tester.widgetList<SwitchListTile>(
      find.byType(SwitchListTile),
    );
    expect(switches.length, greaterThanOrEqualTo(2));
    expect(switches.elementAt(0).onChanged, isNotNull);
    expect(switches.elementAt(1).onChanged, isNotNull);

    await tester.tap(find.text('行為警覺分析'));
    await tester.pump();
    expect(calls.single.$1, 'analysis.configure');
    expect(calls.single.$2?['behavior_enabled'], isTrue);
  });

  testWidgets('hotkey dialog submits the complete replacement payload',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 900,
            child: SettingsView(
              state: const <String, dynamic>{
                'hotkey_registration': {'supported': true},
                'hotkeys': {
                  'toggle_metrics': 'Ctrl+Alt+O',
                  'toggle_preview': 'Ctrl+Alt+P',
                  'start_stop': 'Ctrl+Alt+S',
                  'lock_overlay': 'Ctrl+Alt+F8',
                  'toggle_all': 'Ctrl+Alt+A',
                  'toggle_recording': 'Ctrl+Alt+F9',
                },
              },
              busy: false,
              onCommand: (command, [args]) async => calls.add((command, args)),
            ),
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.text('快捷鍵'));
    await tester.tap(find.text('快捷鍵'));
    await tester.pumpAndSettle();
    expect(find.text('快捷鍵設定'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(6));

    await tester.enterText(find.byType(TextField).first, 'Alt+1');
    await tester.tap(find.text('套用快捷鍵'));
    await tester.pumpAndSettle();

    expect(calls, hasLength(1));
    expect(calls.single.$1, 'hotkeys.configure');
    expect(calls.single.$2?['hotkeys'], <String, dynamic>{
      'toggle_metrics': 'Alt+1',
      'toggle_preview': 'Ctrl+Alt+P',
      'start_stop': 'Ctrl+Alt+S',
      'lock_overlay': 'Ctrl+Alt+F8',
      'toggle_all': 'Ctrl+Alt+A',
      'toggle_recording': 'Ctrl+Alt+F9',
    });
  });

  testWidgets('hotkey dialog rejects entries longer than 64 characters',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SettingsView(
            state: const <String, dynamic>{
              'hotkeys': {},
              'hotkey_registration': {'supported': true}
            },
            busy: false,
            onCommand: (command, [args]) async => calls.add((command, args)),
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.text('快捷鍵'));
    await tester.tap(find.text('快捷鍵'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'x' * 65);
    await tester.tap(find.text('套用快捷鍵'));
    await tester.pumpAndSettle();

    expect(find.text('每個快捷鍵最多 64 個字元'), findsOneWidget);
    expect(calls, isEmpty);
  });

  testWidgets('user profile dialog submits fields and shows read-only BMI',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SettingsView(
            state: const <String, dynamic>{
              'user_profile': {
                'age': 40,
                'height_cm': 180,
                'weight_kg': 90.0,
                'bmi': 27.8
              },
            },
            busy: false,
            onCommand: (command, [args]) async => calls.add((command, args)),
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.text('使用者資料'));
    await tester.tap(find.text('使用者資料'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('BMI 27.8'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(3));
    await tester.enterText(find.byType(TextField).at(2), '85');
    await tester.tap(find.text('套用使用者資料'));
    await tester.pumpAndSettle();

    expect(calls, hasLength(1));
    expect(calls.single.$1, 'user_profile.configure');
    expect(calls.single.$2?['user_profile'], <String, dynamic>{
      'age': 40,
      'height_cm': 180,
      'weight_kg': 85.0,
    });
  });

  testWidgets('user profile dialog rejects values outside supported ranges',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SettingsView(
            state: const <String, dynamic>{'user_profile': {}},
            busy: false,
            onCommand: (command, [args]) async => calls.add((command, args)),
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.text('使用者資料'));
    await tester.tap(find.text('使用者資料'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '111');
    await tester.tap(find.text('套用使用者資料'));
    await tester.pumpAndSettle();

    expect(find.text('年齡需介於 0 到 110'), findsOneWidget);
    expect(calls, isEmpty);
  });

  testWidgets('alarm dialog submits complete config and tests a draft scenario',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    const alarm = <String, dynamic>{
      'enabled': true,
      'volume': 70,
      'trigger_delay_sec': 1.0,
      'repeat_interval_sec': 20.0,
      'repeat_while_critical': false,
      'use_builtin_fallback': true,
      'scenarios': {
        'low_vigilance': {'enabled': true, 'sound_path': ''},
        'drowsy': {'enabled': true, 'sound_path': ''},
        'critical': {'enabled': true, 'sound_path': ''},
        'microsleep': {'enabled': true, 'sound_path': ''},
      },
    };
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SettingsView(
                state: const {'alarm': alarm},
                busy: false,
                onCommand: (command, [args]) async =>
                    calls.add((command, args))))));
    await tester.ensureVisible(find.text('警報器'));
    await tester.tap(find.text('警報器'));
    await tester.pumpAndSettle();

    expect(find.byType(TextField), findsNWidgets(6));
    await tester.ensureVisible(find.byTooltip('測試 critical'));
    await tester.tap(find.byTooltip('測試 critical'));
    await tester.pumpAndSettle();
    expect(calls, hasLength(1));
    expect(calls.single.$1, 'alarm.test');
    expect(calls.single.$2?['scenario'], 'critical');
    expect(calls.single.$2?['alarm'], isA<Map>());

    await tester.ensureVisible(find.text('套用警報設定'));
    await tester.tap(find.text('套用警報設定'));
    await tester.pumpAndSettle();
    expect(calls, hasLength(2));
    expect(calls.last.$1, 'alarm.configure');
    expect(calls.last.$2?['alarm'], isA<Map>());
    expect((calls.last.$2?['alarm'] as Map)['volume'], 70);
  });

  testWidgets(
      'reset requires confirmation and sends exact scoped or all sections',
      (tester) async {
    final calls = <(String, Map<String, dynamic>?)>[];
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SettingsView(
                state: const {
          'hotkey_registration': {'supported': true}
        },
                busy: false,
                onCommand: (command, [args]) async =>
                    calls.add((command, args))))));
    await tester.ensureVisible(find.text('重設快捷鍵'));
    await tester.tap(find.text('重設快捷鍵'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(calls, isEmpty);

    await tester.tap(find.text('重設快捷鍵'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '確認重設'));
    await tester.pumpAndSettle();
    expect(calls.single.$1, 'settings.reset');
    expect(calls.single.$2, <String, dynamic>{
      'sections': ['hotkeys']
    });

    await tester.ensureVisible(find.text('全部重設'));
    await tester.tap(find.text('全部重設'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '確認重設'));
    await tester.pumpAndSettle();
    expect(calls.last.$1, 'settings.reset');
    expect(calls.last.$2?['sections'], [
      'hotkeys',
      'user_profile',
      'alarm',
      'camera',
      'toggles',
      'overlay',
      'web',
      'replay'
    ]);
  });
}
