import 'dart:async';

import 'package:fatigue_monitor_ui/main.dart';
import 'package:fatigue_monitor_ui/services/backend_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _StartingBackend extends BackendService {
  var ready = false;
  var recordingRequests = 0;
  final packets = StreamController<Map<String, dynamic>>.broadcast();
  Completer<List<Map<String, dynamic>>>? pendingRecordings;

  @override
  Stream<Map<String, dynamic>> connectMetrics() => packets.stream;

  @override
  Future<Map<String, dynamic>> controlState() async {
    if (!ready) throw StateError('Engine is starting');
    return {'settings_dirty': true};
  }

  @override
  Future<List<Map<String, dynamic>>> recordings() {
    recordingRequests++;
    return pendingRecordings?.future ??
        Future.value([
          {'path': '/test/session.db', 'session_name': 'Recovered recording'}
        ]);
  }

  @override
  Future<Map<String, dynamic>> command(String command,
          [Map<String, dynamic>? args]) async =>
      throw StateError('Command rejected');

  @override
  Future<void> dispose() async {
    await packets.close();
    await super.dispose();
  }
}

Future<void> _pumpShell(WidgetTester tester, _StartingBackend backend,
    {Future<bool> Function()? isBackendStarting}) async {
  await tester.binding.setSurfaceSize(const Size(1280, 820));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: MonitorShell(backend: backend,
      isBackendStarting: isBackendStarting)));
  await tester.pump();
}

void main() {
  testWidgets('native cold loading remains visible until control API is ready',
      (tester) async {
    final backend = _StartingBackend();
    await _pumpShell(tester, backend, isBackendStarting: () async => true);
    expect(find.textContaining('畫面已開啟，監測服務正在載入'), findsOneWidget);
    expect(find.text('監測服務暫時無法連線，請稍後重試。'), findsNothing);
    expect(backend.recordingRequests, 0);
    await tester.pump(const Duration(seconds: 40));
    await tester.pump();
    expect(find.textContaining('畫面已開啟，監測服務正在載入'), findsOneWidget);
    backend.ready = true;
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.textContaining('畫面已開啟，監測服務正在載入'), findsNothing);
    expect(backend.recordingRequests, 1);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('unresolved native status keeps only one bridge request',
      (tester) async {
    final backend = _StartingBackend();
    final pending = Completer<bool>();
    var queries = 0;
    await _pumpShell(tester, backend, isBackendStarting: () {
      queries++;
      return pending.future;
    });
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(seconds: 3));
      await tester.pump();
    }
    expect(queries, 1);
    pending.complete(false);
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('native startup completion without API shows a connection error',
      (tester) async {
    final backend = _StartingBackend();
    var starting = true;
    await _pumpShell(tester, backend, isBackendStarting: () async => starting);
    starting = false;
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.textContaining('畫面已開啟，監測服務正在載入'), findsNothing);
    expect(find.text('監測服務暫時無法連線，請稍後重試。'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('metrics before engine readiness do not skip the recordings load',
      (tester) async {
    final backend = _StartingBackend();
    await _pumpShell(tester, backend);
    expect(backend.recordingRequests, 0);
    expect(find.text('監測服務暫時無法連線，請稍後重試。'), findsOneWidget);

    backend.packets.add({'fps': 30});
    await tester.pump();
    await tester.pump();
    expect(find.text('引擎已連線'), findsWidgets);
    backend.ready = true;
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.text('監測服務暫時無法連線，請稍後重試。'), findsNothing);
    expect(backend.recordingRequests, 1);
    await tester.tap(find.text('歷史回放'));
    await tester.pump();
    expect(find.text('Recovered recording'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    expect(backend.recordingRequests, 1);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('recordings loading is single flight and retries after failure',
      (tester) async {
    final pending = Completer<List<Map<String, dynamic>>>();
    final backend = _StartingBackend()
      ..ready = true
      ..pendingRecordings = pending;
    await _pumpShell(tester, backend);
    expect(backend.recordingRequests, 1);
    await tester.pump(const Duration(seconds: 3));
    expect(backend.recordingRequests, 1);
    pending.completeError(StateError('Recordings unavailable'));
    await tester.pump();
    await tester.pump();
    expect(find.text('無法載入歷史記錄，請確認監測服務連線後重試。'), findsOneWidget);

    backend.pendingRecordings = null;
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(backend.recordingRequests, 2);
    expect(find.text('無法載入歷史記錄，請確認監測服務連線後重試。'), findsNothing);
    await tester.pump(const Duration(seconds: 3));
    expect(backend.recordingRequests, 2);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets(
      'recordings completion and silent state refresh preserve command errors',
      (tester) async {
    final pending = Completer<List<Map<String, dynamic>>>();
    final backend = _StartingBackend()
      ..ready = true
      ..pendingRecordings = pending;
    await _pumpShell(tester, backend);
    await tester.tap(find.text('系統設定'));
    await tester.pump();
    await tester.tap(find.text('儲存設定'));
    await tester.pump();
    final notice = find.text('操作失敗：Bad state: Command rejected');
    expect(notice, findsWidgets);
    pending.complete([]);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(notice, findsWidgets);
    expect(find.text('重試'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(notice, findsWidgets);
    expect(find.text('重試'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });
}
