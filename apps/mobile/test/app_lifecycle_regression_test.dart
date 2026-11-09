import 'dart:async';

import 'package:ai_story_book/main.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/notification_scheduler.dart';
import 'package:ai_story_book/services/screen_time_service.dart';
import 'package:dio/dio.dart';
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

class _ForegroundStatusApi extends ApiClient {
  _ForegroundStatusApi() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'qa');

  final jobs = <String>[];

  @override
  Future<JobStatus> getBookStatus(String jobId, {CancelToken? cancelToken}) async {
    jobs.add(jobId);
    return JobStatus(
      jobId: jobId,
      status: jobs.length == 1 ? JobState.running : JobState.done,
      progress: jobs.length == 1 ? 50 : 100,
    );
  }
}

void main() {
  testWidgets('foreground refreshes the active-generation list', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final screenTime = _ScreenTime()..initialized.complete();
    var reads = 0;
    final container = ProviderContainer(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        screenTimeStateProvider.overrideWith(() => screenTime),
        notificationSchedulerProvider.overrideWithValue(_Notifications()),
        activeBookGenerationsProvider.overrideWith(
          (ref) async => [
            if (reads++ == 0)
              JobStatus(
                jobId: 'active',
                status: JobState.running,
                progress: 50,
              ),
          ],
        ),
      ],
    );
    addTearDown(container.dispose);
    final listener = container.listen(
      activeBookGenerationsProvider,
      (_, __) {},
    );
    addTearDown(listener.close);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const AIStoryBookApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(listener.read().valueOrNull?.single.jobId, 'active');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(reads, 2);
    expect(listener.read().valueOrNull, isEmpty);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('returning from background wakes the existing job immediately', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final api = _ForegroundStatusApi();
    final screenTime = _ScreenTime()..initialized.complete();
    final container = ProviderContainer(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        screenTimeStateProvider.overrideWith(() => screenTime),
        notificationSchedulerProvider.overrideWithValue(_Notifications()),
      ],
    );
    addTearDown(api.close);
    addTearDown(container.dispose);
    final listener = container.listen(jobPollingProvider('existing-job'), (_, __) {});
    addTearDown(listener.close);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const AIStoryBookApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(listener.read().valueOrNull?.progress, 50);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(api.jobs, ['existing-job']);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 4));
    expect(api.jobs, ['existing-job']);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(listener.read().valueOrNull?.isComplete, isTrue);
    expect(api.jobs, ['existing-job', 'existing-job']);
    await tester.pump(const Duration(seconds: 4));
    expect(api.jobs, hasLength(2));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

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
