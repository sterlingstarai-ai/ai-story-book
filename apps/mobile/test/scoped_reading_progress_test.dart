import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/scoped_reading_progress.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late Directory temp;
  late SharedPreferences prefs;
  const first =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  const second =
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
  const third =
      'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'reading_progress_same_v1': 9,
      'branch_story_progress_same_v1': 'legacy',
    });
    prefs = await SharedPreferences.getInstance();
    temp = await Directory.systemTemp.createTemp('asb-progress-');
  });
  tearDown(() async {
    await temp.delete(recursive: true);
  });
  BookMediaStore store(String scope) => BookMediaStore(
    prefs,
    scopeDigest: scope,
    baseDirectory: () async => temp,
    journalDirectory: () async => temp,
  );

  test(
    'offline same book IDs stay isolated across accounts and profiles',
    () async {
      final a = ScopedReadingProgress(prefs, store(first), 'same', () => true);
      final b = ScopedReadingProgress(prefs, store(second), 'same', () => true);
      final c = ScopedReadingProgress(prefs, store(third), 'same', () => true);
      expect(await a.page(), isNull);
      await a.savePage(3);
      await a.saveAudio('voice-a');
      await a.saveBranch('branch-a');
      await b.savePage(5);
      await c.saveBranch('branch-c');
      expect(await a.page(), 3);
      expect(await a.audio(), 'voice-a');
      expect(await b.page(), 5);
      expect(await b.audio(), isNull);
      expect(await c.branch(), 'branch-c');
      expect(prefs.getInt('reading_progress_same_v1'), 9);
      expect(prefs.getString('branch_story_progress_same_v1'), 'legacy');
    },
  );

  test(
    'deletion serializes queued writes and restart retains tombstone',
    () async {
      final owner = store(first);
      final progress = ScopedReadingProgress(prefs, owner, 'same', () => true);
      final other = ScopedReadingProgress(
        prefs,
        store(second),
        'same',
        () => true,
      );
      await progress.savePage(3);
      await other.savePage(7);
      final hold = Completer<void>();
      final entered = Completer<void>();
      final pending = owner.withReadableBook('same', () async {
        entered.complete();
        await hold.future;
        return true;
      });
      await entered.future;
      final deletion = owner.beginDeletion('same', profileDigest: third);
      final lateWrite = progress.savePage(8);
      hold.complete();
      await pending;
      final request = await deletion;
      await lateWrite;
      expect(prefs.getInt(progress.key('page')), 3);
      await owner.confirmDeletion('same', request, profileDigest: third);
      final restarted = store(first);
      expect((await restarted.confirmedDeletions()).single.bookId, 'same');
      await clearScopedBookProgress(prefs, first, 'same');
      expect(prefs.containsKey(progress.key('page')), isFalse);
      expect(await other.page(), 7);
      await ScopedReadingProgress(
        prefs,
        restarted,
        'same',
        () => true,
      ).savePage(4);
      expect(prefs.containsKey(progress.key('page')), isFalse);
      expect(prefs.getInt('reading_progress_same_v1'), 9);
    },
  );

  test(
    'account cleanup is scoped and retries while preserving legacy',
    () async {
      final a = ScopedReadingProgress(prefs, store(first), 'same', () => true);
      final b = ScopedReadingProgress(prefs, store(second), 'same', () => true);
      await a.savePage(1);
      await b.savePage(2);
      await prefs.setBool(UserService.deletionCommittedKey, true);
      await prefs.setString(
        bookMediaCleanupPlanKey,
        jsonEncode({
          'scopes': [first],
          'metadata_keys': [],
        }),
      );
      final cleanup = LocalMediaCleanup(prefs, purge: () async {});
      await expectLater(cleanup.run(), throwsStateError);
      expect(prefs.containsKey(a.key('page')), isFalse);
      expect(await b.page(), 2);
      expect(prefs.getInt('reading_progress_same_v1'), 9);
      await expectLater(cleanup.retryPending(), throwsStateError);
      expect(await b.page(), 2);
    },
  );

  test('invalidated profile cannot save into its old scope', () async {
    var active = true;
    final progress = ScopedReadingProgress(
      prefs,
      store(first),
      'same',
      () => active,
    );
    await progress.savePage(2);
    active = false;
    await progress.savePage(8);
    expect(prefs.getInt(progress.key('page')), 2);
    expect(await progress.page(), isNull);
  });
}
