// 통합 E2E — 실제 앱 라우팅(StartupGate→buildAppRoute)을 타며 멀티 화면 여정을 검증.
//
// 단위 위젯 테스트(단일 화면)가 놓치는 *화면 간 네비게이션 + 전체 provider 그래프*를
// 검증한다. 네트워크 경계만 mock(오프라인·결정적). 두 가지로 실행 가능:
//   - CI/로컬(에뮬레이터 불필요):  flutter test integration_test/
//   - 실기기/시뮬레이터(flutter_driver): flutter drive \
//       --driver=test_driver/integration_test.dart --target=integration_test/app_flow_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/screens/onboarding_screen.dart';
import 'package:ai_story_book/screens/reading_growth_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';

/// 네트워크 경계만 가짜로 — 동의/조회 등 여정에 필요한 메서드만.
class _MockApi extends ApiClient {
  _MockApi()
      : super(
            baseUrl: 'http://localhost',
            userKey: 'itest',
            enableLogging: false);

  bool consentGranted = false;

  @override
  Future<Map<String, dynamic>> getConsent() async => {
        'photos': false,
        'privacy': consentGranted,
        'data_processing': consentGranted,
      };

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    consentGranted = true;
    return {
      'photos': photos,
      'privacy': privacy,
      'data_processing': dataProcessing
    };
  }
}

class _EmptyLibrary extends LibraryNotifier {
  @override
  Future<List<LibraryBook>> build() async => const [];
}

GrowthReport _growth() => const GrowthReport(
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
      levelKey: 'steady_growth',
      levelLabel: '기초 다지기',
      scoreValue: 60,
    );

HomeStreakSnapshot _streak() => const HomeStreakSnapshot(
      currentStreak: 3,
      longestStreak: 5,
      totalDays: 9,
      readToday: true,
      todayThemeName: '우정',
      todayTopic: '숲속 친구들의 모험',
      todayBookId: null,
      readDates: {},
    );

PeerComparison _peer() => const PeerComparison(
      ageBand: '5-7',
      peerCount: 2,
      isBaseline: true,
      showRanking: false,
      myBooks: 7,
      peerBooks: 5,
      myVocab: 12,
      peerVocab: 8,
      myAccuracy: 0.75,
      peerAccuracy: 0.6,
      myScore: 60,
      peerScore: 50,
      topPercent: 50,
      medal: 'none',
    );

Future<SharedPreferences> _prefs({
  bool consent = false,
  bool onboarding = false,
  bool ageGate = false,
}) async {
  SharedPreferences.setMockInitialValues({
    if (consent) ParentalControlService.consentGrantedKey: true,
    if (onboarding) ParentalControlService.onboardingDoneKey: true,
    if (ageGate)
      ParentalControlService.ageGateSessionKey:
          DateTime.now().millisecondsSinceEpoch,
  });
  return SharedPreferences.getInstance();
}

Widget _app(SharedPreferences prefs, ApiClient api) => ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        // 화면 데이터는 결정적 값으로(네트워크 비의존) — 라우팅/통합이 테스트 대상.
        libraryProvider.overrideWith(() => _EmptyLibrary()),
        homeStreakProvider.overrideWith((ref) async => _streak()),
        growthReportProvider.overrideWith((ref) async => _growth()),
        peerComparisonProvider.overrideWith((ref) async => _peer()),
        weeklyReadingTrendProvider
            .overrideWith((ref) async => const <int>[1, 2, 3]),
      ],
      child: const _IntegrationApp(),
    );

/// 실제 라우팅(buildAppRoute)을 쓰는 앱 셸 — provider override는 바깥 ProviderScope가 담당.
class _IntegrationApp extends StatelessWidget {
  const _IntegrationApp();

  @override
  Widget build(BuildContext context) => const MaterialApp(
        initialRoute: '/startup',
        onGenerateRoute: buildAppRoute,
        locale: Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      );
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('신규 사용자 여정: 시작 게이트 → 부모 동의 → 온보딩 → 홈', (tester) async {
    await tester.pumpWidget(_app(await _prefs(), _MockApi()));
    await tester.pumpAndSettle();

    // StartupGate가 동의 미완료를 감지 → 동의 화면으로 라우팅
    expect(find.byType(ConsentScreen), findsOneWidget);

    // 약관 전체 동의 → 시작 버튼 활성 → 진행
    await tester.tap(find.text('약관 전체 동의'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('동의하고 시작하기'));
    await tester.pumpAndSettle();

    // 온보딩 도달 → '다음' 반복 후 '시작하기'
    expect(find.byType(OnboardingScreen), findsOneWidget);
    for (var i = 0; i < 8 && find.text('다음').evaluate().isNotEmpty; i++) {
      await tester.tap(find.text('다음'));
      await tester.pumpAndSettle();
    }
    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();

    // 홈 도달
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('재방문 사용자 여정: 시작 게이트 → 홈 → 읽기 성장', (tester) async {
    await tester.pumpWidget(_app(
      await _prefs(consent: true, onboarding: true, ageGate: true),
      _MockApi(),
    ));
    await tester.pumpAndSettle();

    // 동의·온보딩 완료 → 바로 홈
    expect(find.byType(HomeScreen), findsOneWidget);

    // 읽기 성장 카드는 스크롤 하단일 수 있어 보일 때까지 스크롤 후 탭
    final growthCard = find.text('읽기 성장 보기');
    await tester.scrollUntilVisible(
      growthCard,
      300,
      scrollable: find.byType(Scrollable).first,
    );
    // 홈은 AppShell(하단 네비게이션)로 감싸져 있어, scrollUntilVisible이 카드를 화면
    // 최하단 가장자리에 '겨우 보이는' 상태로 남기면 탭 좌표가 네비바에 떨어져 전환이
    // 일어나지 않는다(러너 화면 메트릭에 따라 갈림). 중앙으로 끌어와 탭 지점을 안정화한다.
    await tester.ensureVisible(growthCard);
    await tester.pumpAndSettle();
    await tester.tap(growthCard);

    // 성장 화면은 진입 후 비동기 조회 결과로 hero를 렌더한다. pumpAndSettle은 프레임이
    // 멎으면 반환하므로 네트워크 대기 중에는 조기 반환할 수 있다 — 키가 나타날 때까지
    // 유한 대기(최대 ~4초)한다. 조용한 스킵이 아니라 아래 expect가 최종 판정한다.
    final hero = find.byKey(const Key('growth_level_hero'));
    for (var i = 0; i < 40 && hero.evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    // 성장 리포트 화면 도달(부모 게이트는 prefs 세션으로 통과)
    expect(find.byType(ReadingGrowthScreen), findsOneWidget);
    expect(hero, findsOneWidget);
  });
}
