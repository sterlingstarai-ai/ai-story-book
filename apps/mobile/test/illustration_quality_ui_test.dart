import 'dart:async';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

BookResult _originalBook() => BookResult(
      bookId: 'original-book',
      jobId: 'original-job',
      title: '원래 동화',
      coverImageUrl: '',
      pages: [
        PageResult(pageNumber: 1, text: '원래 본문이에요.', imageUrl: ''),
      ],
    );

Widget _loadingApp(
  Locale locale,
  Stream<JobStatus> stream, {
  List<String>? navigations,
}) =>
    ProviderScope(
      overrides: [
        jobPollingProvider('quality-job').overrideWith((ref) => stream),
      ],
      child: MaterialApp(
        locale: locale,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const LoadingScreen(jobId: 'quality-job'),
        onGenerateRoute: (settings) {
          navigations?.add(settings.name!);
          return MaterialPageRoute<void>(
            builder: (_) =>
                Scaffold(body: Text('destination ${settings.name}')),
          );
        },
      ),
    );

class _QualityFailureApi extends ApiClient {
  _QualityFailureApi()
      : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test-user');

  int regenerationCalls = 0;

  @override
  Future<Map<String, dynamic>> getSettings() async =>
      {'allow_kakao_share': false};

  @override
  Future<String> regeneratePage(
    String jobId,
    int pageNumber, {
    required String regenerateTarget,
    String? feedback,
  }) async {
    regenerationCalls++;
    expect(jobId, 'original-job');
    expect(pageNumber, 1);
    expect(regenerateTarget, 'image');
    throw DioException(
      requestOptions: RequestOptions(path: '/test-regenerate'),
      error: ApiError(
        code: 'IMAGE_QUALITY_FAILED',
        message: 'private diagnostic; refund completed',
        statusCode: 502,
      ),
    );
  }
}

/// 재생성이 '큐 등록'만 끝난 시점에 책을 다시 읽어오면 워커가 끝나기 전의 옛 그림이
/// 캐시에 고정되고, 이후 재조회가 없어 새 그림이 영영 보이지 않았다. 이 대역은 잡이
/// 완료로 바뀌는 순간까지 관측을 반복하게 만든다.
class _QueuedThenDoneApi extends ApiClient {
  _QueuedThenDoneApi()
      : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test-user');

  int regenerationCalls = 0;
  int statusPolls = 0;

  @override
  Future<Map<String, dynamic>> getSettings() async =>
      {'allow_kakao_share': false};

  @override
  Future<String> regeneratePage(
    String jobId,
    int pageNumber, {
    required String regenerateTarget,
    String? feedback,
  }) async {
    regenerationCalls++;
    return 'regen-job';
  }

  @override
  Future<JobStatus> getBookStatus(String jobId, {CancelToken? cancelToken}) async {
    statusPolls++;
    return JobStatus(
      jobId: jobId,
      status: statusPolls >= 3 ? JobState.done : JobState.running,
      progress: statusPolls >= 3 ? 100 : 40,
    );
  }

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async =>
      <String, dynamic>{};
}

