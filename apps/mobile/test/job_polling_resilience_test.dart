import 'dart:async';
import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/library_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/job_polling.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _StatusApi extends ApiClient {
  _StatusApi({this.finishOnReturn = false, this.active = const []})
    : super(baseUrl: 'http://127.0.0.1:1', userKey: 'status-test');

  final bool finishOnReturn;
  final List<JobStatus> active;
  final jobIds = <String>[];
  final tokens = <CancelToken>[];

  @override
  Future<List<JobStatus>> getActiveBookGenerations() async => active;

  @override
  Future<JobStatus> getBookStatus(
    String jobId, {
    CancelToken? cancelToken,
  }) async {
    jobIds.add(jobId);
    tokens.add(cancelToken!);
    if (jobIds.length > 1) {
      if (!finishOnReturn) throw await cancelToken.whenCancel;
      return JobStatus(
        jobId: jobId,
        status: JobState.done,
        progress: 100,
        result: BookResult(
          bookId: 'finished-book',
          title: 'Story',
          coverImageUrl: '',
          pages: [],
        ),
      );
    }
    return JobStatus(jobId: jobId, status: JobState.running, progress: 30);
  }
}

class _EmptyLibrary extends LibraryBrowseNotifier {
  @override
  Future<LibraryBrowseState> build() async => LibraryBrowseState.initial();
}

class _ActiveGenerationApi extends _StatusApi {
  _ActiveGenerationApi(this.responses);

  final List<Object> responses;
  int reads = 0;

  @override
  Future<List<JobStatus>> getActiveBookGenerations() async {
    final response = responses[reads++];
    if (response is List<JobStatus>) return response;
    if (response is Future<List<JobStatus>>) return response;
    throw response;
  }
}

class _LibraryGenerationApi extends _StatusApi {
  bool finished = false;
  final libraryReads = <(String, String?, String?)>[];

  @override
  Future<List<JobStatus>> getActiveBookGenerations() async => [
    if (!finished)
      JobStatus(
        jobId: 'first-book-job',
        status: JobState.running,
        progress: 60,
      ),
  ];

  @override
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
    String? cursor,
    String sort = 'newest',
    String? style,
    String? targetAge,
  }) async {
    libraryReads.add((sort, style, targetAge));
    return LibraryResponse(
      books: [
        if (finished)
          LibraryBook(
            id: 'finished-book',
            title: '완성된 첫 동화',
            coverImageUrl: '',
            targetAge: '7-9',
            style: 'watercolor',
            createdAt: DateTime(2026),
          ),
      ],
      total: finished ? 1 : 0,
      nextCursor: null,
      hasMore: false,
    );
  }
}

class _RefundApi extends _StatusApi {
  bool refunded = false;

  @override
  Future<List<JobStatus>> getActiveBookGenerations() async => [
    if (!refunded)
      JobStatus(jobId: 'refunded-job', status: JobState.running, progress: 30),
  ];

  @override
  Future<GenerationOptions> getGenerationOptions() async => GenerationOptions(
    const [BookStyle.watercolor],
    firstBookTrialAvailable: refunded,
  );

  @override
  Future<JobStatus> getBookStatus(
    String jobId, {
    CancelToken? cancelToken,
  }) async {
    refunded = true;
    return JobStatus(
      jobId: jobId,
      status: JobState.failed,
      progress: 30,
      creditRefundStatus: 'refunded',
    );
  }
}

class _ReconnectApi extends _StatusApi {
  _ReconnectApi({required this.failOnFirstRead, this.failure});

  final bool failOnFirstRead;
  final ApiError? failure;

  @override
  Future<JobStatus> getBookStatus(
    String jobId, {
    CancelToken? cancelToken,
  }) async {
    jobIds.add(jobId);
    if (jobIds.length == (failOnFirstRead ? 1 : 2)) {
      throw failure ??
          ApiError(code: 'CONNECTION_ERROR', message: '', statusCode: 0);
    }
    final completed = jobIds.length == (failOnFirstRead ? 2 : 3);
    return JobStatus(
      jobId: jobId,
      status: completed ? JobState.done : JobState.running,
      progress: completed ? 100 : 55,
      result: completed
          ? BookResult(
              bookId: 'reconnected-book',
              title: 'Story',
              coverImageUrl: '',
              pages: [],
            )
          : null,
    );
  }
}

