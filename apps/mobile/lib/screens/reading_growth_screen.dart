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
/// 레벨 라벨 — **안정 키 우선**(S2, M5 원칙과 동일).
///
/// 서버가 `reading_level.key`(first_steps 등)를 주므로 앱이 자체 l10n 으로 그린다.
/// 서버 `label`(사용자 언어로 로컬라이즈됨)은 키를 모를 때의 폴백이고, 둘 다 없으면
/// 일반 문구로 떨어진다 — 어느 경로에서도 한국어가 en/ja 사용자에게 새지 않는다.
String _levelLabel(AppLocalizations l, GrowthReport report) {
  switch (report.levelKey) {
    case 'first_steps':
      return l.growthLevelFirstSteps;
    case 'building_basics':
      return l.growthLevelBuildingBasics;
    case 'steady_growth':
      return l.growthLevelSteadyGrowth;
    case 'reading_leap':
      return l.growthLevelReadingLeap;
    case 'fluent_reader':
      return l.growthLevelFluentReader;
  }
  final label = report.levelLabel.trim();
  return label.isEmpty ? l.growthLevelFallbackLabel : label;
}

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
      backgroundColor: AppPalette.of(context).background,
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).readingGrowthTitle),
        backgroundColor: AppPalette.of(context).surface,
        foregroundColor: AppPalette.of(context).textPrimary,
        elevation: 0,
      ),
      body: SafeArea(
        top: false,
        child: reportAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (err, _) => _ErrorView(
            onRetry: () => ref.invalidate(growthReportProvider),
          ),
          data: (report) => RefreshIndicator(
            onRefresh: () => ref.refresh(growthReportProvider.future),
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
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
        _levelLabel(l, report),
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
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.growthCtaTitle, style: AppTextStyles.heading3),
          const SizedBox(height: AppSpacing.xs),
          Text(
            l.growthCtaSubtitle,
            style: AppTextStyles.caption
                .copyWith(color: AppPalette.of(context).textHint),
          ),
          const SizedBox(height: AppSpacing.md),
          LayoutBuilder(builder: (context, constraints) {
            final stacked = constraints.maxWidth < 360 ||
                MediaQuery.textScalerOf(context).scale(16) > 20;
            final buttons = [
              Semantics(
                button: true,
                label: l.growthShareSemantic,
                child: Builder(builder: (buttonContext) {
                  return OutlinedButton.icon(
                    key: const Key('growth_share_btn'),
                    onPressed: () async {
                      final box =
                          buttonContext.findRenderObject() as RenderBox?;
                      try {
                        await Share.share(
                          _shareText(l),
                          sharePositionOrigin: box == null
                              ? null
                              : box.localToGlobal(Offset.zero) & box.size,
                        );
                      } catch (_) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(l.libraryShareFailed)),
                          );
                        }
                      }
                    },
                    icon: const Icon(Icons.ios_share, size: 18),
                    label:
                        Text(l.growthShareButton, textAlign: TextAlign.center),
                  );
                }),
              ),
              Semantics(
                button: true,
                label: l.growthCreateSemantic,
                child: ElevatedButton.icon(
                  key: const Key('growth_create_btn'),
                  onPressed: () => Navigator.pushNamed(context, '/create'),
                  icon: const Icon(Icons.auto_stories, size: 18),
                  label:
                      Text(l.growthCreateButton, textAlign: TextAlign.center),
                ),
              ),
            ];
            if (stacked) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  buttons[0],
                  const SizedBox(height: AppSpacing.sm),
                  buttons[1]
                ],
              );
            }
            return Row(
              children: [
                Expanded(child: buttons[0]),
                const SizedBox(width: AppSpacing.sm),
                Expanded(child: buttons[1]),
              ],
            );
          }),
        ],
      ),
    );
  }
}

class _LevelHero extends StatelessWidget {
  const _LevelHero({required this.report});

  final GrowthReport report;

  String _confidenceStars(int books) => books >= 13
      ? '⭐⭐⭐'
      : books >= 5
          ? '⭐⭐'
          : '⭐';

