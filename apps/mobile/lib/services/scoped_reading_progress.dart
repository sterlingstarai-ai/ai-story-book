import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'book_media_store.dart';

const scopedReadingProgressPrefix = 'reading_progress_scoped_v2_';

String scopedReadingProgressKey(String scope, String bookId, String kind) {
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope) ||
      bookId.trim().isEmpty ||
      !const {'page', 'audio', 'branch'}.contains(kind)) {
    throw ArgumentError('Invalid reading progress scope');
  }
  final book = sha256.convert(utf8.encode(bookId));
  return '$scopedReadingProgressPrefix${scope}_${kind}_$book';
}

/// Progress shares the verified local account/profile scope and deletion lock
/// with book media. Unattributed v1 data is intentionally never read here.
class ScopedReadingProgress {
  ScopedReadingProgress(
    this.preferences,
    this.store,
    this.bookId,
    this.isCurrent,
  );

  final SharedPreferences preferences;
  final BookMediaStore store;
  final String bookId;
  final bool Function() isCurrent;

  String key(String kind) =>
      scopedReadingProgressKey(store.scopeDigest, bookId, kind);

  Future<T?> _perform<T>(Future<T?> Function() action) async {
    return store.withReadableBook<T?>(bookId, () async {
      if (!isCurrent()) return null;
      return action();
    });
  }

  Future<int?> page() => _perform(() async => preferences.getInt(key('page')));
  Future<String?> audio() =>
      _perform(() async => preferences.getString(key('audio')));
  Future<String?> branch() =>
      _perform(() async => preferences.getString(key('branch')));

  Future<void> savePage(int page) async {
    await _perform(() async => preferences.setInt(key('page'), page));
  }

  Future<void> saveAudio(String value) async {
    await _perform(() async => preferences.setString(key('audio'), value));
  }

  Future<void> saveBranch(String value) async {
    await _perform(() async => preferences.setString(key('branch'), value));
  }

  Future<void> clearPage() async {
    await _perform(() async => preferences.remove(key('page')));
  }

  Future<void> clearBranch() async {
    await _perform(() async => preferences.remove(key('branch')));
  }

  Future<void> clearReading() async {
    await _perform(() async {
      await preferences.remove(key('page'));
      await preferences.remove(key('audio'));
      return true;
    });
  }
}

/// Invoke only after a scoped server deletion receipt is confirmed.
Future<void> clearScopedBookProgress(
  SharedPreferences prefs,
  String scope,
  String bookId,
) async {
  for (final kind in ['page', 'audio', 'branch']) {
    if (!await prefs.remove(scopedReadingProgressKey(scope, bookId, kind))) {
      throw StateError('Could not clear deleted reading progress');
    }
  }
}
