import 'dart:async';
import 'dart:io';

import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  const first =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  const second =
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
  const profile =
      'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
  late SharedPreferences prefs;
  late Directory directory;
  late BookMediaRegistry registry;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
    directory = await Directory.systemTemp.createTemp('asb-registry-test-');
    registry = BookMediaRegistry(prefs, baseDirectory: () async => directory);
  });
  tearDown(() async {
    if (await directory.exists()) await directory.delete(recursive: true);
  });

  Future<File> put(BookMediaStore store, String book, String data) =>
      store.write(
        book,
        'image',
        extension: 'png',
        download: (file) async {
          await file.writeAsString(data);
        },
      );

  test(
    'cleanup inventory waits for an in-flight profile registration',
    () async {
      final started = Completer<void>();
      final finish = Completer<void>();
      final order = <String>[];
      final registration = registry.guardProfileRegistration(() async {
        order.add('registration-start');
        started.complete();
        await finish.future;
        order.add('registration-end');
      });
      await started.future;
      final inventory = registry.guardProfileRegistration(
        () async => order.add('inventory'),
      );
      await Future<void>.delayed(Duration.zero);
      expect(order, ['registration-start']);
      finish.complete();
      await Future.wait([registration, inventory]);
      expect(order, ['registration-start', 'registration-end', 'inventory']);
    },
  );

  test('account cleanup removes only named scope files and journals', () async {
    final a = registry.forScope(first);
    final b = registry.forScope(second);
    final aFile = await put(a, 'book-a', 'a');
    final bFile = await put(b, 'book-b', 'b');
    await a.beginDeletion('book-a', profileDigest: profile);
    final bRequest = await b.beginDeletion('book-b', profileDigest: profile);
    await registry.purgeScopes({first}, eraseJournal: true);
    expect(await aFile.exists(), isFalse);
    expect(await bFile.readAsString(), 'b');
    expect((await b.pendingRequests()).single.requestId, bRequest);
    registry.releasePurgedScopes();
  });

  test(
    'verified migration moves distinct books and their request records',
    () async {
      final source = registry.forScope(first);
      final target = registry.forScope(second);
      final old = await put(source, 'book-a', 'private');
      final other = await put(target, 'book-b', 'other');
      final request = await source.beginDeletion(
        'book-a',
        profileDigest: profile,
      );
      await registry.migrateScopes(first, second);
      expect(await old.exists(), isFalse);
      expect(await other.readAsString(), 'other');
      final migrated = registry.forScope(second);
      expect((await migrated.pendingRequests()).single.requestId, request);
      await expectLater(put(migrated, 'book-a', 'late'), throwsStateError);
      expect(await registry.hasScopeData(first), isFalse);
    },
  );

  test(
    'same-book collision refuses migration without deleting either file',
    () async {
      final source = registry.forScope(first);
      final target = registry.forScope(second);
      final left = await put(source, 'same-book', 'left');
      final right = await put(target, 'same-book', 'right');
      await expectLater(
        registry.migrateScopes(first, second),
        throwsStateError,
      );
      expect(await left.readAsString(), 'left');
      expect(await right.readAsString(), 'right');
    },
  );

  test('migration fences a download that was already in flight', () async {
    final source = registry.forScope(first);
    final started = Completer<void>();
    final release = Completer<void>();
    final download = source.write(
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
    final failed = expectLater(download, throwsStateError);
    final migration = registry.migrateScopes(first, second);
    while (await source.canRead('book-a')) {
      await Future<void>.delayed(const Duration(milliseconds: 1));
    }
    release.complete();
    await failed;
    await migration;
    expect(
      await registry
          .forScope(second)
          .lookup('book-a', 'image', extension: 'png'),
      isNull,
    );
  });
}
