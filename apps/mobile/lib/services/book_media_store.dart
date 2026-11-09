import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'book_deletion_journal.dart';

class PendingBookDeletion {
  const PendingBookDeletion(this.bookId, this.requestId, this.profileDigest);
  final String bookId;
  final String requestId;
  final String profileDigest;
}

class BookDeletionUnconfirmed implements Exception {
  const BookDeletionUnconfirmed();
}

class BookDeletionNotStarted implements Exception {
  const BookDeletionNotStarted();
}

/// A dedicated per-book file store for the image/audio UI.
///
/// Use one scope-scoped instance on one isolate, and route *all* writers through
/// [write]. A deletion tombstone remains after cleanup so a stale screen cannot
/// recreate deleted files. The caller must also stop playback and evict its
/// decoded images. This does not identify or remove the historical shared cache.
/// The request journal is flushed before its preference mirror. Portable
/// directory fsync and actual power-loss recovery remain separate checks.
class BookMediaStore {
  BookMediaStore(
    this.preferences, {
    required this.baseDirectory,
    required this.scopeDigest,
    Future<Directory> Function()? journalDirectory,
    this.drainTimeout = const Duration(seconds: 30),
    Future<void> Function(Directory directory)? deleteDirectory,
  }) : _deleteDirectory = deleteDirectory ?? _deleteFlatDirectory,
       _journal = BookDeletionJournal(
         scopeDigest,
         baseDirectory: journalDirectory ?? baseDirectory,
       ) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scopeDigest)) {
      throw ArgumentError('A verified opaque scope digest is required');
    }
  }

  final SharedPreferences preferences;
  final Future<Directory> Function() baseDirectory;

  /// Caller-provided digest of a verified server and stable account scope.
  /// Never pass a bearer credential, and never reuse it for a different scope.
  final String scopeDigest;
  final Duration drainTimeout;
  final Future<void> Function(Directory directory) _deleteDirectory;
  final BookDeletionJournal _journal;
  static const _statePrefix = 'book_media_state_v1_';
  static const _requested = 'requested';
  static const _pending = 'purging';
  static const _deleted = 'deleted';
  static bool isBookBlocked(
    SharedPreferences preferences,
    String scope,
    String bookId,
  ) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope) || bookId.trim().isEmpty) {
      return true;
    }
    final token = sha256.convert(utf8.encode(bookId)).toString();
    return preferences.containsKey('$_statePrefix${scope}_$token');
  }

  /// V1 mixed profiles in one scope. A well-formed marker blocks only the
  /// profile recorded in the journal; malformed markers always fail closed.
  static bool isLegacyBookBlockedForProfile(
    SharedPreferences preferences,
    String scope,
    String bookId,
    String profileDigest,
  ) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope) ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(profileDigest) ||
        bookId.trim().isEmpty) {
      return true;
    }
    final token = sha256.convert(utf8.encode(bookId)).toString();
    try {
      final raw = preferences.getString('$_statePrefix${scope}_$token');
      if (raw == null) return false;
      final record = jsonDecode(raw);
      if (record is! Map<String, dynamic> ||
          record.length != 4 ||
          record['book_id'] != bookId ||
          record['request_id'] is! String ||
          !RegExp(r'^[0-9a-f]{32}$').hasMatch(record['request_id'] as String) ||
          record['profile_digest'] is! String ||
          !RegExp(
            r'^[0-9a-f]{64}$',
          ).hasMatch(record['profile_digest'] as String) ||
          !{_requested, _pending, _deleted}.contains(record['state'])) {
        return true;
      }
      return record['profile_digest'] == profileDigest;
    } catch (_) {
      return true;
    }
  }

  Future<void> _commands = Future<void>.value();
  final Map<String, int> _active = {};
  final Map<String, Completer<void>> _drained = {};
  final Map<String, Future<void>> _purges = {};
  final Map<String, int> _fileEpochs = {};
  final Map<String, Map<String, dynamic>> _records = {};
  Future<void>? _initialization;
  bool _closed = false;

  String _digest(String input) => sha256.convert(utf8.encode(input)).toString();

  String _bookToken(String bookId) {
    if (bookId.trim().isEmpty) throw ArgumentError('bookId is required');
    return _digest(bookId);
  }

  Future<T> _serialized<T>(Future<T> Function() operation) {
    final result = _commands.then((_) async {
      await initialize();
      return operation();
    });
    _commands = result.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return result;
  }

  String get _scopePrefix => '$_statePrefix${scopeDigest}_';
  String _stateKey(String token) => '$_scopePrefix$token';
  bool _blocked(String token) =>
      _records.containsKey(token) || preferences.containsKey(_stateKey(token));

  Future<bool> canRead(String bookId) async {
    await initialize();
    return _serialized(() async {
      final token = _bookToken(bookId);
      return !_closed && !_blocked(token);
    });
  }

  /// Serialize small metadata operations with deletion and shutdown. This
  /// prevents a late progress write from recreating data after a tombstone.
  Future<T?> withReadableBook<T>(
    String bookId,
    Future<T> Function() operation,
  ) => _serialized(() async {
    if (_closed || _blocked(_bookToken(bookId))) return null;
    return operation();
  });

  Map<String, dynamic> _parseRecord(String token, String raw) {
    try {
      final record = jsonDecode(raw);
      if (record is! Map<String, dynamic> ||
          record.length != 4 ||
          record['book_id'] is! String ||
          (record['book_id'] as String).trim().isEmpty ||
          _digest(record['book_id'] as String) != token ||
          record['request_id'] is! String ||
          !RegExp(r'^[0-9a-f]{32}$').hasMatch(record['request_id'] as String) ||
          record['profile_digest'] is! String ||
          !RegExp(
            r'^[0-9a-f]{64}$',
          ).hasMatch(record['profile_digest'] as String) ||
          !const {_requested, _pending, _deleted}.contains(record['state'])) {
        throw const FormatException();
      }
      return record;
    } catch (_) {
      throw StateError('Invalid book deletion marker');
    }
  }

  Map<String, dynamic>? _readRecord(String token) => _records[token];

  /// Reconcile the flushed journal with the older preference mirror. A
  /// mismatch that cannot be explained by a monotonic update fails closed.
  Future<void> initialize() {
    final current = _initialization;
    if (current != null) return current;
    final operation = _initialize();
    _initialization = operation;
    operation.then(
      (_) {},
      onError: (Object _, StackTrace __) {
        if (identical(_initialization, operation)) _initialization = null;
      },
    );
    return operation;
  }

  Future<void> _initialize() async {
    final files = await _journal.readAll();
    final tokens = <String>{...files.keys};
    for (final key in preferences.getKeys().where(
      (key) => key.startsWith(_scopePrefix),
    )) {
      final token = key.substring(_scopePrefix.length);
      if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(token)) {
        throw StateError('Invalid book deletion marker');
      }
      tokens.add(token);
    }
    const ranks = {_requested: 0, _pending: 1, _deleted: 2};
    for (final token in tokens) {
      final diskText = files[token];
      final prefText = preferences.getString(_stateKey(token));
      final disk = diskText == null ? null : _parseRecord(token, diskText);
      final pref = prefText == null ? null : _parseRecord(token, prefText);
      if (disk != null && pref != null) {
        if (disk['book_id'] != pref['book_id'] ||
            disk['request_id'] != pref['request_id'] ||
            disk['profile_digest'] != pref['profile_digest'] ||
            ranks[disk['state']]! < ranks[pref['state']]!) {
          throw StateError('Book deletion journal disagrees with preferences');
        }
      }
      final chosen = disk ?? pref;
      if (chosen == null) continue;
      final encoded = jsonEncode(chosen);
      if (disk == null) await _journal.write(token, encoded);
      _records[token] = chosen;
      if (prefText != encoded &&
          !await preferences.setString(_stateKey(token), encoded)) {
        throw StateError('Could not recover book deletion marker');
      }
    }
  }

  Future<void> _setState(
    String token,
    String bookId,
    String requestId,
    String profileDigest,
    String state,
  ) async {
    final record = <String, dynamic>{
      'book_id': bookId,
      'request_id': requestId,
      'profile_digest': profileDigest,
      'state': state,
    };
    final encoded = jsonEncode(record);
    await _journal.write(token, encoded);
    _records[token] = record;
    if (!await preferences.setString(_stateKey(token), encoded)) {
      throw StateError('Could not persist book deletion');
    }
  }

  Future<Directory> _root({required bool create}) async {
    final base = await baseDirectory();
    final basePath = await base.resolveSymbolicLinks();
    final root = Directory('$basePath/asb_book_media_v1');
    var type = await FileSystemEntity.type(root.path, followLinks: false);
    if (type == FileSystemEntityType.notFound && create) {
      await root.create();
      type = await FileSystemEntity.type(root.path, followLinks: false);
    }
    if (type != FileSystemEntityType.notFound &&
        (type != FileSystemEntityType.directory ||
            await root.resolveSymbolicLinks() != root.path)) {
      throw StateError('Book media root is not a private directory');
    }
    return root;
  }

  Future<Directory> _bookDirectory(String token, {required bool create}) async {
    final root = await _root(create: create);
    final scope = await _childDirectory(root, scopeDigest, create: create);
    return _childDirectory(scope, token, create: create);
  }

  Future<Directory> _childDirectory(
    Directory parent,
    String child, {
    required bool create,
  }) async {
    final directory = Directory('${parent.path}/$child');
    var type = await FileSystemEntity.type(directory.path, followLinks: false);
    if (type == FileSystemEntityType.notFound && create) {
      await directory.create();
      type = await FileSystemEntity.type(directory.path, followLinks: false);
    }
    if (type != FileSystemEntityType.notFound &&
        (type != FileSystemEntityType.directory ||
            await directory.resolveSymbolicLinks() != directory.path)) {
      throw StateError('Book media path is not a private directory');
    }
    return directory;
  }

  /// Writes a file into the book's private directory, or returns an existing
  /// regular file when [reuseExisting] is set. [download] must not complete
  /// until all writes to the supplied temporary file have stopped.
  Future<File> write(
    String bookId,
    String mediaIdentity, {
    required String extension,
    required Future<void> Function(File temporary) download,
    bool reuseExisting = false,
  }) async {
    if (mediaIdentity.isEmpty ||
        !RegExp(r'^[a-z0-9]{1,8}$').hasMatch(extension)) {
      throw ArgumentError('Invalid media identity or extension');
    }
    final token = _bookToken(bookId);
    final fileName = '${_digest(mediaIdentity)}.$extension';
    final fileKey = '$token/$fileName';
    final started = await _serialized<(File, int?)>(() async {
      if (_closed || _blocked(token)) {
        throw StateError('Book media is unavailable');
      }
      final directory = await _bookDirectory(token, create: true);
      if (reuseExisting) {
        final cached = File('${directory.path}/$fileName');
        if (await FileSystemEntity.type(cached.path, followLinks: false) ==
            FileSystemEntityType.file) {
          return (cached, null);
        }
      }
      final random = Random.secure();
      final nonce = List.generate(
        16,
        (_) => random.nextInt(256),
      ).map((value) => value.toRadixString(16).padLeft(2, '0')).join();
      final file = await File(
        '${directory.path}/.part-$nonce',
      ).create(exclusive: true);
      _active[token] = (_active[token] ?? 0) + 1;
      return (file, _fileEpochs[fileKey] ?? 0);
    });
    final temporary = started.$1;
    final epoch = started.$2;
    if (epoch == null) return temporary;
    try {
      await download(temporary);
      return await _serialized(() async {
        if (_closed ||
            _blocked(token) ||
            (_fileEpochs[fileKey] ?? 0) != epoch) {
          throw StateError('Book media is unavailable');
        }
        if (await FileSystemEntity.type(temporary.path, followLinks: false) !=
            FileSystemEntityType.file) {
          throw StateError('Book media download is not a regular file');
        }
        final directory = await _bookDirectory(token, create: false);
        final target = '${directory.path}/$fileName';
        return temporary.rename(target);
      });
    } finally {
      // A cleanup failure is surfaced; the deletion marker remains in place.
      try {
        if (await FileSystemEntity.type(temporary.path, followLinks: false) !=
            FileSystemEntityType.notFound) {
          await temporary.delete();
        }
      } finally {
        await _serialized(() async {
          final remaining = (_active[token] ?? 1) - 1;
          if (remaining == 0) {
            _active.remove(token);
            _drained.remove(token)?.complete();
          } else {
            _active[token] = remaining;
          }
        });
      }
    }
  }

  /// Returns only a currently tracked, non-deleted regular file.
  Future<File?> lookup(
    String bookId,
    String mediaIdentity, {
    required String extension,
  }) async {
    if (mediaIdentity.isEmpty ||
        !RegExp(r'^[a-z0-9]{1,8}$').hasMatch(extension)) {
      throw ArgumentError('Invalid media identity or extension');
    }
    final token = _bookToken(bookId);
    return _serialized(() async {
      if (_closed || _blocked(token)) return null;
      final directory = await _bookDirectory(token, create: false);
      final file = File(
        '${directory.path}/${_digest(mediaIdentity)}.$extension',
      );
      return await FileSystemEntity.type(file.path, followLinks: false) ==
              FileSystemEntityType.file
          ? file
          : null;
    });
  }

  /// Invalidate in-flight writers for this file before unlinking it.
  Future<void> remove(
    String bookId,
    String mediaIdentity, {
    required String extension,
  }) {
    if (mediaIdentity.isEmpty ||
        !RegExp(r'^[a-z0-9]{1,8}$').hasMatch(extension)) {
      throw ArgumentError('Invalid media identity or extension');
    }
    final token = _bookToken(bookId);
    final fileKey = '$token/${_digest(mediaIdentity)}.$extension';
    return _serialized(() async {
      if (_closed) throw StateError('Book media store is closed');
      _fileEpochs[fileKey] = (_fileEpochs[fileKey] ?? 0) + 1;
      final directory = await _bookDirectory(token, create: false);
      final path = '${directory.path}/${_digest(mediaIdentity)}.$extension';
      final type = await FileSystemEntity.type(path, followLinks: false);
      if (type == FileSystemEntityType.file) {
        await File(path).delete();
      } else if (type == FileSystemEntityType.link) {
        await Link(path).delete();
      } else if (type != FileSystemEntityType.notFound) {
        throw StateError('Unexpected book media entry');
      }
    });
  }

  /// Stop accepting writes and wait for already-started writers to drain.
  Future<void> shutdown() async {
    final waiting = await _serialized(() async {
      _closed = true;
      return (
        _active.keys
            .map((token) => _drained.putIfAbsent(token, Completer<void>.new))
            .toList(),
        _purges.values.toList(),
      );
    });
    await Future.wait([
      ...waiting.$1.map((drain) => drain.future),
      ...waiting.$2,
    ]).timeout(drainTimeout);
  }

  /// Record the intention *before* the server request; block new writes.
  Future<String> beginDeletion(
    String bookId, {
    required String profileDigest,
  }) => _serialized(() async {
    if (_closed) throw StateError('Book media store is closed');
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(profileDigest)) {
      throw ArgumentError('A verified opaque profile digest is required');
    }
    final token = _bookToken(bookId);
    final record = _readRecord(token);
    if (record != null) {
      if (record['state'] != _requested ||
          record['profile_digest'] != profileDigest) {
        throw StateError('Book deletion is already in progress');
      }
      return record['request_id'] as String;
    }
    final random = Random.secure();
    final requestId = List.generate(
      16,
      (_) => random.nextInt(256),
    ).map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    await _setState(token, bookId, requestId, profileDigest, _requested);
    return requestId;
  });

  /// Only call after verifying a committed deletion for this exact scope.
  /// A timeout, 403 or ambiguous 404 is not proof of deletion.
  Future<void> confirmDeletion(
    String bookId,
    String requestId, {
    required String profileDigest,
  }) => _serialized(() async {
    if (_closed) throw StateError('Book media store is closed');
    final token = _bookToken(bookId);
    final record = _readRecord(token);
    if (record?['request_id'] != requestId ||
        record?['profile_digest'] != profileDigest) {
      throw StateError('Book deletion request does not match');
    }
    final state = record?['state'];
    if (state == _requested) {
      await _setState(token, bookId, requestId, profileDigest, _pending);
    } else if (state != _pending && state != _deleted) {
      throw StateError('Book deletion has not been requested');
    }
  });

  /// Only call after a definitive rejection in the same verified scope.
  Future<void> rejectDeletion(
    String bookId,
    String requestId, {
    required String profileDigest,
  }) => _serialized(() async {
    if (_closed) throw StateError('Book media store is closed');
    final token = _bookToken(bookId);
    final record = _readRecord(token);
    if (record?['state'] != _requested ||
        record?['request_id'] != requestId ||
        record?['profile_digest'] != profileDigest) {
      throw StateError('Only an unconfirmed request can be rejected');
    }
    await _journal.remove(token);
    if (!await preferences.remove(_stateKey(token))) {
      throw StateError('Could not clear book deletion request');
    }
    _records.remove(token);
  });

  Future<List<PendingBookDeletion>> _requestsWithStates(Set<String> states) =>
      _serialized(() async {
        return _records.values
            .where((record) => states.contains(record['state']))
            .map(
              (record) => PendingBookDeletion(
                record['book_id'] as String,
                record['request_id'] as String,
                record['profile_digest'] as String,
              ),
            )
            .toList();
      });

  /// Requests requiring server reconciliation, limited to this exact scope.
  Future<List<PendingBookDeletion>> pendingRequests() =>
      _requestsWithStates({_requested});

  /// Confirmed deletions also drive cleanup of per-book text/progress after a crash.
  Future<List<PendingBookDeletion>> confirmedDeletions() =>
      _requestsWithStates({_pending, _deleted});

  /// Both an unconfirmed request and an unfinished local purge need attention.
  Future<List<PendingBookDeletion>> unfinishedDeletions() =>
      _requestsWithStates({_requested, _pending});

  /// Migration is allowed only after this scope has stopped every writer.
  Future<Map<String, String>> exportStoppedRecords() => _serialized(() async {
    if (!_closed) throw StateError('Book media store must be stopped');
    return {
      for (final entry in _records.entries) entry.key: jsonEncode(entry.value),
    };
  });

  Future<void> importStoppedRecords(Map<String, String> records) =>
      _serialized(() async {
        if (!_closed) throw StateError('Book media store must be stopped');
        final incoming = <String, Map<String, dynamic>>{};
        for (final entry in records.entries) {
          if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(entry.key)) {
            throw StateError('Invalid book deletion marker');
          }
          final record = _parseRecord(entry.key, entry.value);
          final existing = _records[entry.key];
          if (existing != null && jsonEncode(existing) != jsonEncode(record)) {
            throw StateError('Book deletion records require reconciliation');
          }
          incoming[entry.key] = record;
        }
        for (final entry in incoming.entries) {
          if (_records.containsKey(entry.key)) continue;
          final record = entry.value;
          await _setState(
            entry.key,
            record['book_id'] as String,
            record['request_id'] as String,
            record['profile_digest'] as String,
            record['state'] as String,
          );
        }
      });

  Future<void> removeStoppedRecords() => _serialized(() async {
    if (!_closed) throw StateError('Book media store must be stopped');
    await _journal.purgeScope();
    for (final key
        in preferences
            .getKeys()
            .where((key) => key.startsWith(_scopePrefix))
            .toList()) {
      if (!await preferences.remove(key)) {
        throw StateError('Could not remove migrated book marker');
      }
    }
    _records.clear();
  });

  /// Keep the deletion tombstone after the directory has been removed.
  Future<void> purgeBook(String bookId) async {
    final token = _bookToken(bookId);
    final operation = await _serialized(() async {
      if (_closed) throw StateError('Book media store is closed');
      final state = _readRecord(token)?['state'];
      if (state != _pending && state != _deleted) {
        throw StateError('Book deletion is not confirmed');
      }
      return (_purgeToken(token),);
    });
    await operation.$1;
  }

  Future<void> _purgeToken(String token) {
    final existing = _purges[token];
    if (existing != null) return existing;
    final result = _finishPurge(token);
    _purges[token] = result;
    result.then(
      (_) => _purges.remove(token),
      onError: (Object _, StackTrace __) {
        _purges.remove(token);
      },
    );
    return result;
  }

  Future<void> _finishPurge(String token) async {
    final drain = await _serialized<Completer<void>?>(() async {
      final state = _readRecord(token)?['state'];
      if (state != _pending && state != _deleted) {
        throw StateError('Book deletion is not confirmed');
      }
      if ((_active[token] ?? 0) == 0) return null;
      return _drained.putIfAbsent(token, Completer<void>.new);
    });

    if (drain != null) await drain.future.timeout(drainTimeout);
    final directory = await _bookDirectory(token, create: false);
    if (await FileSystemEntity.type(directory.path, followLinks: false) !=
        FileSystemEntityType.notFound) {
      await _deleteDirectory(directory);
      if (await FileSystemEntity.type(directory.path, followLinks: false) !=
          FileSystemEntityType.notFound) {
        throw StateError('Book media directory remains');
      }
    }
    await _serialized(() async {
      if ((_active[token] ?? 0) != 0) {
        throw StateError('Book download is active');
      }
      final record = _readRecord(token);
      if (record == null) throw StateError('Book deletion marker is missing');
      await _setState(
        token,
        record['book_id'] as String,
        record['request_id'] as String,
        record['profile_digest'] as String,
        _deleted,
      );
    });
  }

  /// Call on app startup before permitting any media writes.
  Future<void> retryPending() async {
    final pending = await _requestsWithStates({_pending});
    for (final request in pending) {
      await purgeBook(request.bookId);
    }
  }

  static Future<void> _deleteFlatDirectory(Directory directory) async {
    await for (final item in directory.list(followLinks: false)) {
      final type = await FileSystemEntity.type(item.path, followLinks: false);
      if (type == FileSystemEntityType.file) {
        await File(item.path).delete();
      } else if (type == FileSystemEntityType.link) {
        await Link(item.path).delete();
      } else {
        throw StateError('Unexpected entry in book media directory');
      }
    }
    await directory.delete();
  }
}
