import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../models/models.dart';

/// Read retries never submit a second generation or discard the last progress.
/// The deadline bounds outages as well as server work; auth/ownership errors stop.
Stream<JobStatus> pollBookJob({
  required Future<JobStatus> Function() fetch,
  required bool Function() cancelled,
  required Future<void> Function(Duration) wait,
  DateTime Function()? now,
  Duration timeout = const Duration(minutes: 10),
}) async* {
  final clock = now ?? DateTime.now;
  final started = clock();
  var failures = 0;
  while (!cancelled()) {
    final remaining = timeout - clock().difference(started);
    if (remaining <= Duration.zero) {
      throw TimeoutException('Generation status deadline reached');
    }
    Duration delay;
    try {
      final status = await fetch();
      if (cancelled()) return;
      yield status;
      if (status.isComplete || status.isFailed) return;
      failures = 0;
      delay = const Duration(seconds: 3);
    } catch (error) {
      if (cancelled()) return;
      final apiError = error is ApiError
          ? error
          : error is DioException
          ? error.error is ApiError
                ? error.error as ApiError
                : ApiError.fromDioException(error)
          : null;
      if (apiError == null ||
          !(apiError.statusCode == 429 ||
              apiError.statusCode >= 500 ||
              const {
                'TIMEOUT',
                'CONNECTION_ERROR',
                'NETWORK_ERROR',
              }.contains(apiError.code))) {
        rethrow;
      }
      failures += 1;
      final backoff = Duration(
        seconds: min(30, 3 * pow(2, min(failures - 1, 4)).toInt()),
      );
      final requested = apiError.retryAfter;
      delay = requested != null && requested > backoff ? requested : backoff;
    }
    final budget = timeout - clock().difference(started);
    if (budget <= Duration.zero) continue;
    await wait(delay > budget ? budget : delay);
  }
}
