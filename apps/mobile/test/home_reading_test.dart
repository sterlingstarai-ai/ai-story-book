import 'dart:async';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Library extends LibraryNotifier {
  _Library(this.load);
  final Future<List<LibraryBook>> Function() load;

  @override
  Future<List<LibraryBook>> build() => load();
}

class _Characters extends CharactersNotifier {
  @override
  Future<List<Character>> build() async => [];
}

class _TodayFailure extends ApiClient {
  _TodayFailure(this.status) : super(baseUrl: 'http://test', userKey: 'test');

  final int status;
  String? requestedAge;

  @override
  Future<String> generateTodayStory({
    required String targetAge,
    required String style,
    String? protagonistName,
    String language = 'ko',
    String? idempotencyKey,
  }) async {
    requestedAge = targetAge;
    throw DioException(
      requestOptions: RequestOptions(path: '/v1/streak/today/generate'),
      error: ApiError(
        code: status == 402 ? 'PAYMENT_REQUIRED' : 'SERVICE_UNAVAILABLE',
        statusCode: status,
        message: 'synthetic',
      ),
    );
  }
}

class _PendingTodayStory extends ApiClient {
  _PendingTodayStory() : super(baseUrl: 'http://test', userKey: 'test');

  final completion = Completer<String>();
  final sentKeys = <String?>[];

  @override
  Future<String> generateTodayStory({
    required String targetAge,
    required String style,
    String? protagonistName,
    String language = 'ko',
    String? idempotencyKey,
  }) {
    sentKeys.add(idempotencyKey);
    return completion.future;
  }
}

LibraryBook _book(String id, String title) => LibraryBook(
  id: id,
  title: title,
  coverImageUrl: '',
  targetAge: '7-9',
  style: 'watercolor',
  createdAt: DateTime(2026, 9, 6),
);

const _streak = HomeStreakSnapshot(
  currentStreak: 2,
  longestStreak: 3,
  totalDays: 4,
  readToday: false,
  todayThemeName: '우정',
  todayTopic: '숲에서 만난 친구',
  todayBookId: 'today-book',
  readDates: {},
);

Future<void> _pump(
  WidgetTester tester, {
  required Future<List<LibraryBook>> Function() load,
  required List<RouteSettings> navigation,
  Map<String, Object> initialPreferences = const {},
  List<Override> overrides = const [],
  Future<List<JobStatus>> Function()? loadActiveJobs,
  HomeStreakSnapshot streak = _streak,
}) async {
  SharedPreferences.setMockInitialValues(initialPreferences);
  final prefs = await SharedPreferences.getInstance();
  tester.view.physicalSize = const Size(320, 480);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = 1.4;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        libraryProvider.overrideWith(() => _Library(load)),
        activeBookGenerationsProvider.overrideWith(
          (ref) async => loadActiveJobs == null ? [] : await loadActiveJobs(),
        ),
        charactersProvider.overrideWith(_Characters.new),
        homeStreakProvider.overrideWith((ref) async => streak),
        growthReportProvider.overrideWith(
          (ref) async => throw StateError('synthetic'),
        ),
        ...overrides,
      ],
      child: MaterialApp(
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const HomeScreen(),
        onGenerateRoute: (settings) {
          navigation.add(settings);
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => const Scaffold(body: Text('destination')),
          );
        },
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _scrollTo(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    160,
    scrollable: find
        .descendant(
          of: find.byKey(const Key('home_scroll')),
          matching: find.byType(Scrollable),
        )
        .first,
  );
  await tester.pumpAndSettle();
}

