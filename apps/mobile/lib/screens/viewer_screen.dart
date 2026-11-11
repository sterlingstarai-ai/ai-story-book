import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:confetti/confetti.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:audio_session/audio_session.dart';
import 'package:just_audio/just_audio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/page_audio_playback.dart';
import 'package:printing/printing.dart';
import '../core/api_error.dart';
import '../core/media_urls.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../widgets/vocab_game_card.dart';
import '../providers/providers.dart';
import 'inpaint_screen.dart';
import '../services/analytics.dart';
import '../services/api_client.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';
import '../widgets/common_widgets.dart';
import '../widgets/scoped_book_image.dart';
import '../services/book_media_store.dart';
import '../services/book_scoped_cache_manager.dart';
import '../widgets/credit_shortage_modal.dart';
import '../widgets/content_report_sheet.dart';

/// 페이지 재생성 잡의 관측 결과. 타임아웃을 실패로 섞지 않는다(느린 성공 보호).
enum _PageJobOutcome { completed, failed, qualityFailed, timeout }

/// 책 뷰어 화면
class ViewerScreen extends ConsumerStatefulWidget {
  final String bookId;

  const ViewerScreen({super.key, required this.bookId});

  @override
  ConsumerState<ViewerScreen> createState() => _ViewerScreenState();
}

