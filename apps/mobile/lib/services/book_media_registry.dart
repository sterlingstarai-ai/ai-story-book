import 'dart:io';

import 'package:shared_preferences/shared_preferences.dart';

import 'book_media_store.dart';
import 'book_deletion_journal.dart';

/// One registry per app session: every scoped downloader shares its barriers.
class BookMediaRegistry {
  BookMediaRegistry(
    this.preferences, {
    required this.baseDirectory,
    this.journalDirectory,
  });
  final SharedPreferences preferences;
  final Future<Directory> Function() baseDirectory;
  final Future<Directory> Function()? journalDirectory;
  final Map<String, BookMediaStore> _stores = {};
  final Set<String> _purgingScopes = {};
  final Set<String> _migrationScopes = {};
  bool _closed = false;
  Future<void>? _closing;
  Future<void> _maintenance = Future<void>.value();

  Future<T> _exclusive<T>(Future<T> Function() operation) {
    final result = _maintenance.then((_) => operation());
    _maintenance = result.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return result;
  }

  /// Serialize profile registration against cleanup inventory checks.
  Future<T> guardProfileRegistration<T>(Future<T> Function() operation) =>
      _exclusive(operation);

  BookMediaStore forScope(String scope) {
    if (_closed ||
        _purgingScopes.contains(scope) ||
        _migrationScopes.contains(scope)) {
      throw StateError('Book media registry is unavailable');
    }
    return _stores.putIfAbsent(
      scope,
      () => BookMediaStore(
        preferences,
        baseDirectory: baseDirectory,
        journalDirectory: journalDirectory,
        scopeDigest: scope,
      ),
    );
  }

