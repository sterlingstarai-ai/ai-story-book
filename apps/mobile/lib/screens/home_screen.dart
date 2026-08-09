import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';
import '../widgets/credit_shortage_modal.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';

/// 홈 화면
/// H25: 서버가 내려주는 안정 theme id → 로케일 표시명(미지 id는 서버 폴백).
String dailyThemeLabel(AppLocalizations l, String themeId, String fallback) {
  // M6: 서버가 값을 주지 않으면 로케일 폴백(이전엔 provider 가 한국어를 채웠다).
  if (themeId.isEmpty && fallback.isEmpty) return l.homeTodayFallbackTheme;
  switch (themeId) {
    case 'friendship':
      return l.dailyThemeFriendship;
    case 'courage':
      return l.dailyThemeCourage;
    case 'kindness':
      return l.dailyThemeKindness;
    case 'family':
      return l.dailyThemeFamily;
    case 'nature':
      return l.dailyThemeNature;
    case 'growth':
      return l.dailyThemeGrowth;
    case 'imagination':
      return l.dailyThemeImagination;
    default:
      return fallback.isNotEmpty ? fallback : themeId;
  }
}

/// H25: 서버 topic_id('theme_idx') → 로케일 표시 토픽(미지 id는 서버 폴백).
String dailyTopicLabel(AppLocalizations l, String topicId, String fallback) {
  if (topicId.isEmpty && fallback.isEmpty) return l.homeTodayFallbackTopic;
  switch (topicId) {
    case 'friendship_0':
      return l.dailyTopicFriendship0;
    case 'friendship_1':
      return l.dailyTopicFriendship1;
    case 'friendship_2':
      return l.dailyTopicFriendship2;
    case 'friendship_3':
      return l.dailyTopicFriendship3;
    case 'courage_0':
      return l.dailyTopicCourage0;
    case 'courage_1':
      return l.dailyTopicCourage1;
    case 'courage_2':
      return l.dailyTopicCourage2;
    case 'courage_3':
      return l.dailyTopicCourage3;
    case 'kindness_0':
      return l.dailyTopicKindness0;
    case 'kindness_1':
      return l.dailyTopicKindness1;
    case 'kindness_2':
      return l.dailyTopicKindness2;
    case 'kindness_3':
      return l.dailyTopicKindness3;
    case 'family_0':
      return l.dailyTopicFamily0;
    case 'family_1':
      return l.dailyTopicFamily1;
    case 'family_2':
      return l.dailyTopicFamily2;
    case 'family_3':
      return l.dailyTopicFamily3;
    case 'nature_0':
      return l.dailyTopicNature0;
    case 'nature_1':
      return l.dailyTopicNature1;
    case 'nature_2':
      return l.dailyTopicNature2;
    case 'nature_3':
      return l.dailyTopicNature3;
    case 'growth_0':
      return l.dailyTopicGrowth0;
    case 'growth_1':
      return l.dailyTopicGrowth1;
    case 'growth_2':
      return l.dailyTopicGrowth2;
    case 'growth_3':
      return l.dailyTopicGrowth3;
    case 'imagination_0':
      return l.dailyTopicImagination0;
    case 'imagination_1':
      return l.dailyTopicImagination1;
    case 'imagination_2':
      return l.dailyTopicImagination2;
    case 'imagination_3':
      return l.dailyTopicImagination3;
    default:
      return fallback;
  }
}

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  /// 오늘의 동화 카드 기본 액션.
  /// 오늘 책이 있으면 바로 읽고, 없으면 오늘의 테마로 *원탭 개인화 생성*(B3) → 로딩.
  /// 크레딧/한도 등 실패 시 일반 생성 화면으로 폴백한다(기존 동작 유지).
  Future<void> _onTodayPrimary(
    BuildContext context,
    WidgetRef ref,
    HomeStreakSnapshot streak,
  ) async {
    if (streak.todayBookId != null) {
      Navigator.pushNamed(context, '/viewer', arguments: streak.todayBookId);
      return;
    }
    ref.read(analyticsProvider).logEvent(AnalyticsEvents.todayStoryRequested);
    // 오늘의 동화도 앱 로케일 언어로 생성(영/일 UI에서 한국어 동화 방지).
    final language = Localizations.localeOf(context).languageCode;
    // H18: 시도-단위 멱등키(재시도 시 재사용, 성공 시 리셋) → 재탭 이중 생성·차감 방지.
    final keyNotifier = ref.read(todayAttemptKeyProvider.notifier);
    final sigNotifier = ref.read(todayAttemptSigProvider.notifier);
    // #20: 날짜가 바뀌면 새 키 — 어제 실패한 키로 오늘 요청하면 서버가 어제 잡을 반환한다.
    final now = DateTime.now();
    final todaySig =
        '${now.year}-${now.month}-${now.day}|$language';
    if (keyNotifier.state == null || sigNotifier.state != todaySig) {
      keyNotifier.state = const Uuid().v4();
      sigNotifier.state = todaySig;
    }
    try {
      final jobId = await ref.read(apiClientProvider).generateTodayStory(
            targetAge: '5-7',
            style: 'watercolor',
            language: language,
            idempotencyKey: keyNotifier.state,
          );
      keyNotifier.state = null; // 성공 → 다음 생성은 새 키
      sigNotifier.state = null;
      if (context.mounted) {
        Navigator.pushReplacementNamed(context, '/loading', arguments: jobId);
      }
    } catch (_) {
      // 크레딧 부족·무료한도 등 → 일반 생성 화면으로 폴백
      if (context.mounted) {
        await showCreditShortageModal(context);
        if (context.mounted) {
          Navigator.pushNamed(context, '/create');
        }
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final libraryAsync = ref.watch(libraryProvider);
    final charactersAsync = ref.watch(charactersProvider);
    final streakAsync = ref.watch(homeStreakProvider);
    final growthAsync = ref.watch(growthReportProvider);
    final growthSubtitle = growthAsync.maybeWhen(
      data: (g) => (g.vocabLearned > 0 || g.quizTotal > 0)
          ? l.homeGrowthSubtitleStats(g.vocabLearned,
              g.quizTotal > 0 ? (g.quizAccuracy * 100).round() : 0)
          : l.readingGrowthEntrySubtitle,
      orElse: () => l.readingGrowthEntrySubtitle,
    );

    return AppShell(
      currentIndex: 0,
      body: SafeArea(
        child: CustomScrollView(
          slivers: [
            // 헤더
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child:
                              Text(l.homeTitle, style: AppTextStyles.heading1),
                        ),
                        IconButton(
                          onPressed: () =>
                              Navigator.pushNamed(context, '/settings'),
                          icon: const Icon(Icons.settings_outlined),
                          tooltip: l.homeSettingsTooltip,
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      l.homeHeaderSubtitle,
                      style: AppTextStyles.bodySmall,
                    ),
                  ],
                ),
              ),
            ),

            // 새 책 만들기 카드
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: _CreateBookCard(
                  onTap: () => Navigator.pushNamed(context, '/create'),
                ),
              ),
            ),

            // 사진→캐릭터 진입 (프라이버시 신뢰 메시지 포함)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 0),
                child: _PhotoCharacterCard(
                  onTap: () => Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {'startPhotoCharacter': true},
                  ),
                ),
              ),
            ),

            // 캐릭터-퍼스트 진입: 저장된 캐릭터로 바로 새 책 만들기
            charactersAsync.maybeWhen(
              data: (characters) => characters.isEmpty
                  ? const SliverToBoxAdapter(child: SizedBox.shrink())
                  : SliverToBoxAdapter(
                      child: Padding(
                        padding: const EdgeInsets.only(top: AppSpacing.lg),
                        child: _CharacterQuickStartRow(
                          characters: characters.take(8).toList(),
                          onSelect: (id) => Navigator.pushNamed(
                            context,
                            '/create',
                            arguments: {
                              'characterIds': [id],
                            },
                          ),
                        ),
                      ),
                    ),
              orElse: () => const SliverToBoxAdapter(child: SizedBox.shrink()),
            ),

            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.xl)),
            _SectionLabel(l.homeSectionTodayReading),

            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: streakAsync.when(
                  data: (streak) => _StreakSummaryCard(
                    data: streak,
                    onTapPrimary: () => _onTodayPrimary(context, ref, streak),
                  ),
                  loading: () => const _StreakLoadingCard(),
                  error: (error, _) => _StreakErrorCard(
                    message: l.homeStreakLoadError,
                    onRetry: () => ref.invalidate(homeStreakProvider),
                  ),
                ),
              ),
            ),

            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.lg)),
            _SectionLabel(l.homeSectionForParents),

            // 읽기 성장 진입
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: _GrowthEntryCard(
                  subtitle: growthSubtitle,
                  onTap: () => Navigator.pushNamed(context, '/reading-growth'),
                ),
              ),
            ),

            const SliverToBoxAdapter(
              child: SizedBox(height: AppSpacing.xl),
            ),

            // 최근 책 섹션
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(l.homeRecentBooksTitle, style: AppTextStyles.heading3),
                    TextButton(
                      onPressed: () => Navigator.pushNamed(context, '/library'),
                      child: Text(
                        l.homeViewAll,
                        style: AppTextStyles.bodySmall.copyWith(
                          color: AppColors.primary,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // 최근 책 목록
            libraryAsync.when(
              data: (books) {
                if (books.isEmpty) {
                  return SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.all(AppSpacing.xl),
                      child: EmptyState(
                        icon: Icons.auto_stories_outlined,
                        title: l.homeEmptyTitle,
                        subtitle: l.homeEmptySubtitle,
                      ),
                    ),
                  );
                }

                final recentBooks = books.take(4).toList();
                return SliverPadding(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  sliver: SliverGrid(
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      mainAxisSpacing: AppSpacing.md,
                      crossAxisSpacing: AppSpacing.md,
                      childAspectRatio: 0.65,
                    ),
                    delegate: SliverChildBuilderDelegate(
                      (context, index) {
                        final book = recentBooks[index];
                        return BookCard(
                          title: book.title,
                          imageUrl: book.coverImageUrl,
                          subtitle: book.theme,
                          onTap: () => Navigator.pushNamed(
                            context,
                            '/viewer',
                            arguments: book.id,
                          ),
                        );
                      },
                      childCount: recentBooks.length,
                    ),
                  ),
                );
              },
              loading: () => const SliverToBoxAdapter(
                child: Center(
                  child: Padding(
                    padding: EdgeInsets.all(AppSpacing.xl),
                    child: CircularProgressIndicator(),
                  ),
                ),
              ),
              error: (error, _) => SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: EmptyState(
                    icon: Icons.error_outline,
                    title: l.homeLibraryErrorTitle,
                    subtitle: error.toString(),
                    buttonText: l.retry,
                    onButtonPressed: () => ref.invalidate(libraryProvider),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 새 책 만들기 카드
class _CreateBookCard extends StatelessWidget {
  final VoidCallback onTap;

  const _CreateBookCard({required this.onTap});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [AppColors.primary, AppColors.secondary],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(AppRadius.xl),
          boxShadow: const [
            BoxShadow(
              color: AppColors.primaryStrong,
              blurRadius: 20,
              offset: Offset(0, 8),
            ),
          ],
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l.homeCreateCardTitle,
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    l.homeCreateCardSubtitle,
                    style: const TextStyle(
                      fontSize: 14,
                      color: AppColors.whiteOverlayStrong,
                    ),
                  ),
                ],
              ),
            ),
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: AppColors.whiteOverlay,
                borderRadius: BorderRadius.circular(AppRadius.lg),
              ),
              child: const Icon(
                Icons.add_rounded,
                size: 36,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StreakSummaryCard extends StatelessWidget {
  final HomeStreakSnapshot data;
  final VoidCallback onTapPrimary;

  const _StreakSummaryCard({
    required this.data,
    required this.onTapPrimary,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final recentDays = _recentDays(context, data.readDates);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [
            Color(0xFFFFEDD5),
            Color(0xFFFFFBEB),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(
          color: const Color(0xFFFED7AA),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('🔥', style: TextStyle(fontSize: 24)),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  l.homeStreakDaysLabel(data.currentStreak),
                  style: AppTextStyles.heading3,
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  color: data.readToday
                      ? AppColors.successLight
                      : AppColors.blackOverlayLight,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  data.readToday
                      ? l.homeReadTodayBadge
                      : l.homeNotReadTodayBadge,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l.homeStreakSummary(data.totalDays, data.longestStreak),
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          _TodayStoryPanel(
            themeName: dailyThemeLabel(l, data.todayThemeId, data.todayThemeName),
            topic: dailyTopicLabel(l, data.todayTopicId, data.todayTopic),
            hasTodayBook: data.todayBookId != null,
            onTap: onTapPrimary,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            l.homeRecent7Days,
            style: AppTextStyles.caption.copyWith(
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: recentDays
                .map((entry) => _RecentDayDot(
                      weekday: entry.label,
                      read: entry.read,
                    ))
                .toList(),
          ),
        ],
      ),
    );
  }

  List<_RecentDayEntry> _recentDays(
      BuildContext context, Set<String> readDates) {
    final now = DateTime.now();
    final entries = <_RecentDayEntry>[];
    for (var i = 6; i >= 0; i--) {
      final date = now.subtract(Duration(days: i));
      final key =
          '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
      entries.add(
        _RecentDayEntry(
          label: _weekdayLabel(context, date.weekday),
          read: readDates.contains(key),
        ),
      );
    }
    return entries;
  }

  String _weekdayLabel(BuildContext context, int weekday) {
    final l = AppLocalizations.of(context);
    switch (weekday) {
      case DateTime.monday:
        return l.homeWeekdayMon;
      case DateTime.tuesday:
        return l.homeWeekdayTue;
      case DateTime.wednesday:
        return l.homeWeekdayWed;
      case DateTime.thursday:
        return l.homeWeekdayThu;
      case DateTime.friday:
        return l.homeWeekdayFri;
      case DateTime.saturday:
        return l.homeWeekdaySat;
      case DateTime.sunday:
        return l.homeWeekdaySun;
      default:
        return l.homeWeekdayUnknown;
    }
  }
}

class _TodayStoryPanel extends StatelessWidget {
  final String themeName;
  final String topic;
  final bool hasTodayBook;
  final VoidCallback onTap;

  const _TodayStoryPanel({
    required this.themeName,
    required this.topic,
    required this.hasTodayBook,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.homeTodayStoryLabel(themeName),
            style: AppTextStyles.caption.copyWith(
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            topic,
            style: AppTextStyles.body,
          ),
          const SizedBox(height: AppSpacing.sm),
          PrimaryButton(
            text: hasTodayBook ? l.homeContinueReading : l.homeMakeTodayStory,
            onPressed: onTap,
            isFullWidth: false,
          ),
        ],
      ),
    );
  }
}

