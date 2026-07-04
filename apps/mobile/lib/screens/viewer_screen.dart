import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:confetti/confetti.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:just_audio/just_audio.dart';
import 'package:printing/printing.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../widgets/vocab_game_card.dart';
import '../providers/providers.dart';
import 'inpaint_screen.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';
import '../widgets/common_widgets.dart';
import '../widgets/credit_shortage_modal.dart';

/// 책 뷰어 화면
class ViewerScreen extends ConsumerStatefulWidget {
  final String bookId;

  const ViewerScreen({super.key, required this.bookId});

  @override
  ConsumerState<ViewerScreen> createState() => _ViewerScreenState();
}

class _ViewerScreenState extends ConsumerState<ViewerScreen> {
  late PageController _pageController;
  late final ConfettiController _completionConfettiController;
  final AudioPlayer _audioPlayer = AudioPlayer();
  StreamSubscription<PlayerState>? _playerStateSubscription;
  StreamSubscription<Duration>? _positionSubscription;
  Timer? _sleepModeTimer;
  int _currentPage = 0;
  bool _showControls = true;
  bool _isPlaying = false;
  bool _isLoadingAudio = false;
  bool _completionHandled = false;
  // 완독률을 '진짜 변별되는' 측정치로 만들기 위해: 본문에 진입(표지 이후)했는데 마지막
  // 페이지까지 안 가고 이탈하면 completed:false 로 1회 기록한다(이탈도 표본에 포함).
  int _maxPageReached = 0;
  bool _exitReadRecorded = false;
  bool _progressRestored = false;
  // 같은 세션에서 학습 시트 재오픈 시 동일 퀴즈 중복 기록 방지(성장 집계 왜곡 방지)
  final Set<String> _recordedQuiz = {};
  bool _dualLanguageEnabled = false;
  bool _followReadingEnabled = false;
  bool _allowKakaoShare = true;
  bool _sleepModeEnabled = false;
  DateTime? _sleepModeEndsAt;
  bool _sleepAutoAdvancing = false;
  double _audioProgress = 0;
  int _audioProgressPage = 0;
  BookResult? _activeBook;
  DateTime _viewStartedAt = DateTime.now();
  // 다국어 지원
  String _selectedLanguage = 'ko'; // 'ko' or 'en'

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _completionConfettiController = ConfettiController(
      duration: const Duration(seconds: 3),
    );
    _viewStartedAt = DateTime.now();
    ref.read(analyticsProvider).logEvent(
      AnalyticsEvents.readingStarted,
      params: {'book_id': widget.bookId},
    );
    unawaited(_loadViewerSettings());
    // Store subscription to cancel later (memory leak fix)
    _playerStateSubscription = _audioPlayer.playerStateStream.listen((state) {
      if (mounted) {
        setState(() {
          _isPlaying = state.playing;
          if (state.processingState == ProcessingState.completed) {
            _audioProgress = 1;
          }
        });
      }
      if (state.processingState == ProcessingState.completed &&
          _sleepModeEnabled) {
        unawaited(_handleSleepPlaybackCompleted());
      }
    });
    _positionSubscription = _audioPlayer.positionStream.listen((position) {
      if (!mounted || !_isPlaying) {
        return;
      }
      if (_audioProgressPage != _currentPage) {
        return;
      }
      final duration = _audioPlayer.duration;
      if (duration == null || duration.inMilliseconds <= 0) {
        return;
      }
      final ratio =
          (position.inMilliseconds / duration.inMilliseconds).clamp(0.0, 1.0);
      if ((ratio - _audioProgress).abs() < 0.02 && ratio < 1) {
        return;
      }
      setState(() => _audioProgress = ratio);
    });
  }

  @override
  void dispose() {
    _recordAbandonedReadIfNeeded();
    // Cancel subscription to prevent memory leak
    _playerStateSubscription?.cancel();
    _positionSubscription?.cancel();
    _sleepModeTimer?.cancel();
    _completionConfettiController.dispose();
    _pageController.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  /// 본문에 진입했으나 완독 없이 화면을 떠날 때 미완독(completed:false)으로 1회 기록.
  /// 완독은 _handleBookCompleted가 별도로 completed:true를 남기므로 세션당 로그는 1개.
  void _recordAbandonedReadIfNeeded() {
    if (_completionHandled || _exitReadRecorded || _maxPageReached < 1) {
      return;
    }
    _exitReadRecorded = true;
    final seconds = DateTime.now().difference(_viewStartedAt).inSeconds;
    final api = ref.read(apiClientProvider);
    // fire-and-forget: 화면은 사라지지만 ApiClient(Dio)는 provider에 살아있어 전송 완료됨.
    unawaited(
      api
          .recordReading(
            bookId: widget.bookId,
            readingTime: seconds < 0 ? 0 : seconds,
            completed: false,
          )
          .catchError((_) => <String, dynamic>{}),
    );
  }

  void _toggleControls() {
    setState(() => _showControls = !_showControls);
  }

  Future<void> _loadViewerSettings() async {
    try {
      final settings = await ref.read(apiClientProvider).getSettings();
      final allowKakao = settings['allow_kakao_share'];
      final next = allowKakao is bool ? allowKakao : true;
      if (!mounted) {
        _allowKakaoShare = next;
        return;
      }
      setState(() => _allowKakaoShare = next);
    } catch (_) {
      // 설정 조회 실패 시 기본값(true)을 사용한다.
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final bookAsync = ref.watch(bookDetailProvider(widget.bookId));

    return Scaffold(
      backgroundColor: Colors.black,
      body: bookAsync.when(
        data: (book) => _buildViewer(book),
        loading: () => const Center(
          child: CircularProgressIndicator(color: Colors.white),
        ),
        error: (error, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error, color: Colors.white, size: 48),
              const SizedBox(height: AppSpacing.md),
              Text(
                l.viewerBookLoadError,
                style: AppTextStyles.body.copyWith(color: Colors.white),
              ),
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                text: l.viewerGoBack,
                isFullWidth: false,
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildViewer(BookResult book) {
    final l = AppLocalizations.of(context);
    _activeBook = book;
    // 표지(0) + 페이지들
    final totalPages = book.pages.length + 1;
    _restoreReadingProgressIfNeeded(totalPages);
    final currentWarning = _currentGenerationWarning(book);

    return GestureDetector(
      onTap: _toggleControls,
      child: Stack(
        children: [
          // 페이지 뷰
          PageView.builder(
            controller: _pageController,
            itemCount: totalPages,
            onPageChanged: (index) async {
              await _audioPlayer.stop();
              if (!mounted) {
                return;
              }
              setState(() {
                _currentPage = index;
                _audioProgress = 0;
                _audioProgressPage = index;
              });
              if (index > _maxPageReached) {
                _maxPageReached = index;
              }
              unawaited(_saveReadingProgress(index, totalPages));
              if (_sleepModeEnabled && index > 0) {
                await _playPageAudio(book, restart: true);
              }
              if (index == totalPages - 1 && !_completionHandled) {
                _completionHandled = true;
                ref.read(analyticsProvider).logEvent(
                  AnalyticsEvents.readingCompleted,
                  params: {
                    'book_id': widget.bookId,
                    'reading_seconds':
                        DateTime.now().difference(_viewStartedAt).inSeconds,
                  },
                );
                _handleBookCompleted(book);
              }
            },
            itemBuilder: (context, index) {
              if (index == 0) {
                // 표지
                return _CoverPage(
                  title: book.getTitle(_selectedLanguage),
                  imageUrl: book.coverImageUrl,
                );
              } else {
                // 본문 페이지
                final page = book.pages[index - 1];
                final secondaryText = _dualLanguageEnabled
                    ? (_selectedLanguage == 'ko' ? page.textEn : page.textKo)
                    : null;
                return _ContentPage(
                  pageNumber: page.pageNumber,
                  text: page.getText(_selectedLanguage),
                  secondaryText: secondaryText,
                  imageUrl: page.imageUrl,
                  page: page,
                  selectedLanguage: _selectedLanguage,
                  followReadingEnabled: _followReadingEnabled,
                  followProgress:
                      _audioProgressPage == index ? _audioProgress : 0,
                  onShowLearning: () => _showLearningMode(book, page),
                );
              }
            },
          ),
          if (currentWarning != null)
            Positioned(
              top: MediaQuery.of(context).padding.top + AppSpacing.md,
              left: AppSpacing.md,
              right: AppSpacing.md,
              child: IgnorePointer(
                ignoring: true,
                child: AnimatedOpacity(
                  opacity: _showControls ? 1 : 0.92,
                  duration: const Duration(milliseconds: 200),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.md,
                      vertical: AppSpacing.sm,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.warning.withValues(alpha: 0.92),
                      borderRadius: BorderRadius.circular(AppRadius.md),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.warning_amber_rounded,
                          color: Colors.white,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Text(
                            currentWarning.message,
                            style: AppTextStyles.bodySmall.copyWith(
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),

          // 컨트롤
          IgnorePointer(
            ignoring: !_showControls,
            child: AnimatedOpacity(
              opacity: _showControls ? 1.0 : 0.0,
              duration: const Duration(milliseconds: 200),
              child: _buildControls(book, totalPages),
            ),
          ),
          IgnorePointer(
            ignoring: true,
            child: AnimatedOpacity(
              opacity: _sleepModeEnabled ? 0.34 : 0,
              duration: const Duration(milliseconds: 200),
              child: const ColoredBox(color: Colors.black),
            ),
          ),
          if (_sleepModeEnabled)
            Positioned(
              top: MediaQuery.of(context).padding.top + AppSpacing.md,
              right: AppSpacing.md,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.sm,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  color: AppColors.blackOverlayStrong,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  l.viewerSleepRemaining(_sleepRemainingText()),
                  style: AppTextStyles.caption.copyWith(color: Colors.white),
                ),
              ),
            ),
        ],
      ),
    );
  }

  GenerationWarning? _currentGenerationWarning(BookResult book) {
    if (!book.hasGenerationWarnings) {
      return null;
    }

    final targetPage = _currentPage;
    for (final warning in book.generationWarnings) {
      if (warning.pageNumber == targetPage) {
        return warning;
      }
    }
    return book.generationWarnings.first;
  }

  /// 마일스톤 달성 모달 — 첫 마일스톤을 축하하고 보상(보너스 크레딧)을 알린다.
  /// (보상 크레딧은 서버의 읽기 기록 흐름에서 이미 지급됨.)
  Future<void> _showMilestoneModal(List<dynamic> milestones) async {
    final l = AppLocalizations.of(context);
    final m = milestones.first;
    if (m is! Map) {
      return;
    }
    final title = m['title']?.toString() ?? '';
    final description = m['description']?.toString() ?? '';
    final hasReward = m['reward'] != null;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(description),
            if (hasReward) ...[
              const SizedBox(height: AppSpacing.md),
              Container(
                padding: const EdgeInsets.all(AppSpacing.sm),
                decoration: BoxDecoration(
                  color: AppColors.primaryLight,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.card_giftcard,
                        color: AppColors.primary, size: 20),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(child: Text(l.viewerMilestoneRewardEarned)),
                  ],
                ),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.viewerMilestoneConfirm),
          ),
        ],
      ),
    );
  }

  Future<void> _handleBookCompleted(BookResult book) async {
    await _clearReadingProgress();
    final readingSeconds = DateTime.now().difference(_viewStartedAt).inSeconds;
    final api = ref.read(apiClientProvider);
    int streak = 0;

    try {
      final readResult = await api.recordReading(
        bookId: widget.bookId,
        readingTime: readingSeconds < 0 ? 0 : readingSeconds,
        completed: true,
      );
      final milestones = readResult['milestones'];
      if (milestones is List && milestones.isNotEmpty && mounted) {
        await _showMilestoneModal(milestones);
      }
      final streakInfo = await api.getStreakInfo();
      final currentStreak = streakInfo['current_streak'];
      if (currentStreak is int) {
        streak = currentStreak;
      } else if (currentStreak is num) {
        streak = currentStreak.toInt();
      }
    } catch (_) {
      // 완독 기록 실패는 읽기 흐름을 막지 않는다.
    }

    try {
      final prefs = ref.read(sharedPreferencesProvider);
      final reviewService = ref.read(reviewServiceProvider);
      var shouldPrompt = false;

      const firstCompletionKey = 'review_first_book_completed_v1';
      final firstCompletionDone = prefs.getBool(firstCompletionKey) ?? false;
      if (!firstCompletionDone) {
        await prefs.setBool(firstCompletionKey, true);
        shouldPrompt = true;
      }
      if (streak >= 3) {
        shouldPrompt = true;
      }

      if (shouldPrompt) {
        await reviewService.requestReviewIfEligible(prefs);
      }
    } catch (_) {
      // 리뷰 요청 실패는 무시한다.
    }

    if (!mounted) {
      return;
    }

    await _showCompletionCelebration(streak);
  }

  Future<void> _showCompletionCelebration(int streak) async {
    final l = AppLocalizations.of(context);
    _completionConfettiController
      ..stop()
      ..play();

    await showDialog<void>(
      context: context,
      barrierDismissible: true,
      builder: (dialogContext) => Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        child: Stack(
          alignment: Alignment.topCenter,
          children: [
            IgnorePointer(
              child: SizedBox(
                width: double.infinity,
                height: 420,
                child: ConfettiWidget(
                  confettiController: _completionConfettiController,
                  blastDirectionality: BlastDirectionality.explosive,
                  emissionFrequency: 0.05,
                  numberOfParticles: 24,
                  maxBlastForce: 16,
                  minBlastForce: 8,
                  gravity: 0.25,
                  shouldLoop: false,
                  colors: const [
                    AppColors.primary,
                    AppColors.secondary,
                    AppColors.success,
                    Color(0xFFFFD166),
                    Color(0xFFEF476F),
                  ],
                  createParticlePath: _buildConfettiStarPath,
                ),
              ),
            ),
            Container(
              margin: const EdgeInsets.only(top: AppSpacing.xxl),
              padding: const EdgeInsets.all(AppSpacing.xl),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadius.xl),
                boxShadow: const [
                  BoxShadow(
                    color: AppColors.blackOverlayShadow,
                    blurRadius: 16,
                    offset: Offset(0, 8),
                  ),
                ],
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(
                      color: AppColors.primaryLight,
                      borderRadius: BorderRadius.circular(44),
                    ),
                    child: const Icon(
                      Icons.auto_awesome,
                      size: 44,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    l.viewerCompletionTitle,
                    style: AppTextStyles.heading2,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    streak >= 3
                        ? l.viewerCompletionStreak(streak)
                        : l.viewerCompletionMessage,
                    style: AppTextStyles.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  PrimaryButton(
                    text: l.viewerCreateNextStory,
                    onPressed: () {
                      Navigator.pop(dialogContext);
                      Navigator.pushNamedAndRemoveUntil(
                        context,
                        '/create',
                        (route) => route.isFirst,
                      );
                    },
                  ),
                  const SizedBox(height: AppSpacing.md),
                  SecondaryButton(
                    text: l.viewerGoToLibrary,
                    onPressed: () {
                      Navigator.pop(dialogContext);
                      Navigator.pushNamedAndRemoveUntil(
                        context,
                        '/library',
                        (route) => route.isFirst,
                      );
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Path _buildConfettiStarPath(Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final outerRadius = min(size.width, size.height) / 2;
    final innerRadius = outerRadius / 2.4;
    final path = Path();

    for (var i = 0; i < 10; i++) {
      final radius = i.isEven ? outerRadius : innerRadius;
      final angle = (pi / 5 * i) - pi / 2;
      final offset = Offset(
        center.dx + cos(angle) * radius,
        center.dy + sin(angle) * radius,
      );
      if (i == 0) {
        path.moveTo(offset.dx, offset.dy);
      } else {
        path.lineTo(offset.dx, offset.dy);
      }
    }

    path.close();
    return path;
  }

  Widget _buildControls(BookResult book, int totalPages) {
    final l = AppLocalizations.of(context);
    return Column(
      children: [
        // 상단 바
        Container(
          padding: EdgeInsets.only(
            top: MediaQuery.of(context).padding.top + AppSpacing.sm,
            left: AppSpacing.md,
            right: AppSpacing.md,
            bottom: AppSpacing.sm,
          ),
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                AppColors.blackOverlayStrong,
                Colors.transparent,
              ],
            ),
          ),
          child: Row(
            children: [
              IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                tooltip: l.viewerCloseTooltip,
                onPressed: () => Navigator.pop(context),
              ),
              Expanded(
                child: Text(
                  book.getTitle(_selectedLanguage),
                  style: AppTextStyles.heading3.copyWith(color: Colors.white),
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              // 언어 토글 버튼
              _LanguageToggle(
                selectedLanguage: _selectedLanguage,
                hasTranslation: book.titleKo != null || book.titleEn != null,
                onToggle: () async {
                  final wasPlaying = _isPlaying;
                  await _audioPlayer.stop();
                  if (!mounted) {
                    return;
                  }
                  setState(() {
                    _selectedLanguage = _selectedLanguage == 'ko' ? 'en' : 'ko';
                  });
                  if (wasPlaying && _currentPage > 0) {
                    await _toggleAudio(book);
                  }
                },
              ),
              IconButton(
                icon: const Icon(Icons.more_vert, color: Colors.white),
                tooltip: l.viewerMoreOptionsTooltip,
                onPressed: () => _showOptionsMenu(book),
              ),
            ],
          ),
        ),

        const Spacer(),

        // 하단 바
        Container(
          padding: EdgeInsets.only(
            left: AppSpacing.lg,
            right: AppSpacing.lg,
            top: AppSpacing.md,
            bottom: MediaQuery.of(context).padding.bottom + AppSpacing.md,
          ),
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.bottomCenter,
              end: Alignment.topCenter,
              colors: [
                AppColors.blackOverlayStrong,
                Colors.transparent,
              ],
            ),
          ),
          child: Column(
            children: [
              // 학습 모드 상시 진입(C1: 옵션 메뉴 깊숙이 → 하단 상시 노출로 접근성↑)
              _buildLearningBar(book),
              // 페이지 인디케이터 (텍스트형으로 오버플로우 방지)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.md,
                      vertical: AppSpacing.xs,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.whiteOverlay,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      _currentPage == 0
                          ? l.viewerCover
                          : l.viewerPageIndicator(_currentPage, totalPages - 1),
                      style:
                          AppTextStyles.caption.copyWith(color: Colors.white),
                    ),
                  ),
                ],
              ),

              const SizedBox(height: AppSpacing.md),

              // 네비게이션 버튼
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _NavButton(
                    icon: Icons.chevron_left,
                    tooltip: l.viewerPreviousPageTooltip,
                    enabled: _currentPage > 0,
                    onPressed: () {
                      _pageController.previousPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                      );
                    },
                  ),
                  // 오디오 재생 버튼 (페이지에서만)
                  if (_currentPage > 0)
                    _AudioButton(
                      isPlaying: _isPlaying,
                      isLoading: _isLoadingAudio,
                      onPressed: () => _toggleAudio(book),
                    )
                  else
                    const SizedBox(width: AppSizing.minTouchTarget),
                  const SizedBox.shrink(),
                  _NavButton(
                    icon: Icons.chevron_right,
                    tooltip: l.viewerNextPageTooltip,
                    enabled: _currentPage < totalPages - 1,
                    onPressed: () {
                      _pageController.nextPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                      );
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  /// 학습 모드 상시 진입 바 — 현재 페이지에 학습 콘텐츠가 있을 때만 노출.
  /// (커버/콘텐츠 없으면 빈 위젯, 옵션 메뉴를 거치지 않고 한 번에 학습 모드로.)
  Widget _buildLearningBar(BookResult book) {
    final l = AppLocalizations.of(context);
    if (_currentPage <= 0 || _currentPage > book.pages.length) {
      return const SizedBox.shrink();
    }
    final page = book.pages[_currentPage - 1];
    final vocab = page.vocab?.length ?? 0;
    final quiz = page.quiz?.length ?? 0;
    final compr = page.comprehensionQuestions?.length ?? 0;
    if (vocab == 0 && quiz == 0 && compr == 0) {
      return const SizedBox.shrink();
    }
    final parts = <String>[
      if (vocab > 0) l.viewerLearningWordCount(vocab),
      if (quiz > 0) l.viewerLearningQuizCount(quiz),
      if (compr > 0) l.viewerLearningQuestionCount(compr),
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: GestureDetector(
        key: const Key('viewer_learning_bar'),
        onTap: () => _showLearningMode(book, page),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: 13,
          ),
          decoration: BoxDecoration(
            color: AppColors.primary,
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.menu_book_rounded, color: Colors.white, size: 18),
              const SizedBox(width: AppSpacing.sm),
              Text(
                l.viewerLearningBar(parts.join(' · ')),
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _toggleAudio(BookResult book) async {
    if (_isPlaying) {
      await _audioPlayer.pause();
      return;
    }
    if (mounted) {
      setState(() {
        _audioProgressPage = _currentPage;
      });
    } else {
      _audioProgressPage = _currentPage;
    }
    await _playPageAudio(book, restart: true);
  }

  ApiError? _extractApiError(Object error) {
    if (error is ApiError) {
      return error;
    }
    if (error is DioException && error.error is ApiError) {
      return error.error as ApiError;
    }
    return null;
  }

  Future<bool> _handlePaymentRequired(Object error) async {
    final apiError = _extractApiError(error);
    if (apiError == null || apiError.code != 'PAYMENT_REQUIRED') {
      return false;
    }
    if (!mounted) {
      return true;
    }

    final l = AppLocalizations.of(context);
    final message = apiError.message.trim();
    final title = message.contains('PDF') ||
            message.contains('오디오') ||
            message.contains('플랜')
        ? l.viewerPlanUpgradeNeeded
        : l.viewerCreditShortage;
    await showCreditShortageModal(
      context,
      title: title,
      message: message,
    );
    return true;
  }

  Future<void> _playPageAudio(BookResult book, {bool restart = false}) async {
    if (_currentPage == 0) {
      return; // 표지는 오디오 없음
    }

    setState(() {
      _isLoadingAudio = true;
      _audioProgress = 0;
      _audioProgressPage = _currentPage;
    });

    try {
      if (restart) {
        await _audioPlayer.stop();
      }
      final apiClient = ref.read(apiClientProvider);
      final page = book.pages[_currentPage - 1];

      // 이미 오디오 URL이 있으면 바로 재생
      String? audioUrl = page.getAudioUrl(_selectedLanguage);

      // 없으면 API에서 가져오기 (자동 생성)
      if (audioUrl == null || audioUrl.isEmpty) {
        audioUrl = await apiClient.getPageAudioUrl(
          book.bookId,
          _currentPage,
          language: _selectedLanguage,
        );
      }

      // 오디오 재생
      await _audioPlayer.setUrl(audioUrl);
      await _audioPlayer.play();
    } catch (e) {
      if (await _handlePaymentRequired(e)) {
        return;
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerAudioPlayFailed),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoadingAudio = false);
      }
    }
  }

  Future<void> _handleSleepPlaybackCompleted() async {
    if (!_sleepModeEnabled || _sleepAutoAdvancing) {
      return;
    }
    final book = _activeBook;
    if (book == null) {
      return;
    }
    final totalPages = book.pages.length + 1;
    if (_currentPage >= totalPages - 1) {
      return;
    }

    _sleepAutoAdvancing = true;
    try {
      await _pageController.nextPage(
        duration: const Duration(milliseconds: 450),
        curve: Curves.easeInOut,
      );
    } finally {
      _sleepAutoAdvancing = false;
    }
  }

  Future<void> _startSleepMode(BookResult book) async {
    final api = ref.read(apiClientProvider);
    var minutes = 20;
    try {
      final settings = await api.getSettings();
      final value = settings['sleep_mode_default_minutes'];
      if (value is int) {
        minutes = value;
      } else if (value is num) {
        minutes = value.toInt();
      } else if (value is String) {
        minutes = int.tryParse(value) ?? minutes;
      }
    } catch (_) {
      // 실패 시 기본값 사용
    }

    if (!mounted) {
      return;
    }

    final normalizedMinutes = minutes.clamp(10, 60);
    _sleepModeTimer?.cancel();
    setState(() {
      _sleepModeEnabled = true;
      _sleepModeEndsAt = DateTime.now().add(
        Duration(minutes: normalizedMinutes),
      );
    });

    _sleepModeTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      final endsAt = _sleepModeEndsAt;
      if (endsAt == null) {
        return;
      }
      if (DateTime.now().isAfter(endsAt)) {
        unawaited(_stopSleepMode(byTimer: true));
        return;
      }
      if (mounted) {
        setState(() {});
      }
    });

    if (_currentPage == 0) {
      await _pageController.animateToPage(
        1,
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeInOut,
      );
      return;
    }
    await _playPageAudio(book, restart: true);
  }

  Future<void> _stopSleepMode({bool byTimer = false}) async {
    final wasEnabled = _sleepModeEnabled;
    _sleepModeTimer?.cancel();
    _sleepModeTimer = null;
    _sleepModeEndsAt = null;

    if (mounted) {
      setState(() => _sleepModeEnabled = false);
    } else {
      _sleepModeEnabled = false;
    }

    await _audioPlayer.stop();
    if (byTimer && wasEnabled && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppLocalizations.of(context).viewerSleepModeEnded)),
      );
    }
  }

  String _sleepRemainingText() {
    final endsAt = _sleepModeEndsAt;
    if (endsAt == null) {
      return '--:--';
    }
    final remaining = endsAt.difference(DateTime.now());
    if (remaining.isNegative) {
      return '00:00';
    }
    final minutes = remaining.inMinutes.toString().padLeft(2, '0');
    final seconds = (remaining.inSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  String get _progressKey => 'reading_progress_${widget.bookId}_v1';

  void _restoreReadingProgressIfNeeded(int totalPages) {
    if (_progressRestored) {
      return;
    }
    _progressRestored = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final prefs = ref.read(sharedPreferencesProvider);
      final savedPage = prefs.getInt(_progressKey) ?? 0;
      if (!mounted || savedPage <= 0 || savedPage >= totalPages) {
        return;
      }
      _currentPage = savedPage;
      _audioProgressPage = savedPage;
      _pageController.jumpToPage(savedPage);
      setState(() {});
    });
  }

  Future<void> _saveReadingProgress(int pageIndex, int totalPages) async {
    final prefs = ref.read(sharedPreferencesProvider);
    if (pageIndex >= totalPages - 1) {
      await prefs.remove(_progressKey);
      return;
    }
    await prefs.setInt(_progressKey, pageIndex);
  }

  Future<void> _clearReadingProgress() async {
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.remove(_progressKey);
  }

  /// 다른 연령대로 본문만 다시 써서 새 책으로 연다(삽화 재사용, 크레딧 0).
  Future<void> _showRetellAgePicker(BookResult book) async {
    final l = AppLocalizations.of(context);
    final targetAge = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: Text(l.viewerRetellTitle),
        children: [
          for (final entry in {
            '3-5': l.libraryAge3to5,
            '5-7': l.libraryAge5to7,
            '7-9': l.libraryAge7to9,
          }.entries)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, entry.key),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: Text(entry.value),
              ),
            ),
        ],
      ),
    );
    if (targetAge == null || !mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(l.viewerRetellInProgress)),
    );
    try {
      final newBookId =
          await ref.read(apiClientProvider).retellBook(book.bookId, targetAge);
      if (!mounted) {
        return;
      }
      Navigator.pushReplacementNamed(context, '/viewer', arguments: newBookId);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l.viewerRetellFailed),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  void _showOptionsMenu(BookResult book) {
    final l = AppLocalizations.of(context);
    final hasBilingualText = book.pages.any(
      (page) =>
          (page.textKo?.isNotEmpty ?? false) &&
          (page.textEn?.isNotEmpty ?? false),
    );
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => AdaptiveModalSheet(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.lg),
            if (_currentPage > 0)
              ListTile(
                leading: Icon(
                  _followReadingEnabled
                      ? Icons.hearing_disabled
                      : Icons.hearing,
                ),
                title: Text(
                  _followReadingEnabled
                      ? l.viewerFollowReadingOff
                      : l.viewerFollowReadingOn,
                ),
                subtitle: Text(l.viewerFollowReadingSubtitle),
                onTap: () {
                  Navigator.pop(context);
                  if (!mounted) {
                    return;
                  }
                  setState(
                      () => _followReadingEnabled = !_followReadingEnabled);
                },
              ),
            if (hasBilingualText)
              ListTile(
                leading: const Icon(Icons.translate),
                title: Text(
                  _dualLanguageEnabled
                      ? l.viewerDualLanguageOff
                      : l.viewerDualLanguageOn,
                ),
                subtitle: Text(l.viewerDualLanguageSubtitle),
                onTap: () {
                  Navigator.pop(context);
                  if (!mounted) {
                    return;
                  }
                  setState(() => _dualLanguageEnabled = !_dualLanguageEnabled);
                },
              ),
            ListTile(
              leading: const Icon(Icons.alt_route),
              title: Text(l.viewerBranchStoryTitle),
              subtitle: Text(l.viewerBranchStorySubtitle),
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(
                  context,
                  '/branch-story',
                  arguments: {
                    'bookId': book.bookId,
                  },
                );
              },
            ),
            // 아이와 함께 자라는 리텔 — 같은 그림으로 다른 연령대 본문
            ListTile(
              leading: const Icon(Icons.auto_stories),
              title: Text(l.viewerRetellTitle),
              subtitle: Text(l.viewerRetellSubtitle),
              onTap: () {
                Navigator.pop(context);
                _showRetellAgePicker(book);
              },
            ),
            // 학습 모드 (페이지에서만)
            if (_currentPage > 0 &&
                book.pages[_currentPage - 1].hasLearningContent)
              ListTile(
                leading: const Icon(Icons.school),
                title: Text(l.viewerLearningModeTitle),
                subtitle: Text(l.viewerLearningModeSubtitle),
                onTap: () {
                  Navigator.pop(context);
                  _showLearningMode(book, book.pages[_currentPage - 1]);
                },
              ),
            // 부모 가이드
            if (book.learningAssets != null)
              ListTile(
                leading: const Icon(Icons.family_restroom),
                title: Text(l.viewerParentGuideTitle),
                subtitle: Text(l.viewerParentGuideSubtitle),
                onTap: () {
                  Navigator.pop(context);
                  _showParentGuide(book);
                },
              ),
            if (_currentPage > 0)
              ListTile(
                leading: const Icon(Icons.record_voice_over_outlined),
                title: Text(l.viewerPronunciationTitle),
                subtitle: Text(l.viewerPronunciationSubtitle),
                onTap: () {
                  final page = book.pages[_currentPage - 1];
                  final expected = page.getText(_selectedLanguage);
                  Navigator.pop(context);
                  Navigator.pushNamed(
                    context,
                    '/pronunciation-practice',
                    arguments: {
                      'bookId': book.bookId,
                      'pageNumber': page.pageNumber,
                      'expectedText': expected,
                    },
                  );
                },
              ),
            if (_currentPage > 0)
              ListTile(
                leading: const Icon(Icons.refresh),
                title: Text(l.viewerRegeneratePageTitle),
                onTap: () {
                  Navigator.pop(context);
                  _showRegenerateOptions(book);
                },
              ),
            if (book.characterId != null)
              ListTile(
                leading: const Icon(Icons.auto_stories),
                title: Text(l.viewerSameCharacterNewStory),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {'characterId': book.characterId},
                  );
                },
              ),
            ListTile(
              leading: const Icon(Icons.picture_as_pdf),
              title: Text(l.viewerExportPdf),
              onTap: () {
                Navigator.pop(context);
                _downloadPdf(book);
              },
            ),
            ListTile(
              leading: const Icon(Icons.local_shipping_outlined),
              title: Text(l.viewerOrderPhysicalBook),
              subtitle: Text(l.viewerOrderPhysicalBookSubtitle),
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(
                  context,
                  '/pod-order',
                  arguments: {
                    'bookId': book.bookId,
                    'bookTitle': book.title,
                  },
                );
              },
            ),
            ListTile(
              leading: Icon(
                _sleepModeEnabled ? Icons.bedtime_off : Icons.bedtime,
              ),
              title: Text(
                  _sleepModeEnabled ? l.viewerSleepModeStop : l.viewerSleepModeStart),
              subtitle: Text(
                _sleepModeEnabled
                    ? l.viewerSleepModeRemaining(_sleepRemainingText())
                    : l.viewerSleepModeDescription,
              ),
              onTap: () {
                Navigator.pop(context);
                if (_sleepModeEnabled) {
                  unawaited(_stopSleepMode());
                  return;
                }
                unawaited(_startSleepMode(book));
              },
            ),
            ListTile(
              leading: const Icon(Icons.print_outlined),
              title: Text(l.viewerPrint),
              onTap: () {
                Navigator.pop(context);
                _printPdf(book);
              },
            ),
            ListTile(
              leading: const Icon(Icons.share),
              title: Text(l.viewerShare),
              onTap: () {
                Navigator.pop(context);
                _showShareOptions(book);
              },
            ),
            const SizedBox(height: AppSpacing.md),
          ],
        ),
      ),
    );
  }

  /// 학습 모드 표시
  void _showLearningMode(BookResult book, PageResult page) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => _LearningModeSheet(
          page: page,
          scrollController: scrollController,
          onQuizAnswered: (correct, questionIndex) {
            unawaited(_recordQuizAnswer(page, correct, questionIndex));
          },
          onVocabAnswered: (term, correct, index) {
            unawaited(_recordVocabAnswer(page, term, correct, index));
          },
        ),
      ),
    );
  }

  /// 퀴즈 응답을 성장 측정에 기록한다(실패는 읽기 흐름을 막지 않음).
  Future<void> _recordQuizAnswer(
    PageResult page,
    bool correct,
    int questionIndex,
  ) async {
    final key = '${page.pageNumber}:$questionIndex';
    if (_recordedQuiz.contains(key)) {
      return; // 이미 기록한 문항 — 시트 재오픈 중복 적재 방지
    }
    _recordedQuiz.add(key);
    try {
      await ref.read(apiClientProvider).recordQuizAnswer(
            bookId: widget.bookId,
            quizType: 'quiz',
            correct: correct,
            pageNumber: page.pageNumber,
            questionIndex: questionIndex,
          );
    } catch (_) {
      // 조용히 무시 — 학습 응답 기록 실패가 읽기를 방해하지 않는다.
      _recordedQuiz.remove(key); // 실패 시 재시도 허용
    }
  }

  /// 어휘 게임 응답을 vocab 측정으로 기록('학습 어휘'의 실데이터 — 재인 신호).
  Future<void> _recordVocabAnswer(
    PageResult page,
    String term,
    bool correct,
    int index,
  ) async {
    final key = 'vocab:${page.pageNumber}:$term';
    if (_recordedQuiz.contains(key)) {
      return;
    }
    _recordedQuiz.add(key);
    try {
      await ref.read(apiClientProvider).recordQuizAnswer(
            bookId: widget.bookId,
            quizType: 'vocab',
            correct: correct,
            pageNumber: page.pageNumber,
            questionIndex: index,
            term: term,
          );
    } catch (_) {
      _recordedQuiz.remove(key);
    }
  }

  /// 부모 가이드 표시
  void _showParentGuide(BookResult book) {
    if (book.learningAssets == null) return;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.4,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) => _ParentGuideSheet(
          parentGuide: book.learningAssets!.parentGuide,
          scrollController: scrollController,
        ),
      ),
    );
  }

  void _showRegenerateOptions(BookResult book) {
    final l = AppLocalizations.of(context);
    final pageIndex = _currentPage - 1; // 표지 제외
    if (pageIndex < 0) return;
    // 능력기반: 알려진 미지원이면 인페인트 옵션 숨김(미확정/지원은 노출, 409로 폴백).
    final caps = ref.read(capabilitiesProvider).valueOrNull;
    final inpaintOk = caps == null ? true : caps['inpaint_supported'] == true;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.viewerRegenerateDialogTitle),
        content: Text(l.viewerRegenerateDialogContent),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.viewerCancel),
          ),
          if (inpaintOk && pageIndex < book.pages.length)
            TextButton(
              onPressed: () {
                Navigator.pop(context);
                _openInpaint(book, pageIndex);
              },
              child: Text(l.viewerRegenerateRegion),
            ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'text');
            },
            child: Text(l.viewerRegenerateTextOnly),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'image');
            },
            child: Text(l.viewerRegenerateImageOnly),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'both');
            },
            child: Text(l.viewerRegenerateAll),
          ),
        ],
      ),
    );
  }

  Future<void> _openInpaint(BookResult book, int pageIndex) async {
    final l = AppLocalizations.of(context);
    if (book.jobId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.viewerRegenerateNotSupported)),
      );
      return;
    }
    final page = book.pages[pageIndex];
    final result = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (_) => InpaintScreen(
          jobId: book.jobId!,
          bookId: widget.bookId,
          pageNumber: pageIndex + 1,
          imageUrl: page.imageUrl,
        ),
      ),
    );
    if (!mounted) return;
    if (result == false) {
      // 제공자 미지원 → 전체 이미지 재생성으로 폴백
      _regeneratePage(book, pageIndex + 1, 'image');
    }
  }

  Future<void> _regeneratePage(
      BookResult book, int pageNumber, String target) async {
    final l = AppLocalizations.of(context);
    if (book.jobId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.viewerRegenerateNotSupported)),
      );
      return;
    }

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(l.viewerRegenerating)),
    );

    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.regeneratePage(book.jobId!, pageNumber,
          regenerateTarget: target);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).viewerRegenerateStarted)),
        );
        // 책 데이터 새로고침
        ref.invalidate(bookDetailProvider(widget.bookId));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerRegenerateFailed),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }

  Future<void> _downloadPdf(BookResult book) async {
    final l = AppLocalizations.of(context);
    try {
      // 로딩 표시
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.viewerPdfGenerating)),
      );

      // API 호출
      final apiClient = ref.read(apiClientProvider);
      final pdfBytes = await apiClient.downloadPdf(book.bookId);

      // 파일 저장
      final directory = await getApplicationDocumentsDirectory();
      final fileName =
          '${book.title.replaceAll(RegExp(r'[\\\\/:*?\"<>|]'), '_').replaceAll(' ', '_')}.pdf';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(pdfBytes);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).viewerPdfSaved(fileName))),
        );
      }
    } catch (e) {
      if (await _handlePaymentRequired(e)) {
        return;
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerPdfDownloadFailed),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }

  void _showShareOptions(BookResult book) {
    final l = AppLocalizations.of(context);
    final kakaoShare = ref.read(kakaoShareServiceProvider);
    final canUseKakaoShare = _allowKakaoShare && kakaoShare.isConfigured;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => AdaptiveModalSheet(
        title: l.viewerShare,
        contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.lg),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: AppSpacing.lg,
              runSpacing: AppSpacing.md,
              children: [
                _ShareButton(
                  icon: Icons.public,
                  label: l.viewerShareLink,
                  onTap: () {
                    Navigator.pop(context);
                    _createAndShareLink(book);
                  },
                ),
                _ShareButton(
                  icon: Icons.link,
                  label: l.viewerShareCopyUrl,
                  onTap: () {
                    Navigator.pop(context);
                    _copyShareUrl(book);
                  },
                ),
                _ShareButton(
                  icon: Icons.chat_bubble,
                  label: l.viewerShareMessage,
                  onTap: () {
                    Navigator.pop(context);
                    _shareText(book);
                  },
                ),
                if (canUseKakaoShare)
                  _ShareButton(
                    icon: Icons.sms_outlined,
                    label: l.viewerShareKakao,
                    onTap: () async {
                      Navigator.pop(context);
                      await _shareToKakao(book);
                    },
                  ),
                _ShareButton(
                  icon: Icons.image_outlined,
                  label: l.viewerShareCover,
                  onTap: () {
                    Navigator.pop(context);
                    _shareCoverImage(book);
                  },
                ),
                _ShareButton(
                  icon: Icons.picture_as_pdf,
                  label: l.viewerSharePdf,
                  onTap: () {
                    Navigator.pop(context);
                    _sharePdf(book);
                  },
                ),
                _ShareButton(
                  icon: Icons.more_horiz,
                  label: l.viewerShareMore,
                  onTap: () async {
                    Navigator.pop(context);
                    // 약간의 딜레이 후 시스템 공유 다이얼로그 표시
                    await Future.delayed(const Duration(milliseconds: 300));
                    _shareText(book);
                  },
                ),
                _ShareButton(
                  icon: Icons.link_off,
                  label: l.viewerShareRevoke,
                  onTap: () async {
                    Navigator.pop(context);
                    await _revokeShare(book);
                  },
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }

  /// 공개 공유 링크는 아이 정보가 외부에 노출되므로 생성 전에 부모 인증을 거친다(F7).
  /// 인증 통과 시 서버에 공개 링크를 생성하고 그 URL을 반환. 취소/빈 URL이면 null.
  Future<String?> _createPublicShareUrl(BookResult book) async {
    final parental = ref.read(parentalControlServiceProvider);
    if (!parental.isAgeGateVerifiedForSession) {
      final passed = await showAgeGateDialog(context, ref);
      if (!passed) {
        return null;
      }
    }
    final api = ref.read(apiClientProvider);
    final result = await api.createShareLink(book.bookId);
    final url = (result['url'] as String?) ?? '';
    return url.isEmpty ? null : url;
  }

  Future<void> _copyShareUrl(BookResult book) async {
    final l = AppLocalizations.of(context);
    try {
      // 실제 공개 링크 URL을 복사한다(이전엔 제목 문구만 복사되던 버그).
      final url = await _createPublicShareUrl(book);
      if (url == null) {
        return;
      }
      await Clipboard.setData(ClipboardData(text: url));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.viewerCopyDone)),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).viewerShareLinkFailed)),
        );
      }
    }
  }

  /// 부모 인증 후 공개 공유 링크 생성·공유(누구나 열어볼 수 있는 동화 페이지).
  Future<void> _createAndShareLink(BookResult book) async {
    final l = AppLocalizations.of(context);
    // 공유 시트 위치는 await 전에 캡처(async gap 후 context 사용 회피).
    final box = context.findRenderObject() as RenderBox?;
    final origin = box != null
        ? box.localToGlobal(Offset.zero) & box.size
        : const Rect.fromLTWH(0, 0, 100, 100);
    try {
      final url = await _createPublicShareUrl(book);
      if (url == null) {
        return;
      }
      await Share.share(
        l.viewerShareLinkText(book.title, url),
        sharePositionOrigin: origin,
      );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).viewerShareLinkFailed)),
        );
      }
    }
  }

  /// 활성 공유 링크 철회(부모가 만든 공개 링크를 비활성화). 철회 UI 부재(F7) 해소.
  Future<void> _revokeShare(BookResult book) async {
    final l = AppLocalizations.of(context);
    try {
      await ref.read(apiClientProvider).revokeShareLink(book.bookId);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.viewerShareRevokeDone)),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).viewerShareRevokeFailed)),
        );
      }
    }
  }

  void _shareText(BookResult book) {
    final l = AppLocalizations.of(context);
    final shareText = l.viewerShareFullText(book.title).trim();
    final box = context.findRenderObject() as RenderBox?;
    Share.share(
      shareText,
      sharePositionOrigin: box != null
          ? box.localToGlobal(Offset.zero) & box.size
          : const Rect.fromLTWH(0, 0, 100, 100),
    );
  }

  Future<void> _shareToKakao(BookResult book) async {
    final l = AppLocalizations.of(context);
    final box = context.findRenderObject() as RenderBox?;
    final shareOrigin = box != null
        ? box.localToGlobal(Offset.zero) & box.size
        : const Rect.fromLTWH(0, 0, 100, 100);

    // 부모 인증 후 실제 공개 토큰 URL을 만든다(이전엔 /books/{bookId} 라 수신자 404).
    final shareUrl = await _createPublicShareUrl(book);
    if (shareUrl == null) {
      return;
    }

    final kakaoShare = ref.read(kakaoShareServiceProvider);
    final result = await kakaoShare.shareBookCard(
      bookId: book.bookId,
      shareUrl: shareUrl,
      title: book.title,
      coverImageUrl: book.coverImageUrl,
      description: l.viewerKakaoDescription,
    );
    if (result.shared) {
      return;
    }
    if (mounted && result.reason != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result.reason!)),
      );
    }

    // 폴백(카카오톡 미설치 등): 앱 딥링크 + 공개 토큰 URL.
    final deepLink = 'ai-story-book://books/${book.bookId}';
    final shareText =
        l.viewerKakaoShareText(book.title, deepLink, shareUrl).trim();
    await Share.share(
      shareText,
      subject: l.viewerKakaoShareSubject(book.title),
      sharePositionOrigin: shareOrigin,
    );
  }

  Future<void> _printPdf(BookResult book) async {
    try {
      final apiClient = ref.read(apiClientProvider);
      final pdfBytes = await apiClient.downloadPdf(book.bookId);
      await Printing.layoutPdf(
        onLayout: (_) async => Uint8List.fromList(pdfBytes),
      );
    } catch (e) {
      if (await _handlePaymentRequired(e)) {
        return;
      }
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(AppLocalizations.of(context).viewerPrintFailed),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  Future<void> _shareCoverImage(BookResult book) async {
    final l = AppLocalizations.of(context);
    try {
      final request = await HttpClient().getUrl(Uri.parse(book.coverImageUrl));
      final response = await request.close();
      final bytes = await consolidateHttpClientResponseBytes(response);

      final directory = await getTemporaryDirectory();
      final fileName =
          '${book.title.replaceAll(RegExp(r'[\\\\/:*?\"<>|]'), '_').replaceAll(' ', '_')}_cover.jpg';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(bytes);
      if (!mounted) {
        return;
      }

      final box = context.findRenderObject() as RenderBox?;
      await Share.shareXFiles(
        [XFile(file.path)],
        text: l.viewerShareCoverText(book.title),
        sharePositionOrigin: box != null
            ? box.localToGlobal(Offset.zero) & box.size
            : const Rect.fromLTWH(0, 0, 100, 100),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(AppLocalizations.of(context).viewerShareCoverFailed),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  Future<void> _sharePdf(BookResult book) async {
    final l = AppLocalizations.of(context);
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.viewerPdfGenerating)),
      );

      final apiClient = ref.read(apiClientProvider);
      final pdfBytes = await apiClient.downloadPdf(book.bookId);

      final directory = await getTemporaryDirectory();
      final fileName =
          '${book.title.replaceAll(RegExp(r'[\\\\/:*?\"<>|]'), '_').replaceAll(' ', '_')}.pdf';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(pdfBytes);
      if (!mounted) return;

      final box = context.findRenderObject() as RenderBox?;
      await Share.shareXFiles(
        [XFile(file.path)],
        text: l.viewerSharePdfText(book.title),
        sharePositionOrigin: box != null
            ? box.localToGlobal(Offset.zero) & box.size
            : const Rect.fromLTWH(0, 0, 100, 100),
      );
    } catch (e) {
      if (await _handlePaymentRequired(e)) {
        return;
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerSharePdfFailed),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }
}

/// 공유 버튼 위젯
class _ShareButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _ShareButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: AppSizing.minTouchTarget,
            height: AppSizing.minTouchTarget,
            decoration: BoxDecoration(
              color: AppColors.primaryLight,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(icon, color: AppColors.primary, size: 28),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(label, style: AppTextStyles.caption),
        ],
      ),
    );
  }
}

