import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/timezone_sync.dart';
import '../utils/constants.dart';
import 'home_screen.dart';

class StartupGateScreen extends ConsumerStatefulWidget {
  const StartupGateScreen({super.key});

  @override
  ConsumerState<StartupGateScreen> createState() => _StartupGateScreenState();
}

class _StartupGateScreenState extends ConsumerState<StartupGateScreen> {
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.loadAgeGateSession(prefs);

    var hasConsent = await parental.hasConsent(prefs);
    if (hasConsent && mounted) {
      try {
        final current = await ref
            .read(apiClientProvider)
            .getConsent()
            .timeout(const Duration(seconds: 3));
        if (current['guardian_email_required'] == true) hasConsent = false;
      } catch (_) {
        // Local reading remains possible offline. The server still controls
        // all writes that require an active consent record.
      }
    }
    if (!hasConsent) {
      if (!mounted) {
        return;
      }
      Navigator.pushReplacementNamed(context, '/consent');
      return;
    }

    // H2/G10: 기기 타임존을 서버에 동기화(변경 없으면 no-op). 실패해도 부팅을 막지 않는다.
    unawaited(
      TimezoneSync.sync(api: ref.read(apiClientProvider), prefs: prefs),
    );

    final doneOnboarding = await parental.hasSeenOnboarding(prefs);
    if (!doneOnboarding) {
      if (!mounted) {
        return;
      }
      Navigator.pushReplacementNamed(context, '/onboarding');
      return;
    }

    if (mounted) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.light,
        child: Scaffold(
          backgroundColor: StorybookColors.ink,
          body: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Image.asset(
                      'assets/branding/splash.png',
                      width: 240,
                      excludeFromSemantics: true,
                    ),
                    Text(
                      AppLocalizations.of(context).appTitle,
                      style: AppTextStyles.heading1.copyWith(
                        color: StorybookColors.onInk,
                        fontSize: 34,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    if (!MediaQuery.disableAnimationsOf(context)) ...[
                      const SizedBox(height: AppSpacing.lg),
                      const SizedBox(
                        width: 48,
                        child: LinearProgressIndicator(
                          minHeight: 2,
                          color: StorybookColors.moonlight,
                          backgroundColor: Color(0xFF315553),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    return const HomeScreen();
  }
}
