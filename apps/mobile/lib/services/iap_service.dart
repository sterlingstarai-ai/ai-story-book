import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';

import 'service_availability.dart';

class IapService {
  IapService({
    InAppPurchase? inAppPurchase,
    Future<void> Function(PurchaseDetails)? androidConsume,
  })  : _iap = inAppPurchase ?? InAppPurchase.instance,
        _androidConsume = androidConsume;

  final InAppPurchase _iap;

  // Android 소모성 소비(consume)의 테스트 시임 — 미주입 시 실제 플랫폼 애드온을 사용.
  final Future<void> Function(PurchaseDetails)? _androidConsume;

  Stream<List<PurchaseDetails>> get purchaseStream => _iap.purchaseStream;

  bool get isConfigured => Platform.isIOS || Platform.isAndroid;

  String? get unavailableReason {
    if (!isConfigured) {
      return '인앱결제는 iOS/Android에서만 지원됩니다.';
    }
    return null;
  }

  Future<ServiceAvailability> checkAvailability() async {
    final reason = unavailableReason;
    if (reason != null) {
      return ServiceAvailability.unsupported(reason);
    }
    final available = await _iap.isAvailable();
    if (!available) {
      return const ServiceAvailability.unavailable(
        '스토어 결제를 현재 사용할 수 없습니다.',
      );
    }
    return const ServiceAvailability.available();
  }

  Future<bool> isAvailable() async {
    return (await checkAvailability()).isAvailable;
  }

  Future<List<ProductDetails>> loadProducts(Set<String> productIds) async {
    final response = await _iap.queryProductDetails(productIds);
    if (response.error != null) {
      throw Exception(response.error!.message);
    }
    return response.productDetails;
  }

  Future<void> buyProduct(
    ProductDetails product, {
    bool consumable = false,
  }) async {
    final param = PurchaseParam(productDetails: product);
    if (consumable) {
      // autoConsume:false — 서버 영수증 검증 성공 후에만 소비/완료한다. 검증 실패 시
      // 트랜잭션을 pending으로 유지해 다음 실행에서 재검증되게 하여 대금 유실을 막는다(C3).
      await _iap.buyConsumable(purchaseParam: param, autoConsume: false);
      return;
    }
    await _iap.buyNonConsumable(purchaseParam: param);
  }

  Future<void> restorePurchases() async {
    await _iap.restorePurchases();
  }

  Future<void> completePurchase(PurchaseDetails purchase) async {
    if (purchase.pendingCompletePurchase) {
      await _iap.completePurchase(purchase);
    }
  }

  /// 서버 영수증 검증 성공 후에만 호출해 스토어 트랜잭션을 마무리한다.
  ///
  /// - Android + 소모성: [InAppPurchaseAndroidPlatformAddition.consumePurchase]를 호출한다.
  ///   completePurchase(acknowledge-only)만으로는 소비가 되지 않아 같은 SKU 재구매가
  ///   ITEM_ALREADY_OWNED로 영구 실패한다(핸드오프 정정 B1).
  /// - 그 외(iOS, 구독 등): completePurchase(acknowledge).
  Future<void> finishPurchase(
    PurchaseDetails purchase, {
    required bool consumable,
  }) async {
    if (defaultTargetPlatform == TargetPlatform.android && consumable) {
      final consume = _androidConsume ?? _defaultAndroidConsume;
      await consume(purchase);
      return;
    }
    await completePurchase(purchase);
  }

  Future<void> _defaultAndroidConsume(PurchaseDetails purchase) async {
    final android =
        _iap.getPlatformAddition<InAppPurchaseAndroidPlatformAddition>();
    await android.consumePurchase(purchase);
  }
}
