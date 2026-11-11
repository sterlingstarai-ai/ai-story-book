import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../utils/constants.dart';

class AppShell extends StatelessWidget {
  const AppShell({
    super.key,
    required this.currentIndex,
    this.appBar,
    required this.body,
    this.backgroundColor,
    this.floatingActionButton,
    this.showNavigation = true,
  });

  final bool showNavigation;
  final int currentIndex;
  final PreferredSizeWidget? appBar;
  final Widget body;
  final Color? backgroundColor;
  final Widget? floatingActionButton;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: backgroundColor ?? AppPalette.of(context).background,
      appBar: appBar,
      body: body,
      floatingActionButton: floatingActionButton,
      bottomNavigationBar: showNavigation
          ? _BottomNavBar(currentIndex: currentIndex)
          : null,
    );
  }
}

class _BottomNavBar extends StatelessWidget {
  const _BottomNavBar({required this.currentIndex});

  final int currentIndex;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final colors = StorybookColors.of(context);
    return Container(
      decoration: BoxDecoration(
        color: colors.sheet,
        border: Border(top: BorderSide(color: colors.rule)),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.sm,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _NavItem(
                icon: Icons.home_rounded,
                label: l10n.navShellHome,
                isSelected: currentIndex == 0,
                onTap: currentIndex == 0
                    ? () {}
                    : () => Navigator.pushReplacementNamed(context, '/'),
              ),
              _NavItem(
                icon: Icons.add_circle_rounded,
                label: l10n.navShellCreate,
                isSelected: currentIndex == 1,
                onTap: currentIndex == 1
                    ? () {}
                    : () => Navigator.pushNamed(context, '/create'),
              ),
              _NavItem(
                icon: Icons.auto_stories_rounded,
                label: l10n.navShellLibrary,
                isSelected: currentIndex == 2,
                onTap: currentIndex == 2
                    ? () {}
                    : () => Navigator.pushReplacementNamed(context, '/library'),
              ),
              _NavItem(
                icon: Icons.people_rounded,
                label: l10n.navShellCharacters,
                isSelected: currentIndex == 3,
                onTap: currentIndex == 3
                    ? () {}
                    : () => Navigator.pushReplacementNamed(
                        context,
                        '/characters',
                      ),
              ),
            ].map((item) => Expanded(child: item)).toList(),
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
    final colors = StorybookColors.of(context);
    final color = isSelected ? colors.accent : colors.muted;

    return Semantics(
      button: true,
      selected: isSelected,
      label: label,
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        child: Container(
          constraints: const BoxConstraints(
            minHeight: AppSizing.minTouchTarget,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xs,
            vertical: AppSpacing.sm,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: AppSizing.minTouchTarget,
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
                decoration: BoxDecoration(
                  color: isSelected ? colors.tint : null,
                  borderRadius: BorderRadius.circular(AppRadius.lg),
                ),
                child: Icon(icon, color: color, size: 26),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                label,
                textAlign: TextAlign.center,
                style: AppTextStyles.caption.copyWith(
                  fontSize: 13,
                  color: color,
                  fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
