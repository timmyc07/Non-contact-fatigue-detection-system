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
  BackendService(
      {this.baseUrl = _backendBaseUrl, http.Client? client, io.Socket? socket})
      : _client = client ?? http.Client(),
        _ownsClient = client == null,
        _socket = socket;

  final String baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  io.Socket? _socket;
  Timer? _poller;
  bool _pollingInFlight = false;
  bool _disposed = false;
  static const _requestTimeout = Duration(seconds: 12);
  late final StreamController<MetricsSnapshot> _metrics =
      StreamController<MetricsSnapshot>.broadcast(
    onListen: _connectMetrics,
    onCancel: _disconnectMetrics,
  );
  final StreamController<String> _previewFrames =
      StreamController<String>.broadcast();

  Stream<String> get previewFrames => _previewFrames.stream;

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _disconnectMetrics();
    await Future.wait([_metrics.close(), _previewFrames.close()]);
    if (_ownsClient) {
      _client.close();
    }
  }

  Stream<Map<String, dynamic>> connectMetrics() {
    return connectMetricSnapshots().map((snapshot) => snapshot.toJson());
  }

  Stream<MetricsSnapshot> connectMetricSnapshots() {
    return _metrics.stream;
  }

  void _connectMetrics() {
    if (_disposed) return;
    try {
      final socket = _socket ??
          io.io(
            baseUrl,
            <String, dynamic>{
              'transports': ['websocket', 'polling'],
              'autoConnect': true,
              'reconnection': true,
              'forceNew': true,
            },
          );
      _socket = socket;
      socket.on('metrics_update', (dynamic payload) {
        _consumeSocketEvent(payload, (raw) {
          final packet = _packet(raw);
          if (packet != null && !_metrics.isClosed) {
            _metrics.add(MetricsSnapshot.fromJson(packet));
          }
        });
      });
      socket.on('frame_update', (dynamic payload) {
        _consumeSocketEvent(payload, (raw) {
          final frame = raw is Map ? raw['frame'] : null;
          if (frame is String && frame.isNotEmpty && !_previewFrames.isClosed) {
            _previewFrames.add(frame);
          }
        });
      });
      socket.on('connect', (_) {
        _stopPolling();
      });
      socket.on('connect_error', (_) => _startPolling());
      socket.on('disconnect', (_) => _startPolling());
    } catch (_) {
      _startPolling();
    }
  }

  void _disconnectMetrics() {
    _socket?.dispose();
    _socket = null;
    _stopPolling();
  }

  void _consumeSocketEvent(dynamic event, void Function(dynamic) consume) {
    final acknowledged =
        event is List && event.length == 2 && event.last is Function;
    try {
      consume(acknowledged ? event.first : event);
    } finally {
      if (acknowledged) Function.apply(event.last as Function, [null]);
    }
  }

  Future<List<Map<String, dynamic>>> recordings() async {
    final values = await recordingMetadata();
    return values.map((row) => row.toJson()).toList();
  }

  Future<List<RecordingMetadata>> recordingMetadata() async {
    final response = await _client
        .get(Uri.parse('$baseUrl/api/recordings'))
        .timeout(_requestTimeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Backend returned HTTP ${response.statusCode}.');
    }
    final body = jsonDecode(response.body);
    final data = body is Map ? body['data'] : null;
    if (data is! List) return <RecordingMetadata>[];
    return data.whereType<Map>().map(RecordingMetadata.fromJson).toList();
  }

  Future<Map<String, dynamic>> playback(String dbPath,
      {int limit = 100, int offset = 0}) async {
    final uri = Uri.parse('$baseUrl/api/playback').replace(
      queryParameters: <String, String>{
        'db_path': dbPath,
        'limit': limit.toString(),
        'offset': offset.toString(),
      },
    );
    final response = await _client.get(uri).timeout(_requestTimeout);
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
    final response = await _client
        .get(Uri.parse('$baseUrl/api/metrics'))
        .timeout(_requestTimeout);
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
    final response = await (method == 'POST'
            ? _client.post(
                uri,
                headers: const <String, String>{
                  'Content-Type': 'application/json'
                },
                body: jsonEncode(body),
              )
            : _client.get(uri))
        .timeout(_requestTimeout);
    final payload = jsonDecode(response.body);
    if (response.statusCode < 200 ||
        response.statusCode >= 300 ||
        payload is! Map) {
      throw StateError(_errorMessage(payload, response.statusCode));
    }
    final data = payload['data'];
    return data is Map ? Map<String, dynamic>.from(data) : <String, dynamic>{};
  }

  void _startPolling() {
    if (_poller != null || _disposed || !_metrics.hasListener) return;
    _poller = Timer.periodic(const Duration(seconds: 2), (poller) async {
      if (_pollingInFlight) return;
      _pollingInFlight = true;
      try {
        final response = await _client
            .get(Uri.parse('$baseUrl/api/metrics'))
            .timeout(_requestTimeout);
        if (response.statusCode == 200) {
          final packet = _packet(jsonDecode(response.body));
          if (packet != null &&
              !_disposed &&
              _metrics.hasListener &&
              identical(_poller, poller)) {
            _metrics.add(MetricsSnapshot.fromJson(packet));
          }
        }
      } catch (_) {
        // 下一輪重試，保留最後一筆資料。
      } finally {
        _pollingInFlight = false;
      }
    });
  }

  void _stopPolling() {
    _poller?.cancel();
    _poller = null;
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
