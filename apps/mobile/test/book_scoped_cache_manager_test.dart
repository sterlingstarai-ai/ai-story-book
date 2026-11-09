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
  Future<FileInfo?> getFileFromCache(
    String key, {
    bool ignoreMemCache = false,
  }) async {
    reads++;
    return info;
  }
}

class _DelayedCacheMissStore extends BookMediaStore {
  _DelayedCacheMissStore(
    super.preferences, {
    required super.baseDirectory,
    required super.scopeDigest,
    required this.delayedIdentity,
  });

  final String delayedIdentity;
  final missObserved = Completer<void>();
  final releaseMiss = Completer<void>();

  @override
  Future<File?> lookup(
    String bookId,
    String mediaIdentity, {
    required String extension,
  }) async {
    final file = await super.lookup(
      bookId,
      mediaIdentity,
      extension: extension,
    );
    if (file == null &&
        mediaIdentity == delayedIdentity &&
        !missObserved.isCompleted) {
      missObserved.complete();
      await releaseMiss.future;
    }
    return file;
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

  test('one book reuses a connection across uncached illustrations', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final ports = <int>[];
    server.listen((request) async {
      ports.add(request.connectionInfo!.remotePort);
      request.response
        ..contentLength = 3
        ..write('img');
      await request.response.close();
    });
    final url = 'http://127.0.0.1:${server.port}';
    final before = BookScopedCacheManager(
      store: store,
      bookId: 'baseline',
      fileExtension: 'img',
    );
    final after = BookScopedCacheManager(
      store: store,
      bookId: 'pooled',
      fileExtension: 'img',
      reuseConnections: true,
    );
    try {
      for (var page = 1; page <= 4; page++) {
        final file = await before.getSingleFile('$url/$page');
        expect(await file.readAsString(), 'img');
      }
      expect(ports.toSet(), hasLength(4));
      ports.clear();
      for (var page = 1; page <= 4; page++) {
        final file = await after.getSingleFile('$url/$page');
        expect(await file.readAsString(), 'img');
      }
      expect(ports, hasLength(4));
      expect(ports.toSet(), hasLength(1));
    } finally {
      await before.dispose();
      await after.dispose();
      await server.close(force: true);
    }
    await expectLater(after.getSingleFile('$url/1'), throwsStateError);
  });

