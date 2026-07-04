import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

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
              // 전환: 성장을 자랑(공유)하고 → 더 읽어 성장을 잇는다(새 책 만들기).
              const SizedBox(height: AppSpacing.md),
              _GrowthCtaCard(report: report),
            ],
          ),
        ),
      ),
    );
  }
}

/// 성장 화면 하단 전환 카드 — (1) 성장 공유(자랑심리→바이럴), (2) 새 책 만들기.
class _GrowthCtaCard extends StatelessWidget {
  const _GrowthCtaCard({required this.report});

  final GrowthReport report;

  String _shareText(AppLocalizations l) => l.growthShareText(
        report.booksRead,
        report.levelNumber,
        report.levelLabel,
        report.scoreValue,
        report.vocabLearned,
        report.currentStreak,
      );

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('growth_cta_card'),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.growthCtaTitle, style: AppTextStyles.heading3),
          const SizedBox(height: AppSpacing.xs),
          Text(
            l.growthCtaSubtitle,
            style: AppTextStyles.caption.copyWith(color: AppColors.textHint),
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Expanded(
                child: Semantics(
                  button: true,
                  label: l.growthShareSemantic,
                  child: OutlinedButton.icon(
                    key: const Key('growth_share_btn'),
                    onPressed: () => Share.share(_shareText(l)),
                    icon: const Icon(Icons.ios_share, size: 18),
                    label: Text(l.growthShareButton),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Semantics(
                  button: true,
                  label: l.growthCreateSemantic,
                  child: ElevatedButton.icon(
                    key: const Key('growth_create_btn'),
                    onPressed: () => Navigator.pushNamed(context, '/create'),
                    icon: const Icon(Icons.auto_stories, size: 18),
                    label: Text(l.growthCreateButton),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LevelHero extends StatelessWidget {
  const _LevelHero({required this.report});

  final GrowthReport report;

  String _confidenceStars(int books) =>
      books >= 13 ? '⭐⭐⭐' : books >= 5 ? '⭐⭐' : '⭐';

  String _confidenceText(int books, AppLocalizations l) => books >= 13
      ? l.growthConfidenceHigh
      : books >= 5
          ? l.growthConfidenceMedium
          : l.growthConfidenceLow;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final progress = (report.scoreValue / 100).clamp(0.0, 1.0);
    // 보조기술(TalkBack/VoiceOver)에 핵심 지표를 하나의 명료한 문장으로 읽어준다
    // (시각적 막대·분리된 텍스트 대신 통합 라벨).
    return Semantics(
      container: true,
      excludeSemantics: true,
      label: l.growthHeroSemantic(
        report.levelNumber,
        report.levelLabel,
        report.scoreValue,
        _confidenceText(report.booksRead, l),
      ),
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
                '${_confidenceStars(report.booksRead)} '
                '${_confidenceText(report.booksRead, l)}',
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
            l.growthScoreSummary(report.scoreValue),
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
          value: l10n.growthBooksValue(report.booksRead),
          color: AppColors.primary,
        ),
        _StatCard(
          icon: Icons.local_fire_department_rounded,
          label: l10n.currentStreakLabel,
          value: l10n.growthDaysValue(report.currentStreak),
          sub: l10n.growthLongestStreak(report.longestStreak),
          color: AppColors.warning,
        ),
        _StatCard(
          icon: Icons.spellcheck_rounded,
          label: l10n.vocabLearnedLabel,
          value: l10n.growthWordsValue(report.vocabLearned),
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
    // 보조기술(TalkBack/VoiceOver)에 '읽은 책 12권'처럼 라벨+값을 한 노드로 안내.
    return Semantics(
      container: true,
      excludeSemantics: true,
      label: '$label $value${sub != null ? ', $sub' : ''}',
      child: Container(
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
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.textSecondary),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 주간 읽기 추이(자기 대비 성장 1차) — 읽기 기록에서 클라이언트 집계 + 지난 주 대비 델타.
class _WeeklyTrend extends StatelessWidget {
  const _WeeklyTrend({required this.counts});

  final List<int> counts;

  String _deltaText(AppLocalizations l) {
    if (counts.length < 2) {
      return l.growthWeekSingle(counts.isEmpty ? 0 : counts.last);
    }
    final last = counts.last;
    final delta = last - counts[counts.length - 2];
    if (delta > 0) {
      return l.growthWeekDeltaUp(last, delta);
    }
    if (delta < 0) {
      return l.growthWeekDeltaDown(last, -delta);
    }
    return l.growthWeekDeltaSame(last);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
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
          Text(l.growthWeeklyTitle, style: AppTextStyles.heading3),
          const SizedBox(height: 2),
          Text(_deltaText(l), style: AppTextStyles.caption),
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
                            i == counts.length - 1
                                ? l.growthWeekThis
                                : l.growthWeekN(i + 1),
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

  // 리그 구분은 이모지로 시각화(로케일 무관). 이름만 번역한다.
  String _leagueEmoji(String medal) {
    switch (medal) {
      case 'gold':
        return '🌳';
      case 'silver':
        return '🌿';
      default:
        return '🌱';
    }
  }

  String _leagueName(String medal, AppLocalizations l) {
    switch (medal) {
      case 'gold':
        return l.growthLeagueMaster;
      case 'silver':
        return l.growthLeagueChallenge;
      default:
        return l.growthLeagueGrowth;
    }
  }

  String _encourage(int topPercent, AppLocalizations l) {
    if (topPercent <= 10) {
      return l.growthEncourageTop;
    }
    if (topPercent <= 30) {
      return l.growthEncourageAhead;
    }
    if (topPercent <= 60) {
      return l.growthEncourageOnPar;
    }
    // 중앙값 미만에도 '따라잡아라'식 열세·추격 프레이밍 대신 자기성장에 초점
    // (아동 사회비교 상향 압박 완화 — 매일 읽는 습관이 성장의 핵심).
    return l.growthEncourageGrow;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    return ref.watch(peerComparisonProvider).maybeWhen(
          data: (peer) =>
              peer.showRanking ? _ranking(peer, l) : _selfGrowth(peer, l),
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
  Widget _selfGrowth(PeerComparison peer, AppLocalizations l) => _shell(children: [
        Text(l.growthSelfGrowthTitle, style: AppTextStyles.heading3),
        const SizedBox(height: AppSpacing.sm),
        Text(
          l.growthSelfGrowthSummary(peer.myBooks, peer.myVocab),
          style: AppTextStyles.body,
        ),
        const SizedBox(height: 4),
        Text(
          l.growthSelfGrowthNote,
          style: const TextStyle(
              fontSize: 12, color: AppColors.textSecondary, height: 1.5),
        ),
      ]);

  Widget _ranking(PeerComparison peer, AppLocalizations l) {
    final subtitle = peer.isBaseline
        ? l.growthPeerSubtitleBaseline(peer.ageBand)
        : l.growthPeerSubtitle(peer.ageBand, peer.peerCount);
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

    addRow(l.growthCompareScoreLabel, peer.myScore.toDouble(),
        peer.peerScore.toDouble(),
        l.growthScorePoints(peer.myScore), l.growthPeerScorePoints(peer.peerScore));
    addRow(l.booksReadLabel, peer.myBooks.toDouble(), peer.peerBooks,
        l.growthBooksValue(peer.myBooks),
        l.growthPeerBooksValue(peer.peerBooks.toStringAsFixed(1)));
    addRow(l.vocabLearnedLabel, peer.myVocab.toDouble(), peer.peerVocab,
        l.growthWordsValue(peer.myVocab),
        l.growthPeerWordsValue(peer.peerVocab.toStringAsFixed(1)));
    addRow(l.quizAccuracyLabel, peer.myAccuracy * 100, peer.peerAccuracy * 100,
        '${(peer.myAccuracy * 100).round()}%',
        l.growthPeerAccuracyPercent((peer.peerAccuracy * 100).round()));

    return _shell(children: [
      Text(l.growthPeerTitle, style: AppTextStyles.heading3),
      const SizedBox(height: 2),
      Text(subtitle, style: AppTextStyles.caption),
      const SizedBox(height: AppSpacing.md),
      Row(
        children: [
          Text(_leagueEmoji(peer.medal),
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
                      l.growthTopPercent(peer.topPercent),
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Flexible(
                      child: Text(_leagueName(peer.medal, l),
                          style: AppTextStyles.bodySmall,
                          overflow: TextOverflow.ellipsis),
                    ),
                  ],
                ),
                Text(_encourage(peer.topPercent, l), style: AppTextStyles.bodySmall),
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
      child: Text(
        AppLocalizations.of(context).growthDisclaimer,
        style: const TextStyle(
            fontSize: 12, color: AppColors.textSecondary, height: 1.5),
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
          Text(AppLocalizations.of(context).growthLoadError),
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
