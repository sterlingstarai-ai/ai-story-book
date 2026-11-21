// Synthetic credentials only. Run on an isolated simulator/emulator with
// --dart-define=RUN_SECURITY_CREDENTIALS_NATIVE=true (replaces that install's keys).
import 'dart:io';

import 'package:ai_story_book/services/recovery_clipboard.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const oldKey = '11111111-2222-4333-8444-555555555555';
  final pendingKey = 'asb_device_${'B' * 43}';
  final code = 'ASB-R1-${'C' * 43}';
  final skipNative =
      !const bool.fromEnvironment('RUN_SECURITY_CREDENTIALS_NATIVE') ||
      (!Platform.isIOS && !Platform.isAndroid);

  // Run before the subsequent test installs a preferences mock. Both storage
  // plugins here must use the platform implementation on the isolated target.
  testWidgets(
    'native bootstrap after interrupted migration removes persisted plaintext',
    (tester) async {
      const secure = FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
        iOptions: IOSOptions(
          accessibility: KeychainAccessibility.unlocked_this_device,
          synchronizable: false,
        ),
      );
      final prefs = await SharedPreferences.getInstance();
      addTearDown(() async {
        await prefs.remove('user_key');
        await prefs.remove('user_key_initialized_v1');
        await secure.delete(key: 'user_key');
        UserService.resetCacheForTest();
      });
      // Model process death just after secure storage was committed.
      expect(await prefs.setString('user_key', oldKey), isTrue);
      await secure.write(key: 'user_key', value: oldKey);
      UserService.resetCacheForTest();
      await prefs.reload();
      expect(prefs.getString('user_key'), oldKey);
      expect(await secure.read(key: 'user_key'), oldKey);

      expect(
        await UserService.bootstrapUserKey(prefs, allowCreate: false),
        oldKey,
      );
      await prefs.reload();
      expect(prefs.containsKey('user_key'), isFalse);
      expect(await secure.read(key: 'user_key'), oldKey);

      UserService.resetCacheForTest();
      expect(
        await UserService.bootstrapUserKey(prefs, allowCreate: false),
        oldKey,
      );
      await prefs.reload();
      expect(prefs.containsKey('user_key'), isFalse);
    },
    skip: skipNative,
  );

  testWidgets(
    'native credential upgrade retains active and staged recovery keys',
    (tester) async {
      const original = FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
        iOptions: IOSOptions(accessibility: KeychainAccessibility.unlocked),
      );
      await original.delete(key: 'user_key');
      await original.delete(key: 'pending_recovered_user_key_v1');
      addTearDown(() async {
        await original.delete(key: 'user_key');
        await original.delete(key: 'pending_recovered_user_key_v1');
      });
      await original.write(key: 'user_key', value: oldKey);
      await original.write(
        key: 'pending_recovered_user_key_v1',
        value: pendingKey,
      );
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      UserService.resetCacheForTest();
      final user = UserService(prefs);
      expect(await user.pendingRecoveryKey(), pendingKey);
      expect(await UserService.bootstrapUserKey(prefs), oldKey);
      await user.activatePendingRecoveryKey();
      expect(user.getUserKey(), pendingKey);
      expect(await user.pendingRecoveryKey(), isNull);
      expect(await original.read(key: 'user_key'), pendingKey);
    },
    skip: skipNative,
  );

  testWidgets(
    'native protected copy preserves another app copy and expires its own item',
    (tester) async {
      // Keep the activity resumed/focused: Android restricts background clipboard reads.
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: Text('Synthetic security test')),
        ),
      );
      await tester.pumpAndSettle();
      // The engine can start tests before Android finishes focusing the window.
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 2)),
      );
      final clipboard = RecoveryClipboard();
      addTearDown(clipboard.dispose);
      await clipboard.copy(code);
      expect((await Clipboard.getData(Clipboard.kTextPlain))?.text, code);
      await Clipboard.setData(
        const ClipboardData(text: 'unrelated clipboard item'),
      );
      await clipboard.clear();
      expect(
        (await Clipboard.getData(Clipboard.kTextPlain))?.text,
        'unrelated clipboard item',
      );
      await clipboard.copy(code);
      expect((await Clipboard.getData(Clipboard.kTextPlain))?.text, code);
      // Android clipboard metadata can be inspected during this wait with adb.
      debugPrint('SECURITY_CLIPBOARD_EXPIRY_WAIT ${Platform.operatingSystem}');
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 62)),
      );
      // The test binding can have a null lifecycle state on a foreground simulator.
      // Check the clipboard, then prove reads are available with a fresh probe.
      // Read the candidate first so the probe cannot erase evidence of a leak.
      Future<void> expectEmptyAndReadable(String probe) async {
        final observed = (await Clipboard.getData(Clipboard.kTextPlain))?.text;
        expect(observed ?? '', isEmpty);
        await Clipboard.setData(ClipboardData(text: probe));
        expect((await Clipboard.getData(Clipboard.kTextPlain))?.text, probe);
      }

      await expectEmptyAndReadable('synthetic expiry read check');
      await clipboard.copy(code);
      expect((await Clipboard.getData(Clipboard.kTextPlain))?.text, code);
      await clipboard.dispose();
      await expectEmptyAndReadable('synthetic dispose read check');
    },
    skip: skipNative,
  );
}