void main() {
  for (final language in ['ko', 'en', 'ja']) {
    final locale = Locale(language);
    testWidgets('$language distinguishes checking, repair and recheck',
        (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.textScaleFactorTestValue = 1.4;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final l = await AppLocalizations.delegate.load(locale);
      final controller = StreamController<JobStatus>();
      addTearDown(controller.close);
      final navigations = <String>[];
      await tester.pumpWidget(
        _loadingApp(locale, controller.stream, navigations: navigations),
      );
      await tester.pump();

      final phases = [
        (86, 'verify_illustrations', l.loadingStepVerifyIllustrations),
        (87, 'repair_illustrations', l.loadingStepRepairIllustrations),
        (88, 'verify_illustrations', l.loadingStepRecheckIllustrations),
      ];
      for (final (progress, step, label) in phases) {
        controller.add(JobStatus(
          jobId: 'quality-job',
          status: JobState.running,
          progress: progress,
          currentStep: step,
          // An existing result must not make an unfinished check complete.
          result: _originalBook(),
        ));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));
        expect(find.text(label), findsOneWidget);
        expect(find.text('$progress%'), findsOneWidget);
        expect(find.text(step), findsNothing);
        expect(find.text(l.loadingStepGenerateImages), findsNothing);
        expect(navigations, isEmpty);
        expect(tester.takeException(), isNull);
      }
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('$language quality failure stays failed with reachable actions',
        (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.textScaleFactorTestValue = 1.4;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final l = await AppLocalizations.delegate.load(locale);
      final failed = JobStatus.fromJson({
        'job_id': 'quality-job',
        'status': 'failed',
        'progress': 100,
        'current_step': 'verify_illustrations',
        'error': {
          'code': 'IMAGE_QUALITY_FAILED',
          'message': 'private diagnostic; refund completed',
        },
        'result': _originalBook().toJson(),
      });
      expect(failed.isFailed, isTrue);
      expect(failed.isComplete, isFalse);
      final navigations = <String>[];
      await tester.pumpWidget(
        _loadingApp(locale, Stream.value(failed), navigations: navigations),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text(l.loadingImageQualityFailed), findsOneWidget);
      expect(find.textContaining('private diagnostic'), findsNothing);
      expect(find.textContaining('refund completed'), findsNothing);
      expect(find.text(l.loadingCompleted), findsNothing);
      expect(navigations, isEmpty);

      for (final label in [
        l.loadingRetryButton,
        l.loadingCheckStatusButton,
        l.loadingBackToHomeButton,
      ]) {
        final button = find.ancestor(
          of: find.text(label),
          matching:
              find.byWidgetPredicate((widget) => widget is ButtonStyleButton),
        );
        await tester.ensureVisible(button);
        await tester.pump();
        expect(tester.getSize(button).height, greaterThanOrEqualTo(64));
        expect(tester.takeException(), isNull);
      }
      await tester.ensureVisible(find.text(l.loadingRetryButton));
      await tester.pump();
      await tester.tap(find.text(l.loadingRetryButton));
      await tester.pumpAndSettle();
      expect(navigations, ['/create']);
    });
  }

  testWidgets('failed existing-page quality check keeps original book cached',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final api = _QualityFailureApi();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    var detailReads = 0;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        bookDetailProvider('original-book').overrideWith((ref) async {
          detailReads++;
          return _originalBook();
        }),
        capabilitiesProvider.overrideWith((ref) async => {
              'inpaint_supported': false,
              'audio_supported': false,
              'pod_ordering_supported': false,
              'purchases_supported': false,
            }),
      ],
      child: const MaterialApp(
        locale: Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ViewerScreen(bookId: 'original-book'),
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byIcon(Icons.chevron_right).first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text(l.viewerRegeneratePageTitle));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text(l.viewerRegenerateImageOnly));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    // The initial in-progress snackbar finishes before the error is shown.
    await tester.pump(const Duration(seconds: 5));
    await tester.pump(const Duration(milliseconds: 300));
    expect(api.regenerationCalls, 1);
    expect(detailReads, 1);
    expect(find.text('원래 본문이에요.'), findsOneWidget);
    expect(find.text(l.viewerImageQualityFailed), findsOneWidget);
    expect(find.text(l.viewerRegenerateStarted), findsNothing);
    expect(find.textContaining('private diagnostic'), findsNothing);
    expect(find.byIcon(Icons.volume_up), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 4));
  });

  testWidgets('page regeneration refreshes the book only after the job is done',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final api = _QueuedThenDoneApi();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    var detailReads = 0;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        bookDetailProvider('original-book').overrideWith((ref) async {
          detailReads++;
          return _originalBook();
        }),
        capabilitiesProvider.overrideWith((ref) async => {
              'inpaint_supported': false,
              'audio_supported': false,
              'pod_ordering_supported': false,
              'purchases_supported': false,
            }),
      ],
      child: const MaterialApp(
        locale: Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ViewerScreen(bookId: 'original-book'),
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byIcon(Icons.chevron_right).first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text(l.viewerRegeneratePageTitle));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text(l.viewerRegenerateImageOnly));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    // 큐 등록 직후에는 아직 결과가 없다 — 여기서 새로고침하면 옛 그림이 고정된다.
    expect(api.regenerationCalls, 1);
    expect(detailReads, 1);

    // 잡이 done 으로 바뀔 때까지 관측한 뒤에만 한 번 새로고침한다.
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(api.statusPolls, greaterThanOrEqualTo(3));
    expect(detailReads, 2);
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text(l.viewerRegenerateCompleted), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 4));
  });
}
