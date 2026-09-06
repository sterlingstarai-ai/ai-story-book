import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:shimmer/shimmer.dart';
import '../utils/constants.dart';

/// 기본 버튼
class PrimaryButton extends StatelessWidget {
  final String text;
  final VoidCallback? onPressed;
  final bool isLoading;
  final bool isFullWidth;

  const PrimaryButton({
    super.key,
    required this.text,
    this.onPressed,
    this.isLoading = false,
    this.isFullWidth = true,
  });

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(
          minHeight: 64, minWidth: isFullWidth ? double.infinity : 0),
      child: ElevatedButton(
        onPressed: isLoading ? null : onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: const Color(0xFF4F46E5),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          foregroundColor: Colors.white,
          disabledBackgroundColor: AppColors.primaryHalf,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
        child: isLoading
            ? const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : Text(text,
                style: AppTextStyles.button, textAlign: TextAlign.center),
      ),
    );
  }
}

/// 보조 버튼
class SecondaryButton extends StatelessWidget {
  final String text;
  final VoidCallback? onPressed;

  const SecondaryButton({
    super.key,
    required this.text,
    this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints:
          const BoxConstraints(minHeight: 64, minWidth: double.infinity),
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: AppPalette.of(context).primary,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          side: BorderSide(color: AppPalette.of(context).primary),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
        child: Text(text,
            style: AppTextStyles.button, textAlign: TextAlign.center),
      ),
    );
  }
}

/// 책 카드
class BookCard extends StatelessWidget {
  final String title;
  final String imageUrl;
  final String? subtitle;
  final VoidCallback? onTap;

