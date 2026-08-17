import 'dart:io';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/services/iap_platform_init.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/services/user_service.dart';

/// 인메모리 보안 저장소 페이크 — 실 Keychain/Keystore 대신.
class _FakeSecureStorage extends FlutterSecureStorage {
  _FakeSecureStorage({this.writeThrows = false}) : super();

  final Map<String, String> store = <String, String>{};
  final bool writeThrows;
  int writeCalls = 0;

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    return store[key];
  }

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
    writeCalls++;
    if (writeThrows) {
      throw Exception('keystore write failed');
    }
    if (value == null) {
      store.remove(key);
    } else {
      store[key] = value;
    }
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

void main() {
  setUp(UserService.resetCacheForTest);

  // ════════ M1: X-User-Key 를 Keychain/Keystore 로 (평문 이관 + 삭제) ════════

  group('M1 — user_key 보안 저장', () {
    test('기존 평문 값을 보안 저장소로 이관하고 평문을 삭제한다', () async {
      const legacyKey = '11111111-2222-4333-8444-555555555555';
      SharedPreferences.setMockInitialValues(<String, Object>{
        'user_key': legacyKey,
      });
      final prefs = await SharedPreferences.getInstance();
      final secure = _FakeSecureStorage();

      final resolved = await UserService.bootstrapUserKey(
        prefs,
        secureStorage: secure,
      );

      // 같은 계정이 유지돼야 한다(키가 바뀌면 서재·구독을 통째로 잃는다).
      expect(resolved, legacyKey);
      expect(secure.store['user_key'], legacyKey);
      // 평문은 사라진다 — 이게 없으면 백업·기기이전 유출 경로가 그대로 남는다.
      expect(prefs.getString('user_key'), isNull);
    });

    test('보안 저장소 쓰기가 실패하면 평문을 지우지 않는다(자격증명 유실 방지)', () async {
      const legacyKey = '11111111-2222-4333-8444-555555555555';
      SharedPreferences.setMockInitialValues(<String, Object>{
        'user_key': legacyKey,
      });
      final prefs = await SharedPreferences.getInstance();
      final secure = _FakeSecureStorage(writeThrows: true);

      final resolved = await UserService.bootstrapUserKey(
        prefs,
        secureStorage: secure,
      );

      expect(resolved, legacyKey);
      // 쓰기 실패 후 평문까지 지웠다면 계정 자체가 사라진다 — 순서가 계약이다.
      expect(prefs.getString('user_key'), legacyKey);
    });

    test('신규 설치는 평문을 만들지 않고 보안 저장소에만 쓴다', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final secure = _FakeSecureStorage();

      final resolved = await UserService.bootstrapUserKey(
        prefs,
        secureStorage: secure,
      );

      expect(resolved.length, greaterThanOrEqualTo(10));
      expect(secure.store['user_key'], resolved);
      expect(prefs.getString('user_key'), isNull);
    });

    test('이관 후 동기 getUserKey()가 같은 키를 돌려준다', () async {
      const legacyKey = '11111111-2222-4333-8444-555555555555';
      SharedPreferences.setMockInitialValues(<String, Object>{
        'user_key': legacyKey,
      });
      final prefs = await SharedPreferences.getInstance();
      final secure = _FakeSecureStorage();

      await UserService.bootstrapUserKey(prefs, secureStorage: secure);
      final service = UserService(prefs, secureStorage: secure);

      expect(service.getUserKey(), legacyKey);
    });

    test('부트스트랩 없이 새 키가 필요해도 평문에 쓰지 않는다', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final secure = _FakeSecureStorage();
      final service = UserService(prefs, secureStorage: secure);

      final key = service.getUserKey();

      expect(key.length, greaterThanOrEqualTo(10));
      expect(
        prefs.getString('user_key'),
        isNull,
        reason: '어떤 경로로도 새 평문 자격증명이 생기면 안 된다',
      );
    });
  });

  // ════════ R0-1: iOS StoreKit1 강제 ════════

  group('R0-1 — iOS StoreKit1 강제', () {
    setUp(IapPlatformInit.resetForTest);

    test('iOS에서 enableStoreKit1을 호출한다', () async {
      // 이 호출이 없으면 storekit 0.4.8 기본값(StoreKit2) 때문에
      // serverVerificationData 가 legacy 앱 영수증이 아니라 JWS 로 나가고, 백엔드의
      // legacy /verifyReceipt 가 21002(malformed)로 **전량 실패**한다(과금됐는데 미지급).
      //
      // red-proof: main.dart 의 `await IapPlatformInit.ensureStoreKit1()` 을 지우거나
      // 이 클래스의 호출을 no-op으로 바꾸면 calls == 0 이 되어 FAIL.
      var calls = 0;
      await IapPlatformInit.ensureStoreKit1(
        isIOS: true,
        enableStoreKit1: () async {
          calls++;
          return false; // false = 더 이상 StoreKit2 아님 = SK1 적용됨
        },
      );

      expect(calls, 1);
      expect(IapPlatformInit.lastStoreKit1Applied, isTrue);
    });

    test('iOS가 아니면 호출하지 않는다(Android는 SK와 무관)', () async {
      var calls = 0;
      await IapPlatformInit.ensureStoreKit1(
        isIOS: false,
        enableStoreKit1: () async {
          calls++;
          return false;
        },
      );
      expect(calls, 0);
    });

    test('두 번 호출해도 1회만 적용한다(등록 시점 이후 재설정 방지)', () async {
      var calls = 0;
      Future<bool> enable() async {
        calls++;
        return false;
      }

      await IapPlatformInit.ensureStoreKit1(isIOS: true, enableStoreKit1: enable);
      await IapPlatformInit.ensureStoreKit1(isIOS: true, enableStoreKit1: enable);
      expect(calls, 1);
    });

    test('실패해도 예외를 던지지 않는다(결제 실패 < 앱 부팅 실패)', () async {
      await IapPlatformInit.ensureStoreKit1(
        isIOS: true,
        enableStoreKit1: () async => throw Exception('platform channel down'),
      );
      expect(IapPlatformInit.lastStoreKit1Applied, isNull);
    });

    test('main.dart 가 SharedPreferences/IAP 접근 전에 강제한다', () {
      // 순서가 load-bearing 이다: 플러그인 등록은 `InAppPurchase.instance` **첫 접근**에서
      // 일어나고, 그 시점의 플래그로 SK1/SK2 옵저버가 정해진다. 늦게 부르면 무효다.
      final source = File('lib/main.dart').readAsStringSync();
      final storeKitAt = source.indexOf('IapPlatformInit.ensureStoreKit1');
      final runAppAt = source.indexOf('runApp(');
      expect(storeKitAt, greaterThan(0), reason: 'SK1 강제 호출이 없다');
      expect(storeKitAt, lessThan(runAppAt));
    });
  });

  // ════════ R4: 부모 게이트 강화 ════════

  group('R4 — 부모 게이트', () {
    test('문제가 두 자리 덧셈이 아니다(타깃 7-9세가 풀 수 있음)', () {
      final service = ParentalControlService(random: Random(42));
      for (var i = 0; i < 200; i++) {
        final challenge = service.createChallenge();
        // 곱셈이어야 하고, 정답은 세 자리 이상(암산 난이도 확보).
        expect(challenge.prompt, contains('×'));
        expect(challenge.answer, challenge.left * challenge.right);
        expect(challenge.answer, greaterThanOrEqualTo(100));
        expect(challenge.left, greaterThanOrEqualTo(100));
        expect(challenge.right, greaterThanOrEqualTo(3));
      }
    });

    test('정답/오답 판정은 그대로 동작한다', () {
      final service = ParentalControlService(random: Random(7));
      final challenge = service.createChallenge();
      expect(service.verifyChallenge(challenge, '${challenge.answer}'), isTrue);
      expect(
        service.verifyChallenge(challenge, '${challenge.answer + 1}'),
        isFalse,
      );
      expect(service.verifyChallenge(challenge, 'abc'), isFalse);
    });

    test('시계를 되돌려도 세션이 부활하지 않는다', () async {
      // 수정 전에는 `elapsed <= 30분` 만 봤다. 시계를 과거로 돌리면 elapsed 가 음수가 되어
      // 조건을 항상 만족 → 한 번 통과한 부모 게이트가 영구 유효(아이가 결제·삭제 가능).
      //
      // red-proof: `!elapsed.isNegative &&` 를 지우면 이 테스트가 FAIL.
      final future = DateTime.now().add(const Duration(days: 1));
      SharedPreferences.setMockInitialValues(<String, Object>{
        ParentalControlService.ageGateSessionKey: future.millisecondsSinceEpoch,
      });
      final prefs = await SharedPreferences.getInstance();
      final service = ParentalControlService();

      await service.loadAgeGateSession(prefs);

      expect(service.isAgeGateVerifiedForSession, isFalse);
      expect(prefs.getInt(ParentalControlService.ageGateSessionKey), isNull);
    });

    test('정상 시간 흐름에서는 30분 내 세션이 유지된다(반대 방향 봉인)', () async {
      final recent = DateTime.now().subtract(const Duration(minutes: 5));
      SharedPreferences.setMockInitialValues(<String, Object>{
        ParentalControlService.ageGateSessionKey: recent.millisecondsSinceEpoch,
      });
      final prefs = await SharedPreferences.getInstance();
      final service = ParentalControlService();

      await service.loadAgeGateSession(prefs);

      expect(service.isAgeGateVerifiedForSession, isTrue);
    });

    test('만료된 세션은 그대로 무효화된다', () async {
      final old = DateTime.now().subtract(const Duration(hours: 2));
      SharedPreferences.setMockInitialValues(<String, Object>{
        ParentalControlService.ageGateSessionKey: old.millisecondsSinceEpoch,
      });
      final prefs = await SharedPreferences.getInstance();
      final service = ParentalControlService();

      await service.loadAgeGateSession(prefs);

      expect(service.isAgeGateVerifiedForSession, isFalse);
    });
  });

  // ════════ R4: Android 백업 제외 ════════

  group('M1 — Android 백업 제외', () {
    test('AndroidManifest 가 allowBackup=false 이고 추출 규칙을 지정한다', () {
      final manifest =
          File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
      expect(manifest, contains('android:allowBackup="false"'));
      expect(
        manifest,
        contains('android:dataExtractionRules="@xml/data_extraction_rules"'),
      );
    });

    test('data_extraction_rules 가 백업·기기이전 양쪽을 제외한다', () {
      final rules =
          File('android/app/src/main/res/xml/data_extraction_rules.xml')
              .readAsStringSync();
      expect(rules, contains('<cloud-backup>'));
      expect(rules, contains('<device-transfer>'));
      // Android 12+ 는 이 파일을 쓰고 그 이하는 allowBackup 을 쓴다 — 두 경로 모두 닫아야 한다.
      expect('<exclude domain="sharedpref" />'.allMatches(rules).length, 2);
    });
  });
}
