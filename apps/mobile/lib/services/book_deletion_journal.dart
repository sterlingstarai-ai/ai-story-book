import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// App-private, per-scope request journal. File contents are flushed before an
/// atomic same-directory rename. Dart does not expose a portable directory
/// fsync, so sudden power-loss durability still requires device verification.
class BookDeletionJournal {
  BookDeletionJournal(this.scope, {required this.baseDirectory}) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(scope)) {
      throw ArgumentError('Invalid scope');
    }
  }
  final String scope;
  final Future<Directory> Function() baseDirectory;

  Future<Directory> _scopeDirectory({required bool create}) async {
    final base = await baseDirectory();
    final rootPath =
        '${await base.resolveSymbolicLinks()}/asb_book_deletion_journal_v1';
    final root = Directory(rootPath);
    Future<Directory> child(Directory directory) async {
      var type = await FileSystemEntity.type(
        directory.path,
        followLinks: false,
      );
      if (type == FileSystemEntityType.notFound && create) {
        await directory.create();
        type = await FileSystemEntity.type(directory.path, followLinks: false);
      }
      if (type != FileSystemEntityType.notFound &&
          (type != FileSystemEntityType.directory ||
              await directory.resolveSymbolicLinks() != directory.path)) {
        throw StateError('Deletion journal path is not private');
      }
      return directory;
    }

    await child(root);
    return child(Directory('$rootPath/$scope'));
  }

  void _validateToken(String token) {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(token)) {
      throw ArgumentError('Invalid book token');
    }
  }

  Future<Map<String, String>> readAll() async {
    final directory = await _scopeDirectory(create: false);
    if (await FileSystemEntity.type(directory.path, followLinks: false) ==
        FileSystemEntityType.notFound) {
      return {};
    }
    final records = <String, String>{};
    await for (final entry in directory.list(followLinks: false)) {
      final name = entry.uri.pathSegments.where((part) => part.isNotEmpty).last;
      if (name.startsWith('.tmp-')) continue;
      if (!RegExp(r'^[0-9a-f]{64}\.json$').hasMatch(name) ||
          await FileSystemEntity.type(entry.path, followLinks: false) !=
              FileSystemEntityType.file) {
        throw StateError('Invalid deletion journal entry');
      }
      final file = File(entry.path);
      if (await file.length() > 4096) {
        throw StateError('Deletion journal entry is too large');
      }
      final content = await file.readAsString();
      records[name.substring(0, 64)] = content;
    }
    return records;
  }

  Future<void> write(String token, String content) async {
    _validateToken(token);
    if (utf8.encode(content).length > 4096) {
      throw StateError('Deletion journal entry is too large');
    }
    final directory = await _scopeDirectory(create: true);
    final target = File('${directory.path}/$token.json');
    final existing = await FileSystemEntity.type(
      target.path,
      followLinks: false,
    );
    if (existing != FileSystemEntityType.notFound &&
        existing != FileSystemEntityType.file) {
      throw StateError('Deletion journal entry is not a regular file');
    }
    final random = Random.secure();
    final nonce = List.generate(
      16,
      (_) => random.nextInt(256),
    ).map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    final temp = await File(
      '${directory.path}/.tmp-$nonce',
    ).create(exclusive: true);
    try {
      final handle = await temp.open(mode: FileMode.write);
      try {
        await handle.writeString(content);
        await handle.flush();
      } finally {
        await handle.close();
      }
      await temp.rename(target.path);
    } finally {
      if (await FileSystemEntity.type(temp.path, followLinks: false) !=
          FileSystemEntityType.notFound) {
        await temp.delete();
      }
    }
  }

  Future<void> remove(String token) async {
    _validateToken(token);
    final directory = await _scopeDirectory(create: false);
    final file = File('${directory.path}/$token.json');
    final type = await FileSystemEntity.type(file.path, followLinks: false);
    if (type == FileSystemEntityType.notFound) return;
    if (type != FileSystemEntityType.file) {
      throw StateError('Deletion journal entry is not a regular file');
    }
    await file.delete();
  }

  Future<void> purgeScope() async {
    final directory = await _scopeDirectory(create: false);
    if (await FileSystemEntity.type(directory.path, followLinks: false) ==
        FileSystemEntityType.notFound) {
      return;
    }
    await for (final entry in directory.list(followLinks: false)) {
      final type = await FileSystemEntity.type(entry.path, followLinks: false);
      if (type == FileSystemEntityType.file) {
        await File(entry.path).delete();
      } else if (type == FileSystemEntityType.link) {
        await Link(entry.path).delete();
      } else {
        throw StateError('Unexpected deletion journal entry');
      }
    }
    await directory.delete();
  }
}
