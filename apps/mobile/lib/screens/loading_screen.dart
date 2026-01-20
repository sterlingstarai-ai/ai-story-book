import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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
  bool _hasNavigated = false;  // Prevent double navigation

  @override
  Widget build(BuildContext context) {
    final jobStatusAsync = ref.watch(jobPollingProvider(widget.jobId));

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: jobStatusAsync.when(
            data: (status) {
              // 완료 시 뷰어로 이동 (guard against double navigation)
              if (status.isComplete && status.result != null && !_hasNavigated) {
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
                return _buildCompletedContent();
              }

              // 실패 시 에러 표시
              if (status.isFailed) {
                return _buildErrorContent(context, status);
              }

              // 진행 중
              return _buildProgressContent(status);
            },
            loading: () => _buildProgressContent(
              JobStatus(
                jobId: widget.jobId,
                status: JobState.queued,
                progress: 0,
                currentStep: '대기 중...',
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

  Widget _buildProgressContent(JobStatus status) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        // 애니메이션 아이콘
        _AnimatedBookIcon(),

        const SizedBox(height: AppSpacing.xl),

        // 제목
        const Text(
          '동화책을 만들고 있어요',
          style: AppTextStyles.heading2,
          textAlign: TextAlign.center,
        ),

        const SizedBox(height: AppSpacing.sm),

        Text(
          _getStepDescription(status.currentStep),
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
                  _getRandomTip(),
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

  Widget _buildCompletedContent() {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.check_circle,
            size: 80,
            color: AppColors.success,
          ),
          SizedBox(height: AppSpacing.lg),
          Text(
            '완성되었어요!',
            style: AppTextStyles.heading2,
          ),
        ],
      ),
    );
  }

  Widget _buildErrorContent(BuildContext context, JobStatus status) {
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
          const Text(
            '문제가 발생했어요',
            style: AppTextStyles.heading2,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            status.errorMessage ?? '알 수 없는 오류',
            style: AppTextStyles.bodySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.xl),
          PrimaryButton(
            text: '다시 시도',
            isFullWidth: false,
            onPressed: () {
              Navigator.pushReplacementNamed(context, '/create');
            },
          ),
          const SizedBox(height: AppSpacing.md),
          TextButton(
            onPressed: () => Navigator.pushReplacementNamed(context, '/'),
            child: const Text('홈으로 돌아가기'),
          ),
        ],
      ),
    );
  }

  String _getStepDescription(String? step) {
    if (step == null) return '준비 중...';

    final descriptions = {
      'normalize': '입력을 분석하고 있어요',
      'moderate_input': '안전성을 검사하고 있어요',
      'generate_story': '이야기를 만들고 있어요',
      'generate_character_sheet': '캐릭터를 디자인하고 있어요',
      'generate_image_prompts': '그림을 준비하고 있어요',
      'generate_images': '그림을 그리고 있어요',
      'moderate_output': '최종 검사 중이에요',
      'package': '마무리하고 있어요',
    };

    return descriptions[step] ?? step;
  }

  String _getRandomTip() {
    final tips = [
      '아이에게 맞는 단어와 문장으로 이야기가 만들어져요',
      '캐릭터가 일관되게 그려지도록 AI가 신경 쓰고 있어요',
      '완성된 책은 서재에서 언제든지 다시 볼 수 있어요',
      '마음에 들지 않는 페이지는 나중에 다시 생성할 수 있어요',
      '같은 캐릭터로 시리즈 동화를 만들 수도 있어요',
    ];
    return tips[DateTime.now().second % tips.length];
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
          gradient: LinearGradient(
            colors: [AppColors.primary, AppColors.secondary],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(AppRadius.xl),
          boxShadow: [
            BoxShadow(
              color: AppColors.primaryStrong,
              blurRadius: 30,
              offset: const Offset(0, 10),
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
