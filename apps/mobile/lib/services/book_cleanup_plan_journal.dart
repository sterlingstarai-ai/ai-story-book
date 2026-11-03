import 'dart:io';
import 'dart:math';
import 'dart:convert';

/// Flushes the account-scoped cleanup plan before a destructive operation.
/// Atomic rename protects process interruption; portable directory fsync is not
/// available in Dart, so sudden power-loss guarantees remain unverified.
class BookCleanupPlanJournal {
  BookCleanupPlanJournal({required this.baseDirectory});
  final Future<Directory> Function() baseDirectory;

  Future<Directory> _directory({required bool create}) async {
    final base = await baseDirectory();
    final dir = Directory(
      '${await base.resolveSymbolicLinks()}/asb_book_cleanup_v1',
    );
    var type = await FileSystemEntity.type(dir.path, followLinks: false);
    if (type == FileSystemEntityType.notFound && create) {
      await dir.create();
      type = await FileSystemEntity.type(dir.path, followLinks: false);
    }
    if (type != FileSystemEntityType.notFound &&
        (type != FileSystemEntityType.directory ||
            await dir.resolveSymbolicLinks() != dir.path)) {
      throw StateError('Invalid cleanup journal path');
    }
    return dir;
  }

  Future<String?> read() async {
    final dir = await _directory(create: false);
    final file = File('${dir.path}/plan.json');
    final type = await FileSystemEntity.type(file.path, followLinks: false);
    if (type == FileSystemEntityType.notFound) return null;
    if (type != FileSystemEntityType.file) {
      throw StateError('Invalid cleanup plan');
    }
    if (await file.length() > 8192) throw StateError('Invalid cleanup plan');
    final text = await file.readAsString();
    return text;
  }

  Future<void> write(String value) async {
    if (utf8.encode(value).length > 8192) {
      throw StateError('Invalid cleanup plan');
    }
    final dir = await _directory(create: true);
    final target = File('${dir.path}/plan.json');
    final type = await FileSystemEntity.type(target.path, followLinks: false);
    if (type != FileSystemEntityType.notFound &&
        type != FileSystemEntityType.file) {
      throw StateError('Invalid cleanup plan');
    }
    final random = Random.secure();
    final nonce = List.generate(
      16,
      (_) => random.nextInt(256),
    ).map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    final temp = await File('${dir.path}/.tmp-$nonce').create(exclusive: true);
    try {
      final handle = await temp.open(mode: FileMode.write);
      try {
        await handle.writeString(value);
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

  Future<void> clear() async {
    final dir = await _directory(create: false);
    final file = File('${dir.path}/plan.json');
    final type = await FileSystemEntity.type(file.path, followLinks: false);
    if (type == FileSystemEntityType.notFound) return;
    if (type != FileSystemEntityType.file) {
      throw StateError('Invalid cleanup plan');
    }
    await file.delete();
  }
}
