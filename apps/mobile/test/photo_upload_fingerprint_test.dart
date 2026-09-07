import 'dart:io';

import 'package:ai_story_book/services/photo_upload_fingerprint.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'identical uploads have the same fingerprint across picker cache paths',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'photo-upload-fingerprint-',
      );
      try {
        final first = File('${directory.path}/first.jpg');
        final reselected = File('${directory.path}/reselected.jpg');
        await first.writeAsBytes([1, 2, 3, 4]);
        await reselected.writeAsBytes([1, 2, 3, 4]);
        final digest = await fingerprintPhotoUpload(first);
        expect(await fingerprintPhotoUpload(reselected), digest);
        await reselected.writeAsBytes([4, 3, 2, 1]);
        expect(await fingerprintPhotoUpload(reselected), isNot(digest));
        expect(await first.readAsBytes(), [1, 2, 3, 4]);
      } finally {
        await directory.delete(recursive: true);
      }
    },
  );
}
