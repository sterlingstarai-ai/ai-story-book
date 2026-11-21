import 'dart:io';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'user_service.dart';
import 'scoped_reading_progress.dart';
import 'share_staging.dart';

const localMediaCleanupPendingKey = 'local_media_cleanup_pending_v1';
const bookMediaCleanupPlanKey = 'book_media_cleanup_plan_v1';
const scopedBookCachePrefix = 'book_cache_scoped_v2_';

String scopedBookCacheKey(String scope, String profile, String bookId) {
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope) ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(profile) ||
      bookId.trim().isEmpty) {
    throw ArgumentError('Invalid book cache scope');
  }
  return '$scopedBookCachePrefix${scope}_${profile}_${sha256.convert(utf8.encode(bookId))}';
}

bool hasUnattributedLegacyData(
  SharedPreferences preferences, {
  required bool accountDeleted,
}) => preferences.getKeys().any(
  (key) =>
      (key.startsWith('book_cache_') &&
          !key.startsWith(scopedBookCachePrefix)) ||
      (accountDeleted &&
          ((key.startsWith('reading_progress_') &&
                  !key.startsWith(scopedReadingProgressPrefix)) ||
              key.startsWith('branch_story_progress_'))),
);

/// The file journal takes precedence only for the monotonic consent-to-account
/// transition; different target scopes are never combined or guessed.
Future<String?> reconcileBookCleanupPlan(
  SharedPreferences preferences,
  Future<String?> Function() read,
  Future<void> Function(String) write,
) async {
  final file = await read();
  final pref = preferences.getString(bookMediaCleanupPlanKey);
  Map<String, dynamic> decode(String value) {
    final parsed = jsonDecode(value);
    if (parsed is! Map<String, dynamic> ||
        parsed['scopes'] is! List ||
        parsed['metadata_keys'] is! List ||
        (parsed.containsKey('legacy_scopes') &&
            parsed['legacy_scopes'] is! List) ||
        (parsed['kind'] != null &&
            parsed['kind'] != 'consent' &&
            parsed['kind'] != 'account' &&
            parsed['kind'] != 'account_requested')) {
      throw StateError('Invalid book media cleanup plan');
    }
    return parsed;
  }

  if (file != null) decode(file);
  if (pref != null) decode(pref);
  var selected = file ?? pref;
  if (file != null && pref != null && file != pref) {
    final f = decode(file);
    final p = decode(pref);
    final sameTargets =
        jsonEncode(f['scopes']) == jsonEncode(p['scopes']) &&
        jsonEncode(f['legacy_scopes']) == jsonEncode(p['legacy_scopes']) &&
        jsonEncode(f['metadata_keys']) == jsonEncode(p['metadata_keys']);
    final advancesToAccount = f['kind'] == 'account' && p['kind'] != 'account';
    if (!sameTargets || !advancesToAccount) {
      throw StateError('Account media cleanup plans disagree');
    }
    selected = file;
  }
  if (selected != null) {
    if (file == null) await write(selected);
    if (pref != selected &&
        !await preferences.setString(bookMediaCleanupPlanKey, selected)) {
      throw StateError('Could not recover account media cleanup plan');
    }
  }
  return selected;
}

Future<void> purgeAppImageCache() async {
  PaintingBinding.instance.imageCache.clear();
  PaintingBinding.instance.imageCache.clearLiveImages();
  // The historical shared cache is not account-scoped. Never delete it while
  // entries remain because that could destroy another account's offline data.
  final temporary = await getTemporaryDirectory();
  await ensureSharedImageCacheEmpty(temporary);
}

Future<void> ensureSharedImageCacheEmpty(Directory temporary) async {
  if (await ShareStaging.legacyFiles(temporary)) {
    throw StateError('Historical shared export ownership is unresolved');
  }
  final root = await temporary.resolveSymbolicLinks();
  final directory = Directory('$root/${DefaultCacheManager.key}');
  if (await directory.exists()) {
    final resolved = await directory.resolveSymbolicLinks();
    if (resolved != '$root/${DefaultCacheManager.key}') {
      throw StateError('Image cache path escaped the app cache');
    }
    if (!await directory.list(followLinks: false).isEmpty) {
      throw StateError('Historical shared image cache ownership is unresolved');
    }
  }
}

