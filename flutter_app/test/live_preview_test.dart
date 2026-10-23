import 'dart:async';
import 'dart:convert';

import 'package:fatigue_monitor_ui/widgets/live_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _redPng =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC';
const _bluePng =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC';

Widget _host(Stream<String> frames) => Directionality(
      textDirection: TextDirection.ltr,
      child: SizedBox(
        width: 320,
        height: 180,
        child: LivePreviewImage(
          frames: frames,
          placeholder: const Text('Waiting for camera'),
        ),
      ),
    );

MemoryImage _currentImage(WidgetTester tester) =>
    tester.widget<Image>(find.byType(Image)).image as MemoryImage;

Future<void> _waitForImage(WidgetTester tester) async {
  for (var attempt = 0; attempt < 100; attempt++) {
    if (imageCache.pendingImageCount == 0 &&
        tester.widget<RawImage>(find.byType(RawImage)).image != null) {
      return;
    }
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pump();
  }
  expect(tester.widget<RawImage>(find.byType(RawImage)).image, isNotNull);
  expect(imageCache.pendingImageCount, 0);
}

void main() {
  setUp(() {
    imageCache.clear();
    imageCache.clearLiveImages();
  });

  testWidgets('a burst shows the latest frame without rebuilding its parent',
      (tester) async {
    final frames = StreamController<String>.broadcast(sync: true);
    addTearDown(frames.close);
    var parentBuilds = 0;
    await tester.pumpWidget(Builder(builder: (_) {
      parentBuilds++;
      return _host(frames.stream);
    }));
    final callbacks = tester.binding.transientCallbackCount;

    for (var index = 0; index < 99; index++) {
      frames.add(_redPng);
    }
    frames.add(_bluePng);
    expect(tester.binding.transientCallbackCount, callbacks + 1);
    expect(find.byType(Image), findsNothing);
    await tester.pump();
    await _waitForImage(tester);

    expect(_currentImage(tester).bytes, base64Decode(_bluePng));
    expect(find.byType(RawImage), findsOneWidget);
    expect(parentBuilds, 1);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('invalid base64 preserves the last visible image',
      (tester) async {
    final frames = StreamController<String>.broadcast(sync: true);
    addTearDown(frames.close);
    await tester.pumpWidget(_host(frames.stream));
    frames.add(_redPng);
    await tester.pump();
    await _waitForImage(tester);
    final previous = _currentImage(tester);

    frames.add('invalid base64!');
    await tester.pump();

    expect(_currentImage(tester), same(previous));
    expect(find.text('Waiting for camera'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('replacing the stream cancels the old listener and pending frame',
      (tester) async {
    final oldFrames = StreamController<String>.broadcast(sync: true);
    final newFrames = StreamController<String>.broadcast(sync: true);
    addTearDown(oldFrames.close);
    addTearDown(newFrames.close);
    await tester.pumpWidget(_host(oldFrames.stream));
    tester.binding.scheduleFrameCallback((_) => oldFrames.add(_redPng));

    await tester.pumpWidget(_host(newFrames.stream));
    expect(oldFrames.hasListener, isFalse);
    expect(newFrames.hasListener, isTrue);
    expect(find.text('Waiting for camera'), findsOneWidget);
    oldFrames.add(_redPng);
    newFrames.add(_bluePng);
    await tester.pump();
    await _waitForImage(tester);

    expect(_currentImage(tester).bytes, base64Decode(_bluePng));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('disposing cancels a pending frame and releases the listener',
      (tester) async {
    final frames = StreamController<String>.broadcast(sync: true);
    addTearDown(frames.close);
    final visible = ValueNotifier(true);
    addTearDown(visible.dispose);
    await tester.pumpWidget(ValueListenableBuilder<bool>(
      valueListenable: visible,
      builder: (_, show, __) =>
          show ? _host(frames.stream) : const SizedBox.shrink(),
    ));

    tester.binding.scheduleFrameCallback((_) {
      frames.add(_redPng);
      visible.value = false;
    });
    await tester.pump();
    await tester.pump();

    expect(frames.hasListener, isFalse);
    expect(find.byType(Image), findsNothing);
    expect(tester.binding.transientCallbackCount, 0);
    expect(imageCache.currentSize, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('decoded frames do not accumulate in the image cache',
      (tester) async {
    final frames = StreamController<String>.broadcast(sync: true);
    addTearDown(frames.close);
    await tester.pumpWidget(_host(frames.stream));

    for (var index = 0; index < 20; index++) {
      frames.add(index.isEven ? _redPng : _bluePng);
      await tester.pump();
      await _waitForImage(tester);
      expect(imageCache.currentSize, 1);
      expect(imageCache.liveImageCount, 1);
      expect(imageCache.pendingImageCount, 0);
    }

    await tester.pumpWidget(const SizedBox.shrink());
    expect(imageCache.currentSize, 0);
    expect(imageCache.liveImageCount, 0);
    expect(tester.takeException(), isNull);
  });
}