/// 표지 페이지
class _CoverPage extends StatelessWidget {
  final String title;
  final String imageUrl;

  const _CoverPage({
    required this.title,
    required this.imageUrl,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Stack(
      fit: StackFit.expand,
      children: [
        Semantics(
          label: l.viewerCoverImageSemantics(title),
          image: true,
          child: CachedNetworkImage(
            imageUrl: imageUrl,
            fit: BoxFit.cover,
            placeholder: (context, url) => const Center(
              child: CircularProgressIndicator(color: Colors.white),
            ),
            errorWidget: (context, url, error) => Container(
              color: AppColors.primary,
              child:
                  const Icon(Icons.broken_image, color: Colors.white, size: 64),
            ),
          ),
        ),
        Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.transparent,
                AppColors.blackOverlayStrong,
              ],
            ),
          ),
        ),
        Positioned(
          left: AppSpacing.lg,
          right: AppSpacing.lg,
          bottom: 100,
          child: Text(
            title,
            style: const TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.bold,
              color: Colors.white,
              shadows: [
                Shadow(
                  offset: Offset(0, 2),
                  blurRadius: 8,
                  color: Colors.black54,
                ),
              ],
            ),
            textAlign: TextAlign.center,
          ),
        ),
      ],
    );
  }
}

/// 본문 페이지
class _ContentPage extends StatelessWidget {
  final int pageNumber;
  final String text;
  final String? secondaryText;
  final String imageUrl;
  final PageResult page;
  final String selectedLanguage;
  final bool followReadingEnabled;
  final double followProgress;
  final VoidCallback onShowLearning;