/// Only call after the device owner confirms removal of the shared cache.
/// This may erase offline data belonging to other accounts or profiles.
Future<void> clearUnattributedLegacyData(SharedPreferences preferences) async {
  final temporary = await getTemporaryDirectory();
  await ShareStaging.legacyFiles(temporary, remove: true);
  final root = await temporary.resolveSymbolicLinks();
  final directory = Directory('$root/${DefaultCacheManager.key}');
  if (await directory.exists() &&
      await directory.resolveSymbolicLinks() !=
          '$root/${DefaultCacheManager.key}') {
    throw StateError('Image cache path escaped the app cache');
  }
  await DefaultCacheManager().emptyCache();
  if (await directory.exists()) {
    if (await directory.resolveSymbolicLinks() !=
        '$root/${DefaultCacheManager.key}') {
      throw StateError('Image cache path escaped the app cache');
    }
    await directory.delete(recursive: true);
  }
  for (final key in preferences.getKeys().toList()) {
    if ((key.startsWith('book_cache_') &&
            !key.startsWith(scopedBookCachePrefix)) ||
        (key.startsWith('reading_progress_') &&
            !key.startsWith(scopedReadingProgressPrefix)) ||
        key.startsWith('branch_story_progress_')) {
      if (!await preferences.remove(key)) {
        throw StateError('Could not clear historical data');
      }
    }
  }
}

/// A durable pending marker prevents a failed disk cleanup from being reported
/// as completed and makes the same operation retryable on the next launch.
class LocalMediaCleanup {
  LocalMediaCleanup(
    this.preferences, {
    required this.purge,
    this.onComplete,
    this.clearPlan,
    this.preparePlan,
  });
  final SharedPreferences preferences;
  final Future<void> Function() purge;
  final void Function()? onComplete;
  final Future<void> Function()? clearPlan;
  final Future<void> Function()? preparePlan;
  Future<void> _commands = Future<void>.value();

  Future<void> markPending() async {
    if (!await preferences.setBool(localMediaCleanupPendingKey, true)) {
      throw StateError('Could not persist local media cleanup');
    }
  }

  Future<void> retryPending() async {
    if (preferences.getBool(localMediaCleanupPendingKey) == true) {
      await run();
    }
  }

  Future<void> run() {
    return _enqueue(_run);
  }

  Future<void> prepareAccountDeletion() => _enqueue(() async {
    if (preferences.getBool(localMediaCleanupPendingKey) == true &&
        preferences.getBool(UserService.deletionRequestedKey) != true) {
      await _run();
    }
    await preparePlan?.call();
  });

  Future<void> _enqueue(Future<void> Function() command) {
    final operation = _commands.then((_) => command());
    _commands = operation.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return operation;
  }

  Future<void> _run() async {
    await markPending();
    await purge();
    final accountDeleted =
        preferences.getBool(UserService.deletionCommittedKey) == true;
    final planText = preferences.getString(bookMediaCleanupPlanKey);
    final plan = planText == null ? null : jsonDecode(planText);
    if (plan != null &&
        (plan is! Map<String, dynamic> ||
            plan['scopes'] is! List ||
            plan['metadata_keys'] is! List)) {
      throw StateError('Invalid book media cleanup plan');
    }
    final scopes = plan == null
        ? <String>[]
        : List<String>.from(plan['scopes'] as List);
    final metadataKeys = plan == null
        ? <String>[]
        : List<String>.from(plan['metadata_keys'] as List);
    if (scopes.any((scope) => !RegExp(r'^[0-9a-f]{64}$').hasMatch(scope)) ||
        metadataKeys.any(
          (key) =>
              !key.startsWith('book_media_scope_binding_v1_') &&
              !key.startsWith('book_media_storage_scope_v1_') &&
              !key.startsWith('book_media_profile_scope_v2_'),
        )) {
      throw StateError('Invalid book media cleanup plan');
    }
    for (final key in preferences.getKeys().toList()) {
      if (scopes.any(
            (scope) => key.startsWith('$scopedBookCachePrefix${scope}_'),
          ) ||
          (accountDeleted && scopes.any(
            (scope) => key.startsWith('$scopedReadingProgressPrefix${scope}_'),
          )) ||
          (accountDeleted &&
              (metadataKeys.contains(key) ||
                  scopes.any(
                    (scope) => key.startsWith('book_media_state_v1_${scope}_'),
                  )))) {
        if (!await preferences.remove(key)) {
          throw StateError('Could not remove offline book data');
        }
      }
    }
    // Historical cache entries have no trustworthy owner. Preserve them and
    // keep cleanup pending rather than erasing another account's data or
    // claiming the requesting account's historical data has been purged.
    if (hasUnattributedLegacyData(
      preferences,
      accountDeleted: accountDeleted,
    )) {
      throw StateError('Historical book cache ownership is unresolved');
    }
    if (!accountDeleted) {
      await clearPlan?.call();
      if (!await preferences.remove(bookMediaCleanupPlanKey)) {
        throw StateError('Could not clear book media cleanup plan');
      }
    }
    if (!await preferences.remove(localMediaCleanupPendingKey)) {
      throw StateError('Could not confirm local media cleanup');
    }
    onComplete?.call();
  }
}
