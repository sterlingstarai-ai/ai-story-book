import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/credits_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/iap_service.dart';
import 'package:ai_story_book/services/service_availability.dart';

// C3 — IAP 검증 실패 시 finally에서 completePurchase 무조건 호출 → 소모성 대금 영구 유실.
// 검증 성공 후에만 마무리(Android는 consume, 정정 B1)하도록 회귀 방지한다.

PurchaseDetails _purchased(String id, String product) => PurchaseDetails(
      purchaseID: id,
      productID: product,
      verificationData: PurchaseVerificationData(
        localVerificationData: 'local',
        serverVerificationData: 'server',
        source: 'test',
      ),
      transactionDate: null,
      status: PurchaseStatus.purchased,
    )..pendingCompletePurchase = true;

/// R0-2: purchaseID 가 없는 구매 이벤트(스토어가 식별자를 아직 못 준 상태).
PurchaseDetails _purchasedWithoutId(String product) => PurchaseDetails(
      purchaseID: null,
      productID: product,
      verificationData: PurchaseVerificationData(
        localVerificationData: 'local',
        serverVerificationData: 'server',
        source: 'test',
      ),
      transactionDate: null,
      status: PurchaseStatus.purchased,
    )..pendingCompletePurchase = true;

ProductDetails _product(String id) => ProductDetails(
      id: id,
      title: 'title',
      description: 'desc',
      price: '\$1',
      rawPrice: 1.0,
      currencyCode: 'USD',
    );

/// InAppPurchase 인터페이스를 만족하는 no-op(스파이가 실제로 호출하지 않는 경로용).
class _NoopIap implements InAppPurchase {
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

/// buyConsumable(autoConsume)·completePurchase를 기록하는 fake InAppPurchase.
class _RecordingIap implements InAppPurchase {
  bool? lastAutoConsume;
  int completeCalls = 0;
  int buyNonConsumableCalls = 0;

  @override
  Future<bool> buyConsumable({
    required PurchaseParam purchaseParam,
    bool autoConsume = true,
  }) async {
    lastAutoConsume = autoConsume;
    return true;
  }

  @override
  Future<bool> buyNonConsumable({required PurchaseParam purchaseParam}) async {
    buyNonConsumableCalls++;
    return true;
  }

  @override
  Future<void> completePurchase(PurchaseDetails purchase) async {
    completeCalls++;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

/// 화면 제어흐름 테스트용 스파이 — finishPurchase/completePurchase 호출과 스트림을 제어.
class _SpyIapService extends IapService {
  _SpyIapService() : super(inAppPurchase: _NoopIap());

  final StreamController<List<PurchaseDetails>> controller =
      StreamController<List<PurchaseDetails>>.broadcast();
  int finishCalls = 0;
  int completeCalls = 0;
  bool? lastConsumable;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => controller.stream;

  @override
  Future<ServiceAvailability> checkAvailability() async =>
      const ServiceAvailability.available();

  @override
  Future<void> finishPurchase(
    PurchaseDetails purchase, {
    required bool consumable,
  }) async {
    finishCalls++;
    lastConsumable = consumable;
  }

  @override
  Future<void> completePurchase(PurchaseDetails purchase) async {
    completeCalls++;
  }
}

class _FakeApiClient extends ApiClient {
  _FakeApiClient({this.verifyThrows = false})
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  final bool verifyThrows;
  int verifyCalls = 0;

  @override
  Future<Map<String, dynamic>> verifyIap(Map<String, dynamic> payload) async {
    verifyCalls++;
    if (verifyThrows) {
      throw Exception('verify failed');
    }
    return <String, dynamic>{'status': 'verified'};
  }

  @override
  Future<Map<String, dynamic>> getCreditsStatus() async =>
      <String, dynamic>{'credits': 3, 'subscription': null};

  @override
  Future<List<dynamic>> getTransactions({int limit = 20, int offset = 0}) async =>
      <dynamic>[];
}

Widget _harness({
  required SharedPreferences prefs,
  required IapService iap,
  required ApiClient api,
}) {
  return ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      iapServiceProvider.overrideWithValue(iap),
      apiClientProvider.overrideWithValue(api),
    ],
    // route != '/credits' → age gate 스킵, _loadCreditsStatus만 수행.
    child: const MaterialApp(
      locale: Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: CreditsScreen(),
    ),
  );
}

void main() {
  // ---- IapService 단위: 소모성 autoConsume:false ----
  test('buyProduct(consumable:true) uses autoConsume:false', () async {
    final iap = _RecordingIap();
    final service = IapService(inAppPurchase: iap);
    await service.buyProduct(_product('credit_pack_1'), consumable: true);
    expect(iap.lastAutoConsume, isFalse);
  });

  test('buyProduct(consumable:false) uses buyNonConsumable', () async {
    final iap = _RecordingIap();
    final service = IapService(inAppPurchase: iap);
    await service.buyProduct(_product('subscription_basic'), consumable: false);
    expect(iap.buyNonConsumableCalls, 1);
    expect(iap.lastAutoConsume, isNull);
  });

  // ---- IapService 단위: finishPurchase 플랫폼 라우팅 ----
  test('finishPurchase on iOS completes (no android consume)', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final iap = _RecordingIap();
    var consumed = 0;
    final service = IapService(
      inAppPurchase: iap,
      androidConsume: (_) async => consumed++,
    );
    await service.finishPurchase(_purchased('t', 'credit_pack_1'),
        consumable: true);
    expect(iap.completeCalls, 1);
    expect(consumed, 0);
  });

