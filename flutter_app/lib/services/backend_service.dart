import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:socket_io_client/socket_io_client.dart' as io;

class BackendService {
  BackendService({this.baseUrl = 'http://127.0.0.1:5000'});

  final String baseUrl;
  io.Socket? _socket;
  Timer? _poller;

  Stream<Map<String, dynamic>> connectMetrics() {
    final controller = StreamController<Map<String, dynamic>>.broadcast(
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
        if (packet != null && !controller.isClosed) controller.add(packet);
      });
      socket.on('connect', (_) => socket.emit('request_metrics'));
      socket.on('connect_error', (_) => _startPolling(controller));
    } catch (_) {
      _startPolling(controller);
    }
    return controller.stream;
  }

  Future<List<Map<String, dynamic>>> recordings() async {
    final response = await http.get(Uri.parse('$baseUrl/api/recordings'));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Backend returned HTTP ${response.statusCode}.');
    }
    final body = jsonDecode(response.body);
    final data = body is Map ? body['data'] : null;
    if (data is! List) return <Map<String, dynamic>>[];
    return data.whereType<Map>().map((row) => Map<String, dynamic>.from(row)).toList();
  }

  void _startPolling(StreamController<Map<String, dynamic>> controller) {
    if (_poller != null) return;
    _poller = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final response = await http.get(Uri.parse('$baseUrl/api/metrics'));
        if (response.statusCode == 200) {
          final packet = _packet(jsonDecode(response.body));
          if (packet != null && !controller.isClosed) controller.add(packet);
        }
      } catch (_) {
        // The UI keeps the last sample and exposes its disconnected state.
      }
    });
  }

  Map<String, dynamic>? _packet(dynamic payload) {
    final value = payload is Map && payload['metrics'] is Map ? payload['metrics'] : payload;
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }
}
