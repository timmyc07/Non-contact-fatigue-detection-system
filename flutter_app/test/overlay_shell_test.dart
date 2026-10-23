import 'dart:async';

import 'package:fatigue_monitor_ui/main.dart';
import 'package:fatigue_monitor_ui/services/backend_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _OverlayBackend extends BackendService {
  final state = Completer<Map<String, dynamic>>();
  final packets = StreamController<Map<String, dynamic>>.broadcast();
  final pendingSnapshot = Completer<Map<String, dynamic>>();
  final states = <Future<Map<String, dynamic>>>[];
  var snapshotRequests = 0;
  var controlRequests = 0;

  @override
  Future<Map<String, dynamic>> controlState() {
    controlRequests++;
    return states.isEmpty ? state.future : states.removeAt(0);
  }

  @override
  Stream<Map<String, dynamic>> connectMetrics() => packets.stream;

  @override
  Future<Map<String, dynamic>> metricsSnapshot() {
    snapshotRequests++;
    return pendingSnapshot.future;
  }

  @override
  Future<void> dispose() async {
    await packets.close();
    await super.dispose();
  }
}

void main() {
  testWidgets(
      'native visibility pauses hidden work and preserves unfocused updates',
      (tester) async {
    final backend = _OverlayBackend();
    backend.state.complete({
      'overlay_opacity': 100,
      'overlay_metrics': true,
      'overlay_preview': true,
    });
    final visibility = StreamController<bool>.broadcast(sync: true);
    addTearDown(visibility.close);
    await tester.pumpWidget(MaterialApp(
        home: OverlayShell(
            backend: backend, visibilityChanges: visibility.stream)));
    expect(backend.controlRequests, 0);
    expect(backend.packets.hasListener, isFalse);
    expect(find.text('NCFD 監測 Overlay'), findsNothing);

    visibility.add(true);
    await tester.pump();
    await tester.pump();
    expect(backend.controlRequests, 1);
    expect(backend.packets.hasListener, isTrue);
    expect(find.text('NCFD 監測 Overlay'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump(const Duration(seconds: 1));
    expect(backend.controlRequests, 2);
    expect(backend.packets.hasListener, isTrue);

    visibility.add(false);
    await tester.pump();
    expect(backend.packets.hasListener, isFalse);
    expect(find.text('NCFD 監測 Overlay'), findsNothing);
    await tester.pump(const Duration(seconds: 3));
    expect(backend.controlRequests, 2);
    visibility.add(true);
    await tester.pump();
    await tester.pump();
    expect(backend.controlRequests, 3);
    backend.packets.add({'fps': 29});
    await tester.pump();
    await tester.pump();
    expect(find.text('FPS 29.0'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('showing again ignores a control response from before hiding',
      (tester) async {
    final oldState = Completer<Map<String, dynamic>>();
    final backend = _OverlayBackend();
    backend.states.add(oldState.future);
    backend.state.complete({'overlay_opacity': 25});
    final visibility = StreamController<bool>.broadcast(sync: true);
    addTearDown(visibility.close);
    await tester.pumpWidget(MaterialApp(
        home: OverlayShell(
            backend: backend, visibilityChanges: visibility.stream)));
    visibility.add(true);
    await tester.pump();
    visibility.add(false);
    visibility.add(true);
    await tester.pump();
    await tester.pump();
    expect(backend.controlRequests, 2);
    expect(tester.widget<Opacity>(find.byType(Opacity)).opacity, .25);
    oldState.complete({'overlay_opacity': 90});
    await tester.pump();
    await tester.pump();
    expect(tester.widget<Opacity>(find.byType(Opacity)).opacity, .25);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('control state updates without a redundant slow metrics request',
      (tester) async {
    final backend = _OverlayBackend();
    await tester.pumpWidget(MaterialApp(home: OverlayShell(backend: backend)));
    backend.state.complete({
      'overlay_opacity': 25,
      'overlay_metrics': true,
    });
    await tester.pump();

    expect(tester.widget<Opacity>(find.byType(Opacity)).opacity, .25);
    expect(backend.snapshotRequests, 0);
    backend.packets.add({'stress_bpm': 72, 'fps': 30});
    await tester.pump();
    await tester.pump();
    expect(find.text('72.0'), findsOneWidget);
    expect(find.text('FPS 30.0'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  test('overlay opacity preserves the 0..100 contract', () {
    expect(overlayOpacityPercent({'overlay_opacity': 0}), 0);
    expect(overlayOpacityPercent({'overlay_opacity': 150}), 100);
    expect(overlayOpacityPercent({}), 55);
  });

  test('overlay geometry accepts physical multi-monitor coordinates', () {
    const geometry = <String, dynamic>{
      'x': -1280,
      'y': 24,
      'width': 720,
      'height': 480,
    };

    expect(overlayGeometryFromState({'overlay_geometry': geometry}), geometry);
    expect(overlayGeometryEquals(geometry, Map.of(geometry)), isTrue);
    expect(
      overlayGeometryEquals(geometry, {...geometry, 'x': -1279}),
      isFalse,
    );
  });

  test('overlay geometry rejects incomplete or non-integer payloads', () {
    expect(
      overlayGeometryFromState({
        'overlay_geometry': {'x': 0, 'y': 0, 'width': 720},
      }),
      isNull,
    );
    expect(
      overlayGeometryFromState({
        'overlay_geometry': {
          'x': 0,
          'y': 0,
          'width': 720.0,
          'height': 480,
        },
      }),
      isNull,
    );
  });

  test('first visible overlay applies the saved geometry', () {
    expect(
      overlayGeometryNeedsApply(
        syncGeometry: true,
        acceptedInitialized: false,
        savedGeometry: const {
          'x': -1280,
          'y': 24,
          'width': 720,
          'height': 480,
        },
        acceptedGeometry: null,
        visible: true,
        windowExists: false,
      ),
      isTrue,
    );
  });

  test('repeated disconnect hide skips geometry synchronization', () {
    expect(
      overlayGeometryNeedsApply(
        syncGeometry: false,
        acceptedInitialized: true,
        savedGeometry: null,
        acceptedGeometry: const {
          'x': 10,
          'y': 20,
          'width': 720,
          'height': 480,
        },
        visible: false,
        windowExists: true,
      ),
      isFalse,
    );
  });

  test('external backend geometry update is applied to an existing overlay',
      () {
    expect(
      overlayGeometryNeedsApply(
        syncGeometry: true,
        acceptedInitialized: true,
        savedGeometry: const {
          'x': 100,
          'y': 120,
          'width': 800,
          'height': 600,
        },
        acceptedGeometry: const {
          'x': 10,
          'y': 20,
          'width': 720,
          'height': 480,
        },
        visible: true,
        windowExists: true,
      ),
      isTrue,
    );
  });

  test('clearing backend geometry requests a native reset', () {
    final needsApply = overlayGeometryNeedsApply(
      syncGeometry: true,
      acceptedInitialized: true,
      savedGeometry: null,
      acceptedGeometry: const {
        'x': 10,
        'y': 20,
        'width': 720,
        'height': 480,
      },
      visible: true,
      windowExists: true,
    );

    expect(needsApply, isTrue);
    expect(
      overlayGeometryResetRequested(
        geometryNeedsApply: needsApply,
        savedGeometry: null,
      ),
      isTrue,
    );
  });

  testWidgets('overlay shell renders without a backend frame', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: OverlayShell()),
    );

    expect(find.text('NCFD 監測 Overlay'), findsOneWidget);
  });

  test('overlay values use bounded display precision', () {
    expect(formatOverlayValue('fps', 29.915841141097077), '29.9');
    expect(formatOverlayValue('stress_bpm', 56.099237808936956), '56.1');
    expect(formatOverlayValue('perclos', 3.03040432814172), '3.0%');
    expect(formatOverlayValue('perclos', 120), '100.0%');
    expect(formatOverlayValue('stress_bpm', 0), '--');
    expect(formatOverlayValue('fps', double.nan), '--');
    expect(formatOverlayValue('status', '  清醒  '), '清醒');
  });

  testWidgets('overlay metrics do not overflow at the native minimum size',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 180));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(textScaler: TextScaler.linear(2.25)),
          child: OverlayShell(
            initialState: <String, dynamic>{
              'overlay_preview': true,
              'overlay_metrics': true,
              'overlay_locked': false,
              'overlay_opacity': 100,
            },
            initialMetrics: <String, dynamic>{
              'fps': 29.915841141097077,
              'stress_bpm': 56.099237808936956,
              'perclos': 3.03040432814172,
              'status': '極度危險狀態',
            },
          ),
        ),
      ),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('FPS 29.9'), findsOneWidget);
    expect(find.text('56.1'), findsOneWidget);
    expect(find.text('3.0%'), findsOneWidget);
  });
}
