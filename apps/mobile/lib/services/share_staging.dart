import 'dart:async';
import 'dart:io';
import 'package:uuid/uuid.dart';

/// share_plus copies Android attachments into cache/share_plus before opening
/// the chooser. Its success result means a target was selected, not that the
/// receiver finished opening the file. Give that copy a bounded handoff window.
class ShareStaging {
  static const handoffWindow = Duration(minutes: 10);
  static final _name = RegExp(
    r'^asb-share-([a-f0-9]{64})-([a-f0-9]{64})-[a-f0-9-]{36}\.(pdf|jpg)$',
  );

  static Future<Directory> _directory(Directory base, String name) async {
    final path = '${await base.resolveSymbolicLinks()}/$name';
    final type = await FileSystemEntity.type(path, followLinks: false);
    if (type != FileSystemEntityType.directory &&
        type != FileSystemEntityType.notFound) {
      throw StateError('Unexpected share staging directory');
    }
    return Directory(path);
  }

  static Future<void> _unlink(File file) async {
    try {
      await file.delete();
    } on PathNotFoundException {
      // Another cleanup or the platform already removed this file.
    }
  }

  static Future<void> run({
    required Directory base,
    required String scope,
    required String bookToken,
    required String extension,
    required List<int> bytes,
    required Future<bool> Function(File) present,
  }) async {
    final name = 'asb-share-$scope-$bookToken-${const Uuid().v4()}.$extension';
    if (!_name.hasMatch(name)) throw ArgumentError('Invalid share file name');
    final staging = await _directory(base, 'asb_share_staging_v1');
    await staging.create();
    final source = File('${staging.path}/$name');
    await source.create(exclusive: true);
    var handedOff = false;
    try {
      await source.writeAsBytes(bytes, flush: true);
      handedOff = await present(source);
    } finally {
      await _unlink(source);
      if (Platform.isAndroid) {
        final android = await _directory(base, 'share_plus');
        final copy = File('${android.path}/$name');
        if (handedOff) {
          Timer(handoffWindow, () {
            unawaited(_unlink(copy).catchError((Object _) {}));
          });
        } else {
          await _unlink(copy);
        }
      }
    }
  }

  /// At cold start no previous chooser has an active source writer. A recent
  /// Android delivery may still be opening its copy after a process restart.
  static Future<void> clean(
    Directory base, {
    Set<String>? scopes,
    String? bookToken,
  }) async {
    for (final folder in ['asb_share_staging_v1', 'share_plus']) {
      final directory = await _directory(base, folder);
      if (!await directory.exists()) continue;
      await for (final item in directory.list(followLinks: false)) {
        if (item is! File) continue;
        final match = _name.firstMatch(item.uri.pathSegments.last);
        if (match == null ||
            (scopes != null && !scopes.contains(match[1])) ||
            (bookToken != null && bookToken != match[2])) {
          continue;
        }
        if (scopes == null && folder == 'share_plus') {
          final remaining = (await item.lastModified())
              .add(handoffWindow)
              .difference(DateTime.now());
          if (remaining > Duration.zero) {
            Timer(remaining > handoffWindow ? handoffWindow : remaining, () {
              unawaited(_unlink(item).catchError((Object _) {}));
            });
            continue;
          }
        }
        await _unlink(item);
      }
    }
  }

  /// Earlier versions used titles directly in the cache root. Their ownership
  /// is unknowable, so require the existing shared-data confirmation.
  static Future<bool> legacyFiles(Directory base, {bool remove = false}) async {
    for (final dir in [base, await _directory(base, 'share_plus')]) {
      if (!await dir.exists()) continue;
      await for (final entry in dir.list(followLinks: false)) {
        if (entry is! File) continue;
        final name = entry.uri.pathSegments.last;
        if (_name.hasMatch(name) ||
            !(name.endsWith('.pdf') || name.endsWith('_cover.jpg'))) {
          continue;
        }
        if (!remove) return true;
        await _unlink(entry);
      }
    }
    return false;
  }
}
