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
