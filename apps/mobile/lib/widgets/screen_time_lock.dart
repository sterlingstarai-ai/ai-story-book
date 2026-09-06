import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';
import '../services/screen_time_service.dart';
import '../utils/constants.dart';

class ScreenTimeLockOverlay extends StatelessWidget {
  const ScreenTimeLockOverlay({
    super.key,
    required this.snapshot,
    required this.onExtend,
  });

  final ScreenTimeSnapshot snapshot;
  final VoidCallback onExtend;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final usedMinutes = snapshot.usedMinutesRounded;
    final limitMinutes = (snapshot.effectiveLimitSeconds / 60).ceil();

    return Positioned.fill(
      child: Material(
        color: AppColors.blackOverlayStrong,
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
                child: Container(
              margin: const EdgeInsets.all(AppSpacing.lg),
              padding: const EdgeInsets.all(AppSpacing.lg),
              decoration: BoxDecoration(
                color: AppPalette.of(context).surface,
                borderRadius: BorderRadius.circular(AppRadius.lg),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.lock_clock,
                      size: 48, color: AppColors.error),
                  const SizedBox(height: AppSpacing.md),
                  Text(
                    l.lockTitle,
                    style: AppTextStyles.heading3,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    l.lockUsage(usedMinutes, limitMinutes),
                    style: AppTextStyles.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    l.lockSubtitle,
                    style: AppTextStyles.caption,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.md),
                  ElevatedButton.icon(
                    onPressed: onExtend,
                    icon: const Icon(Icons.family_restroom),
                    label: Text(l.lockExtendButton),
                  ),
                ],
              ),
            )),
          ),
        ),
      ),
    );
  }
}
