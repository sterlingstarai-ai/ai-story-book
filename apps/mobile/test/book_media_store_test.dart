import 'dart:async';
import 'dart:io';

import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/share_staging.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late Directory temporary;
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'reading_progress_book-b_v1': 7,
      'book_cache_book-b_v1': 'other book',
    });
    prefs = await SharedPreferences.getInstance();
    temporary = await Directory.systemTemp.createTemp('asb-book-media-test-');
  });
  tearDown(() async {
    if (await temporary.exists()) await temporary.delete(recursive: true);
  });
  BookMediaStore createStore({
    Duration timeout = const Duration(seconds: 2),
    Future<void> Function(Directory directory)? deleteDirectory,
    String scope =
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  }) => BookMediaStore(
    prefs,
    baseDirectory: () async => temporary,
    scopeDigest: scope,
    drainTimeout: timeout,
    deleteDirectory: deleteDirectory,
  );
  Future<File> write(BookMediaStore store, String book, String media) =>
      store.write(
        book,
        media,
        extension: 'png',
        download: (file) async {
          await file.writeAsString(media);
        },
      );

  Future<void> confirm(BookMediaStore store, String book) async {
    const profile =
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
    final request = await store.beginDeletion(book, profileDigest: profile);
    await store.confirmDeletion(book, request, profileDigest: profile);
  }

  test('sharing removes sources on dismissal and failure', () async {
    final store = createStore();
    for (final fail in [false, true]) {
      late File source;
      final run = store.share(
        'book-a',
        extension: 'pdf',
        bytes: [1, 2],
        present: (file) async {
          source = file;
          expect(await file.readAsBytes(), [1, 2]);
          if (fail) throw StateError('chooser failed');
          return false;
        },
      );
      if (fail) {
        await expectLater(run, throwsStateError);
      } else {
        await run;
      }
      expect(await source.exists(), isFalse);
    }
  });

  test(
    'book purge drains sharing and removes only matching native handoff copies',
    () async {
      final store = createStore();
      final shown = Completer<File>();
      final close = Completer<bool>();
      final share = store.share(
        'book-a',
        extension: 'jpg',
        bytes: [5],
        present: (file) {
          shown.complete(file);
          return close.future;
        },
      );
      final source = await shown.future;
      final android = await Directory('${temporary.path}/share_plus').create();
      final name = source.uri.pathSegments.last;
      final copy = await source.copy('${android.path}/$name');
      final other = await source.copy(
        '${android.path}/${name.replaceFirst(store.scopeDigest, 'b' * 64)}',
      );
      await confirm(store, 'book-a');
      final purge = store.purgeBook('book-a');
      close.complete(true);
      await share;
      await purge;
      expect(await source.exists(), isFalse);
      expect(await copy.exists(), isFalse);
      expect(await other.exists(), isTrue);
      await expectLater(
        store.share(
          'book-a',
          extension: 'jpg',
          bytes: [1],
          present: (_) async => true,
        ),
        throwsStateError,
      );
    },
  );

  test(
    'startup cleans interrupted shares and expired Android copies; legacy cleanup requires confirmation',
    () async {
      final staging = await Directory(
        '${temporary.path}/asb_share_staging_v1',
      ).create();
      final plugin = await Directory('${temporary.path}/share_plus').create();
      final name =
          'asb-share-${'a' * 64}-${'b' * 64}-00000000-0000-4000-8000-000000000001.pdf';
      final file = await File('${staging.path}/$name').writeAsString('story');
      final copy = await file.copy('${plugin.path}/$name');
      await copy.setLastModified(DateTime(2020));
      final legacy = await file.copy('${temporary.path}/old story.pdf');
      final cover = await file.copy('${plugin.path}/old_cover.jpg');
      final other = await file.copy('${temporary.path}/unrelated.jpg');
      await ShareStaging.clean(temporary);
      expect(await file.exists(), isFalse);
      expect(await copy.exists(), isFalse);
      expect(await ShareStaging.legacyFiles(temporary), isTrue);
      expect(await legacy.exists(), isTrue);
      await ShareStaging.legacyFiles(temporary, remove: true);
      expect(await legacy.exists(), isFalse);
      expect(await cover.exists(), isFalse);
      expect(await other.exists(), isTrue);
    },
  );

  test(
    'an unconfirmed request survives restart without deleting local media',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      final request = await store.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      await expectLater(store.purgeBook('book-a'), throwsStateError);
      final restarted = createStore();
      await restarted.retryPending();
      expect(await file.exists(), isTrue);
      final pending = await restarted.pendingRequests();
      expect(pending.single.bookId, 'book-a');
      expect(pending.single.requestId, request);
      expect(pending.single.profileDigest, profile);
      await expectLater(write(restarted, 'book-a', 'new'), throwsStateError);
      await restarted.confirmDeletion(
        'book-a',
        request,
        profileDigest: profile,
      );
      await restarted.purgeBook('book-a');
      expect(await file.exists(), isFalse);
    },
  );

  test(
    'different accounts and profiles cannot confirm an old request',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      const otherProfile =
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
      const otherScope =
          'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
      final oldScope = createStore();
      final oldFile = await write(oldScope, 'book-a', 'old account');
      final request = await oldScope.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      final newScope = createStore(scope: otherScope);
      final newFile = await write(newScope, 'book-a', 'new account');
      expect(await newScope.pendingRequests(), isEmpty);
      await expectLater(
        newScope.confirmDeletion('book-a', request, profileDigest: profile),
        throwsStateError,
      );
      await expectLater(
        oldScope.confirmDeletion(
          'book-a',
          request,
          profileDigest: otherProfile,
        ),
        throwsStateError,
      );
      await newScope.retryPending();
      expect(await oldFile.exists(), isTrue);
      await oldScope.confirmDeletion('book-a', request, profileDigest: profile);
      await oldScope.purgeBook('book-a');
      expect(await oldFile.exists(), isFalse);
      expect(await newFile.readAsString(), 'new account');
    },
  );

  test(
    'a late response cannot confirm a newer request after rejection',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      final oldRequest = await store.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      await store.rejectDeletion('book-a', oldRequest, profileDigest: profile);
      final newRequest = await store.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      expect(newRequest, isNot(oldRequest));
      await expectLater(
        store.confirmDeletion('book-a', oldRequest, profileDigest: profile),
        throwsStateError,
      );
      await expectLater(
        store.rejectDeletion('book-a', oldRequest, profileDigest: profile),
        throwsStateError,
      );
      expect(await file.exists(), isTrue);
      await store.confirmDeletion('book-a', newRequest, profileDigest: profile);
      await store.purgeBook('book-a');
      expect(await file.exists(), isFalse);
    },
  );

  test('deleting one book keeps other files and reading progress', () async {
    final store = createStore();
    final a = await write(store, 'book-a', 'private a');
    final b = await write(store, 'book-b', 'private b');
    await confirm(store, 'book-a');
    await store.purgeBook('book-a');
    expect(await a.exists(), isFalse);
    expect(await b.readAsString(), 'private b');
    expect(await store.lookup('book-a', 'private a', extension: 'png'), isNull);
    expect(
      await store.lookup('book-b', 'private b', extension: 'png'),
      isNotNull,
    );
    expect(prefs.getInt('reading_progress_book-b_v1'), 7);
    expect(prefs.getString('book_cache_book-b_v1'), 'other book');
    await expectLater(write(store, 'book-a', 'late'), throwsStateError);
  });

  test('a late download cannot publish after the deletion marker', () async {
    final store = createStore();
    final started = Completer<File>();
    final release = Completer<void>();
    final download = store.write(
      'book-a',
      'image',
      extension: 'png',
      download: (file) async {
        started.complete(file);
        await release.future;
        await file.writeAsString('late child image');
      },
    );
    final part = await started.future;
    final failure = expectLater(download, throwsStateError);
    await confirm(store, 'book-a');
    final purge = store.purgeBook('book-a');
    release.complete();
    await failure;
    await purge;
    expect(await part.exists(), isFalse);
    expect(await store.lookup('book-a', 'image', extension: 'png'), isNull);
    await expectLater(write(store, 'book-a', 'later'), throwsStateError);
  });

  test(
    'file removal fences an earlier writer without touching another file',
    () async {
      final store = createStore();
      final other = await write(store, 'book-a', 'other');
      final started = Completer<void>();
      final release = Completer<void>();
      final pending = store.write(
        'book-a',
        'image',
        extension: 'png',
        download: (file) async {
          started.complete();
          await release.future;
          await file.writeAsString('late');
        },
      );
      await started.future;
      final failure = expectLater(pending, throwsStateError);
      await store.remove('book-a', 'image', extension: 'png');
      release.complete();
      await failure;
      expect(await store.lookup('book-a', 'image', extension: 'png'), isNull);
      expect(await other.readAsString(), 'other');
    },
  );

  test(
    'file removal remains available while book deletion is pending',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      await store.beginDeletion('book-a', profileDigest: profile);
      await store.remove('book-a', 'image', extension: 'png');
      expect(await file.exists(), isFalse);
    },
  );

  test('pending deletion is retried after a restart', () async {
    final first = createStore();
    final oldFile = await write(first, 'book-a', 'image');
    final other = await write(first, 'book-b', 'image');
    await confirm(first, 'book-a');
    final restarted = createStore();
    await restarted.retryPending();
    expect(await oldFile.exists(), isFalse);
    expect(await other.exists(), isTrue);
    await expectLater(write(restarted, 'book-a', 'another'), throwsStateError);
  });

  test(
    'flushed request survives a lost preferences mirror on restart',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      final request = await store.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      final key = prefs.getKeys().singleWhere(
        (key) => key.startsWith('book_media_state_v1_'),
      );
      await prefs.remove(key);
      final restarted = createStore();
      final pending = await restarted.pendingRequests();
      expect(pending.single.requestId, request);
      expect(await file.exists(), isTrue);
      await expectLater(write(restarted, 'book-a', 'late'), throwsStateError);
    },
  );

  test(
    'confirmed disk record wins over an older preference after restart',
    () async {
      const profile =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      final request = await store.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      final key = prefs.getKeys().singleWhere(
        (key) => key.startsWith('book_media_state_v1_'),
      );
      final oldMirror = prefs.getString(key)!;
      await store.confirmDeletion('book-a', request, profileDigest: profile);
      await prefs.setString(key, oldMirror);
      final restarted = createStore();
      await restarted.retryPending();
      expect(await file.exists(), isFalse);
    },
  );

  test(
    'failed physical removal keeps a marker and retry finishes it',
    () async {
      final first = createStore(
        deleteDirectory: (_) async => throw const FileSystemException('test'),
      );
      final file = await write(first, 'book-a', 'audio');
      await confirm(first, 'book-a');
      await expectLater(
        first.purgeBook('book-a'),
        throwsA(isA<FileSystemException>()),
      );
      expect(await file.exists(), isTrue);
      await expectLater(write(first, 'book-a', 'new'), throwsStateError);
      await createStore().retryPending();
      expect(await file.exists(), isFalse);
    },
  );

  test('a no-op delete cannot be mistaken for successful removal', () async {
    final store = createStore(deleteDirectory: (_) async {});
    final file = await write(store, 'book-a', 'image');
    await confirm(store, 'book-a');
    await expectLater(store.purgeBook('book-a'), throwsStateError);
    expect(await file.exists(), isTrue);
    await createStore().retryPending();
    expect(await file.exists(), isFalse);
  });

  test('a corrupt request marker blocks erasure and new writes', () async {
    const profile =
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
    final store = createStore();
    final file = await write(store, 'book-a', 'image');
    await store.beginDeletion('book-a', profileDigest: profile);
    final key = prefs.getKeys().singleWhere(
      (key) => key.startsWith('book_media_state_v1_'),
    );
    await prefs.setString(key, 'invalid');
    await expectLater(createStore().retryPending(), throwsStateError);
    await expectLater(write(store, 'book-a', 'new'), throwsStateError);
    expect(await file.exists(), isTrue);
  });

  test(
    'drain timeout stays pending and retry handles eventual completion',
    () async {
      final store = createStore(timeout: const Duration(milliseconds: 20));
      final started = Completer<void>();
      final release = Completer<void>();
      final download = store.write(
        'book-a',
        'audio',
        extension: 'mp3',
        download: (file) async {
          started.complete();
          await release.future;
          await file.writeAsString('late audio');
        },
      );
      await started.future;
      final failure = expectLater(download, throwsStateError);
      await confirm(store, 'book-a');
      await expectLater(
        store.purgeBook('book-a'),
        throwsA(isA<TimeoutException>()),
      );
      release.complete();
      await failure;
      await store.retryPending();
      expect(await store.lookup('book-a', 'audio', extension: 'mp3'), isNull);
      await expectLater(write(store, 'book-a', 'new'), throwsStateError);
    },
  );

  test(
    'a symlink in place of a book directory preserves outside files',
    () async {
      final outside = await Directory.systemTemp.createTemp(
        'asb-book-outside-',
      );
      addTearDown(() => outside.delete(recursive: true));
      final original = await File(
        '${outside.path}/original',
      ).writeAsString('keep');
      final store = createStore();
      final file = await write(store, 'book-a', 'image');
      final bookDir = file.parent;
      await bookDir.delete(recursive: true);
      await Link(bookDir.path).create(outside.path);
      await confirm(store, 'book-a');
      await expectLater(store.purgeBook('book-a'), throwsStateError);
      expect(await original.readAsString(), 'keep');
    },
  );
}
