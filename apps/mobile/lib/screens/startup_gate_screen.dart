import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../services/timezone_sync.dart';
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

    final hasConsent = await parental.hasConsent(prefs);
    if (!hasConsent) {
      if (!mounted) {
        return;
      }
      Navigator.pushReplacementNamed(context, '/consent');
      return;
    }

    // H2/G10: 기기 타임존을 서버에 동기화(변경 없으면 no-op). 실패해도 부팅을 막지 않는다.
    unawaited(TimezoneSync.sync(api: ref.read(apiClientProvider), prefs: prefs));

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
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    return const HomeScreen();
  }
}
