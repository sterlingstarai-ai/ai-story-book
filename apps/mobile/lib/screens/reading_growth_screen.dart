import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';

/// 부모용 '읽기 성장' 리포트 화면.
///
/// '동화 생성기'가 아니라 '측정되는 읽기성장 동반자' 리포지셔닝의 얼굴.
/// 아이가 동화를 읽을수록 쌓이는 성장(읽은 책·연속 읽기·학습 어휘·퀴즈 정확도·추정 읽기레벨)을 보여준다.
class ReadingGrowthScreen extends ConsumerStatefulWidget {
  const ReadingGrowthScreen({super.key});

  @override
  ConsumerState<ReadingGrowthScreen> createState() =>
      _ReadingGrowthScreenState();
}

class _ReadingGrowthScreenState extends ConsumerState<ReadingGrowthScreen> {
  @override
  void initState() {
    super.initState();
    ref.read(analyticsProvider).logEvent(AnalyticsEvents.growthViewed);
  }

  @override
  Widget build(BuildContext context) {
    final reportAsync = ref.watch(growthReportProvider);
    final weekly = ref.watch(weeklyReadingTrendProvider).asData?.value;
    final hasTrend = weekly != null && weekly.any((c) => c > 0);
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).readingGrowthTitle),
        backgroundColor: AppColors.surface,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
      ),
      body: reportAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _ErrorView(
          onRetry: () => ref.invalidate(growthReportProvider),
        ),
        data: (report) => RefreshIndicator(
          onRefresh: () => ref.refresh(growthReportProvider.future),
          child: ListView(
            padding: const EdgeInsets.all(AppSpacing.md),
            children: [
              _LevelHero(report: report),
              const SizedBox(height: AppSpacing.md),
              _StatGrid(report: report),
              if (hasTrend) ...[
                const SizedBox(height: AppSpacing.md),
                _WeeklyTrend(counts: weekly),
              ],
              const SizedBox(height: AppSpacing.md),
              const _PeerComparison(),
              const SizedBox(height: AppSpacing.md),
              const _DisclaimerNote(),
            ],
          ),
        ),
      ),
    );
  }
}

class _LevelHero extends StatelessWidget {
  const _LevelHero({required this.report});

  final GrowthReport report;

