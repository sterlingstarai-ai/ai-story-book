import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

class RewardedAdService {
  const RewardedAdService();

  String get _adUnitId {
    if (kDebugMode) {
      // Google 공식 테스트 광고 유닛
      if (Platform.isIOS) {
        return 'ca-app-pub-3940256099942544/1712485313';
      }
      return 'ca-app-pub-3940256099942544/5224354917';
    }

    if (Platform.isIOS) {
      const configured = String.fromEnvironment(
        'ADMOB_REWARDED_AD_UNIT_IOS',
      );
      if (configured.isNotEmpty) {
        return configured;
      }
    } else if (Platform.isAndroid) {
      const configured = String.fromEnvironment(
        'ADMOB_REWARDED_AD_UNIT_ANDROID',
      );
      if (configured.isNotEmpty) {
        return configured;
      }
    }

    // 릴리스에서 미설정 시 테스트 유닛으로 폴백해 크래시를 방지한다.
    if (Platform.isIOS) {
      return 'ca-app-pub-3940256099942544/1712485313';
    }
    return 'ca-app-pub-3940256099942544/5224354917';
  }

  Future<bool> showRewardedAd() async {
    if (!Platform.isAndroid && !Platform.isIOS) {
      return false;
    }

    final completer = Completer<bool>();
    RewardedAd.load(
      adUnitId: _adUnitId,
      request: const AdRequest(),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) {
          var rewarded = false;

          ad.fullScreenContentCallback = FullScreenContentCallback(
            onAdDismissedFullScreenContent: (ad) {
              ad.dispose();
              if (!completer.isCompleted) {
                completer.complete(rewarded);
              }
            },
            onAdFailedToShowFullScreenContent: (ad, _) {
              ad.dispose();
              if (!completer.isCompleted) {
                completer.complete(false);
              }
            },
          );

          ad.show(
            onUserEarnedReward: (_, __) {
              rewarded = true;
            },
          );
        },
        onAdFailedToLoad: (_) {
          if (!completer.isCompleted) {
            completer.complete(false);
          }
        },
      ),
    );

    return completer.future;
  }
}