void main() {
  for (final (http, wait) in [(503, 3), (429, 12)]) {
    testWidgets('server backoff is honored across app suspension ($http)', (
      tester,
    ) async {
      final api = _ReconnectApi(
        failOnFirstRead: false,
        failure: ApiError(
          code: 'SERVER_ERROR',
          message: '',
          statusCode: http,
          retryAfter: http == 429 ? Duration(seconds: wait) : null,
        ),
      );
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final job = container.listen(jobPollingProvider('same-job'), (_, __) {});
      final background = container.read(
        generationInBackgroundProvider.notifier,
      );
      await tester.pump();
      await tester.pump(const Duration(seconds: 3));
      expect(job.read().requireValue.isRechecking, isTrue);
      expect(job.read().requireValue.progress, 55);

      background.state = true;
      await tester.pump(const Duration(seconds: 1));
      background.state = false;
      await tester.pump();
      expect(api.jobIds, ['same-job', 'same-job']);

      background.state = true;
      await tester.pump(Duration(seconds: wait));
      expect(api.jobIds, ['same-job', 'same-job']);
      background.state = false;
      await tester.pump();
      expect(api.jobIds, List.filled(3, 'same-job'));
      expect(job.read().requireValue.result?.bookId, 'reconnected-book');
    });
  }

  for (final failOnFirstRead in [false, true]) {
    testWidgets(
      'a lost connection resumes the same book (first read: $failOnFirstRead)',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(320, 480);
        tester.platformDispatcher.textScaleFactorTestValue = 1.4;
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final api = _ReconnectApi(failOnFirstRead: failOnFirstRead);
        addTearDown(api.close);
        final container = ProviderContainer(
          overrides: [apiClientProvider.overrideWithValue(api)],
        );
        addTearDown(container.dispose);
        final opened = <Object?>[];
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: MaterialApp(
              locale: const Locale('ko'),
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              home: const LoadingScreen(jobId: 'existing-job'),
              onGenerateRoute: (settings) {
                expect(settings.name, '/viewer');
                opened.add(settings.arguments);
                return MaterialPageRoute(
                  builder: (_) =>
                      const Scaffold(body: Text('Reconnected viewer')),
                );
              },
            ),
          ),
        );
        await tester.pump();
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        if (failOnFirstRead) {
          expect(find.text(l.loadingStepWaitingForStatusRetry), findsOneWidget);
          expect(find.text('0%'), findsNothing);
          expect(find.text(l.loadingStepWaiting), findsNothing);
          expect(api.jobIds, ['existing-job']);
        } else {
          expect(find.text('55%'), findsOneWidget);
          expect(find.text(l.loadingInProgressHint), findsOneWidget);
          await tester.pump(const Duration(seconds: 3));
          expect(find.text('55%'), findsOneWidget);
          expect(find.text(l.loadingStepRecheckingStatus), findsOneWidget);
          expect(api.jobIds, ['existing-job', 'existing-job']);
        }
        expect(find.text(l.loadingInProgressHint), findsNothing);
        expect(find.text(l.loadingCheckStatusButton), findsNothing);
        expect(tester.takeException(), isNull);

        final background = container.read(
          generationInBackgroundProvider.notifier,
        );
        background.state = true;
        background.state = false;
        await tester.pumpAndSettle();
        expect(find.text('Reconnected viewer'), findsOneWidget);
        expect(
          api.jobIds,
          List.filled(failOnFirstRead ? 2 : 3, 'existing-job'),
        );
        expect(opened, ['reconnected-book']);
      },
    );
  }

  testWidgets(
    'a confirmed failure refreshes active work and the first-book offer',
    (tester) async {
      final api = _RefundApi();
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final options = container.listen(generationOptionsProvider, (_, __) {});
      final active = container.listen(
        activeBookGenerationsProvider,
        (_, __) {},
      );
      await tester.pump();
      expect(options.read().valueOrNull?.firstBookTrialAvailable, isFalse);
      expect(active.read().valueOrNull?.single.jobId, 'refunded-job');
      final job = container.listen(
        jobPollingProvider('refunded-job'),
        (_, __) {},
      );
      await tester.pumpAndSettle();
      expect(job.read().valueOrNull?.creditRefundStatus, 'refunded');
      expect(options.read().valueOrNull?.firstBookTrialAvailable, isTrue);
      expect(active.read().valueOrNull, isEmpty);
    },
  );

  testWidgets(
    'an initial outage recovers active work without leaving the page',
    (tester) async {
      final api = _ActiveGenerationApi([
        ApiError(code: 'SERVICE_UNAVAILABLE', message: '', statusCode: 503),
        ApiError(
          code: 'RATE_LIMIT_EXCEEDED',
          message: '',
          statusCode: 429,
          retryAfter: const Duration(seconds: 45),
        ),
        [
          JobStatus(
            jobId: 'existing-job',
            status: JobState.running,
            progress: 40,
          ),
        ],
        <JobStatus>[],
      ]);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final active = container.listen(
        activeBookGenerationsProvider,
        (_, __) {},
      );
      await tester.pump();
      expect(active.read().hasError, isTrue);

      await tester.pump(const Duration(seconds: 30));
      expect(api.reads, 2);
      await tester.pump(const Duration(seconds: 44));
      expect(api.reads, 2);
      await tester.pump(const Duration(seconds: 1));
      expect(active.read().requireValue.single.jobId, 'existing-job');
      await tester.pump(const Duration(seconds: 15));
      expect(active.read().requireValue, isEmpty);
      await tester.pump(const Duration(minutes: 1));
      expect(api.reads, 4);
    },
  );

  testWidgets('active work does not retry authorization errors', (
    tester,
  ) async {
    final api = _ActiveGenerationApi([
      ApiError(code: 'FORBIDDEN', message: '', statusCode: 403),
    ]);
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(api)],
    );
    addTearDown(api.close);
    addTearDown(container.dispose);
    final active = container.listen(activeBookGenerationsProvider, (_, __) {});
    await tester.pump();
    expect(active.read().hasError, isTrue);
    await tester.pump(const Duration(minutes: 2));
    expect(api.reads, 1);
  });

  testWidgets(
    'confirmed work stays visible during retry and disappears on denial',
    (tester) async {
      final refresh = Completer<List<JobStatus>>();
      final api = _ActiveGenerationApi([
        [
          JobStatus(
            jobId: 'existing-job',
            status: JobState.running,
            progress: 40,
          ),
        ],
        refresh.future,
        ApiError(code: 'FORBIDDEN', message: '', statusCode: 403),
      ]);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final visible = container.listen(
        visibleActiveBookGenerationsProvider,
        (_, __) {},
      );
      await tester.pump();
      expect(visible.read().single.isRechecking, isFalse);
      await tester.pump(const Duration(seconds: 15));
      expect(api.reads, 2);
      expect(visible.read().single.isRechecking, isTrue);
      expect(visible.read().single.jobId, 'existing-job');
      refresh.completeError(
        ApiError(
          code: 'RATE_LIMIT_EXCEEDED',
          message: '',
          statusCode: 429,
          retryAfter: const Duration(seconds: 45),
        ),
      );
      await tester.pump();
      expect(visible.read().single.progress, 40);
      await tester.pump(const Duration(seconds: 44));
      expect(api.reads, 2);
      expect(visible.read().single.isRechecking, isTrue);
      await tester.pump(const Duration(seconds: 1));
      expect(api.reads, 3);
      expect(visible.read(), isEmpty);
      await tester.pump(const Duration(minutes: 1));
      expect(api.reads, 3);
    },
  );

  testWidgets('a late response cannot show work from the previous profile', (
    tester,
  ) async {
    final pending = Completer<List<JobStatus>>();
    final oldApi = _ActiveGenerationApi([
      [
        JobStatus(
          jobId: 'other-profile',
          status: JobState.running,
          progress: 55,
        ),
      ],
      pending.future,
    ]);
    final nextApi = _ActiveGenerationApi([
      ApiError(code: 'SERVICE_UNAVAILABLE', message: '', statusCode: 503),
      [
        JobStatus(
          jobId: 'current-profile',
          status: JobState.queued,
          progress: 0,
        ),
      ],
      <JobStatus>[],
    ]);
    final selected = StateProvider<ApiClient>((_) => oldApi);
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWith((ref) => ref.watch(selected))],
    );
    addTearDown(oldApi.close);
    addTearDown(nextApi.close);
    addTearDown(container.dispose);
    final visible = container.listen(
      visibleActiveBookGenerationsProvider,
      (_, __) {},
    );
    await tester.pump();
    expect(visible.read().single.jobId, 'other-profile');
    await tester.pump(const Duration(seconds: 15));
    expect(visible.read().single.isRechecking, isTrue);
    container.read(selected.notifier).state = nextApi;
    expect(visible.read(), isEmpty);
    pending.complete([
      JobStatus(
        jobId: 'late-other-profile',
        status: JobState.running,
        progress: 60,
      ),
    ]);
    await tester.pump();
    expect(visible.read(), isEmpty);
    await tester.pump(const Duration(seconds: 30));
    expect(visible.read().single.jobId, 'current-profile');
    await tester.pump(const Duration(seconds: 15));
    expect(visible.read(), isEmpty);
  });

  testWidgets(
    'reopening a generation reads the same job and cancels old polls',
    (tester) async {
      final api = _StatusApi();
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final provider = jobPollingProvider('existing-job');
      final first = container.listen(provider, (_, __) {});
      await tester.pump();
      expect(first.read().valueOrNull?.progress, 30);

      first.close();
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      expect(api.jobIds, ['existing-job']);
      expect(api.tokens.single.isCancelled, isTrue);

      final reopened = container.listen(provider, (_, __) {});
      await tester.pump();
      expect(api.jobIds, ['existing-job', 'existing-job']);
      expect(api.tokens.last.isCancelled, isFalse);

      reopened.close();
      await tester.pump(const Duration(milliseconds: 1));
      expect(api.tokens.last.isCancelled, isTrue);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('browse the library and return to the finished book', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 480);
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final api = _StatusApi(
      finishOnReturn: true,
      active: [JobStatus(jobId: 'job', status: JobState.running, progress: 30)],
    );
    addTearDown(api.close);
    final navigator = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(api),
          libraryBrowseProvider.overrideWith(_EmptyLibrary.new),
          pendingBookDeletionsProvider.overrideWith((ref) async => []),
          bookMediaStoreProvider.overrideWith((ref) async {
            throw StateError('no local media in this test');
          }),
        ],
        child: MaterialApp(
          navigatorKey: navigator,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('ko'),
          home: const Scaffold(),
          onGenerateRoute: (settings) => switch (settings.name) {
            '/viewer' => MaterialPageRoute(
              builder: (_) =>
                  Scaffold(body: Text('Viewer ${settings.arguments}')),
            ),
            _ => buildAppRoute(settings),
          },
        ),
      ),
    );
    unawaited(navigator.currentState!.pushNamed('/loading', arguments: 'job'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('30%'), findsOneWidget);
    final browse = find.text('서재를 둘러보며 기다리기');
    expect(tester.getRect(browse).bottom, lessThan(480));
    await tester.tap(browse);
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.widgetWithText(AppBar, l.libraryTitle), findsOneWidget);
    expect(api.jobIds, ['job']);
    expect(api.tokens.single.isCancelled, isFalse);

    await tester.tap(find.text(l.libraryActiveGenerations(1)));
    await tester.pumpAndSettle();
    expect(api.jobIds, ['job', 'job']);
    expect(find.text('Viewer finished-book'), findsOneWidget);
    expect(navigator.currentState!.canPop(), isTrue);
    navigator.currentState!.pop();
    await tester.pumpAndSettle();
    expect(navigator.currentState!.canPop(), isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a fresh library can reopen a selected server generation', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 480);
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final api = _StatusApi(
      active: [
        JobStatus(jobId: 'newest', status: JobState.queued, progress: 0),
        JobStatus(jobId: 'older', status: JobState.running, progress: 30),
      ],
    );
    addTearDown(api.close);
    final navigator = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(api),
          libraryBrowseProvider.overrideWith(_EmptyLibrary.new),
          pendingBookDeletionsProvider.overrideWith((ref) async => []),
          bookMediaStoreProvider.overrideWith(
            (ref) async => throw StateError('no local media in this test'),
          ),
        ],
        child: MaterialApp(
          navigatorKey: navigator,
          home: const Scaffold(),
          onGenerateRoute: buildAppRoute,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('ko'),
        ),
      ),
    );
    unawaited(navigator.currentState!.pushNamed('/library'));
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(api.jobIds, isEmpty);
    await tester.tap(find.text(l.libraryActiveGenerations(2)));
    await tester.pumpAndSettle();
    expect(find.text(l.loadingStepWaiting), findsOneWidget);
    await tester.tap(find.text(l.libraryActiveGenerationItem(2)));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(api.jobIds, ['older']);
    expect(find.text('30%'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  });

  testWidgets(
    'an open library discovers a finished first book without resetting filters',
    (tester) async {
      final api = _LibraryGenerationApi();
      addTearDown(api.close);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(api),
            pendingBookDeletionsProvider.overrideWith((ref) async => []),
            bookMediaStoreProvider.overrideWith((ref) async {
              throw StateError('no local media in this test');
            }),
          ],
          child: const MaterialApp(
            home: LibraryScreen(),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: Locale('ko'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(LibraryScreen)),
      );
      final notifier = container.read(libraryBrowseProvider.notifier);
      await notifier.setTargetAgeFilter('7-9');
      await notifier.setStyleFilter('watercolor');
      await tester.pumpAndSettle();
      expect(find.text('완성된 첫 동화'), findsNothing);
      final readsBeforeCompletion = api.libraryReads.length;

      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(api.libraryReads.length, readsBeforeCompletion);

      api.finished = true;
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(api.libraryReads.length, readsBeforeCompletion + 1);
      expect(api.libraryReads.last, ('newest', 'watercolor', '7-9'));
      expect(find.text('완성된 첫 동화'), findsOneWidget);
      expect(api.jobIds, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'an eight-minute job reaches done through rate limits and a lost connection',
    () async {
      var now = DateTime.utc(2026, 9, 7);
      final start = now;
      var calls = 0;
      final waits = <Duration>[];
      final progress = <int>[];
      await for (final status in pollBookJob(
        jobId: 'job',
        now: () => now,
        cancelled: () => false,
        wait: (delay) async {
          waits.add(delay);
          now = now.add(delay);
        },
        fetch: () async {
          calls++;
          if (calls == 3) {
            final options = RequestOptions(path: '/v1/books/job');
            throw DioException(
              requestOptions: options,
              response: Response(
                requestOptions: options,
                statusCode: 429,
                headers: Headers.fromMap({
                  'retry-after': ['60'],
                }),
              ),
            );
          }
          if (calls == 4) {
            throw ApiError(
              code: 'CONNECTION_ERROR',
              message: '',
              statusCode: 0,
            );
          }
          final seconds = now.difference(start).inSeconds;
          return JobStatus(
            jobId: 'job',
            status: seconds >= 480 ? JobState.done : JobState.running,
            progress: seconds >= 480 ? 100 : seconds ~/ 5,
          );
        },
      )) {
        progress.add(status.progress);
      }
      expect(progress.last, 100);
      expect(waits, contains(const Duration(seconds: 60)));
      expect(waits, contains(const Duration(seconds: 6)));
      expect(
        now.difference(start),
        greaterThanOrEqualTo(const Duration(minutes: 8)),
      );
    },
  );

  test(
    'stable long generation steps reduce reads without slowing transitions',
    () async {
      var calls = 0;
      var foregroundWaits = 0;
      final waits = <int>[];
      final statuses = await pollBookJob(
        jobId: 'job',
        cancelled: () => false,
        wait: (delay) async => waits.add(delay.inSeconds),
        waitBetweenReads: (delay) async {
          waits.add(delay.inSeconds);
          return ++foregroundWaits == 3;
        },
        fetch: () async {
          final read = calls++;
          if (read == 5) {
            throw ApiError(
              code: 'SERVICE_UNAVAILABLE',
              message: '',
              statusCode: 503,
            );
          }
          return JobStatus(
            jobId: 'job',
            status: read == 9 ? JobState.done : JobState.running,
            progress: read == 9
                ? 100
                : read == 8
                ? 55
                : 50,
            currentStep: read < 7
                ? 'generate_image_prompts'
                : 'generate_images',
          );
        },
      ).toList();

      expect(waits, [3, 3, 6, 3, 6, 3, 3, 3, 3]);
      expect(
        statuses.where((status) => status.isRechecking).single.progress,
        50,
      );
      expect(statuses.last.isComplete, isTrue);
      expect(calls, 10);
    },
  );

  for (final code in ['FORBIDDEN', 'NETWORK_ERROR']) {
    test('permanent ownership failure is never retried ($code)', () async {
      var calls = 0;
      final stream = pollBookJob(
        jobId: 'job',
        cancelled: () => false,
        wait: (_) async {},
        fetch: () async {
          calls++;
          throw ApiError(code: code, message: '', statusCode: 403);
        },
      );
      await expectLater(stream.toList(), throwsA(isA<ApiError>()));
      expect(calls, 1);
    });
  }

  for (final (resumed, completed) in [
    (true, true),
    (true, false),
    (false, false),
  ]) {
    test(
      'expired polling rechecks only on foreground return ($resumed, $completed)',
      () async {
        var now = DateTime.utc(2026);
        var calls = 0;
        final statuses = <JobStatus>[];
        final stream = pollBookJob(
          jobId: 'existing-job',
          now: () => now,
          cancelled: () => false,
          wait: (_) async => fail('A successful read uses the normal wait'),
          waitBetweenReads: (_) async {
            now = now.add(const Duration(minutes: 11));
            return resumed;
          },
          fetch: () async {
            calls++;
            final done = calls == 2 && completed;
            return JobStatus(
              jobId: 'existing-job',
              status: done ? JobState.done : JobState.running,
              progress: done ? 100 : 50,
            );
          },
        );

        final collected = stream.forEach(statuses.add);
        if (completed) {
          await collected;
          expect(statuses.last.isComplete, isTrue);
          expect(statuses.map((status) => status.jobId), [
            'existing-job',
            'existing-job',
          ]);
        } else {
          await expectLater(collected, throwsA(isA<TimeoutException>()));
          expect(statuses.single.progress, 50);
        }
        expect(calls, resumed ? 2 : 1);
      },
    );
  }

  test(
    'a persistent outage is bounded by elapsed time, including Retry-After',
    () async {
      var now = DateTime.utc(2026);
      var calls = 0;
      final stream = pollBookJob(
        jobId: 'job',
        now: () => now,
        timeout: const Duration(seconds: 10),
        cancelled: () => false,
        waitBetweenReads: (_) async =>
            fail('Retry-After cannot be interrupted by foreground refresh'),
        wait: (delay) async {
          now = now.add(delay);
        },
        fetch: () async {
          calls++;
          throw ApiError(
            code: 'RATE_LIMIT_EXCEEDED',
            message: '',
            statusCode: 429,
            retryAfter: const Duration(minutes: 2),
          );
        },
      );
      await expectLater(stream.toList(), throwsA(isA<TimeoutException>()));
      expect(calls, 1);
      expect(now, DateTime.utc(2026).add(const Duration(seconds: 10)));
    },
  );

  testWidgets('a slow foreground recheck is cancelled after five seconds', (
    tester,
  ) async {
    final pending = Completer<JobStatus>();
    var requests = 0;
    var cancelled = false;
    final finished = pollBookJob(
      jobId: 'job',
      now: tester.binding.clock.now,
      timeout: const Duration(seconds: 3),
      cancelled: () => cancelled,
      cancelFetch: () => cancelled = true,
      wait: (_) async => fail('A successful read uses the normal wait'),
      waitBetweenReads: (delay) async {
        await Future<void>.delayed(delay);
        return true;
      },
      fetch: () async => ++requests == 1
          ? JobStatus(jobId: 'job', status: JobState.running, progress: 50)
          : pending.future,
    ).toList();
    final assertion = expectLater(finished, throwsA(isA<TimeoutException>()));

    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    expect(requests, 2);
    await tester.pump(const Duration(seconds: 4));
    expect(cancelled, isFalse);
    await tester.pump(const Duration(seconds: 1));
    await assertion;
    expect(cancelled, isTrue);
    pending.complete(
      JobStatus(jobId: 'job', status: JobState.done, progress: 100),
    );
    await tester.pump();
    expect(requests, 2);
  });

  testWidgets('the deadline cancels a status request still in flight', (
    tester,
  ) async {
    final pending = Completer<JobStatus>();
    final received = <JobStatus>[];
    var cancelled = false;
    var requests = 0;
    final finished = pollBookJob(
      jobId: 'job',
      now: tester.binding.clock.now,
      timeout: const Duration(seconds: 5),
      cancelled: () => cancelled,
      cancelFetch: () => cancelled = true,
      wait: (delay) => Future<void>.delayed(delay),
      fetch: () async {
        requests++;
        return requests == 1
            ? JobStatus(jobId: 'job', status: JobState.running, progress: 30)
            : pending.future;
      },
    ).forEach(received.add);
    final assertion = expectLater(finished, throwsA(isA<TimeoutException>()));

    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    expect(requests, 2);
    expect(cancelled, isFalse);
    await tester.pump(const Duration(seconds: 2));
    await assertion;
    expect(cancelled, isTrue);

    pending.complete(
      JobStatus(jobId: 'job', status: JobState.done, progress: 100),
    );
    await tester.pump();
    expect(received.map((status) => status.progress), [30]);
    expect(requests, 2);
  });

  testWidgets('status deadline offers to recheck the same generation', (
    tester,
  ) async {
    final checked = <String>[];
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobPollingProvider.overrideWith((ref, jobId) {
            checked.add(jobId);
            if (checked.length == 1) return Stream.error(TimeoutException(''));
            return Stream.value(
              JobStatus(jobId: jobId, status: JobState.running, progress: 65),
            );
          }),
        ],
        child: const MaterialApp(
          locale: Locale('ko'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: LoadingScreen(jobId: 'existing-job'),
        ),
      ),
    );
    await tester.pump();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.loadingStatusUnavailableTitle), findsOneWidget);
    expect(find.text(l.loadingRetryButton), findsNothing);
    await tester.tap(find.text(l.loadingCheckStatusButton));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('65%'), findsOneWidget);
    expect(checked, ['existing-job', 'existing-job']);
  });

  test('cancellation stops further requests after the current wait', () async {
    var cancelled = false;
    var calls = 0;
    await pollBookJob(
      jobId: 'job',
      cancelled: () => cancelled,
      wait: (_) async {
        cancelled = true;
      },
      fetch: () async {
        calls++;
        return JobStatus(jobId: 'job', status: JobState.running, progress: 30);
      },
    ).toList();
    expect(calls, 1);
  });
}
