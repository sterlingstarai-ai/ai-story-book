class JsonParsing {
  const JsonParsing._();

  static Map<String, dynamic> asMap(dynamic value, {required String field}) {
    if (value is Map<String, dynamic>) {
      return value;
    }
    if (value is Map) {
      final mapped = <String, dynamic>{};
      for (final entry in value.entries) {
        if (entry.key == null) {
          continue;
        }
        mapped[entry.key.toString()] = entry.value;
      }
      return mapped;
    }
    throw FormatException('Expected JSON object for $field');
  }

  static Map<String, dynamic>? asNullableMap(
    dynamic value, {
    required String field,
  }) {
    if (value == null) {
      return null;
    }
    return asMap(value, field: field);
  }

  static List<dynamic> asList(dynamic value, {required String field}) {
    if (value is List<dynamic>) {
      return value;
    }
    if (value is List) {
      return List<dynamic>.from(value);
    }
    throw FormatException('Expected JSON array for $field');
  }

  static List<dynamic>? asNullableList(dynamic value, {required String field}) {
    if (value == null) {
      return null;
    }
    return asList(value, field: field);
  }

  static String asRequiredString(dynamic value, {required String field}) {
    if (value is String) {
      return value;
    }
    if (value == null) {
      throw FormatException('Missing required field: $field');
    }
    return value.toString();
  }

  static String? asOptionalString(dynamic value) {
    if (value == null) {
      return null;
    }
    if (value is String) {
      return value;
    }
    return value.toString();
  }

  static int asRequiredInt(dynamic value, {required String field}) {
    final parsed = asOptionalInt(value, field: field);
    if (parsed != null) {
      return parsed;
    }
    throw FormatException('Missing required field: $field');
  }

  static int? asOptionalInt(dynamic value, {required String field}) {
    if (value == null) {
      return null;
    }
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      final parsed = int.tryParse(value);
      if (parsed != null) {
        return parsed;
      }
    }
    throw FormatException('Expected integer for $field');
  }

  static bool? asOptionalBool(dynamic value, {required String field}) {
    if (value == null) {
      return null;
    }
    if (value is bool) {
      return value;
    }
    if (value is num) {
      if (value == 0) {
        return false;
      }
      if (value == 1) {
        return true;
      }
    }
    if (value is String) {
      final normalized = value.trim().toLowerCase();
      if (normalized == 'true' || normalized == '1') {
        return true;
      }
      if (normalized == 'false' || normalized == '0') {
        return false;
      }
    }
    throw FormatException('Expected boolean for $field');
  }

  static DateTime asRequiredDateTime(dynamic value, {required String field}) {
    final raw = asRequiredString(value, field: field);
    final parsed = DateTime.tryParse(raw);
    if (parsed != null) {
      return parsed;
    }
    throw FormatException('Expected ISO-8601 datetime for $field');
  }
}
