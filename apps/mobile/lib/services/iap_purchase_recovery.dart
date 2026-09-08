import 'dart:async';

import 'package:in_app_purchase/in_app_purchase.dart';

import 'iap_service.dart';

/// Listen for unfinished store transactions as soon as account bootstrap ends.
/// A failed verification remains pending at the store and is retried on resume;
/// no receipt/token is copied to preferences or logs.
class IapPurchaseRecovery {
  IapPurchaseRecovery({
    required this.iap,
    required this.verify,
    this.onDelivered,
  });

  final IapService iap;
  final Future<Map<String, dynamic>> Function(Map<String, dynamic>) verify;
  final void Function()? onDelivered;
  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Map<String, PurchaseDetails> _pending = {};
  bool _disposed = false;

  void start() {
    if (_subscription != null || _disposed) return;
    try {
      _subscription = iap.purchaseStream.listen(
        (purchases) {
          for (final purchase in purchases) {
            if (purchase.status != PurchaseStatus.purchased &&
                purchase.status != PurchaseStatus.restored) {
              continue;
            }
            final id = purchase.purchaseID;
            if (id == null || id.isEmpty) continue;
            _pending[id] = purchase;
            unawaited(_deliver(purchase));
          }
        },
        onError: (Object _) {
          // Keep pending store transactions intact; resume retries delivery.
        },
      );
    } catch (_) {
      // Desktop/headless tests have no native store plugin.
    }
  }

  Future<void> _deliver(PurchaseDetails purchase) async {
    if (_disposed) return;
    try {
      final result = await iap.verifyAndFinish(purchase, verify: verify);
      if (result != null) {
        _pending.remove(purchase.purchaseID);
        if (!_disposed) onDelivered?.call();
      }
    } catch (_) {
      // Store acknowledgement happens only after successful server delivery.
    }
  }

  void retryPending() {
    start();
    for (final purchase in _pending.values.toList()) {
      unawaited(_deliver(purchase));
    }
  }

  void dispose() {
    _disposed = true;
    unawaited(_subscription?.cancel());
    _pending.clear();
  }
}
