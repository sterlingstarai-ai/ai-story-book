import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';

/// 부모용 '읽기 성장' 리포트 화면.
///
/// '측정되는 읽기성장 동반자' 리포지셔닝의 얼굴. 시장 조사(Khan/Reading Eggs/Lexia·SDT/Piaget)
/// 근거로 *자기 대비 성장*을 1차로, 또래 비교는 2차·안전(구간·연령 게이트)으로 배치한다.
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
    WidgetsBinding.instance.addPostFrameCallback((_) => _guardWithAgeGate());
  }

  /// 부모 인증 게이트 — 아이가 자기 '상위%·강등'을 부모 매개 없이 직면하지 않게.
  Future<void> _guardWithAgeGate() async {
    if (!mounted) {
      return;
    }
    final routeName = ModalRoute.of(context)?.settings.name;
    if (routeName != '/reading-growth') {
      return; // 라우트로 진입했을 때만 게이트(테스트/직접 임베드는 통과)
    }
    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.loadAgeGateSession(prefs);
    if (parental.isAgeGateVerifiedForSession || !mounted) {
      return;
    }
    final passed = await showAgeGateDialog(context, ref);
    if (!passed && mounted) {
      Navigator.pop(context);
    }
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
              // 1차: 자기 대비 성장(주간 추이) — 또래보다 먼저, 더 크게.
              if (hasTrend) ...[
                const SizedBox(height: AppSpacing.md),
                _WeeklyTrend(counts: weekly),
              ],
              const SizedBox(height: AppSpacing.md),
              _StatGrid(report: report),
              // 2차: 또래 비교(안전·구간·연령 게이트). 데이터 없으면 숨김.
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

  String _confidenceStars(int books) =>
      books >= 13 ? '⭐⭐⭐' : books >= 5 ? '⭐⭐' : '⭐';

  String _confidenceText(int books) => books >= 13
      ? '신뢰도 높음'
      : books >= 5
          ? '신뢰도 보통'
          : '더 읽을수록 정확해져요';

  @override
  Widget build(BuildContext context) {
    final progress = (report.scoreValue / 100).clamp(0.0, 1.0);
    // 보조기술(TalkBack/VoiceOver)에 핵심 지표를 하나의 명료한 문장으로 읽어준다
    // (시각적 막대·분리된 텍스트 대신 통합 라벨).
    return Semantics(
      container: true,
      excludeSemantics: true,
      label: '추정 읽기 레벨 ${report.levelNumber}, ${report.levelLabel}. '
          '읽은 책·어휘·정확도·완독 종합 점수 ${report.scoreValue}점 만점 100점. '
          '신뢰도 ${_confidenceText(report.booksRead)}.',
      child: Container(
        key: const Key('growth_level_hero'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.primary,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  AppLocalizations.of(context).estimatedReadingLevel,
                  style: const TextStyle(color: Colors.white70, fontSize: 13),
                ),
              ),
              Text(
                '${_confidenceStars(report.booksRead)} ${_confidenceText(report.booksRead)}',
                style: const TextStyle(color: Colors.white70, fontSize: 11),
              ),
            ],
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
          Text(
            '읽은 책·어휘·정확도·완독을 종합한 추정 점수 ${report.scoreValue}/100',
            style: const TextStyle(color: Colors.white70, fontSize: 12),
          ),
        ],
        ),
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

/// 주간 읽기 추이(자기 대비 성장 1차) — 읽기 기록에서 클라이언트 집계 + 지난 주 대비 델타.
class _WeeklyTrend extends StatelessWidget {
  const _WeeklyTrend({required this.counts});

  final List<int> counts;

  String _deltaText() {
    if (counts.length < 2) {
      return '이번 주 ${counts.isEmpty ? 0 : counts.last}권';
    }
    final delta = counts.last - counts[counts.length - 2];
    final sign = delta > 0 ? '+$delta' : '$delta';
    final tail = delta > 0
        ? ' 더 읽었어요 👏'
        : delta < 0
            ? ''
            : ' (지난 주와 같아요)';
    return '이번 주 ${counts.last}권 · 지난 주 대비 $sign권$tail';
  }

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
          const Text('우리 아이 성장 (주간)', style: AppTextStyles.heading3),
          const SizedBox(height: 2),
          Text(_deltaText(), style: AppTextStyles.caption),
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

/// 또래 비교(2차·안전) — /v1/growth/peers.
/// - 3-5세(show_ranking=false): 등수 대신 자기 성장만.
/// - 6-9세: 복합 점수 기준 구간 리그(성장/도전/마스터) + 상위%. 데이터 0인 축은 숨김.
class _PeerComparison extends ConsumerWidget {
  const _PeerComparison();

