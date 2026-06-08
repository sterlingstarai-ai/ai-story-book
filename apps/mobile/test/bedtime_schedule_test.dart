import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/services/bedtime_schedule.dart';

void main() {
  group('BedtimeSchedule.nextOccurrence', () {
    test('target later today returns today', () {
      final now = DateTime(2026, 6, 8, 20, 0);
      expect(
        BedtimeSchedule.nextOccurrence(now, 21, 0),
        DateTime(2026, 6, 8, 21, 0),
      );
    });

    test('target earlier today returns tomorrow', () {
      final now = DateTime(2026, 6, 8, 22, 0);
      expect(
        BedtimeSchedule.nextOccurrence(now, 21, 0),
        DateTime(2026, 6, 9, 21, 0),
      );
    });

    test('target equal to now returns tomorrow (no immediate fire)', () {
      final now = DateTime(2026, 6, 8, 21, 0);
      expect(
        BedtimeSchedule.nextOccurrence(now, 21, 0),
        DateTime(2026, 6, 9, 21, 0),
      );
    });

    test('crosses month boundary', () {
      final now = DateTime(2026, 6, 30, 23, 30);
      expect(
        BedtimeSchedule.nextOccurrence(now, 21, 0),
        DateTime(2026, 7, 1, 21, 0),
      );
    });

    test('result is strictly after now at the target time', () {
      final now = DateTime(2026, 1, 1, 9, 15);
      final next = BedtimeSchedule.nextOccurrence(now, 9, 0);
      expect(next.isAfter(now), isTrue);
      expect(next.hour, 9);
      expect(next.minute, 0);
    });
  });
}
