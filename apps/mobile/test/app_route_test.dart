import 'package:ai_story_book/main.dart';
import 'package:ai_story_book/screens/screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<Widget> _buildWidgetFromRoute(
  WidgetTester tester,
  Route<dynamic> route,
) async {
  final materialRoute = route as MaterialPageRoute<dynamic>;
  late Widget builtWidget;

  await tester.pumpWidget(
    MaterialApp(
      home: Builder(
        builder: (context) {
          builtWidget = materialRoute.builder(context);
          return const SizedBox.shrink();
        },
      ),
    ),
  );

  return builtWidget;
}

void main() {
  group('buildAppRoute', () {
    testWidgets('builds LoadingScreen for valid /loading arguments',
        (tester) async {
      final route = buildAppRoute(
          const RouteSettings(name: '/loading', arguments: 'job-1'));
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<LoadingScreen>());
      expect((builtWidget as LoadingScreen).jobId, 'job-1');
    });

    testWidgets('falls back to HomeScreen for malformed /loading arguments',
        (tester) async {
      final route =
          buildAppRoute(const RouteSettings(name: '/loading', arguments: 123));
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<HomeScreen>());
    });

    testWidgets('builds ViewerScreen for valid /viewer arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(name: '/viewer', arguments: 'book-1'),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<ViewerScreen>());
      expect((builtWidget as ViewerScreen).bookId, 'book-1');
    });

    testWidgets('builds startup/settings/consent/onboarding routes',
        (tester) async {
      final startup = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/startup')),
      );
      final settings = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/settings')),
      );
      final consent = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/consent')),
      );
      final onboarding = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/onboarding')),
      );

      expect(startup, isA<StartupGateScreen>());
      expect(settings, isA<SettingsScreen>());
      expect(consent, isA<ConsentScreen>());
      expect(onboarding, isA<OnboardingScreen>());
    });

    testWidgets('builds profiles/parent-dashboard/voice-profiles routes',
        (tester) async {
      final profiles = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/profiles')),
      );
      final parent = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/parent-dashboard')),
      );
      final voices = await _buildWidgetFromRoute(
        tester,
        buildAppRoute(const RouteSettings(name: '/voice-profiles')),
      );

      expect(profiles, isA<ProfilesScreen>());
      expect(parent, isA<ParentDashboardScreen>());
      expect(voices, isA<VoiceProfilesScreen>());
    });

    testWidgets('builds BranchStoryScreen for valid /branch-story arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(
          name: '/branch-story',
          arguments: {'bookId': 'book-branch-1'},
        ),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<BranchStoryScreen>());
      expect((builtWidget as BranchStoryScreen).bookId, 'book-branch-1');
    });

    testWidgets(
        'falls back to HomeScreen for malformed /branch-story arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(name: '/branch-story', arguments: {'bad': 'value'}),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<HomeScreen>());
    });

    testWidgets(
        'builds PronunciationPracticeScreen for valid /pronunciation-practice arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(
          name: '/pronunciation-practice',
          arguments: {
            'bookId': 'book-pron-1',
            'pageNumber': 2,
            'expectedText': '토끼가 걸어가요',
          },
        ),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<PronunciationPracticeScreen>());
      final screen = builtWidget as PronunciationPracticeScreen;
      expect(screen.bookId, 'book-pron-1');
      expect(screen.pageNumber, 2);
      expect(screen.expectedText, '토끼가 걸어가요');
    });

    testWidgets(
        'falls back to HomeScreen for malformed /pronunciation-practice arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(
          name: '/pronunciation-practice',
          arguments: {'bookId': 'book-pron-1', 'pageNumber': 0},
        ),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<HomeScreen>());
    });

    testWidgets('builds PodOrderScreen for valid /pod-order arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(
          name: '/pod-order',
          arguments: {
            'bookId': 'book-pod-1',
            'bookTitle': '테스트 동화',
          },
        ),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<PodOrderScreen>());
      final screen = builtWidget as PodOrderScreen;
      expect(screen.bookId, 'book-pod-1');
      expect(screen.bookTitle, '테스트 동화');
    });

    testWidgets('falls back to HomeScreen for malformed /pod-order arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(
          name: '/pod-order',
          arguments: {'bookTitle': 'missing-id'},
        ),
      );
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<HomeScreen>());
    });

    testWidgets('falls back to HomeScreen for unknown routes', (tester) async {
      final route = buildAppRoute(const RouteSettings(name: '/unknown'));
      final builtWidget = await _buildWidgetFromRoute(tester, route);

      expect(builtWidget, isA<HomeScreen>());
    });
  });
}
