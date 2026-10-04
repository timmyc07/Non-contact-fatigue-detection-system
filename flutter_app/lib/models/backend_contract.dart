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
  }) : values = const <String, dynamic>{};

  ApiError._({
    required this.code,
    required this.message,
    required Map<String, dynamic> values,
    this.field,
    this.path,
  }) : values = Map<String, dynamic>.unmodifiable(values);

  final String code;
  final String message;
  final String? field;
  final String? path;
  final Map<String, dynamic> values;

  dynamic operator [](String key) => values[key];

  /// Re-serializes the structured error without dropping newer backend fields.
  Map<String, dynamic> toJson() {
    final result = Map<String, dynamic>.from(values);
    result['code'] = code;
    result['message'] = message;
    if (field == null) {
      result.remove('field');
    } else {
      result['field'] = field;
    }
    if (path == null) {
      result.remove('path');
    } else {
      result['path'] = path;
    }
    return result;
  }

  factory ApiError.fromPayload(dynamic payload, int statusCode) {
    final raw = payload is Map ? payload['error'] : null;
    if (raw is Map) {
      final values = <String, dynamic>{};
      raw.forEach((key, value) {
        if (key is String) values[key] = value;
      });
      return ApiError._(
        code: values['code'] is String
            ? values['code'] as String
            : 'http_$statusCode',
        message: values['message'] is String
            ? values['message'] as String
            : 'Backend returned HTTP $statusCode.',
        field: values['field'] is String ? values['field'] as String : null,
        path: values['path'] is String ? values['path'] as String : null,
        values: values,
      );
    }
    if (raw is String && raw.isNotEmpty) {
      return ApiError._(
        code: 'http_$statusCode',
        message: raw,
        values: <String, dynamic>{},
      );
    }
    return ApiError._(
      code: 'http_$statusCode',
      message: 'Backend returned HTTP $statusCode.',
      values: <String, dynamic>{},
    );
  }
}
