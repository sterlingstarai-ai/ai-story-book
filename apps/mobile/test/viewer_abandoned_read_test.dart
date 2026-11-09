import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/review_service.dart';
import 'package:ai_story_book/services/scoped_reading_progress.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ReadingApi extends ApiClient {
  _ReadingApi({this.failure, this.pending})
      : super(
            baseUrl: 'http://test',
            userKey: 'test-reader',
            enableLogging: false);

  final String? failure;
  final Completer<Map<String, dynamic>>? pending;
  final records = <({String bookId, int seconds, bool completed})>[];
  var streakReads = 0;

  @override
  Future<Map<String, dynamic>> getSettings() async =>
      {'allow_kakao_share': false};

  @override
  Future<Map<String, dynamic>> getStreakInfo() async {
    streakReads++;
    return {'current_streak': 1};
  }

  @override
  Future<Map<String, dynamic>> getTodayStory() async => {};

  @override
  Future<List<dynamic>> getReadingHistory({int days = 30}) async => [];

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) {
    records.add((bookId: bookId, seconds: readingTime, completed: completed));
    if (failure == 'sync') throw StateError('client already closed');
    if (failure == 'async') return Future.error(StateError('connection lost'));
    return pending?.future ?? Future.value(<String, dynamic>{});
  }
}

class _NoReview extends ReviewService {
  @override
  Future<void> requestReviewIfEligible(SharedPreferences prefs) async {}
}

class _ProgressStore extends BookMediaStore {
  _ProgressStore(super.preferences)
    : super(
        baseDirectory: () => throw StateError('Widget test uses no files'),
        scopeDigest: 'a' * 64,
      );

  @override
  Future<void> initialize() async {}
}

final _sessionApiProvider =
    StateProvider<ApiClient>((ref) => throw UnimplementedError());

BookResult _book() => BookResult(
      bookId: 'read-session-book',
      title: '세 장의 이야기',
      coverImageUrl: '',
      pages: [
        for (var page = 1; page <= 3; page++)
          PageResult(pageNumber: page, text: '$page 번째 이야기', imageUrl: ''),
      ],
    );

Future<ProviderContainer> _pumpViewer(
  WidgetTester tester,
  _ReadingApi api, {
  bool withBackStack = false,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  const bookId = 'read-session-book';
  final store = _ProgressStore(prefs);
  final container = ProviderContainer(overrides: [
    sharedPreferencesProvider.overrideWithValue(prefs),
    _sessionApiProvider.overrideWith((ref) => api),
    apiClientProvider.overrideWith((ref) => ref.watch(_sessionApiProvider)),
    reviewServiceProvider.overrideWithValue(_NoReview()),
    bookDetailProvider(bookId).overrideWith((ref) async => _book()),
    readingProgressProvider(bookId).overrideWith(
      (ref) async => ScopedReadingProgress(prefs, store, bookId, () => true),
    ),
    capabilitiesProvider
        .overrideWith((ref) async => {'audio_supported': false}),
  ]);
  addTearDown(container.dispose);
  const viewer = ViewerScreen(bookId: bookId);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: withBackStack
            ? Scaffold(
                body: Builder(
                  builder: (context) => TextButton(
                    onPressed: () => Navigator.of(context).pushNamed('/viewer'),
                    child: const Text('도서관'),
                  ),
                ),
              )
            : viewer,
        initialRoute: withBackStack ? '/viewer' : null,
        routes: withBackStack ? {'/viewer': (_) => viewer} : const {},
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 200));
  return container;
}

Future<void> _nextPage(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.chevron_right));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  await tester.pump();
}

Future<void> _closeViewer(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  // Flush player cleanup and the confetti ticker without pumpAndSettle's
  // unbounded wait on animations.
  await tester.pump(const Duration(seconds: 4));
}

