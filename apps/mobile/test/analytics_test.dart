import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/reading_growth_screen.dart';
import 'package:ai_story_book/services/analytics.dart';

class _FakeAnalytics implements Analytics {
  final events = <String>[];

  @override
  void logEvent(String name, {Map<String, Object?> params = const {}}) {
    events.add(name);
  }
}

GrowthReport _sample() => const GrowthReport(
      booksRead: 1,
      currentStreak: 0,
      longestStreak: 0,
      totalReadingDays: 0,
      vocabLearned: 0,
      quizTotal: 0,
      quizCorrect: 0,
      quizAccuracy: 0.0,
      levelNumber: 1,
      levelLabel: '첫 걸음',
    );

void main() {
  test('LoggingAnalytics.logEvent does not throw', () {
    const LoggingAnalytics().logEvent('x', params: {'a': 1});
  });

  testWidgets('ReadingGrowthScreen logs growth_viewed on open', (tester) async {
    final fake = _FakeAnalytics();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          analyticsProvider.overrideWithValue(fake),
          growthReportProvider.overrideWith((ref) async => _sample()),
        ],
        child: const MaterialApp(
          locale: Locale('ko'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: ReadingGrowthScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(fake.events, contains(AnalyticsEvents.growthViewed));
  });
}