  String _league(String medal) {
    switch (medal) {
      case 'gold':
        return '🌳 마스터 리그';
      case 'silver':
        return '🌿 도전 리그';
      default:
        return '🌱 성장 리그';
    }
  }

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
    // 중앙값 미만에도 '따라잡아라'식 열세·추격 프레이밍 대신 자기성장에 초점
    // (아동 사회비교 상향 압박 완화 — 매일 읽는 습관이 성장의 핵심).
    return '매일 읽을수록 쑥쑥 자라요. 오늘도 한 권 어때요? 🌱';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref.watch(peerComparisonProvider).maybeWhen(
          data: (peer) => peer.showRanking ? _ranking(peer) : _selfGrowth(peer),
          orElse: () => const SizedBox.shrink(),
        );
  }

  Widget _shell({required List<Widget> children}) => Container(
        key: const Key('growth_peer_comparison'),
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.divider),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
      );

  // 3-5세: 등수·백분위는 발달상 무의미 → 자기 성장만(사회비교 배제).
  Widget _selfGrowth(PeerComparison peer) => _shell(children: [
        const Text('우리 아이 읽기 성장', style: AppTextStyles.heading3),
        const SizedBox(height: AppSpacing.sm),
        Text(
          '이번까지 책 ${peer.myBooks}권 · 학습 어휘 ${peer.myVocab}개',
          style: AppTextStyles.body,
        ),
        const SizedBox(height: 4),
        const Text(
          '이 나이엔 등수보다 매일 읽는 습관이 가장 중요해요. 또래 비교는 더 큰 친구들에게 보여드려요.',
          style: TextStyle(fontSize: 12, color: AppColors.textSecondary, height: 1.5),
        ),
      ]);

  Widget _ranking(PeerComparison peer) {
    final subtitle = peer.isBaseline
        ? '아직 또래 표본이 적어 ${peer.ageBand}세 기준값과 비교 (참고용)'
        : '같은 ${peer.ageBand}세 또래 ${peer.peerCount}명 기준 · 읽기 종합 점수';
    final rows = <Widget>[];
    void addRow(String label, double mine, double peer, String mineText, String peerText) {
      if (mine <= 0 && peer <= 0) {
        return; // 데이터 0인 축은 '거짓 열세' 방지 위해 숨김
      }
      rows.add(_CompareRow(
        label: label,
        mine: mine,
        peerValue: peer,
        mineText: mineText,
        peerText: peerText,
      ));
    }

    addRow('읽기 종합 점수', peer.myScore.toDouble(), peer.peerScore.toDouble(),
        '${peer.myScore}점', '또래 ${peer.peerScore}점');
    addRow('읽은 책', peer.myBooks.toDouble(), peer.peerBooks,
        '${peer.myBooks}권', '또래 ${peer.peerBooks.toStringAsFixed(1)}권');
    addRow('학습 어휘', peer.myVocab.toDouble(), peer.peerVocab,
        '${peer.myVocab}개', '또래 ${peer.peerVocab.toStringAsFixed(1)}개');
    addRow('퀴즈 정확도', peer.myAccuracy * 100, peer.peerAccuracy * 100,
        '${(peer.myAccuracy * 100).round()}%', '또래 ${(peer.peerAccuracy * 100).round()}%');

    return _shell(children: [
      const Text('또래 비교', style: AppTextStyles.heading3),
      const SizedBox(height: 2),
      Text(subtitle, style: AppTextStyles.caption),
      const SizedBox(height: AppSpacing.md),
      Row(
        children: [
          Text(_league(peer.medal).split(' ').first,
              style: const TextStyle(fontSize: 30)),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(
                      '상위 ${peer.topPercent}%',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Text(_league(peer.medal).split(' ').last,
                        style: AppTextStyles.bodySmall),
                  ],
                ),
                Text(_encourage(peer.topPercent), style: AppTextStyles.bodySmall),
              ],
            ),
          ),
        ],
      ),
      const SizedBox(height: AppSpacing.md),
      ...rows,
    ]);
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
        '읽기 점수·레벨은 읽은 책·완독·학습 어휘·퀴즈 정확도를 종합한 추정치예요. '
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
