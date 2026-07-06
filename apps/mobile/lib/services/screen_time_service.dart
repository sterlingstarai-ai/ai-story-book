import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

class ScreenTimeSnapshot {
  final bool enabled;
  final int dailyLimitMinutes;
  final int usedSecondsToday;
  final int extensionSecondsToday;
  final String dayKey;

  const ScreenTimeSnapshot({
    required this.enabled,
    required this.dailyLimitMinutes,
    required this.usedSecondsToday,
    required this.extensionSecondsToday,
    required this.dayKey,
  });

  factory ScreenTimeSnapshot.initial() {
    return ScreenTimeSnapshot(
      enabled: false,
      dailyLimitMinutes: ScreenTimeService.defaultDailyLimitMinutes,
      usedSecondsToday: 0,
      extensionSecondsToday: 0,
      dayKey: ScreenTimeService.todayKey(),
    );
  }

  int get baseLimitSeconds => dailyLimitMinutes * 60;
  int get effectiveLimitSeconds => baseLimitSeconds + extensionSecondsToday;
  int get remainingSeconds => max(0, effectiveLimitSeconds - usedSecondsToday);
  bool get isLocked => enabled && usedSecondsToday >= effectiveLimitSeconds;
  int get usedMinutesRounded => (usedSecondsToday / 60).ceil();
  int get remainingMinutesRounded => (remainingSeconds / 60).ceil();

  ScreenTimeSnapshot copyWith({
    bool? enabled,
    int? dailyLimitMinutes,
    int? usedSecondsToday,
    int? extensionSecondsToday,
    String? dayKey,
  }) {
    return ScreenTimeSnapshot(
      enabled: enabled ?? this.enabled,
      dailyLimitMinutes: dailyLimitMinutes ?? this.dailyLimitMinutes,
      usedSecondsToday: usedSecondsToday ?? this.usedSecondsToday,
      extensionSecondsToday:
          extensionSecondsToday ?? this.extensionSecondsToday,
      dayKey: dayKey ?? this.dayKey,
    );
  }
}

class ScreenTimeService {
  static const keyEnabled = 'screen_time_enabled_v1';
  static const keyDailyLimitMinutes = 'screen_time_daily_limit_minutes_v1';
  static const keyUsedSecondsToday = 'screen_time_used_seconds_today_v1';
  static const keyExtensionSecondsToday =
      'screen_time_extension_seconds_today_v1';
  static const keyDay = 'screen_time_day_v1';
  static const defaultDailyLimitMinutes = 60;

  Future<ScreenTimeSnapshot> load(SharedPreferences prefs) async {
    final today = todayKey();
    final storedDay = prefs.getString(keyDay);
    if (storedDay != today) {
      await _resetDailyUsage(prefs, today: today);
    }

    return ScreenTimeSnapshot(
      enabled: prefs.getBool(keyEnabled) ?? false,
      dailyLimitMinutes:
          prefs.getInt(keyDailyLimitMinutes) ?? defaultDailyLimitMinutes,
      usedSecondsToday: prefs.getInt(keyUsedSecondsToday) ?? 0,
      extensionSecondsToday: prefs.getInt(keyExtensionSecondsToday) ?? 0,
      dayKey: today,
    );
  }

  Future<ScreenTimeSnapshot> syncSettings(
    SharedPreferences prefs, {
    required bool enabled,
    required int dailyLimitMinutes,
  }) async {
    await prefs.setBool(keyEnabled, enabled);
    await prefs.setInt(
      keyDailyLimitMinutes,
      dailyLimitMinutes.clamp(1, 24 * 60),
    );
    return load(prefs);
  }

  Future<ScreenTimeSnapshot> addUsageSeconds(
    SharedPreferences prefs, {
    required int seconds,
  }) async {
    if (seconds <= 0) {
      return load(prefs);
    }
    final current = await load(prefs);
    final nextUsed = max(0, current.usedSecondsToday + seconds);
    await prefs.setInt(keyUsedSecondsToday, nextUsed);
    return current.copyWith(usedSecondsToday: nextUsed);
  }

  Future<ScreenTimeSnapshot> addExtensionMinutes(
    SharedPreferences prefs, {
    required int minutes,
  }) async {
    if (minutes <= 0) {
      return load(prefs);
    }
    final current = await load(prefs);
    final next = max(0, current.extensionSecondsToday + (minutes * 60));
    await prefs.setInt(keyExtensionSecondsToday, next);
    return current.copyWith(extensionSecondsToday: next);
  }

  Future<ScreenTimeSnapshot> resetToday(SharedPreferences prefs) async {
    final today = todayKey();
    await _resetDailyUsage(prefs, today: today);
    return load(prefs);
  }

  Future<void> _resetDailyUsage(
    SharedPreferences prefs, {
    required String today,
  }) async {
    await prefs.setString(keyDay, today);
    await prefs.setInt(keyUsedSecondsToday, 0);
    await prefs.setInt(keyExtensionSecondsToday, 0);
  }

  static String todayKey() {
    final now = DateTime.now();
    final mm = now.month.toString().padLeft(2, '0');
    final dd = now.day.toString().padLeft(2, '0');
    return '${now.year}-$mm-$dd';
  }
}
