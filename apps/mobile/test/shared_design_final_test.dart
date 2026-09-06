import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/services/screen_time_service.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/utils/constants.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:ai_story_book/widgets/screen_time_lock.dart';
import 'support/design_capture.dart';

void main() {
  setUpAll(loadDesignFonts);
  for (final brightness in Brightness.values) {
    test('semantic text contrast meets normal text threshold in $brightness',
        () {
      final p = AppPalette(brightness == Brightness.dark);
      double contrast(Color a, Color b) {
        final first = a.computeLuminance(),
            second = Color.alphaBlend(b, p.surface).computeLuminance();
        return ((first > second ? first : second) + .05) /
            ((first > second ? second : first) + .05);
      }

      for (final background in [p.background, p.surface, p.primaryLight]) {
        expect(contrast(p.textPrimary, background), greaterThanOrEqualTo(4.5));
        expect(
            contrast(p.textSecondary, background), greaterThanOrEqualTo(4.5));
        expect(contrast(p.primary, background), greaterThanOrEqualTo(4.5));
      }
    });
    for (final locale in const [Locale('ko'), Locale('en'), Locale('ja')]) {
      testWidgets(
          'shared actions and lock remain reachable ${locale.languageCode} $brightness',
          (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(320, 480);
        tester.platformDispatcher.textScaleFactorTestValue = 1.4;
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final l = await AppLocalizations.delegate.load(locale);
        var taps = 0;
        Widget app(Widget body) => designCaptureBoundary(MaterialApp(
              debugShowCheckedModeBanner: false,
              locale: locale,
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              theme: buildAppTheme(brightness),
              home: Scaffold(body: body),
            ));
        await tester.pumpWidget(app(SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(children: [
            Text(l.createTopicLabel, style: AppTextStyles.heading2),
            const SizedBox(height: 16),
            TextField(decoration: InputDecoration(hintText: l.createTopicHint)),
            const SizedBox(height: 24),
            PrimaryButton(
                text: l.viewerCreateNextStory, onPressed: () => taps++),
            const SizedBox(height: 16),
            SecondaryButton(text: l.viewerGoToLibrary, onPressed: () => taps++),
          ]),
        )));
        await tester.pumpAndSettle();
        for (final finder in [
          find.byType(PrimaryButton),
          find.byType(SecondaryButton)
        ]) {
          await tester.ensureVisible(finder);
          await tester.tap(finder);
          expect(tester.getSize(finder).height, greaterThanOrEqualTo(64));
        }
        expect(taps, 2);
        expect(tester.takeException(), isNull);
        await captureDesign(
            tester, 'shared-${locale.languageCode}-${brightness.name}');
        await tester.pumpWidget(app(Stack(children: [
          ScreenTimeLockOverlay(
            snapshot: const ScreenTimeSnapshot(
                enabled: true,
                dailyLimitMinutes: 30,
                usedSecondsToday: 1800,
                extensionSecondsToday: 0,
                dayKey: '2026-09-06'),
            onExtend: () => taps++,
          ),
        ])));
        await tester.pumpAndSettle();
        final extend = find.text(l.lockExtendButton);
        await tester.ensureVisible(extend);
        await tester.tap(extend);
        expect(taps, 3);
        expect(tester.takeException(), isNull);
        await captureDesign(
            tester, 'lock-${locale.languageCode}-${brightness.name}');
      });
    }
  }
}
