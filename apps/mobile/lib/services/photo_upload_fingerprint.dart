import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final photoUploadFingerprintProvider = Provider<Future<String> Function(File)>(
  (ref) => fingerprintPhotoUpload,
);

/// A picker gives the same photo a new temporary path on each selection.
/// Keep only its digest in the pending upload attempt; never retain the photo.
/// The digest is local and is not sent to the API or written to logs/storage.
Future<String> fingerprintPhotoUpload(File photo) async =>
    (await sha256.bind(photo.openRead()).first).toString();