  @override
  Widget build(BuildContext context) {
    final progress = (report.levelNumber / 10).clamp(0.0, 1.0);
    return Container(
      key: const Key('growth_level_hero'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.primary,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).estimatedReadingLevel,
            style: const TextStyle(color: Colors.white70, fontSize: 13),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                'Lv.${report.levelNumber}',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 40,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Text(
                report.levelLabel,
                style: const TextStyle(color: Colors.white, fontSize: 18),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.sm),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 8,
              backgroundColor: Colors.white24,
              valueColor: const AlwaysStoppedAnimation<Color>(Colors.white),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          const Text(
            '매일 읽을수록 또렷해져요',
            style: TextStyle(color: Colors.white70, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _StatGrid extends StatelessWidget {
  const _StatGrid({required this.report});

  final GrowthReport report;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final accuracyLabel = report.quizTotal > 0
        ? '${(report.quizAccuracy * 100).round()}%'
        : '—';
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: AppSpacing.sm,
      crossAxisSpacing: AppSpacing.sm,
      childAspectRatio: 1.6,
      children: [
        _StatCard(
          icon: Icons.menu_book_rounded,
          label: l10n.booksReadLabel,
          value: '${report.booksRead}권',
          color: AppColors.primary,
        ),
        _StatCard(
          icon: Icons.local_fire_department_rounded,
          label: l10n.currentStreakLabel,
          value: '${report.currentStreak}일',
          sub: '최장 ${report.longestStreak}일',
          color: AppColors.warning,
        ),
        _StatCard(
          icon: Icons.spellcheck_rounded,
          label: l10n.vocabLearnedLabel,
          value: '${report.vocabLearned}개',
          color: AppColors.secondary,
        ),
        _StatCard(
          icon: Icons.quiz_rounded,
          label: l10n.quizAccuracyLabel,
          value: accuracyLabel,
          sub: report.quizTotal > 0 ? '${report.quizCorrect}/${report.quizTotal}' : null,
          color: AppColors.success,
        ),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
    this.sub,
  });

  final IconData icon;
  final String label;
  final String value;
  final String? sub;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Icon(icon, color: color, size: 22),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: AppColors.textPrimary,
                ),
              ),
              Text(
                sub == null ? label : '$label · $sub',
                style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 주간 읽기 추이 막대차트(C1 신규) — 읽기 기록에서 클라이언트 집계.
class _WeeklyTrend extends StatelessWidget {
  const _WeeklyTrend({required this.counts});

  final List<int> counts;

  @override
  Widget build(BuildContext context) {
    final maxC = counts.fold<int>(1, (m, c) => c > m ? c : m);
    return Container(
      key: const Key('growth_weekly_trend'),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('주간 읽기 추이', style: AppTextStyles.heading3),
          const SizedBox(height: 2),
          Text('최근 ${counts.length}주 · 읽은 횟수', style: AppTextStyles.caption),
          const SizedBox(height: AppSpacing.md),
          SizedBox(
            height: 120,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                for (var i = 0; i < counts.length; i++)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 5),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          Text(
                            '${counts[i]}',
                            style: AppTextStyles.caption.copyWith(
                              fontWeight: FontWeight.w700,
                              color: AppColors.textSecondary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Container(
                            height: 8 + (counts[i] / maxC) * 64,
                            decoration: const BoxDecoration(
                              gradient: LinearGradient(
                                colors: [
                                  AppColors.primary,
                                  AppColors.primaryHalf
                                ],
                                begin: Alignment.topCenter,
                                end: Alignment.bottomCenter,
                              ),
                              borderRadius: BorderRadius.vertical(
                                top: Radius.circular(6),
                              ),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            i == counts.length - 1 ? '이번' : '${i + 1}주',
                            style: AppTextStyles.caption,
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 또래 비교(경쟁 동기) — /v1/growth/peers. 데이터 없으면 조용히 숨김.
class _PeerComparison extends ConsumerWidget {
  const _PeerComparison();

  static const _medalEmoji = {
    'gold': '🥇',
    'silver': '🥈',
    'bronze': '🥉',
    'none': '🌱',
  };

  String _encourage(int topPercent) {
    if (topPercent <= 10) {
      return '또래 중 최상위! 정말 잘하고 있어요 🎉';
    }
    if (topPercent <= 30) {
      return '또래보다 앞서가고 있어요 👍';
    }
    if (topPercent <= 60) {
      return '또래와 비슷하게 잘 읽고 있어요';
    }
    return '조금만 더 읽으면 또래를 따라잡아요!';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref.watch(peerComparisonProvider).maybeWhen(
          data: _card,
          orElse: () => const SizedBox.shrink(),
        );
  }

  Widget _card(PeerComparison peer) {
    final subtitle = peer.isBaseline
        ? '또래 표본이 적어 ${peer.ageBand}세 기준값과 비교했어요 (참고용)'
        : '같은 ${peer.ageBand}세 또래 ${peer.peerCount}명 기준';
    return Container(
      key: const Key('growth_peer_comparison'),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('또래 비교', style: AppTextStyles.heading3),
          const SizedBox(height: 2),
          Text(subtitle, style: AppTextStyles.caption),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Text(_medalEmoji[peer.medal] ?? '🌱',
                  style: const TextStyle(fontSize: 34)),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '상위 ${peer.topPercent}%',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: AppColors.primary,
                      ),
                    ),
                    Text(_encourage(peer.topPercent),
                        style: AppTextStyles.bodySmall),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          _CompareRow(
            label: '읽은 책',
            mine: peer.myBooks.toDouble(),
            peerValue: peer.peerBooks,
            mineText: '${peer.myBooks}권',
            peerText: '또래 ${peer.peerBooks.toStringAsFixed(1)}권',
          ),
          _CompareRow(
            label: '학습 어휘',
            mine: peer.myVocab.toDouble(),
            peerValue: peer.peerVocab,
            mineText: '${peer.myVocab}개',
            peerText: '또래 ${peer.peerVocab.toStringAsFixed(1)}개',
          ),
          _CompareRow(
            label: '퀴즈 정확도',
            mine: peer.myAccuracy * 100,
            peerValue: peer.peerAccuracy * 100,
            mineText: '${(peer.myAccuracy * 100).round()}%',
            peerText: '또래 ${(peer.peerAccuracy * 100).round()}%',
          ),
        ],
      ),
    );
  }
}

class _CompareRow extends StatelessWidget {
  const _CompareRow({
    required this.label,
    required this.mine,
    required this.peerValue,
    required this.mineText,
    required this.peerText,
  });

  final String label;
  final double mine;
  final double peerValue;
  final String mineText;
  final String peerText;

  @override
  Widget build(BuildContext context) {
    final maxV = [mine, peerValue, 1.0].reduce((a, b) => a > b ? a : b);
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(label, style: AppTextStyles.bodySmall)),
              Text(
                mineText,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Text(peerText, style: AppTextStyles.caption),
            ],
          ),
          const SizedBox(height: 6),
          _bar(mine / maxV, AppColors.primary),
          const SizedBox(height: 4),
          _bar(peerValue / maxV, AppColors.textHint),
        ],
      ),
    );
  }

  Widget _bar(double ratio, Color color) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: LinearProgressIndicator(
        value: ratio.clamp(0.0, 1.0),
        minHeight: 8,
        backgroundColor: AppColors.background,
        valueColor: AlwaysStoppedAnimation<Color>(color),
      ),
    );
  }
}

class _DisclaimerNote extends StatelessWidget {
  const _DisclaimerNote();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: const Text(
        '읽기레벨은 읽은 책·학습 어휘·퀴즈 정확도로 산출한 추정치예요. '
        '공인 척도는 아니며, 아이가 꾸준히 읽을수록 더 정확해집니다.',
        style: TextStyle(fontSize: 12, color: AppColors.textSecondary, height: 1.5),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('성장 리포트를 불러오지 못했어요.'),
          const SizedBox(height: AppSpacing.md),
          ElevatedButton(
            onPressed: onRetry,
            child: Text(AppLocalizations.of(context).retry),
          ),
        ],
      ),
    );
  }
}