class _RecentDayDot extends StatelessWidget {
  final String weekday;
  final bool read;

  const _RecentDayDot({
    required this.weekday,
    required this.read,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 18,
          height: 18,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: read ? AppColors.success : AppColors.divider,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          weekday,
          style: AppTextStyles.caption,
        ),
      ],
    );
  }
}

class _StreakLoadingCard extends StatelessWidget {
  const _StreakLoadingCard();

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(l.homeStreakLoading),
        ],
      ),
    );
  }
}

class _StreakErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _StreakErrorCard({
    required this.message,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
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
              const Icon(Icons.error_outline, color: AppColors.error),
              const SizedBox(width: AppSpacing.sm),
              Text(l.homeStreakErrorTitle, style: AppTextStyles.heading3),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(message, style: AppTextStyles.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextButton(
            onPressed: onRetry,
            child: Text(l.retry),
          ),
        ],
      ),
    );
  }
}

class _RecentDayEntry {
  final String label;
  final bool read;

  const _RecentDayEntry({
    required this.label,
    required this.read,
  });
}

/// 홈에서 '읽기 성장' 리포트로 가는 진입 카드.
class _GrowthEntryCard extends StatelessWidget {
  const _GrowthEntryCard({required this.onTap, this.subtitle});

  final VoidCallback onTap;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: Container(
        key: const Key('home_growth_entry'),
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.divider),
          boxShadow: const [
            BoxShadow(
              color: AppColors.blackOverlayShadow,
              blurRadius: 10,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(AppSpacing.sm),
              decoration: BoxDecoration(
                color: AppColors.primaryLight,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: const Icon(Icons.trending_up_rounded,
                  color: AppColors.primary, size: 22),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l.homeGrowthEntryTitle, style: AppTextStyles.heading3),
                  const SizedBox(height: 2),
                  Text(
                    subtitle ?? l.readingGrowthEntrySubtitle,
                    style: AppTextStyles.bodySmall,
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.textHint),
          ],
        ),
      ),
    );
  }
}