  test('finishPurchase on Android consumable calls consume (not complete)',
      () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final iap = _RecordingIap();
    var consumed = 0;
    final service = IapService(
      inAppPurchase: iap,
      androidConsume: (_) async => consumed++,
    );
    await service.finishPurchase(_purchased('t', 'credit_pack_1'),
        consumable: true);
    expect(consumed, 1);
    expect(iap.completeCalls, 0);
  });

  test('finishPurchase on Android non-consumable completes (not consume)',
      () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final iap = _RecordingIap();
    var consumed = 0;
    final service = IapService(
      inAppPurchase: iap,
      androidConsume: (_) async => consumed++,
    );
    await service.finishPurchase(_purchased('t', 'subscription_basic'),
        consumable: false);
    expect(consumed, 0);
    expect(iap.completeCalls, 1);
  });

  // ---- 화면 제어흐름: 검증 실패 시 마무리하지 않음(대금 유실 방지) ----
  testWidgets('verifyIap failure does NOT finish purchase (stays pending)',
      (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final prefs = await SharedPreferences.getInstance();
    final spy = _SpyIapService();
    addTearDown(spy.controller.close);
    final api = _FakeApiClient(verifyThrows: true);

    await tester.pumpWidget(_harness(prefs: prefs, iap: spy, api: api));
    await tester.pump();

    spy.controller.add([_purchased('tx-fail', 'credit_pack_1')]);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(api.verifyCalls, 1);
    expect(spy.finishCalls, 0); // 검증 실패 → 마무리 안 함
    expect(spy.completeCalls, 0);
  });

  testWidgets('verifyIap success finishes purchase once (consumable)',
      (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final prefs = await SharedPreferences.getInstance();
    final spy = _SpyIapService();
    addTearDown(spy.controller.close);
    final api = _FakeApiClient(verifyThrows: false);

    await tester.pumpWidget(_harness(prefs: prefs, iap: spy, api: api));
    await tester.pump();

    spy.controller.add([_purchased('tx-ok', 'credit_pack_1')]);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(api.verifyCalls, 1);
    expect(spy.finishCalls, 1);
    expect(spy.lastConsumable, isTrue); // 크레딧팩 = 소모성
  });

  // ═════════════ R0 (2026-08-17 보안감사 🔴C1): iOS 결제 전량 파손 ═════════════

  testWidgets(
      'R0-2: purchaseID 부재 시 가짜 id를 만들지 않고 검증을 보류한다',
      (tester) async {
    // 수정 전에는 `purchase.purchaseID ?? "\${productID}-\${now.ms}"` 로 **시간 기반 가짜
    // transaction_id** 를 만들어 서버로 보냈다. 재시도마다 값이 달라지므로
    //  · Apple: 그 id가 영수증의 어떤 거래와도 매칭되지 않아 영구 검증 실패
    //  · Google: 서버 dedup 키가 매번 달라져 **이중 지급** 여지
    // 즉 멱등성이 파괴된다. 식별자가 없으면 아무것도 보내지 않고 pending 을 유지해야 한다.
    //
    // red-proof: credits_screen 의 `if (transactionId == null || isEmpty) return;` 을
    // 지우고 옛 `??` 폴백을 되돌리면 verifyCalls == 1 이 되어 FAIL.
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final prefs = await SharedPreferences.getInstance();
    final spy = _SpyIapService();
    addTearDown(spy.controller.close);
    final api = _FakeApiClient(verifyThrows: false);

    await tester.pumpWidget(_harness(prefs: prefs, iap: spy, api: api));
    await tester.pump();

    spy.controller.add([_purchasedWithoutId('credit_pack_1')]);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(api.verifyCalls, 0, reason: '가짜 id로 서버 검증을 시도했다(멱등성 파괴)');
    // 마무리도 하지 않는다 — 마무리하면 미지급 상태로 대금이 영구 유실된다.
    expect(spy.finishCalls, 0);
    expect(spy.completeCalls, 0);
  });

  testWidgets('R0-2: purchaseID 가 빈 문자열이어도 동일하게 보류한다',
      (tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final prefs = await SharedPreferences.getInstance();
    final spy = _SpyIapService();
    addTearDown(spy.controller.close);
    final api = _FakeApiClient(verifyThrows: false);

    await tester.pumpWidget(_harness(prefs: prefs, iap: spy, api: api));
    await tester.pump();

    spy.controller.add([_purchased('', 'credit_pack_1')]);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(api.verifyCalls, 0);
    expect(spy.finishCalls, 0);
  });
}
