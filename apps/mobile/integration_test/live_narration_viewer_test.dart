// Opt-in acceptance with a synthetic account and a loopback backend.
// Inline fixtures can serve prerecorded audio. The live file fixture can
// synthesize up to one narration per page during continuous playback.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/page_audio_playback.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/widgets/scoped_book_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FixtureUser extends UserService {
  _FixtureUser(super.preferences, this.key);

  final String key;

  @override
  String getUserKey() => key;
}

// Inject only aged media URLs; all API requests still reach the disposable server.
class _AgedMediaApi extends ApiClient {
  _AgedMediaApi({
    required super.baseUrl,
    required super.userKey,
    required this.expired,
  }) : super(enableLogging: false);
  final Map<String, dynamic> expired;
  final refreshed = <int>[];
  final cachedLookups = <int>[];
  int bookDetailReads = 0;
  final acceptedReadingRecords = <({String bookId, bool completed})>[];

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async {
    final result = await super.recordReading(
      bookId: bookId,
      readingTime: readingTime,
      completed: completed,
    );
    acceptedReadingRecords.add((bookId: bookId, completed: completed));
    return result;
  }

  @override
  Future<String?> getCachedPageAudioUrl(
    String id,
    int page, {
    required String language,
    required String voice,
    required String style,
  }) async {
    final url = await super.getCachedPageAudioUrl(
      id,
      page,
      language: language,
      voice: voice,
      style: style,
    );
    cachedLookups.add(page);
    return url;
  }

  @override
  Future<BookResult> getBook(String id) async {
    final book = await super.getBook(id);
    bookDetailReads++;
    if (expired.isEmpty) return book;
    final json = book.toJson();
    for (final page in json['pages'] as List) {
      final url = expired[page['page_number'].toString()];
      if (url != null) {
        page['audio_url'] = url;
        page['audio_url_ko'] = url;
      }
    }
    return BookResult.fromJson(json);
  }

