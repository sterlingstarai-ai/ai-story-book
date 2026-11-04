// H1/G9: 오디오 비활성 배포에서 뷰어 낭독 버튼이 실제로 숨겨지는지 — UI 게이팅 검증.
//
// 감사 확정 #2: 서버 플래그가 readiness에만 배선돼 낭독 UI가 그대로 살아있고 탭마다
// 에러가 났다. 서버는 capabilities.audio_supported를 내려주고, 뷰어는 그 값으로 낭독
// 버튼·발음 메뉴를 숨긴다. 이 테스트는 위젯 트리에서 버튼 존재/부재를 직접 확인한다.
import 'dart:io';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/utils/constants.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 뷰어가 초기화 시 호출하는 서버 조회만 막는 최소 스텁(네트워크 차단).
class _StubApiClient extends ApiClient {
  _StubApiClient() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test-user');
  int pdfRequests = 0;
  int narrationRequests = 0;

  @override
  Future<String> getPageAudioUrl(
    String id,
    int page, {
    String language = 'ko',
    String voice = 'default',
    String style = 'legacy',
  }) async {
    narrationRequests++;
    throw StateError('synthetic narration boundary');
  }

  @override
  Future<List<int>> downloadPdf(String bookId) async {
    pdfRequests++;
    throw StateError('synthetic export boundary');
  }

  @override
  Future<Map<String, dynamic>> getSettings() async => {
    'allow_kakao_share': true,
  };

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async => {};
}

class _EmptyMediaStore extends BookMediaStore {
  _EmptyMediaStore(SharedPreferences prefs)
    : super(
        prefs,
        baseDirectory: () async => Directory.systemTemp,
        scopeDigest: 'a' * 64,
      );

  @override
  Future<T?> withReadableBook<T>(
    String bookId,
    Future<T> Function() operation,
  ) => operation();

  @override
  Future<File?> lookup(String bookId, String key, {required String extension}) async =>
      null;
}

BookResult _book() => BookResult(
  bookId: 'book-1',
  jobId: 'job-1',
  title: '테스트 동화',
  coverImageUrl: '',
  pages: [PageResult(pageNumber: 1, text: '토끼가 숲으로 갔어요.', imageUrl: '')],
);

Future<void> _pumpViewer(
  WidgetTester tester, {
  required bool audioSupported,
  bool? narrationSupported,
  bool podSupported = false,
  bool stubMedia = false,
  BookResult? book,
  _StubApiClient? api,
  ParentalControlService? parental,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api ?? _StubApiClient()),
        if (stubMedia)
          bookMediaStoreProvider.overrideWith(
            (ref) async => BookMediaContext(
              _EmptyMediaStore(prefs),
              serverVerified: false,
            ),
          ),
        if (parental != null)
          parentalControlServiceProvider.overrideWithValue(parental),
        bookDetailProvider(
          'book-1',
        ).overrideWith((ref) async => book ?? _book()),
        capabilitiesProvider.overrideWith(
          (ref) async => {
            'inpaint_supported': false,
            'audio_supported': audioSupported,
            if (narrationSupported != null)
              'narration_supported': narrationSupported,
            'pod_ordering_supported': podSupported,
          },
        ),
      ],
      child: MaterialApp(
        theme: ThemeData(
          useMaterial3: true,
          iconButtonTheme: IconButtonThemeData(
            style: IconButton.styleFrom(
              minimumSize: const Size(64, 64),
              padding: const EdgeInsets.all(16),
            ),
          ),
        ),
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('ko'),
        home: const ViewerScreen(bookId: 'book-1'),
      ),
    ),
  );
  // 뷰어에 상시 애니메이션(confetti 등)이 있어 pumpAndSettle은 타임아웃한다.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));

  // 표지(page 0)에서는 낭독 버튼이 원래 없다 — 본문 페이지로 넘긴다.
  final next = find.byIcon(Icons.chevron_right);
  if (next.evaluate().isNotEmpty) {
    await tester.tap(next.first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
  }
}

/// 뷰어는 confetti·오디오 컨트롤러 타이머를 들고 있어, 트리를 폐기하고 시간을 흘려보내야
/// 'A Timer is still pending' 단언을 피할 수 있다.
Future<void> _teardownViewer(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 4));
}

