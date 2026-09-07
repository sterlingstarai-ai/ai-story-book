import 'dart:async';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _PendingBookApi extends ApiClient {
  _PendingBookApi()
    : super(baseUrl: 'http://test', userKey: 'synthetic', enableLogging: false);
  final pending = Completer<BookResult>();
  bool requested = false;
  @override
  Future<BookResult> getBook(String id) {
    requested = true;
    return pending.future;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'failed physical purge retains pending intent and retry removes offline child data only',
    () async {
      SharedPreferences.setMockInitialValues({
        'book_cache_old_v1': 'private story',
        'reading_progress_old_v1': 'page 3',
        'active_profile_id_v1': 'profile',
        'consent_granted_v1': false,
      });
      final prefs = await SharedPreferences.getInstance();
      var fail = true;
      var calls = 0;
      final cleanup = LocalMediaCleanup(
        prefs,
        purge: () async {
          calls++;
          if (fail) throw StateError('disk not writable');
        },
      );
      await expectLater(cleanup.run(), throwsStateError);
      expect(prefs.getBool(localMediaCleanupPendingKey), true);
      expect(prefs.getString('book_cache_old_v1'), 'private story');
      fail = false;
      await cleanup.retryPending();
      expect(calls, 2);
      expect(prefs.getBool(localMediaCleanupPendingKey), isNull);
      expect(prefs.getString('book_cache_old_v1'), isNull);
      expect(prefs.getString('reading_progress_old_v1'), isNull);
      expect(prefs.getString('active_profile_id_v1'), 'profile');
      expect(prefs.getBool('consent_granted_v1'), false);
    },
  );

  test(
    'an in-flight detail response cannot restore erased offline text',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = _PendingBookApi();
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(api),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
        ],
      );
      addTearDown(container.dispose);
      addTearDown(api.close);
      container.read(bookDetailProvider('synthetic-book'));
      expect(api.requested, true);
      await container.read(localMediaCleanupProvider).run();
      api.pending.complete(
        BookResult(
          bookId: 'synthetic-book',
          title: 'Private story',
          coverImageUrl: '',
          pages: [],
        ),
      );
      await Future<void>.delayed(Duration.zero);
      expect(prefs.getString('book_cache_synthetic-book_v1'), isNull);
      expect(prefs.getBool(localMediaCleanupPendingKey), isNull);
    },
  );

  test(
    'revoking consent forgets parent verification but keeps the already-seen introduction',
    () async {
      SharedPreferences.setMockInitialValues({
        ParentalControlService.onboardingDoneKey: true,
      });
      final prefs = await SharedPreferences.getInstance();
      final service = ParentalControlService()..markAgeGateVerified();
      await service.setConsent(prefs, false);
      expect(await service.hasSeenOnboarding(prefs), true);
      expect(prefs.getBool(ParentalControlService.consentGrantedKey), false);
    },
  );
}
