import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

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
  static const _activeProfileIdKey = 'active_profile_id_v1';

  /// Android 는 Keystore 로 암호화된 SharedPreferences 백엔드를 명시해야 한다
  /// (기본 백엔드는 구형 기기에서 평문으로 떨어질 수 있다).
  static const _secureOptions = AndroidOptions(encryptedSharedPreferences: true);
  static const _defaultSecureStorage = FlutterSecureStorage(
    aOptions: _secureOptions,
  );

  /// 부팅 시 [bootstrapUserKey] 가 채우는 프로세스 캐시.
  ///
  /// 보안 저장소 접근은 비동기인데 `getUserKey()` 는 앱 전반에서 동기로 쓰인다. 앱 부팅에서
  /// 한 번 읽어 캐시하고, 이후 동기 접근은 그 값을 돌려준다.
  static String? _cachedUserKey;

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
    } catch (error) {
      // 보안 저장소 장애(예: Keystore 손상)에서 앱을 못 켜게 만들지는 않는다.
      debugPrint('secure storage read 실패: $error');
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
        } catch (error) {
          debugPrint('user_key 보안 저장소 이관 실패(평문 유지): $error');
          key = legacy; // 이관 실패 시에도 계정은 유지 — 다음 부팅에서 재시도.
        }
      }
    }

    if (!_isValidKey(key)) {
      key = const Uuid().v4();
      try {
        await secure.write(
          key: _userKeyKey,
          value: key,
          aOptions: _secureOptions,
        );
      } catch (error) {
        debugPrint('user_key 보안 저장소 저장 실패: $error');
      }
    }

    _cachedUserKey = key;
    return key!;
  }

  static bool _isValidKey(String? value) => value != null && value.length >= 10;

  /// user_key 가져오기 (없으면 생성)
  ///
  /// 정상 경로에서는 [bootstrapUserKey] 가 채운 캐시를 돌려준다. 부트스트랩이 돌지 않은
  /// 컨텍스트(단위 테스트 등)에서는 레거시 평문을 **읽기만** 하고, 새 키는 평문에 쓰지 않고
  /// 보안 저장소에 비동기로 쓴다 — 어떤 경로로도 새 평문 자격증명이 생기지 않게.
  String getUserKey() {
    if (_isValidKey(_cachedUserKey)) {
      return _cachedUserKey!;
    }
    final legacy = _prefs.getString(_userKeyKey);
    if (_isValidKey(legacy)) {
      _cachedUserKey = legacy;
      return legacy!;
    }
    final generated = const Uuid().v4();
    _cachedUserKey = generated;
    unawaited(
      _secureStorage
          .write(key: _userKeyKey, value: generated, aOptions: _secureOptions)
          .catchError((Object error) {
        debugPrint('user_key 저장 실패: $error');
      }),
    );
    return generated;
  }

  /// user_key 초기화 (디버그용)
  Future<void> resetUserKey() async {
    _cachedUserKey = null;
    await _prefs.remove(_userKeyKey);
    try {
      await _secureStorage.delete(key: _userKeyKey, aOptions: _secureOptions);
    } catch (error) {
      debugPrint('user_key 삭제 실패: $error');
    }
  }

  @visibleForTesting
  static void resetCacheForTest() {
    _cachedUserKey = null;
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
