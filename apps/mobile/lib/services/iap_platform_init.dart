import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';

/// Store selection before the first InAppPurchase.instance access.
///
/// The production app uses the maintained StoreKit 2 default. The backend now
/// verifies its signed JWS transactions using Apple's official server library.
/// The legacy opt-in below is retained for diagnostic compatibility tests only.
class IapPlatformInit {
  const IapPlatformInit._();

  static bool _done = false;

  /// 마지막 초기화에서 StoreKit1이 실제로 적용됐는지(관측·테스트용).
  static bool? lastStoreKit1Applied;

  /// StoreKit 2 is supported by the backend; new app sessions use the maintained
  /// plugin default. [ensureStoreKit1] remains only for legacy diagnostic tests.
  static void useStoreKitDefault() {
    _done = true;
    lastStoreKit1Applied = false;
  }

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

    final enable =
        // ignore: deprecated_member_use
        enableStoreKit1 ?? InAppPurchaseStoreKitPlatform.enableStoreKit1;
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
