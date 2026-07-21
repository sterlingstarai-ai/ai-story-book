import 'dart:async';
import 'dart:ui';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'core/app_telemetry.dart';
import 'l10n/app_localizations.dart';
import 'providers/providers.dart';
import 'screens/screens.dart';
import 'services/analytics.dart';
import 'services/screen_time_service.dart';
import 'utils/constants.dart';
import 'widgets/age_gate_dialog.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  FlutterError.onError = (details) {
    AppTelemetry.recordError(
      details.exception,
      details.stack ?? StackTrace.current,
      context: 'flutter_error',
    );
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    AppTelemetry.recordError(
      error,
      stack,
      context: 'platform_dispatcher_error',
    );
    return true;
  };

  // 상태바 스타일
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
    ),
  );

  // SharedPreferences 초기화
  final prefs = await SharedPreferences.getInstance();

  runApp(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ],
      child: const AIStoryBookApp(),
    ),
  );
}

class AIStoryBookApp extends ConsumerStatefulWidget {
  const AIStoryBookApp({super.key});

  @override
  ConsumerState<AIStoryBookApp> createState() => _AIStoryBookAppState();
}

class _AIStoryBookAppState extends ConsumerState<AIStoryBookApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    ref.read(analyticsProvider).logEvent(AnalyticsEvents.appOpen);
    final screenTimeNotifier = ref.read(screenTimeStateProvider.notifier);
    unawaited(screenTimeNotifier.initialize().then((_) {
      screenTimeNotifier.onAppResumed();
    }));
    unawaited(ref.read(notificationSchedulerProvider).initialize());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final screenTimeNotifier = ref.read(screenTimeStateProvider.notifier);
    if (state == AppLifecycleState.resumed) {
      screenTimeNotifier.onAppResumed();
      return;
    }
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(screenTimeNotifier.onAppPaused());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(ref.read(screenTimeStateProvider.notifier).onAppPaused());
    super.dispose();
  }

  Future<void> _extendScreenTime() async {
    final verified = await showAgeGateDialog(context, ref);
    if (!verified || !mounted) {
      return;
    }
    await ref.read(screenTimeStateProvider.notifier).grantExtensionMinutes(10);
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(AppLocalizations.of(context).lockExtendDone)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final themeMode = ref.watch(appThemeModeProvider);
    final screenTime = ref.watch(screenTimeStateProvider);
    return MaterialApp(
      title: 'AI 동화책',
      debugShowCheckedModeBanner: false,
      theme: _buildTheme(Brightness.light),
      darkTheme: _buildTheme(Brightness.dark),
      themeMode: themeMode,
      initialRoute: '/startup',
      onGenerateRoute: buildAppRoute,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      builder: (context, child) {
        final base = child ?? const SizedBox.shrink();
        if (!screenTime.enabled || !screenTime.isLocked) {
          return base;
        }

        return Stack(
          children: [
            base,
            _ScreenTimeLockOverlay(
              snapshot: screenTime,
              onExtend: _extendScreenTime,
            ),
          ],
        );
      },
    );
  }

  ThemeData _buildTheme(Brightness brightness) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: brightness,
    );
    return ThemeData(
      useMaterial3: true,
      fontFamily: 'Pretendard',
      colorScheme: colorScheme,
      scaffoldBackgroundColor: brightness == Brightness.dark
          ? colorScheme.surface
          : AppColors.background,
      appBarTheme: AppBarTheme(
        backgroundColor: brightness == Brightness.dark
            ? colorScheme.surface
            : AppColors.background,
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
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          minimumSize: const Size(double.infinity, 64),
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
        backgroundColor: AppColors.surface,
        disabledColor: AppColors.divider,
        selectedColor: AppColors.primaryMedium,
        secondarySelectedColor: AppColors.primaryMedium,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.md,
        ),
        labelStyle: AppTextStyles.bodySmall,
        secondaryLabelStyle: AppTextStyles.bodySmall,
        brightness: brightness,
        side: const BorderSide(color: AppColors.divider),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
      ),
      materialTapTargetSize: MaterialTapTargetSize.padded,
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.divider),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.divider),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.primary, width: 2),
        ),
      ),
    );
  }
}

