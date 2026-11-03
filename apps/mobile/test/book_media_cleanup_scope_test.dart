import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/book_cleanup_plan_journal.dart';
import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _BootUser extends UserService {
  _BootUser(super.preferences);
  bool resumed = false;
  @override
  String getUserKey() {
    if (!resumed) throw const UserKeyUnavailable();
    return 'old-credential';
  }

  @override
  Future<void> resumeKeyForDeletion() async {
    resumed = true;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'restart loads old credential and cleans only that account scope',
    () async {
      SharedPreferences.setMockInitialValues({
        UserService.deletionCommittedKey: true,
      });
      final prefs = await SharedPreferences.getInstance();
      final dir = await Directory.systemTemp.createTemp('asb-account-cleanup-');
      addTearDown(() => dir.delete(recursive: true));
      const base = 'https://synthetic.example';
      final scope = sha256
          .convert(
            utf8.encode(
              'asb:local-media-scope:v1\u0000$base\u0000old-credential',
            ),
          )
          .toString();
      const other =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      const profile =
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
      final registry = BookMediaRegistry(prefs, baseDirectory: () async => dir);
      final old = registry.forScope(scope);
      final another = registry.forScope(other);
      final oldFile = await old.write(
        'old-book',
        'image',
        extension: 'png',
        download: (file) async {
          await file.writeAsString('old');
        },
      );
      final otherFile = await another.write(
        'other-book',
        'image',
        extension: 'png',
        download: (file) async {
          await file.writeAsString('other');
        },
      );
      final otherRequest = await another.beginDeletion(
        'other-book',
        profileDigest: profile,
      );
      final user = _BootUser(prefs);
      final plan = BookCleanupPlanJournal(baseDirectory: () async => dir);
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(user),
          apiBaseUrlProvider.overrideWithValue(base),
          bookMediaRegistryProvider.overrideWithValue(registry),
          bookCleanupPlanJournalProvider.overrideWithValue(plan),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
        ],
      );
      addTearDown(container.dispose);
      await expectLater(container.read(localMediaCleanupProvider).run(), throwsStateError);
      expect(user.resumed, isTrue);
      expect(await oldFile.readAsString(), 'old');
      await container.read(clearLegacyAccountMediaProvider)();
      await container.read(localMediaCleanupProvider).retryPending();
      expect(await oldFile.exists(), isFalse);
      expect(await otherFile.readAsString(), 'other');
      expect((await another.pendingRequests()).single.requestId, otherRequest);
      expect(prefs.getString(bookMediaCleanupPlanKey), isNotNull);
      expect(await plan.read(), isNotNull);
    },
  );

  test(
    'flushed cleanup plan resumes without guessing after the credential changes',
    () async {
      SharedPreferences.setMockInitialValues({
        UserService.deletionCommittedKey: true,
      });
      final prefs = await SharedPreferences.getInstance();
      final dir = await Directory.systemTemp.createTemp('asb-account-plan-');
      addTearDown(() => dir.delete(recursive: true));
      const oldScope =
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
      const otherScope =
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
      final registry = BookMediaRegistry(prefs, baseDirectory: () async => dir);
      final oldFile = await registry
          .forScope(oldScope)
          .write(
            'old-book',
            'image',
            extension: 'png',
            download: (file) async {
              await file.writeAsString('old');
            },
          );
      final otherFile = await registry
          .forScope(otherScope)
          .write(
            'other-book',
            'image',
            extension: 'png',
            download: (file) async {
              await file.writeAsString('other');
            },
          );
      final plan = BookCleanupPlanJournal(baseDirectory: () async => dir);
      await plan.write(
        jsonEncode({
          'scopes': [oldScope],
          'metadata_keys': <String>[],
        }),
      );
      final user = _BootUser(prefs);
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(user),
          bookMediaRegistryProvider.overrideWithValue(registry),
          bookCleanupPlanJournalProvider.overrideWithValue(plan),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
        ],
      );
      addTearDown(container.dispose);
      await expectLater(container.read(localMediaCleanupProvider).run(), throwsStateError);
      expect(user.resumed, isFalse);
      expect(await oldFile.exists(), isTrue);
      expect(await otherFile.exists(), isTrue);
      expect(prefs.getString(bookMediaCleanupPlanKey), isNotNull);
    },
  );
}
