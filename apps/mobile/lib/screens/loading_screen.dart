import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

/// M29: 실패 잡의 표시 텍스트 조합.
///
/// 안전 차단(SAFETY_INPUT)은 서버가 사용자 언어로 생성된 reasons만 담아 오므로,
/// 클라이언트가 로컬라이즈된 접두어를 붙여 표시한다(한국어 접두어 하드코딩 제거).
/// 그 외 에러 코드는 서버 메시지를 원문 그대로 사용한다.
String composeJobErrorText(
  AppLocalizations l,
  String? errorCode,
  String? errorMessage,
) {
  // H17: 폴링 타임아웃은 로컬라이즈된 안내로(TimeoutException 원문 미노출).
  if (errorCode == 'TIMEOUT') {
    return l.loadingTimeoutMessage;
  }
  final message = errorMessage ?? l.loadingUnknownError;
  if (errorCode == 'SAFETY_INPUT') {
    return '${l.loadingSafetyBlockedPrefix} $message';
  }
  return message;
}

/// 로딩 화면 (책 생성 진행 상황)
class LoadingScreen extends ConsumerStatefulWidget {
  final String jobId;

  const LoadingScreen({super.key, required this.jobId});

  @override
  ConsumerState<LoadingScreen> createState() => _LoadingScreenState();
}

class _LoadingScreenState extends ConsumerState<LoadingScreen> {
  bool _hasNavigated = false; // Prevent double navigation
  late final int _selectedTipIndex;

