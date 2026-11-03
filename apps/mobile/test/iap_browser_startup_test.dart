import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/services/iap_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final platform in [TargetPlatform.macOS, TargetPlatform.android]) {
    test('browser startup skips native store on ${platform.name}', () async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);

      final service = IapService();
      expect(
        await service.purchaseStream.toList().timeout(const Duration(seconds: 3)),
        isEmpty,
      );
      expect(service.isConfigured, isFalse);
      expect((await service.checkAvailability()).isAvailable, isFalse);
    }, skip: !kIsWeb);
  }
}
