import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';
import '../widgets/common_widgets.dart';

/// M15: 구독 플랜명을 안정 키(plan id)로 로컬라이즈한다. 서버는 한국어 name을
/// 내려주지만(하위호환) en/ja 사용자에게 '베이직' 등을 노출하지 않도록 id→l10n.
String localizedPlanName(
  AppLocalizations l,
  String planId,
  String fallback,
) {
  switch (planId) {
    case 'free':
      return l.planFree;
    case 'basic':
      return l.planBasic;
    case 'premium':
      return l.planPremium;
    default:
      return fallback;
  }
}

/// M15: 플랜 features를 로컬라이즈. arb에는 '|' 구분 문자열로 저장하고 분리한다.
/// 매핑 없는 플랜은 서버 features로 폴백(하위호환).
List<String> localizedPlanFeatures(
  AppLocalizations l,
  String planId,
  List<String> fallback,
) {
  String? joined;
  switch (planId) {
    case 'free':
      joined = l.planFeaturesFree;
      break;
    case 'basic':
      joined = l.planFeaturesBasic;
      break;
    case 'premium':
      joined = l.planFeaturesPremium;
      break;
  }
  if (joined == null || joined.isEmpty) {
    return fallback;
  }
  return joined
      .split('|')
      .map((s) => s.trim())
      .where((s) => s.isNotEmpty)
      .toList();
}

/// 크레딧 및 구독 화면
class CreditsScreen extends ConsumerStatefulWidget {
  const CreditsScreen({super.key});

  @override
  ConsumerState<CreditsScreen> createState() => _CreditsScreenState();
}

class _CreditsScreenState extends ConsumerState<CreditsScreen> {
  static const Map<String, String> _subscriptionProductMap = {
    'basic': 'subscription_basic',
    'premium': 'subscription_premium',
  };
  static const Map<String, int> _creditPackProducts = {
    'credit_pack_1': 1,
    'credit_pack_5': 5,
    'credit_pack_10': 10,
  };

  bool _isLoading = true;
  Map<String, dynamic>? _creditsStatus;
  List<dynamic> _transactions = [];
  final GlobalKey _plansSectionKey = GlobalKey();
  StreamSubscription<List<PurchaseDetails>>? _purchaseSubscription;
  final Set<String> _verifyingTransactions = <String>{};

