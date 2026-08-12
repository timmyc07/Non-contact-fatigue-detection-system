import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
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
}
