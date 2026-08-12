/// R3-5: 부모 인증 게이트가 **실제로 화면을 막는지** 검증.
///
/// 왜 새로 필요한가(2026-08-11 플랫폼 E2E 반송분):
/// credits_screen·reading_growth_screen 의 게이트는 라우트 이름 조건부다.
///   final routeName = ModalRoute.of(context)?.settings.name;
///   if (routeName != '/credits') { ... return; }   // 게이트 건너뜀
/// 그런데 기존 위젯 테스트는 전부 `home: CreditsScreen()` 처럼 **라우트 이름 없이**
/// 임베드해서 pump 했다. 즉 게이트 분기가 단 한 번도 실행된 적이 없고,
/// "부모 인증이 필요한 화면이 차단된다"를 주장하는 테스트는 존재하지 않았다.
///
/// 여기서는 실제 라우트 이름('/credits', '/reading-growth')을 단 MaterialPageRoute 로
/// 진입시켜 게이트 분기를 태운다.
///
/// red-proof: 각 화면의 `if (routeName != '/...') return;` 을 지우거나 게이트 호출
/// 자체를 제거하면 아래 '다이얼로그 노출'·'취소 시 pop' 테스트가 FAIL 한다.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/credits_screen.dart';
import 'package:ai_story_book/screens/reading_growth_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';

/// 네트워크를 타지 않는 최소 스텁 — 게이트 동작만 관측한다.
class _FakeApiClient extends ApiClient {
  _FakeApiClient()
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  int creditsStatusCalls = 0;

  @override
  Future<Map<String, dynamic>> getCreditsStatus() async {
    creditsStatusCalls++;
    return <String, dynamic>{'credits': 3, 'subscription': null};
  }

  @override
  Future<List<dynamic>> getTransactions({int limit = 20, int offset = 0}) async =>
      <dynamic>[];
}

GrowthReport _report() => const GrowthReport(
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

/// 실제 라우트 이름을 달아 화면을 **push** 한다(게이트 분기 실행 조건).
///
/// 홈 라우트를 깔고 그 위로 push 하는 것이 중요하다: 화면이 스택의 유일한 라우트면
/// 게이트가 `Navigator.pop` 을 불러도 아무 일도 일어나지 않아 '차단'을 관측할 수 없다.
final _navKey = GlobalKey<NavigatorState>();

Widget _routedHarness({
  required SharedPreferences prefs,
  required String routeName,
  required Widget screen,
  List<Override> overrides = const [],
}) {
  return ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      ...overrides,
    ],
    child: MaterialApp(
      navigatorKey: _navKey,
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      initialRoute: '/',
      onGenerateRoute: (settings) {
        if (settings.name == routeName) {
          return MaterialPageRoute<void>(
            settings: settings, // ← 라우트 이름이 화면에 전달되는 지점
            builder: (_) => screen,
          );
        }
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => const Scaffold(body: Text('home-marker')),
        );
      },
    ),
  );
}

/// 로딩 인디케이터가 무한 애니메이션이라 pumpAndSettle 을 쓸 수 없는 화면용.
Future<void> _pumpFrames(WidgetTester tester, {int frames = 8}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<SharedPreferences> _prefs([Map<String, Object> values = const {}]) async {
  SharedPreferences.setMockInitialValues(values);
  return SharedPreferences.getInstance();
}

/// 세션 인증이 이미 통과된 상태의 prefs(게이트 없이 통과해야 함).
Future<SharedPreferences> _verifiedPrefs() => _prefs({
      ParentalControlService.ageGateSessionKey:
          DateTime.now().millisecondsSinceEpoch,
    });

void main() {
  group('부모 인증 게이트 — 실제 라우트로 진입', () {
    testWidgets('reading-growth: 미인증이면 나이 게이트 다이얼로그가 뜬다',
        (tester) async {
      final prefs = await _prefs();
      await tester.pumpWidget(
        _routedHarness(
          prefs: prefs,
          routeName: '/reading-growth',
          screen: const ReadingGrowthScreen(),
          overrides: [
            growthReportProvider.overrideWith((ref) async => _report()),
            weeklyReadingTrendProvider.overrideWith((ref) async => <int>[]),
          ],
        ),
      );
      await tester.pumpAndSettle();
      unawaited(_navKey.currentState!.pushNamed('/reading-growth'));
      await tester.pumpAndSettle();

      expect(
        find.byType(AlertDialog),
        findsOneWidget,
        reason: '부모 인증 게이트가 뜨지 않았다 — 아이가 상위%·강등을 직면한다',
      );
    });

    testWidgets('reading-growth: 이미 인증된 세션이면 다이얼로그 없이 통과',
        (tester) async {
      final prefs = await _verifiedPrefs();
      await tester.pumpWidget(
        _routedHarness(
          prefs: prefs,
          routeName: '/reading-growth',
          screen: const ReadingGrowthScreen(),
          overrides: [
            growthReportProvider.overrideWith((ref) async => _report()),
            weeklyReadingTrendProvider.overrideWith((ref) async => <int>[]),
          ],
        ),
      );
      await tester.pumpAndSettle();
      unawaited(_navKey.currentState!.pushNamed('/reading-growth'));
      await tester.pumpAndSettle();

      // 양성 대조: 게이트가 '항상 뜬다'가 아니라 '미인증일 때만 뜬다'.
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(ReadingGrowthScreen), findsOneWidget);
    });

    testWidgets('credits: 미인증이면 나이 게이트 다이얼로그가 뜬다', (tester) async {
      final prefs = await _prefs();
      await tester.pumpWidget(
        _routedHarness(
          prefs: prefs,
          routeName: '/credits',
          screen: const CreditsScreen(),
          overrides: [apiClientProvider.overrideWithValue(_FakeApiClient())],
        ),
      );
      await tester.pumpAndSettle();
      unawaited(_navKey.currentState!.pushNamed('/credits'));
      // CreditsScreen 은 로딩 인디케이터가 계속 도므로 pumpAndSettle 이 끝나지 않는다.
      await _pumpFrames(tester);

      expect(
        find.byType(AlertDialog),
        findsOneWidget,
        reason: '결제 화면이 부모 인증 없이 열렸다',
      );
    });

    testWidgets('credits: 게이트를 취소하면 화면이 닫힌다(차단)', (tester) async {
      final prefs = await _prefs();
      await tester.pumpWidget(
        _routedHarness(
          prefs: prefs,
          routeName: '/credits',
          screen: const CreditsScreen(),
          overrides: [apiClientProvider.overrideWithValue(_FakeApiClient())],
        ),
      );
      await tester.pumpAndSettle();
      unawaited(_navKey.currentState!.pushNamed('/credits'));
      await _pumpFrames(tester);
      expect(find.byType(AlertDialog), findsOneWidget);

      // 취소 → Navigator.pop → 화면이 사라져야 한다.
      // 화면 자체에도 TextButton 이 있으므로 반드시 다이얼로그 안에서 찾는다.
      final cancel = find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(TextButton),
      );
      expect(cancel, findsOneWidget);
      await tester.tap(cancel);
      await _pumpFrames(tester);

      expect(
        find.byType(CreditsScreen),
        findsNothing,
        reason: '게이트를 취소했는데 결제 화면이 그대로 남아 있다',
      );
    });
  });
}