/// 홈 섹션 구분 라벨(C1: 위계·여백 정제).
class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return SliverToBoxAdapter(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg + 2, 0, AppSpacing.lg, AppSpacing.sm + 2),
        child: Text(
          text,
          style: AppTextStyles.bodySmall.copyWith(
            fontWeight: FontWeight.w700,
            color: AppColors.textHint,
          ),
        ),
      ),
    );
  }
}

/// 사진→캐릭터 진입 카드 — 탭하면 생성 화면에서 사진/캐릭터 시트를 바로 연다.
class _PhotoCharacterCard extends StatelessWidget {
  const _PhotoCharacterCard({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.divider),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(AppSpacing.sm),
              decoration: BoxDecoration(
                color: AppColors.secondaryLight,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: const Icon(Icons.face_retouching_natural,
                  color: AppColors.secondary, size: 22),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l.homePhotoCharacterTitle,
                      style: AppTextStyles.heading3),
                  const SizedBox(height: 2),
                  Text(l.homePhotoCharacterSubtitle,
                      style: AppTextStyles.bodySmall),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.textHint),
          ],
        ),
      ),
    );
  }
}

/// 캐릭터-퍼스트 진입 행 — 저장된 캐릭터를 가로로 보여주고,
/// 탭하면 그 캐릭터로 바로 새 책 생성 화면을 연다.
class _CharacterQuickStartRow extends StatelessWidget {
  final List<Character> characters;
  final void Function(String characterId) onSelect;

