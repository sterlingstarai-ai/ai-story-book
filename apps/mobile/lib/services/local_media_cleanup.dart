import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';

const localMediaCleanupPendingKey = 'local_media_cleanup_pending_v1';

Future<void> purgeAppImageCache() async {
  PaintingBinding.instance.imageCache.clear();
  PaintingBinding.instance.imageCache.clearLiveImages();
  await DefaultCacheManager().emptyCache();
  // Also remove physical entries, including orphaned files whose cache metadata
  // was lost. Restrict deletion to this app's known image-cache directory.
  final temporary = await getTemporaryDirectory();
  final root = await temporary.resolveSymbolicLinks();
  final directory = Directory('$root/${DefaultCacheManager.key}');
  if (await directory.exists()) {
    final resolved = await directory.resolveSymbolicLinks();
    if (resolved != '$root/${DefaultCacheManager.key}') {
      throw StateError('Image cache path escaped the app cache');
    }
    await directory.delete(recursive: true);
  }
}

/// A durable pending marker prevents a failed disk cleanup from being reported
/// as completed and makes the same operation retryable on the next launch.
class LocalMediaCleanup {
  LocalMediaCleanup(this.preferences, {required this.purge});
  final SharedPreferences preferences;
  final Future<void> Function() purge;

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

  Future<void> run() async {
    await markPending();
    await purge();
    for (final key in preferences.getKeys().toList()) {
      if (key.startsWith('book_cache_') ||
          key.startsWith('reading_progress_')) {
        if (!await preferences.remove(key)) {
          throw StateError('Could not remove offline book data');
        }
      }
    }
    if (!await preferences.remove(localMediaCleanupPendingKey)) {
      throw StateError('Could not confirm local media cleanup');
    }
  }
}
