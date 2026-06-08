import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../core/app_telemetry.dart';
import 'bedtime_schedule.dart';

/// 로컬 알림 스케줄러 추상화 — 플러그인을 인터페이스 뒤로 캡슐화(테스트에서 Fake 주입).
abstract class NotificationScheduler {
  Future<void> initialize();
  Future<bool> requestPermissions();
  Future<void> scheduleDailyBedtime({
    required int hour,
    required int minute,
    required String title,
    required String body,
  });
  Future<void> cancelBedtime();
}

/// 기본 구현: flutter_local_notifications 기반. 비모바일/실패 시 안전하게 무시한다.
class LocalNotificationScheduler implements NotificationScheduler {
  LocalNotificationScheduler();

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  bool get _isMobile =>
      defaultTargetPlatform == TargetPlatform.iOS ||
      defaultTargetPlatform == TargetPlatform.android;

  @override
  Future<void> initialize() async {
    if (_initialized || !_isMobile) {
      return;
    }
    try {
      tzdata.initializeTimeZones();
      const android = AndroidInitializationSettings('@mipmap/ic_launcher');
      const darwin = DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      );
      await _plugin.initialize(
        const InitializationSettings(android: android, iOS: darwin),
      );
      _initialized = true;
    } catch (e) {
      AppTelemetry.logInfo('notification_init_failed', data: {'error': '$e'});
    }
  }

  @override
  Future<bool> requestPermissions() async {
    if (!_isMobile) {
      return false;
    }
    try {
      await initialize();
      final ios = _plugin.resolvePlatformSpecificImplementation<
          IOSFlutterLocalNotificationsPlugin>();
      if (ios != null) {
        final granted =
            await ios.requestPermissions(alert: true, badge: true, sound: true);
        return granted ?? false;
      }
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      if (android != null) {
        final granted = await android.requestNotificationsPermission();
        return granted ?? false;
      }
      return false;
    } catch (e) {
      AppTelemetry.logInfo('notification_permission_failed', data: {'error': '$e'});
      return false;
    }
  }

  @override
  Future<void> scheduleDailyBedtime({
    required int hour,
    required int minute,
    required String title,
    required String body,
  }) async {
    if (!_isMobile) {
      return;
    }
    try {
      await initialize();
      final next = BedtimeSchedule.nextOccurrence(DateTime.now(), hour, minute);
      final scheduled = tz.TZDateTime.from(next, tz.local);
      await _plugin.zonedSchedule(
        BedtimeSchedule.notificationId,
        title,
        body,
        scheduled,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'bedtime_reminder',
            '잠자리 알림',
            channelDescription: '매일 밤 오늘의 동화 읽기 리마인더',
            importance: Importance.defaultImportance,
            priority: Priority.defaultPriority,
          ),
          iOS: DarwinNotificationDetails(),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
        matchDateTimeComponents: DateTimeComponents.time,
      );
    } catch (e) {
      AppTelemetry.logInfo('notification_schedule_failed', data: {'error': '$e'});
    }
  }

  @override
  Future<void> cancelBedtime() async {
    if (!_isMobile) {
      return;
    }
    try {
      await initialize();
      await _plugin.cancel(BedtimeSchedule.notificationId);
    } catch (e) {
      AppTelemetry.logInfo('notification_cancel_failed', data: {'error': '$e'});
    }
  }
}
