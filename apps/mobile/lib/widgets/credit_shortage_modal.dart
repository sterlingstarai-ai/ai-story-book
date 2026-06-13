import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../utils/constants.dart';

Future<void> showCreditShortageModal(
  BuildContext context, {
  String? title,
  String? message,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (context) => _CreditShortageSheet(
      title: title,
      message: message,
    ),
  );
}

class _CreditShortageSheet extends StatelessWidget {
  const _CreditShortageSheet({
    this.title,
    this.message,
  });

  final String? title;
  final String? message;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final resolvedTitle = title != null && title!.trim().isNotEmpty
        ? title!.trim()
        : l10n.creditShortageTitle;
    final resolvedMessage = message != null && message!.trim().isNotEmpty
        ? message!.trim()
        : l10n.creditShortageMessage;

    return Container(
      decoration: const BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.xl)),
      ),
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.xl,
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(resolvedTitle, style: AppTextStyles.heading2),
            const SizedBox(height: AppSpacing.sm),
            Text(
              resolvedMessage,
              style: AppTextStyles.bodySmall,
            ),
            const SizedBox(height: AppSpacing.lg),
            _ActionCard(
              icon: Icons.ondemand_video,
              title: l10n.creditShortageFreeTitle,
              subtitle: l10n.creditShortageFreeSubtitle,
              onTap: () => Navigator.pop(context),
            ),
            const SizedBox(height: AppSpacing.sm),
            _ActionCard(
              icon: Icons.workspace_premium,
              title: l10n.creditShortageSubscribeTitle,
              subtitle: l10n.creditShortageSubscribeSubtitle,
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(context, '/credits');
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            _ActionCard(
              icon: Icons.local_offer,
              title: l10n.creditShortagePurchaseTitle,
              subtitle: l10n.creditShortagePurchaseSubtitle,
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(context, '/credits');
              },
            ),
            const SizedBox(height: AppSpacing.md),
            Center(
              child: TextButton(
                onPressed: () => Navigator.pop(context),
                child: Text(l10n.creditShortageClose),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.primaryLight,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.primaryMedium),
        ),
        child: Row(
          children: [
            Icon(icon, color: AppColors.primary),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: AppTextStyles.body
                          .copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(subtitle, style: AppTextStyles.caption),
                ],
              ),
            ),
            const Icon(Icons.chevron_right),
          ],
        ),
      ),
    );
  }
}
