import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/widgets/scoped_book_image.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Api extends ApiClient {
  _Api({this.queued, this.errorCode})
    : super(baseUrl: 'http://127.0.0.1:1', userKey: 'regeneration-test');

  final Completer<String>? queued;
  final String? errorCode;
  var calls = 0;
  var polls = 0;
  var detailReads = 0;

  @override
  Future<Map<String, dynamic>> getSettings() async => {};

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async => {};

  @override
  Future<String> regeneratePage(
    String jobId,
    int pageNumber, {
    required String regenerateTarget,
    String? feedback,
  }) {
    calls++;
    return queued?.future ?? Future.value('regeneration-job');
  }

  @override
  Future<JobStatus> getBookStatus(
    String jobId, {
    CancelToken? cancelToken,
  }) async {
    polls++;
    return JobStatus(
      jobId: jobId,
      status: errorCode == null ? JobState.running : JobState.failed,
      progress: 0,
      errorCode: errorCode,
      errorMessage: 'private diagnostics',
    );
  }
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

Future<AppLocalizations> _openReader(
  WidgetTester tester,
  _Api api, {
  Future<BookResult> Function()? readBook,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        capabilitiesProvider.overrideWith((ref) async => {}),
        if (readBook != null)
          bookMediaBlockedProvider('book').overrideWith((ref) => false),
        bookDetailProvider('book').overrideWith((ref) async {
          api.detailReads++;
          if (readBook != null) return readBook();
          return BookResult(
            bookId: 'book',
            jobId: 'original-job',
            title: 'Reading test',
            coverImageUrl: '',
            pages: [
              PageResult(pageNumber: 1, text: 'Original story', imageUrl: ''),
            ],
          );
        }),
      ],
      child: const MaterialApp(
        locale: Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ViewerScreen(bookId: 'book'),
      ),
    ),
  );
  await _settle(tester);
  return AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
}

Future<AppLocalizations> _pump(WidgetTester tester, _Api api) async {
  final l = await _openReader(tester, api);
  await tester.tap(find.byIcon(Icons.chevron_right));
  await _settle(tester);
  await _openOptions(tester, l);
  await tester.tap(find.text(l.viewerRegenerateImageOnly));
  await _settle(tester);
  return l;
}

Future<void> _openOptions(WidgetTester tester, AppLocalizations l) async {
  await tester.tap(find.byIcon(Icons.more_vert));
  await _settle(tester);
  await tester.tap(find.text(l.viewerRegeneratePageTitle));
  await _settle(tester);
}

Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 4));
}

void main() {
  testWidgets(
    'illustration link renewal can recover twice in one reading session',
    (tester) async {
      final api = _Api();
      final firstRenewal = Completer<BookResult>();
      BookResult book(String signature) => BookResult(
        bookId: 'book',
        jobId: 'original-job',
        title: 'Reading test',
        coverImageUrl:
            'https://fixture.invalid/cover.jpg?X-Amz-Signature=$signature',
        pages: [
          PageResult(pageNumber: 1, text: 'Original story', imageUrl: ''),
        ],
      );
      await _openReader(
        tester,
        api,
        readBook: () async => switch (api.detailReads) {
          1 => book('old'),
          2 => firstRenewal.future,
          _ => book('renewed-again'),
        },
      );
      ScopedBookImage illustration() =>
          tester.widget<ScopedBookImage>(find.byType(ScopedBookImage).first);
      illustration().onSignedUrlRejected!();
      illustration().onSignedUrlRejected!();
      await tester.pump();
      expect(api.detailReads, 2);
      firstRenewal.complete(book('renewed'));
      await _settle(tester);
      expect(illustration().imageUrl, endsWith('=renewed'));
      illustration().onSignedUrlRejected!();
      await tester.pump();
      expect(api.detailReads, 2);
      await tester.pump(const Duration(minutes: 1));
      illustration().onSignedUrlRejected!();
      await _settle(tester);
      expect(api.detailReads, 3);
      await tester.pump();
      expect(illustration().imageUrl, endsWith('=renewed-again'));
      await _close(tester);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('an expired distant illustration renews only near its page', (
    tester,
  ) async {
    final api = _Api();
    const expired =
        'https://fixture.invalid/page-3.jpg?X-Amz-Date=20200101T000000Z'
        '&X-Amz-Expires=60&X-Amz-Signature=old';
    await _openReader(
      tester,
      api,
      readBook: () async => BookResult(
        bookId: 'book',
        jobId: 'original-job',
        title: 'Reading test',
        coverImageUrl: '',
        pages: [
          for (var number = 1; number <= 4; number++)
            PageResult(
              pageNumber: number,
              text: 'Story page $number',
              imageUrl: number == 3 && api.detailReads == 1 ? expired : '',
            ),
        ],
      ),
    );
    await tester.pump(const Duration(minutes: 1));
    expect(api.detailReads, 1);
    await tester.tap(find.byIcon(Icons.chevron_right));
    await _settle(tester);
    expect(api.detailReads, 1);
    await tester.tap(find.byIcon(Icons.chevron_right));
    await _settle(tester);
    await _settle(tester);
    expect(api.detailReads, 2);
    expect(find.text('Story page 2').hitTestable(), findsOneWidget);
    await _close(tester);
    expect(tester.takeException(), isNull);
  });

  testWidgets('pending regeneration cannot be submitted a second time', (
    tester,
  ) async {
    final api = _Api();
    final l = await _pump(tester, api);
    await _openOptions(tester, l);
    expect(find.text(l.viewerRegenerateImageOnly), findsNothing);
    expect(api.calls, 1);
    expect(api.detailReads, 1);
    await _close(tester);
    expect(tester.takeException(), isNull);
  });

  testWidgets('leaving before the queued response never starts polling', (
    tester,
  ) async {
    final queued = Completer<String>();
    final api = _Api(queued: queued);
    await _pump(tester, api);
    await _close(tester);
    queued.complete('regeneration-job');
    await tester.pump();
    expect(api.calls, 1);
    expect(api.polls, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'asynchronous quality failure keeps the original and localized reason',
    (tester) async {
      final api = _Api(errorCode: 'IMAGE_QUALITY_FAILED');
      final l = await _pump(tester, api);
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 5));
      await _settle(tester);
      expect(api.polls, 1);
      expect(api.detailReads, 1);
      expect(find.text('Original story'), findsOneWidget);
      expect(find.text(l.viewerImageQualityFailed), findsOneWidget);
      expect(find.textContaining('private diagnostics'), findsNothing);
      await _close(tester);
      expect(tester.takeException(), isNull);
    },
  );
}
