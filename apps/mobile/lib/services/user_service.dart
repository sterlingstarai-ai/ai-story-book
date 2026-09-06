import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class UserKeyUnavailable implements Exception {
  const UserKeyUnavailable();
}

/// 사용자 서비스 (user_key 관리)
///
/// M1(2026-08-17 보안감사): `X-User-Key` 는 이 앱의 **유일한 자격증명**이다(비밀번호·토큰
/// 없음). 이 값을 아는 사람은 그 계정의 서재·아동 사진·크레딧·구독에 그대로 접근한다.
/// 그런데 예전에는 SharedPreferences 평문(Android `shared_prefs/*.xml`, iOS plist)에
/// 저장됐고 Android 기본 `allowBackup=true` 로 클라우드 백업에도 포함됐다 → 기기 이전·
/// 백업 추출·루팅/탈옥 어느 쪽이든 **계정 탈취**다.
///
/// 지금은 iOS Keychain / Android Keystore(EncryptedSharedPreferences)에 저장하고,
/// 기존 평문 값은 부팅 시 1회 이관 후 삭제한다.
class UserService {
  static const _userKeyKey = 'user_key';
  static const _initializedKey = 'user_key_initialized_v1';
  static const _pendingRecoveryKey = 'pending_recovered_user_key_v1';
  static const deletionCommittedKey = 'account_deletion_committed_v1';
  static const recoveryBackupNeededKey = 'recovery_backup_needed_v1';
  static const _activeProfileIdKey = 'active_profile_id_v1';

  /// Android 는 Keystore 로 암호화된 SharedPreferences 백엔드를 명시해야 한다
  /// (기본 백엔드는 구형 기기에서 평문으로 떨어질 수 있다).
  static const _secureOptions =
      AndroidOptions(encryptedSharedPreferences: true);
  static const _defaultSecureStorage = FlutterSecureStorage(
    aOptions: _secureOptions,
  );

  /// 부팅 시 [bootstrapUserKey] 가 채우는 프로세스 캐시.
  ///
  /// 보안 저장소 접근은 비동기인데 `getUserKey()` 는 앱 전반에서 동기로 쓰인다. 앱 부팅에서
  /// 한 번 읽어 캐시하고, 이후 동기 접근은 그 값을 돌려준다.
  static String? _cachedUserKey;
  static bool _credentialUnavailable = false;

  final SharedPreferences _prefs;
  final FlutterSecureStorage _secureStorage;

  UserService(
    this._prefs, {
    FlutterSecureStorage? secureStorage,
  }) : _secureStorage = secureStorage ?? _defaultSecureStorage;

  /// 앱 부팅에서 1회 호출 — 보안 저장소에서 user_key 를 읽고, 없으면 평문 값을 이관한다.
  ///
  /// 순서가 계약이다: **보안 저장소 쓰기 성공 후에만** 평문을 삭제한다. 반대로 하면 중간에
  /// 죽었을 때 자격증명이 사라져 **계정 자체가 유실**된다(서재·구독 접근 불가).
  static Future<String> bootstrapUserKey(
    SharedPreferences prefs, {
    FlutterSecureStorage? secureStorage,
  }) async {
    final secure = secureStorage ?? _defaultSecureStorage;

    String? key;
    try {
      key = await secure.read(key: _userKeyKey);
    } catch (_) {
      // 읽기 실패는 신규 설치가 아니다. 기존 키를 절대 덮어쓰지 않는다.
      throw const UserKeyUnavailable();
    }

    if (key != null && !_isValidKey(key)) {
      throw const UserKeyUnavailable();
    }

    if (!_isValidKey(key)) {
      final legacy = prefs.getString(_userKeyKey);
      if (_isValidKey(legacy)) {
        // 이관: 보안 저장소에 먼저 쓰고, 성공했을 때만 평문 제거.
        try {
          await secure.write(
            key: _userKeyKey,
            value: legacy,
            aOptions: _secureOptions,
          );
          await prefs.remove(_userKeyKey);
          key = legacy;
        } catch (_) {
          debugPrint('user_key 보안 저장소 이관 실패(다음 부팅에서 재시도)');
          key = legacy; // 이관 실패 시에도 계정은 유지 — 다음 부팅에서 재시도.
        }
      }
    }

    if (!_isValidKey(key)) {
      if (prefs.getBool(_initializedKey) == true) {
        throw const UserKeyUnavailable();
      }
      key = const Uuid().v4();
      try {
        await secure.write(
          key: _userKeyKey,
          value: key,
          aOptions: _secureOptions,
        );
        if (await secure.read(key: _userKeyKey) != key) {
          throw const UserKeyUnavailable();
        }
      } catch (_) {
        // 영속화되지 않은 임시 계정으로 결제·책 생성을 시작하지 않는다.
        throw const UserKeyUnavailable();
      }
    }

    await prefs.setBool(_initializedKey, true);
    _cachedUserKey = key;
    _credentialUnavailable = false;
    return key!;
  }

  static bool _isValidKey(String? value) => value != null && value.length >= 10;

