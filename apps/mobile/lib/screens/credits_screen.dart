import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

/// 크레딧 및 구독 화면
class CreditsScreen extends ConsumerStatefulWidget {
  const CreditsScreen({super.key});

  @override
  ConsumerState<CreditsScreen> createState() => _CreditsScreenState();
}

class _CreditsScreenState extends ConsumerState<CreditsScreen> {
  bool _isLoading = true;
  Map<String, dynamic>? _creditsStatus;
  List<dynamic> _transactions = [];

  @override
  void initState() {
    super.initState();
    _loadCreditsStatus();
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
          SnackBar(content: Text('크레딧 정보를 불러오지 못했어요: $e')),
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
                    _buildTransactionsSection(),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildCreditsCard() {
    final credits = _creditsStatus?['credits'] ?? {};
    final currentCredits = credits['credits'] ?? 0;
    final totalUsed = credits['total_used'] ?? 0;

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
                  '총 ${totalUsed}권 생성',
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
                  onPressed: () => _showPurchaseDialog(),
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
    final subscription = _creditsStatus?['subscription'];

    if (subscription == null) {
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
                    '${subscription['plan_name']} 구독',
                    style: AppTextStyles.heading3,
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: AppColors.successLight,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text(
                  '활성',
                  style: TextStyle(
                    color: AppColors.success,
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
                '${subscription['credits_per_month']}개',
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
            children: (subscription['features'] as List<dynamic>?)
                    ?.map((f) => Chip(
                          label: Text(f.toString(),
                              style: const TextStyle(fontSize: 12)),
                          backgroundColor: AppColors.primaryLight,
                        ))
                    .toList() ??
                [],
          ),
          const SizedBox(height: AppSpacing.md),
          TextButton(
            onPressed: () => _showCancelSubscriptionDialog(),
            child: const Text(
              '구독 취소',
              style: TextStyle(color: AppColors.error),
            ),
          ),
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
    final plans = _creditsStatus?['available_plans'] as List<dynamic>? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '구독 플랜',
          style: AppTextStyles.heading2,
        ),
        const SizedBox(height: AppSpacing.md),
        ...plans.map((plan) => _buildPlanCard(plan)).toList(),
      ],
    );
  }

  Widget _buildPlanCard(Map<String, dynamic> plan) {
    final isCurrentPlan =
        _creditsStatus?['subscription']?['plan'] == plan['id'];

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
                plan['name'],
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
            plan['price'] == 0 ? '무료' : '₩${_formatNumber(plan['price'])}/월',
            style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.bold,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '월 ${plan['credits_per_month']}권 생성 가능',
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: (plan['features'] as List<dynamic>)
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
          if (!isCurrentPlan && plan['id'] != 'free') ...[
            const SizedBox(height: AppSpacing.md),
            PrimaryButton(
              text: '구독하기',
              onPressed: () => _subscribe(plan['id']),
            ),
          ],
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
              final isPositive = (tx['amount'] as int) > 0;

              return ListTile(
                leading: Icon(
                  isPositive ? Icons.add_circle : Icons.remove_circle,
                  color: isPositive ? AppColors.success : AppColors.error,
                ),
                title: Text(tx['description'] ?? tx['transaction_type']),
                subtitle: Text(_formatDateTime(tx['created_at'])),
                trailing: Text(
                  '${isPositive ? '+' : ''}${tx['amount']}',
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
    // TODO: Implement scroll to plans section
  }

  void _showPurchaseDialog() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('크레딧 구매'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildPurchaseOption(5, 4900),
            _buildPurchaseOption(15, 12900),
            _buildPurchaseOption(30, 22900),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
        ],
      ),
    );
  }

  Widget _buildPurchaseOption(int credits, int price) {
    return ListTile(
      title: Text('$credits 크레딧'),
      subtitle: Text('₩${_formatNumber(price)}'),
      trailing: const Icon(Icons.arrow_forward_ios, size: 16),
      onTap: () {
        Navigator.pop(context);
        _purchaseCredits(credits, price);
      },
    );
  }

  Future<void> _purchaseCredits(int credits, int price) async {
    // TODO: Implement in-app purchase flow
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('인앱 결제 기능은 준비 중입니다.')),
    );
  }

  Future<void> _subscribe(String planId) async {
    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.subscribe(planId);
      await _loadCreditsStatus();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('구독이 시작되었습니다!')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('구독 실패: $e')),
        );
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
          SnackBar(content: Text('취소 실패: $e')),
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
}