  @override
  void initState() {
    super.initState();
    _attachPurchaseListener();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _guardWithAgeGate();
    });
  }

  @override
  void dispose() {
    _purchaseSubscription?.cancel();
    super.dispose();
  }

  void _attachPurchaseListener() {
    try {
      final iapService = ref.read(iapServiceProvider);
      _purchaseSubscription = iapService.purchaseStream.listen(
        (purchases) {
          for (final purchase in purchases) {
            _handlePurchaseUpdate(purchase);
          }
        },
      );
    } catch (_) {
      // 테스트/미지원 플랫폼에서는 IAP 리스너를 생략한다.
    }
  }

  Future<void> _guardWithAgeGate() async {
    final routeName = ModalRoute.of(context)?.settings.name;
    if (routeName != '/credits') {
      await _loadCreditsStatus();
      return;
    }

    final parental = ref.read(parentalControlServiceProvider);
    if (!parental.isAgeGateVerifiedForSession) {
      final passed = await showAgeGateDialog(context, ref);
      if (!passed) {
        if (mounted) {
          Navigator.pop(context);
        }
        return;
      }
    }
    await _loadCreditsStatus();
  }

  Future<void> _loadCreditsStatus() async {
    setState(() => _isLoading = true);
    try {
      final apiClient = ref.read(apiClientProvider);
      final status = await apiClient.getCreditsStatus();
      final transactions = await apiClient.getTransactions();

      if (mounted) {
        setState(() {
          _creditsStatus = status;
          _transactions = transactions;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsLoadError)),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l.creditsTitle),
        backgroundColor: AppColors.surface,
        actions: [
          // Apple 3.1.1: 구독/비소모성 상품 앱은 '구매 복원' 필수(기기 변경·재설치 대응).
          TextButton(
            key: const Key('restore_purchases_btn'),
            onPressed: _restorePurchases,
            child: Text(l.creditsRestorePurchases),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadCreditsStatus,
              child: SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildCreditsCard(),
                    const SizedBox(height: AppSpacing.lg),
                    _buildSubscriptionCard(),
                    const SizedBox(height: AppSpacing.lg),
                    _buildPlansSection(),
                    const SizedBox(height: AppSpacing.lg),
                    _buildCreditPackSection(),
                    const SizedBox(height: AppSpacing.lg),
                    _buildTransactionsSection(),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildCreditsCard() {
    final l = AppLocalizations.of(context);
    final credits = _asMap(_creditsStatus?['credits']);
    final currentCredits = _parseAmount(credits['credits']);
    final totalUsed = _parseAmount(credits['total_used']);

    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [AppColors.primary, Color(0xFF5B4CCC)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                l.creditsMyCredits,
                style: const TextStyle(
                  color: Colors.white70,
                  fontSize: 14,
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: AppColors.whiteOverlay,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  l.creditsTotalCreated(totalUsed),
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '$currentCredits',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 48,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 8, left: 4),
                child: Text(
                  l.creditsUnit,
                  style: const TextStyle(
                    color: Colors.white70,
                    fontSize: 16,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _scrollToPlans,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white70),
                  ),
                  child: Text(l.creditsBuyCredits),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSubscriptionCard() {
    final l = AppLocalizations.of(context);
    final subscription = _asMap(_creditsStatus?['subscription']);
    final subscriptionStatus =
        (_coerceText(subscription['status']) ?? 'active').toLowerCase();
    final isCancelled = subscriptionStatus == 'cancelled';
    final badgeColor = isCancelled ? AppColors.warning : AppColors.success;
    final badgeBackground =
        isCancelled ? AppColors.warningLight : AppColors.successLight;
    final badgeText =
        isCancelled ? l.creditsBadgeCancelScheduled : l.creditsBadgeActive;

    if (subscription.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.card_membership,
                    color: AppColors.textSecondary),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  l.creditsSubscriptionInfo,
                  style: AppTextStyles.heading3,
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              l.creditsNoActivePlan,
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.md),
            PrimaryButton(
              text: l.creditsStartSubscription,
              onPressed: () => _scrollToPlans(),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.primaryStrong),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.card_membership, color: AppColors.primary),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    l.creditsPlanSubscriptionLabel(
                        _coerceText(subscription['plan_name']) ??
                            l.creditsDefaultPlanName),
                    style: AppTextStyles.heading3,
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: badgeBackground,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  badgeText,
                  style: TextStyle(
                    color: badgeColor,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              _buildSubscriptionInfo(
                l.creditsMonthlyCredits,
                l.creditsCreditCount(
                    _parseAmount(subscription['credits_per_month'])),
              ),
              const SizedBox(width: AppSpacing.lg),
              _buildSubscriptionInfo(
                l.creditsNextRenewal,
                _formatDate(subscription['current_period_end']),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: _asList(subscription['features'])
                .map((f) => Chip(
                      label: Text(f.toString(),
                          style: const TextStyle(fontSize: 12)),
                      backgroundColor: AppColors.primaryLight,
                    ))
                .toList(),
          ),
          if (isCancelled) ...[
            const SizedBox(height: AppSpacing.md),
            Text(
              l.creditsCancelNotice,
              style: AppTextStyles.caption,
            ),
          ] else ...[
            const SizedBox(height: AppSpacing.md),
            TextButton(
              onPressed: () => _showCancelSubscriptionDialog(),
              child: Text(
                l.creditsCancelSubscription,
                style: const TextStyle(color: AppColors.error),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildSubscriptionInfo(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: AppColors.textSecondary,
            fontSize: 12,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: const TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 16,
          ),
        ),
      ],
    );
  }

  Widget _buildPlansSection() {
    final l = AppLocalizations.of(context);
    final plans = _asList(_creditsStatus?['available_plans']);
    final planMaps =
        plans.map(_asMap).where((plan) => plan.isNotEmpty).toList();

    return Column(
      key: _plansSectionKey,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l.creditsPlansTitle,
          style: AppTextStyles.heading2,
        ),
        const SizedBox(height: AppSpacing.md),
        if (planMaps.isEmpty)
          Text(
            l.creditsNoAvailablePlans,
            style: const TextStyle(color: AppColors.textSecondary),
          )
        else
          ...planMaps.map(_buildPlanCard),
      ],
    );
  }

  Widget _buildPlanCard(Map<String, dynamic> plan) {
    final l = AppLocalizations.of(context);
    final planId = _coerceText(plan['id']) ?? '';
    final planName = localizedPlanName(
      l,
      planId,
      _coerceText(plan['name']) ?? l.creditsPlanFallbackName,
    );
    final price = _parseAmount(plan['price']);
    final creditsPerMonth = _parseAmount(plan['credits_per_month']);
    final features = localizedPlanFeatures(
      l,
      planId,
      _asList(plan['features']).map((f) => f.toString()).toList(),
    );
    final isCurrentPlan =
        _coerceText(_asMap(_creditsStatus?['subscription'])['plan']) == planId;

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
          color: isCurrentPlan ? AppColors.primary : AppColors.divider,
          width: isCurrentPlan ? 2 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                planName,
                style: AppTextStyles.heading3,
              ),
              if (isCurrentPlan)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    l.creditsCurrentPlan,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            price == 0
                ? l.creditsFree
                : l.creditsPricePerMonth(_formatNumber(price)),
            style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.bold,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l.creditsMonthlyCreatable(creditsPerMonth),
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: features
                .map((f) => Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.check_circle,
                          size: 16,
                          color: AppColors.success,
                        ),
                        const SizedBox(width: 4),
                        Text(f.toString(),
                            style: const TextStyle(fontSize: 13)),
                      ],
                    ))
                .toList(),
          ),
          if (!isCurrentPlan && planId != 'free' && planId.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.md),
            PrimaryButton(
              text: l.creditsSubscribe,
              onPressed: () => _subscribe(planId),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildCreditPackSection() {
    final l = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l.creditsPackTitle,
          style: AppTextStyles.heading2,
        ),
        const SizedBox(height: AppSpacing.md),
        ..._creditPackProducts.entries.map((entry) {
          return _buildCreditPackCard(
            productId: entry.key,
            credits: entry.value,
          );
        }),
      ],
    );
  }

  Widget _buildCreditPackCard({
    required String productId,
    required int credits,
  }) {
    final l = AppLocalizations.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.divider),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: AppColors.primaryLight,
              borderRadius: BorderRadius.circular(22),
            ),
            child: const Icon(Icons.stars, color: AppColors.primary),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l.creditsPackName(credits), style: AppTextStyles.heading3),
                Text(
                  l.creditsPackSubtitle,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          SizedBox(
            width: 120,
            child: OutlinedButton(
              onPressed: () => _buyCreditPack(productId),
              child: Text(l.creditsBuy),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTransactionsSection() {
    final l = AppLocalizations.of(context);
    if (_transactions.isEmpty) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l.creditsTransactionsTitle,
          style: AppTextStyles.heading2,
        ),
        const SizedBox(height: AppSpacing.md),
        Container(
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.divider),
          ),
          child: ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _transactions.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, index) {
              final tx = _transactions[index];
              final amount = _parseAmount(tx['amount']);
              final isPositive = amount > 0;
              final description = _coerceText(tx['description']) ??
                  _coerceText(tx['transaction_type']) ??
                  l.creditsTransactionFallback;

              return ListTile(
                leading: Icon(
                  isPositive ? Icons.add_circle : Icons.remove_circle,
                  color: isPositive ? AppColors.success : AppColors.error,
                ),
                title: Text(description),
                subtitle: Text(_formatDateTime(_coerceText(tx['created_at']))),
                trailing: Text(
                  '${isPositive ? '+' : ''}$amount',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: isPositive ? AppColors.success : AppColors.error,
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  void _scrollToPlans() {
    final context = _plansSectionKey.currentContext;
    if (context == null) {
      return;
    }

    Scrollable.ensureVisible(
      context,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
      alignment: 0.1,
    );
  }

  Future<void> _restorePurchases() async {
    // 복원된 구매는 기존 purchaseStream → _handlePurchaseUpdate(restored)로 검증·반영된다.
    final iapService = ref.read(iapServiceProvider);
    if (mounted) {
      final l = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.creditsRestoring)),
      );
    }
    try {
      await iapService.restorePurchases();
    } catch (_) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsRestoreFailed)),
        );
      }
    }
  }

  Future<void> _handlePurchaseUpdate(PurchaseDetails purchase) async {
    final iapService = ref.read(iapServiceProvider);

    if (purchase.status == PurchaseStatus.pending) {
      return;
    }

    if (purchase.status == PurchaseStatus.error) {
      await iapService.completePurchase(purchase);
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsPaymentCancelledOrFailed)),
        );
      }
      return;
    }

    final purchased = purchase.status == PurchaseStatus.purchased ||
        purchase.status == PurchaseStatus.restored;
    if (!purchased) {
      await iapService.completePurchase(purchase);
      return;
    }

    // R0-2(2026-08-17 보안감사): purchaseID가 없을 때 시간 기반 가짜 id를 만들면
    // **멱등성이 파괴된다**. 재시도마다 값이 달라지므로 (1) Apple은 그 id를 영수증에서
    // 찾지 못해 영구 검증 실패, (2) Google은 서버 dedup 키가 매번 달라져 **이중 지급** 여지가
    // 생긴다. 식별자가 없으면 검증을 **진행하지 않고** 트랜잭션을 pending으로 남긴다 —
    // 스토어가 다음 실행 purchaseStream 으로 재전달할 때 id와 함께 다시 처리된다.
    // (여기서 completePurchase 를 호출하면 미지급 상태로 대금이 영구 유실된다.)
    final transactionId = purchase.purchaseID;
    if (transactionId == null || transactionId.isEmpty) {
      debugPrint('purchaseID 없음 — 검증 보류(다음 실행 재전달로 재시도)');
      return;
    }
    // 검증 진행 중인 동일 트랜잭션의 중복 스트림 이벤트는 drop한다(MI2). 여기서 complete를
    // 호출하면 원 이벤트의 검증 결과와 무관하게 트랜잭션이 마무리돼 대금 유실 위험이 있다.
    if (_verifyingTransactions.contains(transactionId)) {
      return;
    }

    final isSubscription =
        _subscriptionProductMap.containsValue(purchase.productID);
    final consumable = !isSubscription;

    _verifyingTransactions.add(transactionId);
    try {
      final apiClient = ref.read(apiClientProvider);
      final platform =
          defaultTargetPlatform == TargetPlatform.iOS ? 'apple' : 'google';
      final payload = <String, dynamic>{
        'platform': platform,
        'product_id': purchase.productID,
        'transaction_id': transactionId,
        'is_subscription': isSubscription,
      };
      final serverData = purchase.verificationData.serverVerificationData;
      if (platform == 'apple') {
        payload['receipt_data'] = serverData;
      } else {
        payload['purchase_token'] = serverData;
      }

      final result = await apiClient.verifyIap(payload);
      // 서버 검증 성공 후에만 스토어 트랜잭션을 마무리(Android 소모성은 consume). 검증
      // 전에 마무리하면 미지급 상태로 대금이 영구 유실된다(C3). 실패 시(catch) 마무리하지
      // 않아 pending으로 남기고 다음 실행 purchaseStream 재전달로 재검증되게 한다.
      await iapService.finishPurchase(purchase, consumable: consumable);
      await _loadCreditsStatus();

      if (mounted) {
        final l = AppLocalizations.of(context);
        final status = _coerceText(result['status']) ?? 'verified';
        final message = switch (status) {
          'already_processed' => l.creditsAlreadyProcessed,
          'already_subscribed' => l.creditsAlreadySubscribed,
          _ => l.creditsVerifiedReflected,
        };
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    } catch (_) {
      // 검증 실패: completePurchase/consume를 호출하지 않아 트랜잭션을 pending 유지 →
      // 다음 앱 실행 시 재검증. 기존 문구가 '잠시 후 다시 시도' 취지라 그대로 재사용.
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsVerifyFailed)),
        );
      }
    } finally {
      _verifyingTransactions.remove(transactionId);
    }
  }

  Future<bool> _startStorePurchase(
    String productId, {
    required bool consumable,
  }) async {
    try {
      final iapService = ref.read(iapServiceProvider);
      final availability = await iapService.checkAvailability();
      if (!availability.isAvailable) {
        if (mounted) {
          final l = AppLocalizations.of(context);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                availability.unavailableReason ?? l.creditsStoreUnavailable,
              ),
            ),
          );
        }
        return false;
      }

      final products = await iapService.loadProducts({productId});
      ProductDetails? target;
      for (final product in products) {
        if (product.id == productId) {
          target = product;
          break;
        }
      }
      if (target == null) {
        return false;
      }

      await iapService.buyProduct(target, consumable: consumable);
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsProceedStorePayment)),
        );
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<void> _buyCreditPack(String productId) async {
    final started = await _startStorePurchase(productId, consumable: true);
    if (!started && mounted) {
      final l = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.creditsCannotStartStorePurchase)),
      );
    }
  }

  Future<void> _subscribe(String planId) async {
    final productId = _subscriptionProductMap[planId];
    if (productId != null) {
      final started = await _startStorePurchase(productId, consumable: false);
      if (started) {
        return;
      }
    }

    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.subscribe(planId);
      ref.read(analyticsProvider).logEvent(
        AnalyticsEvents.subscriptionStarted,
        params: {'plan_id': planId},
      );
      await _loadCreditsStatus();

      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsSubscriptionStarted)),
        );
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsSubscribeFailed)),
        );
      }
    }
  }

  void _showCancelSubscriptionDialog() {
    final l = AppLocalizations.of(context);
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.creditsCancelSubscription),
        content: Text(l.creditsCancelConfirmContent),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.creditsNo),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _cancelSubscription();
            },
            child: Text(l.creditsConfirmCancel,
                style: const TextStyle(color: AppColors.error)),
          ),
        ],
      ),
    );
  }

  Future<void> _cancelSubscription() async {
    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.cancelSubscription();
      await _loadCreditsStatus();

      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsSubscriptionCancelled)),
        );
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.creditsCancelFailed)),
        );
      }
    }
  }

  String _formatNumber(int number) {
    return number.toString().replaceAllMapped(
          RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
          (m) => '${m[1]},',
        );
  }

  String _formatDate(String? isoDate) {
    if (isoDate == null) return '-';
    try {
      final date = DateTime.parse(isoDate);
      return '${date.year}.${date.month}.${date.day}';
    } catch (e) {
      return isoDate;
    }
  }

  String _formatDateTime(String? isoDate) {
    if (isoDate == null) return '-';
    try {
      final date = DateTime.parse(isoDate);
      return '${date.year}.${date.month}.${date.day} ${date.hour}:${date.minute.toString().padLeft(2, '0')}';
    } catch (e) {
      return isoDate;
    }
  }

  int _parseAmount(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value) ?? 0;
    }
    return 0;
  }

  String? _coerceText(dynamic value) {
    if (value == null) {
      return null;
    }
    final text = value.toString().trim();
    if (text.isEmpty) {
      return null;
    }
    return text;
  }

  Map<String, dynamic> _asMap(dynamic value) {
    if (value is Map<String, dynamic>) {
      return value;
    }
    if (value is Map) {
      final mapped = <String, dynamic>{};
      for (final entry in value.entries) {
        if (entry.key == null) {
          continue;
        }
        mapped[entry.key.toString()] = entry.value;
      }
      return mapped;
    }
    return <String, dynamic>{};
  }

  List<dynamic> _asList(dynamic value) {
    if (value is List<dynamic>) {
      return value;
    }
    if (value is List) {
      return List<dynamic>.from(value);
    }
    return const <dynamic>[];
  }
}
