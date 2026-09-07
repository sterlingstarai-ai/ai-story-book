import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/account_recovery_screen.dart';
import 'package:ai_story_book/services/account_recovery_service.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _oldKey = '11111111-2222-4333-8444-555555555555';
final _code = 'ASB-R1-${List.filled(43, 'A').join()}';
final _replacement = 'ASB-R1-${List.filled(43, 'B').join()}';

class _Secure extends FlutterSecureStorage {
  final store = <String, String>{'user_key': _oldKey};
  String? failWriteKey;
  String? silentWriteKey;
  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => store[key];
  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (key == failWriteKey) throw Exception('storage unavailable');
    if (key == silentWriteKey) return;
    if (value != null) store[key] = value;
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    store.remove(key);
  }
}

DioException _httpError(int status) {
  final options = RequestOptions(path: '/v1/account/recover');
  return DioException(
    requestOptions: options,
    response: Response(requestOptions: options, statusCode: status),
  );
}

class _RecoveryApi extends ApiClient {
  _RecoveryApi() : super(baseUrl: 'http://localhost', userKey: 'unused');
  bool active = false;
  bool loseResponse = false;
  bool deny = false;
  bool codeFails = false;
  int calls = 0;
  bool deleted = false;
  bool deletionUncertain = false;
  bool deletionUnauthorized = false;
  int deleteCalls = 0;
  @override
  Future<void> deleteMyData() async {
    deleteCalls++;
    if (deletionUnauthorized) throw _httpError(401);
    if (deleted) {
      throw DioException(
        requestOptions: RequestOptions(path: '/v1/users/me'),
        error: ApiError(code: 'ACCOUNT_DELETED', message: '', statusCode: 401),
      );
    }
    deleted = true;
    if (deletionUncertain) throw TimeoutException('lost response');
  }

  String? newKey;
  Future<void> Function()? beforeRecover;
  @override
  Future<bool> hasAccountRecovery() async => false;
  @override
  Future<String?> recoverAccount({
    required String recoveryCode,
    required String newUserKey,
  }) async {
    await beforeRecover?.call();
    calls++;
    newKey = newUserKey;
    if (deny) throw _httpError(401);
    if (active) return null;
    active = true;
    if (loseResponse) throw TimeoutException('interrupted');
    return _replacement;
  }

  @override
  Future<void> validateAccountSession() async {
    if (!active) throw _httpError(401);
  }

  @override
  Future<String> createAccountRecoveryCode() async {
    if (codeFails) throw _httpError(503);
    return _replacement;
  }

  @override
  Future<Map<String, dynamic>> getConsent() async => {
    'granted': true,
    'privacy': true,
    'data_processing': true,
    'revoked': false,
  };
}

