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
import 'screens/account_recovery_screen.dart';
import 'services/analytics.dart';
import 'services/iap_platform_init.dart';
import 'services/user_service.dart';
import 'utils/app_theme.dart';
import 'widgets/age_gate_dialog.dart';
import 'widgets/account_bootstrap.dart';
import 'widgets/screen_time_lock.dart';

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

  // R0(🔴C1): iOS StoreKit1 강제. **반드시 InAppPurchase.instance 첫 접근 전에** —
  // 플러그인 등록이 그 접근에서 일어나고, 등록 시점 플래그로 SK1/SK2 옵저버가 정해진다.
  // 늦게 호출하면 이미 SK2로 등록돼 serverVerificationData가 JWS로 나가고, 백엔드
  // legacy verifyReceipt가 21002로 전량 실패한다(과금됐는데 미지급).
  await IapPlatformInit.ensureStoreKit1();

  // SharedPreferences 초기화
  final prefs = await SharedPreferences.getInstance();

  // M1(🟠): X-User-Key(유일 자격증명)를 Keychain/Keystore에서 로드하고, 기존 평문
  // SharedPreferences 값이 있으면 이관 후 평문을 삭제한다. 동기 `getUserKey()`가
  // 이 캐시를 쓰므로 runApp 전에 완료돼야 한다.
  runApp(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ],
      child: Consumer(
          builder: (context, ref, _) => AccountBootstrap(
                onRestore: (context) =>
                    openAccountRecovery(context, ref, restoreOnly: true),
                initialize: () async {
                  await ref.read(accountRecoveryServiceProvider).initialize();
                  await UserService.bootstrapUserKey(prefs);
                  await ref
                      .read(accountRecoveryServiceProvider)
                      .validateCurrentSession();
                },
                child: const AIStoryBookApp(),
              )),
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
      // M15: 작업 전환기/웹 탭 타이틀을 로케일별로(한국어 하드코딩 제거).
      onGenerateTitle: (context) => AppLocalizations.of(context).appTitle,
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(Brightness.light),
      darkTheme: buildAppTheme(Brightness.dark),
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
            ExcludeSemantics(child: base),
            ScreenTimeLockOverlay(
              snapshot: screenTime,
              onExtend: _extendScreenTime,
            ),
          ],
        );
      },
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
        settings: settings,
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
