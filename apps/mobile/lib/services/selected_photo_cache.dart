import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

final selectedPhotoCacheCleanerProvider =
    Provider<Future<void> Function(XFile?)>((ref) => deleteSelectedPhotoCache);

/// Only remove the picker copy in an application/OS cache, never a photo-library
/// or documents original. Resolve links before checking the cache boundary.
Future<void> deleteSelectedPhotoCache(XFile? image) async {
  if (image == null) return;
  try {
    final file = File(image.path);
    if (!await file.exists()) return;
    final path = await file.resolveSymbolicLinks();
    final roots = <Directory>[Directory.systemTemp];
    try {
      roots.add(await getTemporaryDirectory());
    } catch (_) {}
    try {
      roots.add(await getApplicationCacheDirectory());
    } catch (_) {}
    for (final root in roots) {
      final rootPath = await root.resolveSymbolicLinks();
      if (path.startsWith('$rootPath${Platform.pathSeparator}')) {
        await file.delete();
        return;
      }
    }
  } catch (_) {
    // A missing picker copy has already been cleaned up by the platform.
  }
}
