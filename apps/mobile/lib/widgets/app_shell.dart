import 'package:flutter/material.dart';

import '../utils/constants.dart';

class AppShell extends StatelessWidget {
  const AppShell({
    super.key,
    required this.currentIndex,
    this.appBar,
    required this.body,
    this.backgroundColor,
    this.floatingActionButton,
  });

  final int currentIndex;
  final PreferredSizeWidget? appBar;
  final Widget body;
  final Color? backgroundColor;
  final Widget? floatingActionButton;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: backgroundColor ?? AppColors.background,
      appBar: appBar,
      body: body,
      floatingActionButton: floatingActionButton,
      bottomNavigationBar: _BottomNavBar(currentIndex: currentIndex),
    );
  }
}

class _BottomNavBar extends StatelessWidget {
  const _BottomNavBar({required this.currentIndex});

  final int currentIndex;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.surface,
        boxShadow: [
          BoxShadow(
            color: AppColors.blackOverlayLight,
            blurRadius: 10,
            offset: Offset(0, -4),
          ),
        ],
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _NavItem(
                icon: Icons.home_rounded,
                label: '홈',
                isSelected: currentIndex == 0,
                onTap: currentIndex == 0
                    ? () {}
                    : () => Navigator.pushReplacementNamed(context, '/'),
              ),
              _NavItem(
                icon: Icons.add_circle_rounded,
                label: '만들기',
                isSelected: currentIndex == 1,
                onTap: () => Navigator.pushNamed(context, '/create'),
              ),
              _NavItem(
                icon: Icons.auto_stories_rounded,
                label: '서재',
                isSelected: currentIndex == 2,
                onTap: currentIndex == 2
                    ? () {}
                    : () => Navigator.pushReplacementNamed(context, '/library'),
              ),
              _NavItem(
                icon: Icons.people_rounded,
                label: '캐릭터',
                isSelected: currentIndex == 3,
                onTap: currentIndex == 3
                    ? () {}
                    : () =>
                        Navigator.pushReplacementNamed(context, '/characters'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.icon,
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = isSelected ? AppColors.primary : AppColors.textHint;

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: color, size: 24),
            const SizedBox(height: AppSpacing.xs),
            Text(
              label,
              style: TextStyle(
                fontSize: 12,
                color: color,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
