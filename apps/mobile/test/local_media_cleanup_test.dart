import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/book_cleanup_plan_journal.dart';
import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _User extends UserService {
  _User(super.prefs);
  @override
  String getUserKey() => 'synthetic-cleanup-test-key';
}

class _PendingBookApi extends ApiClient {
  _PendingBookApi()
    : super(baseUrl: 'http://test', userKey: 'synthetic', enableLogging: false);
  final pending = Completer<BookResult>();
  bool requested = false;
  @override
  Future<String> getAccountMediaScope() async =>
      throw StateError('synthetic legacy server');
  @override
  Future<BookResult> getBook(String id) {
    requested = true;
    return pending.future;
  }
}

void main() {
  test(
    'v1 account cache without a profile remains unowned and is not deleted',
    () async {
      final legacy = 'book_cache_scoped_v1_${'a' * 64}_${'b' * 64}';
      SharedPreferences.setMockInitialValues({legacy: 'private data'});
      final prefs = await SharedPreferences.getInstance();
      await expectLater(
        LocalMediaCleanup(prefs, purge: () async {}).run(),
        throwsStateError,
      );
      expect(prefs.getString(legacy), 'private data');
      expect(prefs.getBool(localMediaCleanupPendingKey), isTrue);
    },
  );
  test(
    'shared image cache is preserved and blocks cleanup when ownership is unknown',
    () async {
      final temporary = await Directory.systemTemp.createTemp(
        'asb-shared-cache-test-',
      );
      addTearDown(() async => temporary.delete(recursive: true));
      final cache = Directory('${temporary.path}/${DefaultCacheManager.key}');
      await cache.create();
      final other = File('${cache.path}/other-account-image');
      await other.writeAsString('other account data');
      await expectLater(
        ensureSharedImageCacheEmpty(temporary),
        throwsStateError,
      );
      expect(await other.readAsString(), 'other account data');
    },
  );
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'queued cleanup calls each run even when the first is in flight',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final firstEntered = Completer<void>();
      final unblock = Completer<void>();
      var calls = 0;
      final cleanup = LocalMediaCleanup(
        prefs,
        purge: () async {
          calls++;
          if (calls == 1) {
            firstEntered.complete();
            await unblock.future;
          }
        },
      );
      final first = cleanup.run();
      await firstEntered.future;
      final second = cleanup.run();
      unblock.complete();
      await Future.wait([first, second]);
      expect(calls, 2);
    },
  );

  test('file commitment can only advance a matching cleanup plan', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final consent = jsonEncode({
      'scopes': ['a'],
      'metadata_keys': [],
      'kind': 'consent',
    });
    final account = jsonEncode({
      'scopes': ['a'],
      'metadata_keys': [],
      'kind': 'account',
    });
    await prefs.setString(bookMediaCleanupPlanKey, consent);
    expect(
      await reconcileBookCleanupPlan(prefs, () async => account, (_) async {}),
      account,
    );
    expect(prefs.getString(bookMediaCleanupPlanKey), account);
    await prefs.setString(
      bookMediaCleanupPlanKey,
      jsonEncode({
        'scopes': ['b'],
        'metadata_keys': [],
        'kind': 'consent',
      }),
    );
    await expectLater(
      reconcileBookCleanupPlan(prefs, () async => account, (_) async {}),
      throwsStateError,
    );
  });
  test(
    'failed physical purge retains pending intent and retry removes offline child data only',
    () async {
      SharedPreferences.setMockInitialValues({
        'book_cache_old_v1': 'private story',
        'reading_progress_old_v1': 'page 3',
        'branch_story_progress_old_v1': 'choice 2',
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
      await expectLater(cleanup.retryPending(), throwsStateError);
      expect(calls, 2);
      expect(prefs.getBool(localMediaCleanupPendingKey), isTrue);
      expect(prefs.getString('book_cache_old_v1'), 'private story');
      expect(prefs.getString('reading_progress_old_v1'), 'page 3');
      expect(prefs.getString('branch_story_progress_old_v1'), 'choice 2');
      expect(prefs.getString('active_profile_id_v1'), 'profile');
      expect(prefs.getBool('consent_granted_v1'), false);
    },
  );

  test(
    'account deletion preserves unowned legacy entries and remains pending',
    () async {
      SharedPreferences.setMockInitialValues({
        UserService.deletionCommittedKey: true,
        'book_cache_old_v1': 'private story',
        'reading_progress_old_v1': 'page 3',
        'branch_story_progress_old_v1': 'choice 2',
      });
      final prefs = await SharedPreferences.getInstance();
      await expectLater(
        LocalMediaCleanup(prefs, purge: () async {}).run(),
        throwsStateError,
      );
      expect(prefs.containsKey('book_cache_old_v1'), isTrue);
      expect(prefs.containsKey('reading_progress_old_v1'), isTrue);
      expect(prefs.containsKey('branch_story_progress_old_v1'), isTrue);
      expect(prefs.getBool(localMediaCleanupPendingKey), isTrue);
    },
  );

  test(
    'cleanup removes only caches belonging to planned account scopes',
    () async {
      final mine = scopedBookCacheKey('a' * 64, 'c' * 64, 'same-book');
      final other = scopedBookCacheKey('b' * 64, 'c' * 64, 'same-book');
      SharedPreferences.setMockInitialValues({
        mine: 'mine',
        other: 'other',
        bookMediaCleanupPlanKey: jsonEncode({
          'scopes': ['a' * 64],
          'metadata_keys': [],
          'kind': 'consent',
        }),
      });
      final prefs = await SharedPreferences.getInstance();
      await LocalMediaCleanup(prefs, purge: () async {}).run();
      expect(prefs.containsKey(mine), isFalse);
      expect(prefs.getString(other), 'other');
      expect(prefs.getBool(localMediaCleanupPendingKey), isNull);
    },
  );

  test(
    'an in-flight detail response cannot restore erased offline text',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = _PendingBookApi();
      final directory = await Directory.systemTemp.createTemp(
        'asb-cleanup-test-',
      );
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(_User(prefs)),
          apiClientProvider.overrideWithValue(api),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
          bookMediaRegistryProvider.overrideWithValue(
            BookMediaRegistry(prefs, baseDirectory: () async => directory),
          ),
          bookCleanupPlanJournalProvider.overrideWithValue(
            BookCleanupPlanJournal(baseDirectory: () async => directory),
          ),
        ],
      );
      addTearDown(container.dispose);
      addTearDown(api.close);
      addTearDown(() async => directory.delete(recursive: true));
      await container.read(bookMediaStoreProvider.future);
      container.read(bookDetailProvider('synthetic-book'));
      await Future<void>.delayed(Duration.zero);
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
