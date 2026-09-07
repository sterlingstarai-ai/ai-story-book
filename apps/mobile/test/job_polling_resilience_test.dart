import 'dart:async';
import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/services/job_polling.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'an eight-minute job reaches done through rate limits and a lost connection',
    () async {
      var now = DateTime.utc(2026, 9, 7);
      final start = now;
      var calls = 0;
      final waits = <Duration>[];
      final progress = <int>[];
      await for (final status in pollBookJob(
        now: () => now,
        cancelled: () => false,
        wait: (delay) async {
          waits.add(delay);
          now = now.add(delay);
        },
        fetch: () async {
          calls++;
          if (calls == 3) {
            final options = RequestOptions(path: '/v1/books/job');
            throw DioException(
              requestOptions: options,
              response: Response(
                requestOptions: options,
                statusCode: 429,
                headers: Headers.fromMap({
                  'retry-after': ['60'],
                }),
              ),
            );
          }
          if (calls == 4) {
            throw ApiError(
              code: 'CONNECTION_ERROR',
              message: '',
              statusCode: 0,
            );
          }
          final seconds = now.difference(start).inSeconds;
          return JobStatus(
            jobId: 'job',
            status: seconds >= 480 ? JobState.done : JobState.running,
            progress: seconds >= 480 ? 100 : seconds ~/ 5,
          );
        },
      )) {
        progress.add(status.progress);
      }
      expect(progress.last, 100);
      expect(waits, contains(const Duration(seconds: 60)));
      expect(waits, contains(const Duration(seconds: 6)));
      expect(
        now.difference(start),
        greaterThanOrEqualTo(const Duration(minutes: 8)),
      );
    },
  );

  test('permanent ownership failure is never retried', () async {
    var calls = 0;
    final stream = pollBookJob(
      cancelled: () => false,
      wait: (_) async {},
      fetch: () async {
        calls++;
        throw ApiError(code: 'FORBIDDEN', message: '', statusCode: 403);
      },
    );
    await expectLater(stream.toList(), throwsA(isA<ApiError>()));
    expect(calls, 1);
  });

  test(
    'a persistent outage is bounded by elapsed time, including Retry-After',
    () async {
      var now = DateTime.utc(2026);
      var calls = 0;
      final stream = pollBookJob(
        now: () => now,
        timeout: const Duration(seconds: 10),
        cancelled: () => false,
        wait: (delay) async {
          now = now.add(delay);
        },
        fetch: () async {
          calls++;
          throw ApiError(
            code: 'RATE_LIMIT_EXCEEDED',
            message: '',
            statusCode: 429,
            retryAfter: const Duration(minutes: 2),
          );
        },
      );
      await expectLater(stream.toList(), throwsA(isA<TimeoutException>()));
      expect(calls, 1);
      expect(now, DateTime.utc(2026).add(const Duration(seconds: 10)));
    },
  );

  test('cancellation stops further requests after the current wait', () async {
    var cancelled = false;
    var calls = 0;
    await pollBookJob(
      cancelled: () => cancelled,
      wait: (_) async {
        cancelled = true;
      },
      fetch: () async {
        calls++;
        return JobStatus(jobId: 'job', status: JobState.running, progress: 30);
      },
    ).toList();
    expect(calls, 1);
  });
}