  const _ContentPage({
    required this.pageNumber,
    required this.text,
    this.secondaryText,
    required this.imageUrl,
    required this.page,
    required this.selectedLanguage,
    required this.followReadingEnabled,
    required this.followProgress,
    required this.onShowLearning,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final hasLearning = page.hasLearningContent;

    return Container(
      color: AppColors.background,
      child: Column(
        children: [
          // 이미지
          Expanded(
            flex: 3,
            child: Semantics(
              label: l.viewerPageImageSemantics(pageNumber),
              image: true,
              child: CachedNetworkImage(
                imageUrl: imageUrl,
                fit: BoxFit.cover,
                width: double.infinity,
                placeholder: (context, url) => Container(
                  color: AppColors.divider,
                  child: const Center(child: CircularProgressIndicator()),
                ),
                errorWidget: (context, url, error) => Container(
                  color: AppColors.divider,
                  child: const Icon(Icons.broken_image, size: 64),
                ),
              ),
            ),
          ),

          // 텍스트
          Expanded(
            flex: 2,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Expanded(
                    child: Center(
                      child: SingleChildScrollView(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            _HighlightedStoryText(
                              text: text,
                              progress: followProgress,
                              enabled: followReadingEnabled,
                              style: const TextStyle(
                                fontSize: 20,
                                height: 1.8,
                                color: AppColors.textPrimary,
                              ),
                              highlightColor: AppColors.primary,
                            ),
                            if (secondaryText != null &&
                                secondaryText!.trim().isNotEmpty) ...[
                              const SizedBox(height: AppSpacing.lg),
                              Container(
                                width: double.infinity,
                                height: 1,
                                color: AppColors.divider,
                              ),
                              const SizedBox(height: AppSpacing.lg),
                              _HighlightedStoryText(
                                text: secondaryText!,
                                progress: 0,
                                enabled: false,
                                style: const TextStyle(
                                  fontSize: 17,
                                  height: 1.7,
                                  color: AppColors.textSecondary,
                                ),
                                highlightColor: AppColors.primary,
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                  // 학습 모드 버튼
                  if (hasLearning)
                    TextButton.icon(
                      onPressed: onShowLearning,
                      icon: const Icon(Icons.school, size: 18),
                      label: Text(l.viewerLearn),
                      style: TextButton.styleFrom(
                        foregroundColor: AppColors.primary,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HighlightedStoryText extends StatelessWidget {
  final String text;
  final double progress;
  final bool enabled;
  final TextStyle style;
  final Color highlightColor;

  const _HighlightedStoryText({
    required this.text,
    required this.progress,
    required this.enabled,
    required this.style,
    required this.highlightColor,
  });

  @override
  Widget build(BuildContext context) {
    final normalized = text.trim();
    if (!enabled || normalized.isEmpty) {
      return Text(
        text,
        style: style,
        textAlign: TextAlign.center,
      );
    }

    final segments = text.split(RegExp(r'(\s+)'));
    final words = segments.where((segment) => segment.trim().isNotEmpty).length;
    if (words == 0) {
      return Text(
        text,
        style: style,
        textAlign: TextAlign.center,
      );
    }

    final target = (words * progress.clamp(0.0, 1.0)).round().clamp(0, words);
    var seenWords = 0;

    final spans = segments.map((segment) {
      if (segment.trim().isEmpty) {
        return TextSpan(text: segment, style: style);
      }
      seenWords += 1;
      return TextSpan(
        text: segment,
        style: style.copyWith(
          color: seenWords <= target ? highlightColor : style.color,
          fontWeight: seenWords <= target ? FontWeight.w700 : style.fontWeight,
        ),
      );
    }).toList(growable: false);

    return RichText(
      textAlign: TextAlign.center,
      text: TextSpan(children: spans),
    );
  }
}

/// 네비게이션 버튼
class _NavButton extends StatelessWidget {
  final IconData icon;
  final bool enabled;
  final VoidCallback onPressed;
  final String tooltip;

  const _NavButton({
    required this.icon,
    required this.enabled,
    required this.onPressed,
    required this.tooltip,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: tooltip,
      button: true,
      enabled: enabled,
      child: GestureDetector(
        onTap: enabled ? onPressed : null,
        child: Container(
          width: AppSizing.minTouchTarget,
          height: AppSizing.minTouchTarget,
          decoration: BoxDecoration(
            color: enabled ? AppColors.whiteOverlay : Colors.transparent,
            borderRadius: BorderRadius.circular(AppSizing.minTouchTarget / 2),
          ),
          child: Icon(
            icon,
            color: enabled ? Colors.white : AppColors.whiteOverlayLight,
            size: 32,
          ),
        ),
      ),
    );
  }
}

/// 오디오 재생 버튼
class _AudioButton extends StatelessWidget {
  final bool isPlaying;
  final bool isLoading;
  final VoidCallback onPressed;

  const _AudioButton({
    required this.isPlaying,
    required this.isLoading,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Semantics(
      label: isPlaying ? l.viewerPauseAudioTooltip : l.viewerPlayAudioTooltip,
      button: true,
      child: GestureDetector(
        onTap: isLoading ? null : onPressed,
        child: Container(
          width: AppSizing.minTouchTarget,
          height: AppSizing.minTouchTarget,
          decoration: BoxDecoration(
            color: isPlaying ? AppColors.primaryMuted : AppColors.whiteOverlay,
            borderRadius: BorderRadius.circular(AppSizing.minTouchTarget / 2),
          ),
          child: isLoading
              ? const Padding(
                  padding: EdgeInsets.all(12),
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : Icon(
                  isPlaying ? Icons.pause : Icons.volume_up,
                  color: Colors.white,
                  size: 24,
                ),
        ),
      ),
    );
  }
}

/// 언어 토글 버튼
class _LanguageToggle extends StatelessWidget {
  final String selectedLanguage;
  final bool hasTranslation;
  final VoidCallback onToggle;

  const _LanguageToggle({
    required this.selectedLanguage,
    required this.hasTranslation,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    if (!hasTranslation) return const SizedBox.shrink();

    final l = AppLocalizations.of(context);
    return Semantics(
      label: l.viewerLanguageToggleTooltip,
      button: true,
      child: GestureDetector(
        onTap: onToggle,
        child: Container(
          constraints: const BoxConstraints(
            minWidth: AppSizing.minTouchTarget,
            minHeight: AppSizing.minTouchTarget,
          ),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppColors.whiteOverlay,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                selectedLanguage == 'ko' ? l.viewerLanguageKo : l.viewerLanguageEn,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
              const SizedBox(width: 4),
              const Icon(Icons.swap_horiz, color: Colors.white, size: 16),
            ],
          ),
        ),
      ),
    );
  }
}

/// 학습 모드 시트
class _LearningModeSheet extends StatefulWidget {
  final PageResult page;
  final ScrollController scrollController;
  final void Function(bool correct, int questionIndex)? onQuizAnswered;
  final void Function(String term, bool correct, int index)? onVocabAnswered;

  const _LearningModeSheet({
    required this.page,
    required this.scrollController,
    this.onQuizAnswered,
    this.onVocabAnswered,
  });

  @override
  State<_LearningModeSheet> createState() => _LearningModeSheetState();
}

class _LearningModeSheetState extends State<_LearningModeSheet>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Column(
      children: [
        // 핸들
        const SizedBox(height: AppSpacing.md),
        Container(
          width: 40,
          height: 4,
          decoration: BoxDecoration(
            color: AppColors.divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // 제목
        Text(l.viewerLearningModeTitle, style: AppTextStyles.heading2),
        const SizedBox(height: AppSpacing.md),

        // 탭 바
        TabBar(
          controller: _tabController,
          labelColor: AppColors.primary,
          unselectedLabelColor: AppColors.textSecondary,
          indicatorColor: AppColors.primary,
          tabs: [
            Tab(icon: const Icon(Icons.abc), text: l.viewerTabWord),
            Tab(icon: const Icon(Icons.help_outline), text: l.viewerTabQuestion),
            Tab(icon: const Icon(Icons.quiz), text: l.viewerTabQuiz),
          ],
        ),

        // 탭 내용
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              _VocabTab(
                vocab: widget.page.vocab ?? [],
                onAnswered: widget.onVocabAnswered,
              ),
              _ComprehensionTab(
                  questions: widget.page.comprehensionQuestions ?? []),
              _QuizTab(
                quiz: widget.page.quiz ?? [],
                onAnswered: widget.onQuizAnswered,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 단어 탭 — '어휘 맞추기 게임'(4지선다). 정답이 vocab 측정으로 기록돼 '학습 어휘'를 살린다.
/// 단어가 2개 이상이면 게임, 1개뿐이면 단순 표시로 폴백.
class _VocabTab extends StatelessWidget {
  final List<VocabItem> vocab;
  final void Function(String term, bool correct, int index)? onAnswered;

  const _VocabTab({required this.vocab, this.onAnswered});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    if (vocab.isEmpty) {
      return Center(child: Text(l.viewerNoVocab));
    }
    // 서로 다른 뜻이 3개 이상일 때만 게임(3지선다↑) — 2지선다 trivial 게임의 측정 오염 방지.
    final meanings = vocab.map((v) => v.meaning).toList();
    final playable = meanings.toSet().length >= 3;
    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: vocab.length,
      itemBuilder: (context, index) {
        final item = vocab[index];
        if (!playable) {
          return _VocabDisplayCard(item: item);
        }
        return VocabGameCard(
          key: ValueKey('vocab-${item.word}-$index'),
          item: item,
          allMeanings: meanings,
          onAnswered: (correct) => onAnswered?.call(item.word, correct, index),
        );
      },
    );
  }
}

/// 단어 1개일 때 폴백(게임 불가) — 단어·뜻 표시.
class _VocabDisplayCard extends StatelessWidget {
  final VocabItem item;
  const _VocabDisplayCard({required this.item});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          children: [
            Text(item.word,
                style: AppTextStyles.heading3
                    .copyWith(color: AppColors.primary)),
            const SizedBox(width: AppSpacing.sm),
            Expanded(child: Text(item.meaning, style: AppTextStyles.body)),
          ],
        ),
      ),
    );
  }
}

// 어휘 맞추기 게임 카드는 lib/widgets/vocab_game_card.dart(VocabGameCard)로 추출 —
// 자체완결형이라 단위 위젯 테스트 가능. 사용은 _VocabTab 참조.

/// 질문 탭
class _ComprehensionTab extends StatelessWidget {
  final List<ComprehensionQuestion> questions;

  const _ComprehensionTab({required this.questions});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    if (questions.isEmpty) {
      return Center(child: Text(l.viewerNoComprehension));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: questions.length,
      itemBuilder: (context, index) {
        final q = questions[index];
        return _ComprehensionCard(question: q, index: index + 1);
      },
    );
  }
}

class _ComprehensionCard extends StatefulWidget {
  final ComprehensionQuestion question;
  final int index;

  const _ComprehensionCard({required this.question, required this.index});

  @override
  State<_ComprehensionCard> createState() => _ComprehensionCardState();
}

class _ComprehensionCardState extends State<_ComprehensionCard> {
  bool _showAnswer = false;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.viewerComprehensionQuestion(widget.index, widget.question.question),
              style: AppTextStyles.body.copyWith(fontWeight: FontWeight.bold),
            ),
            if (widget.question.answer != null) ...[
              const SizedBox(height: AppSpacing.sm),
              if (_showAnswer)
                Text(
                  l.viewerComprehensionAnswer(widget.question.answer!),
                  style: AppTextStyles.body.copyWith(color: AppColors.primary),
                )
              else
                TextButton(
                  onPressed: () => setState(() => _showAnswer = true),
                  child: Text(l.viewerShowAnswer),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 퀴즈 탭
class _QuizTab extends StatelessWidget {
  final List<QuizItem> quiz;
  final void Function(bool correct, int questionIndex)? onAnswered;

  const _QuizTab({required this.quiz, this.onAnswered});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    if (quiz.isEmpty) {
      return Center(child: Text(l.viewerNoQuiz));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: quiz.length,
      itemBuilder: (context, index) {
        final q = quiz[index];
        return _QuizCard(quiz: q, index: index + 1, onAnswered: onAnswered);
      },
    );
  }
}

class _QuizCard extends StatefulWidget {
  final QuizItem quiz;
  final int index;
  final void Function(bool correct, int questionIndex)? onAnswered;

  const _QuizCard({required this.quiz, required this.index, this.onAnswered});

  @override
  State<_QuizCard> createState() => _QuizCardState();
}

class _QuizCardState extends State<_QuizCard> {
  int? _selectedIndex;
  bool _showResult = false;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final isCorrect = _selectedIndex == widget.quiz.answerIndex;

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.viewerQuizQuestion(widget.index, widget.quiz.question),
              style: AppTextStyles.body.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: AppSpacing.md),
            ...widget.quiz.options.asMap().entries.map((entry) {
              final optionIndex = entry.key;
              final option = entry.value;
              final isSelected = _selectedIndex == optionIndex;
              final isAnswer = optionIndex == widget.quiz.answerIndex;

              Color? backgroundColor;
              if (_showResult && isAnswer) {
                backgroundColor = AppColors.success.withValues(alpha: 0.2);
              } else if (_showResult && isSelected && !isCorrect) {
                backgroundColor = AppColors.error.withValues(alpha: 0.2);
              } else if (isSelected) {
                backgroundColor = AppColors.primaryLight;
              }

              return GestureDetector(
                onTap: _showResult
                    ? null
                    : () => setState(() => _selectedIndex = optionIndex),
                child: Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: AppSpacing.sm),
                  padding: const EdgeInsets.all(AppSpacing.sm),
                  decoration: BoxDecoration(
                    color: backgroundColor,
                    border: Border.all(
                      color: isSelected ? AppColors.primary : AppColors.divider,
                    ),
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                  child: Text(option),
                ),
              );
            }),
            if (_selectedIndex != null && !_showResult)
              ElevatedButton(
                onPressed: () {
                  final correct = _selectedIndex == widget.quiz.answerIndex;
                  setState(() => _showResult = true);
                  widget.onAnswered?.call(correct, widget.index - 1);
                },
                child: Text(l.viewerCheckAnswer),
              ),
            if (_showResult) ...[
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Icon(
                    isCorrect ? Icons.check_circle : Icons.cancel,
                    color: isCorrect ? AppColors.success : AppColors.error,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    isCorrect ? l.viewerQuizCorrect : l.viewerQuizIncorrect,
                    style: TextStyle(
                      color: isCorrect ? AppColors.success : AppColors.error,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              if (widget.quiz.explanation != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  widget.quiz.explanation!,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

/// 부모 가이드 시트
class _ParentGuideSheet extends StatelessWidget {
  final ParentGuide parentGuide;
  final ScrollController scrollController;

  const _ParentGuideSheet({
    required this.parentGuide,
    required this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Column(
      children: [
        // 핸들
        const SizedBox(height: AppSpacing.md),
        Container(
          width: 40,
          height: 4,
          decoration: BoxDecoration(
            color: AppColors.divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // 제목
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.family_restroom, color: AppColors.primary),
            const SizedBox(width: AppSpacing.sm),
            Text(l.viewerParentGuideTitle, style: AppTextStyles.heading2),
          ],
        ),
        const SizedBox(height: AppSpacing.md),

        // 내용
        Expanded(
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              // 요약
              _GuideSection(
                icon: Icons.summarize,
                title: l.viewerGuideSummaryTitle,
                content: parentGuide.summary,
              ),
              const SizedBox(height: AppSpacing.lg),

              // 토론 주제
              _GuideSection(
                icon: Icons.chat,
                title: l.viewerGuideDiscussionTitle,
                items: parentGuide.discussionPrompts,
              ),
              const SizedBox(height: AppSpacing.lg),

              // 활동
              _GuideSection(
                icon: Icons.sports_esports,
                title: l.viewerGuideActivitiesTitle,
                items: parentGuide.activities,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _GuideSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? content;
  final List<String>? items;

  const _GuideSection({
    required this.icon,
    required this.title,
    this.content,
    this.items,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, color: AppColors.primary, size: 20),
            const SizedBox(width: AppSpacing.sm),
            Text(title, style: AppTextStyles.heading3),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        if (content != null) Text(content!, style: AppTextStyles.body),
        if (items != null)
          ...items!.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('• ', style: TextStyle(fontSize: 16)),
                    Expanded(child: Text(item, style: AppTextStyles.body)),
                  ],
                ),
              )),
      ],
    );
  }
}