class _ViewerScreenState extends ConsumerState<ViewerScreen>
    with WidgetsBindingObserver {
  static const _narrationSpeedKey = 'narration_playback_speed_v1';
  static const _narrationSpeeds = [0.9, 1.0, 1.15, 1.3];
  static const _narrationPrefetchGrace = Duration(milliseconds: 200);
  static const _illustrationRefreshInterval = Duration(minutes: 1);

  Timer? _mediaRefreshTimer;
  Timer? _illustrationRefreshCooldown;
  late PageController _pageController;
  late final ConfettiController _completionConfettiController;
  final AudioPlayer _audioPlayer = AudioPlayer();
  late final PageAudioPlayback _pageAudio;
  late final SharedPreferences _audioPreferences;
  int _lastSavedAudioSecond = -1;
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
  // Keep the reading session's identity: disposal may happen after providers
  // have changed or become unavailable, and must never read a new profile.
  late final ApiClient _readingSessionApi;
  // 읽기 기록은 이 라우트보다 오래 산다(퇴장 기록은 dispose에서 발행). 기록이 끝난 뒤
  // 홈의 '오늘의 읽기' 카드를 새로 읽어오려면 위젯이 아닌 컨테이너를 잡아 둬야 한다.
  late final ProviderContainer _readingSessionScope;
  bool _progressRestored = false;
  bool _regenerationInFlight = false;
  // 같은 세션에서 학습 시트 재오픈 시 동일 퀴즈 중복 기록 방지(성장 집계 왜곡 방지)
  final Set<String> _recordedQuiz = {};
  bool _dualLanguageEnabled = false;
  bool _followReadingEnabled = false;
  bool _allowKakaoShare = true;
  bool _sleepModeEnabled = false;
  DateTime? _sleepModeEndsAt;
  bool _continuousNarration = false;
  bool _narrationAutoAdvancing = false;
  String? _lastNarrationPrefetch;
  ({String key, Future<void> done})? _activeNarrationPrefetch;
  BookMediaStore? _narrationCacheStore;
  final _narrationCaches =
      <({String extension, bool lookahead}), BookScopedCacheManager>{};
  double _audioProgress = 0;
  int _audioProgressPage = 0;
  BookResult? _activeBook;
  DateTime _viewStartedAt = DateTime.now();
  // 다국어 지원
  String _selectedLanguage = 'ko'; // 책 언어로 초기화됨(H3). ko/en 토글은 이중언어 책용.
  bool _languageInitialized = false;

  Future<void> _configureAudioSession() async {
    // H28(G27=a): 취침 오디오가 화면 잠금(백그라운드)에서도 재생되도록 playback 카테고리
    // 구성. UIBackgroundModes(audio)와 함께 동작. 플러그인 실패 시 조용히 폴백하되 로그.
    try {
      final session = await AudioSession.instance;
      await session.configure(const AudioSessionConfiguration.speech());
    } catch (e, st) {
      debugPrint('AudioSession configure failed: $e\n$st');
    }
  }

  @override
  void initState() {
    super.initState();
    _readingSessionApi = ref.read(apiClientProvider);
    _audioPreferences = ref.read(sharedPreferencesProvider);
    final savedSpeed = _audioPreferences.get(_narrationSpeedKey);
    if (savedSpeed is double && _narrationSpeeds.contains(savedSpeed)) {
      unawaited(_audioPlayer.setSpeed(savedSpeed).catchError((Object _) {}));
    }
    _pageAudio = PageAudioPlayback(
      JustAudioPagePlayer(_audioPlayer),
      onError: (error) => unawaited(_showAudioError(error)),
    );
    _pageAudio.addListener(() {
      if (mounted) setState(() => _isLoadingAudio = _pageAudio.loading);
    });
    _readingSessionScope = ProviderScope.containerOf(context, listen: false);
    WidgetsBinding.instance.addObserver(this);
    _mediaRefreshTimer = Timer.periodic(
      _illustrationRefreshInterval,
      (_) => _refreshMediaIfNeeded(),
    );
    _pageController = PageController();
    _completionConfettiController = ConfettiController(
      duration: const Duration(seconds: 3),
    );
    _viewStartedAt = DateTime.now();
    ref
        .read(analyticsProvider)
        .logEvent(
          AnalyticsEvents.readingStarted,
          params: {'book_id': widget.bookId},
        );
    unawaited(_loadViewerSettings());
    unawaited(_configureAudioSession());
    // Store subscription to cancel later (memory leak fix)
    _playerStateSubscription = _audioPlayer.playerStateStream.listen((state) {
      if (mounted) {
        setState(() {
          _isPlaying =
              state.playing &&
              state.processingState != ProcessingState.completed;
          if (state.processingState == ProcessingState.completed) {
            _audioProgress = 1;
          }
        });
      }
      if (mounted &&
          (_sleepModeEnabled || _continuousNarration) &&
          state.playing &&
          state.processingState == ProcessingState.completed &&
          _pageAudio.takeCompletion()) {
        unawaited(_advanceNarration());
      } else if (mounted &&
          state.playing &&
          state.processingState == ProcessingState.ready) {
        unawaited(_prefetchNextNarration());
      }
    });
    _positionSubscription = _audioPlayer.positionStream.listen((position) {
      if (!mounted || !_isPlaying || !_pageAudio.hasLoadedSource) {
        return;
      }
      if (_audioProgressPage != _currentPage) {
        return;
      }
      final second = position.inSeconds;
      if (second != _lastSavedAudioSecond && second % 2 == 0) {
        _lastSavedAudioSecond = second;
        unawaited(_saveAudioPosition(position));
      }
      final duration = _audioPlayer.duration;
      if (duration == null || duration.inMilliseconds <= 0) {
        return;
      }
      final ratio = (position.inMilliseconds / duration.inMilliseconds).clamp(
        0.0,
        1.0,
      );
      if ((ratio - _audioProgress).abs() < 0.02 && ratio < 1) {
        return;
      }
      setState(() => _audioProgress = ratio);
    });
  }

  void _refreshMediaIfNeeded() {
    final book = _activeBook;
    if (!mounted || book == null) return;
    // The adjacent pages are the ones PageView may prepare for the next turn.
    final first = max(0, _currentPage - 1);
    final last = min(book.pages.length, _currentPage + 1);
    for (var index = first; index <= last; index++) {
      final url = index == 0
          ? book.coverImageUrl
          : book.pages[index - 1].imageUrl;
      if (mediaUrlNeedsRefresh(url)) {
        _refreshRejectedIllustration();
        return;
      }
    }
  }

  bool get _canRefreshBookMedia =>
      mounted &&
      identical(ref.read(apiClientProvider), _readingSessionApi) &&
      !ref.read(bookMediaBlockedProvider(widget.bookId));

  void _requestIllustrationRefresh({required bool automatic}) {
    if (automatic && _illustrationRefreshCooldown?.isActive == true) return;
    final detail = bookDetailProvider(widget.bookId);
    if (ref.read(detail).isLoading) return;
    _illustrationRefreshCooldown?.cancel();
    _illustrationRefreshCooldown = Timer(
      _illustrationRefreshInterval,
      () => _illustrationRefreshCooldown = null,
    );
    ref.invalidate(detail);
  }

  void _refreshRejectedIllustration() {
    if (_canRefreshBookMedia) _requestIllustrationRefresh(automatic: true);
  }

  Future<void> _retryRejectedIllustration() async {
    if (!_canRefreshBookMedia) return;
    _requestIllustrationRefresh(automatic: false);
    await ref.read(bookDetailProvider(widget.bookId).future);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refreshMediaIfNeeded();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _mediaRefreshTimer?.cancel();
    _illustrationRefreshCooldown?.cancel();
    _recordAbandonedReadIfNeeded();
    // Cancel subscription to prevent memory leak
    _playerStateSubscription?.cancel();
    _positionSubscription?.cancel();
    _sleepModeTimer?.cancel();
    _completionConfettiController.dispose();
    _pageController.dispose();
    _pageAudio.dispose();
    _closeNarrationCaches();
    unawaited(_audioPlayer.dispose());
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
    // Reading metrics must not interrupt disposal. Future.sync also catches
    // synchronous transport errors (for example a client closed at sign-out).
    unawaited(
      Future<Map<String, dynamic>>.sync(
            () => _readingSessionApi.recordReading(
              bookId: widget.bookId,
              readingTime: seconds < 0 ? 0 : seconds,
              completed: false,
            ),
          )
          .then((result) {
            // 서버는 이 기록만으로도 '오늘 읽음'이 된다. 홈 카드가 캐시된 옛 값을
            // 계속 보여 주지 않도록 기록 성공 후에만 무효화한다.
            _readingSessionScope.invalidate(homeStreakProvider);
            return result;
          })
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
    ref.listen<bool>(bookMediaBlockedProvider(widget.bookId), (
      previous,
      blocked,
    ) {
      if (blocked) _stopUnavailableNarration();
    });
    ref.listen(apiClientProvider, (previous, next) {
      if (!identical(next, _readingSessionApi)) _stopUnavailableNarration();
    });
    ref.listen(bookMediaStoreProvider, (previous, next) {
      if (_narrationCacheStore != null &&
          !identical(next.valueOrNull?.store, _narrationCacheStore)) {
        _stopUnavailableNarration();
      }
    });
    final bookAsync = ref.watch(bookDetailProvider(widget.bookId));

    final reader = Scaffold(
      backgroundColor: StorybookColors.ink,
      bottomNavigationBar: _showControls
          ? bookAsync.maybeWhen(
              data: (book) => _buildControls(book, book.pages.length + 1),
              orElse: () => null,
            )
          : null,
      body: bookAsync.when(
        data: (book) => _buildViewer(book),
        loading: () =>
            const Center(child: CircularProgressIndicator(color: Colors.white)),
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
    final darkReaderBackground =
        bookAsync.valueOrNull == null ||
        _currentPage == 0 ||
        _sleepModeEnabled ||
        AppPalette.of(context).isDark;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: darkReaderBackground
            ? Brightness.light
            : Brightness.dark,
        statusBarBrightness: darkReaderBackground
            ? Brightness.dark
            : Brightness.light,
      ),
      child: reader,
    );
  }

  Widget _buildViewer(BookResult book) {
    _activeBook = book;
    // H3: 오디오·발음을 책 언어로 요청하도록 최초 1회 책 언어로 초기화한다.
    // (ja/zh/es 책이 한국어 보이스로 오합성된 오디오를 요청하던 문제 제거.)
    if (!_languageInitialized) {
      final lang = book.language;
      if (lang != null && lang.isNotEmpty) {
        _selectedLanguage = lang;
      }
      _languageInitialized = true;
    }
    // 표지(0) + 페이지들
    final totalPages = book.pages.length + 1;
    _restoreReadingProgressIfNeeded(totalPages);
    final currentWarning = _currentGenerationWarning(book);

    final l = AppLocalizations.of(context);
    final controlsHint = _showControls
        ? l.viewerHideReadingControls
        : l.viewerShowReadingControls;
    final audioOk = narrationSupported(
      ref.watch(capabilitiesProvider).valueOrNull,
    );
    return Stack(
      fit: StackFit.expand,
      children: [
        // 페이지 뷰
        PageView.builder(
          controller: _pageController,
          allowImplicitScrolling: true,
          itemCount: totalPages,
          onPageChanged: (index) async {
            final continueNarration =
                _narrationAutoAdvancing || _isPlaying || _pageAudio.loading;
            final stopped = _pageAudio.stop();
            setState(() {
              _currentPage = index;
              _audioProgress = 0;
              _audioProgressPage = index;
            });
            if (index > _maxPageReached) {
              _maxPageReached = index;
            }
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (_currentPage == index) _refreshMediaIfNeeded();
            });
            unawaited(_saveReadingProgress(index));
            await stopped;
            if (mounted &&
                _currentPage == index &&
                (_sleepModeEnabled ||
                    (_continuousNarration && continueNarration)) &&
                index > 0) {
              await _playPageAudio(book, restart: true);
            }
          },
          itemBuilder: (context, index) {
            if (index == 0) {
              // 표지
              return _CoverPage(
                bookId: book.bookId,
                title: book.getTitle(_selectedLanguage),
                imageUrl: book.coverImageUrl,
                onTap: _toggleControls,
                controlsHint: controlsHint,
                onSignedUrlRejected: _refreshRejectedIllustration,
                onRetrySignedUrl: _retryRejectedIllustration,
              );
            } else {
              // 본문 페이지
              final page = book.pages[index - 1];
              final secondaryText = _dualLanguageEnabled
                  ? (_selectedLanguage == 'ko' ? page.textEn : page.textKo)
                  : null;
              return _ContentPage(
                bookId: book.bookId,
                showInlineLearning: !_showControls,
                sleepMode: _sleepModeEnabled,
                onIllustrationTap: _toggleControls,
                controlsHint: controlsHint,
                onSignedUrlRejected: _refreshRejectedIllustration,
                onRetrySignedUrl: _retryRejectedIllustration,
                onNarrate: audioOk && index == _currentPage
                    ? () {
                        if (!_showControls) {
                          setState(() => _showControls = true);
                        }
                        unawaited(_toggleAudio(book));
                      }
                    : null,
                onComplete: index == totalPages - 1 && !_completionHandled
                    ? () => _completeReading(book)
                    : null,
                pageNumber: page.pageNumber,
                text: page.getText(_selectedLanguage),
                secondaryText: secondaryText,
                imageUrl: page.imageUrl,
                page: page,
                selectedLanguage: _selectedLanguage,
                followReadingEnabled: _followReadingEnabled,
                followProgress: _audioProgressPage == index
                    ? _audioProgress
                    : 0,
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
      ],
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
                  color: AppPalette.of(context).primaryLight,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.card_giftcard,
                      color: AppPalette.of(context).primary,
                      size: 20,
                    ),
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

  Future<void> _completeReading(BookResult book) async {
    if (_completionHandled || _currentPage != book.pages.length) return;
    setState(() => _completionHandled = true);
    ref
        .read(analyticsProvider)
        .logEvent(
          AnalyticsEvents.readingCompleted,
          params: {
            'book_id': widget.bookId,
            'reading_seconds': DateTime.now()
                .difference(_viewStartedAt)
                .inSeconds,
          },
        );
    await _handleBookCompleted(book);
  }

  Future<void> _handleBookCompleted(BookResult book) async {
    await _clearReadingProgress();
    final readingSeconds = DateTime.now().difference(_viewStartedAt).inSeconds;
    final api = _readingSessionApi;
    int streak = 0;

    try {
      final readResult = await api.recordReading(
        bookId: widget.bookId,
        readingTime: readingSeconds < 0 ? 0 : readingSeconds,
        completed: true,
      );
      _readingSessionScope.invalidate(homeStreakProvider);
      if (!mounted) return;
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

    if (!mounted) return;
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
        child: SingleChildScrollView(
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
                  color: AppPalette.of(context).surface,
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
                        color: AppPalette.of(context).primaryLight,
                        borderRadius: BorderRadius.circular(44),
                      ),
                      child: Icon(
                        Icons.auto_awesome,
                        size: 44,
                        color: AppPalette.of(context).primary,
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

  /// H1/G9: 이 배포에서 오디오(낭독·발음)를 제공하는가.
  /// 미지원이면 UI를 숨긴다 — 비활성 배포에서 탭마다 에러가 나던 문제 차단.
  /// 로딩·조회 실패 중에는 지원을 확인할 수 없어 노출하지 않는다.
  bool _audioSupportedFrom(Map<String, dynamic>? caps) =>
      caps?['audio_supported'] == true;

  Widget _buildControls(BookResult book, int totalPages) {
    final l = AppLocalizations.of(context);
    final colors = StorybookColors(
      _sleepModeEnabled || AppPalette.of(context).isDark || _currentPage == 0,
    );
    final audioOk = narrationSupported(
      ref.watch(capabilitiesProvider).valueOrNull,
    );
    final page = _currentPage > 0 && _currentPage <= book.pages.length
        ? book.pages[_currentPage - 1]
        : null;
    final showLearning =
        page?.hasLearningContent == true &&
        MediaQuery.sizeOf(context).width >= 5 * AppSizing.minTouchTarget;
    const iconSize = 23.0;
    final buttonStyle = IconButton.styleFrom(
      minimumSize: const Size.square(AppSizing.minTouchTarget),
      padding: EdgeInsets.zero,
      foregroundColor: colors.text,
    );
    final metaStyle = AppTextStyles.caption.copyWith(
      color: colors.muted,
      fontWeight: FontWeight.w600,
    );

    return ColoredBox(
      key: const Key('viewer_bottom_controls'),
      color: colors.sheet,
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Divider(height: 1, color: colors.rule),
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Wrap(
                alignment: WrapAlignment.center,
                spacing: AppSpacing.sm,
                children: [
                  Text(
                    _currentPage == 0
                        ? l.viewerCover
                        : l.viewerPageIndicator(_currentPage, totalPages - 1),
                    style: metaStyle,
                  ),
                  if (_sleepModeEnabled)
                    Text(
                      l.viewerSleepRemaining(_sleepRemainingText()),
                      key: const Key('viewer_sleep_countdown'),
                      style: metaStyle,
                    ),
                  if (_isLoadingAudio)
                    Semantics(
                      liveRegion: true,
                      child: Text(l.viewerNarrationPreparing, style: metaStyle),
                    ),
                ],
              ),
            ),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  IconButton(
                    style: buttonStyle,
                    iconSize: iconSize,
                    icon: const Icon(Icons.chevron_left),
                    tooltip: l.viewerPreviousPageTooltip,
                    onPressed: _currentPage == 0
                        ? null
                        : () {
                            _pageController.previousPage(
                              duration: const Duration(milliseconds: 300),
                              curve: Curves.easeInOut,
                            );
                          },
                  ),
                  if (_currentPage == 0 && audioOk && book.pages.isNotEmpty)
                    Flexible(
                      child: TextButton(
                        style: TextButton.styleFrom(
                          minimumSize: const Size.square(
                            AppSizing.minTouchTarget,
                          ),
                          foregroundColor: colors.accent,
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.xs,
                          ),
                        ),
                        onPressed: () => _startContinuousNarration(book),
                        child: Text(
                          l.viewerListenFromStart,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ),
                  if (_currentPage > 0 && audioOk)
                    IconButton(
                      style: buttonStyle,
                      tooltip: _isPlaying
                          ? l.viewerPauseAudioTooltip
                          : l.viewerPlayAudioTooltip,
                      onPressed: _isLoadingAudio
                          ? null
                          : () => _toggleAudio(book),
                      icon: DecoratedBox(
                        decoration: BoxDecoration(
                          color: colors.tint,
                          shape: BoxShape.circle,
                        ),
                        child: SizedBox.square(
                          dimension: 42,
                          child: Center(
                            child: _isLoadingAudio
                                ? SizedBox.square(
                                    dimension: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: colors.accent,
                                    ),
                                  )
                                : Icon(
                                    _isPlaying
                                        ? Icons.pause_rounded
                                        : Icons.play_arrow_rounded,
                                    size: iconSize,
                                    color: colors.accent,
                                  ),
                          ),
                        ),
                      ),
                    ),
                  IconButton(
                    style: buttonStyle,
                    iconSize: iconSize,
                    icon: const Icon(Icons.chevron_right),
                    tooltip: l.viewerNextPageTooltip,
                    onPressed: _currentPage >= totalPages - 1
                        ? null
                        : () {
                            _pageController.nextPage(
                              duration: const Duration(milliseconds: 300),
                              curve: Curves.easeInOut,
                            );
                          },
                  ),
                  if (showLearning && page != null)
                    IconButton(
                      key: const Key('viewer_learning_bar'),
                      style: buttonStyle,
                      iconSize: iconSize,
                      icon: const Icon(Icons.menu_book_rounded),
                      tooltip: l.viewerLearn,
                      onPressed: () => _showLearningMode(book, page),
                    ),
                  IconButton(
                    style: buttonStyle,
                    iconSize: iconSize,
                    icon: const Icon(Icons.more_vert),
                    tooltip: l.viewerMoreOptionsTooltip,
                    onPressed: () => _showOptionsMenu(book),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _toggleLanguage(BookResult book) async {
    final wasPlaying = _isPlaying;
    await _pageAudio.stop();
    if (!mounted) return;
    setState(() {
      _selectedLanguage = _selectedLanguage == 'ko' ? 'en' : 'ko';
    });
    if (wasPlaying && _currentPage > 0) {
      await _toggleAudio(book);
    }
  }

  Future<void> _toggleAudio(BookResult book) async {
    if (_isPlaying) {
      await _pageAudio.pause();
      await _saveAudioPosition(_audioPlayer.position);
      return;
    }
    await _playPageAudio(book);
  }

  String _narrationSpeedLabel(AppLocalizations l, double speed) =>
      l.viewerNarrationSpeedValue(speed == 1 ? '1' : speed.toString());

  Future<void> _pickNarrationSpeed() async {
    final l = AppLocalizations.of(context);
    final speed = await showDialog<double>(
      context: context,
      builder: (context) => SimpleDialog(
        title: Text(l.viewerNarrationSpeed),
        children: [
          for (final option in _narrationSpeeds)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, option),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: Semantics(
                    selected: option == _audioPlayer.speed,
                    child: Text(_narrationSpeedLabel(l, option)),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
    if (!mounted || speed == null || speed == _audioPlayer.speed) return;
    try {
      await _audioPlayer.setSpeed(speed);
      if (await _audioPreferences.setDouble(_narrationSpeedKey, speed)) return;
    } catch (_) {
      // A speed change never re-requests the recording.
    }
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(l.settingsSaveError)));
  }

  Future<void> _saveAudioPosition(Duration position) async {
    if (_currentPage < 1 || _completionHandled) return;
    if (!identical(ref.read(apiClientProvider), _readingSessionApi)) return;
    final voice = narrationVoiceOrDefault(
      _audioPreferences.getString(narrationVoicePreferenceKey),
    );
    final style = narrationStyleOrDefault(
      _audioPreferences.getString(narrationStylePreferenceKey),
    );
    final provider = narrationAudioProvider(
      ref.read(capabilitiesProvider).valueOrNull,
    );
    final value =
        '$_currentPage|$_selectedLanguage|${position.inMilliseconds}|$voice|$style|${provider ?? 'unknown'}';
    try {
      final progress = await ref.read(
        readingProgressProvider(widget.bookId).future,
      );
      await progress.saveAudio(value);
    } catch (_) {
      // Saving a resume point must not interrupt playback.
    }
  }

  Future<Duration> _savedAudioPosition({
    required int page,
    required String language,
    required String voice,
    required String style,
    required String? provider,
  }) async {
    if (!identical(ref.read(apiClientProvider), _readingSessionApi)) {
      return Duration.zero;
    }
    String? saved;
    try {
      final progress = await ref.read(
        readingProgressProvider(widget.bookId).future,
      );
      saved = await progress.audio();
    } catch (_) {
      return Duration.zero;
    }
    if (!mounted) return Duration.zero;
    return narrationResumePosition(
      saved,
      page: page,
      language: language,
      voice: voice,
      style: style,
      provider: provider,
    );
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
    final message = apiError.localizedMessage(l);
    // M5: 안정 키 기반 분기(서버 error.details.reason). 한국어 문자열 매칭 금지.
    final title = apiError.isPlanUpgradeRequired
        ? l.viewerPlanUpgradeNeeded
        : l.viewerCreditShortage;
    await showCreditShortageModal(context, title: title, message: message);
    return true;
  }

  Future<void> _showAudioError(Object error) async {
    if (await _handlePaymentRequired(error) || !mounted) return;
    final l = AppLocalizations.of(context);
    final apiError = _extractApiError(error);
    final budgetExceeded = apiError?.code == 'SERVICE_BUDGET_EXCEEDED';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          budgetExceeded
              ? apiError!.localizedMessage(l)
              : l.viewerAudioPlayFailed,
        ),
        duration: Duration(seconds: budgetExceeded ? 8 : 4),
        backgroundColor: AppColors.error,
      ),
    );
  }

  String? _defaultNarrationUrl(
    BookResult book,
    PageResult page,
    String language,
  ) {
    final localized = switch (language) {
      'ko' => page.audioUrlKo,
      'en' => page.audioUrlEn,
      _ => null,
    };
    return localized ??
        (language == (book.language ?? 'ko') ? page.audioUrl : null);
  }

  String _narrationExtension(String? url, String? provider) {
    final path = Uri.tryParse(url ?? '')?.path.toLowerCase() ?? '';
    if (path.endsWith('.wav')) return 'wav';
    if (path.endsWith('.mp3')) return 'mp3';
    return provider == 'openai_realtime' ? 'wav' : 'mp3';
  }

  void _closeNarrationCaches() {
    for (final cache in _narrationCaches.values) {
      unawaited(cache.dispose());
    }
    _narrationCaches.clear();
    _narrationCacheStore = null;
  }

  void _stopUnavailableNarration() {
    _closeNarrationCaches();
    // Provider invalidation can run while the viewer is being built.
    unawaited(
      Future<void>.microtask(() async {
        if (mounted) await _pageAudio.stop();
      }),
    );
  }

  BookScopedCacheManager _narrationCache(
    BookMediaStore store,
    String extension, {
    required bool lookahead,
  }) {
    if (!identical(store, _narrationCacheStore)) {
      _closeNarrationCaches();
      _narrationCacheStore = store;
    }
    // A stalled lookahead must never hold the foreground request after its
    // short handoff grace period. Each lane reuses its own HTTP connections.
    return _narrationCaches.putIfAbsent(
      (extension: extension, lookahead: lookahead),
      () => BookScopedCacheManager(
        store: store,
        bookId: widget.bookId,
        fileExtension: extension,
        reuseConnections: true,
        connectionIdleTimeout: const Duration(minutes: 1),
      ),
    );
  }

  Future<void> _prefetchNextNarration() async {
    final book = _activeBook;
    final page = _currentPage;
    if (book == null ||
        page == 0 ||
        page >= book.pages.length ||
        !(_continuousNarration || _sleepModeEnabled) ||
        _activeNarrationPrefetch != null) {
      return;
    }
    final caps = ref.read(capabilitiesProvider).valueOrNull;
    final canLookup = caps?['narration_cached_lookup_supported'] == true;
    final language = _selectedLanguage;
    final voice = narrationVoiceOrDefault(
      _audioPreferences.getString(narrationVoicePreferenceKey),
    );
    final style = narrationStyleOrDefault(
      _audioPreferences.getString(narrationStylePreferenceKey),
    );
    final provider = narrationAudioProvider(caps);
    final next = book.pages[page];
    final defaultUrl = voice == 'default' && style == 'legacy'
        ? _defaultNarrationUrl(book, next, language)
        : null;
    final embeddedUrl =
        defaultUrl != null &&
            defaultUrl.isNotEmpty &&
            !mediaUrlNeedsRefresh(defaultUrl)
        ? defaultUrl
        : null;
    if (embeddedUrl == null && !canLookup) return;
    final key = pageAudioCacheKey(
      book.bookId,
      page + 1,
      language,
      next.getText(language),
      voice: voice,
      style: style,
      provider: provider,
    );
    bool sessionIsCurrent() =>
        mounted &&
        identical(ref.read(apiClientProvider), _readingSessionApi) &&
        !ref.read(bookMediaBlockedProvider(widget.bookId));
    bool isCurrent() =>
        sessionIsCurrent() &&
        (_currentPage == page || _currentPage == page + 1) &&
        _selectedLanguage == language &&
        (_continuousNarration || _sleepModeEnabled);
    if (_lastNarrationPrefetch == key || !isCurrent()) return;
    _lastNarrationPrefetch = key;
    final finished = Completer<void>();
    _activeNarrationPrefetch = (key: key, done: finished.future);
    try {
      final media = await ref.read(bookMediaStoreProvider.future);
      bool mediaIsCurrent() =>
          mounted &&
          identical(
            ref.read(bookMediaStoreProvider).valueOrNull?.store,
            media.store,
          );
      if (!isCurrent() || !media.serverVerified || !mediaIsCurrent()) return;
      Future<String?> lookupSavedUrl() =>
          _readingSessionApi.getCachedPageAudioUrl(
            book.bookId,
            page + 1,
            language: language,
            voice: voice,
            style: style,
          );
      await cachedPageAudio(
        key,
        () async {
          final url = embeddedUrl ?? await lookupSavedUrl();
          if (url == null || url.isEmpty) {
            throw StateError('No saved narration');
          }
          return url;
        },
        cache: _narrationCache(
          media.store,
          _narrationExtension(defaultUrl, provider),
          lookahead: true,
        ),
        isCurrent: () => isCurrent() && mediaIsCurrent(),
        shouldRemoveLateFile: () => !sessionIsCurrent() || !mediaIsCurrent(),
        refreshRejectedUrl: (rejectedUrl) async {
          if (!canLookup ||
              (embeddedUrl == null && !hasS3MediaSignature(rejectedUrl))) {
            return null;
          }
          return lookupSavedUrl();
        },
      );
    } catch (_) {
      // Lookahead is optional. The requested page still uses normal playback.
    } finally {
      _activeNarrationPrefetch = null;
      finished.complete();
      if (mounted &&
          _currentPage != page &&
          _isPlaying &&
          _pageAudio.hasLoadedSource) {
        unawaited(_prefetchNextNarration());
      }
    }
  }

  Future<void> _playPageAudio(BookResult book, {bool restart = false}) async {
    if (!mounted ||
        _currentPage == 0 ||
        _pageAudio.loading ||
        ref.read(bookMediaBlockedProvider(widget.bookId))) {
      return;
    }
    final pageIndex = _currentPage;
    final language = _selectedLanguage;
    final voice = narrationVoiceOrDefault(
      _audioPreferences.getString(narrationVoicePreferenceKey),
    );
    final style = narrationStyleOrDefault(
      _audioPreferences.getString(narrationStylePreferenceKey),
    );
    final caps = ref.read(capabilitiesProvider).valueOrNull;
    final provider = narrationAudioProvider(caps);
    if (style != 'legacy' &&
        caps?['narration_style_selection_supported'] != true) {
      await _showAudioError(StateError('Narration style is unavailable'));
      return;
    }
    if (voice != 'default' &&
        caps?['narration_voice_selection_supported'] != true) {
      await _showAudioError(StateError('Narrator selection is unavailable'));
      return;
    }
    final page = book.pages[pageIndex - 1];
    final key = pageAudioCacheKey(
      book.bookId,
      pageIndex,
      language,
      page.getText(language),
      voice: voice,
      style: style,
      provider: provider,
    );
    setState(() {
      _audioProgressPage = pageIndex;
    });
    bool scopeIsCurrent() =>
        mounted &&
        _currentPage == pageIndex &&
        _selectedLanguage == language &&
        identical(ref.read(apiClientProvider), _readingSessionApi) &&
        !ref.read(bookMediaBlockedProvider(widget.bookId));
    if (!scopeIsCurrent()) return;
    await _pageAudio.play(
      key,
      () async {
        final requestIsCurrent = _pageAudio.captureRequestGuard();
        final canLookup = caps?['narration_cached_lookup_supported'] == true;
        final media = await ref.read(bookMediaStoreProvider.future);
        bool mediaIsCurrent() =>
            scopeIsCurrent() &&
            identical(
              ref.read(bookMediaStoreProvider).valueOrNull?.store,
              media.store,
            );
        if (!requestIsCurrent() || !mediaIsCurrent()) {
          throw StateError('Narration request is no longer active');
        }
        final prefetch = _activeNarrationPrefetch;
        if (prefetch != null &&
            prefetch.key == key &&
            (_continuousNarration || _sleepModeEnabled)) {
          // A nearly finished download can satisfy playback without another
          // audio request. A slow lookahead never owns the foreground load.
          await prefetch.done.timeout(
            _narrationPrefetchGrace,
            onTimeout: () {},
          );
        }
        if (!requestIsCurrent() || !mediaIsCurrent()) {
          throw StateError('Narration request is no longer active');
        }
        final usesDefaultAudio = voice == 'default' && style == 'legacy';
        final existingUrl = usesDefaultAudio
            ? _defaultNarrationUrl(book, page, language)
            : null;
        final embeddedUrl =
            existingUrl != null &&
                existingUrl.isNotEmpty &&
                !mediaUrlNeedsRefresh(existingUrl)
            ? existingUrl
            : null;
        Future<String> resolveNarration() => _readingSessionApi.getPageAudioUrl(
          book.bookId,
          pageIndex,
          language: language,
          voice: voice,
          style: style,
        );
        return cachedPageAudio(
          key,
          () async => embeddedUrl ?? await resolveNarration(),
          cache: _narrationCache(
            media.store,
            _narrationExtension(existingUrl, provider),
            lookahead: false,
          ),
          isCurrent: () => requestIsCurrent() && mediaIsCurrent(),
          shouldRemoveLateFile: () => !mediaIsCurrent(),
          refreshRejectedUrl: (rejectedUrl) async {
            if (!hasS3MediaSignature(rejectedUrl)) return null;
            if (canLookup) {
              // A retry renews a recording's URL without asking for synthesis.
              return _readingSessionApi.getCachedPageAudioUrl(
                book.bookId,
                pageIndex,
                language: language,
                voice: voice,
                style: style,
              );
            }
            if (rejectedUrl != embeddedUrl) return null;
            return resolveNarration();
          },
        );
      },
      restart: restart,
      initialPosition: restart
          ? Duration.zero
          : _savedAudioPosition(
              page: pageIndex,
              language: language,
              voice: voice,
              style: style,
              provider: provider,
            ),
      isCurrent: scopeIsCurrent,
    );
  }

  Future<void> _advanceNarration() async {
    final book = _activeBook;
    if (book == null || _narrationAutoAdvancing) return;
    if (_currentPage >= book.pages.length) {
      if (_continuousNarration) setState(() => _continuousNarration = false);
      return;
    }
    await _goToNarrationPage(_currentPage + 1);
  }

  Future<void> _goToNarrationPage(int page) async {
    if (_narrationAutoAdvancing || !_pageController.hasClients) return;
    _narrationAutoAdvancing = true;
    try {
      await _pageController.animateToPage(
        page,
        duration: const Duration(milliseconds: 450),
        curve: Curves.easeInOut,
      );
    } finally {
      _narrationAutoAdvancing = false;
    }
  }

  Future<void> _startContinuousNarration(BookResult book) async {
    if (_narrationAutoAdvancing ||
        _sleepModeEnabled ||
        ref.read(bookMediaBlockedProvider(widget.bookId))) {
      return;
    }
    setState(() => _continuousNarration = true);
    if (_currentPage == 0) {
      await _goToNarrationPage(1);
    } else if (!_isPlaying) {
      await _playPageAudio(book);
    } else {
      unawaited(_prefetchNextNarration());
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
      _continuousNarration = false;
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

    await _pageAudio.stop();
    if (byTimer && wasEnabled && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(AppLocalizations.of(context).viewerSleepModeEnded),
        ),
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

  void _restoreReadingProgressIfNeeded(int totalPages) {
    if (_progressRestored) {
      return;
    }
    _progressRestored = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted ||
          !identical(ref.read(apiClientProvider), _readingSessionApi)) {
        return;
      }
      int savedPage;
      try {
        final progress = await ref.read(
          readingProgressProvider(widget.bookId).future,
        );
        savedPage = await progress.page() ?? 0;
      } catch (_) {
        return;
      }
      if (!mounted ||
          _currentPage != 0 ||
          _continuousNarration ||
          savedPage <= 0 ||
          savedPage >= totalPages) {
        return;
      }
      _currentPage = savedPage;
      _audioProgressPage = savedPage;
      _pageController.jumpToPage(savedPage);
      setState(() {});
    });
  }

  Future<void> _saveReadingProgress(int pageIndex) async {
    if (!mounted ||
        _completionHandled ||
        !identical(ref.read(apiClientProvider), _readingSessionApi)) {
      return;
    }
    try {
      final progress = await ref.read(
        readingProgressProvider(widget.bookId).future,
      );
      // Navigating to the last page still leaves a reading position. Only
      // the explicit completion action clears it.
      if (_completionHandled || _currentPage != pageIndex) return;
      await progress.savePage(pageIndex);
      if (mounted) ref.invalidate(homeReadingProgressProvider(widget.bookId));
    } catch (_) {
      // A missing scope never blocks reading.
    }
  }

  Future<void> _clearReadingProgress() async {
    if (!mounted ||
        !identical(ref.read(apiClientProvider), _readingSessionApi)) {
      return;
    }
    try {
      final progress = await ref.read(
        readingProgressProvider(widget.bookId).future,
      );
      await progress.clearReading();
      if (mounted) ref.invalidate(homeReadingProgressProvider(widget.bookId));
    } catch (_) {
      // A missing scope never blocks reading.
    }
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
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(l.viewerRetellInProgress)));
    try {
      final newBookId = await ref
          .read(apiClientProvider)
          .retellBook(book.bookId, targetAge);
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
    final capabilities = ref.read(capabilitiesProvider).valueOrNull;
    final audioOk = narrationSupported(capabilities);
    final hasBilingualText = book.pages.any(
      (page) =>
          (page.textKo?.isNotEmpty ?? false) &&
          (page.textEn?.isNotEmpty ?? false),
    );
    showModalBottomSheet(
      context: context,
      backgroundColor: AppPalette.of(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      isScrollControlled: true,
      builder: (context) => AdaptiveModalSheet(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              minTileHeight: AppSizing.minTouchTarget,
              leading: const Icon(Icons.close),
              title: Text(l.viewerCloseTooltip),
              onTap: () {
                Navigator.pop(context);
                Navigator.pop(this.context);
              },
            ),
            if (audioOk &&
                !_sleepModeEnabled &&
                !_continuousNarration &&
                _currentPage > 0 &&
                _currentPage < book.pages.length)
              ListTile(
                minTileHeight: AppSizing.minTouchTarget,
                leading: const Icon(Icons.headphones),
                title: Text(l.viewerListenFromHere),
                onTap: () {
                  Navigator.pop(context);
                  unawaited(_startContinuousNarration(book));
                },
              ),
            if (audioOk)
              ListTile(
                minTileHeight: AppSizing.minTouchTarget,
                leading: const Icon(Icons.speed_outlined),
                title: Text(l.viewerNarrationSpeed),
                subtitle: Text(_narrationSpeedLabel(l, _audioPlayer.speed)),
                onTap: () {
                  Navigator.pop(context);
                  unawaited(_pickNarrationSpeed());
                },
              ),
            if (book.titleKo != null || book.titleEn != null)
              ListTile(
                minTileHeight: AppSizing.minTouchTarget,
                leading: const Icon(Icons.swap_horiz),
                title: Text(l.viewerLanguageToggleTooltip),
                subtitle: Text(
                  _selectedLanguage == 'ko'
                      ? l.viewerLanguageKo
                      : l.viewerLanguageEn,
                ),
                onTap: () {
                  Navigator.pop(context);
                  unawaited(_toggleLanguage(book));
                },
              ),
            if (book.learningAssets == null)
              Padding(
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Text(l.viewerLearningUnavailable),
              ),
            const SizedBox(height: AppSpacing.lg),
            ListTile(
              minTileHeight: 64,
              leading: const Icon(Icons.flag_outlined),
              title: Text(l.reportContentTitle),
              onTap: () {
                final pageNumber = _currentPage == 0
                    ? 0
                    : book.pages[_currentPage - 1].pageNumber;
                Navigator.pop(context);
                unawaited(
                  showContentReportSheet(
                    this.context,
                    ref,
                    bookId: book.bookId,
                    pageNumber: pageNumber,
                  ),
                );
              },
            ),
            if (_currentPage > 0 && audioOk)
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
                    () => _followReadingEnabled = !_followReadingEnabled,
                  );
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
                  arguments: {'bookId': book.bookId},
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
            if (_currentPage > 0 && _audioSupportedFrom(capabilities))
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
                      // H3: 발음 평가를 책 언어로(ja/zh/es 한국어 오전사 제거).
                      'language': _selectedLanguage,
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
            if (audioOk || _sleepModeEnabled)
              ListTile(
                leading: Icon(
                  _sleepModeEnabled ? Icons.bedtime_off : Icons.bedtime,
                ),
                title: Text(
                  _sleepModeEnabled
                      ? l.viewerSleepModeStop
                      : l.viewerSleepModeStart,
                ),
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
      backgroundColor: AppPalette.of(context).surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => SafeArea(
          top: false,
          child: _LearningModeSheet(
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
      await ref
          .read(apiClientProvider)
          .recordQuizAnswer(
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
      await ref
          .read(apiClientProvider)
          .recordQuizAnswer(
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
      backgroundColor: AppPalette.of(context).surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.4,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) => SafeArea(
          top: false,
          child: _ParentGuideSheet(
            parentGuide: book.learningAssets!.parentGuide,
            scrollController: scrollController,
          ),
        ),
      ),
    );
  }

  void _showRegenerateOptions(BookResult book) {
    final l = AppLocalizations.of(context);
    if (_regenerationInFlight) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerRegenerating)));
      return;
    }
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
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerRegenerateNotSupported)));
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

  /// M12: 서버는 mode=text/both에 feedback을 필수로 요구한다(없으면 422). 어떻게 바꿀지
  /// 입력받아 전달한다 — 입력 UI가 없어 '텍스트만/모두' 메뉴가 100% 실패하던 문제 수정.
  Future<String?> _askRegenerateFeedback() async {
    final l = AppLocalizations.of(context);
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.viewerRegenerateFeedbackTitle),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 200,
          decoration: InputDecoration(hintText: l.viewerRegenerateFeedbackHint),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.viewerCancel),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: Text(l.viewerRegenerateConfirm),
          ),
        ],
      ),
    );
    controller.dispose();
    return result;
  }

  Future<void> _regeneratePage(
    BookResult book,
    int pageNumber,
    String target,
  ) async {
    if (_regenerationInFlight) return;
    final l = AppLocalizations.of(context);
    if (book.jobId == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerRegenerateNotSupported)));
      return;
    }

    _regenerationInFlight = true;
    try {
      String? feedback;
      if (target == 'text' || target == 'both') {
        feedback = await _askRegenerateFeedback();
        if (feedback == null) {
          return; // 사용자가 취소
        }
        if (feedback.isEmpty) {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(l.viewerRegenerateFeedbackRequired)),
          );
          return;
        }
      }
      if (!mounted) return;

      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerRegenerating)));

      final apiClient = ref.read(apiClientProvider);
      final regenJobId = await apiClient.regeneratePage(
        book.jobId!,
        pageNumber,
        regenerateTarget: target,
        feedback: feedback,
      );
      if (!mounted) return;

      // 응답은 '큐에 넣었다'까지다. 여기서 바로 새로고침하면 워커가 끝나기 전의 옛 그림을
      // 다시 받아 캐시에 고정되고, 이후 재조회가 없어 새 그림이 영영 보이지 않았다.
      // 인페인트와 같이 잡 완료를 기다린 뒤에만 성공으로 처리한다.
      final outcome = await _waitForPageJob(apiClient, regenJobId);
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      switch (outcome) {
        case _PageJobOutcome.completed:
          ref.invalidate(bookDetailProvider(widget.bookId));
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(l10n.viewerRegenerateCompleted)),
          );
          break;
        case _PageJobOutcome.failed:
        case _PageJobOutcome.qualityFailed:
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                outcome == _PageJobOutcome.qualityFailed
                    ? l10n.viewerImageQualityFailed
                    : l10n.viewerRegenerateFailed,
              ),
              backgroundColor: AppColors.error,
            ),
          );
          break;
        case _PageJobOutcome.timeout:
          // 아직 처리 중일 수 있다. 실패로 단정하지 않고 기다림을 안내한다.
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(l10n.inpaintApplyingRefreshLater)),
          );
          break;
      }
    } catch (e) {
      if (mounted) {
        final qualityFailed =
            _extractApiError(e)?.code == 'IMAGE_QUALITY_FAILED';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              qualityFailed
                  ? AppLocalizations.of(context).viewerImageQualityFailed
                  : AppLocalizations.of(context).viewerRegenerateFailed,
            ),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      _regenerationInFlight = false;
    }
  }

  /// 페이지 재생성 잡의 완료를 기다린다(인페인트의 `_waitForJob`과 같은 규약).
  /// 느린 성공을 실패로 오분류하지 않도록 이미지 타임아웃 스펙(90초×재시도)에 맞춘 예산.
  Future<_PageJobOutcome> _waitForPageJob(ApiClient api, String jobId) async {
    final startedAt = DateTime.now();
    const budget = Duration(minutes: 3);
    while (mounted && DateTime.now().difference(startedAt) < budget) {
      await Future.delayed(const Duration(seconds: 1));
      if (!mounted) break;
      try {
        final js = await api.getBookStatus(jobId);
        if (js.isComplete) return _PageJobOutcome.completed;
        if (js.isFailed) {
          return js.errorCode == 'IMAGE_QUALITY_FAILED'
              ? _PageJobOutcome.qualityFailed
              : _PageJobOutcome.failed;
        }
      } catch (_) {
        // 일시적 오류는 무시하고 재시도
      }
    }
    return _PageJobOutcome.timeout;
  }

  Future<void> _downloadPdf(BookResult book) async {
    if (!await ensureAgeGate(context, ref) || !mounted) return;
    final l = AppLocalizations.of(context);
    try {
      // 로딩 표시
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerPdfGenerating)));

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
          SnackBar(
            content: Text(
              AppLocalizations.of(context).viewerPdfSaved(fileName),
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).hideCurrentSnackBar();
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
      backgroundColor: AppPalette.of(context).surface,
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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(l.viewerCopyDone)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerShareLinkFailed),
          ),
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
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerShareLinkFailed),
          ),
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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(l.viewerShareRevokeDone)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).viewerShareRevokeFailed),
          ),
        );
      }
    }
  }

  Future<void> _shareText(BookResult book) async {
    if (!await ensureAgeGate(context, ref) || !mounted) return;
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
      coverImageUrl: "${shareUrl.replaceFirst(RegExp(r'/+$'), '')}/img/cover",
      buttonTitle: l.shareKakaoCardTitle,
      fallbackDescription: l.shareKakaoCardDescription,
      description: l.viewerKakaoDescription,
    );
    if (result.shared) {
      return;
    }
    if (mounted && result.reason != null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(result.reason!)));
    }

    // 폴백(카카오톡 미설치 등): 앱 딥링크 + 공개 토큰 URL.
    final deepLink = 'ai-story-book://books/${book.bookId}';
    final shareText = l
        .viewerKakaoShareText(book.title, deepLink, shareUrl)
        .trim();
    await Share.share(
      shareText,
      subject: l.viewerKakaoShareSubject(book.title),
      sharePositionOrigin: shareOrigin,
    );
  }

  Future<void> _printPdf(BookResult book) async {
    if (!await ensureAgeGate(context, ref) || !mounted) return;
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
    if (!await ensureAgeGate(context, ref) || !mounted) return;
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
    if (!await ensureAgeGate(context, ref) || !mounted) return;
    final l = AppLocalizations.of(context);
    try {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.viewerPdfGenerating)));

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
              color: AppPalette.of(context).primaryLight,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(icon, color: AppPalette.of(context).primary, size: 28),
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
  final String bookId;
  final String title;
  final String imageUrl;
  final VoidCallback onTap;
  final String controlsHint;
  final VoidCallback onSignedUrlRejected;
  final Future<void> Function() onRetrySignedUrl;

  const _CoverPage({
    required this.bookId,
    required this.title,
    required this.imageUrl,
    required this.onTap,
    required this.controlsHint,
    required this.onSignedUrlRejected,
    required this.onRetrySignedUrl,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      excludeFromSemantics: true,
      child: SafeArea(
        bottom: false,
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 540),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(
                      height: (constraints.maxHeight * 0.68).clamp(
                        150.0,
                        560.0,
                      ),
                      child: Semantics(
                        container: true,
                        label: l.viewerCoverImageSemantics(title),
                        hint: controlsHint,
                        image: true,
                        button: true,
                        onTap: onTap,
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: const Color(0xFF193D40),
                            borderRadius: BorderRadius.circular(AppRadius.lg),
                            border: Border.all(color: const Color(0xFF40635D)),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(AppSpacing.sm),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(AppRadius.md),
                              child: imageUrl.trim().isEmpty
                                  ? const Icon(
                                      Icons.auto_stories_outlined,
                                      color: StorybookColors.moonlight,
                                      size: 64,
                                    )
                                  : ScopedBookImage(
                                      bookId: bookId,
                                      imageUrl: imageUrl,
                                      onSignedUrlRejected: onSignedUrlRejected,
                                      onRetrySignedUrl: onRetrySignedUrl,
                                      fit: BoxFit.contain,
                                      placeholder: const Center(
                                        child: CircularProgressIndicator(
                                          color: StorybookColors.moonlight,
                                        ),
                                      ),
                                      error: const Icon(
                                        Icons.broken_image_outlined,
                                        color: StorybookColors.onInk,
                                        size: 48,
                                      ),
                                    ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      title,
                      style: AppTextStyles.heading1.copyWith(
                        fontSize: 32,
                        height: 1.18,
                        color: StorybookColors.onInk,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 본문 페이지
class _ContentPage extends StatelessWidget {
  final String bookId;
  final VoidCallback? onComplete;
  final bool showInlineLearning;
  final bool sleepMode;
  final VoidCallback onIllustrationTap;
  final String controlsHint;
  final VoidCallback onSignedUrlRejected;
  final Future<void> Function() onRetrySignedUrl;
  final VoidCallback? onNarrate;
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
    required this.bookId,
    this.onComplete,
    required this.showInlineLearning,
    required this.sleepMode,
    required this.onIllustrationTap,
    required this.controlsHint,
    required this.onSignedUrlRejected,
    required this.onRetrySignedUrl,
    this.onNarrate,
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
    final colors = StorybookColors(sleepMode || AppPalette.of(context).isDark);

    return ColoredBox(
      color: colors.paper,
      child: Column(
        children: [
          SizedBox(height: MediaQuery.paddingOf(context).top),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                return _ReaderPageScroll(
                  key: ValueKey(pageNumber),
                  pageNumber: pageNumber,
                  thumbColor: colors.muted.withValues(alpha: 0.6),
                  child: Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
                        child: Center(
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 620),
                            child: SizedBox(
                              height:
                                  (constraints.maxHeight *
                                          (onComplete == null ? 0.58 : 0.43))
                                      .clamp(150.0, 540.0),
                              width: double.infinity,
                              child: GestureDetector(
                                onTap: onIllustrationTap,
                                excludeFromSemantics: true,
                                child: Semantics(
                                  container: true,
                                  label: l.viewerPageImageSemantics(pageNumber),
                                  hint: controlsHint,
                                  image: true,
                                  button: true,
                                  onTap: onIllustrationTap,
                                  child: DecoratedBox(
                                    decoration: BoxDecoration(
                                      color: colors.sheet,
                                      border: Border.all(color: colors.rule),
                                      borderRadius: BorderRadius.circular(
                                        AppRadius.lg,
                                      ),
                                    ),
                                    child: Padding(
                                      padding: const EdgeInsets.all(
                                        AppSpacing.sm,
                                      ),
                                      child: ClipRRect(
                                        borderRadius: BorderRadius.circular(
                                          AppRadius.md,
                                        ),
                                        child: imageUrl.trim().isEmpty
                                            ? Icon(
                                                Icons.image_outlined,
                                                size: 48,
                                                color: colors.muted,
                                              )
                                            : ScopedBookImage(
                                                bookId: bookId,
                                                imageUrl: imageUrl,
                                                onSignedUrlRejected:
                                                    onSignedUrlRejected,
                                                onRetrySignedUrl:
                                                    onRetrySignedUrl,
                                                fit: BoxFit.contain,
                                                width: double.infinity,
                                                placeholder: Center(
                                                  child:
                                                      CircularProgressIndicator(
                                                        color: colors.accent,
                                                      ),
                                                ),
                                                error: Icon(
                                                  Icons.broken_image_outlined,
                                                  size: 48,
                                                  color: colors.muted,
                                                ),
                                              ),
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 580),
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(26, 22, 26, 28),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              GestureDetector(
                                behavior: HitTestBehavior.opaque,
                                onTap: onNarrate,
                                child: _HighlightedStoryText(
                                  text: text,
                                  progress: followProgress,
                                  enabled: followReadingEnabled,
                                  style: AppTextStyles.body.copyWith(
                                    fontSize: 20,
                                    height: 1.75,
                                    color: colors.text,
                                  ),
                                  highlightColor: colors.accent,
                                ),
                              ),
                              if (secondaryText != null &&
                                  secondaryText!.trim().isNotEmpty) ...[
                                const SizedBox(height: AppSpacing.lg),
                                Divider(color: colors.rule, height: 1),
                                const SizedBox(height: AppSpacing.lg),
                                _HighlightedStoryText(
                                  text: secondaryText!,
                                  progress: 0,
                                  enabled: false,
                                  style: AppTextStyles.body.copyWith(
                                    fontSize: 17,
                                    height: 1.7,
                                    color: colors.muted,
                                  ),
                                  highlightColor: colors.accent,
                                ),
                              ],
                              if (onComplete != null) ...[
                                const SizedBox(height: AppSpacing.lg),
                                PrimaryButton(
                                  key: const Key('viewer-finish-reading'),
                                  text: l.viewerFinishReading,
                                  backgroundColor: colors.accent,
                                  foregroundColor: colors.onAccent,
                                  onPressed: onComplete,
                                ),
                              ],
                              if (hasLearning && showInlineLearning)
                                TextButton.icon(
                                  onPressed: onShowLearning,
                                  icon: const Icon(Icons.school, size: 18),
                                  label: Text(l.viewerLearn),
                                  style: TextButton.styleFrom(
                                    foregroundColor: colors.accent,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          if (showInlineLearning)
            SizedBox(height: MediaQuery.paddingOf(context).bottom),
        ],
      ),
    );
  }
}

class _ReaderPageScroll extends StatefulWidget {
  const _ReaderPageScroll({
    super.key,
    required this.pageNumber,
    required this.thumbColor,
    required this.child,
  });

  final int pageNumber;
  final Color thumbColor;
  final Widget child;

  @override
  State<_ReaderPageScroll> createState() => _ReaderPageScrollState();
}

class _ReaderPageScrollState extends State<_ReaderPageScroll> {
  final _controller = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RawScrollbar(
      controller: _controller,
      thumbVisibility: true,
      interactive: false,
      thumbColor: widget.thumbColor,
      thickness: 3,
      radius: const Radius.circular(AppSpacing.xs),
      crossAxisMargin: AppSpacing.xs,
      child: SingleChildScrollView(
        key: ValueKey('reader-content-${widget.pageNumber}'),
        controller: _controller,
        primary: false,
        child: widget.child,
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
      return Text(text, style: style, textAlign: TextAlign.start);
    }

    final segments = RegExp(
      r'\s+|\S+',
    ).allMatches(text).map((match) => match.group(0)!).toList(growable: false);
    final words = segments.where((segment) => segment.trim().isNotEmpty).length;
    if (words == 0) {
      return Text(text, style: style, textAlign: TextAlign.start);
    }

    final target = (words * progress.clamp(0.0, 1.0)).round().clamp(0, words);
    var seenWords = 0;

    final spans = segments
        .map((segment) {
          if (segment.trim().isEmpty) {
            return TextSpan(text: segment, style: style);
          }
          seenWords += 1;
          return TextSpan(
            text: segment,
            style: style.copyWith(
              color: seenWords <= target ? highlightColor : style.color,
              fontWeight: seenWords <= target
                  ? FontWeight.w700
                  : style.fontWeight,
            ),
          );
        })
        .toList(growable: false);

    return RichText(
      textScaler: MediaQuery.textScalerOf(context),
      textAlign: TextAlign.start,
      text: TextSpan(
        style: DefaultTextStyle.of(context).style.merge(style),
        children: spans,
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
            color: AppPalette.of(context).divider,
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
          labelPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
          labelStyle: AppTextStyles.bodySmall.copyWith(
            fontWeight: FontWeight.w600,
          ),
          unselectedLabelStyle: AppTextStyles.bodySmall.copyWith(
            fontWeight: FontWeight.w600,
          ),
          labelColor: AppPalette.of(context).primary,
          unselectedLabelColor: AppPalette.of(context).textSecondary,
          indicatorColor: AppPalette.of(context).primary,
          tabs: [
            Tab(icon: const Icon(Icons.abc), text: l.viewerTabWord),
            Tab(
              icon: const Icon(Icons.help_outline),
              text: l.viewerTabQuestion,
            ),
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
                questions: widget.page.comprehensionQuestions ?? [],
              ),
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
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              item.word,
              style: AppTextStyles.heading3.copyWith(
                color: AppPalette.of(context).primary,
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(item.meaning, style: AppTextStyles.body),
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
              l.viewerComprehensionQuestion(
                widget.index,
                widget.question.question,
              ),
              style: AppTextStyles.body.copyWith(fontWeight: FontWeight.bold),
            ),
            if (widget.question.answer != null) ...[
              const SizedBox(height: AppSpacing.sm),
              if (_showAnswer)
                Text(
                  l.viewerComprehensionAnswer(widget.question.answer!),
                  style: AppTextStyles.body.copyWith(
                    color: AppPalette.of(context).primary,
                  ),
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
                backgroundColor = AppPalette.of(context).primaryLight;
              }

              return Semantics(
                button: true,
                selected: isSelected,
                enabled: !_showResult,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                    onTap: _showResult
                        ? null
                        : () => setState(() => _selectedIndex = optionIndex),
                    child: Container(
                      constraints: const BoxConstraints(
                        minHeight: AppSizing.minTouchTarget,
                      ),
                      alignment: Alignment.centerLeft,
                      width: double.infinity,
                      padding: const EdgeInsets.all(AppSpacing.md),
                      decoration: BoxDecoration(
                        color: backgroundColor,
                        border: Border.all(
                          color: isSelected
                              ? AppPalette.of(context).primary
                              : AppPalette.of(context).divider,
                        ),
                        borderRadius: BorderRadius.circular(AppRadius.sm),
                      ),
                      child: Text(option),
                    ),
                  ),
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
                  Expanded(
                    child: Text(
                      isCorrect ? l.viewerQuizCorrect : l.viewerQuizIncorrect,
                      style: TextStyle(
                        color: isCorrect ? AppColors.success : AppColors.error,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
              if (widget.quiz.explanation != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  widget.quiz.explanation!,
                  style: AppTextStyles.caption.copyWith(
                    color: AppPalette.of(context).textSecondary,
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
            color: AppPalette.of(context).divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // 제목
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.family_restroom, color: AppPalette.of(context).primary),
            const SizedBox(width: AppSpacing.sm),
            Flexible(
              child: Text(
                l.viewerParentGuideTitle,
                style: AppTextStyles.heading2,
              ),
            ),
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
            Icon(icon, color: AppPalette.of(context).primary, size: 20),
            const SizedBox(width: AppSpacing.sm),
            Expanded(child: Text(title, style: AppTextStyles.heading3)),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        if (content != null) Text(content!, style: AppTextStyles.body),
        if (items != null)
          ...items!.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('• ', style: TextStyle(fontSize: 16)),
                  Expanded(child: Text(item, style: AppTextStyles.body)),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
