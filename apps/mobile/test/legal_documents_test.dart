import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/screens/legal_document_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget app(Widget child, {double scale = 1}) => ProviderScope(
  child: MaterialApp(
    locale: const Locale('ko'),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(
        context,
      ).copyWith(textScaler: TextScaler.linear(scale)),
      child: child!,
    ),
    home: child,
  ),
);

Future<void> settleDocument(WidgetTester tester, LegalDocument document) async {
  // Build the reader before yielding to real asset I/O. pumpAndSettle advances
  // the fake frame clock; it cannot deliver callbacks queued in the real zone.
  await tester.pump();
  await tester.runAsync(() async {
    await rootBundle.loadString('assets/legal/${document.name}.ko.json');
    await Future<void>.delayed(Duration.zero);
  });
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    // Each widget test owns a new fake-async zone. Do not carry a cached asset
    // Future created by a previous test into the next zone.
    for (final document in LegalDocument.values) {
      rootBundle.evict('assets/legal/${document.name}.ko.json');
    }
  });
  for (final document in LegalDocument.values) {
    testWidgets(
      'approved ${document.name} opens offline and scrolls at 2.35x',
      (tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          app(LegalDocumentScreen(document: document), scale: 2.35),
        );
        await settleDocument(tester, document);
        expect(find.textContaining('support@aistorybook.com'), findsNothing);
        expect(find.textContaining('출시 전 검토본입니다.'), findsNothing);
        expect(
          find.textContaining(RegExp(r'^시행일 \d{4}-\d{2}-\d{2}$')),
          findsOneWidget,
        );
        final lastHeading = find.text(
          document == LegalDocument.privacy ? '6. 보호 조치와 변경' : '6. 변경과 문의',
        );
        await tester.scrollUntilVisible(
          lastHeading,
          600,
          scrollable: find.byType(Scrollable),
          maxScrolls: 120,
        );
        expect(lastHeading.hitTestable(), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'consent opens full document before granting consent and required-only excludes photos',
    (tester) async {
      await tester.pumpWidget(app(const ConsentScreen()));
      await tester.pumpAndSettle();
      await tester.tap(find.text('개인정보처리방침'));
      await settleDocument(tester, LegalDocument.privacy);
      expect(find.byType(LegalDocumentScreen), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      final all = find.widgetWithText(CheckboxListTile, '필수 항목에 모두 동의');
      await tester.ensureVisible(all);
      await tester.tap(all);
      await tester.pump();
      final tiles = tester
          .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
          .toList();
      expect(tiles.map((t) => t.value), [true, true, true, false]);
      expect(tester.takeException(), isNull);
    },
  );
}
