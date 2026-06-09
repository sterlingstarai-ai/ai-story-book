import 'package:flutter/material.dart';

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
    final resolvedTitle =
        title != null && title!.trim().isNotEmpty ? title!.trim() : '크레딧이 부족해요';
    final resolvedMessage = message != null && message!.trim().isNotEmpty
        ? message!.trim()
        : '아래 방법으로 크레딧을 충전하고 동화책 만들기를 이어갈 수 있어요.';

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
              title: '무료 크레딧 받기',
              subtitle: '광고 시청 또는 초대로 무료 크레딧',
              onTap: () => Navigator.pop(context),
            ),
            const SizedBox(height: AppSpacing.sm),
            _ActionCard(
              icon: Icons.workspace_premium,
              title: '구독하기',
              subtitle: '월 구독으로 넉넉하게 이용하기',
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(context, '/credits');
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            _ActionCard(
              icon: Icons.local_offer,
              title: '크레딧 구매',
              subtitle: '필요한 만큼 바로 충전하기',
              onTap: () {
                Navigator.pop(context);
                Navigator.pushNamed(context, '/credits');
              },
            ),
            const SizedBox(height: AppSpacing.md),
            Center(
              child: TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('닫기'),
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
