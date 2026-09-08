import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:ai_story_book/services/iap_purchase_recovery.dart';
import 'package:ai_story_book/services/iap_service.dart';

class Store extends IapService {
  Store() : super(inAppPurchase: NoopStore());
  final events = StreamController<List<PurchaseDetails>>.broadcast();
  int finished = 0;
  @override
  Stream<List<PurchaseDetails>> get purchaseStream => events.stream;
  @override
  Future<void> finishPurchase(
    PurchaseDetails purchase, {
    required bool consumable,
  }) async {
    finished++;
  }
}

class NoopStore implements InAppPurchase {
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

PurchaseDetails purchase() => PurchaseDetails(
  purchaseID: 'store-tx',
  productID: 'credit_pack_1',
  transactionDate: null,
  status: PurchaseStatus.purchased,
  verificationData: PurchaseVerificationData(
    localVerificationData: '',
    serverVerificationData: 'receipt',
    source: 'test',
  ),
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => debugDefaultTargetPlatformOverride = TargetPlatform.iOS);
  tearDown(() => debugDefaultTargetPlatformOverride = null);

  test(
    'startup listener delivers a pending purchase without opening credits UI',
    () async {
      final store = Store();
      var verified = 0;
      final delivered = Completer<void>();
      final recovery = IapPurchaseRecovery(
        iap: store,
        verify: (_) async {
          verified++;
          return {'status': 'verified'};
        },
        onDelivered: () => delivered.complete(),
      );
      recovery.start();
      store.events.add([purchase()]);
      await delivered.future;
      expect(verified, 1);
      expect(store.finished, 1);
      recovery.dispose();
      await store.events.close();
    },
  );

  test(
    'resume retries failed delivery and never acknowledges before success',
    () async {
      final store = Store();
      var fail = true;
      var calls = 0;
      final delivered = Completer<void>();
      final recovery = IapPurchaseRecovery(
        iap: store,
        verify: (_) async {
          calls++;
          if (fail) throw StateError('offline');
          return {'status': 'verified'};
        },
        onDelivered: () => delivered.complete(),
      );
      recovery.start();
      store.events.add([purchase()]);
      await Future<void>.delayed(Duration.zero);
      expect(store.finished, 0);
      fail = false;
      recovery.retryPending();
      await delivered.future;
      expect(calls, 2);
      expect(store.finished, 1);
      recovery.dispose();
      await store.events.close();
    },
  );

  test(
    'screen and startup listener share one verification and one completion',
    () async {
      final store = Store();
      final gate = Completer<Map<String, dynamic>>();
      var calls = 0;
      Future<Map<String, dynamic>> verify(Map<String, dynamic> _) {
        calls++;
        return gate.future;
      }

      final first = store.verifyAndFinish(purchase(), verify: verify);
      final second = store.verifyAndFinish(purchase(), verify: verify);
      gate.complete({'status': 'verified'});
      await Future.wait([first, second]);
      expect(calls, 1);
      expect(store.finished, 1);
      // A later restore still rechecks account entitlement, without consuming twice.
      await store.verifyAndFinish(purchase(), verify: verify);
      expect(calls, 2);
      expect(store.finished, 1);
      await store.events.close();
    },
  );

  test(
    'unexpected success envelope does not finish a paid transaction',
    () async {
      final store = Store();
      await expectLater(
        store.verifyAndFinish(
          purchase(),
          verify: (_) async => {'status': 'pending'},
        ),
        throwsStateError,
      );
      expect(store.finished, 0);
      await store.events.close();
    },
  );
}