  /// An unmerged local area must never be silently abandoned on recovery.
  Future<bool> hasScopeData(String scope) async {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope)) {
      throw ArgumentError('Invalid scope');
    }
    if (preferences.getKeys().any(
      (key) => key.startsWith('book_media_state_v1_${scope}_'),
    )) {
      return true;
    }
    if ((await BookDeletionJournal(
      scope,
      baseDirectory: journalDirectory ?? baseDirectory,
    ).readAll()).isNotEmpty) {
      return true;
    }
    final base = await baseDirectory();
    final path =
        '${await base.resolveSymbolicLinks()}/asb_book_media_v1/$scope';
    return await FileSystemEntity.type(path, followLinks: false) !=
        FileSystemEntityType.notFound;
  }

  /// Caller must first verify that both local scopes belong to the same server
  /// account. Conflicts are never overwritten; interrupted moves are retryable.
  Future<void> migrateScopes(String source, String destination) =>
      _exclusive(() => _migrateScopes(source, destination));

  Future<void> _migrateScopes(String source, String destination) async {
    if (source == destination) return;
    if (![
      source,
      destination,
    ].every((scope) => RegExp(r'^[0-9a-f]{64}$').hasMatch(scope))) {
      throw ArgumentError('Invalid media scope');
    }
    final from = forScope(source);
    final to = forScope(destination);
    _migrationScopes.addAll({source, destination});
    var writersDrained = false;
    try {
      await Future.wait([from.shutdown(), to.shutdown()]);
      writersDrained = true;
      final sourceRecords = await from.exportStoppedRecords();
      final destinationRecords = await to.exportStoppedRecords();
      for (final entry in sourceRecords.entries) {
        if (destinationRecords.containsKey(entry.key) &&
            destinationRecords[entry.key] != entry.value) {
          throw StateError('Book deletion records require reconciliation');
        }
      }
      final base = await baseDirectory();
      final rootPath = '${await base.resolveSymbolicLinks()}/asb_book_media_v1';
      final root = Directory(rootPath);
      var rootType = await FileSystemEntity.type(rootPath, followLinks: false);
      if (rootType == FileSystemEntityType.notFound) {
        await root.create();
        rootType = await FileSystemEntity.type(rootPath, followLinks: false);
      }
      if (rootType != FileSystemEntityType.directory ||
          await root.resolveSymbolicLinks() != rootPath) {
        throw StateError('Book media root is not private');
      }
      Future<Directory> checkedScope(
        String scope, {
        required bool create,
      }) async {
        final dir = Directory('$rootPath/$scope');
        var type = await FileSystemEntity.type(dir.path, followLinks: false);
        if (type == FileSystemEntityType.notFound && create) {
          await dir.create();
          type = await FileSystemEntity.type(dir.path, followLinks: false);
        }
        if (type != FileSystemEntityType.notFound &&
            (type != FileSystemEntityType.directory ||
                await dir.resolveSymbolicLinks() != dir.path)) {
          throw StateError('Book media scope is not private');
        }
        return dir;
      }

      final sourceDir = await checkedScope(source, create: false);
      final targetDir = await checkedScope(destination, create: true);
      final moves = <(Directory, String)>[];
      if (await FileSystemEntity.type(sourceDir.path, followLinks: false) !=
          FileSystemEntityType.notFound) {
        await for (final entry in sourceDir.list(followLinks: false)) {
          final name = entry.uri.pathSegments
              .where((part) => part.isNotEmpty)
              .last;
          if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(name) ||
              await FileSystemEntity.type(entry.path, followLinks: false) !=
                  FileSystemEntityType.directory ||
              await Directory(entry.path).resolveSymbolicLinks() !=
                  entry.path ||
              await FileSystemEntity.type(
                    '${targetDir.path}/$name',
                    followLinks: false,
                  ) !=
                  FileSystemEntityType.notFound) {
            throw StateError('Book media files require reconciliation');
          }
          moves.add((Directory(entry.path), name));
        }
      }
      // Copy journal evidence first. A crash before a move leaves both source
      // and destination evidence, so the next attempt remains conservative.
      await to.importStoppedRecords(sourceRecords);
      for (final move in moves) {
        final target = '${targetDir.path}/${move.$2}';
        if (await FileSystemEntity.type(target, followLinks: false) !=
            FileSystemEntityType.notFound) {
          throw StateError('Book media files require reconciliation');
        }
        await move.$1.rename(target);
      }
      await from.removeStoppedRecords();
      if (await FileSystemEntity.type(sourceDir.path, followLinks: false) !=
          FileSystemEntityType.notFound) {
        await sourceDir.delete();
      }
    } finally {
      if (writersDrained) {
        _stores.remove(source);
        _stores.remove(destination);
        _migrationScopes.remove(source);
        _migrationScopes.remove(destination);
      }
    }
  }

  Future<void> close() {
    final current = _closing;
    if (current != null) return current;
    _closed = true;
    final operation = _exclusive(_close);
    _closing = operation;
    operation.then(
      (_) {},
      onError: (Object _, StackTrace __) {
        if (identical(_closing, operation)) _closing = null;
      },
    );
    return operation;
  }

  Future<void> _close() async {
    _closed = true;
    await Future.wait(_stores.values.map((store) => store.shutdown()));
  }

  /// Only verified scopes belonging to the current account may be removed.
  /// Unknown and other accounts' areas must remain untouched.
  Future<void> purgeScopes(Set<String> scopes, {bool eraseJournal = false}) =>
      _exclusive(() => _purgeScopes(scopes, eraseJournal: eraseJournal));

  Future<void> _purgeScopes(
    Set<String> scopes, {
    required bool eraseJournal,
  }) async {
    if (scopes.any((scope) => !RegExp(r'^[0-9a-f]{64}$').hasMatch(scope))) {
      throw ArgumentError('Invalid media scope');
    }
    _purgingScopes.addAll(scopes);
    await Future.wait(
      scopes
          .where(_stores.containsKey)
          .map((scope) => _stores[scope]!.shutdown()),
    );
    final base = await baseDirectory();
    final root = '${await base.resolveSymbolicLinks()}/asb_book_media_v1';
    final type = await FileSystemEntity.type(root, followLinks: false);
    if (type != FileSystemEntityType.notFound &&
        (type != FileSystemEntityType.directory ||
            await Directory(root).resolveSymbolicLinks() != root)) {
      throw StateError('Book media root is not a private directory');
    }
    for (final scope in scopes) {
      final path = '$root/$scope';
      final scopeType = await FileSystemEntity.type(path, followLinks: false);
      if (scopeType == FileSystemEntityType.notFound) continue;
      if (scopeType != FileSystemEntityType.directory ||
          await Directory(path).resolveSymbolicLinks() != path) {
        throw StateError('Book media scope is not a private directory');
      }
      await Directory(path).delete(recursive: true);
      if (await FileSystemEntity.type(path, followLinks: false) !=
          FileSystemEntityType.notFound) {
        throw StateError('Book media cleanup is incomplete');
      }
    }
    if (eraseJournal) {
      for (final scope in scopes) {
        await BookDeletionJournal(
          scope,
          baseDirectory: journalDirectory ?? baseDirectory,
        ).purgeScope();
      }
    }
  }

  /// Call only after the cleanup marker has been cleared successfully.
  void releasePurgedScopes() {
    for (final scope in _purgingScopes) {
      _stores.remove(scope);
    }
    _purgingScopes.clear();
  }
}
