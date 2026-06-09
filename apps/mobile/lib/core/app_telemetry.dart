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
      error: error,
      stackTrace: stackTrace,
      level: 1000,
    );
    if (kDebugMode) {
      debugPrint('$formatted\n$error');
    }
  }

  static String _formatMessage(String message, Map<String, Object?> data) {
    if (data.isEmpty) {
      return message;
    }
    return '$message ${data.toString()}';
  }
}
