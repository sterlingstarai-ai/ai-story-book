import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_telemetry.dart';

/// 제품 분석 이벤트 추상화 — 리텐션·퍼널 측정의 단일 진입점.
///
/// 기본 구현(LoggingAnalytics)은 구조화 로그로 남긴다. **실제 백엔드
/// (firebase_analytics / posthog / amplitude) 연동은 이 인터페이스 구현 하나를
/// 교체하고 analyticsProvider override 만으로 드롭인** 된다.
abstract class Analytics {
  void logEvent(String name, {Map<String, Object?> params});
}

/// 기본 구현: 구조화 로그(AppTelemetry)로 이벤트를 남긴다.
class LoggingAnalytics implements Analytics {
  const LoggingAnalytics();

  @override
  void logEvent(String name, {Map<String, Object?> params = const {}}) {
    AppTelemetry.logInfo('analytics_event', data: {'event': name, ...params});
  }
}

/// 측정할 핵심 퍼널 이벤트 이름.
class AnalyticsEvents {
  static const appOpen = 'app_open';
  static const bookCreateRequested = 'book_create_requested';
  static const todayStoryRequested = 'today_story_requested';
  static const paywallShown = 'paywall_shown';
  static const readingStarted = 'reading_started';
  static const readingCompleted = 'reading_completed';
  static const streakViewed = 'streak_viewed';
  static const growthViewed = 'growth_viewed';
  static const subscriptionStarted = 'subscription_started';
}

final analyticsProvider =
    Provider<Analytics>((ref) => const LoggingAnalytics());
