import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _User extends UserService {
  _User(super.prefs);
  @override
  String getUserKey() => 'synthetic-cache-test-key';
}

class _ProfileUser extends _User {
  _ProfileUser(super.prefs, this.profile);
  final String profile;
  @override
  String? getActiveProfileId() => profile;
}

class _BookApi extends ApiClient {
  _BookApi(this.load)
    : super(baseUrl: 'http://localhost', userKey: 'cache-test');

  final Future<BookResult> Function() load;

  @override
  Future<BookResult> getBook(String bookId) => load();
}

BookResult _book(String title) => BookResult(
  bookId: 'book-1',
  title: title,
  coverImageUrl: '',
  pages: const [],
);

void main() {
  final cacheKey = scopedBookCacheKey(
    'a' * 64,
    bookMediaProfileDigest(null),
    'book-1',
  );

  Future<(ProviderContainer, SharedPreferences)> setup(
    _BookApi api, {
    Future<BookMediaContext> Function(BookMediaStore)? initialize,
  }) async {
    SharedPreferences.setMockInitialValues({
      cacheKey: jsonEncode(_book('cached').toJson()),
    });
    final prefs = await SharedPreferences.getInstance();
    final directory = await Directory.systemTemp.createTemp('asb-detail-test-');
    final store = BookMediaStore(
      prefs,
      baseDirectory: () async => directory,
      scopeDigest: 'a' * 64,
    );
    final container = ProviderContainer(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        userServiceProvider.overrideWithValue(_User(prefs)),
        bookMediaStoreProvider.overrideWith(
          (ref) async =>
              await initialize?.call(store) ??
              BookMediaContext(store, serverVerified: false),
        ),
      ],
    );
    addTearDown(container.dispose);
    addTearDown(() async => directory.delete(recursive: true));
    return (container, prefs);
  }

  test(
    'detail fetch overlaps media setup without exposing an early book',
    () async {
      final mediaReady = Completer<void>();
      final detailStarted = Completer<void>();
      final (container, prefs) = await setup(
        _BookApi(() async {
          detailStarted.complete();
          return _book('fresh');
        }),
        initialize: (store) async {
          await mediaReady.future;
          return BookMediaContext(store, serverVerified: true);
        },
      );
      addTearDown(() {
        if (!mediaReady.isCompleted) mediaReady.complete();
      });
      final provider = bookDetailProvider('book-1');
      final result = container.read(provider.future);
      await detailStarted.future.timeout(const Duration(seconds: 2));
      expect(container.read(provider).isLoading, isTrue);
      expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'cached');
      mediaReady.complete();
      expect((await result).title, 'fresh');
      expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'fresh');
    },
  );

  test(
    'media authorization failure discards an early detail response',
    () async {
      final denied = StateError('Account media access is not authorized');
      final mediaReady = Completer<BookMediaContext>();
      final detailStarted = Completer<void>();
      final (container, prefs) = await setup(
        _BookApi(() async {
          detailStarted.complete();
          return _book('must not be displayed');
        }),
        initialize: (_) => mediaReady.future,
      );
      addTearDown(() {
        if (!mediaReady.isCompleted) mediaReady.completeError(denied);
      });
      final result = container.read(bookDetailProvider('book-1').future);
      final check = expectLater(result, throwsA(same(denied)));
      await detailStarted.future.timeout(const Duration(seconds: 2));
      mediaReady.completeError(denied);
      await check;
      expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'cached');
    },
  );

  test('deletion during media setup blocks an early detail response', () async {
    final mediaReady = Completer<void>();
    final mediaStore = Completer<BookMediaStore>();
    final detailStarted = Completer<void>();
    final (container, prefs) = await setup(
      _BookApi(() async {
        detailStarted.complete();
        return _book('must not be displayed');
      }),
      initialize: (store) async {
        mediaStore.complete(store);
        await mediaReady.future;
        return BookMediaContext(store, serverVerified: true);
      },
    );
    addTearDown(() {
      if (!mediaReady.isCompleted) mediaReady.complete();
    });
    final result = container.read(bookDetailProvider('book-1').future);
    final check = expectLater(result, throwsStateError);
    await detailStarted.future.timeout(const Duration(seconds: 2));
    final store = await mediaStore.future;
    await store.beginDeletion(
      'book-1',
      profileDigest: bookMediaProfileDigest(null),
    );
    mediaReady.complete();
    await check;
    expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'cached');
  });

  test('pending account cleanup skips the detail request', () async {
    var requests = 0;
    final (container, prefs) = await setup(
      _BookApi(() async {
        requests++;
        return _book('must not be requested');
      }),
    );
    await prefs.setBool(localMediaCleanupPendingKey, true);
    await expectLater(
      container.read(bookDetailProvider('book-1').future),
      throwsStateError,
    );
    expect(requests, 0);
  });

  test(
    'reopening a book obtains fresh media URLs instead of returning cache',
    () async {
      final (container, prefs) = await setup(
        _BookApi(() async => _book('fresh')),
      );
      final result = await container.read(bookDetailProvider('book-1').future);
      expect(result.title, 'fresh');
      expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'fresh');
    },
  );

  test('offline reading may use the saved book', () async {
    final (container, _) = await setup(
      _BookApi(
        () async => throw ApiError(
          code: 'NETWORK_ERROR',
          message: 'Offline',
          statusCode: 0,
        ),
      ),
    );
    final result = await container.read(bookDetailProvider('book-1').future);
    expect(result.title, 'cached');
  });

  for (final (status, code) in [
    (502, 'BAD_GATEWAY'),
    (503, 'SERVICE_UNAVAILABLE'),
    (504, 'GATEWAY_TIMEOUT'),
  ]) {
    test(
      'HTTP $status keeps the scoped copy until a fresh lookup succeeds',
      () async {
        var unavailable = true;
        final (container, prefs) = await setup(
          _BookApi(() async {
            if (unavailable) {
              throw ApiError(
                code: code,
                message: 'Temporary outage',
                statusCode: status,
              );
            }
            return _book('fresh');
          }),
        );
        final provider = bookDetailProvider('book-1');
        expect((await container.read(provider.future)).title, 'cached');
        expect(prefs.containsKey(cacheKey), isTrue);
        unavailable = false;
        container.invalidate(provider);
        expect((await container.read(provider.future)).title, 'fresh');
        expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'fresh');
      },
    );
  }

  test(
    'another account cannot read the same book id from offline cache',
    () async {
      final (first, prefs) = await setup(
        _BookApi(() async => _book('account A')),
      );
      await first.read(bookDetailProvider('book-1').future);
      final directory = await Directory.systemTemp.createTemp(
        'asb-other-account-',
      );
      final otherStore = BookMediaStore(
        prefs,
        baseDirectory: () async => directory,
        scopeDigest: 'b' * 64,
      );
      final offline = ApiError(
        code: 'NETWORK_ERROR',
        message: 'Offline',
        statusCode: 0,
      );
      final second = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(_User(prefs)),
          apiClientProvider.overrideWithValue(
            _BookApi(() async => throw offline),
          ),
          bookMediaStoreProvider.overrideWith(
            (ref) async => BookMediaContext(otherStore, serverVerified: false),
          ),
        ],
      );
      addTearDown(second.dispose);
      addTearDown(() async => directory.delete(recursive: true));
      await expectLater(
        second.read(bookDetailProvider('book-1').future),
        throwsA(same(offline)),
      );
      expect(prefs.getString(cacheKey), isNotNull);
    },
  );

  test('unowned historical cache is not used for offline reads', () async {
    final offline = ApiError(
      code: 'NETWORK_ERROR',
      message: 'Offline',
      statusCode: 0,
    );
    final (container, prefs) = await setup(_BookApi(() async => throw offline));
    await prefs.remove(cacheKey);
    await prefs.setString(
      'book_cache_book-1_v1',
      jsonEncode(_book('legacy').toJson()),
    );
    await expectLater(
      container.read(bookDetailProvider('book-1').future),
      throwsA(same(offline)),
    );
    expect(prefs.containsKey('book_cache_book-1_v1'), isTrue);
  });

  test('another profile cannot read the same account book offline', () async {
    final (first, prefs) = await setup(
      _BookApi(() async => _book('profile A')),
    );
    await first.read(bookDetailProvider('book-1').future);
    final directory = await Directory.systemTemp.createTemp(
      'asb-other-profile-',
    );
    final store = BookMediaStore(
      prefs,
      baseDirectory: () async => directory,
      scopeDigest: 'a' * 64,
    );
    final offline = ApiError(
      code: 'NETWORK_ERROR',
      message: 'Offline',
      statusCode: 0,
    );
    final second = ProviderContainer(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        userServiceProvider.overrideWithValue(_ProfileUser(prefs, 'profile-b')),
        apiClientProvider.overrideWithValue(
          _BookApi(() async => throw offline),
        ),
        bookMediaStoreProvider.overrideWith(
          (ref) async => BookMediaContext(store, serverVerified: false),
        ),
      ],
    );
    addTearDown(second.dispose);
    addTearDown(() async => directory.delete(recursive: true));
    await expectLater(
      second.read(bookDetailProvider('book-1').future),
      throwsA(same(offline)),
    );
    expect(prefs.getString(cacheKey), isNotNull);
  });

  for (final (status, code) in [
    (401, 'UNAUTHORIZED'),
    (403, 'NETWORK_ERROR'),
    (404, 'NOT_FOUND'),
    (503, 'PRIVACY_RECORD_UNAVAILABLE'),
  ]) {
    test(
      'HTTP $status does not bypass server denial with a cached book',
      () async {
        final denial = ApiError(
          code: code,
          message: 'Unavailable',
          statusCode: status,
        );
        final (container, prefs) = await setup(
          _BookApi(() async => throw denial),
        );
        await expectLater(
          container.read(bookDetailProvider('book-1').future),
          throwsA(same(denial)),
        );
        expect(prefs.containsKey(cacheKey), isFalse);
      },
    );
  }
}