  test(
    'disposing pooled narration aborts a download before publication',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final started = Completer<void>();
      final release = Completer<void>();
      server.listen((request) async {
        started.complete();
        await release.future;
        try {
          await request.response.close();
        } on HttpException {
          // Disposal can close the peer before the fixture replies.
        }
      });
      final cache = BookScopedCacheManager(
        store: store,
        bookId: 'book-a',
        fileExtension: 'mp3',
        reuseConnections: true,
        connectionIdleTimeout: const Duration(minutes: 1),
      );
      try {
        final stopped = expectLater(
          cache.getSingleFile(
            'http://127.0.0.1:${server.port}/clip.mp3',
            key: 'narration-page-1',
          ),
          throwsA(isA<HttpException>()),
        );
        await started.future.timeout(const Duration(seconds: 5));
        await cache.dispose();
        await stopped.timeout(const Duration(seconds: 5));
        expect(
          await store.lookup('book-a', 'narration-page-1', extension: 'mp3'),
          isNull,
        );
      } finally {
        release.complete();
        await cache.dispose();
        await server.close(force: true);
      }
    },
  );

  test(
    'one failed illustration does not abort a sibling or its shared load',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final started = Completer<void>();
      final release = Completer<void>();
      var siblingRequests = 0;
      server.listen((request) async {
        if (request.uri.path == '/expired') {
          request.response.statusCode = HttpStatus.forbidden;
        } else {
          siblingRequests++;
          if (!started.isCompleted) started.complete();
          await release.future;
          request.response
            ..contentLength = 3
            ..write('img');
        }
        await request.response.close();
      });
      final url = 'http://127.0.0.1:${server.port}';
      final manager = BookScopedCacheManager(
        store: store,
        bookId: 'book-a',
        fileExtension: 'img',
        reuseConnections: true,
      );
      try {
        final first = manager.getSingleFile('$url/healthy');
        await started.future;
        final repeated = manager.getSingleFile('$url/healthy');
        await expectLater(
          manager.getSingleFile('$url/expired'),
          throwsA(isA<HttpExceptionWithStatus>()),
        );
        release.complete();
        expect(await (await first).readAsString(), 'img');
        expect((await repeated).path, (await first).path);
        expect(siblingRequests, 1);
      } finally {
        if (!release.isCompleted) release.complete();
        await manager.dispose();
        await server.close(force: true);
      }
    },
  );

  test(
    'renewed signing reuses an illustration and a replacement downloads',
    () async {
      const prefix = 'https://s3.test/storybooks/jobs/job_a/';
      const query = '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=';
      const first = '${prefix}0123456789abcdef0123456789abcdef.png${query}old';
      const refreshed =
          '${prefix}0123456789abcdef0123456789abcdef.png${query}new';
      const replacement =
          '${prefix}fedcba9876543210fedcba9876543210.png${query}new';
      final downloaded = <String>[];
      final manager = BookScopedCacheManager(
        store: store,
        bookId: 'book-a',
        fileExtension: 'img',
        download: (uri, target, _) async {
          downloaded.add(uri.toString());
          await target.writeAsString('synthetic illustration');
        },
      );
      final image = await manager.getSingleFile(first);
      expect((await manager.getSingleFile(refreshed)).path, image.path);
      expect(
        (await manager.getSingleFile(replacement)).path,
        isNot(image.path),
      );
      expect(downloaded, [first, replacement]);

      final otherBook = BookScopedCacheManager(
        store: store,
        bookId: 'book-b',
        fileExtension: 'img',
      );
      expect(await otherBook.getFileFromCache(refreshed), isNull);
      await store.beginDeletion('book-a', profileDigest: 'b' * 64);
      expect(await manager.getFileFromCache(refreshed), isNull);
    },
  );

  test('a late disk miss reuses the illustration just published', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final firstRequest = Completer<void>();
    final releaseFirst = Completer<void>();
    final signatures = <String>[];
    server.listen((request) async {
      final signature = request.uri.queryParameters['X-Amz-Signature']!;
      signatures.add(signature);
      if (signature == 'old') {
        firstRequest.complete();
        await releaseFirst.future;
      }
      request.response.write('illustration');
      await request.response.close();
    });
    final base =
        'http://127.0.0.1:${server.port}/books/jobs/job_a/'
        '0123456789abcdef0123456789abcdef.png'
        '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=';
    final prefs = await SharedPreferences.getInstance();
    final delayedStore = _DelayedCacheMissStore(
      prefs,
      baseDirectory: () async => root,
      scopeDigest: 'a' * 64,
      delayedIdentity: '${base}renewed',
    );
    final manager = BookScopedCacheManager(
      store: delayedStore,
      bookId: 'book-a',
      fileExtension: 'img',
      reuseConnections: true,
    );
    try {
      final first = manager.downloadFile('${base}old');
      await firstRequest.future.timeout(const Duration(seconds: 5));
      final late = manager.downloadFile('${base}renewed');
      await delayedStore.missObserved.future.timeout(
        const Duration(seconds: 5),
      );
      releaseFirst.complete();
      final published = await first;
      delayedStore.releaseMiss.complete();
      final reused = await late;
      expect(reused.source, FileSource.Cache);
      expect(reused.file.path, published.file.path);
      expect(await reused.file.readAsString(), 'illustration');
      expect(signatures, ['old']);
      final refreshed = await manager.downloadFile(
        '${base}forced',
        force: true,
      );
      expect(refreshed.source, FileSource.Online);
      expect(signatures, ['old', 'forced']);
    } finally {
      if (!releaseFirst.isCompleted) releaseFirst.complete();
      if (!delayedStore.releaseMiss.isCompleted) {
        delayedStore.releaseMiss.complete();
      }
      await manager.dispose();
      await delayedStore.shutdown();
      await server.close(force: true);
    }
  });

  for (final firstStatus in [HttpStatus.ok, HttpStatus.forbidden]) {
    test(
      'a renewed URL shares the active image and handles HTTP $firstStatus',
      () async {
        final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
        final started = Completer<void>();
        final release = Completer<void>();
        final signatures = <String>[];
        var active = 0;
        var peak = 0;
        server.listen((request) async {
          final signature = request.uri.queryParameters['X-Amz-Signature']!;
          signatures.add(signature);
          active++;
          if (active > peak) peak = active;
          if (signature == 'old') {
            started.complete();
            await release.future;
          }
          final response = request.response;
          response.statusCode = signature == 'old'
              ? firstStatus
              : HttpStatus.ok;
          if (response.statusCode == HttpStatus.ok) {
            response.write('illustration');
          }
          active--;
          await response.close();
        });
        final signed =
            'http://127.0.0.1:${server.port}/books/jobs/job_a/'
            '0123456789abcdef0123456789abcdef.png'
            '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=';
        final manager = BookScopedCacheManager(
          store: store,
          bookId: 'book-a',
          fileExtension: 'img',
          reuseConnections: true,
        );
        try {
          final first = manager.downloadFile('${signed}old', force: true);
          final original = firstStatus == HttpStatus.forbidden
              ? expectLater(first, throwsA(isA<HttpExceptionWithStatus>()))
              : first.then((file) async {
                  expect(await file.file.readAsString(), 'illustration');
                });
          await started.future;
          final renewed = manager.downloadFile('${signed}new', force: true);
          final secondReader = manager.downloadFile(
            '${signed}new',
            force: true,
          );
          release.complete();

          await original;
          final restored = await renewed;
          expect(await restored.file.readAsString(), 'illustration');
          expect((await secondReader).file.path, restored.file.path);
          expect(signatures, [
            'old',
            if (firstStatus == HttpStatus.forbidden) 'new',
          ]);
          expect(peak, 1);
        } finally {
          if (!release.isCompleted) release.complete();
          await manager.dispose();
          await server.close(force: true);
        }
      },
    );
  }

  test('a queued renewed URL cannot download after deletion begins', () async {
    const signed =
        'https://s3.test/books/jobs/job_a/'
        '0123456789abcdef0123456789abcdef.png'
        '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=';
    final started = Completer<void>();
    final release = Completer<void>();
    final attempted = <String>[];
    final manager = BookScopedCacheManager(
      store: store,
      bookId: 'book-a',
      fileExtension: 'img',
      download: (url, _, _) async {
        attempted.add(url.toString());
        started.complete();
        await release.future;
        throw const HttpExceptionWithStatus(403, 'expired');
      },
    );
    final old = expectLater(
      manager.downloadFile('${signed}old', force: true),
      throwsA(isA<HttpExceptionWithStatus>()),
    );
    await started.future;
    final fresh = expectLater(
      manager.downloadFile('${signed}new', force: true),
      throwsStateError,
    );
    try {
      await store.beginDeletion('book-a', profileDigest: 'b' * 64);
    } finally {
      release.complete();
    }
    await old;
    await fresh;
    expect(attempted, ['${signed}old']);
    expect(await manager.getFileFromCache('${signed}new'), isNull);
    await manager.dispose();
  });

  test('an older offline illustration still opens with its saved URL', () async {
    const url =
        'https://s3.test/storybooks/jobs/job_a/0123456789abcdef0123456789abcdef.png'
        '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=old';
    final previous = await store.write(
      'book-a',
      url,
      extension: 'img',
      download: (file) async {
        await file.writeAsString('existing illustration');
      },
    );
    final manager = BookScopedCacheManager(
      store: store,
      bookId: 'book-a',
      fileExtension: 'img',
      download: (_, __, ___) async => throw StateError('offline'),
    );
    expect((await manager.getSingleFile(url)).path, previous.path);
    await manager.removeFile(url);
    expect(await manager.getFileFromCache(url), isNull);
  });

  test(
    'legacy cache is read only and blocked after a deletion request',
    () async {
      final old = await File('${root.path}/legacy').writeAsString('old audio');
      final legacy = _ReadOnlyLegacy(
        FileInfo(
          const LocalFileSystem().file(old.path),
          FileSource.Cache,
          DateTime.now().add(const Duration(days: 1)),
          'https://example.invalid/audio',
        ),
      );
      final manager = BookScopedCacheManager(
        store: store,
        bookId: 'book-a',
        fileExtension: 'mp3',
        legacyReadOnly: legacy,
        download: (_, __, ___) async => throw StateError('must not download'),
      );
      expect(
        (await manager.getSingleFile('https://example.invalid/audio')).path,
        old.path,
      );
      expect(legacy.reads, 1);
      await store.beginDeletion('book-a', profileDigest: 'b' * 64);
      expect(
        await manager.getFileFromCache('https://example.invalid/audio'),
        isNull,
      );
      expect(await old.exists(), isTrue);
    },
  );
}