void main() {
  testWidgets('closing after a story page records exactly one abandoned read',
      (tester) async {
    final api = _ReadingApi();
    await _pumpViewer(tester, api);
    await _nextPage(tester);
    expect(find.text('1 번째 이야기'), findsOneWidget);
    expect(api.records, isEmpty);
    await _closeViewer(tester);
    expect(api.records, hasLength(1));
    expect(api.records.single.bookId, 'read-session-book');
    expect(api.records.single.completed, isFalse);
    expect(api.records.single.seconds, greaterThanOrEqualTo(0));
    expect(tester.takeException(), isNull);
  });

  testWidgets('closing on the cover does not record an abandoned read',
      (tester) async {
    final api = _ReadingApi();
    await _pumpViewer(tester, api);
    await _closeViewer(tester);
    expect(api.records, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('system back records an abandoned read and returns to the library',
      (tester) async {
    final api = _ReadingApi();
    await _pumpViewer(tester, api, withBackStack: true);
    await _nextPage(tester);
    expect(find.text('1 번째 이야기'), findsOneWidget);
    expect(api.records, isEmpty);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle(
      const Duration(milliseconds: 50),
      EnginePhase.sendSemanticsUpdate,
      const Duration(seconds: 2),
    );
    expect(find.byType(ViewerScreen), findsNothing);
    expect(find.text('도서관'), findsOneWidget);
    expect(api.records, hasLength(1));
    expect(api.records.single.bookId, 'read-session-book');
    expect(api.records.single.completed, isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'a delayed successful exit record refreshes the cached home streak',
    (tester) async {
      final pending = Completer<Map<String, dynamic>>();
      final api = _ReadingApi(pending: pending);
      final container = await _pumpViewer(tester, api);
      await container.read(homeStreakProvider.future);
      expect(api.streakReads, 1);
      await _nextPage(tester);
      await _closeViewer(tester);
      await container.read(homeStreakProvider.future);
      expect(
        api.streakReads,
        1,
        reason: 'Do not refresh before the write succeeds.',
      );
      pending.complete({});
      await tester.pump();
      await container.read(homeStreakProvider.future);
      expect(api.streakReads, 2);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('a failed exit record leaves the cached streak intact', (
    tester,
  ) async {
    final api = _ReadingApi(failure: 'async');
    final container = await _pumpViewer(tester, api);
    await container.read(homeStreakProvider.future);
    await _nextPage(tester);
    await _closeViewer(tester);
    await container.read(homeStreakProvider.future);
    expect(api.streakReads, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'completion followed by disposal does not add an abandoned record',
    (tester) async {
      final pending = Completer<Map<String, dynamic>>();
      final api = _ReadingApi(pending: pending);
      await _pumpViewer(tester, api);
      await _nextPage(tester);
      await _nextPage(tester);
      await _nextPage(tester);
      expect(api.records, isEmpty);
      final finish = find.byKey(const Key('viewer-finish-reading'));
      await tester.ensureVisible(finish);
      await tester.tap(finish);
      await tester.pump();
      expect(api.records, hasLength(1));
      expect(api.records.single.completed, isTrue);
      await _closeViewer(tester);
      pending.complete({});
      await tester.pump();
      expect(api.records, hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('an unfinished last page reopens there and clears on completion', (
    tester,
  ) async {
    final api = _ReadingApi();
    final container = await _pumpViewer(tester, api, withBackStack: true);
    final prefs = container.read(sharedPreferencesProvider);
    final pageKey = scopedReadingProgressKey(
      'a' * 64,
      'read-session-book',
      'page',
    );
    await _nextPage(tester);
    await _nextPage(tester);
    await _nextPage(tester);
    expect(api.records, isEmpty);
    expect(prefs.getInt(pageKey), 3);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(api.records.single.completed, isFalse);
    await tester.tap(find.text('도서관'));
    await tester.pumpAndSettle();
    expect(find.text('3 번째 이야기'), findsOneWidget);

    final finish = find.byKey(const Key('viewer-finish-reading'));
    await tester.ensureVisible(finish);
    await tester.tap(finish);
    await tester.pump();
    expect(prefs.getInt(pageKey), isNull);
    await _closeViewer(tester);
    expect(api.records.map((record) => record.completed), [false, true]);
    expect(tester.takeException(), isNull);
  });

  for (final failure in ['sync', 'async']) {
    testWidgets('$failure recording failure does not interrupt viewer cleanup',
        (tester) async {
      final api = _ReadingApi(failure: failure);
      await _pumpViewer(tester, api);
      await _nextPage(tester);
      await _closeViewer(tester);
      expect(api.records, hasLength(1));
      expect(api.records.single.completed, isFalse);
      expect(find.byType(ViewerScreen), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'a provider identity change cannot send the read to another profile',
      (tester) async {
    final originalApi = _ReadingApi();
    final replacementApi = _ReadingApi();
    final container = await _pumpViewer(tester, originalApi);
    await _nextPage(tester);
    container.read(_sessionApiProvider.notifier).state = replacementApi;
    expect(container.read(apiClientProvider), same(replacementApi));
    await _closeViewer(tester);
    expect(originalApi.records, hasLength(1));
    expect(replacementApi.records, isEmpty);
    expect(tester.takeException(), isNull);
  });
}
