import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';
import '../widgets/storybook_illustration.dart';

/// M29: 실패 잡의 표시 텍스트 조합.
///
/// 안전 차단(SAFETY_INPUT)은 서버가 사용자 언어로 생성된 reasons만 담아 오므로,
/// 클라이언트가 로컬라이즈된 접두어를 붙여 표시한다(한국어 접두어 하드코딩 제거).
/// 그림 품질 실패는 검증되지 않은 서버 상세나 환불 상태를 표시하지 않는다.
/// SAFETY_OUTPUT도 서버가 제공한 안전 사유를 보존한다. 그 외 실패는
/// 서버의 언어 고정 일반 문구 대신 앱의 로컬라이즈된 안내를 사용한다.
String composeJobErrorText(
  AppLocalizations l,
  String? errorCode,
  String? errorMessage,
) {
  // H17: 폴링 타임아웃은 로컬라이즈된 안내로(TimeoutException 원문 미노출).
  if (errorCode == 'TIMEOUT') {
    return l.loadingTimeoutMessage;
  }
  if (errorCode == 'STATUS_UNAVAILABLE') {
    return l.loadingStatusUnavailable;
  }
  if (errorCode == 'AI_PROVIDER_UNAVAILABLE') return l.errorServiceUnavailable;
  if (errorCode == 'IMAGE_QUALITY_FAILED') {
    return l.loadingImageQualityFailed;
  }
  // 서버가 원문을 그대로 내보내는 코드는 안전 코드뿐이다(core/errors.py의
  // CLIENT_SAFE_ERROR_CODES). 그 외 실패는 서버가 한국어 일반 문구 하나로 바꿔 저장하므로,
  // 그대로 렌더하면 en/ja 사용자가 실패 화면에서 한국어를 보게 된다.
  final serverMessage = errorMessage?.trim();
  if (errorCode == 'SAFETY_INPUT') {
    final detail = (serverMessage == null || serverMessage.isEmpty)
        ? l.loadingUnknownError
        : serverMessage;
    return '${l.loadingSafetyBlockedPrefix} $detail';
  }
  if (errorCode == 'SAFETY_OUTPUT' &&
      serverMessage != null &&
      serverMessage.isNotEmpty) {
    return serverMessage;
  }
  return l.loadingGenericFailure;
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

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final jobStatusAsync = ref.watch(jobPollingProvider(widget.jobId));

    return Scaffold(
      backgroundColor: AppPalette.of(context).background,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: (constraints.maxHeight - AppSpacing.lg * 2).clamp(
                  0,
                  double.infinity,
                ),
              ),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 460),
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
                            ref.invalidate(libraryBrowseProvider);
                            Navigator.pushReplacementNamed(
                              context,
                              '/viewer',
                              arguments: status.result!.bookId,
                            );
                          }
                        });
                        return _buildCompletedContent(l);
                      }

                      if (status.isComplete && status.result == null) {
                        return _buildErrorContent(
                          context,
                          JobStatus(
                            jobId: widget.jobId,
                            status: JobState.failed,
                            progress: status.progress,
                            errorCode: 'STATUS_UNAVAILABLE',
                          ),
                        );
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
                          errorCode: isTimeout
                              ? 'TIMEOUT'
                              : 'STATUS_UNAVAILABLE',
                        ),
                      );
                    },
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildProgressContent(AppLocalizations l, JobStatus status) {
    final palette = AppPalette.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          l.loadingTitle,
          style: AppTextStyles.heading1.copyWith(
            color: palette.textPrimary,
            height: 1.25,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        _buildCreationArtwork(l, palette),
        const SizedBox(height: AppSpacing.md),
        DecoratedBox(
          decoration: BoxDecoration(
            color: palette.surface,
            border: Border.all(color: palette.divider),
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Semantics(
                  liveRegion: true,
                  child: Text(
                    _getStepDescription(l, status.currentStep, status.progress),
                    style: AppTextStyles.heading3.copyWith(
                      color: palette.textPrimary,
                    ),
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                ProgressIndicatorBar(
                  progress: status.progress.clamp(0, 100).toInt(),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.lightbulb_outline, size: 20, color: palette.primary),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  l.loadingTip3,
                  style: AppTextStyles.bodySmall.copyWith(
                    color: palette.textSecondary,
                    height: 1.45,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildCreationArtwork(AppLocalizations l, AppPalette palette) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.xl),
      child: AspectRatio(
        aspectRatio: 1.6,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.asset(
              'assets/branding/creation-garden.jpg',
              fit: BoxFit.cover,
              alignment: const Alignment(0, -0.32),
              excludeFromSemantics: true,
              errorBuilder: (_, __, ___) => ColoredBox(
                color: palette.primaryLight,
                child: const Center(child: StorybookIllustration()),
              ),
            ),
            PositionedDirectional(
              start: AppSpacing.md,
              end: AppSpacing.md,
              bottom: AppSpacing.md,
              child: Align(
                alignment: AlignmentDirectional.centerStart,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: palette.surface,
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.sm,
                      vertical: AppSpacing.xs,
                    ),
                    child: Text(
                      l.loadingIllustrationExample,
                      style: AppTextStyles.caption.copyWith(
                        color: palette.textPrimary,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCompletedContent(AppLocalizations l) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.check_circle, size: 80, color: AppColors.success),
          const SizedBox(height: AppSpacing.lg),
          Text(l.loadingCompleted, style: AppTextStyles.heading2),
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
          const Icon(Icons.error_outline, size: 80, color: AppColors.error),
          const SizedBox(height: AppSpacing.lg),
          Text(
            status.errorCode == 'TIMEOUT' ||
                    status.errorCode == 'STATUS_UNAVAILABLE'
                ? l.loadingStatusUnavailableTitle
                : l.loadingErrorTitle,
            style: AppTextStyles.heading2,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            composeJobErrorText(l, status.errorCode, status.errorMessage),
            style: AppTextStyles.bodySmall,
            textAlign: TextAlign.center,
          ),
          if (const {
            'refunded',
            'pending',
            'not_charged',
          }.contains(status.creditRefundStatus)) ...[
            const SizedBox(height: AppSpacing.md),
            Text(
              status.creditRefundStatus == 'refunded'
                  ? l.loadingCreditRefunded
                  : status.creditRefundStatus == 'pending'
                  ? l.loadingCreditRefundPending
                  : l.loadingCreditNotCharged,
              style: AppTextStyles.bodySmall,
              textAlign: TextAlign.center,
            ),
          ],
          const SizedBox(height: AppSpacing.xl),
          // H17: 타임아웃이면 주 액션은 '상태 다시 확인'(현재 잡 재조회) — 신규 생성으로
          // 직행하면 크레딧 재차감·서재 중복이 발생한다. 진짜 서버 실패에서만 신규 생성.
          if (status.errorCode == 'TIMEOUT' ||
              status.errorCode == 'STATUS_UNAVAILABLE') ...[
            PrimaryButton(
              text: l.loadingCheckStatusButton,
              isFullWidth: false,
              onPressed: () => ref.invalidate(jobPollingProvider(widget.jobId)),
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
              style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: () => ref.invalidate(jobPollingProvider(widget.jobId)),
              child: Text(l.loadingCheckStatusButton),
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          TextButton(
            style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
            onPressed: () => Navigator.pushReplacementNamed(context, '/'),
            child: Text(l.loadingBackToHomeButton),
          ),
        ],
      ),
    );
  }

  String _getStepDescription(AppLocalizations l, String? step, int progress) {
    if (step == null) return l.loadingStepPreparing;

    final descriptions = {
      // M32: 백엔드 안정 키 → 로케일 문자열. 백엔드가 한국어 표시 문자열 대신 이 키를
      // 보내므로 `?? step` 폴백이 더 이상 한국어 원문을 노출하지 않는다.
      'queued': l.loadingStepWaiting,
      'preparing': l.loadingStepPreparing,
      'normalize': l.loadingStepNormalize,
      'moderate_input': l.loadingStepModerateInput,
      'generate_story': l.loadingStepGenerateStory,
      'generate_character_sheet': l.loadingStepGenerateCharacterSheet,
      'generate_image_prompts': l.loadingStepGenerateImagePrompts,
      'generate_images': l.loadingStepGenerateImages,
      'verify_illustrations': progress >= 88
          ? l.loadingStepRecheckIllustrations
          : l.loadingStepVerifyIllustrations,
      'repair_illustrations': l.loadingStepRepairIllustrations,
      'moderate_output': l.loadingStepModerateOutput,
      'learning_assets': l.loadingStepLearningAssets,
      'package': l.loadingStepPackage,
      'done': l.loadingCompleted,
    };

    // Unknown backend stages are implementation details, not reading guidance.
    return descriptions[step] ?? l.loadingStepPreparing;
  }
}