  String _confidenceText(int books, AppLocalizations l) => books >= 13
      ? l.growthConfidenceHigh
      : books >= 5
          ? l.growthConfidenceMedium
          : l.growthConfidenceLow;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final progress = (report.scoreValue / 100).clamp(0.0, 1.0);
    const solidPalette = AppPalette(false);
    // 보조기술(TalkBack/VoiceOver)에 핵심 지표를 하나의 명료한 문장으로 읽어준다
    // (시각적 막대·분리된 텍스트 대신 통합 라벨).
    return Semantics(
      container: true,
      excludeSemantics: true,
      label: l.growthHeroSemantic(
        report.levelNumber,
        _levelLabel(l, report),
        report.scoreValue,
        _confidenceText(report.booksRead, l),
      ),
      child: Container(
        key: const Key('growth_level_hero'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: solidPalette.primary,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.xs,
              children: [
                Text(
                  AppLocalizations.of(context).estimatedReadingLevel,
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                ),
                Text(
                  '${_confidenceStars(report.booksRead)} '
                  '${_confidenceText(report.booksRead, l)}',
                  style: const TextStyle(color: Colors.white, fontSize: 11),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  'Lv.${report.levelNumber}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 40,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(
                  _levelLabel(l, report),
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
              style: const TextStyle(color: Colors.white, fontSize: 12),
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
    final accuracyLabel =
        report.quizTotal > 0 ? '${(report.quizAccuracy * 100).round()}%' : '—';
    final cards = [
      _StatCard(
        icon: Icons.menu_book_rounded,
        label: l10n.booksReadLabel,
        value: l10n.growthBooksValue(report.booksRead),
        color: AppPalette.of(context).primary,
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
        sub: report.quizTotal > 0
            ? '${report.quizCorrect}/${report.quizTotal}'
            : null,
        color: AppColors.success,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final minCardWidth = MediaQuery.textScalerOf(context).scale(135);
        final columns =
            constraints.maxWidth >= minCardWidth * 2 + AppSpacing.sm ? 2 : 1;
        final width =
            (constraints.maxWidth - AppSpacing.sm * (columns - 1)) / columns;
        return Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final card in cards) SizedBox(width: width, child: card)
          ],
        );
      },
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
          color: AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppPalette.of(context).divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: color, size: 22),
            const SizedBox(height: AppSpacing.sm),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: AppPalette.of(context).textPrimary,
                  ),
                ),
                Text(
                  sub == null ? label : '$label · $sub',
                  style: TextStyle(
                      fontSize: 12,
                      color: AppPalette.of(context).textSecondary),
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
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.growthWeeklyTitle, style: AppTextStyles.heading3),
          const SizedBox(height: 2),
          Text(_deltaText(l), style: AppTextStyles.caption),
          const SizedBox(height: AppSpacing.md),
          SizedBox(
            height: 92 + MediaQuery.textScalerOf(context).scale(48),
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
                              color: AppPalette.of(context).textSecondary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Container(
                            height: 8 + (counts[i] / maxC) * 64,
                            decoration: BoxDecoration(
                              gradient: LinearGradient(
                                colors: [
                                  AppPalette.of(context).primary,
                                  AppColors.primaryHalf
                                ],
                                begin: Alignment.topCenter,
                                end: Alignment.bottomCenter,
                              ),
                              borderRadius: const BorderRadius.vertical(
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
                            textAlign: TextAlign.center,
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
          data: (peer) => peer.showRanking
              ? _ranking(context, peer, l)
              : _selfGrowth(context, peer, l),
          orElse: () => const SizedBox.shrink(),
        );
  }

  Widget _shell(BuildContext context, {required List<Widget> children}) =>
      Container(
        key: const Key('growth_peer_comparison'),
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppPalette.of(context).divider),
        ),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: children),
      );

  // 3-5세: 등수·백분위는 발달상 무의미 → 자기 성장만(사회비교 배제).
  Widget _selfGrowth(
          BuildContext context, PeerComparison peer, AppLocalizations l) =>
      _shell(context, children: [
        Text(l.growthSelfGrowthTitle, style: AppTextStyles.heading3),
        const SizedBox(height: AppSpacing.sm),
        Text(
          l.growthSelfGrowthSummary(peer.myBooks, peer.myVocab),
          style: AppTextStyles.body,
        ),
        const SizedBox(height: 4),
        Text(
          l.growthSelfGrowthNote,
          style: TextStyle(
              fontSize: 12,
              color: AppPalette.of(context).textSecondary,
              height: 1.5),
        ),
      ]);

  Widget _ranking(
      BuildContext context, PeerComparison peer, AppLocalizations l) {
    final subtitle = peer.isBaseline
        ? l.growthPeerSubtitleBaseline(peer.ageBand)
        : l.growthPeerSubtitle(peer.ageBand, peer.peerCount);
    final rows = <Widget>[];
    void addRow(String label, double mine, double peer, String mineText,
        String peerText) {
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

    addRow(
        l.growthCompareScoreLabel,
        peer.myScore.toDouble(),
        peer.peerScore.toDouble(),
        l.growthScorePoints(peer.myScore),
        l.growthPeerScorePoints(peer.peerScore));
    addRow(
        l.booksReadLabel,
        peer.myBooks.toDouble(),
        peer.peerBooks,
        l.growthBooksValue(peer.myBooks),
        l.growthPeerBooksValue(peer.peerBooks.toStringAsFixed(1)));
    addRow(
        l.vocabLearnedLabel,
        peer.myVocab.toDouble(),
        peer.peerVocab,
        l.growthWordsValue(peer.myVocab),
        l.growthPeerWordsValue(peer.peerVocab.toStringAsFixed(1)));
    addRow(
        l.quizAccuracyLabel,
        peer.myAccuracy * 100,
        peer.peerAccuracy * 100,
        '${(peer.myAccuracy * 100).round()}%',
        l.growthPeerAccuracyPercent((peer.peerAccuracy * 100).round()));

    return _shell(context, children: [
      Text(l.growthPeerTitle, style: AppTextStyles.heading3),
      const SizedBox(height: 2),
      Text(subtitle, style: AppTextStyles.caption),
      const SizedBox(height: AppSpacing.md),
      Row(
        children: [
          Text(_leagueEmoji(peer.medal), style: const TextStyle(fontSize: 30)),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: AppSpacing.sm,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      l.growthTopPercent(peer.topPercent),
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: AppPalette.of(context).primary,
                      ),
                    ),
                    Text(_leagueName(peer.medal, l),
                        style: AppTextStyles.bodySmall),
                  ],
                ),
                Text(_encourage(peer.topPercent, l),
                    style: AppTextStyles.bodySmall),
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
          Text(label, style: AppTextStyles.bodySmall),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            children: [
              Text(
                mineText,
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppPalette.of(context).primary,
                ),
              ),
              Text(peerText, style: AppTextStyles.caption),
            ],
          ),
          const SizedBox(height: 6),
          _bar(context, mine / maxV, AppPalette.of(context).primary),
          const SizedBox(height: 4),
          _bar(context, peerValue / maxV, AppPalette.of(context).textHint),
        ],
      ),
    );
  }

  Widget _bar(BuildContext context, double ratio, Color color) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: LinearProgressIndicator(
        value: ratio.clamp(0.0, 1.0),
        minHeight: 8,
        backgroundColor: AppPalette.of(context).background,
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
        color: AppPalette.of(context).primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Text(
        AppLocalizations.of(context).growthDisclaimer,
        style: TextStyle(
            fontSize: 12,
            color: AppPalette.of(context).textSecondary,
            height: 1.5),
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
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(AppLocalizations.of(context).growthLoadError,
                textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(
              onPressed: onRetry,
              child: Text(AppLocalizations.of(context).retry),
            ),
          ],
        ),
      ),
    );
  }
}
