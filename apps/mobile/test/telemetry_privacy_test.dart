import 'dart:convert';

import 'package:ai_story_book/core/app_telemetry.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('telemetry preserves diagnostics without credentials or child data', () {
    final sanitized = AppTelemetry.sanitizeData({
      'requestId': 'correlation-id',
      'code': 'NETWORK_ERROR',
      'statusCode': 503,
      'X-User-Key': 'account-secret',
      'recovery_code': 'backup-secret',
      'new_user_key': 'device-secret',
      'detail': 'ASB-R1-hiddenBackup asb_device_hiddenDevice',
      'body': {'child_name': 'private-name'},
      'url': 'https://example.com/image?X-Amz-Signature=secret',
      'path': '/share/family-secret/img/cover',
      'nested': {'receipt': 'receipt-secret'},
    });
    expect(sanitized['requestId'], 'correlation-id');
    expect(sanitized['code'], 'NETWORK_ERROR');
    expect(sanitized['statusCode'], 503);
    final serialized = jsonEncode(sanitized);
    for (final secret in [
      'account-secret',
      'private-name',
      'X-Amz-Signature',
      'family-secret',
      'receipt-secret',
      'backup-secret',
      'device-secret',
      'hiddenBackup',
      'hiddenDevice'
    ]) {
      expect(serialized, isNot(contains(secret)));
    }
  });
}
