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
      completion: 0.8,
      levelNumber: 4,
      levelKey: 'building_basics',
      levelLabel: '기초 다지기',
      scoreValue: 60,
    );

PeerComparison _samplePeer() => const PeerComparison(
      ageBand: '5-7',
      peerCount: 42,
      isBaseline: false,
      showRanking: true,
      myBooks: 12,
      peerBooks: 8.0,
      myVocab: 84,
      peerVocab: 56.0,
      myAccuracy: 0.87,
      peerAccuracy: 0.72,
      myScore: 78,
      peerScore: 60,
      topPercent: 8,
      medal: 'gold',
    );

PeerComparison _samplePeerYoung() => const PeerComparison(
      ageBand: '3-5',
      peerCount: 30,
      isBaseline: false,
      showRanking: false,
      myBooks: 4,
      peerBooks: 5.0,
      myVocab: 6,
      peerVocab: 10.0,
      myAccuracy: 0.6,
      peerAccuracy: 0.65,
      myScore: 40,
      peerScore: 55,
      topPercent: 70,
      medal: 'none',
    );

void main() {
  testWidgets('ReadingGrowthScreen renders peer comparison when data available',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          growthReportProvider.overrideWith((ref) async => _sample()),
          peerComparisonProvider.overrideWith((ref) async => _samplePeer()),
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

    // 또래 비교는 화면 하단이라 스크롤해서 빌드시킨다
    await tester.scrollUntilVisible(
      find.byKey(const Key('growth_peer_comparison')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('growth_peer_comparison')), findsOneWidget);
    expect(find.text('또래 비교'), findsOneWidget);
    expect(find.text('상위 8%'), findsOneWidget);
    expect(find.textContaining('또래 42명'), findsOneWidget);
  });

  testWidgets('ReadingGrowthScreen hides ranking for 3-5 (self-growth only)',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          growthReportProvider.overrideWith((ref) async => _sample()),
          peerComparisonProvider
              .overrideWith((ref) async => _samplePeerYoung()),
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
    await tester.scrollUntilVisible(
      find.byKey(const Key('growth_peer_comparison')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();

    // 3-5세는 등수·백분위 미노출(전조작기) → 자기성장 카드만
    expect(find.text('우리 아이 읽기 성장'), findsOneWidget);
    expect(find.textContaining('상위'), findsNothing);
  });

  testWidgets('S2: en 로케일에서 레벨 라벨에 한국어가 노출되지 않는다', (tester) async {
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

    // 서버 label 이 한국어여도(구버전 서버·폴백) 안정 키가 있으면 앱이 자체 l10n 으로 그린다.
    expect(find.text('기초 다지기'), findsNothing,
        reason: 'en 사용자에게 한국어 레벨 라벨이 노출됐다(S2 회귀)');
    expect(find.text('Building basics'), findsOneWidget);
  });

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

  testWidgets('ReadingGrowthScreen renders conversion CTA (share + create)',
      (tester) async {
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
    // 전환 CTA는 화면 최하단 → 스크롤해서 빌드
    await tester.scrollUntilVisible(
      find.byKey(const Key('growth_cta_card')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('growth_cta_card')), findsOneWidget);
    expect(find.byKey(const Key('growth_share_btn')), findsOneWidget);
    expect(find.byKey(const Key('growth_create_btn')), findsOneWidget);
    expect(find.text('성장 공유'), findsOneWidget);
    expect(find.text('새 책 만들기'), findsOneWidget);
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
