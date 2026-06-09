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
}
