import 'dart:async';

import 'package:in_app_purchase/in_app_purchase.dart';

class IapService {
  IapService({InAppPurchase? inAppPurchase})
      : _iap = inAppPurchase ?? InAppPurchase.instance;

  final InAppPurchase _iap;

  Stream<List<PurchaseDetails>> get purchaseStream => _iap.purchaseStream;

  Future<bool> isAvailable() async {
    return _iap.isAvailable();
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