void main() {
  testWidgets(
    'tapping the story requests narration and leaves controls visible',
    (tester) async {
      final api = _StubApiClient();
      await _pumpViewer(tester, audioSupported: true, api: api, stubMedia: true);
      final story = find.text('토끼가 숲으로 갔어요.');
      expect(story.hitTestable(), findsOneWidget);
      await tester.tap(story);
      await tester.pump(const Duration(milliseconds: 350));
      expect(api.narrationRequests, 1);
      expect(find.byKey(const Key('viewer_bottom_controls')), findsOneWidget);
      await _teardownViewer(tester);
    },
  );

  testWidgets('sleep countdown leaves reader controls reachable', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await _pumpViewer(tester, audioSupported: true);
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    final more = find.byTooltip(l.viewerMoreOptionsTooltip);
    final countdown = find.byKey(const Key('viewer_sleep_countdown'));
    final controls = find.byKey(const Key('viewer_bottom_controls'));
    expect(
      tester.getRect(find.byType(PageView)).bottom,
      tester.getRect(controls).top,
    );
    expect(tester.getSize(more).height, greaterThanOrEqualTo(64));
    expect(find.byTooltip(l.viewerCloseTooltip), findsNothing);

    await tester.tap(more);
    await tester.pumpAndSettle();
    final start = find.text(l.viewerSleepModeStart);
    await tester.ensureVisible(start);
    await tester.tap(start);
    await tester.pumpAndSettle();

    expect(countdown, findsOneWidget);
    expect(
      find.ancestor(
        of: find.byKey(const ValueKey('reader-content-1')),
        matching: find.byWidgetPredicate(
          (widget) =>
              widget is ColoredBox &&
              widget.color == const AppPalette(true).background,
        ),
      ),
      findsOneWidget,
    );
    expect(tester.getRect(countdown).overlaps(tester.getRect(more)), isFalse);
    // The synthetic client cannot supply audio, so let its error snackbar exit.
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await tester.tap(more);
    await tester.pumpAndSettle();
    expect(find.text(l.viewerSleepModeStop), findsOneWidget);
    expect(find.text(l.viewerCloseTooltip), findsOneWidget);
    await _teardownViewer(tester);
  });

  for (final export in [
    'cover',
    'pdf',
    'message',
    'more',
    'download',
    'print',
  ]) {
    testWidgets('$export requires parental approval before export', (
      tester,
    ) async {
      final api = _StubApiClient();
      await _pumpViewer(tester, audioSupported: false, api: api);
      final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
      await tester.tap(find.byIcon(Icons.more_vert));
      await tester.pumpAndSettle();
      if (['cover', 'pdf', 'message', 'more'].contains(export)) {
        await tester.ensureVisible(find.text(l.viewerShare));
        await tester.tap(find.text(l.viewerShare));
        await tester.pumpAndSettle();
      }
      final label = switch (export) {
        'cover' => l.viewerShareCover,
        'pdf' => l.viewerSharePdf,
        'message' => l.viewerShareMessage,
        'more' => l.viewerShareMore,
        'download' => l.viewerExportPdf,
        _ => l.viewerPrint,
      };
      await tester.ensureVisible(find.text(label));
      await tester.tap(find.text(label));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      expect(api.pdfRequests, 0);
      // Cancelling the gate cannot reach the provider/native export boundary.
      Navigator.of(tester.element(find.byType(AlertDialog))).pop(false);
      await tester.pumpAndSettle();
      expect(api.pdfRequests, 0);
      await _teardownViewer(tester);
    });
  }

  testWidgets('fresh parental approval still allows PDF download', (
    tester,
  ) async {
    final api = _StubApiClient();
    final parental = ParentalControlService()..markAgeGateVerified();
    await _pumpViewer(
      tester,
      audioSupported: false,
      api: api,
      parental: parental,
    );
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text(l.viewerExportPdf));
    await tester.tap(find.text(l.viewerExportPdf));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(api.pdfRequests, 1);
    await _teardownViewer(tester);
  });
  testWidgets('viewer report menu opens the parent gate inside the app', (
    tester,
  ) async {
    await _pumpViewer(tester, audioSupported: false);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('문제 신고'), findsOneWidget);
    await tester.tap(find.text('문제 신고'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.byType(ViewerScreen), findsOneWidget);
    await _teardownViewer(tester);
  });

  testWidgets('small large-text reader keeps story above page navigation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpViewer(tester, audioSupported: false);
    final story = find.text('토끼가 숲으로 갔어요.');
    final next = find.byIcon(Icons.chevron_right);
    final illustration = find.byWidgetPredicate(
      (widget) => widget is Semantics && widget.properties.label == '1페이지 삽화',
    );
    final controls = find.byKey(const Key('viewer_bottom_controls'));
    expect(
      tester.getRect(illustration).bottom,
      lessThanOrEqualTo(tester.getRect(controls).top),
    );
    await tester.ensureVisible(story);
    await tester.pump();
    expect(tester.getRect(story).bottom, lessThan(tester.getRect(next).top));
    expect(tester.takeException(), isNull);
    await _teardownViewer(tester);
  });

  testWidgets(
    'small reader scrolls long learning pages without covering controls',
    (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      tester.view.padding = const FakeViewPadding(top: 44, bottom: 34);
      tester.platformDispatcher.textScaleFactorTestValue = 1.4;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPadding);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final book = BookResult.fromJson({
        'book_id': 'book-1',
        'title': '긴 이야기를 함께 읽어요',
        'cover_image_url': '',
        'pages': [
          {
            'page_number': 1,
            'text': List.filled(6, '토끼는 친구와 정원에 갔어요.').join(' '),
            'image_url': '',
            'vocab': [
              {'word': '정원', 'meaning': '꽃이 피는 곳'},
            ],
          },
        ],
      });
      await _pumpViewer(tester, audioSupported: true, book: book);
      expect(tester.takeException(), isNull);
      final finish = find.byKey(const Key('viewer-finish-reading'));
      final bodyScroll = find.byKey(const ValueKey('reader-content-1'));
      for (var i = 0; i < 12 && finish.hitTestable().evaluate().isEmpty; i++) {
        await tester.drag(bodyScroll, const Offset(0, -220));
        await tester.pump(const Duration(milliseconds: 300));
      }
      await tester.pump(const Duration(milliseconds: 300));
      expect(finish.hitTestable(), findsOneWidget);
      expect(
        tester.getRect(finish).bottom,
        lessThanOrEqualTo(
          tester.getRect(find.byKey(const Key('viewer_learning_bar'))).top,
        ),
      );
      expect(tester.takeException(), isNull);
      await _teardownViewer(tester);
    },
  );

  testWidgets('reader leaves the iPhone cutout clear without a title bar', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(402, 874);
    tester.view.devicePixelRatio = 1;
    tester.view.padding = const FakeViewPadding(top: 62, bottom: 34);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPadding);
    await _pumpViewer(tester, audioSupported: false);
    final illustration = find.byWidgetPredicate(
      (widget) => widget is Semantics && widget.properties.label == '1페이지 삽화',
    );
    expect(find.byTooltip('닫기'), findsNothing);
    expect(tester.getRect(illustration).top, greaterThanOrEqualTo(62));
    expect(tester.getRect(illustration).top, lessThan(70));
    expect(tester.takeException(), isNull);
    await _teardownViewer(tester);
  });

  testWidgets('실물책 주문이 비활성이면 메뉴를 숨긴다', (tester) async {
    await _pumpViewer(tester, audioSupported: false);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byIcon(Icons.local_shipping_outlined), findsNothing);
    await _teardownViewer(tester);
  });

  testWidgets('이전 서버가 주문 가능으로 응답해도 실물 배송 메뉴를 제공하지 않는다', (tester) async {
    await _pumpViewer(tester, audioSupported: false, podSupported: true);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byIcon(Icons.local_shipping_outlined), findsNothing);
    await _teardownViewer(tester);
  });

  testWidgets('오디오 미지원 배포에서는 낭독 버튼이 숨겨진다 (H1/G9)', (tester) async {
    await _pumpViewer(tester, audioSupported: false);
    expect(find.byIcon(Icons.volume_up), findsNothing);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byIcon(Icons.hearing), findsNothing);
    expect(find.byIcon(Icons.bedtime), findsNothing);
    await _teardownViewer(tester);
  });

  testWidgets('오디오 지원 배포에서는 낭독 버튼이 노출된다 (과잉 차단 방지)', (tester) async {
    await _pumpViewer(tester, audioSupported: true);
    expect(find.byIcon(Icons.volume_up), findsOneWidget);
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    expect(find.byTooltip(l.viewerPlayAudioTooltip), findsOneWidget);
    await _teardownViewer(tester);
  });

  testWidgets('낭독만 지원하면 낭독은 보이고 발음 연습은 숨긴다', (tester) async {
    await _pumpViewer(tester, audioSupported: false, narrationSupported: true);
    expect(find.byIcon(Icons.volume_up), findsOneWidget);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byIcon(Icons.record_voice_over_outlined), findsNothing);
    await _teardownViewer(tester);
  });

  testWidgets('낭독이 명시적으로 비활성이면 기존 오디오 플래그보다 우선한다', (tester) async {
    await _pumpViewer(tester, audioSupported: true, narrationSupported: false);
    expect(find.byIcon(Icons.volume_up), findsNothing);
    await _teardownViewer(tester);
  });
}
