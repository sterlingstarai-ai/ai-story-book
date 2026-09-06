import 'dart:developer' as developer;

import 'package:flutter/foundation.dart';

class AppTelemetry {
  static const _loggerName = 'ai_story_book';

  static void logInfo(
    String message, {
    Map<String, Object?> data = const {},
  }) {
    final formatted = _formatMessage(message, data);
    developer.log(formatted, name: _loggerName);
    if (kDebugMode) {
      debugPrint(formatted);
    }
  }

  static void recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    Map<String, Object?> data = const {},
  }) {
    final formatted = _formatMessage(context, data);
    developer.log(
      formatted,
      name: _loggerName,
      error: error.runtimeType.toString(),
      stackTrace: StackTrace.fromString(_redactString(stackTrace.toString())),
      level: 1000,
    );
    if (kDebugMode) {
      debugPrint('$formatted\n${error.runtimeType}');
    }
  }

  static String _formatMessage(String message, Map<String, Object?> data) {
    if (data.isEmpty) {
      return message;
    }
    return '$message ${sanitizeData(data)}';
  }

  static String _redactString(String value) => value
      .replaceAll(RegExp(r'''https?://[^\s"'<>]+'''), '[redacted-url]')
      .replaceAll(RegExp(r'/share/[^/\s?]+'), '/share/[redacted]')
      .replaceAll(RegExp(r'(?:ASB-R1-|asb_device_)[A-Za-z0-9_-]+'),
          '[redacted-credential]');

  @visibleForTesting
  static Map<String, Object?> sanitizeData(Map<String, Object?> data) {
    const sensitive = {
      'userkey',
      'newuserkey',
      'recoverycode',
      'xuserkey',
      'authorization',
      'cookie',
      'token',
      'sharetoken',
      'apikey',
      'secret',
      'password',
      'receipt',
      'body',
      'payload',
      'response',
      'text',
      'prompt',
      'name',
      'title',
      'description',
      'imagebase64',
    };
    Object? clean(String key, Object? value) {
      final normalized = key.toLowerCase().replaceAll(RegExp(r'[-_]'), '');
      if (sensitive.contains(normalized) ||
          normalized.endsWith('token') ||
          normalized.endsWith('apikey') ||
          normalized.endsWith('secret')) {
        return '[redacted]';
      }
      if (value is Map<String, Object?>) return sanitizeData(value);
      if (value is String) return _redactString(value);
      if (value is List) return value.map((item) => clean(key, item)).toList();
      return value;
    }

    return data.map((key, value) => MapEntry(key, clean(key, value)));
  }
}
