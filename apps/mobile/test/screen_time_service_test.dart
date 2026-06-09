import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/services/screen_time_service.dart';

void main() {
  group('ScreenTimeService', () {
    late ScreenTimeService service;

    setUp(() {
      service = ScreenTimeService();
      SharedPreferences.setMockInitialValues({});
    });

    test('load resets usage when stored day is stale', () async {
      SharedPreferences.setMockInitialValues({
        ScreenTimeService.keyDay: '2026-01-01',
        ScreenTimeService.keyUsedSecondsToday: 777,
        ScreenTimeService.keyExtensionSecondsToday: 120,
      });
      final prefs = await SharedPreferences.getInstance();

      final snapshot = await service.load(prefs);

      expect(snapshot.dayKey, ScreenTimeService.todayKey());
      expect(snapshot.usedSecondsToday, 0);
      expect(snapshot.extensionSecondsToday, 0);
    });

    test('enables limit and locks after exceeding used time', () async {
      final prefs = await SharedPreferences.getInstance();
      await service.syncSettings(
        prefs,
        enabled: true,
        dailyLimitMinutes: 1,
      );

      final afterUsage = await service.addUsageSeconds(
        prefs,
        seconds: 70,
      );

      expect(afterUsage.enabled, isTrue);
      expect(afterUsage.dailyLimitMinutes, 1);
      expect(afterUsage.isLocked, isTrue);
      expect(afterUsage.remainingSeconds, 0);
    });

    test('extension unlocks screen time after lock', () async {
      final prefs = await SharedPreferences.getInstance();
      await service.syncSettings(
        prefs,
        enabled: true,
        dailyLimitMinutes: 1,
      );
      await service.addUsageSeconds(prefs, seconds: 70);

      final extended = await service.addExtensionMinutes(
        prefs,
        minutes: 10,
      );

      expect(extended.isLocked, isFalse);
      expect(extended.remainingSeconds, greaterThan(0));
      expect(extended.extensionSecondsToday, 600);
    });
  });
}
