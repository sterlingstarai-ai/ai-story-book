import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';

Widget _app(Locale locale) => MaterialApp(
      locale: locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Builder(
        builder: (context) =>
            Text(AppLocalizations.of(context).readingGrowthTitle),
      ),
    );

void main() {
  testWidgets('resolves Korean strings', (tester) async {
    await tester.pumpWidget(_app(const Locale('ko')));
    await tester.pump();
    expect(find.text('읽기 성장'), findsOneWidget);
  });

  testWidgets('resolves English strings', (tester) async {
    await tester.pumpWidget(_app(const Locale('en')));
    await tester.pump();
    expect(find.text('Reading Growth'), findsOneWidget);
  });

  test('supports ko, en, ja locales', () {
    final codes =
        AppLocalizations.supportedLocales.map((l) => l.languageCode).toSet();
    expect(codes.containsAll({'ko', 'en', 'ja'}), isTrue);
  });

  testWidgets('loading step keys localize (M32)', (tester) async {
    for (final code in ['ko', 'en', 'ja']) {
      final l = await AppLocalizations.delegate.load(Locale(code));
      // 신규 키가 3로케일 모두에 존재(백엔드 learning_assets 키 매핑용).
      expect(l.loadingStepLearningAssets.isNotEmpty, isTrue);
      expect(l.loadingStepGenerateStory.isNotEmpty, isTrue);
    }
  });
}
