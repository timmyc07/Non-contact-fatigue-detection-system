import 'package:fatigue_monitor_ui/services/backend_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

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
