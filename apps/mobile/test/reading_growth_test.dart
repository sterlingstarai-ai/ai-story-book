import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/reading_growth_screen.dart';

GrowthReport _sample() => const GrowthReport(
      booksRead: 7,
      currentStreak: 3,
      longestStreak: 5,
      totalReadingDays: 9,
      vocabLearned: 12,
      quizTotal: 8,
      quizCorrect: 6,
      quizAccuracy: 0.75,
      levelNumber: 4,
      levelLabel: '기초 다지기',
    );

void main() {
  testWidgets('ReadingGrowthScreen renders level and stats', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
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
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('growth_level_hero')), findsOneWidget);
    expect(find.text('Lv.4'), findsOneWidget);
    expect(find.text('기초 다지기'), findsOneWidget);
    expect(find.text('7권'), findsOneWidget); // 읽은 책
    expect(find.text('75%'), findsOneWidget); // 퀴즈 정확도
    expect(find.text('12개'), findsOneWidget); // 학습 어휘
  });

  testWidgets('ReadingGrowthScreen localizes to English', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          growthReportProvider.overrideWith((ref) async => _sample()),
        ],
        child: const MaterialApp(
          locale: Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: ReadingGrowthScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Reading Growth'), findsOneWidget); // AppBar
    expect(find.text('Books read'), findsOneWidget); // 스탯 라벨
  });
}
