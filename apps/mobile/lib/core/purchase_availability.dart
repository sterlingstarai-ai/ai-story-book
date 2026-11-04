import 'package:flutter/foundation.dart';

enum CreditsFocus { creditPacks }

bool purchasesSupportedForPlatform(
  Map<String, dynamic> capabilities, {
  required TargetPlatform platform,
  bool isWeb = false,
}) {
  if (isWeb || capabilities['purchases_supported'] != true) return false;
  return switch (platform) {
    TargetPlatform.iOS => capabilities['apple_purchases_supported'] == true,
    TargetPlatform.android =>
      capabilities['google_purchases_supported'] == true,
    _ => false,
  };
}
