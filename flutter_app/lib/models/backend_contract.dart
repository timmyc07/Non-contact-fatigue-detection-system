/// Typed, lossless wrappers for the backend JSON contract.
///
/// Unknown fields are retained so newer desktop engines remain compatible with
/// older Flutter shells and future native mobile adapters.
class MetricsSnapshot {
  MetricsSnapshot._(Map<String, dynamic> values)
      : values = Map<String, dynamic>.unmodifiable(values);

  factory MetricsSnapshot.fromJson(dynamic raw) {
    final map =
        raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return MetricsSnapshot._(map);
  }

  final Map<String, dynamic> values;

  dynamic operator [](String key) => values[key];

  double? number(String key) => (values[key] as num?)?.toDouble();

  bool flag(String key) => values[key] == true;

  Map<String, dynamic> toJson() => Map<String, dynamic>.from(values);
}

class ControlState {
  ControlState._(Map<String, dynamic> values)
      : values = Map<String, dynamic>.unmodifiable(values);

  factory ControlState.fromJson(dynamic raw) {
    final map =
        raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return ControlState._(map);
  }

  final Map<String, dynamic> values;

  dynamic operator [](String key) => values[key];

  bool flag(String key) => values[key] == true;

  Map<String, dynamic> toJson() => Map<String, dynamic>.from(values);
}

class RecordingMetadata {
  RecordingMetadata._(Map<String, dynamic> values)
      : values = Map<String, dynamic>.unmodifiable(values);

  factory RecordingMetadata.fromJson(dynamic raw) {
    final map =
        raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return RecordingMetadata._(map);
  }

  final Map<String, dynamic> values;

  String? get path => values['path'] as String?;
  String? get sessionName => values['session_name'] as String?;
  String? get durationLabel => values['duration_str'] as String?;
  int get recordCount => (values['record_count'] as num?)?.toInt() ?? 0;

  Map<String, dynamic> toJson() => Map<String, dynamic>.from(values);
}

class ApiError {
  const ApiError({
    required this.code,
    required this.message,
    this.field,
    this.path,
  });

  final String code;
  final String message;
  final String? field;
  final String? path;

  factory ApiError.fromPayload(dynamic payload, int statusCode) {
    final raw = payload is Map ? payload['error'] : null;
    if (raw is Map) {
      return ApiError(
        code:
            raw['code'] is String ? raw['code'] as String : 'http_$statusCode',
        message: raw['message'] is String
            ? raw['message'] as String
            : 'Backend returned HTTP $statusCode.',
        field: raw['field'] as String?,
        path: raw['path'] as String?,
      );
    }
    if (raw is String && raw.isNotEmpty) {
      return ApiError(code: 'http_$statusCode', message: raw);
    }
    return ApiError(
      code: 'http_$statusCode',
      message: 'Backend returned HTTP $statusCode.',
    );
  }
}