  @override
  void initState() {
    super.initState();
    _selectedTipIndex = _pickTipIndex();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final jobStatusAsync = ref.watch(jobPollingProvider(widget.jobId));

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: jobStatusAsync.when(
            data: (status) {
              // 완료 시 뷰어로 이동 (guard against double navigation)
              if (status.isComplete &&
                  status.result != null &&
                  !_hasNavigated) {
                _hasNavigated = true;
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (mounted) {
                    ref.invalidate(libraryProvider);
                    Navigator.pushReplacementNamed(
                      context,
                      '/viewer',
                      arguments: status.result!.bookId,
                    );
                  }
                });
                return _buildCompletedContent(l);
              }

              // 실패 시 에러 표시
              if (status.isFailed) {
                return _buildErrorContent(context, status);
              }

              // 진행 중
              return _buildProgressContent(l, status);
            },
            loading: () => _buildProgressContent(
              l,
              JobStatus(
                jobId: widget.jobId,
                status: JobState.queued,
                progress: 0,
                currentStep: l.loadingStepWaiting,
              ),
            ),
            error: (error, _) {
              // H17: 폴링 타임아웃은 서버 실패와 구분한다. 원문(TimeoutException…
              // 한국어) 노출 대신 로컬라이즈 문구로, 주 액션은 신규 생성이 아니라
              // 현재 잡 재조회로(크레딧 재차감·서재 중복 방지).
              final isTimeout = error is TimeoutException;
              return _buildErrorContent(
                context,
                JobStatus(
                  jobId: widget.jobId,
                  status: JobState.failed,
                  progress: 0,
                  errorCode: isTimeout ? 'TIMEOUT' : null,
                  errorMessage: isTimeout ? null : error.toString(),
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _buildProgressContent(AppLocalizations l, JobStatus status) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        // 애니메이션 아이콘
        _AnimatedBookIcon(),

        const SizedBox(height: AppSpacing.xl),

        // 제목
        Text(
          l.loadingTitle,
          style: AppTextStyles.heading2,
          textAlign: TextAlign.center,
        ),

        const SizedBox(height: AppSpacing.sm),

        Text(
          _getStepDescription(l, status.currentStep),
          style: AppTextStyles.bodySmall,
          textAlign: TextAlign.center,
        ),

        const SizedBox(height: AppSpacing.xl),

        // 진행률
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: ProgressIndicatorBar(
            progress: status.progress,
            currentStep: status.currentStep,
          ),
        ),

        const SizedBox(height: AppSpacing.xxl),

        // 팁
        Container(
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.primaryLight,
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          child: Row(
            children: [
              const Icon(Icons.lightbulb_outline, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  _selectedTip(l),
                  style: AppTextStyles.bodySmall.copyWith(
                    color: AppColors.primary,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildCompletedContent(AppLocalizations l) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(
            Icons.check_circle,
            size: 80,
            color: AppColors.success,
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            l.loadingCompleted,
            style: AppTextStyles.heading2,
          ),
        ],
      ),
    );
  }

  Widget _buildErrorContent(BuildContext context, JobStatus status) {
    final l = AppLocalizations.of(context);
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(
            Icons.error_outline,
            size: 80,
            color: AppColors.error,
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            l.loadingErrorTitle,
            style: AppTextStyles.heading2,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            composeJobErrorText(l, status.errorCode, status.errorMessage),
            style: AppTextStyles.bodySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.xl),
          // H17: 타임아웃이면 주 액션은 '상태 다시 확인'(현재 잡 재조회) — 신규 생성으로
          // 직행하면 크레딧 재차감·서재 중복이 발생한다. 진짜 서버 실패에서만 신규 생성.
          if (status.errorCode == 'TIMEOUT') ...[
            PrimaryButton(
              text: l.loadingCheckStatusButton,
              isFullWidth: false,
              onPressed: () => ref.invalidate(jobPollingProvider(widget.jobId)),
            ),
            const SizedBox(height: AppSpacing.sm),
            TextButton(
              onPressed: () =>
                  Navigator.pushReplacementNamed(context, '/create'),
              child: Text(l.loadingRetryButton),
            ),
          ] else ...[
            PrimaryButton(
              text: l.loadingRetryButton,
              isFullWidth: false,
              onPressed: () {
                Navigator.pushReplacementNamed(context, '/create');
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            TextButton(
              onPressed: () => ref.invalidate(jobPollingProvider(widget.jobId)),
              child: Text(l.loadingCheckStatusButton),
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          TextButton(
            onPressed: () => Navigator.pushReplacementNamed(context, '/'),
            child: Text(l.loadingBackToHomeButton),
          ),
        ],
      ),
    );
  }

  String _getStepDescription(AppLocalizations l, String? step) {
    if (step == null) return l.loadingStepPreparing;

    final descriptions = {
      'normalize': l.loadingStepNormalize,
      'moderate_input': l.loadingStepModerateInput,
      'generate_story': l.loadingStepGenerateStory,
      'generate_character_sheet': l.loadingStepGenerateCharacterSheet,
      'generate_image_prompts': l.loadingStepGenerateImagePrompts,
      'generate_images': l.loadingStepGenerateImages,
      'moderate_output': l.loadingStepModerateOutput,
      'package': l.loadingStepPackage,
    };

    return descriptions[step] ?? step;
  }

  List<String> _tips(AppLocalizations l) {
    return [
      l.loadingTip1,
      l.loadingTip2,
      l.loadingTip3,
      l.loadingTip4,
      l.loadingTip5,
    ];
  }

  String _selectedTip(AppLocalizations l) {
    final tips = _tips(l);
    return tips[_selectedTipIndex % tips.length];
  }

  int _pickTipIndex() {
    const tipCount = 5;
    return DateTime.now().millisecond % tipCount;
  }
}

/// 애니메이션 책 아이콘
class _AnimatedBookIcon extends StatefulWidget {
  @override
  State<_AnimatedBookIcon> createState() => _AnimatedBookIconState();
}

class _AnimatedBookIconState extends State<_AnimatedBookIcon>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(seconds: 2),
      vsync: this,
    )..repeat(reverse: true);

    _animation = Tween<double>(begin: 0.9, end: 1.1).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Transform.scale(
          scale: _animation.value,
          child: child,
        );
      },
      child: Container(
        width: 120,
        height: 120,
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
              blurRadius: 30,
              offset: Offset(0, 10),
            ),
          ],
        ),
        child: const Icon(
          Icons.auto_stories,
          size: 60,
          color: Colors.white,
        ),
      ),
    );
  }
}
