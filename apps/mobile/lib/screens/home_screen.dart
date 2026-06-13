import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';
import '../widgets/credit_shortage_modal.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';

/// 홈 화면
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
    try {
      final jobId = await ref.read(apiClientProvider).generateTodayStory(
            targetAge: '5-7',
            style: 'watercolor',
          );
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
    final libraryAsync = ref.watch(libraryProvider);
    final streakAsync = ref.watch(homeStreakProvider);
    final growthAsync = ref.watch(growthReportProvider);
    final growthSubtitle = growthAsync.maybeWhen(
      data: (g) => (g.vocabLearned > 0 || g.quizTotal > 0)
          ? '학습 어휘 ${g.vocabLearned}개 · 정확도 ${g.quizTotal > 0 ? (g.quizAccuracy * 100).round() : 0}%'
          : '우리 아이의 읽기 실력이 쌓이는 과정',
      orElse: () => '우리 아이의 읽기 실력이 쌓이는 과정',
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
                        const Expanded(
                          child: Text('AI 동화책', style: AppTextStyles.heading1),
                        ),
                        IconButton(
                          onPressed: () =>
                              Navigator.pushNamed(context, '/settings'),
                          icon: const Icon(Icons.settings_outlined),
                          tooltip: '설정',
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    const Text(
                      '아이를 위한 맞춤 동화를 만들어보세요',
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

            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.xl)),
            const _SectionLabel('오늘의 읽기'),

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
                    message: '스트릭 정보를 불러오지 못했어요.',
                    onRetry: () => ref.invalidate(homeStreakProvider),
                  ),
                ),
              ),
            ),

            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.lg)),
            const _SectionLabel('부모님께'),

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
                    const Text('최근 만든 책', style: AppTextStyles.heading3),
                    TextButton(
                      onPressed: () => Navigator.pushNamed(context, '/library'),
                      child: Text(
                        '전체 보기',
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
                  return const SliverToBoxAdapter(
                    child: Padding(
                      padding: EdgeInsets.all(AppSpacing.xl),
                      child: EmptyState(
                        icon: Icons.auto_stories_outlined,
                        title: '아직 만든 책이 없어요',
                        subtitle: '첫 번째 동화책을 만들어보세요!',
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
                    title: '책을 불러올 수 없어요',
                    subtitle: error.toString(),
                    buttonText: '다시 시도',
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
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '새 동화책 만들기',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  SizedBox(height: AppSpacing.sm),
                  Text(
                    '우리 아이가 주인공인\n맞춤 동화를 만들어요',
                    style: TextStyle(
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
    final recentDays = _recentDays(data.readDates);

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
                  '${data.currentStreak}일 연속 읽기',
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
                  data.readToday ? '오늘 읽음' : '오늘 미완료',
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '총 ${data.totalDays}일 읽었어요 · 최고 ${data.longestStreak}일',
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          _TodayStoryPanel(
            themeName: data.todayThemeName,
            topic: data.todayTopic,
            hasTodayBook: data.todayBookId != null,
            onTap: onTapPrimary,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            '최근 7일',
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

  List<_RecentDayEntry> _recentDays(Set<String> readDates) {
    final now = DateTime.now();
    final entries = <_RecentDayEntry>[];
    for (var i = 6; i >= 0; i--) {
      final date = now.subtract(Duration(days: i));
      final key =
          '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
      entries.add(
        _RecentDayEntry(
          label: _weekdayLabel(date.weekday),
          read: readDates.contains(key),
        ),
      );
    }
    return entries;
  }

  String _weekdayLabel(int weekday) {
    switch (weekday) {
      case DateTime.monday:
        return '월';
      case DateTime.tuesday:
        return '화';
      case DateTime.wednesday:
        return '수';
      case DateTime.thursday:
        return '목';
      case DateTime.friday:
        return '금';
      case DateTime.saturday:
        return '토';
      case DateTime.sunday:
        return '일';
      default:
        return '-';
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
            '오늘의 동화 · $themeName',
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
            text: hasTodayBook ? '이어 읽기' : '오늘 동화 만들기',
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
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: const Row(
        children: [
          SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: AppSpacing.sm),
          Text('스트릭 정보를 불러오는 중...'),
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
          const Row(
            children: [
              Icon(Icons.error_outline, color: AppColors.error),
              SizedBox(width: AppSpacing.sm),
              Text('스트릭 카드 오류', style: AppTextStyles.heading3),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(message, style: AppTextStyles.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextButton(
            onPressed: onRetry,
            child: const Text('다시 시도'),
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
                  const Text('읽기 성장 보기', style: AppTextStyles.heading3),
                  const SizedBox(height: 2),
                  Text(
                    subtitle ?? '우리 아이의 읽기 실력이 쌓이는 과정',
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