  const _CharacterQuickStartRow({
    required this.characters,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg + 2, 0, AppSpacing.lg, AppSpacing.sm),
          child: Text(
            l.homeQuickStartTitle,
            style: AppTextStyles.bodySmall.copyWith(
              fontWeight: FontWeight.w700,
              color: AppColors.textHint,
            ),
          ),
        ),
        SizedBox(
          height: 96,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            itemCount: characters.length,
            separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.md),
            itemBuilder: (context, index) {
              final character = characters[index];
              return _CharacterQuickStartChip(
                name: character.name,
                onTap: () => onSelect(character.id),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// 캐릭터-퍼스트 행의 개별 칩(아바타 + 이름).
class _CharacterQuickStartChip extends StatelessWidget {
  final String name;
  final VoidCallback onTap;

  const _CharacterQuickStartChip({
    required this.name,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final initial = name.isNotEmpty ? name.substring(0, 1) : '?';
    return GestureDetector(
      onTap: onTap,
      child: SizedBox(
        width: 64,
        child: Column(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: AppColors.primaryLight,
                shape: BoxShape.circle,
                border: Border.all(color: AppColors.primaryMedium),
              ),
              child: Text(
                initial,
                style:
                    AppTextStyles.heading3.copyWith(color: AppColors.primary),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: AppTextStyles.caption,
            ),
          ],
        ),
      ),
    );
  }
}