class _ScreenTimeLockOverlay extends StatelessWidget {
  const _ScreenTimeLockOverlay({
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
      child: ColoredBox(
        color: AppColors.blackOverlayStrong,
        child: SafeArea(
          child: Center(
            child: Container(
              margin: const EdgeInsets.all(AppSpacing.lg),
              padding: const EdgeInsets.all(AppSpacing.lg),
              decoration: BoxDecoration(
                color: AppColors.surface,
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
            ),
          ),
        ),
      ),
    );
  }
}

Route<dynamic> buildAppRoute(RouteSettings settings) {
  switch (settings.name) {
    case '/startup':
      return MaterialPageRoute(
        builder: (_) => const StartupGateScreen(),
      );

    case '/':
      return MaterialPageRoute(
        builder: (_) => const HomeScreen(),
      );

    case '/create':
      return MaterialPageRoute(
        builder: (_) => const CreateScreen(),
        fullscreenDialog: true,
      );

    case '/loading':
      final jobId = _readRouteStringArg(settings.arguments);
      if (jobId == null) {
        return _homeRoute();
      }
      return MaterialPageRoute(
        builder: (_) => LoadingScreen(jobId: jobId),
      );

    case '/viewer':
      final bookId = _readRouteStringArg(settings.arguments);
      if (bookId == null) {
        return _homeRoute();
      }
      return MaterialPageRoute(
        builder: (_) => ViewerScreen(bookId: bookId),
        fullscreenDialog: true,
      );

    case '/library':
      return MaterialPageRoute(
        builder: (_) => const LibraryScreen(),
      );

    case '/characters':
      return MaterialPageRoute(
        builder: (_) => const CharactersScreen(),
      );

    case '/credits':
      return MaterialPageRoute(
        settings: settings, // route name 전달(age-gate 트리거가 의존)
        builder: (_) => const CreditsScreen(),
      );

    case '/settings':
      return MaterialPageRoute(
        builder: (_) => const SettingsScreen(),
      );

    case '/profiles':
      return MaterialPageRoute(
        builder: (_) => const ProfilesScreen(),
      );

    case '/parent-dashboard':
      return MaterialPageRoute(
        builder: (_) => const ParentDashboardScreen(),
      );

    case '/reading-growth':
      return MaterialPageRoute(
        settings: settings, // route name 전달(부모 age-gate 트리거가 의존)
        builder: (_) => const ReadingGrowthScreen(),
      );

    case '/voice-profiles':
      return MaterialPageRoute(
        builder: (_) => const VoiceProfilesScreen(),
      );

    case '/branch-story':
      final args = _readRouteMapArg(settings.arguments);
      final bookId = args?['bookId']?.toString();
      if (bookId == null || bookId.isEmpty) {
        return _homeRoute();
      }
      return MaterialPageRoute(
        builder: (_) => BranchStoryScreen(bookId: bookId),
      );

    case '/pronunciation-practice':
      final args = _readRouteMapArg(settings.arguments);
      final bookId = args?['bookId']?.toString();
      final expectedText = args?['expectedText']?.toString();
      final pageRaw = args?['pageNumber'];
      final pageNumber =
          pageRaw is int ? pageRaw : int.tryParse(pageRaw?.toString() ?? '');
      if (bookId == null ||
          bookId.isEmpty ||
          expectedText == null ||
          expectedText.isEmpty ||
          pageNumber == null ||
          pageNumber <= 0) {
        return _homeRoute();
      }
      final pronunciationLanguage = args?['language']?.toString();
      return MaterialPageRoute(
        builder: (_) => PronunciationPracticeScreen(
          bookId: bookId,
          pageNumber: pageNumber,
          expectedText: expectedText,
          language: (pronunciationLanguage != null &&
                  pronunciationLanguage.isNotEmpty)
              ? pronunciationLanguage
              : 'ko',
        ),
      );

    case '/pod-order':
      final args = _readRouteMapArg(settings.arguments);
      final bookId = args?['bookId']?.toString();
      final title = args?['bookTitle']?.toString() ?? '';
      if (bookId == null || bookId.isEmpty) {
        return _homeRoute();
      }
      return MaterialPageRoute(
        builder: (_) => PodOrderScreen(
          bookId: bookId,
          bookTitle: title,
        ),
      );

    case '/consent':
      return MaterialPageRoute(
        builder: (_) => const ConsentScreen(),
      );

    case '/onboarding':
      return MaterialPageRoute(
        builder: (_) => const OnboardingScreen(),
      );

    default:
      return _homeRoute();
  }
}

Route<dynamic> _homeRoute() {
  return MaterialPageRoute(
    builder: (_) => const HomeScreen(),
  );
}

String? _readRouteStringArg(dynamic argument) {
  if (argument is String && argument.isNotEmpty) {
    return argument;
  }
  return null;
}

Map<String, dynamic>? _readRouteMapArg(dynamic argument) {
  if (argument is Map<String, dynamic>) {
    return argument;
  }
  if (argument is Map) {
    final mapped = <String, dynamic>{};
    for (final entry in argument.entries) {
      if (entry.key == null) {
        continue;
      }
      mapped[entry.key.toString()] = entry.value;
    }
    return mapped;
  }
  return null;
}
