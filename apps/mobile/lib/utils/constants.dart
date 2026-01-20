import 'package:flutter/material.dart';

/// 앱 색상
class AppColors {
  static const primary = Color(0xFF6366F1);
  static const secondary = Color(0xFFF472B6);
  static const background = Color(0xFFFAFAFA);
  static const surface = Colors.white;
  static const error = Color(0xFFEF4444);
  static const success = Color(0xFF22C55E);

  static const textPrimary = Color(0xFF1F2937);
  static const textSecondary = Color(0xFF6B7280);
  static const textHint = Color(0xFF9CA3AF);

  static const divider = Color(0xFFE5E7EB);

  // Pre-computed opacity variants (performance optimization)
  // Instead of calling withOpacity() at runtime, use these constants
  static const primaryLight = Color(0x1A6366F1); // primary 10%
  static const primaryMedium = Color(0x336366F1); // primary 20%
  static const primaryStrong = Color(0x4D6366F1); // primary 30%
  static const primaryHalf = Color(0x806366F1); // primary 50%
  static const primaryMuted = Color(0xCC6366F1); // primary 80%

  static const secondaryLight = Color(0x33F472B6); // secondary 20%

  static const successLight = Color(0x1A22C55E); // success 10%

  static const blackOverlay = Color(0x80000000); // black 50%
  static const blackOverlayLight = Color(0x0D000000); // black 5%
  static const blackOverlayShadow = Color(0x14000000); // black 8%
  static const blackOverlayStrong = Color(0xB3000000); // black 70%

  static const whiteOverlay = Color(0x33FFFFFF); // white 20%
  static const whiteOverlayLight = Color(0x4DFFFFFF); // white 30%
  static const whiteOverlayStrong = Color(0xE6FFFFFF); // white 90%
}

/// 앱 텍스트 스타일
class AppTextStyles {
  static const heading1 = TextStyle(
    fontSize: 28,
    fontWeight: FontWeight.bold,
    color: AppColors.textPrimary,
  );

  static const heading2 = TextStyle(
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: AppColors.textPrimary,
  );

  static const heading3 = TextStyle(
    fontSize: 18,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );

  static const body = TextStyle(
    fontSize: 16,
    color: AppColors.textPrimary,
  );

  static const bodySmall = TextStyle(
    fontSize: 14,
    color: AppColors.textSecondary,
  );

  static const caption = TextStyle(
    fontSize: 12,
    color: AppColors.textHint,
  );

  static const button = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w600,
  );
}

/// 앱 간격
class AppSpacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 16.0;
  static const lg = 24.0;
  static const xl = 32.0;
  static const xxl = 48.0;
}

/// 앱 반경
class AppRadius {
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
}
