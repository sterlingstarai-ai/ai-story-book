import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/services/notification_scheduler.dart';

class _FakeScheduler implements NotificationScheduler {
  int scheduled = 0;
  int cancelled = 0;
  int? lastHour;
  int? lastMinute;

  @override
  Future<void> initialize() async {}

  @override
  Future<bool> requestPermissions() async => true;

  @override
  Future<void> scheduleDailyBedtime({
    required int hour,
    required int minute,
    required String title,
    required String body,
  }) async {
    scheduled++;
    lastHour = hour;
    lastMinute = minute;
  }

  @override
  Future<void> cancelBedtime() async {
    cancelled++;
  }
}

void main() {
  test('NotificationScheduler is injectable and records schedule/cancel',
      () async {
    final fake = _FakeScheduler();

    await fake.scheduleDailyBedtime(
      hour: 21,
      minute: 30,
      title: 't',
      body: 'b',
    );
    await fake.cancelBedtime();

    expect(fake.scheduled, 1);
    expect(fake.cancelled, 1);
    expect(fake.lastHour, 21);
    expect(fake.lastMinute, 30);
  });
}
