import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/onboarding_screen.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _scrollViewKey = Key('ui-preflight-scroll-view');

Widget _buildSheetHarness({
  double textScale = 1.0,
  String? title,
  String? subtitle,
}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(
        size: const Size(320, 480),
        textScaler: TextScaler.linear(textScale),
      ),
      child: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Material(
            color: Colors.white,
            child: AdaptiveModalSheet(
              title: title,
              subtitle: subtitle,
              scrollViewKey: _scrollViewKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: List.generate(
                  12,
                  (index) => ListTile(
                    title: Text('액션 ${index + 1}'),
                    subtitle: const Text('프리플라이트용 더미 액션'),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

Finder _sheetScrollable() {
  return find.descendant(
    of: find.byKey(_scrollViewKey),
    matching: find.byType(Scrollable),
  );
}

void _setPhoneViewport(WidgetTester tester) {
  tester.view.devicePixelRatio = 1.0;
  tester.view.physicalSize = const Size(320, 480);
}

void _resetViewport(WidgetTester tester) {
  tester.view.resetPhysicalSize();
  tester.view.resetDevicePixelRatio();
}

void main() {
  group('AdaptiveModalSheet', () {
    testWidgets('keeps the final action reachable on a short viewport',
        (tester) async {
      _setPhoneViewport(tester);
      addTearDown(() => _resetViewport(tester));

      await tester.pumpWidget(_buildSheetHarness(title: '옵션'));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(
        find.text('액션 12'),
        240,
        scrollable: _sheetScrollable(),
      );
      await tester.pumpAndSettle();

      expect(find.text('액션 12'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    // R4: 고정 1.4 하나만 검증하면 iOS 접근성 상단 구간(AX1~AX5, 최대 ~3.1배)을
    // 전혀 커버하지 못한다. 실제로 온보딩 화면이 AX5 에서만 오버플로우했다.
    for (final scale in const [1.0, 1.4, 2.0, 2.6, 3.2]) {
      testWidgets('handles text scale x$scale without overflow', (tester) async {
        _setPhoneViewport(tester);
        addTearDown(() => _resetViewport(tester));

        await tester.pumpWidget(
          _buildSheetHarness(
            textScale: scale,
            title: '공유하기',
            subtitle: '작은 화면에서도 마지막 버튼까지 확인할 수 있어야 해요.',
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('공유하기'), findsOneWidget);
        await tester.scrollUntilVisible(
          find.text('액션 12'),
          240,
          scrollable: _sheetScrollable(),
        );
        await tester.pumpAndSettle();

        expect(find.text('액션 12'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  });

  _onboardingTests();
}

// ---------------------------------------------------------------------------
// R4: 온보딩 화면 접근성 글자 크기 오버플로우
// ---------------------------------------------------------------------------
// 2026-08-11 플랫폼 E2E: iOS 시뮬레이터의 Dynamic Type 을 최대(AX5,
// accessibility-extra-extra-extra-large)로 두면 온보딩 슬라이드가
// 'BOTTOM OVERFLOWED BY 82 PIXELS' 로 잘렸다(AX4 이하는 정상). release 빌드에서는
// 노란 배너 없이 조용히 잘리므로 자동 검증이 없으면 영원히 안 보인다.
//
// red-proof: onboarding_screen.dart 의 SingleChildScrollView/ConstrainedBox 를 걷어내고
// 예전 고정 Column 으로 되돌리면 x3.2 케이스가 overflow 예외로 FAIL 한다.

Widget _buildOnboardingHarness({
  required SharedPreferences prefs,
  required double textScale,
}) {
  return ProviderScope(
    overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
    child: MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: MediaQuery(
        data: MediaQueryData(
          size: const Size(320, 480),
          textScaler: TextScaler.linear(textScale),
        ),
        child: const OnboardingScreen(),
      ),
    ),
  );
}

void _onboardingTests() {
  group('OnboardingScreen accessibility text scales', () {
    for (final scale in const [1.0, 1.4, 2.0, 3.2]) {
      testWidgets('renders without overflow at text scale x$scale',
          (tester) async {
        SharedPreferences.setMockInitialValues(<String, Object>{});
        final prefs = await SharedPreferences.getInstance();

        await tester.pumpWidget(
          _buildOnboardingHarness(prefs: prefs, textScale: scale),
        );
        await tester.pumpAndSettle();

        // RenderFlex overflow 는 예외로 보고된다 — 잡히면 잘린 UI.
        expect(
          tester.takeException(),
          isNull,
          reason: '텍스트 배율 x$scale 에서 온보딩이 오버플로우했다',
        );
        // 마지막 CTA 가 여전히 존재해야 한다(스크롤 구조로 바뀌어도 사라지면 안 됨).
        expect(find.byType(ElevatedButton), findsOneWidget);
      });
    }
  });
}
