import 'dart:async';
import 'dart:io';

import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/book_scoped_cache_manager.dart';
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ReadOnlyLegacy extends Fake implements BaseCacheManager {
  _ReadOnlyLegacy(this.info);
  final FileInfo info;
  int reads = 0;

  @override
  Future<FileInfo?> getFileFromCache(String key, {bool ignoreMemCache = false}) async {
    reads++;
    return info;
  }
}

void main() {
  late Directory root;
  late BookMediaStore store;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    root = await Directory.systemTemp.createTemp('asb-scoped-cache-');
    store = BookMediaStore(
      prefs,
      baseDirectory: () async => root,
      scopeDigest: 'a' * 64,
    );
  });
  tearDown(() async {
    await store.shutdown();
    if (await root.exists()) await root.delete(recursive: true);
  });

  test(
    'cache operations stay in the selected book and reuse its file',
    () async {
      var downloads = 0;
      final manager = BookScopedCacheManager(
        store: store,
        bookId: 'book-a',
        fileExtension: 'mp3',
        download: (url, target, headers) async {
          downloads++;
          await target.writeAsString('synthetic audio');
        },
      );
      final first = await manager.getSingleFile(
        'https://example.invalid/audio',
        key: 'audio',
      );
      final second = await manager.getFileFromCache('audio');
      expect(second?.file.path, first.path);
      expect(await first.readAsString(), 'synthetic audio');
      expect(downloads, 1);
      await manager.removeFile('audio');
      expect(await manager.getFileFromCache('audio'), isNull);
      await expectLater(manager.emptyCache(), throwsUnsupportedError);
    },
  );

  test('late download cannot republish a confirmed deleted book', () async {
    final started = Completer<void>();
    final release = Completer<void>();
    final manager = BookScopedCacheManager(
      store: store,
      bookId: 'book-a',
      fileExtension: 'png',
      download: (url, target, headers) async {
        started.complete();
        await release.future;
        await target.writeAsString('late image');
      },
    );
    final loading = manager.getSingleFile('https://example.invalid/image');
    await started.future;
    final rejected = expectLater(loading, throwsStateError);
    final request = await store.beginDeletion(
      'book-a',
      profileDigest: 'b' * 64,
    );
    await store.confirmDeletion('book-a', request, profileDigest: 'b' * 64);
    final purge = store.purgeBook('book-a');
    release.complete();
    await rejected;
    await purge;
    expect(
      await manager.getFileFromCache('https://example.invalid/image'),
      isNull,
    );
  });

  test('HTTP status remains available for signed URL refresh', () async {
    final manager = BookScopedCacheManager(
      store: store,
      bookId: 'book-a',
      fileExtension: 'mp3',
      download: (_, __, ___) async =>
          throw const HttpExceptionWithStatus(403, 'unavailable'),
    );
    await expectLater(
      manager.getSingleFile('https://example.invalid/audio'),
      throwsA(
        isA<HttpExceptionWithStatus>().having(
          (e) => e.statusCode,
          'status',
          403,
        ),
      ),
    );
  });

  test('legacy cache is read only and blocked after a deletion request', () async {
    final old = await File('${root.path}/legacy').writeAsString('old audio');
    final legacy = _ReadOnlyLegacy(FileInfo(
      const LocalFileSystem().file(old.path),
      FileSource.Cache,
      DateTime.now().add(const Duration(days: 1)),
      'https://example.invalid/audio',
    ));
    final manager = BookScopedCacheManager(
      store: store,
      bookId: 'book-a',
      fileExtension: 'mp3',
      legacyReadOnly: legacy,
      download: (_, __, ___) async => throw StateError('must not download'),
    );
    expect((await manager.getSingleFile('https://example.invalid/audio')).path, old.path);
    expect(legacy.reads, 1);
    await store.beginDeletion('book-a', profileDigest: 'b' * 64);
    expect(await manager.getFileFromCache('https://example.invalid/audio'), isNull);
    expect(await old.exists(), isTrue);
  });
}
