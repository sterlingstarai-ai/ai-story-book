// Native simulator/device Keychain/Keystore probe. Only uniquely prefixed test
// keys are touched; preferences are in-memory and no backend is contacted.
import 'dart:io';

import 'package:ai_story_book/services/user_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NamespacedNativeStorage extends FlutterSecureStorage {
  _NamespacedNativeStorage(this.prefix);
  final String prefix;
  final delegate = const FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true));

  @override
  Future<String?> read(
          {required String key,
          IOSOptions? iOptions,
          AndroidOptions? aOptions,
          LinuxOptions? lOptions,
          WebOptions? webOptions,
          MacOsOptions? mOptions,
          WindowsOptions? wOptions}) =>
      delegate.read(key: '$prefix$key');

  @override
  Future<void> write(
          {required String key,
          required String? value,
          IOSOptions? iOptions,
          AndroidOptions? aOptions,
          LinuxOptions? lOptions,
          WebOptions? webOptions,
          MacOsOptions? mOptions,
          WindowsOptions? wOptions}) =>
      delegate.write(key: '$prefix$key', value: value);

  @override
  Future<void> delete(
          {required String key,
          IOSOptions? iOptions,
          AndroidOptions? aOptions,
          LinuxOptions? lOptions,
          WebOptions? webOptions,
          MacOsOptions? mOptions,
          WindowsOptions? wOptions}) =>
      delegate.delete(key: '$prefix$key');
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
      'native secure account bootstrap, staged recovery, restart and deletion',
      (tester) async {
    final storage = _NamespacedNativeStorage(
        'acceptance_${DateTime.now().microsecondsSinceEpoch}_');
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    UserService.resetCacheForTest();
    final user = UserService(prefs, secureStorage: storage);
    try {
      final original =
          await UserService.bootstrapUserKey(prefs, secureStorage: storage);
      expect(original, isNotEmpty);
      expect(await storage.read(key: 'user_key'), original);
      await prefs.setString('active_profile_id_v1', 'synthetic-old-profile');
      final pending = await user.prepareRecoveryKey();
      expect(pending, matches(r'^asb_device_[A-Za-z0-9_-]{43}$'));
      expect(await storage.read(key: 'pending_recovered_user_key_v1'), pending);
      expect(user.getUserKey(), original);
      // Network authentication/rotation is covered separately; commit the
      // simulated successful response through the real native storage boundary.
      await user.activatePendingRecoveryKey();
      expect(user.getUserKey(), pending);
      expect(await storage.read(key: 'pending_recovered_user_key_v1'), isNull);
      expect(prefs.containsKey('active_profile_id_v1'), false);
      UserService.resetCacheForTest();
      expect(await UserService.bootstrapUserKey(prefs, secureStorage: storage),
          pending);
      await user.completeAccountDeletion();
      expect(user.getUserKey(), isNot(pending));
      expect(await storage.read(key: 'user_key'), user.getUserKey());
    } finally {
      await storage.delete(key: 'pending_recovered_user_key_v1');
      await storage.delete(key: 'user_key');
      UserService.resetCacheForTest();
    }
  }, skip: !Platform.isIOS && !Platform.isAndroid);
}
