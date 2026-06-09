import 'dart:async';
import 'dart:io';

import 'package:in_app_purchase/in_app_purchase.dart';

import 'service_availability.dart';

class IapService {
  IapService({InAppPurchase? inAppPurchase})
      : _iap = inAppPurchase ?? InAppPurchase.instance;

  final InAppPurchase _iap;

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
      await _iap.buyConsumable(purchaseParam: param, autoConsume: true);
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
}
