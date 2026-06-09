import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../core/app_telemetry.dart';

enum RewardedAdStatus {
  rewarded,
  dismissed,
  unavailable,
  misconfigured,
  loadFailed,
}

class RewardedAdResult {
  const RewardedAdResult({
    required this.status,
    this.reason,
    this.adUnitId,
  });

  final RewardedAdStatus status;
  final String? reason;
  final String? adUnitId;

  bool get rewarded => status == RewardedAdStatus.rewarded;
}

class RewardedAdService {
  const RewardedAdService();

  String? get configuredAdUnitId {
    if (kDebugMode) {
      if (Platform.isIOS) {
        return 'ca-app-pub-3940256099942544/1712485313';
      }
      if (Platform.isAndroid) {
        return 'ca-app-pub-3940256099942544/5224354917';
      }
      return null;
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
    return null;
  }

  bool get isConfigured => configuredAdUnitId != null;

  String? get unavailableReason {
    if (!Platform.isAndroid && !Platform.isIOS) {
      return '리워드 광고는 iOS/Android에서만 지원됩니다.';
    }
    if (!isConfigured) {
      return '리워드 광고 유닛이 설정되지 않았습니다.';
    }
    return null;
  }

  Future<RewardedAdResult> showRewardedAd() async {
    final reason = unavailableReason;
    if (reason != null) {
      final status = (!Platform.isAndroid && !Platform.isIOS)
          ? RewardedAdStatus.unavailable
          : RewardedAdStatus.misconfigured;
      AppTelemetry.logInfo(
        'rewarded_ad_unavailable',
        data: {
          'status': status.name,
          'reason': reason,
        },
      );
      return RewardedAdResult(status: status, reason: reason);
    }

    final adUnitId = configuredAdUnitId!;
    final completer = Completer<RewardedAdResult>();
    RewardedAd.load(
      adUnitId: adUnitId,
      request: const AdRequest(),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) {
          var rewarded = false;

          ad.fullScreenContentCallback = FullScreenContentCallback(
            onAdDismissedFullScreenContent: (ad) {
              ad.dispose();
              if (!completer.isCompleted) {
                completer.complete(
                  RewardedAdResult(
                    status: rewarded
                        ? RewardedAdStatus.rewarded
                        : RewardedAdStatus.dismissed,
                    adUnitId: adUnitId,
                  ),
                );
              }
            },
            onAdFailedToShowFullScreenContent: (ad, _) {
              ad.dispose();
              if (!completer.isCompleted) {
                completer.complete(
                  RewardedAdResult(
                    status: RewardedAdStatus.loadFailed,
                    reason: '광고를 표시하지 못했습니다.',
                    adUnitId: adUnitId,
                  ),
                );
              }
            },
          );

          ad.show(
            onUserEarnedReward: (_, __) {
              rewarded = true;
            },
          );
        },
        onAdFailedToLoad: (error) {
          AppTelemetry.logInfo(
            'rewarded_ad_load_failed',
            data: {
              'adUnitId': adUnitId,
              'code': error.code,
              'message': error.message,
            },
          );
          if (!completer.isCompleted) {
            completer.complete(
              RewardedAdResult(
                status: RewardedAdStatus.loadFailed,
                reason: '광고를 불러오지 못했습니다.',
                adUnitId: adUnitId,
              ),
            );
          }
        },
      ),
    );

    return completer.future;
  }
}
