import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fatigue_monitor_ui/models/mobile_runtime_contract.dart';
import 'package:fatigue_monitor_ui/models/platform_contract.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const methodChannel = MethodChannel(
    MobileRuntimeChannelContract.methodChannelName,
  );

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(methodChannel, null);
  });

  test(
      'channel adapter serializes lifecycle, model, permission and storage calls',
      () async {
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(methodChannel, (call) async {
      calls.add(call);
      switch (call.method) {
        case MobileRuntimeChannelContract.getPermissionState:
        case MobileRuntimeChannelContract.requestPermission:
          return 'granted';
        case MobileRuntimeChannelContract.loadModel:
          return 'ready';
        case MobileRuntimeChannelContract.readLocal:
          return 'saved-value';
        default:
          return null;
      }
    });

    final events = StreamController<dynamic>.broadcast();
    final adapter = MobileRuntimeChannelAdapter(
      PlatformCapabilities.android,
      methodChannel: methodChannel,
      eventStream: events.stream,
    );

    expect(await adapter.permissionState(RuntimePermission.camera),
        PermissionState.granted);
    expect(await adapter.requestPermission(RuntimePermission.camera),
        PermissionState.granted);
    await adapter.startCamera(
      const CameraConfiguration(width: 640, height: 480, fps: 30),
    );
    expect(await adapter.loadModel('face_landmarker'), ModelRuntimeState.ready);
    expect(await adapter.readLocal('session'), 'saved-value');
    await adapter.writeLocal('session', 'new-value');
    await adapter.deleteLocal('session');
    await adapter.setForegroundState(ForegroundState.active);
    await adapter.unloadModel();
    await adapter.stopCamera();

    expect(
      calls.map((call) => call.method),
      containsAll(<String>[
        MobileRuntimeChannelContract.getPermissionState,
        MobileRuntimeChannelContract.requestPermission,
        MobileRuntimeChannelContract.startCamera,
        MobileRuntimeChannelContract.loadModel,
        MobileRuntimeChannelContract.readLocal,
        MobileRuntimeChannelContract.writeLocal,
        MobileRuntimeChannelContract.deleteLocal,
        MobileRuntimeChannelContract.setForegroundState,
        MobileRuntimeChannelContract.unloadModel,
        MobileRuntimeChannelContract.stopCamera,
      ]),
    );
    final startCall = calls.firstWhere(
      (call) => call.method == MobileRuntimeChannelContract.startCamera,
    );
    expect(startCall.arguments, <String, dynamic>{
      'width': 640,
      'height': 480,
      'fps': 30,
      'front_facing': true,
    });
    final modelCall = calls.firstWhere(
      (call) => call.method == MobileRuntimeChannelContract.loadModel,
    );
    expect(
        modelCall.arguments, <String, dynamic>{'model_id': 'face_landmarker'});
    expect(adapter.modelState, ModelRuntimeState.unloaded);

    await adapter.dispose();
    await events.close();
  });

  test('event channel preserves camera frame bytes and foreground metadata',
      () async {
    final events = StreamController<dynamic>.broadcast();
    final adapter = MobileRuntimeChannelAdapter(
      PlatformCapabilities.ios,
      eventStream: events.stream,
    );
    final frameFuture = adapter.cameraFrames.first;
    final states = <ForegroundState>[];
    final stateSubscription = adapter.foregroundStates.listen(states.add);

    events.add(<String, dynamic>{
      'type': MobileRuntimeChannelContract.cameraFrameEvent,
      'bytes': <int>[1, 2, 255],
      'width': 2,
      'height': 1,
      'timestamp_micros': 123456,
      'format': 'rgba8888',
    });
    events.add(<String, dynamic>{
      'type': MobileRuntimeChannelContract.foregroundEvent,
      'state': 'background',
    });

    final frame = await frameFuture;
    await Future<void>.delayed(Duration.zero);
    expect(frame.bytes, orderedEquals(<int>[1, 2, 255]));
    expect(frame.width, 2);
    expect(frame.height, 1);
    expect(frame.timestampMicros, 123456);
    expect(frame.format, CameraPixelFormat.rgba8888);
    expect(states, contains(ForegroundState.background));
    expect(adapter.foregroundState, ForegroundState.background);

    await stateSubscription.cancel();
    await adapter.dispose();
    await events.close();
  });

  test('missing native plugin fails closed without desktop fallback', () async {
    final adapter = MobileRuntimeChannelAdapter(
      PlatformCapabilities.android,
      eventStream: const Stream<dynamic>.empty(),
    );

    await expectLater(
      adapter.startCamera(
        const CameraConfiguration(width: 640, height: 480, fps: 30),
      ),
      throwsA(isA<UnsupportedPlatformRuntimeError>()),
    );
    expect(adapter.isAvailable, isFalse);
    await adapter.dispose();
  });

  test('factory selects channel only for mobile platforms', () async {
    final android = createMobileRuntime(PlatformCapabilities.android);
    final ios = createMobileRuntime(PlatformCapabilities.ios);
    final desktop = createMobileRuntime(PlatformCapabilities.macos);

    expect(android, isA<MobileRuntimeChannelAdapter>());
    expect(ios, isA<MobileRuntimeChannelAdapter>());
    expect(desktop, isA<UnsupportedMobileRuntimeAdapter>());

    await android.dispose();
    await ios.dispose();
    await desktop.dispose();
  });
}
