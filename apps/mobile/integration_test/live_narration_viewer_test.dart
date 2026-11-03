// Opt-in disposable backend acceptance, replaying generic prerecorded narration.
// Never pass production credentials. No provider calls are made by this test.
import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  testWidgets(
    'real viewer plays each page and stops previous narration',
    (tester) async {
      final fixture = jsonDecode(fixtureJson) as Map<String, dynamic>;
      final uri = Uri.parse(fixture['base_url'] as String);
      expect(uri.host, '127.0.0.1');
      final api = _AgedMediaApi(
        baseUrl: uri.toString(),
        userKey: fixture['user_key'] as String,
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
          apiClientProvider.overrideWithValue(api),
          parentalControlServiceProvider.overrideWithValue(
            ParentalControlService()..markAgeGateVerified(),
          ),
        ],
      );
      addTearDown(container.dispose);
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
      Future<void> until(bool Function() ready) async {
        for (var i = 0; i < 300 && !ready(); i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(ready(), isTrue);
      }

      await until(() => find.byType(PageView).evaluate().isNotEmpty);
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
    skip: fixtureJson.isEmpty || !Platform.isIOS,
  );
}