  /// 부트스트랩이 확인한 키를 읽는다. 동기 경로에서는 새 계정을 만들지 않는다.
  ///
  /// 정상 경로에서는 [bootstrapUserKey] 가 채운 캐시를 돌려준다. 부트스트랩이 돌지 않은
  /// 컨텍스트(기존 테스트 등)에서는 레거시 값을 읽을 수 있다.
  String getUserKey() {
    if (_credentialUnavailable) throw const UserKeyUnavailable();
    if (_isValidKey(_cachedUserKey)) {
      return _cachedUserKey!;
    }
    final legacy = _prefs.getString(_userKeyKey);
    if (_isValidKey(legacy)) {
      _cachedUserKey = legacy;
      return legacy!;
    }
    throw const UserKeyUnavailable();
  }

  /// Stage a credential durably before the server invalidates the old device.
  Future<String> prepareRecoveryKey() async {
    final existing = await pendingRecoveryKey();
    if (existing != null) return existing;
    final random = Random.secure();
    final bytes = List<int>.generate(32, (_) => random.nextInt(256));
    final key = 'asb_device_${base64UrlEncode(bytes).replaceAll('=', '')}';
    try {
      await _secureStorage.write(
          key: _pendingRecoveryKey, value: key, aOptions: _secureOptions);
      if (await _secureStorage.read(key: _pendingRecoveryKey) != key) {
        throw const UserKeyUnavailable();
      }
    } catch (_) {
      throw const UserKeyUnavailable();
    }
    return key;
  }

  Future<String?> pendingRecoveryKey() async {
    try {
      final key = await _secureStorage.read(key: _pendingRecoveryKey);
      if (key != null &&
          !RegExp(r'^asb_device_[A-Za-z0-9_-]{43}$').hasMatch(key)) {
        throw const UserKeyUnavailable();
      }
      return key;
    } catch (_) {
      throw const UserKeyUnavailable();
    }
  }

  Future<void> discardPendingRecoveryKey() async {
    try {
      await _secureStorage.delete(
          key: _pendingRecoveryKey, aOptions: _secureOptions);
    } catch (_) {
      throw const UserKeyUnavailable();
    }
  }

  /// A failed write leaves the staged key available to reconcile on restart.
  /// Clear every old account preference before exposing the recovered credential.
  Future<void> activatePendingRecoveryKey() async {
    final key = await pendingRecoveryKey();
    if (key == null) throw const UserKeyUnavailable();
    _credentialUnavailable = true;
    try {
      await _secureStorage.write(
          key: _userKeyKey, value: key, aOptions: _secureOptions);
      if (await _secureStorage.read(key: _userKeyKey) != key) {
        throw const UserKeyUnavailable();
      }
      if (!await _prefs.clear() ||
          !await _prefs.setBool(_initializedKey, true) ||
          !await _prefs.setBool(recoveryBackupNeededKey, true)) {
        throw const UserKeyUnavailable();
      }
      _cachedUserKey = key;
      await discardPendingRecoveryKey();
      _credentialUnavailable = false;
    } catch (_) {
      // The old key may already be revoked. Never keep using it on this process.
      _cachedUserKey = null;
      throw const UserKeyUnavailable();
    }
  }

  /// Called only after the server confirms account deletion, including a durable
  /// media purge retry. The marker makes storage failure retryable at bootstrap.
  Future<void> completeAccountDeletion() async {
    _credentialUnavailable = true;
    try {
      if (!await _prefs.setBool(deletionCommittedKey, true)) {
        throw const UserKeyUnavailable();
      }
      final key = const Uuid().v4();
      await _secureStorage.write(
          key: _userKeyKey, value: key, aOptions: _secureOptions);
      if (await _secureStorage.read(key: _userKeyKey) != key) {
        throw const UserKeyUnavailable();
      }
      await discardPendingRecoveryKey();
      if (!await _prefs.clear() ||
          !await _prefs.setBool(_initializedKey, true)) {
        throw const UserKeyUnavailable();
      }
      _cachedUserKey = key;
      _credentialUnavailable = false;
    } catch (_) {
      _cachedUserKey = null;
      throw const UserKeyUnavailable();
    }
  }

  /// user_key 초기화 (디버그용)
  Future<void> resetUserKey() async {
    _cachedUserKey = null;
    await _prefs.remove(_userKeyKey);
    try {
      await _secureStorage.delete(key: _userKeyKey, aOptions: _secureOptions);
      await _prefs.remove(_initializedKey);
    } catch (_) {
      debugPrint('user_key 삭제 실패');
    }
  }

  @visibleForTesting
  static void resetCacheForTest() {
    _cachedUserKey = null;
    _credentialUnavailable = false;
  }

  String? getActiveProfileId() {
    final value = _prefs.getString(_activeProfileIdKey);
    if (value == null || value.trim().isEmpty) {
      return null;
    }
    return value.trim();
  }

  Future<void> setActiveProfileId(String? profileId) async {
    final normalized = profileId?.trim();
    if (normalized == null || normalized.isEmpty) {
      await _prefs.remove(_activeProfileIdKey);
      return;
    }
    await _prefs.setString(_activeProfileIdKey, normalized);
  }
}