  const BookCard({
    super.key,
    required this.title,
    required this.imageUrl,
    this.subtitle,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: onTap != null,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: AppPalette.of(context).surface,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            boxShadow: const [
              BoxShadow(
                color: AppColors.blackOverlayShadow,
                blurRadius: 10,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Flexible(
                child: ClipRRect(
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(AppRadius.lg),
                  ),
                  child: imageUrl.trim().isEmpty
                      ? Container(
                          width: double.infinity,
                          color: AppPalette.of(context).primaryLight,
                          child: Icon(Icons.auto_stories_outlined,
                              size: 48, color: AppPalette.of(context).primary))
                      : CachedNetworkImage(
                          imageUrl: imageUrl,
                          fit: BoxFit.cover,
                          width: double.infinity,
                          placeholder: (context, url) => Shimmer.fromColors(
                            baseColor: Colors.grey[300]!,
                            highlightColor: Colors.grey[100]!,
                            child: Container(color: Colors.white),
                          ),
                          errorWidget: (context, url, error) => Container(
                            color: AppPalette.of(context).divider,
                            child: const Icon(Icons.broken_image, size: 48),
                          ),
                        ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(AppSpacing.sm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      style: AppTextStyles.body
                          .copyWith(fontWeight: FontWeight.w600),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!,
                        style: AppTextStyles.caption.copyWith(
                            color: AppPalette.of(context).textSecondary),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 캐릭터 카드
class CharacterCard extends StatelessWidget {
  final String name;
  final String description;
  final Widget? avatar;
  final String? statusLabel;
  final VoidCallback? onTap;
  final bool isSelected;
  final bool showCheckbox; // 체크박스 표시 (다중 선택용)

  const CharacterCard({
    super.key,
    required this.name,
    required this.description,
    this.avatar,
    this.statusLabel,
    this.onTap,
    this.isSelected = false,
    this.showCheckbox = false,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: isSelected
              ? AppPalette.of(context).primaryLight
              : AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: isSelected
                ? AppPalette.of(context).primary
                : AppPalette.of(context).divider,
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (showCheckbox) ...[
                  Icon(
                    isSelected
                        ? Icons.check_box
                        : Icons.check_box_outline_blank,
                    color: isSelected
                        ? AppPalette.of(context).primary
                        : AppPalette.of(context).textHint,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                ],
                avatar ??
                    CircleAvatar(
                      backgroundColor: AppColors.secondaryLight,
                      child: Text(
                        name.isNotEmpty ? name[0] : '?',
                        style: const TextStyle(
                          color: AppColors.secondary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    name,
                    style: AppTextStyles.heading3,
                  ),
                ),
                if (isSelected && !showCheckbox)
                  const Icon(Icons.check_circle, color: AppColors.primary),
              ],
            ),
            if (statusLabel != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(statusLabel!,
                  style: AppTextStyles.caption
                      .copyWith(color: AppPalette.of(context).primary)),
            ],
            const SizedBox(height: AppSpacing.sm),
            Text(
              description,
              style: AppTextStyles.bodySmall,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}

/// 로딩 오버레이
class LoadingOverlay extends StatelessWidget {
  final String? message;

  const LoadingOverlay({super.key, this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.blackOverlay,
      child: Center(
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.lg),
          decoration: BoxDecoration(
            color: AppPalette.of(context).surface,
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(
                valueColor: AlwaysStoppedAnimation<Color>(AppColors.primary),
              ),
              if (message != null) ...[
                const SizedBox(height: AppSpacing.md),
                Text(message!, style: AppTextStyles.body),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// 빈 상태 표시
class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final String? buttonText;
  final VoidCallback? onButtonPressed;

  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.buttonText,
    this.onButtonPressed,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      return SingleChildScrollView(
        primary: false,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            minHeight: constraints.hasBoundedHeight ? constraints.maxHeight : 0,
          ),
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, size: 64, color: AppPalette.of(context).textHint),
                  const SizedBox(height: AppSpacing.md),
                  Text(title,
                      style: AppTextStyles.heading3,
                      textAlign: TextAlign.center),
                  if (subtitle != null) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Text(subtitle!,
                        style: AppTextStyles.bodySmall,
                        textAlign: TextAlign.center),
                  ],
                  if (buttonText != null && onButtonPressed != null) ...[
                    const SizedBox(height: AppSpacing.lg),
                    PrimaryButton(
                      text: buttonText!,
                      onPressed: onButtonPressed,
                      isFullWidth: false,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      );
    });
  }
}

/// 진행률 표시기
class ProgressIndicatorBar extends StatelessWidget {
  final int progress;
  final String? currentStep;

  const ProgressIndicatorBar({
    super.key,
    required this.progress,
    this.currentStep,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            if (currentStep != null)
              Expanded(
                  child: Text(currentStep!, style: AppTextStyles.bodySmall)),
            Text('$progress%', style: AppTextStyles.body),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          child: LinearProgressIndicator(
            value: progress / 100,
            backgroundColor: AppPalette.of(context).divider,
            valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
            minHeight: 8,
          ),
        ),
      ],
    );
  }
}

/// 작은 화면에서도 액션 시트를 스크롤 가능하게 유지하는 공통 프레임
class AdaptiveModalSheet extends StatelessWidget {
  final String? title;
  final String? subtitle;
  final Widget child;
  final double maxHeightFactor;
  final EdgeInsetsGeometry contentPadding;
  final Key? scrollViewKey;

  const AdaptiveModalSheet({
    super.key,
    this.title,
    this.subtitle,
    required this.child,
    this.maxHeightFactor = 0.85,
    this.contentPadding = EdgeInsets.zero,
    this.scrollViewKey,
  }) : assert(
          maxHeightFactor > 0 && maxHeightFactor <= 1,
          'maxHeightFactor must be between 0 and 1',
        );

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final maxHeight = mediaQuery.size.height * maxHeightFactor;

    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxHeight),
        child: SingleChildScrollView(
          key: scrollViewKey,
          padding: EdgeInsets.only(
            bottom: AppSpacing.lg + mediaQuery.viewInsets.bottom,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: AppSpacing.md),
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppPalette.of(context).divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              if (title != null) ...[
                const SizedBox(height: AppSpacing.lg),
                Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                    child: Text(title!,
                        style: AppTextStyles.heading3,
                        textAlign: TextAlign.center)),
              ],
              if (subtitle != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  subtitle!,
                  style: AppTextStyles.bodySmall,
                  textAlign: TextAlign.center,
                ),
              ],
              Padding(
                padding: contentPadding,
                child: child,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
