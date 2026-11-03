import 'dart:io';
import 'dart:convert';

import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/book_cleanup_plan_journal.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:crypto/crypto.dart';

class _User extends UserService {
  _User(super.prefs, this.credential, {this.profile});
  final String credential;
  String? profile;
  @override
  String getUserKey() => credential;
  @override
  String? getActiveProfileId() => profile;
  @override
  Future<void> resumeKeyForDeletion() async {}
}

class _Api extends ApiClient {
  _Api({this.legacy = false})
    : super(baseUrl: 'http://synthetic', userKey: 'synthetic');
  final bool legacy;
  bool loseDeletionResponse = false;
  bool receiptAvailable = false;
  bool scopeUnavailable = false;
  bool otherScope = false;
  bool legacyDeleteCalled = false;
  int receiptChecks = 0;
  int receiptDeleteCalls = 0;
  int bookReads = 0;
  @override
  Future<BookResult> getBook(String bookId) async {
    bookReads++;
    return BookResult(
      bookId: bookId,
      title: 'Available',
      coverImageUrl: '',
      pages: const [],
    );
  }

  @override
  Future<String> getAccountMediaScope() async {
    if (scopeUnavailable) throw StateError('scope temporarily unavailable');
    if (otherScope) return 'b' * 64;
    if (legacy) {
      final request = RequestOptions(path: '/v1/account/media-scope');
      throw DioException(
        requestOptions: request,
        response: Response(requestOptions: request, statusCode: 404),
      );
    }
    return 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  }

