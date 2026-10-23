import 'dart:async';

import 'package:fatigue_monitor_ui/services/backend_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:socket_io_client/socket_io_client.dart' as io;

class _TrackingClient extends http.BaseClient {
  bool closed = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async =>
      http.StreamedResponse(const Stream<List<int>>.empty(), 200);

  @override
  void close() {
    closed = true;
    super.close();
  }
}

void main() {
  test('metrics and frames acknowledge consumed and discarded server events',
      () async {
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(socket: socket);
    final packets = <Map<String, dynamic>>[];
    final frames = <String>[];
    final metricsSubscription = service.connectMetrics().listen(packets.add);
    final frameSubscription = service.previewFrames.listen(frames.add);
    var acknowledgements = 0;
    void acknowledge(dynamic _) => acknowledgements++;

    socket.emitEvent([
      'metrics_update',
      {'fps': 30},
      acknowledge
    ]);
    socket.emitEvent([
      'frame_update',
      {'frame': 'latest'},
      acknowledge
    ]);
    socket.emitEvent(['metrics_update', null, acknowledge]);
    socket.emitEvent([
      'frame_update',
      {'frame': ''},
      acknowledge
    ]);
    await Future<void>.delayed(Duration.zero);

    expect(packets, [
      {'fps': 30}
    ]);
    expect(frames, ['latest']);
    expect(acknowledgements, 4);
    expect(
        () => socket.emitEvent([
              'metrics_update',
              {7: 'invalid key'},
              acknowledge
            ]),
        throwsA(isA<TypeError>()));
    expect(acknowledgements, 5);
    await metricsSubscription.cancel();
    await frameSubscription.cancel();
    await service.dispose();
  });

  test('reconnect consumes latest metrics without requesting unused history',
      () async {
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(socket: socket);
    final packets = <Map<String, dynamic>>[];
    final subscription = service.connectMetrics().listen(packets.add);
    addTearDown(service.dispose);

    for (final fps in [30, 31]) {
      socket.emitEvent(['connect', null]);
      socket.emitEvent([
        'metrics_update',
        {
          'metrics': {'fps': fps}
        }
      ]);
      socket.emitEvent(['disconnect', 'reconnecting']);
    }
    await Future<void>.delayed(Duration.zero);

    expect(socket.sendBuffer, isEmpty);
    expect(packets, [
      {'fps': 30},
      {'fps': 31}
    ]);
    await subscription.cancel();
  });

  test('fallback polling is single flight and stops on reconnect or cancel',
      () async {
    var requests = 0;
    final pending = Completer<http.Response>();
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(
        socket: socket,
        client: MockClient((_) {
          requests++;
          return requests == 1
              ? pending.future
              : Future.value(http.Response('{"metrics":{"fps":30}}', 200));
        }));
    final subscription = service.connectMetricSnapshots().listen((_) {});
    socket.emitEvent(['connect_error', 'offline']);
    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 1);
    await Future<void>.delayed(const Duration(seconds: 4));
    expect(requests, 1);
    pending.complete(http.Response('{"metrics":{"fps":30}}', 200));
    await Future<void>.delayed(Duration.zero);
    socket.emitEvent(['connect', null]);
    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 1);
    socket.emitEvent(['disconnect', 'offline']);
    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 2);
    await subscription.cancel();
    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 2);
    await service.dispose();
  });

  test('metrics subscribers share socket listeners until the last cancellation',
      () async {
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(socket: socket);
    final first = <Map<String, dynamic>>[];
    final second = <Map<String, dynamic>>[];
    final frames = <String>[];
    final firstSubscription = service.connectMetrics().listen(first.add);
    final secondSubscription = service.connectMetrics().listen(second.add);
    final frameSubscription = service.previewFrames.listen(frames.add);

    socket.emitEvent([
      'metrics_update',
      {'fps': 30}
    ]);
    socket.emitEvent([
      'frame_update',
      {'frame': 'preview'}
    ]);
    await Future<void>.delayed(Duration.zero);

    expect(first, [
      {'fps': 30}
    ]);
    expect(second, first);
    expect(frames, ['preview']);

    await firstSubscription.cancel();
    socket.emitEvent([
      'metrics_update',
      {'fps': 31}
    ]);
    await Future<void>.delayed(Duration.zero);

    expect(first, hasLength(1));
    expect(second, [
      {'fps': 30},
      {'fps': 31}
    ]);

    await secondSubscription.cancel();
    socket.emitEvent([
      'frame_update',
      {'frame': 'after cancellation'}
    ]);
    await Future<void>.delayed(Duration.zero);
    expect(frames, ['preview']);
    await frameSubscription.cancel();
    await service.dispose();
  });

  test('restarted polling rejects a previous connection response', () async {
    var requests = 0;
    final pending = Completer<http.Response>();
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(
      socket: socket,
      client: MockClient((_) {
        requests++;
        return requests == 1
            ? pending.future
            : Future.value(http.Response('{"metrics":{"fps":31}}', 200));
      }),
    );
    final packets = <Map<String, dynamic>>[];
    final subscription = service.connectMetrics().listen(packets.add);
    socket.emitEvent(['connect_error', 'offline']);
    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 1);

    socket.emitEvent(['connect', null]);
    socket.emitEvent(['disconnect', 'offline again']);
    pending.complete(http.Response('{"metrics":{"fps":10}}', 200));
    await Future<void>.delayed(Duration.zero);
    expect(packets, isEmpty);

    await Future<void>.delayed(const Duration(milliseconds: 2100));
    expect(requests, 2);
    expect(packets, [
      {'fps': 31}
    ]);
    await subscription.cancel();
    await service.dispose();
  });

  test('dispose completes metrics and frame streams', () async {
    final socket = io.io('http://127.0.0.1:1', <String, dynamic>{
      'autoConnect': false,
      'reconnection': false,
      'forceNew': true,
    });
    final service = BackendService(socket: socket);
    final metricsDone = Completer<void>();
    final framesDone = Completer<void>();
    service
        .connectMetricSnapshots()
        .listen((_) {}, onDone: metricsDone.complete);
    service.previewFrames.listen((_) {}, onDone: framesDone.complete);

    await service.dispose();
    await Future.wait([metricsDone.future, framesDone.future]);
    await service.dispose();
    expect(await service.connectMetricSnapshots().isEmpty, isTrue);
  });

  test('playback sends explicit pagination offset', () async {
    final service = BackendService(client: MockClient((request) async {
      expect(request.url.queryParameters['offset'], '200');
      expect(request.url.queryParameters['limit'], '200');
      return http.Response('{"success":true,"total":401,"data":[]}', 200);
    }));
    await service.playback('/tmp/test.db', offset: 200, limit: 200);
    await service.dispose();
  });
  test('command exposes the structured backend error message', () async {
    final service = BackendService(
      client: MockClient(
        (_) async => http.Response(
          '{"success":false,"error":{"code":"invalid_settings","message":"Volume must be between 0 and 100."}}',
          400,
        ),
      ),
    );

    await expectLater(
      service.command('alarm.configure'),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          'Volume must be between 0 and 100.',
        ),
      ),
    );
  });

  test('metrics snapshot unwraps the latest backend packet', () async {
    final service = BackendService(
      baseUrl: 'http://127.0.0.1:5000',
      client: MockClient((request) async {
        expect(request.url.path, '/api/metrics');
        return http.Response(
          '{"success":true,"metrics":{"fps":30,"status":"READY"}}',
          200,
        );
      }),
    );

    expect(await service.metricsSnapshot(), <String, dynamic>{
      'fps': 30,
      'status': 'READY',
    });
    await service.dispose();
  });

  test('controlState preserves a legacy string error', () async {
    final service = BackendService(
      client: MockClient(
        (_) async => http.Response(
          '{"success":false,"error":"Engine is starting."}',
          503,
        ),
      ),
    );

    await expectLater(
      service.controlState(),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          'Engine is starting.',
        ),
      ),
    );
  });

  test('dispose does not close an injected HTTP client', () async {
    final client = _TrackingClient();
    final service = BackendService(client: client);

    await service.dispose();

    expect(client.closed, isFalse);
    client.close();
  });
}
