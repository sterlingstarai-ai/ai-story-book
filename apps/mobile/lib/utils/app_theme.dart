import 'package:flutter/material.dart';
import 'constants.dart';

ThemeData buildAppTheme(Brightness brightness) {
  final palette = AppPalette(brightness == Brightness.dark);
  final colorScheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    brightness: brightness,
  ).copyWith(
      primary: palette.primary,
      surface: palette.surface,
      onSurface: palette.textPrimary,
      onSurfaceVariant: palette.textSecondary,
      outline: palette.divider);
  return ThemeData(
    useMaterial3: true,
    fontFamily: 'Pretendard',
    colorScheme: colorScheme,
    textTheme: ThemeData(brightness: brightness).textTheme.apply(
          fontFamily: 'Pretendard',
          bodyColor: palette.textPrimary,
          displayColor: palette.textPrimary,
        ),
    iconTheme: IconThemeData(color: palette.textSecondary),
    dividerColor: palette.divider,
    dialogTheme: DialogThemeData(backgroundColor: palette.surface),
    bottomSheetTheme: BottomSheetThemeData(backgroundColor: palette.surface),
    scaffoldBackgroundColor: palette.background,
    appBarTheme: AppBarTheme(
      toolbarHeight: AppSizing.minTouchTarget,
      leadingWidth: AppSizing.minTouchTarget,
      scrolledUnderElevation: 0,
      backgroundColor: palette.background,
      elevation: 0,
      centerTitle: true,
      iconTheme: IconThemeData(
        color: brightness == Brightness.dark
            ? colorScheme.onSurface
            : AppColors.textPrimary,
      ),
      titleTextStyle: AppTextStyles.heading3.copyWith(
        color: brightness == Brightness.dark
            ? colorScheme.onSurface
            : AppColors.textPrimary,
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: const Color(0xFF4F46E5),
        foregroundColor: Colors.white,
        minimumSize: const Size(64, 64),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 64),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
        backgroundColor: const Color(0xFF4F46E5),
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 64),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(64, 64),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        minimumSize: const Size(64, 64),
        padding: const EdgeInsets.all(AppSpacing.md),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: palette.surface,
      disabledColor: palette.divider,
      selectedColor: palette.primaryLight,
      secondarySelectedColor: palette.primaryLight,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.md,
      ),
      labelStyle: AppTextStyles.bodySmall.copyWith(color: palette.textPrimary),
      secondaryLabelStyle:
          AppTextStyles.bodySmall.copyWith(color: palette.textPrimary),
      brightness: brightness,
      side: BorderSide(color: palette.divider),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
    ),
    materialTapTargetSize: MaterialTapTargetSize.padded,
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      hintStyle: TextStyle(color: palette.textHint),
      labelStyle: TextStyle(color: palette.textSecondary),
      helperStyle: TextStyle(color: palette.textSecondary),
      counterStyle: TextStyle(color: palette.textSecondary),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
      fillColor: palette.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: BorderSide(color: palette.divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: BorderSide(color: palette.divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: BorderSide(color: palette.primary, width: 2),
      ),
    ),
  );
}
