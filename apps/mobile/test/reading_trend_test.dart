import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/services/reading_trend.dart';

void main() {
  group('weeklyReadingCounts', () {
    final now = DateTime(2026, 6, 8);

    test('buckets reads into correct weeks; last element = current week', () {
      final counts = weeklyReadingCounts([
        now, // 이번 주
        now.subtract(const Duration(days: 2)), // 이번 주
        now.subtract(const Duration(days: 8)), // 1주 전
        now.subtract(const Duration(days: 15)), // 2주 전
        now.subtract(const Duration(days: 40)), // 가장 오래된 버킷
      ], now, weeks: 6);

      expect(counts.length, 6);
      expect(counts.last, 2); // 이번 주 2회
      expect(counts[4], 1); // 1주 전
      expect(counts[3], 1); // 2주 전
      expect(counts.fold<int>(0, (a, b) => a + b), 5);
    });

    test('ignores future and out-of-range dates', () {
      final counts = weeklyReadingCounts([
        now.add(const Duration(days: 3)), // 미래 무시
        now.subtract(const Duration(days: 100)), // 6주 범위 밖 무시
      ], now, weeks: 6);
      expect(counts.every((c) => c == 0), isTrue);
    });

    test('empty input returns all zeros', () {
      expect(weeklyReadingCounts([], now), [0, 0, 0, 0, 0, 0]);
    });
  });
}
