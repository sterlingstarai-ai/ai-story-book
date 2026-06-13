import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

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
            error: (error, _) => _buildErrorContent(
              context,
              JobStatus(
                jobId: widget.jobId,
                status: JobState.failed,
                progress: 0,
                errorMessage: error.toString(),
              ),
            ),
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
            status.errorMessage ?? l.loadingUnknownError,
            style: AppTextStyles.bodySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.xl),
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