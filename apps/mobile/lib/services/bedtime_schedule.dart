/// 잠자리 알림 스케줄 계산 — 순수함수(플러그인/저장소 의존 0, 단위테스트 대상).
class BedtimeSchedule {
  const BedtimeSchedule._();

  /// 로컬 캐시 키(백엔드 bedtime_notification_* 와 별개, 오프라인 재예약용).
  static const String enabledKey = 'bedtime_notification_enabled_v1';
  static const String hourKey = 'bedtime_notification_hour_v1';
  static const String minuteKey = 'bedtime_notification_minute_v1';

  /// 잠자리 알림 ID(취소/갱신용 고정값).
  static const int notificationId = 7001;

  /// now 기준 다음 hour:minute 발생 시각.
  /// 오늘 시각이 아직 안 지났으면 오늘, 이미 지났거나 같으면 내일을 반환한다.
  static DateTime nextOccurrence(DateTime now, int hour, int minute) {
    var next = DateTime(now.year, now.month, now.day, hour, minute);
    if (!next.isAfter(now)) {
      next = next.add(const Duration(days: 1));
    }
    return next;
  }
}
