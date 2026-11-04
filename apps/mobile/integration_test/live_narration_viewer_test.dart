// Opt-in disposable backend acceptance. The prerecorded fixture is offline.
// The file fixture exercises continuous playback and may synthesize up to one
// narration per page. Use only a loopback backend with a synthetic account.
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
  @override
  Future<BookResult> getBook(String id) async {
    final book = await super.getBook(id);
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
    'real viewer plays each page and stops previous narration',
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
      expect(book.pages.length, 4);
      SharedPreferences.setMockInitialValues({
        ParentalControlService.consentGrantedKey: true,
        ParentalControlService.onboardingDoneKey: true,
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
      if (livePlayback) {
        final capabilities = await container.read(capabilitiesProvider.future);
        expect(narrationSupported(capabilities), isTrue);
      }
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            locale: const Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: ViewerScreen(bookId: id),
          ),
        ),
      );
      Future<void> until(bool Function() ready, {int seconds = 30}) async {
        for (var i = 0; i < seconds * 10 && !ready(); i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(ready(), isTrue);
      }

      await until(() => find.byType(PageView).evaluate().isNotEmpty);
      if (livePlayback) {
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        await until(
          () =>
              find.byTooltip(l.viewerMoreOptionsTooltip).evaluate().isNotEmpty,
        );
        await tester.tap(find.byTooltip(l.viewerMoreOptionsTooltip));
        final sleepMode = find.text(l.viewerSleepModeStart);
        await until(() => sleepMode.evaluate().isNotEmpty);
        await tester.ensureVisible(sleepMode);
        await tester.tap(sleepMode);
        final view = find.byType(PageView);
        final pause = find.byIcon(Icons.pause);
        for (var page = 1; page <= book.pages.length; page++) {
          await until(() {
            final position = tester.widget<PageView>(view).controller!.page;
            return position?.round() == page && pause.evaluate().isNotEmpty;
          }, seconds: 150);
          expect(find.byType(SnackBar), findsNothing);
        }
        await until(() => pause.evaluate().isEmpty, seconds: 150);
        expect(
          tester.widget<PageView>(view).controller!.page!.round(),
          book.pages.length,
        );
        expect(api.refreshed, [
          for (final page in book.pages)
            if ((page.audioUrlKo ?? page.audioUrl ?? '').isEmpty)
              page.pageNumber,
        ]);
        expect(find.byType(SnackBar), findsNothing);
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump(const Duration(milliseconds: 500));
        expect(tester.takeException(), isNull);
        return;
      }
      for (var n = 1; n <= 4; n++) {
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump(const Duration(milliseconds: 500));
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
        expect(api.refreshed, [1, 2, 3, 4]);
      }
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.takeException(), isNull);
    },
    skip:
        (fixtureJson.isEmpty && liveFixturePath.isEmpty) ||
        (!Platform.isIOS &&
            !(Platform.isAndroid && liveFixturePath.isNotEmpty)),
    timeout: const Timeout(Duration(minutes: 23)),
  );
}