void main() {
  const resumeGeneration = Key('home_resume_generation');
  for (final count in [1, 2]) {
    testWidgets('home resumes existing generation work ($count jobs)', (
      tester,
    ) async {
      final navigation = <RouteSettings>[];
      await _pump(
        tester,
        load: () async => [],
        loadActiveJobs: () async => [
          for (var index = 0; index < count; index++)
            JobStatus(
              jobId: 'existing-$index',
              status: JobState.running,
              progress: 33,
            ),
        ],
        navigation: navigation,
      );
      final resume = find.byKey(resumeGeneration);
      expect(resume.hitTestable(), findsOneWidget);
      expect(tester.getSize(resume).height, greaterThanOrEqualTo(64));
      await tester.tap(resume);
      await tester.pumpAndSettle();
      expect(navigation.single.name, count == 1 ? '/loading' : '/library');
      expect(navigation.single.arguments, count == 1 ? 'existing-0' : null);
    });
  }

  testWidgets(
    'refreshing and failed active work reads keep saved books usable',
    (tester) async {
      final refresh = Completer<List<JobStatus>>();
      final navigation = <RouteSettings>[];
      var lookups = 0;
      await _pump(
        tester,
        load: () async => [_book('saved-book', '보관한 책')],
        loadActiveJobs: () async => lookups++ == 0
            ? [
                JobStatus(
                  jobId: 'old-job',
                  status: JobState.running,
                  progress: 33,
                ),
              ]
            : refresh.future,
        navigation: navigation,
      );
      final resume = find.byKey(resumeGeneration);
      expect(resume, findsOneWidget);
      final container = ProviderScope.containerOf(
        tester.element(find.byType(HomeScreen)),
      );
      container.invalidate(activeBookGenerationsProvider);
      await tester.pumpAndSettle();
      expect(resume, findsNothing);
      refresh.completeError(StateError('private-debug-text'));
      await tester.pumpAndSettle();
      expect(resume, findsNothing);
      expect(find.textContaining('private-debug-text'), findsNothing);
      await tester.tap(find.byKey(const Key('home_featured_book')));
      await tester.pumpAndSettle();
      expect(navigation.single.arguments, 'saved-book');
    },
  );

  testWidgets('a story finished while away appears on the existing home', (
    tester,
  ) async {
    var completedWhileAway = false;
    var libraryReads = 0;
    await _pump(
      tester,
      load: () async {
        libraryReads++;
        return [if (completedWhileAway) _book('new-book', '새 동화')];
      },
      loadActiveJobs: () async => [
        if (!completedWhileAway)
          JobStatus(
            jobId: 'running-job',
            status: JobState.running,
            progress: 60,
          ),
      ],
      navigation: [],
    );
    expect(find.byKey(resumeGeneration), findsOneWidget);
    expect(find.text('새 동화'), findsNothing);
    final container = ProviderScope.containerOf(
      tester.element(find.byType(HomeScreen)),
    );
    completedWhileAway = true;
    container.invalidate(activeBookGenerationsProvider);
    await tester.pumpAndSettle();
    expect(libraryReads, 2);
    expect(find.byKey(resumeGeneration), findsNothing);
    expect(find.text('새 동화'), findsOneWidget);
  });

  for (final status in [402, 503]) {
    testWidgets('today story failure routes by API error ($status)', (
      tester,
    ) async {
      final navigation = <RouteSettings>[];
      final api = _TodayFailure(status);
      await _pump(
        tester,
        load: () async => [],
        navigation: navigation,
        streak: const HomeStreakSnapshot(
          currentStreak: 2,
          longestStreak: 3,
          totalDays: 4,
          readToday: false,
          todayThemeName: '우정',
          todayTopic: '숲에서 만난 친구',
          todayBookId: null,
          readDates: {},
        ),
        overrides: [
          apiClientProvider.overrideWithValue(api),
          capabilitiesProvider.overrideWith(
            (ref) async => {'free_first_book_trial': status == 402},
          ),
          generationOptionsProvider.overrideWith(
            (ref) async => const GenerationOptions(BookStyle.values),
          ),
        ],
      );
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      final create = find.text(l.homeMakeTodayStory);
      await _scrollTo(tester, create);
      await tester.tap(create);
      await tester.pumpAndSettle();
      expect(api.requestedAge, status == 402 ? '3-5' : '5-7');
      if (status == 402) {
        expect(find.text(l.creditBetaLimitTitle), findsOneWidget);
        final close = find.text(l.creditShortageClose);
        await tester.ensureVisible(close);
        await tester.tap(close);
        await tester.pumpAndSettle();
        expect(navigation, isEmpty);
      } else {
        expect(find.text(l.creditBetaLimitTitle), findsNothing);
        expect(navigation.single.name, '/create');
      }
    });
  }

  for (final bool? eligible in [true, null]) {
    testWidgets(
      'today story reviews settings before a possible first book ($eligible)',
      (tester) async {
        final navigation = <RouteSettings>[];
        final api = _TodayFailure(503);
        addTearDown(api.close);
        final options = Completer<GenerationOptions>();
        if (eligible == true) {
          options.complete(
            const GenerationOptions(
              BookStyle.values,
              firstBookTrialAvailable: true,
            ),
          );
        }
        await _pump(
          tester,
          load: () async => [],
          navigation: navigation,
          streak: const HomeStreakSnapshot(
            currentStreak: 0,
            longestStreak: 0,
            totalDays: 0,
            readToday: false,
            todayThemeName: '우정',
            todayTopic: '숲에서 만난 친구',
            todayBookId: null,
            readDates: {},
          ),
          overrides: [
            apiClientProvider.overrideWithValue(api),
            capabilitiesProvider.overrideWith(
              (ref) async => {'free_first_book_trial': true},
            ),
            generationOptionsProvider.overrideWith((ref) => options.future),
          ],
        );
        final review = find.text('오늘 주제로 동화 만들기');
        await _scrollTo(tester, review);
        await tester.tap(review);
        await tester.pumpAndSettle();
        expect(api.requestedAge, isNull);
        expect(navigation.single.name, '/create');
        expect(navigation.single.arguments, {'topic': '숲에서 만난 친구'});
      },
    );
  }

  for (final scenario in ['stay', 'open settings', 'switch account']) {
    testWidgets(
      'today submission stays within its route and account ($scenario)',
      (tester) async {
        final navigation = <RouteSettings>[];
        final api = _PendingTodayStory();
        final currentApi = StateProvider<ApiClient>((ref) => api);
        addTearDown(api.close);
        await _pump(
          tester,
          load: () async => [],
          navigation: navigation,
          streak: const HomeStreakSnapshot(
            currentStreak: 0,
            longestStreak: 0,
            totalDays: 0,
            readToday: false,
            todayThemeName: '우정',
            todayTopic: '숲에서 만난 친구',
            todayBookId: null,
            readDates: {},
          ),
          overrides: [
            apiClientProvider.overrideWith((ref) => ref.watch(currentApi)),
            capabilitiesProvider.overrideWith(
              (ref) async => {'free_first_book_trial': false},
            ),
            generationOptionsProvider.overrideWith(
              (ref) async => const GenerationOptions(BookStyle.values),
            ),
          ],
        );
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        final create = find.text(l.homeMakeTodayStory);
        await _scrollTo(tester, create);
        final home = tester.element(find.byType(HomeScreen));
        await tester.tap(create);
        await tester.tap(create);
        await tester.pump();
        expect(api.sentKeys, [isNotEmpty]);
        expect(
          find.bySemanticsLabel(l.loadingStepCheckingStatus),
          findsOneWidget,
        );

        if (scenario == 'open settings') {
          unawaited(Navigator.of(home).pushNamed('/settings'));
          await tester.pump();
        }
        if (scenario == 'switch account') {
          final next = _PendingTodayStory();
          addTearDown(next.close);
          final container = ProviderScope.containerOf(home, listen: false);
          container.read(currentApi.notifier).state = next;
          container.invalidate(todayAttemptKeyProvider);
          container.invalidate(todayAttemptSigProvider);
          await tester.pump();
          await tester.tap(create);
          await tester.pump();
          expect(next.sentKeys, [isNotEmpty]);
          expect(next.sentKeys.single, isNot(api.sentKeys.single));
          api.completion.complete('old-account-job');
          await tester.pump();
          expect(navigation, isEmpty);
          expect(
            find.bySemanticsLabel(l.loadingStepCheckingStatus),
            findsOneWidget,
          );
          next.completion.complete('new-job');
        } else {
          api.completion.complete('new-job');
        }
        await tester.pumpAndSettle();
        expect(navigation.map((route) => route.name), [
          scenario == 'open settings' ? '/settings' : '/loading',
        ]);
        if (scenario != 'open settings') {
          expect(navigation.single.arguments, 'new-job');
        }
      },
    );
  }

  testWidgets('scoped saved page offers continue reading', (tester) async {
    await _pump(
      tester,
      load: () async => [_book('latest', '읽다 만 동화')],
      navigation: [],
      overrides: [
        homeReadingProgressProvider('latest').overrideWith((ref) async => 5),
      ],
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('home_featured_book')),
        matching: find.text('이어 읽기'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('unattributed legacy progress is preserved and not displayed', (
    tester,
  ) async {
    await _pump(
      tester,
      load: () async => [_book('latest', '읽다 만 동화')],
      navigation: [],
      initialPreferences: {'reading_progress_latest_v1': 5},
    );
    final featured = find.byKey(const Key('home_featured_book'));
    expect(
      find.descendant(of: featured, matching: find.text('동화 읽기')),
      findsOneWidget,
    );
    await tester.tap(featured);
    await tester.pumpAndSettle();
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('reading_progress_latest_v1'), 5);
    Navigator.pop(tester.element(find.text('destination')));
    await tester.pumpAndSettle();
    expect(
      find.descendant(of: featured, matching: find.text('동화 읽기')),
      findsOneWidget,
    );
  });

  testWidgets(
    'saved story is readable on the first small large-text viewport',
    (tester) async {
      final navigation = <RouteSettings>[];
      await _pump(
        tester,
        load: () async => [_book('latest-book', '토리와 빗방울 정원')],
        navigation: navigation,
      );
      final book = find.byKey(const Key('home_featured_book'));
      expect(book.hitTestable(), findsOneWidget);
      expect(tester.getSize(book).height, greaterThanOrEqualTo(64));
      expect(
        find.byKey(const Key('home_create_book')).hitTestable(),
        findsNothing,
      );
      expect(find.text('오늘은 어떤 이야기를 읽어볼까요?'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(book);
      await tester.pumpAndSettle();
      expect(navigation.last.name, '/viewer');
      expect(navigation.last.arguments, 'latest-book');
    },
  );

  for (final (trial, eligible) in [
    (false, false),
    (true, false),
    (true, true),
  ]) {
    testWidgets(
      'empty home leads to the first book (trial: $trial, eligible: $eligible)',
      (tester) async {
        final navigation = <RouteSettings>[];
        await _pump(
          tester,
          load: () async => [],
          navigation: navigation,
          overrides: [
            capabilitiesProvider.overrideWith(
              (ref) async => {
                'free_first_book_trial': trial,
                'narration_supported': true,
              },
            ),
            generationOptionsProvider.overrideWith(
              (ref) async => GenerationOptions(const [
                BookStyle.watercolor,
              ], firstBookTrialAvailable: eligible),
            ),
          ],
        );
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        expect(find.text('아직 만든 책이 없어요'), findsOneWidget);
        expect(find.byKey(const Key('home_featured_book')), findsNothing);
        final create = find.byKey(const Key('home_create_book'));
        await tester.ensureVisible(create);
        await tester.pumpAndSettle();
        expect(
          find.descendant(
            of: create,
            matching: find.text(l.firstBookTrialOffer),
          ),
          eligible ? findsOneWidget : findsNothing,
        );
        await tester.tap(create);
        await tester.pumpAndSettle();
        expect(navigation.last.name, '/create');
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('library retry stays near the top and never shows raw errors', (
    tester,
  ) async {
    var attempts = 0;
    await _pump(
      tester,
      load: () async {
        if (attempts++ == 0) throw StateError('private-provider-debug-details');
        return [_book('recovered-book', '다시 만난 작은 별')];
      },
      navigation: [],
    );
    expect(find.text('책을 불러올 수 없어요'), findsOneWidget);
    expect(find.textContaining('private-provider'), findsNothing);
    final retry = find.text('다시 시도');
    await tester.ensureVisible(retry);
    await tester.pumpAndSettle();
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('다시 만난 작은 별'), findsOneWidget);
    expect(find.text('책을 불러올 수 없어요'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'additional books keep titles visible and open the selected book',
    (tester) async {
      final navigation = <RouteSettings>[];
      await _pump(
        tester,
        load: () async => [
          _book('latest', '가장 최근 책'),
          _book('second', '두 번째 동화책'),
          _book('third', '세 번째 동화책'),
          _book('fourth', '네 번째 동화책'),
        ],
        navigation: navigation,
      );
      await _scrollTo(tester, find.text('두 번째 동화책'));
      await tester.tap(find.text('두 번째 동화책'));
      await tester.pumpAndSettle();
      expect(navigation.last.name, '/viewer');
      expect(navigation.last.arguments, 'second');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('view all opens the library and parent tools follow reading', (
    tester,
  ) async {
    final navigation = <RouteSettings>[];
    await _pump(
      tester,
      load: () async => [_book('latest', '읽을 동화')],
      navigation: navigation,
    );
    await _scrollTo(tester, find.byKey(const Key('home_growth_entry')));
    expect(find.text('부모님께'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(
      find.byKey(const Key('home_view_library')),
      -200,
      scrollable: find
          .descendant(
            of: find.byKey(const Key('home_scroll')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('home_view_library')));
    await tester.pumpAndSettle();
    expect(navigation.last.name, '/library');
    expect(tester.takeException(), isNull);
  });
}
