import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../core/api_error.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../services/rewarded_ad_service.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';
import '../widgets/common_widgets.dart';

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
  bool _isClaimingReward = false;

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
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('크레딧 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('크레딧'),
        backgroundColor: AppColors.surface,
        actions: [
          // Apple 3.1.1: 구독/비소모성 상품 앱은 '구매 복원' 필수(기기 변경·재설치 대응).
          TextButton(
            key: const Key('restore_purchases_btn'),
            onPressed: _restorePurchases,
            child: const Text('구매 복원'),
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
                    _buildRewardSection(),
                    const SizedBox(height: AppSpacing.lg),
                    _buildTransactionsSection(),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildCreditsCard() {
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
              const Text(
                '내 크레딧',
                style: TextStyle(
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
                  '총 $totalUsed권 생성',
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
              const Padding(
                padding: EdgeInsets.only(bottom: 8, left: 4),
                child: Text(
                  '크레딧',
                  style: TextStyle(
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
                  child: const Text('크레딧 구매'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSubscriptionCard() {
    final subscription = _asMap(_creditsStatus?['subscription']);
    final subscriptionStatus =
        (_coerceText(subscription['status']) ?? 'active').toLowerCase();
    final isCancelled = subscriptionStatus == 'cancelled';
    final badgeColor = isCancelled ? AppColors.warning : AppColors.success;
    final badgeBackground =
        isCancelled ? AppColors.warningLight : AppColors.successLight;
    final badgeText = isCancelled ? '해지 예정' : '활성';

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
            const Row(
              children: [
                Icon(Icons.card_membership, color: AppColors.textSecondary),
                SizedBox(width: AppSpacing.sm),
                Text(
                  '구독 정보',
                  style: AppTextStyles.heading3,
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            const Text(
              '현재 구독 중인 플랜이 없습니다.',
              style: TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.md),
            PrimaryButton(
              text: '구독 시작하기',
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
                    '${_coerceText(subscription['plan_name']) ?? '기본'} 구독',
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
                '월간 크레딧',
                '${_parseAmount(subscription['credits_per_month'])}개',
              ),
              const SizedBox(width: AppSpacing.lg),
              _buildSubscriptionInfo(
                '다음 갱신일',
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
            const Text(
              '현재 결제 주기가 끝나면 무료 플랜으로 전환됩니다.',
              style: AppTextStyles.caption,
            ),
          ] else ...[
            const SizedBox(height: AppSpacing.md),
            TextButton(
              onPressed: () => _showCancelSubscriptionDialog(),
              child: const Text(
                '구독 취소',
                style: TextStyle(color: AppColors.error),
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
    final plans = _asList(_creditsStatus?['available_plans']);
    final planMaps =
        plans.map(_asMap).where((plan) => plan.isNotEmpty).toList();

    return Column(
      key: _plansSectionKey,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '구독 플랜',
          style: AppTextStyles.heading2,
        ),
        const SizedBox(height: AppSpacing.md),
        if (planMaps.isEmpty)
          const Text(
            '현재 이용 가능한 구독 플랜이 없습니다.',
            style: TextStyle(color: AppColors.textSecondary),
          )
        else
          ...planMaps.map(_buildPlanCard),
      ],
    );
  }

  Widget _buildPlanCard(Map<String, dynamic> plan) {
    final planId = _coerceText(plan['id']) ?? '';
    final planName = _coerceText(plan['name']) ?? '플랜';
    final price = _parseAmount(plan['price']);
    final creditsPerMonth = _parseAmount(plan['credits_per_month']);
    final features = _asList(plan['features']);
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
                  child: const Text(
                    '현재 플랜',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            price == 0 ? '무료' : '₩${_formatNumber(price)}/월',
            style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.bold,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '월 $creditsPerMonth권 생성 가능',
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
              text: '구독하기',
              onPressed: () => _subscribe(planId),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildCreditPackSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '크레딧 팩',
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

  Widget _buildRewardSection() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.ondemand_video_outlined, color: AppColors.primary),
              SizedBox(width: AppSpacing.sm),
              Text('리워드 광고', style: AppTextStyles.heading3),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          const Text(
            '광고 시청 완료 시 1크레딧을 지급합니다. (일 최대 3회)',
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.xs),
          const Text(
            '현재는 샌드박스 보상 경로로 동작하며, AdMob 키 연동 시 실제 광고가 표시됩니다.',
            style: AppTextStyles.caption,
          ),
          const SizedBox(height: AppSpacing.md),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _isClaimingReward ? null : _claimRewardAdCredit,
              icon: _isClaimingReward
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.play_circle_outline),
              label: Text(_isClaimingReward ? '처리 중...' : '시청 완료 처리'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCreditPackCard({
    required String productId,
    required int credits,
  }) {
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
                Text('$credits 크레딧 팩', style: AppTextStyles.heading3),
                Text(
                  '필요할 때 즉시 충전',
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
              child: const Text('구매'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTransactionsSection() {
    if (_transactions.isEmpty) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '거래 내역',
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
                  '거래';

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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('구매 내역을 복원하고 있어요...')),
      );
    }
    try {
      await iapService.restorePurchases();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('복원에 실패했어요. 잠시 후 다시 시도해주세요.')),
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('결제가 취소되었거나 실패했어요.')),
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

    final transactionId = purchase.purchaseID ??
        '${purchase.productID}-${DateTime.now().millisecondsSinceEpoch}';
    if (_verifyingTransactions.contains(transactionId)) {
      await iapService.completePurchase(purchase);
      return;
    }

    _verifyingTransactions.add(transactionId);
    try {
      final apiClient = ref.read(apiClientProvider);
      final platform =
          defaultTargetPlatform == TargetPlatform.iOS ? 'apple' : 'google';
      final payload = <String, dynamic>{
        'platform': platform,
        'product_id': purchase.productID,
        'transaction_id': transactionId,
        'is_subscription':
            _subscriptionProductMap.containsValue(purchase.productID),
      };
      final serverData = purchase.verificationData.serverVerificationData;
      if (platform == 'apple') {
        payload['receipt_data'] = serverData;
      } else {
        payload['purchase_token'] = serverData;
      }

      final result = await apiClient.verifyIap(payload);
      await _loadCreditsStatus();

      if (mounted) {
        final status = _coerceText(result['status']) ?? 'verified';
        final message = switch (status) {
          'already_processed' => '이미 처리된 결제입니다.',
          'already_subscribed' => '이미 같은 플랜을 이용 중입니다.',
          _ => '결제가 확인되어 크레딧이 반영되었어요.',
        };
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('결제 검증에 실패했어요. 잠시 후 다시 시도해주세요.')),
        );
      }
    } finally {
      _verifyingTransactions.remove(transactionId);
      await iapService.completePurchase(purchase);
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
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                availability.unavailableReason ?? '스토어 결제를 사용할 수 없어요.',
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('스토어 결제를 진행해주세요.')),
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('스토어 구매를 시작할 수 없어요.')),
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('구독이 시작되었습니다!')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('구독에 실패했어요. 잠시 후 다시 시도해주세요.')),
        );
      }
    }
  }

  Future<void> _claimRewardAdCredit() async {
    if (_isClaimingReward) {
      return;
    }
    setState(() => _isClaimingReward = true);
    try {
      final rewardedAdService = ref.read(rewardedAdServiceProvider);
      final rewardResult = await rewardedAdService.showRewardedAd();
      if (!rewardResult.rewarded) {
        if (mounted) {
          final message = switch (rewardResult.status) {
            RewardedAdStatus.dismissed => '광고를 끝까지 시청해야 보상이 지급돼요.',
            RewardedAdStatus.misconfigured =>
              rewardResult.reason ?? '광고 기능이 아직 설정되지 않았어요.',
            RewardedAdStatus.unavailable =>
              rewardResult.reason ?? '현재 기기에서 광고를 사용할 수 없어요.',
            RewardedAdStatus.loadFailed =>
              rewardResult.reason ?? '광고를 불러오지 못했어요. 잠시 후 다시 시도해주세요.',
            RewardedAdStatus.rewarded => '광고를 끝까지 시청해야 보상이 지급돼요.',
          };
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(message)),
          );
        }
        return;
      }

      final apiClient = ref.read(apiClientProvider);
      final result = await apiClient.completeRewardAd(
        adNetwork: 'admob',
        adUnitId: rewardResult.adUnitId,
      );
      await _loadCreditsStatus();

      if (!mounted) {
        return;
      }
      final reward = _parseAmount(result['reward']);
      final used = _parseAmount(result['today_used']);
      final limit = _parseAmount(result['today_limit']);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('보상 $reward크레딧 지급 완료 ($used/$limit)')),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      final message = error is ApiError
          ? error.userMessage
          : '보상 처리에 실패했어요. 잠시 후 다시 시도해주세요.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
    } finally {
      if (mounted) {
        setState(() => _isClaimingReward = false);
      }
    }
  }

  void _showCancelSubscriptionDialog() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('구독 취소'),
        content: const Text('정말 구독을 취소하시겠어요? 현재 기간이 끝날 때까지는 계속 사용할 수 있어요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('아니오'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _cancelSubscription();
            },
            child: const Text('취소하기', style: TextStyle(color: AppColors.error)),
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('구독이 취소되었습니다.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('구독 취소에 실패했어요. 잠시 후 다시 시도해주세요.')),
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
