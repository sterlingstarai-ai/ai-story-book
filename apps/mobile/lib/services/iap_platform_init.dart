import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';

/// R0 (🔴 C1, 2026-08-17 보안감사): iOS 결제 전량 파손 언블록.
///
/// **증상.** `in_app_purchase_storekit` 0.4.8부터 "StoreKit 2 is now the default for all
/// devices that support it"(CHANGELOG:59)다. StoreKit2 경로에서
/// `purchase.verificationData.serverVerificationData` 는 base64 앱 영수증이 아니라
/// **JWS(서명된 트랜잭션 JWT)** 다. 앱은 그 값을 `receipt_data` 로 보내고, 백엔드는
/// legacy `/verifyReceipt` 로 포워드한다 → Apple이 status 21002(malformed)를 반환 →
/// strict 모드(운영 기본)에서 검증 실패 → **크레딧 미지급**. 결제는 OS가 이미 캡처했고,
/// 앱은 서버 검증 성공 후에만 트랜잭션을 finish하므로 **과금된 채 pending 영구 정체**가
/// 된다(재실행마다 같은 JWS를 재전송해 같은 실패 반복).
///
/// **이 파일의 역할.** iOS에서 StoreKit1을 명시적으로 되돌려
/// `serverVerificationData` 를 legacy 앱 영수증으로 복귀시킨다 → **백엔드 무변경으로 즉시
/// 정합**. 반드시 `InAppPurchase.instance` 에 **처음 접근하기 전**에 호출해야 한다:
/// 플러그인 등록(`InAppPurchaseStoreKitPlatform.registerPlatform()`)은 그 첫 접근에서
/// 일어나고, 등록 시점의 플래그로 SK1/SK2 옵저버가 결정되기 때문이다.
///
/// **임시책임을 명시한다.** Apple은 legacy verifyReceipt를 sunset 중이다. 정공법은 백엔드를
/// App Store Server API + JWS 서명 검증으로 이관하는 것이며, 후속 티켓(R0-3)으로 남겼다.
class IapPlatformInit {
  const IapPlatformInit._();

  static bool _done = false;

  /// 마지막 초기화에서 StoreKit1이 실제로 적용됐는지(관측·테스트용).
  static bool? lastStoreKit1Applied;

  /// 앱 부트에서 1회 호출. iOS가 아니면 no-op.
  ///
  /// 실패해도 앱 부팅을 막지 않는다 — 결제만 못 하는 것과 앱이 안 켜지는 것은 피해가
  /// 다르다. 다만 조용히 넘기지 않고 [lastStoreKit1Applied] 와 로그로 남긴다.
  static Future<void> ensureStoreKit1({
    Future<bool> Function()? enableStoreKit1,
    bool? isIOS,
  }) async {
    if (_done) {
      return;
    }
    final onIOS = isIOS ?? (!kIsWeb && Platform.isIOS);
    if (!onIOS) {
      _done = true;
      return;
    }

    // ignore: deprecated_member_use — SK1 복귀는 의도된 임시책(R0-1). SK2 전환은 R0-3.
    final enable = enableStoreKit1 ?? InAppPurchaseStoreKitPlatform.enableStoreKit1;
    try {
      // 반환값은 '이후에도 StoreKit2를 쓰는가'다. 즉 StoreKit2 미지원 기기(iOS<15)에서는
      // true 가 돌아올 수 있다 — 그 기기는 애초에 SK2 JWS 문제가 없으므로 정합하다.
      final stillStoreKit2 = await enable();
      lastStoreKit1Applied = !stillStoreKit2;
    } catch (error, stack) {
      lastStoreKit1Applied = null;
      debugPrint('StoreKit1 강제 실패(결제가 실패할 수 있음): $error\n$stack');
    } finally {
      _done = true;
    }
  }

  @visibleForTesting
  static void resetForTest() {
    _done = false;
    lastStoreKit1Applied = null;
  }
}
