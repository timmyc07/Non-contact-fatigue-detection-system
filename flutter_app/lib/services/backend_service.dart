import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:socket_io_client/socket_io_client.dart' as io;

import '../models/backend_contract.dart';

const _backendBaseUrl = String.fromEnvironment(
  'NCFD_BACKEND_URL',
  defaultValue: 'http://127.0.0.1:5000',
);

class BackendService {
  BackendService({this.baseUrl = _backendBaseUrl, http.Client? client})
      : _client = client ?? http.Client(),
        _ownsClient = client == null;

  final String baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  io.Socket? _socket;
  Timer? _poller;
  final StreamController<String> _previewFrames =
      StreamController<String>.broadcast();

  Stream<String> get previewFrames => _previewFrames.stream;

  Future<void> dispose() async {
    _poller?.cancel();
    _poller = null;
    _socket?.disconnect();
    _socket?.dispose();
    _socket = null;
    if (!_previewFrames.isClosed) {
      await _previewFrames.close();
    }
    if (_ownsClient) {
      _client.close();
    }
  }

  Stream<Map<String, dynamic>> connectMetrics() {
    return connectMetricSnapshots().map((snapshot) => snapshot.toJson());
  }

  Stream<MetricsSnapshot> connectMetricSnapshots() {
    final controller = StreamController<MetricsSnapshot>.broadcast(
      onCancel: () {
        _socket?.disconnect();
        _socket?.dispose();
        _poller?.cancel();
      },
    );
    try {
      final socket = io.io(
        baseUrl,
        <String, dynamic>{
          'transports': ['websocket', 'polling'],
          'autoConnect': true,
          'reconnection': true,
        },
      );
      _socket = socket;
      socket.on('metrics_update', (dynamic payload) {
        final packet = _packet(payload);
        if (packet != null && !controller.isClosed) {
          controller.add(MetricsSnapshot.fromJson(packet));
        }
      });
      socket.on('frame_update', (dynamic payload) {
        final frame = payload is Map ? payload['frame'] : null;
        if (frame is String && frame.isNotEmpty && !_previewFrames.isClosed) {
          _previewFrames.add(frame);
        }
      });
      socket.on('connect', (_) => socket.emit('request_metrics'));
      socket.on('connect_error', (_) => _startPolling(controller));
    } catch (_) {
      _startPolling(controller);
    }
    return controller.stream;
  }

  Future<List<Map<String, dynamic>>> recordings() async {
    final values = await recordingMetadata();
    return values.map((row) => row.toJson()).toList();
  }

  Future<List<RecordingMetadata>> recordingMetadata() async {
    final response = await _client.get(Uri.parse('$baseUrl/api/recordings'));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Backend returned HTTP ${response.statusCode}.');
    }
    final body = jsonDecode(response.body);
    final data = body is Map ? body['data'] : null;
    if (data is! List) return <RecordingMetadata>[];
    return data.whereType<Map>().map(RecordingMetadata.fromJson).toList();
  }

  Future<Map<String, dynamic>> playback(String dbPath,
      {int limit = 100}) async {
    final uri = Uri.parse('$baseUrl/api/playback').replace(
      queryParameters: <String, String>{
        'db_path': dbPath,
        'limit': limit.toString(),
      },
    );
    final response = await _client.get(uri);
    final payload = jsonDecode(response.body);
    if (response.statusCode < 200 ||
        response.statusCode >= 300 ||
        payload is! Map) {
      throw StateError(_errorMessage(payload, response.statusCode));
    }
    return Map<String, dynamic>.from(payload);
  }

  Future<Map<String, dynamic>> controlState() async {
    return (await controlStateModel()).toJson();
  }

  Future<ControlState> controlStateModel() async {
    return ControlState.fromJson(
      await _controlRequest('GET', '/api/control/state'),
    );
  }

  Future<Map<String, dynamic>> metricsSnapshot() async {
    return (await metricsSnapshotModel()).toJson();
  }

  Future<MetricsSnapshot> metricsSnapshotModel() async {
    final response = await _client.get(Uri.parse('$baseUrl/api/metrics'));
    final payload = jsonDecode(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError(_errorMessage(payload, response.statusCode));
    }
    final packet = _packet(payload);
    return MetricsSnapshot.fromJson(packet);
  }

  Future<Map<String, dynamic>> command(
    String command, [
    Map<String, dynamic>? args,
  ]) async {
    return _controlRequest(
      'POST',
      '/api/control/command',
      body: <String, dynamic>{
        'command': command,
        'args': args ?? <String, dynamic>{},
      },
    );
  }

  Future<Map<String, dynamic>> _controlRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final response = method == 'POST'
        ? await _client.post(
            uri,
            headers: const <String, String>{'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
        : await _client.get(uri);
    final payload = jsonDecode(response.body);
    if (response.statusCode < 200 ||
        response.statusCode >= 300 ||
        payload is! Map) {
      throw StateError(_errorMessage(payload, response.statusCode));
    }
    final data = payload['data'];
    return data is Map ? Map<String, dynamic>.from(data) : <String, dynamic>{};
  }

  void _startPolling(StreamController<MetricsSnapshot> controller) {
    if (_poller != null) return;
    _poller = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final response = await _client.get(Uri.parse('$baseUrl/api/metrics'));
        if (response.statusCode == 200) {
          final packet = _packet(jsonDecode(response.body));
          if (packet != null && !controller.isClosed) {
            controller.add(MetricsSnapshot.fromJson(packet));
          }
        }
      } catch (_) {
        // The UI keeps the last sample and exposes its disconnected state.
      }
    });
  }

  Map<String, dynamic>? _packet(dynamic payload) {
    final value = payload is Map && payload['metrics'] is Map
        ? payload['metrics']
        : payload;
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }

  String _errorMessage(dynamic payload, int statusCode) {
    return ApiError.fromPayload(payload, statusCode).message;
  }
}
