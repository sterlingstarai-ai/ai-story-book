import 'dart:async';

import '../providers/active_child_profile.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';
import '../widgets/scoped_book_image.dart';
import '../widgets/credit_shortage_modal.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../services/api_client.dart';
import '../services/page_audio_playback.dart';

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

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  ApiClient? _todayStoryApi;

  /// 오늘의 동화 카드 기본 액션.
  /// 오늘 책은 바로 열고, 무료 첫 권은 만들기 화면에서 설정을 확인한다.
  /// 과금 제한은 안내하고, 다른 생성 실패는 일반 생성 화면에서 다시 시도한다.
  Future<void> _onTodayPrimary(
    HomeStreakSnapshot streak,
    bool firstBookTrial,
    bool reviewBeforeCreating,
  ) async {
    if (ModalRoute.of(context)?.isCurrent == false) return;
    if (streak.todayBookId != null) {
      Navigator.pushNamed(context, '/viewer', arguments: streak.todayBookId);
      return;
    }
    if (reviewBeforeCreating) {
      ref.read(analyticsProvider).logEvent(AnalyticsEvents.todayStoryRequested);
      final l = AppLocalizations.of(context);
      Navigator.pushNamed(
        context,
        '/create',
        arguments: {
          'topic': dailyTopicLabel(l, streak.todayTopicId, streak.todayTopic),
        },
      );
      return;
    }
    final api = ref.read(apiClientProvider);
    if (identical(_todayStoryApi, api)) return;
    ref.read(analyticsProvider).logEvent(AnalyticsEvents.todayStoryRequested);
    // 오늘의 동화도 앱 로케일 언어로 생성(영/일 UI에서 한국어 동화 방지).
    final language = Localizations.localeOf(context).languageCode;
    // H18: 시도-단위 멱등키(재시도 시 재사용, 성공 시 리셋) → 재탭 이중 생성·차감 방지.
    final keyNotifier = ref.read(todayAttemptKeyProvider.notifier);
    final sigNotifier = ref.read(todayAttemptSigProvider.notifier);
    // #20: 날짜가 바뀌면 새 키 — 어제 실패한 키로 오늘 요청하면 서버가 어제 잡을 반환한다.
    final now = DateTime.now();
    final todaySig = '${now.year}-${now.month}-${now.day}|$language';
    // A capability refresh during a retry must not change the requested age.
    final previousSig = sigNotifier.state;
    final String age;
    if (keyNotifier.state != null &&
        previousSig != null &&
        previousSig.startsWith('$todaySig|')) {
      age = previousSig.substring(todaySig.length + 1);
    } else {
      final profile = ref.read(activeChildProfileProvider).valueOrNull;
      age =
          (firstBookTrial
                  ? profile?.targetAge ?? TargetAge.age3to5
                  : TargetAge.age5to7)
              .value;
      keyNotifier.state = const Uuid().v4();
      sigNotifier.state = '$todaySig|$age';
    }
    setState(() => _todayStoryApi = api);
    try {
      final jobId = await api.generateTodayStory(
        targetAge: age,
        style: 'watercolor',
        language: language,
        idempotencyKey: keyNotifier.state,
      );
      if (!mounted || !identical(api, ref.read(apiClientProvider))) return;
      keyNotifier.state = null; // 성공 → 다음 생성은 새 키
      sigNotifier.state = null;
      ref.invalidate(generationOptionsProvider);
      ref.invalidate(activeBookGenerationsProvider);
      if (ModalRoute.of(context)?.isCurrent != false) {
        Navigator.pushReplacementNamed(context, '/loading', arguments: jobId);
      }
    } catch (error) {
      if (!mounted ||
          !identical(api, ref.read(apiClientProvider)) ||
          ModalRoute.of(context)?.isCurrent == false) {
        return;
      }
      final apiError = error is DioException ? error.error : error;
      if (apiError is ApiError && apiError.code == 'PAYMENT_REQUIRED') {
        unawaited(
          showCreditShortageModal(
            context,
            preferCreditPack: !apiError.isPlanUpgradeRequired,
          ),
        );
        return;
      }
      Navigator.pushNamed(context, '/create');
    } finally {
      if (mounted && identical(_todayStoryApi, api)) {
        setState(() => _todayStoryApi = null);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final colors = StorybookColors.of(context);
    final submittingTodayStory =
        _todayStoryApi != null &&
        identical(_todayStoryApi, ref.watch(apiClientProvider));
    final libraryAsync = ref.watch(libraryProvider);
    final activeJobs = ref.watch(visibleActiveBookGenerationsProvider);
    ref.listen(activeBookGenerationsProvider, (previous, next) {
      if (activeBookGenerationMayHaveFinished(previous, next)) {
        ref.invalidate(libraryProvider);
      }
    });
    final charactersAsync = ref.watch(charactersProvider);
    final streakAsync = ref.watch(homeStreakProvider);
    final capabilities = ref.watch(capabilitiesProvider);
    final firstBookTrialFlag =
        capabilities.asData?.value['free_first_book_trial'];
    final firstBookTrial = firstBookTrialFlag == true;
    final trialOptions = firstBookTrial
        ? ref.watch(generationOptionsProvider)
        : null;
    final accountEligible =
        trialOptions?.isLoading == false &&
        trialOptions?.asData?.value.firstBookTrialAvailable == true;
    final reviewTodayStory =
        capabilities.isLoading ||
        firstBookTrialFlag is! bool ||
        (firstBookTrial &&
            (trialOptions?.isLoading != false ||
                trialOptions?.asData?.value.firstBookTrialAvailable != false));
    final growthAsync = ref.watch(growthReportProvider);
    final growthSubtitle = growthAsync.maybeWhen(
      data: (g) => (g.vocabLearned > 0 || g.quizTotal > 0)
          ? l.homeGrowthSubtitleStats(
              g.vocabLearned,
              g.quizTotal > 0 ? (g.quizAccuracy * 100).round() : 0,
            )
          : l.readingGrowthEntrySubtitle,
      orElse: () => l.readingGrowthEntrySubtitle,
    );

    final hasBooks = libraryAsync.valueOrNull?.isNotEmpty ?? false;
    final activeProfile = ref.watch(activeChildProfileProvider).valueOrNull;
    final trialAvailable =
        firstBookTrial &&
        libraryAsync.asData?.value.isEmpty == true &&
        accountEligible;
    final trialOffer = trialAvailable
        ? (narrationSupported(capabilities.valueOrNull)
              ? l.firstBookTrialOffer
              : l.firstBookTrialIllustratedOffer)
        : null;

    return AppShell(
      currentIndex: 0,
      backgroundColor: colors.paper,
      body: SafeArea(
        child: CustomScrollView(
          key: const Key('home_scroll'),
          slivers: [
            SliverToBoxAdapter(
              child: _HomeMasthead(
                title: l.homeTitle,
                subtitle: activeProfile != null
                    ? l.activeChildLabel(activeProfile.name)
                    : hasBooks
                    ? l.homeReadingSubtitle
                    : l.homeHeaderSubtitle,
                settingsLabel: l.homeSettingsTooltip,
                openSettings: () => Navigator.pushNamed(context, '/settings'),
              ),
            ),

            if (activeJobs.isNotEmpty)
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.lg,
                  ),
                  child: Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: TextButton.icon(
                      key: const Key('home_resume_generation'),
                      style: TextButton.styleFrom(
                        minimumSize: const Size(64, AppSizing.minTouchTarget),
                      ),
                      onPressed: () {
                        final jobs = ref.read(
                          visibleActiveBookGenerationsProvider,
                        );
                        if (jobs.isEmpty ||
                            ModalRoute.of(context)?.isCurrent == false) {
                          return;
                        }
                        if (jobs.length == 1) {
                          Navigator.pushNamed(
                            context,
                            '/loading',
                            arguments: jobs.single.jobId,
                          );
                        } else {
                          Navigator.pushNamed(context, '/library');
                        }
                      },
                      icon: const Icon(Icons.auto_stories_outlined),
                      label: Text(
                        activeJobs.any((job) => job.isRechecking)
                            ? l.loadingCheckStatusButton
                            : l.libraryActiveGenerations(activeJobs.length),
                      ),
                    ),
                  ),
                ),
              ),

            // Saved stories are the first useful action for a returning reader.
            SliverToBoxAdapter(
              child: libraryAsync.when(
                data: (books) => books.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.fromLTRB(
                          AppSpacing.lg,
                          AppSpacing.sm,
                          AppSpacing.lg,
                          AppSpacing.md,
                        ),
                        child: Text(
                          l.homeEmptyTitle,
                          style: AppTextStyles.heading3.copyWith(
                            color: colors.text,
                          ),
                        ),
                      )
                    : _HomeReadingSection(books: books.take(4).toList()),
                loading: () => Semantics(
                  label: l.homeRecentBooksTitle,
                  child: const Padding(
                    padding: EdgeInsets.all(AppSpacing.lg),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                ),
                error: (_, __) => Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.sm,
                    AppSpacing.lg,
                    AppSpacing.lg,
                  ),
                  child: _StreakErrorCard(
                    title: l.homeLibraryErrorTitle,
                    message: l.libraryErrorNetwork,
                    onRetry: () => ref.invalidate(libraryProvider),
                  ),
                ),
              ),
            ),

            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: _CreateBookCard(
                  compact: hasBooks,
                  trialOffer: trialOffer,
                  onTap: () {
                    ref.invalidate(generationOptionsProvider);
                    Navigator.pushNamed(context, '/create');
                  },
                ),
              ),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.md,
                  AppSpacing.lg,
                  0,
                ),
                child: _PhotoCharacterCard(
                  onTap: () => Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {'startPhotoCharacter': true},
                  ),
                ),
              ),
            ),
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
                    reviewBeforeCreating: reviewTodayStory,
                    submittingTodayStory: submittingTodayStory,
                    onTapPrimary: () => _onTodayPrimary(
                      streak,
                      firstBookTrial,
                      reviewTodayStory,
                    ),
                  ),
                  loading: () => const _StreakLoadingCard(),
                  error: (_, __) => _StreakErrorCard(
                    message: l.homeStreakLoadError,
                    onRetry: () => ref.invalidate(homeStreakProvider),
                  ),
                ),
              ),
            ),
            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.lg)),
            _SectionLabel(l.homeSectionForParents),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  0,
                  AppSpacing.lg,
                  AppSpacing.xl,
                ),
                child: _GrowthEntryCard(
                  subtitle: growthSubtitle,
                  onTap: () => Navigator.pushNamed(context, '/reading-growth'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HomeMasthead extends StatelessWidget {
  const _HomeMasthead({
    required this.title,
    required this.subtitle,
    required this.settingsLabel,
    required this.openSettings,
  });

  final String title;
  final String subtitle;
  final String settingsLabel;
  final VoidCallback openSettings;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: DecoratedBox(
        decoration: const BoxDecoration(
          color: StorybookColors.ink,
          borderRadius: BorderRadius.all(Radius.circular(26)),
        ),
        child: Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(10, 2, 4, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Image.asset(
                    'assets/branding/splash.png',
                    width: 62,
                    excludeFromSemantics: true,
                  ),
                  Expanded(
                    child: Text(
                      title,
                      style: AppTextStyles.heading1.copyWith(
                        color: StorybookColors.onInk,
                        fontSize: MediaQuery.sizeOf(context).width < 360
                            ? 24
                            : 30,
                        height: 1.12,
                      ),
                    ),
                  ),
                  IconButton(
                    constraints: const BoxConstraints(
                      minWidth: AppSizing.minTouchTarget,
                      minHeight: AppSizing.minTouchTarget,
                    ),
                    onPressed: openSettings,
                    color: StorybookColors.onInk,
                    icon: const Icon(Icons.settings_outlined),
                    tooltip: settingsLabel,
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsetsDirectional.only(start: 14, end: 16),
                child: Text(
                  subtitle,
                  style: AppTextStyles.bodySmall.copyWith(
                    color: StorybookColors.onInkMuted,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HomeReadingSection extends ConsumerStatefulWidget {
  const _HomeReadingSection({required this.books});

  final List<LibraryBook> books;

  @override
  ConsumerState<_HomeReadingSection> createState() =>
      _HomeReadingSectionState();
}

class _HomeReadingSectionState extends ConsumerState<_HomeReadingSection> {
  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final books = widget.books;
    final colors = StorybookColors.of(context);
    final latest = books.first;
    final progress = ref.watch(homeReadingProgressProvider(latest.id));
    final hasProgress = (progress.valueOrNull ?? 0) > 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    l.homeRecentBooksTitle,
                    style: AppTextStyles.heading3,
                  ),
                ),
                TextButton(
                  key: const Key('home_view_library'),
                  style: TextButton.styleFrom(
                    minimumSize: const Size(
                      AppSizing.minTouchTarget,
                      AppSizing.minTouchTarget,
                    ),
                    foregroundColor: colors.accent,
                    textStyle: AppTextStyles.bodySmall,
                  ),
                  onPressed: () => Navigator.pushNamed(context, '/library'),
                  child: Text(l.homeViewAll),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Material(
              color: colors.sheet,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.lg),
                side: BorderSide(color: colors.rule),
              ),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                key: const Key('home_featured_book'),
                onTap: () async {
                  await Navigator.pushNamed(
                    context,
                    '/viewer',
                    arguments: latest.id,
                  );
                  if (mounted) setState(() {});
                },
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Row(
                    children: [
                      _HomeBookCover(
                        bookId: latest.id,
                        imageUrl: latest.coverImageUrl,
                        width: 84,
                        height: 116,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              latest.title,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: AppTextStyles.heading3.copyWith(
                                color: colors.text,
                                height: 1.25,
                              ),
                            ),
                            const SizedBox(height: AppSpacing.md),
                            Row(
                              children: [
                                Icon(
                                  Icons.auto_stories_rounded,
                                  color: colors.accent,
                                  size: 20,
                                ),
                                const SizedBox(width: AppSpacing.sm),
                                Expanded(
                                  child: Text(
                                    hasProgress
                                        ? l.homeContinueReading
                                        : l.homeReadBook,
                                    style: AppTextStyles.body.copyWith(
                                      color: colors.accent,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (books.length > 1) ...[
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              height: 148 + MediaQuery.textScalerOf(context).scale(38),
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                itemCount: books.length - 1,
                separatorBuilder: (_, __) =>
                    const SizedBox(width: AppSpacing.md),
                itemBuilder: (context, index) {
                  final book = books[index + 1];
                  return SizedBox(
                    width: 132,
                    child: Material(
                      color: AppPalette.of(context).surface,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        side: BorderSide(color: AppPalette.of(context).divider),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: InkWell(
                        onTap: () => Navigator.pushNamed(
                          context,
                          '/viewer',
                          arguments: book.id,
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(AppSpacing.sm),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              _HomeBookCover(
                                bookId: book.id,
                                imageUrl: book.coverImageUrl,
                                width: 116,
                                height: 116,
                              ),
                              const SizedBox(height: AppSpacing.sm),
                              Text(
                                book.title,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: AppTextStyles.bodySmall.copyWith(
                                  color: AppPalette.of(context).textPrimary,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _HomeBookCover extends StatelessWidget {
  const _HomeBookCover({
    required this.bookId,
    required this.imageUrl,
    required this.width,
    required this.height,
  });
  final String bookId;
  final String imageUrl;
  final double width;
  final double height;

  @override
  Widget build(BuildContext context) {
    final colors = StorybookColors.of(context);
    final placeholder = Container(
      color: colors.tint,
      alignment: Alignment.center,
      child: Icon(Icons.auto_stories_outlined, color: colors.accent, size: 32),
    );
    return ExcludeSemantics(
      child: ClipRRect(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        child: SizedBox(
          width: width,
          height: height,
          child: imageUrl.isEmpty
              ? placeholder
              : ScopedBookImage(
                  bookId: bookId,
                  imageUrl: imageUrl,
                  fit: BoxFit.cover,
                  placeholder: placeholder,
                  error: placeholder,
                ),
        ),
      ),
    );
  }
}

/// 새 책 만들기 카드
class _CreateBookCard extends StatelessWidget {
  final VoidCallback onTap;
  final bool compact;
  final String? trialOffer;

  const _CreateBookCard({
    required this.onTap,
    this.compact = false,
    this.trialOffer,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final colors = StorybookColors.of(context);
    return Material(
      color: colors.tint,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.xl),
        side: BorderSide(color: colors.rule),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: const Key('home_create_book'),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              CircleAvatar(
                radius: compact ? 22 : 28,
                backgroundColor: StorybookColors.ink,
                foregroundColor: StorybookColors.moonlight,
                child: const Icon(Icons.auto_stories_outlined),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l.homeCreateCardTitle,
                      style: AppTextStyles.heading3.copyWith(
                        color: colors.text,
                      ),
                    ),
                    if (!compact) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        trialOffer ?? l.homeCreateCardSubtitle,
                        style: AppTextStyles.bodySmall.copyWith(
                          color: colors.muted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Icon(Icons.chevron_right_rounded, color: colors.accent),
            ],
          ),
        ),
      ),
    );
  }
}

class _StreakSummaryCard extends StatelessWidget {
  final HomeStreakSnapshot data;
  final bool reviewBeforeCreating;
  final bool submittingTodayStory;
  final VoidCallback onTapPrimary;

  const _StreakSummaryCard({
    required this.data,
    required this.reviewBeforeCreating,
    required this.submittingTodayStory,
    required this.onTapPrimary,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final recentDays = _recentDays(context, data.readDates);
    final colors = StorybookColors.of(context);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [colors.tint, colors.sheet],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: colors.rule),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.bookmark_outline_rounded, color: colors.accent),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  l.homeStreakDaysLabel(data.currentStreak),
                  style: AppTextStyles.heading3.copyWith(color: colors.text),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: data.readToday
                  ? AppColors.successLight
                  : AppColors.blackOverlayLight,
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              data.readToday ? l.homeReadTodayBadge : l.homeNotReadTodayBadge,
              style: AppTextStyles.caption.copyWith(
                color: AppPalette.of(context).textPrimary,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l.homeStreakSummary(data.totalDays, data.longestStreak),
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          _TodayStoryPanel(
            themeName: dailyThemeLabel(
              l,
              data.todayThemeId,
              data.todayThemeName,
            ),
            topic: dailyTopicLabel(l, data.todayTopicId, data.todayTopic),
            hasTodayBook: data.todayBookId != null,
            reviewBeforeCreating: reviewBeforeCreating,
            isSubmitting: submittingTodayStory,
            onTap: onTapPrimary,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            l.homeRecent7Days,
            style: AppTextStyles.caption.copyWith(
              color: AppPalette.of(context).textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: recentDays
                .map(
                  (entry) => Expanded(
                    child: _RecentDayDot(
                      weekday: entry.label,
                      read: entry.read,
                    ),
                  ),
                )
                .toList(),
          ),
        ],
      ),
    );
  }

  List<_RecentDayEntry> _recentDays(
    BuildContext context,
    Set<String> readDates,
  ) {
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
  final bool reviewBeforeCreating;
  final bool isSubmitting;
  final VoidCallback onTap;

  const _TodayStoryPanel({
    required this.themeName,
    required this.topic,
    required this.hasTodayBook,
    required this.reviewBeforeCreating,
    required this.isSubmitting,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final colors = StorybookColors.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: colors.sheet,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.homeTodayStoryLabel(themeName),
            style: AppTextStyles.caption.copyWith(
              color: AppPalette.of(context).textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(topic, style: AppTextStyles.body),
          const SizedBox(height: AppSpacing.sm),
          Semantics(
            liveRegion: isSubmitting,
            label: isSubmitting ? l.loadingStepCheckingStatus : null,
            child: PrimaryButton(
              text: hasTodayBook
                  ? l.homeContinueReading
                  : reviewBeforeCreating
                  ? l.homeReviewTodayStory
                  : l.homeMakeTodayStory,
              onPressed: onTap,
              isLoading: isSubmitting,
              backgroundColor: colors.accent,
              foregroundColor: colors.onAccent,
              isFullWidth: false,
            ),
          ),
        ],
      ),
    );
  }
}

class _RecentDayDot extends StatelessWidget {
  final String weekday;
  final bool read;

  const _RecentDayDot({required this.weekday, required this.read});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 18,
          height: 18,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: read ? AppColors.success : AppPalette.of(context).divider,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          weekday,
          style: AppTextStyles.caption,
          textAlign: TextAlign.center,
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
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(l.homeStreakLoading)),
        ],
      ),
    );
  }
}

class _StreakErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  final String? title;

  const _StreakErrorCard({
    required this.message,
    required this.onRetry,
    this.title,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.error_outline, color: AppColors.error),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  title ?? l.homeStreakErrorTitle,
                  style: AppTextStyles.heading3,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(message, style: AppTextStyles.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextButton(
            style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
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

  const _RecentDayEntry({required this.label, required this.read});
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
          color: AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppPalette.of(context).divider),
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
                color: AppPalette.of(context).primaryLight,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: Icon(
                Icons.trending_up_rounded,
                color: AppPalette.of(context).primary,
                size: 22,
              ),
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
            Icon(
              Icons.chevron_right_rounded,
              color: AppPalette.of(context).textHint,
            ),
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
          AppSpacing.lg + 2,
          0,
          AppSpacing.lg,
          AppSpacing.sm + 2,
        ),
        child: Text(
          text,
          style: AppTextStyles.bodySmall.copyWith(
            fontWeight: FontWeight.w700,
            color: AppPalette.of(context).textHint,
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
          color: AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppPalette.of(context).divider),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(AppSpacing.sm),
              decoration: BoxDecoration(
                color: AppColors.secondaryLight,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: const Icon(
                Icons.face_retouching_natural,
                color: AppColors.secondary,
                size: 22,
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l.homePhotoCharacterTitle,
                    style: AppTextStyles.heading3,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    l.homePhotoCharacterSubtitle,
                    style: AppTextStyles.bodySmall,
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right_rounded,
              color: AppPalette.of(context).textHint,
            ),
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
            AppSpacing.lg + 2,
            0,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Text(
            l.homeQuickStartTitle,
            style: AppTextStyles.bodySmall.copyWith(
              fontWeight: FontWeight.w700,
              color: AppPalette.of(context).textHint,
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

  const _CharacterQuickStartChip({required this.name, required this.onTap});

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
                color: AppPalette.of(context).primaryLight,
                shape: BoxShape.circle,
                border: Border.all(color: AppColors.primaryMedium),
              ),
              child: Text(
                initial,
                style: AppTextStyles.heading3.copyWith(
                  color: AppPalette.of(context).primary,
                ),
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
