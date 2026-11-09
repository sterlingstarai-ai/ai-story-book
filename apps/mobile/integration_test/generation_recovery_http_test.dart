// Opt-in native test. Only a loopback HTTP server and synthetic data are used.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _waitFor(WidgetTester tester, bool Function() ready) async {
  final deadline = Stopwatch()..start();
  while (!ready() && deadline.elapsed < const Duration(seconds: 45)) {
    await tester.pump(const Duration(milliseconds: 250));
  }
  expect(ready(), isTrue);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'a real HTTP 503 followed by an empty active list refreshes home',
    (tester) async {
      const title = '달빛 도서관의 첫 동화';
      const account = 'synthetic-recovery-account';
      const profile = 'synthetic-recovery-profile';
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final trackedRequests = <(String, String?, String?, String?)>[];
      final mutationMethods = <String>[];
      var activeReads = 0;
      var libraryReads = 0;
      var finished = false;
      server.listen((request) {
        final path = request.uri.path;
        final response = request.response;
        if (request.method != 'GET') mutationMethods.add(request.method);
        if (path == '/v1/books/active-generations' || path == '/v1/library') {
          trackedRequests.add((
            path,
            request.headers.value('x-user-key'),
            request.headers.value('x-profile-id'),
            request.headers.value('x-request-id'),
          ));
        }
        response.headers.contentType = ContentType.json;
        Object body = <String, Object>{};
        switch (path) {
          case '/v1/books/active-generations':
            activeReads++;
            if (activeReads == 1) {
              response.statusCode = HttpStatus.serviceUnavailable;
              body = {
                'error': {'code': 'SERVICE_UNAVAILABLE', 'message': 'fixture'},
              };
            } else {
              body = const [];
            }
          case '/v1/library':
            libraryReads++;
            body = {
              'books': [
                if (finished)
                  {
                    'book_id': 'fixture-book',
                    'title': title,
                    'cover_image_url': '',
                    'target_age': '7-9',
                    'style': 'watercolor',
                    'created_at': '2026-11-08T00:00:00Z',
                  },
              ],
            };
          case '/v1/characters':
            body = const [];
        }
        response.write(jsonEncode(body));
        unawaited(response.close());
      });

      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = ApiClient(
        baseUrl: 'http://127.0.0.1:${server.port}',
        userKey: account,
        profileId: profile,
        enableLogging: false,
      );
      addTearDown(api.close);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(api),
          ],
          child: const MaterialApp(
            home: HomeScreen(),
            locale: Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
          ),
        ),
      );
      await _waitFor(tester, () => activeReads == 1 && libraryReads == 1);
      expect(find.text(title), findsNothing);
      finished = true;

      await _waitFor(tester, () => find.text(title).evaluate().isNotEmpty);
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(activeReads, 2);
      expect(libraryReads, 2);
      expect(mutationMethods, isEmpty);
      expect(trackedRequests.map((read) => read.$2), everyElement(account));
      expect(trackedRequests.map((read) => read.$3), everyElement(profile));
      expect(trackedRequests.map((read) => read.$4), everyElement(isNotEmpty));
      expect(trackedRequests.map((read) => read.$4).toSet(), hasLength(4));
      await tester.pumpWidget(const SizedBox.shrink());
    },
    skip: !const bool.fromEnvironment('RUN_LOCAL_GENERATION_RECOVERY'),
  );

  testWidgets(
    'home opens the same confirmed generation after an active-list HTTP 503',
    (tester) async {
      const jobId = 'synthetic-confirmed-job';
      const bookId = 'synthetic-recovered-book';
      const owner = 'synthetic-active-owner';
      const profile = 'synthetic-active-profile';
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      var activeReads = 0;
      final checkedJobs = <String>[];
      final mutationMethods = <String>[];
      server.listen((request) {
        final path = request.uri.path;
        final response = request.response;
        response.headers.contentType = ContentType.json;
        if (request.method != 'GET') mutationMethods.add(request.method);
        Object body = <String, Object>{};
        switch (path) {
          case '/v1/books/active-generations':
            activeReads++;
            if (activeReads == 2) {
              response.statusCode = HttpStatus.serviceUnavailable;
              body = {
                'error': {'code': 'SERVICE_UNAVAILABLE', 'message': 'fixture'},
              };
            } else {
              body = [
                if (activeReads == 1)
                  {'job_id': jobId, 'status': 'running', 'progress': 42},
              ];
            }
          case '/v1/books/$jobId':
            checkedJobs.add(path);
            if (request.headers.value('x-user-key') != owner ||
                request.headers.value('x-profile-id') != profile) {
              response.statusCode = HttpStatus.forbidden;
            } else {
              body = {
                'job_id': jobId,
                'status': 'done',
                'progress': 100,
                'result': {
                  'book_id': bookId,
                  'title': '완성한 시험 동화',
                  'cover_image_url': '',
                  'pages': [],
                },
              };
            }
          case '/v1/library':
            body = {'books': [], 'total': 0};
          case '/v1/characters':
            body = const [];
        }
        response.write(jsonEncode(body));
        unawaited(response.close());
      });

      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = ApiClient(
        baseUrl: 'http://127.0.0.1:${server.port}',
        userKey: owner,
        profileId: profile,
        enableLogging: false,
      );
      addTearDown(api.close);
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(api),
        ],
      );
      addTearDown(container.dispose);
      final openedBooks = <Object?>[];
      const viewer = Key('recovered-viewer');
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            home: const HomeScreen(),
            locale: const Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            onGenerateRoute: (settings) {
              if (settings.name != '/loading') return null;
              return MaterialPageRoute<void>(
                settings: settings,
                builder: (_) =>
                    LoadingScreen(jobId: settings.arguments! as String),
              );
            },
            routes: {
              '/viewer': (context) {
                openedBooks.add(ModalRoute.of(context)?.settings.arguments);
                return const Scaffold(key: viewer);
              },
            },
          ),
        ),
      );
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      final resume = find.byKey(const Key('home_resume_generation'));
      await _waitFor(tester, () => resume.hitTestable().evaluate().isNotEmpty);
      expect(find.text(l.libraryActiveGenerations(1)), findsOneWidget);

      container.invalidate(activeBookGenerationsProvider);
      await _waitFor(
        tester,
        () => container.read(activeBookGenerationsProvider).hasError,
      );
      await tester.pump();
      expect(find.text(l.loadingCheckStatusButton), findsOneWidget);
      expect(resume.hitTestable(), findsOneWidget);
      await tester.tap(resume);
      await _waitFor(tester, () => find.byKey(viewer).evaluate().isNotEmpty);
      expect(checkedJobs, ['/v1/books/$jobId']);
      expect(openedBooks, [bookId]);
      expect(mutationMethods, isEmpty);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    skip: !const bool.fromEnvironment('RUN_LOCAL_GENERATION_RECOVERY'),
  );

  testWidgets(
    'stable progress and HTTP backoff preserve the same generation',
    (tester) async {
      const jobId = 'synthetic-polling-job';
      const bookId = 'synthetic-completed-book';
      const account = 'synthetic-polling-account';
      const profile = 'synthetic-polling-profile';
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final clock = Stopwatch()..start();
      final reads = <Duration>[];
      final requestIds = <String?>[];
      final unexpectedRequests = <String>[];
      server.listen((request) {
        final response = request.response;
        if (request.method != 'GET' ||
            request.uri.path != '/v1/books/$jobId' ||
            request.headers.value('x-user-key') != account ||
            request.headers.value('x-profile-id') != profile) {
          unexpectedRequests.add(request.method);
          response.statusCode = HttpStatus.badRequest;
        } else {
          reads.add(clock.elapsed);
          requestIds.add(request.headers.value('x-request-id'));
          final done = reads.length >= 6;
          response.headers.contentType = ContentType.json;
          if (reads.length == 5) {
            response.statusCode = HttpStatus.tooManyRequests;
            response.headers.set(HttpHeaders.retryAfterHeader, '6');
            response.write(
              jsonEncode({
                'error': {'code': 'RATE_LIMIT_EXCEEDED', 'message': 'fixture'},
              }),
            );
          } else {
            response.write(
              jsonEncode({
                'job_id': jobId,
                'status': done ? 'done' : 'running',
                'progress': done
                    ? 100
                    : reads.length == 4
                    ? 50
                    : 30,
                'current_step': reads.length >= 4
                    ? 'generate_images'
                    : 'generate_story',
                if (done)
                  'result': {
                    'book_id': bookId,
                    'title': '시험 동화',
                    'cover_image_url': '',
                    'pages': [],
                  },
              }),
            );
          }
        }
        unawaited(response.close());
      });

      final api = ApiClient(
        baseUrl: 'http://127.0.0.1:${server.port}',
        userKey: account,
        profileId: profile,
        enableLogging: false,
      );
      addTearDown(api.close);
      const opened = Key('synthetic-viewer-opened');
      final openedBooks = <Object?>[];
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            home: const LoadingScreen(jobId: jobId),
            locale: const Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            routes: {
              '/viewer': (context) {
                openedBooks.add(ModalRoute.of(context)?.settings.arguments);
                return const Scaffold(key: opened);
              },
            },
          ),
        ),
      );
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      await _waitFor(tester, () => find.text('30%').evaluate().isNotEmpty);
      await _waitFor(tester, () => find.text('50%').evaluate().isNotEmpty);
      await _waitFor(
        tester,
        () => find.text(l.loadingStepRecheckingStatus).evaluate().isNotEmpty,
      );
      expect(find.text('50%'), findsOneWidget);
      final background = container.read(
        generationInBackgroundProvider.notifier,
      );
      background.state = true;
      await tester.pump(const Duration(seconds: 7));
      expect(reads, hasLength(5));
      background.state = false;
      await _waitFor(tester, () => find.byKey(opened).evaluate().isNotEmpty);
      expect(openedBooks, [bookId]);
      expect(reads, hasLength(6));
      expect(requestIds, everyElement(isNotEmpty));
      expect(requestIds.toSet(), hasLength(6));
      expect(unexpectedRequests, isEmpty);
      final gaps = List.generate(
        5,
        (index) => (reads[index + 1] - reads[index]).inMilliseconds,
      );
      expect(gaps, everyElement(greaterThanOrEqualTo(2800)));
      expect(gaps[2], greaterThanOrEqualTo(5800));
      expect(gaps[4], greaterThanOrEqualTo(6500));
      debugPrint('ASB_GENERATION_HTTP_POLL_GAPS_MS ${gaps.join(",")}');
      await tester.pumpWidget(const SizedBox.shrink());
    },
    skip: !const bool.fromEnvironment('RUN_LOCAL_GENERATION_POLLING'),
  );
}
