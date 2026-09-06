import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/utils/constants.dart';
import 'package:ai_story_book/widgets/app_shell.dart';

void main() {
  for (final locale in ['ko', 'en', 'ja']) {
    testWidgets('navigation stays usable on a small screen in $locale',
        (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final semantics = tester.ensureSemantics();
      try {
        var routeCount = 0;
        await tester.pumpWidget(MaterialApp(
          locale: Locale(locale),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              textScaler: const TextScaler.linear(1.4),
            ),
            child: child!,
          ),
          home: const AppShell(currentIndex: 1, body: SizedBox.expand()),
          onGenerateRoute: (_) {
            routeCount++;
            return MaterialPageRoute<void>(
                builder: (_) => const Scaffold(body: Text('Destination')));
          },
        ));
        await tester.pumpAndSettle();
        final context = tester.element(find.byType(AppShell));
        final l = AppLocalizations.of(context);
        for (final label in [
          l.navShellHome,
          l.navShellCreate,
          l.navShellLibrary,
          l.navShellCharacters,
        ]) {
          final button = find.bySemanticsLabel(label);
          expect(button, findsOneWidget);
          expect(tester.getSize(button).height,
              greaterThanOrEqualTo(AppSizing.minTouchTarget));
          expect(tester.getSize(button).width,
              greaterThanOrEqualTo(AppSizing.minTouchTarget));
        }
        expect(tester.takeException(), isNull);
        await tester.tap(find.bySemanticsLabel(l.navShellCreate));
        await tester.pumpAndSettle();
        expect(routeCount, 0,
            reason: 'Re-selecting a tab must not stack copies.');
        await tester.tap(find.bySemanticsLabel(l.navShellLibrary));
        await tester.pumpAndSettle();
        expect(routeCount, 1);
        expect(find.text('Destination'), findsOneWidget);
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    });
  }
}
