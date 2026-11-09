import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../models/models.dart';

const _foregroundStatusCheckTimeout = Duration(seconds: 5);
const _connectionErrors = {'TIMEOUT', 'CONNECTION_ERROR', 'NETWORK_ERROR'};
const _statusInterval = Duration(seconds: 3);
const _unchangedGenerationInterval = Duration(seconds: 6);
const _longGenerationSteps = {
  'generate_story',
  'generate_image_prompts',
  'generate_images',
  'repair_illustrations',
};

ApiError? retryableJobReadError(Object error) {
  final apiError = switch (error) {
    ApiError() => error,
    DioException(error: final ApiError wrapped) => wrapped,
    DioException() => ApiError.fromDioException(error),
    _ => null,
  };
  if (apiError == null) return null;
  final status = apiError.statusCode;
  return (status == 0 && _connectionErrors.contains(apiError.code)) ||
          status == 429 ||
          status >= 500
      ? apiError
      : null;
}

/// Read retries never submit a second generation or discard the last progress.
/// The deadline bounds outages as well as server work; auth/ownership errors stop.
Stream<JobStatus> pollBookJob({
  required String jobId,
  required Future<JobStatus> Function() fetch,
  required bool Function() cancelled,
  required Future<void> Function(Duration) wait,
  // Returns true when the app resumes instead of the normal timer expiring.
  Future<bool> Function(Duration)? waitBetweenReads,
  void Function()? cancelFetch,
  DateTime Function()? now,
  Duration timeout = const Duration(minutes: 10),
}) async* {
  final stopwatch = Stopwatch()..start();
  final started = now?.call();
  Duration elapsed() =>
      now == null ? stopwatch.elapsed : now().difference(started!);
  var failures = 0;
  var repeatedProgress = 0;
  JobStatus? lastStatus;
  while (!cancelled()) {
    final remaining = timeout - elapsed();
    if (remaining <= Duration.zero) {
      throw TimeoutException('Generation status deadline reached');
    }
    Duration delay;
    var wakeOnForeground = false;
    try {
      final status = await fetch().timeout(remaining);
      if (cancelled()) return;
      if (elapsed() >= timeout) {
        throw TimeoutException('Generation status deadline reached');
      }
      if (status.status == JobState.running &&
          _longGenerationSteps.contains(status.currentStep) &&
          lastStatus?.status == status.status &&
          lastStatus?.currentStep == status.currentStep &&
          lastStatus?.progress == status.progress) {
        repeatedProgress++;
      } else {
        repeatedProgress = 0;
      }
      lastStatus = status;
      yield status;
      if (status.isComplete || status.isFailed) return;
      failures = 0;
      // Keep quick updates around transitions. Slow only repeatedly identical
      // reads while the provider is doing a known long-running step.
      delay = repeatedProgress >= 2
          ? _unchangedGenerationInterval
          : _statusInterval;
      wakeOnForeground = true;
    } on TimeoutException {
      if (cancelled()) return;
      cancelFetch?.call();
      rethrow;
    } catch (error) {
      if (cancelled()) return;
      final apiError = retryableJobReadError(error);
      if (apiError == null) rethrow;
      repeatedProgress = 0;
      failures += 1;
      if (failures == 1) {
        yield JobStatus.rechecking(jobId, lastStatus);
        if (cancelled()) return;
      }
      final backoff = Duration(
        seconds: min(30, 3 * pow(2, min(failures - 1, 4)).toInt()),
      );
      final requested = apiError.retryAfter;
      delay = requested != null && requested > backoff ? requested : backoff;
      // A resume can recover a lost connection. Keep server throttling and
      // Retry-After waits intact.
      wakeOnForeground = requested == null && apiError.statusCode == 0;
    }
    final budget = timeout - elapsed();
    if (budget <= Duration.zero) continue;
    final waitDuration = delay > budget ? budget : delay;
    if (!wakeOnForeground || waitBetweenReads == null) {
      await wait(waitDuration);
      continue;
    }
    final resumed = await waitBetweenReads(waitDuration);
    if (resumed) repeatedProgress = 0;
    if (!resumed || cancelled() || elapsed() < timeout) continue;

    // A suspended app can wake after the polling deadline. Give the same job
    // one bounded read for its terminal result, without starting a new poll.
    try {
      final status = await fetch().timeout(_foregroundStatusCheckTimeout);
      if (cancelled()) return;
      if (status.isComplete || status.isFailed) {
        yield status;
        return;
      }
    } on TimeoutException {
      if (cancelled()) return;
      cancelFetch?.call();
      rethrow;
    }
    throw TimeoutException('Generation status deadline reached');
  }
}
