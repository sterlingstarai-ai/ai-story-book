import 'dart:async';
import 'dart:io';

import 'package:ai_story_book/services/recovery_clipboard.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const security = MethodChannel('ai_story_book/security');
  const storage = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final code = 'ASB-R1-${'A' * 43}';

  setUp(() {
    UserService.resetCacheForTest();
    SharedPreferences.setMockInitialValues({});
  });
  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
    messenger.setMockMethodCallHandler(security, null);
    messenger.setMockMethodCallHandler(storage, null);
  });

  test(
    'copy uses protected native channel and clears only the returned handle',
    () async {
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(security, (call) async {
        calls.add(call);
        return call.method == 'copyRecoveryCode' ? 'native-item' : null;
      });
      final clipboard = RecoveryClipboard();
      await clipboard.copy(code);
      await clipboard.clear();
      await clipboard.dispose();
      expect(calls.map((c) => c.method), [
        'copyRecoveryCode',
        'clearRecoveryCode',
      ]);
      expect(calls.first.arguments, code);
      expect(calls.last.arguments, 'native-item');
    },
  );

  test(
    'closing during native copy clears its eventual clipboard item',
    () async {
      final pending = Completer<String>();
      final cleared = <Object?>[];
      messenger.setMockMethodCallHandler(security, (call) async {
        if (call.method == 'copyRecoveryCode') return pending.future;
        cleared.add(call.arguments);
        return null;
      });
      final clipboard = RecoveryClipboard();
      final copy = clipboard.copy(code);
      await clipboard.dispose();
      pending.complete('late-item');
      await copy;
      expect(cleared, ['late-item']);
    },
  );

  test(
    'unavailable secure copy fails without an ordinary clipboard fallback',
    () async {
      final clipboard = RecoveryClipboard();
      await expectLater(
        clipboard.copy(code),
        throwsA(isA<MissingPluginException>()),
      );
      await clipboard.dispose();
    },
  );

  test(
    'iOS protects both existing credentials before recovery initialization reads',
    () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      final calls = <String>[];
      final values = <String, String>{
        'user_key': '11111111-2222-4333-8444-555555555555',
        'pending_recovered_user_key_v1': 'asb_device_${'B' * 43}',
      };
      messenger.setMockMethodCallHandler(security, (call) async {
        calls.add(call.method);
        return null;
      });
      messenger.setMockMethodCallHandler(storage, (call) async {
        calls.add(call.method);
        final args = Map<String, dynamic>.from(call.arguments as Map);
        // The plugin selects options with dart:io.Platform, independent of
        // Flutter's platform override. Actual iOS attributes have native tests.
        if (Platform.isIOS || Platform.isMacOS) {
          expect(args['options']['synchronizable'], 'false');
        }
        if (call.method == 'read') return values[args['key']];
        if (call.method == 'write') values[args['key']] = args['value'];
        if (call.method == 'delete') values.remove(args['key']);
        return null;
      });
      final prefs = await SharedPreferences.getInstance();
      final user = UserService(prefs);
      expect(
        await user.pendingRecoveryKey(),
        values['pending_recovered_user_key_v1'],
      );
      expect(calls.first, 'protectDeviceCredentials');
      expect(await UserService.bootstrapUserKey(prefs), values['user_key']);
      await user.activatePendingRecoveryKey();
      expect(user.getUserKey(), 'asb_device_${'B' * 43}');
      expect(values['pending_recovered_user_key_v1'], isNull);
      expect(calls.where((c) => c == 'protectDeviceCredentials').length, 1);
    },
  );

  test(
    'failed iOS protection cannot read, replace or delete an existing account; retry works',
    () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      var fail = true;
      var storageReads = 0;
      messenger.setMockMethodCallHandler(security, (call) async {
        if (fail) throw PlatformException(code: 'KEYCHAIN_UNAVAILABLE');
        return null;
      });
      messenger.setMockMethodCallHandler(storage, (call) async {
        expect(call.method, 'read');
        storageReads++;
        return '11111111-2222-4333-8444-555555555555';
      });
      final prefs = await SharedPreferences.getInstance();
      await expectLater(
        UserService.bootstrapUserKey(prefs),
        throwsA(isA<UserKeyUnavailable>()),
      );
      expect(storageReads, 0);
      expect(prefs.getBool('user_key_initialized_v1'), isNull);
      fail = false;
      expect(
        await UserService.bootstrapUserKey(prefs),
        '11111111-2222-4333-8444-555555555555',
      );
      expect(storageReads, 1);
    },
  );
}