void main() {
  late SharedPreferences prefs;
  late _Secure secure;
  late UserService user;
  late _RecoveryApi api;
  late AccountRecoveryService service;

  setUp(() async {
    UserService.resetCacheForTest();
    SharedPreferences.setMockInitialValues({
      'active_profile_id_v1': 'old-profile',
      'book_cache_old_v1': 'child data',
      'age_gate_session_v1': 123,
      'user_key_initialized_v1': true,
      'onboarding_done_v1': true,
    });
    prefs = await SharedPreferences.getInstance();
    secure = _Secure();
    user = UserService(prefs, secureStorage: secure);
    await UserService.bootstrapUserKey(prefs, secureStorage: secure);
    api = _RecoveryApi();
    service = AccountRecoveryService(
      purgeLocalMedia: () async {},
      userService: user,
      preferences: prefs,
      clientForKey: (_) => api,
    );
  });

  test(
    'lost delete response keeps intent and old credential, restart reconciles before profiles load',
    () async {
      api.deletionUncertain = true;
      await expectLater(
        service.deleteAccount(client: api),
        throwsA(isA<TimeoutException>()),
      );
      expect(user.deletionRequested, isTrue);
      expect(user.getUserKey(), _oldKey);
      expect(prefs.getString('active_profile_id_v1'), 'old-profile');
      UserService.resetCacheForTest();
      await service.initialize();
      expect(api.deleteCalls, 2);
      expect(user.deletionRequested, isFalse);
      expect(user.getUserKey(), isNot(_oldKey));
      expect(prefs.getString('active_profile_id_v1'), isNull);
      expect(prefs.getString('book_cache_old_v1'), isNull);
    },
  );

  test(
    'committed deletion waits for failed disk purge and resumes offline without another delete',
    () async {
      var fail = true;
      var purgeCalls = 0;
      service = AccountRecoveryService(
        userService: user,
        preferences: prefs,
        clientForKey: (_) => api,
        purgeLocalMedia: () async {
          purgeCalls++;
          if (fail) throw StateError('disk unavailable');
        },
      );
      await expectLater(service.deleteAccount(client: api), throwsStateError);
      expect(prefs.getBool(UserService.deletionCommittedKey), true);
      expect(user.getUserKey(), _oldKey);
      expect(api.deleteCalls, 1);
      fail = false;
      await service.initialize();
      expect(purgeCalls, 2);
      expect(api.deleteCalls, 1);
      expect(user.getUserKey(), isNot(_oldKey));
      expect(prefs.getString('book_cache_old_v1'), isNull);
    },
  );

  test('generic unauthorized does not confirm account deletion', () async {
    api.deletionUnauthorized = true;
    await expectLater(
      service.deleteAccount(client: api),
      throwsA(isA<DioException>()),
    );
    expect(user.deletionRequested, isTrue);
    expect(user.getUserKey(), _oldKey);
    expect(prefs.getString('book_cache_old_v1'), 'child data');
  });

  test(
    'stages cryptographic credential before network and clears old account scope only after success',
    () async {
      api.beforeRecover = () async {
        final staged = await user.pendingRecoveryKey();
        expect(staged, matches(r'^asb_device_[A-Za-z0-9_-]{43}$'));
        expect(user.getUserKey(), _oldKey);
        expect(prefs.getString('book_cache_old_v1'), 'child data');
      };
      expect(await service.recover(_code), _replacement);
      expect(user.getUserKey(), api.newKey);
      expect(await user.pendingRecoveryKey(), isNull);
      expect(prefs.getString('active_profile_id_v1'), isNull);
      expect(prefs.getString('book_cache_old_v1'), isNull);
      expect(prefs.getInt('age_gate_session_v1'), isNull);
      expect(prefs.getBool('onboarding_done_v1'), isNull);
      expect(prefs.getBool('consent_granted_v1'), true);
      expect(prefs.getBool(UserService.recoveryBackupNeededKey), true);
      expect(prefs.getKeys().any((k) => prefs.get(k) == api.newKey), false);
    },
  );

  for (final silent in [false, true]) {
    test(
      'staging ${silent ? 'readback mismatch' : 'write failure'} prevents server rotation',
      () async {
        if (silent) {
          secure.silentWriteKey = 'pending_recovered_user_key_v1';
        } else {
          secure.failWriteKey = 'pending_recovered_user_key_v1';
        }
        await expectLater(
          service.recover(_code),
          throwsA(isA<UserKeyUnavailable>()),
        );
        expect(api.calls, 0);
        expect(user.getUserKey(), _oldKey);
      },
    );
  }

  test(
    'lost response is reconciled with staged credential and new backup is issued',
    () async {
      api.loseResponse = true;
      expect(await service.recover(_code), _replacement);
      expect(api.calls, 1);
      expect(user.getUserKey(), api.newKey);
    },
  );

  test(
    'active write failure leaves staged credential recoverable on restart',
    () async {
      secure.failWriteKey = 'user_key';
      await expectLater(
        service.recover(_code),
        throwsA(isA<UserKeyUnavailable>()),
      );
      expect(await user.pendingRecoveryKey(), api.newKey);
      expect(() => user.getUserKey(), throwsA(isA<UserKeyUnavailable>()));
      secure.failWriteKey = null;
      await service.initialize();
      expect(user.getUserKey(), api.newKey);
      expect(await user.pendingRecoveryKey(), isNull);
      expect(prefs.getBool(UserService.recoveryBackupNeededKey), true);
    },
  );

  test(
    'restart does not discard a 401 staged credential that may still commit',
    () async {
      final pending = await user.prepareRecoveryKey();
      await expectLater(service.initialize(), throwsA(isA<DioException>()));
      expect(await user.pendingRecoveryKey(), pending);
      expect(user.getUserKey(), _oldKey);
    },
  );

  test(
    'definitive first rejection preserves the old account and clears unused stage',
    () async {
      api.deny = true;
      await expectLater(service.recover(_code), throwsA(isA<DioException>()));
      expect(await user.pendingRecoveryKey(), isNull);
      expect(user.getUserKey(), _oldKey);
      expect(prefs.getString('book_cache_old_v1'), 'child data');
    },
  );

  test('rejected retry retains the existing ambiguous stage', () async {
    final pending = await user.prepareRecoveryKey();
    api.deny = true;
    await expectLater(service.recover(_code), throwsA(isA<DioException>()));
    expect(await user.pendingRecoveryKey(), pending);
  });

  test(
    'backup issue failure does not lose a successfully recovered account',
    () async {
      api.active = true;
      api.codeFails = true;
      expect(await service.recover(_code), isNull);
      expect(user.getUserKey(), api.newKey);
      expect(prefs.getBool(UserService.recoveryBackupNeededKey), true);
    },
  );

  test(
    'confirmed deletion replaces a revoked device and removes all recovery state',
    () async {
      await user.prepareRecoveryKey();
      await user.completeAccountDeletion();
      expect(user.getUserKey(), isNot(_oldKey));
      expect(user.getUserKey().startsWith('asb_device_'), false);
      expect(await user.pendingRecoveryKey(), isNull);
      expect(prefs.containsKey('book_cache_old_v1'), false);
      expect(prefs.containsKey(UserService.deletionCommittedKey), false);
      expect(prefs.getBool('user_key_initialized_v1'), true);
    },
  );

  test(
    'confirmed deletion storage failure retries at bootstrap without another delete',
    () async {
      secure.failWriteKey = 'user_key';
      await expectLater(
        user.completeAccountDeletion(),
        throwsA(isA<UserKeyUnavailable>()),
      );
      expect(prefs.getBool(UserService.deletionCommittedKey), true);
      secure.failWriteKey = null;
      await service.initialize();
      expect(user.getUserKey(), isNot(_oldKey));
      expect(prefs.containsKey(UserService.deletionCommittedKey), false);
    },
  );

  test('revoked recovered credential fails bootstrap validation', () async {
    final key = await user.prepareRecoveryKey();
    await user.activatePendingRecoveryKey();
    expect(user.getUserKey(), key);
    await expectLater(
      service.validateCurrentSession(),
      throwsA(isA<UserKeyUnavailable>()),
    );
  });

  testWidgets(
    'backup save requires explicit check and suffix confirmation in a short large-text viewport',
    (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(api),
          ],
          child: MaterialApp(
            locale: const Locale('en'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(1.4)),
              child: child!,
            ),
            home: const AccountRecoveryScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(
                OutlinedButton,
                'Restore an existing account',
              ),
            )
            .onPressed,
        isNull,
      );
      await tester.ensureVisible(find.text('Create recovery code'));
      await tester.tap(find.text('Create recovery code'));
      await tester.pumpAndSettle();
      expect(find.text(_replacement), findsOneWidget);
      expect(tester.takeException(), isNull);
      var confirm = find.widgetWithText(FilledButton, 'Confirm saved code');
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      await tester.ensureVisible(find.byType(CheckboxListTile));
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'BBBBBB');
      await tester.pumpAndSettle();
      await tester.ensureVisible(confirm);
      expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      expect(find.text(_replacement), findsNothing);
      expect(prefs.getBool(UserService.recoveryBackupNeededKey), false);
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(
                OutlinedButton,
                'Restore an existing account',
              ),
            )
            .onPressed,
        isNotNull,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'malformed recovery code does not submit; input disables suggestions and learning',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            accountRecoveryServiceProvider.overrideWithValue(service),
          ],
          child: const MaterialApp(
            locale: Locale('en'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: AccountRecoveryScreen(restoreOnly: true),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final input = tester.widget<TextField>(
        find.byKey(const ValueKey('recovery-code-input')),
      );
      expect(input.obscureText, true);
      expect(input.enableSuggestions, false);
      expect(input.enableIMEPersonalizedLearning, false);
      await tester.enterText(find.byType(TextField), 'wrong');
      await tester.tap(find.text('Restore this account'));
      await tester.pumpAndSettle();
      expect(api.calls, 0);
      expect(
        find.text('Enter the complete recovery code beginning with ASB-R1-.'),
        findsOneWidget,
      );
    },
  );
}
