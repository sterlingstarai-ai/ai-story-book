import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
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
  }) async =>
      {};

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
  Future<JobStatus> getBookStatus(String jobId) async {
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

Future<AppLocalizations> _pump(WidgetTester tester, _Api api) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        capabilitiesProvider.overrideWith((ref) async => {}),
        bookDetailProvider('book').overrideWith((ref) async {
          api.detailReads++;
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
  final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
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