  @override
  Future<String> getPageAudioUrl(
    String id,
    int page, {
    String language = 'ko',
    String voice = 'default',
    String style = 'legacy',
  }) async {
    final url = await super.getPageAudioUrl(
      id,
      page,
      language: language,
      voice: voice,
      style: style,
    );
    refreshed.add(page);
    return url;
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const fixtureJson = String.fromEnvironment('NARRATION_VIEWER_FIXTURE');
  const liveFixturePath = String.fromEnvironment('LIVE_NARRATION_FIXTURE_PATH');
  testWidgets(
    'real viewer renders illustrations or plays the requested narration flow',
    (tester) async {
      final livePlayback = liveFixturePath.isNotEmpty;
      final String fixtureSource;
      if (livePlayback) {
        final file = File(liveFixturePath);
        final wait = Stopwatch()..start();
        while (!await file.exists() &&
            wait.elapsed < const Duration(minutes: 10)) {
          await Future<void>.delayed(const Duration(seconds: 1));
        }
        expect(
          await file.exists(),
          isTrue,
          reason: 'Disposable book was not ready',
        );
        fixtureSource = await file.readAsString();
      } else {
        fixtureSource = fixtureJson;
      }
      final fixture = jsonDecode(fixtureSource) as Map<String, dynamic>;
      final uri = Uri.parse(fixture['base_url'] as String);
      expect(uri.host, '127.0.0.1');
      final userKey = fixture['user_key'] as String;
      final api = _AgedMediaApi(
        baseUrl: uri.toString(),
        userKey: userKey,
        expired: (fixture['expired_audio_urls'] as Map<String, dynamic>?) ?? {},
      );
      addTearDown(api.close);
      final id = fixture['book_id'] as String;
      final book = await api.getBook(id);
      expect(book.pages.length, fixture['page_count'] as int? ?? 4);
      final imagesOnly = fixture['images_only'] == true;
      final verifyReadingExit = fixture['verify_reading_exit'] == true;
      final continuousPlayback =
          livePlayback || fixture['continuous_playback'] == true;
      if (imagesOnly) {
        expect(continuousPlayback, isFalse);
      }
      if (verifyReadingExit) expect(imagesOnly, isTrue);
      SharedPreferences.setMockInitialValues({
        ParentalControlService.consentGrantedKey: true,
        ParentalControlService.onboardingDoneKey: true,
        if (fixture['voice'] case final String voice)
          narrationVoicePreferenceKey: voice,
        if (fixture['style'] case final String style)
          narrationStylePreferenceKey: style,
      });
      final prefs = await SharedPreferences.getInstance();
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(_FixtureUser(prefs, userKey)),
          apiBaseUrlProvider.overrideWithValue(uri.toString()),
          apiClientProvider.overrideWithValue(api),
          parentalControlServiceProvider.overrideWithValue(
            ParentalControlService()..markAgeGateVerified(),
          ),
        ],
      );
      addTearDown(container.dispose);
      if (continuousPlayback) {
        final capabilities = await container.read(capabilitiesProvider.future);
        expect(narrationSupported(capabilities), isTrue);
      }
      final navigator = GlobalKey<NavigatorState>();
      const returnScreen = Key('reading-test-return-screen');
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            navigatorKey: navigator,
            locale: const Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: verifyReadingExit
                ? const Scaffold(key: returnScreen)
                : ViewerScreen(bookId: id),
          ),
        ),
      );
      if (verifyReadingExit) {
        unawaited(
          navigator.currentState!.push<void>(
            MaterialPageRoute(builder: (_) => ViewerScreen(bookId: id)),
          ),
        );
      }
      Future<void> until(bool Function() ready, {int seconds = 30}) async {
        for (var i = 0; i < seconds * 10 && !ready(); i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(ready(), isTrue);
      }

      await until(() => find.byType(PageView).evaluate().isNotEmpty);
      final verifyIllustrations =
          imagesOnly || fixture['verify_illustrations'] == true;
      final urls =
          (fixture['expected_illustration_urls'] as List?)?.cast<String>() ??
          [book.coverImageUrl, ...book.pages.map((p) => p.imageUrl)];
      final separateMedia = fixture['illustration_origin'] as String?;
      final view = find.byType(PageView);
      bool matchesIllustration(String renderedUrl, String expectedUrl) {
        if (renderedUrl == expectedUrl) return true;
        if (separateMedia == null) return false;
        final rendered = Uri.tryParse(renderedUrl);
        final expected = Uri.parse(expectedUrl);
        // Independent detail reads issue fresh signatures for the same object.
        return rendered != null &&
            rendered.isScheme('http') &&
            rendered.host == '127.0.0.1' &&
            rendered.origin == expected.origin &&
            rendered.path == expected.path &&
            rendered.queryParameters.containsKey('X-Amz-Signature');
      }

      bool illustrationDecoded(String url, {bool skipOffstage = true}) {
        final illustration = find.byWidgetPredicate(
          (widget) =>
              widget is ScopedBookImage &&
              matchesIllustration(widget.imageUrl, url),
          skipOffstage: skipOffstage,
        );
        return find
            .descendant(
              of: illustration,
              matching: find.byWidgetPredicate(
                (widget) =>
                    widget is RawImage &&
                    (widget.image?.width ?? 0) > 300 &&
                    (widget.image?.height ?? 0) > 300,
                skipOffstage: skipOffstage,
              ),
              skipOffstage: skipOffstage,
            )
            .evaluate()
            .isNotEmpty;
      }

      final retryIllustrationPages =
          (fixture['retry_illustration_pages'] as List?)?.cast<int>().toSet() ??
          <int>{};
      Future<void> retryIllustration(int page) async {
        final retry = find.widgetWithText(FilledButton, '그림 다시 불러오기');
        Future<void> waitForRetry() => until(
          () =>
              !container.read(bookDetailProvider(id)).isLoading &&
              retry.hitTestable().evaluate().length == 1,
        );
        await waitForRetry();
        expect(
          tester.getSize(retry.hitTestable()).height,
          greaterThanOrEqualTo(64),
        );
        if (page > 0) {
          expect(find.text(book.pages[page - 1].text), findsWidgets);
        }
        await tester.tap(retry.hitTestable());
        if (page == fixture['transient_detail_failure_page']) {
          await tester.pump();
          await waitForRetry();
          expect(find.text(book.pages[page - 1].text), findsWidgets);
          expect(tester.widget<PageView>(view).controller?.page?.round(), page);
          await tester.tap(retry.hitTestable());
        }
        await until(() => illustrationDecoded(urls[page]), seconds: 45);
        expect(retry.hitTestable(), findsNothing);
        expect(tester.widget<PageView>(view).controller?.page?.round(), page);
      }

      if (verifyIllustrations) {
        expect(urls.toSet(), hasLength(urls.length));
        final mediaOrigin = Uri.parse(separateMedia ?? uri.origin);
        expect(mediaOrigin.scheme, 'http');
        expect(mediaOrigin.host, '127.0.0.1');
        expect(mediaOrigin.userInfo, isEmpty);
        for (final url in urls) {
          expect(Uri.parse(url).origin, mediaOrigin.origin);
        }
        if (retryIllustrationPages.contains(0)) {
          await retryIllustration(0);
        } else {
          await until(() => illustrationDecoded(urls.first), seconds: 45);
        }
      }
      if (imagesOnly) {
        final checkLookahead = fixture['check_illustration_lookahead'] == true;
        for (final (index, url) in urls.indexed.skip(1)) {
          final staysRejected =
              index == fixture['permanently_rejected_illustration_page'];
          final needsRetry = retryIllustrationPages.contains(index);
          if (checkLookahead && !staysRejected && !needsRetry) {
            await until(
              () => illustrationDecoded(url, skipOffstage: false),
              seconds: 45,
            );
            expect(
              tester.widget<PageView>(view).controller?.page?.round(),
              index - 1,
            );
          }
          await tester.tap(find.byIcon(Icons.chevron_right));
          await tester.pump(const Duration(milliseconds: 500));
          await until(
            () =>
                tester.widget<PageView>(view).controller?.page?.round() ==
                    index &&
                (staysRejected || needsRetry
                    ? find.byIcon(Icons.broken_image).evaluate().isNotEmpty
                    : illustrationDecoded(url)),
            seconds: 45,
          );
          if (needsRetry) await retryIllustration(index);
          if (staysRejected) {
            expect(find.text(book.pages[index - 1].text), findsWidgets);
            await tester.pump(const Duration(milliseconds: 500));
          }
        }
        if (fixture['expected_book_detail_reads'] case final int count) {
          expect(api.bookDetailReads, count);
        }
        if (verifyReadingExit) {
          expect(api.acceptedReadingRecords, isEmpty);
          await tester.tap(find.byIcon(Icons.more_vert));
          final close = find.widgetWithIcon(ListTile, Icons.close);
          await until(() => close.hitTestable().evaluate().isNotEmpty);
          await tester.tap(close);
          await until(() => find.byType(ViewerScreen).evaluate().isEmpty);
          expect(find.byKey(returnScreen), findsOneWidget);
          await until(() => api.acceptedReadingRecords.isNotEmpty);
          expect(api.acceptedReadingRecords, [(bookId: id, completed: false)]);
        }
        await tester.pumpWidget(const SizedBox.shrink());
        expect(tester.takeException(), isNull);
        return;
      }
      if (continuousPlayback) {
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        final prefetchCheck = fixture['prefetch_check'] == true;
        final allPagesPrefetched = fixture['all_pages_prefetched'] == true;
        final embeddedPrefetch = fixture['embedded_audio_prefetch'] == true;
        final prefetchOverlap = fixture['prefetch_overlap'];
        expect(prefetchOverlap, isIn([null, 'handoff', 'timeout']));
        if (prefetchCheck) expect(book.pages.length, 3);
        if (allPagesPrefetched) {
          expect(prefetchCheck, isFalse);
          expect(prefetchOverlap, isNull);
        }
        if (embeddedPrefetch) {
          expect(book.pages.length, 3);
          expect(prefetchCheck || allPagesPrefetched, isFalse);
          expect(prefetchOverlap, isNull);
        }
        final timedOutPrefetch = prefetchOverlap == 'timeout';
        Future<void> releasePrefetch() async {
          final client = HttpClient();
          try {
            final request = await client.postUrl(
              uri.resolve('/release-prefetch'),
            );
            final response = await request.close();
            expect(response.statusCode, 204);
            await response.drain<void>();
          } finally {
            client.close();
          }
        }

        final sleepModePlayback = fixture['sleep_mode_playback'] == true;
        if (sleepModePlayback) {
          final options = find.byTooltip(l.viewerMoreOptionsTooltip);
          await until(() => options.evaluate().isNotEmpty);
          await tester.tap(options);
          final sleepMode = find.text(l.viewerSleepModeStart);
          await until(() => sleepMode.evaluate().isNotEmpty);
          await tester.ensureVisible(sleepMode);
          await tester.tap(sleepMode);
        } else {
          if (fixture['playback_speed'] case final String speed) {
            final options = find.byTooltip(l.viewerMoreOptionsTooltip);
            await until(() => options.evaluate().isNotEmpty);
            await tester.tap(options);
            await tester.pumpAndSettle();
            final speedMenu = find.text(l.viewerNarrationSpeed);
            await until(() => speedMenu.evaluate().isNotEmpty);
            await tester.ensureVisible(speedMenu);
            await until(() => speedMenu.hitTestable().evaluate().isNotEmpty);
            await tester.tap(speedMenu.hitTestable());
            await tester.pumpAndSettle();
            final choice = find.text(l.viewerNarrationSpeedValue(speed));
            await until(() => choice.evaluate().isNotEmpty);
            await tester.ensureVisible(choice);
            await until(() => choice.hitTestable().evaluate().isNotEmpty);
            await tester.tap(choice.hitTestable());
            await until(
              () =>
                  prefs.getDouble('narration_playback_speed_v1') ==
                  double.parse(speed),
            );
          }
          final listen = find.text(l.viewerListenFromStart).hitTestable();
          await until(() => listen.evaluate().isNotEmpty);
          await tester.tap(listen);
        }
        final pause = find.byIcon(Icons.pause);
        for (var page = 1; page <= book.pages.length; page++) {
          if (prefetchOverlap == 'handoff' && page == 2) {
            await until(
              () =>
                  tester.widget<PageView>(view).controller!.page!.round() ==
                      2 &&
                  find.text(l.viewerNarrationPreparing).evaluate().isNotEmpty,
            );
            await releasePrefetch();
          }
          await until(() {
            if (find.byType(SnackBar).evaluate().isNotEmpty) {
              fail('Unexpected playback error on page $page');
            }
            final position = tester.widget<PageView>(view).controller!.page;
            final visiblePage = position?.round();
            if (visiblePage != null && visiblePage > page) {
              fail('Expected narration on page $page before page $visiblePage');
            }
            return visiblePage == page &&
                pause.evaluate().isNotEmpty &&
                (!verifyIllustrations || illustrationDecoded(urls[page]));
          }, seconds: 150);
          if (timedOutPrefetch && page == 2) await releasePrefetch();
          expect(
            find.byKey(const Key('viewer_sleep_countdown')),
            sleepModePlayback ? findsOneWidget : findsNothing,
          );
          expect(find.byType(SnackBar), findsNothing);
          if ((prefetchCheck || allPagesPrefetched) &&
              page < book.pages.length) {
            await until(() => api.cachedLookups.contains(page + 1), seconds: 5);
            expect(
              tester.widget<PageView>(view).controller!.page!.round(),
              page,
            );
            expect(api.refreshed, [1, if (timedOutPrefetch && page == 2) 2]);
          }
          if (embeddedPrefetch && page < book.pages.length) {
            final store = (await container.read(
              bookMediaStoreProvider.future,
            )).store;
            final next = book.pages[page];
            final key = pageAudioCacheKey(
              id,
              page + 1,
              'ko',
              next.getText('ko'),
            );
            File? prefetched;
            for (
              var attempt = 0;
              attempt < 40 && prefetched == null;
              attempt++
            ) {
              await tester.pump(const Duration(milliseconds: 100));
              prefetched = await store.lookup(id, key, extension: 'mp3');
            }
            expect(prefetched, isNotNull);
            expect(
              tester.widget<PageView>(view).controller!.page!.round(),
              page,
            );
          }
        }
        await until(() => pause.evaluate().isEmpty, seconds: 150);
        expect(
          tester.widget<PageView>(view).controller!.page!.round(),
          book.pages.length,
        );
        if (fixture['expected_cached_audio_lookups'] case final List lookups) {
          expect(api.cachedLookups, lookups.cast<int>());
          expect(
            api.refreshed,
            (fixture['expected_audio_requests'] as List).cast<int>(),
          );
        } else if (embeddedPrefetch) {
          expect(api.cachedLookups, [3]);
          expect(api.refreshed, isEmpty);
        } else if (prefetchCheck) {
          expect(api.cachedLookups, [2, 3]);
          expect(api.refreshed, [1, if (timedOutPrefetch) 2, 3]);
        } else if (allPagesPrefetched) {
          expect(api.cachedLookups, [
            for (var page = 2; page <= book.pages.length; page++) page,
          ]);
          expect(api.refreshed, [1]);
        } else {
          expect(api.refreshed, [
            for (final page in book.pages)
              if ((page.audioUrlKo ?? page.audioUrl ?? '').isEmpty)
                page.pageNumber,
          ]);
        }
        expect(find.byType(SnackBar), findsNothing);
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump(const Duration(milliseconds: 500));
        expect(tester.takeException(), isNull);
        return;
      }
      for (var n = 1; n <= book.pages.length; n++) {
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump(const Duration(milliseconds: 500));
        if (verifyIllustrations) {
          await until(() => illustrationDecoded(urls[n]), seconds: 45);
        }
        await until(() => find.byIcon(Icons.volume_up).evaluate().isNotEmpty);
        expect(find.byIcon(Icons.pause), findsNothing);
        await tester.tap(find.byIcon(Icons.volume_up));
        await until(() => find.byIcon(Icons.pause).evaluate().isNotEmpty);
        await tester.pump(const Duration(milliseconds: 400));
        await tester.tap(find.byIcon(Icons.pause));
        await until(() => find.byIcon(Icons.volume_up).evaluate().isNotEmpty);
        await tester.tap(find.byIcon(Icons.volume_up));
        await until(() => find.byIcon(Icons.pause).evaluate().isNotEmpty);
        if (fixture['wait_for_completion'] == true) {
          await until(() => find.byIcon(Icons.volume_up).evaluate().isNotEmpty);
          expect(find.byType(SnackBar), findsNothing);
          expect(tester.takeException(), isNull);
        }
      }
      if (api.expired.isNotEmpty) {
        expect(
          api.refreshed,
          book.pages.map((page) => page.pageNumber).toList(),
        );
      }
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.takeException(), isNull);
    },
    skip:
        (fixtureJson.isEmpty && liveFixturePath.isEmpty) ||
        !(Platform.isIOS || Platform.isAndroid),
    timeout: const Timeout(Duration(minutes: 23)),
  );
}
