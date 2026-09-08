import 'dart:async';

import 'package:ai_story_book/main.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/notification_scheduler.dart';
import 'package:ai_story_book/services/screen_time_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ScreenTime extends ScreenTimeNotifier {
  final initialized = Completer<void>();
  int pauses = 0, resumes = 0;
  @override
  ScreenTimeSnapshot build() => ScreenTimeSnapshot.initial();
  @override
  Future<void> initialize() => initialized.future;
  @override
  Future<void> onAppPaused() async => pauses++;
  @override
  void onAppResumed() => resumes++;
}

class _Notifications implements NotificationScheduler {
  @override
  Future<void> initialize() async {}
  @override
  Future<bool> requestPermissions() async => false;
  @override
  Future<void> cancelBedtime() async {}
  @override
  Future<void> scheduleDailyBedtime({
    required int hour,
    required int minute,
    required String title,
    required String body,
    required String channelName,
    required String channelDescription,
  }) async {}
}

void main() {
  for (final completesBeforeDispose in [true, false]) {
    testWidgets(
      'app teardown pauses safely, initialized before=$completesBeforeDispose',
      (tester) async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();
        final screenTime = _ScreenTime();
        await tester.pumpWidget(
          ProviderScope(
            overrides: [
              sharedPreferencesProvider.overrideWithValue(prefs),
              screenTimeStateProvider.overrideWith(() => screenTime),
              notificationSchedulerProvider.overrideWithValue(_Notifications()),
            ],
            child: const AIStoryBookApp(),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.byType(ConsentScreen), findsOneWidget);
        expect(find.byType(HomeScreen, skipOffstage: false), findsNothing);
        if (completesBeforeDispose) {
          screenTime.initialized.complete();
          await tester.pump();
        }
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
        if (!completesBeforeDispose) {
          screenTime.initialized.complete();
          await tester.pump();
        }
        expect(tester.takeException(), isNull);
        expect(screenTime.pauses, 1);
        expect(screenTime.resumes, completesBeforeDispose ? 1 : 0);
      },
    );
  }
}