  @override
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
    String? cursor,
    String? style,
    String? targetAge,
    String sort = 'newest',
  }) async => LibraryResponse(
    books: [
      LibraryBook(
        id: 'book-a',
        title: 'a',
        coverImageUrl: '',
        targetAge: '5-7',
        style: 'watercolor',
        createdAt: DateTime(2026),
      ),
    ],
    total: 1,
    nextCursor: null,
    hasMore: false,
  );
  @override
  Future<void> deleteBook(String bookId) async {
    legacyDeleteCalled = true;
  }

  @override
  Future<Map<String, dynamic>> deleteBookWithReceipt(
    String bookId,
    String requestId,
  ) async {
    receiptDeleteCalls++;
    if (loseDeletionResponse) throw StateError('synthetic lost response');
    return {'deletion_committed': true, 'purge_retry_pending': false};
  }

  @override
  Future<void> confirmBookDeletion(String bookId, String requestId) async {
    receiptChecks++;
    if (!receiptAvailable) throw StateError('not confirmed');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory directory;
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'book_cache_book-a_v1': 'preserve until confirmed',
      'reading_progress_book-a_v1': 3,
      'reading_progress_book-b_v1': 7,
    });
    prefs = await SharedPreferences.getInstance();
    directory = await Directory.systemTemp.createTemp('asb-book-integration-');
  });
  tearDown(() async {
    if (await directory.exists()) await directory.delete(recursive: true);
  });

  ProviderContainer container(
    _Api api, {
    String credential = 'credential-a',
    String? profile,
  }) {
    final registry = BookMediaRegistry(
      prefs,
      baseDirectory: () async => directory,
    );
    return ProviderContainer(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        userServiceProvider.overrideWithValue(
          _User(prefs, credential, profile: profile),
        ),
        apiClientProvider.overrideWithValue(api),
        apiBaseUrlProvider.overrideWithValue('https://synthetic.example'),
        bookMediaRegistryProvider.overrideWithValue(registry),
      ],
    );
  }

  test(
    'completed v1 tombstone blocks only its book and permits new media',
    () async {
      const base = 'https://synthetic.example';
      final oldScope = sha256
          .convert(
            utf8.encode(
              'asb:local-media-scope:v1\u0000$base\u0000credential-a',
            ),
          )
          .toString();
      final registry = BookMediaRegistry(
        prefs,
        baseDirectory: () async => directory,
      );
      final old = registry.forScope(oldScope);
      final profile = bookMediaProfileDigest('profile-a');
      final request = await old.beginDeletion('book-a', profileDigest: profile);
      await old.confirmDeletion('book-a', request, profileDigest: profile);
      await old.purgeBook('book-a');
      final api = _Api();
      final session = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(
            _User(prefs, 'credential-a', profile: 'profile-a'),
          ),
          apiClientProvider.overrideWithValue(api),
          apiBaseUrlProvider.overrideWithValue(base),
          bookMediaRegistryProvider.overrideWithValue(registry),
        ],
      );
      addTearDown(session.dispose);
      final media = await session.read(bookMediaStoreProvider.future);
      expect(media.legacyDeletions, isEmpty);
      expect(session.read(bookMediaBlockedProvider('book-a')), isTrue);
      expect(session.read(bookMediaBlockedProvider('book-c')), isFalse);
      await expectLater(
        session.read(bookDetailProvider('book-a').future),
        throwsStateError,
      );
      expect(api.bookReads, 0);
      expect(
        (await session.read(bookDetailProvider('book-c').future)).bookId,
        'book-c',
      );
      expect(api.bookReads, 1);
      final file = await media.store.write(
        'book-c',
        'image',
        extension: 'img',
        download: (f) => f.writeAsString('new').then((_) {}),
      );
      expect(await file.readAsString(), 'new');
      final otherProfile = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(
            _User(prefs, 'credential-a', profile: 'profile-b'),
          ),
          apiClientProvider.overrideWithValue(_Api()),
          apiBaseUrlProvider.overrideWithValue(base),
          bookMediaRegistryProvider.overrideWithValue(registry),
        ],
      );
      addTearDown(otherProfile.dispose);
      await otherProfile.read(bookMediaStoreProvider.future);
      expect(otherProfile.read(bookMediaBlockedProvider('book-a')), isFalse);
      expect(
        await otherProfile.read(pendingBookDeletionsProvider.future),
        isEmpty,
      );
      expect(
        (await otherProfile.read(bookDetailProvider('book-a').future)).bookId,
        'book-a',
      );
    },
  );

  test(
    'v1 requests reconcile only the matching profile while other books remain usable',
    () async {
      const base = 'https://synthetic.example';
      final oldScope = sha256
          .convert(
            utf8.encode(
              'asb:local-media-scope:v1\u0000$base\u0000credential-a',
            ),
          )
          .toString();
      final registry = BookMediaRegistry(
        prefs,
        baseDirectory: () async => directory,
      );
      final old = registry.forScope(oldScope);
      final oldFile = await old.write(
        'book-a',
        'image',
        extension: 'img',
        download: (f) => f.writeAsString('old').then((_) {}),
      );
      await old.beginDeletion(
        'book-a',
        profileDigest: bookMediaProfileDigest('profile-a'),
      );
      await old.beginDeletion(
        'book-b',
        profileDigest: bookMediaProfileDigest('profile-b'),
      );
      final api = _Api();
      final user = _User(prefs, 'credential-a', profile: 'profile-a');
      final session = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(user),
          apiClientProvider.overrideWithValue(api),
          apiBaseUrlProvider.overrideWithValue(base),
          bookMediaRegistryProvider.overrideWithValue(registry),
        ],
      );
      addTearDown(session.dispose);
      final media = await session.read(bookMediaStoreProvider.future);
      expect(media.legacyDeletions.map((e) => e.bookId), ['book-a']);
      expect(api.receiptChecks, 1);
      expect(await oldFile.readAsString(), 'old');
      expect(session.read(bookMediaBlockedProvider('book-a')), isTrue);
      expect(session.read(bookMediaBlockedProvider('book-c')), isFalse);
      await expectLater(
        session.read(bookDetailProvider('book-a').future),
        throwsStateError,
      );
      expect(api.bookReads, 0);
      expect(
        (await session.read(bookDetailProvider('book-c').future)).bookId,
        'book-c',
      );
      expect(api.bookReads, 1);
      api.receiptAvailable = true;
      session.invalidate(bookMediaStoreProvider);
      final reconciled = await session.read(bookMediaStoreProvider.future);
      expect(reconciled.legacyDeletions.map((e) => e.bookId), ['book-a']);
      expect((await old.pendingRequests()).map((e) => e.bookId), ['book-b']);
      expect(await oldFile.readAsString(), 'old');
      expect(session.read(bookMediaBlockedProvider('book-a')), isTrue);
    },
  );

  test('book deletion removes only the active profile text cache', () async {
    final api = _Api();
    final scope = container(api, profile: 'profile-a');
    await scope.read(libraryBrowseProvider.future);
    final media = await scope.read(bookMediaStoreProvider.future);
    final mine = scopedBookCacheKey(
      media.store.scopeDigest,
      bookMediaProfileDigest('profile-a'),
      'book-a',
    );
    final other = scopedBookCacheKey(
      media.store.scopeDigest,
      bookMediaProfileDigest('profile-b'),
      'book-a',
    );
    await prefs.setString(mine, 'profile a');
    await prefs.setString(other, 'profile b');
    await scope.read(libraryBrowseProvider.notifier).deleteBook('book-a');
    expect(prefs.getString(mine), isNull);
    expect(prefs.getString(other), 'profile b');
    scope.dispose();
  });

  test(
    'profile media is isolated and account cleanup removes every registered profile only',
    () async {
      await prefs.remove('book_cache_book-a_v1');
      await prefs.remove('reading_progress_book-a_v1');
      await prefs.remove('reading_progress_book-b_v1');
      final user = _User(prefs, 'credential-a', profile: 'profile-a');
      final registry = BookMediaRegistry(
        prefs,
        baseDirectory: () async => directory,
      );
      final session = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(user),
          apiClientProvider.overrideWithValue(_Api()),
          apiBaseUrlProvider.overrideWithValue('https://synthetic.example'),
          bookMediaRegistryProvider.overrideWithValue(registry),
          bookCleanupPlanJournalProvider.overrideWithValue(
            BookCleanupPlanJournal(baseDirectory: () async => directory),
          ),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
        ],
      );
      addTearDown(session.dispose);
      final a = (await session.read(bookMediaStoreProvider.future)).store;
      final fileA = await a.write(
        'same-book',
        'same-image',
        extension: 'img',
        download: (f) => f.writeAsString('a').then((_) {}),
      );
      user.profile = 'profile-b';
      session.invalidate(bookMediaStoreProvider);
      final b = (await session.read(bookMediaStoreProvider.future)).store;
      expect(b.scopeDigest, isNot(a.scopeDigest));
      expect(
        await b.lookup('same-book', 'same-image', extension: 'img'),
        isNull,
      );
      final fileB = await b.write(
        'same-book',
        'same-image',
        extension: 'img',
        download: (f) => f.writeAsString('b').then((_) {}),
      );
      final otherAccount = container(
        _Api()..otherScope = true,
        credential: 'credential-b',
        profile: 'profile-a',
      );
      addTearDown(otherAccount.dispose);
      final other = (await otherAccount.read(
        bookMediaStoreProvider.future,
      )).store;
      final fileOther = await other.write(
        'same-book',
        'same-image',
        extension: 'img',
        download: (f) => f.writeAsString('other').then((_) {}),
      );
      await session.read(localMediaCleanupProvider).run();
      expect(await fileA.exists(), isFalse);
      expect(await fileB.exists(), isFalse);
      expect(await fileOther.readAsString(), 'other');
    },
  );

  test(
    'historical account media requires explicit cleanup and preserves another account',
    () async {
      await prefs.clear();
      final user = _User(prefs, 'credential-a', profile: 'profile-a');
      final registry = BookMediaRegistry(
        prefs,
        baseDirectory: () async => directory,
      );
      final session = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(user),
          apiClientProvider.overrideWithValue(_Api()),
          apiBaseUrlProvider.overrideWithValue('https://synthetic.example'),
          bookMediaRegistryProvider.overrideWithValue(registry),
          bookCleanupPlanJournalProvider.overrideWithValue(
            BookCleanupPlanJournal(baseDirectory: () async => directory),
          ),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
        ],
      );
      addTearDown(session.dispose);
      await session.read(bookMediaStoreProvider.future);
      final profileKey = prefs.getKeys().singleWhere(
        (key) => key.startsWith('book_media_profile_scope_v2_'),
      );
      final accountScope = profileKey
          .substring('book_media_profile_scope_v2_'.length)
          .split('_')
          .first;
      final historical = registry.forScope(accountScope);
      final oldFile = await historical.write(
        'old-book',
        'image',
        extension: 'img',
        download: (file) => file.writeAsString('old').then((_) {}),
      );
      final otherAccount = container(
        _Api()..otherScope = true,
        credential: 'credential-b',
        profile: 'profile-b',
      );
      addTearDown(otherAccount.dispose);
      final otherStore = (await otherAccount.read(
        bookMediaStoreProvider.future,
      )).store;
      final otherFile = await otherStore.write(
        'other-book',
        'image',
        extension: 'img',
        download: (file) => file.writeAsString('other').then((_) {}),
      );
      await prefs.setBool(UserService.deletionCommittedKey, true);
      await expectLater(
        session.read(localMediaCleanupProvider).run(),
        throwsStateError,
      );
      expect(await oldFile.readAsString(), 'old');
      expect(await otherFile.readAsString(), 'other');
      await session.read(clearLegacyAccountMediaProvider)();
      expect(await oldFile.exists(), isFalse);
      expect(await otherFile.readAsString(), 'other');
      await session.read(localMediaCleanupProvider).retryPending();
      expect(prefs.getBool(localMediaCleanupPendingKey), isNull);
    },
  );

  test(
    'lost response preserves data until same-scope receipt is confirmed after restart',
    () async {
      final api = _Api()..loseDeletionResponse = true;
      final first = container(api);
      await first.read(libraryBrowseProvider.future);
      final media = await first.read(bookMediaStoreProvider.future);
      final file = await media.store.write(
        'book-a',
        'image',
        extension: 'png',
        download: (target) async {
          await target.writeAsString('private');
        },
      );
      final other = await media.store.write(
        'book-b',
        'image',
        extension: 'png',
        download: (target) async {
          await target.writeAsString('other');
        },
      );
      await expectLater(
        first.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
        throwsA(isA<BookDeletionUnconfirmed>()),
      );
      expect(await file.exists(), isTrue);
      expect(
        prefs.getString('book_cache_book-a_v1'),
        'preserve until confirmed',
      );
      expect(prefs.getInt('reading_progress_book-a_v1'), 3);
      expect((await media.store.pendingRequests()).length, 1);
      first.dispose();
      final recoveredApi = _Api();
      final restarted = container(recoveredApi);
      await restarted.read(bookMediaStoreProvider.future);
      expect(recoveredApi.receiptChecks, 1);
      expect(
        (await restarted.read(pendingBookDeletionsProvider.future)).length,
        1,
      );
      expect(await file.exists(), isTrue);
      recoveredApi.receiptAvailable = true;
      restarted.invalidate(bookMediaStoreProvider);
      await restarted.read(bookMediaStoreProvider.future);
      restarted.invalidate(pendingBookDeletionsProvider);
      expect(
        await restarted.read(pendingBookDeletionsProvider.future),
        isEmpty,
      );
      expect(await file.exists(), isFalse);
      expect(await other.exists(), isTrue);
      expect(
        prefs.getString('book_cache_book-a_v1'),
        'preserve until confirmed',
      );
      expect(prefs.getInt('reading_progress_book-b_v1'), 7);
      restarted.dispose();
    },
  );

  test('legacy server does not start deletion or create a marker', () async {
    final api = _Api(legacy: true);
    final scope = container(api);
    await scope.read(libraryBrowseProvider.future);
    final media = await scope.read(bookMediaStoreProvider.future);
    expect(media.serverVerified, isFalse);
    await media.store.beginDeletion(
      'older-request',
      profileDigest: bookMediaProfileDigest(null),
    );
    final file = await media.store.write(
      'book-a',
      'image',
      extension: 'png',
      download: (target) async {
        await target.writeAsString('private');
      },
    );
    await expectLater(
      scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
      throwsA(isA<BookDeletionNotStarted>()),
    );
    expect(api.legacyDeleteCalled, isFalse);
    expect(api.receiptDeleteCalls, 0);
    expect(await file.exists(), isTrue);
    expect(prefs.getInt('reading_progress_book-a_v1'), 3);
    final pending = await media.store.pendingRequests();
    expect(pending.map((request) => request.bookId), ['older-request']);
    expect(await media.store.canRead('book-a'), isTrue);
    expect(prefs.getString('book_cache_book-a_v1'), 'preserve until confirmed');
    await media.store.beginDeletion(
      'book-a',
      profileDigest: bookMediaProfileDigest(null),
    );
    await expectLater(
      scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
      throwsA(isA<BookDeletionUnconfirmed>()),
    );
    expect(api.legacyDeleteCalled, isFalse);
    expect(api.receiptDeleteCalls, 0);
    expect(await file.exists(), isTrue);
    expect(
      (await media.store.pendingRequests())
          .map((request) => request.bookId)
          .toSet(),
      {'older-request', 'book-a'},
    );
    scope.dispose();
  });

  test(
    'scope recheck failure distinguishes prior request without sending deletion',
    () async {
      final api = _Api();
      final scope = container(api);
      await scope.read(libraryBrowseProvider.future);
      final media = await scope.read(bookMediaStoreProvider.future);
      api.scopeUnavailable = true;
      await expectLater(
        scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
        throwsA(isA<BookDeletionNotStarted>()),
      );
      expect(await media.store.pendingRequests(), isEmpty);
      await media.store.beginDeletion(
        'book-a',
        profileDigest: bookMediaProfileDigest(null),
      );
      await expectLater(
        scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
        throwsA(isA<BookDeletionUnconfirmed>()),
      );
      expect(api.legacyDeleteCalled, isFalse);
      expect(api.receiptDeleteCalls, 0);
      expect((await media.store.pendingRequests()).length, 1);
      scope.dispose();
    },
  );

  test('changed server scope does not expose prior request status', () async {
    final api = _Api();
    final scope = container(api);
    await scope.read(libraryBrowseProvider.future);
    final media = await scope.read(bookMediaStoreProvider.future);
    api.otherScope = true;
    await expectLater(
      scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
      throwsA(isA<BookDeletionUnconfirmed>()),
    );
    await media.store.beginDeletion(
      'book-a',
      profileDigest: bookMediaProfileDigest(null),
    );
    await expectLater(
      scope.read(libraryBrowseProvider.notifier).deleteBook('book-a'),
      throwsA(isA<BookDeletionUnconfirmed>()),
    );
    expect(api.legacyDeleteCalled, isFalse);
    expect((await media.store.pendingRequests()).length, 1);
    scope.dispose();
  });
}
