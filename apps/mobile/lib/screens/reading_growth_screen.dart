import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

/// 부모용 '읽기 성장' 리포트 화면.
///
/// '동화 생성기'가 아니라 '측정되는 읽기성장 동반자' 리포지셔닝의 얼굴.
/// 아이가 동화를 읽을수록 쌓이는 성장(읽은 책·연속 읽기·학습 어휘·퀴즈 정확도·추정 읽기레벨)을 보여준다.
class ReadingGrowthScreen extends ConsumerWidget {
  const ReadingGrowthScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reportAsync = ref.watch(growthReportProvider);
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('읽기 성장'),
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
          const Text(
            '우리 아이 추정 읽기레벨',
            style: TextStyle(color: Colors.white70, fontSize: 13),
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
          label: '읽은 책',
          value: '${report.booksRead}권',
          color: AppColors.primary,
        ),
        _StatCard(
          icon: Icons.local_fire_department_rounded,
          label: '연속 읽기',
          value: '${report.currentStreak}일',
          sub: '최장 ${report.longestStreak}일',
          color: AppColors.warning,
        ),
        _StatCard(
          icon: Icons.spellcheck_rounded,
          label: '학습 어휘',
          value: '${report.vocabLearned}개',
          color: AppColors.secondary,
        ),
        _StatCard(
          icon: Icons.quiz_rounded,
          label: '퀴즈 정확도',
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
          ElevatedButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}
