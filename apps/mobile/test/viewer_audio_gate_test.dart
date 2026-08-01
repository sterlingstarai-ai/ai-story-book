// H1/G9: 오디오 비활성 배포에서 뷰어 낭독 버튼이 실제로 숨겨지는지 — UI 게이팅 검증.
//
// 감사 확정 #2: 서버 플래그가 readiness에만 배선돼 낭독 UI가 그대로 살아있고 탭마다
// 에러가 났다. 서버는 capabilities.audio_supported를 내려주고, 뷰어는 그 값으로 낭독
// 버튼·발음 메뉴를 숨긴다. 이 테스트는 위젯 트리에서 버튼 존재/부재를 직접 확인한다.
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 뷰어가 초기화 시 호출하는 서버 조회만 막는 최소 스텁(네트워크 차단).
class _StubApiClient extends ApiClient {
  _StubApiClient() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test-user');

  @override
  Future<Map<String, dynamic>> getSettings() async => {'allow_kakao_share': true};
}

BookResult _book() => BookResult(
      bookId: 'book-1',
      jobId: 'job-1',
      title: '테스트 동화',
      coverImageUrl: '',
      pages: [
        PageResult(
          pageNumber: 1,
          text: '토끼가 숲으로 갔어요.',
          imageUrl: '',
        ),
      ],
    );

Future<void> _pumpViewer(
  WidgetTester tester, {
  required bool audioSupported,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(_StubApiClient()),
        bookDetailProvider('book-1').overrideWith((ref) async => _book()),
        capabilitiesProvider.overrideWith((ref) async => {
              'inpaint_supported': false,
              'audio_supported': audioSupported,
            }),
      ],
      child: const MaterialApp(
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: AppLocalizations.supportedLocales,
        locale: Locale('ko'),
        home: ViewerScreen(bookId: 'book-1'),
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
  testWidgets('오디오 미지원 배포에서는 낭독 버튼이 숨겨진다 (H1/G9)', (tester) async {
    await _pumpViewer(tester, audioSupported: false);
    expect(find.byIcon(Icons.volume_up), findsNothing);
    await _teardownViewer(tester);
  });

  testWidgets('오디오 지원 배포에서는 낭독 버튼이 노출된다 (과잉 차단 방지)', (tester) async {
    await _pumpViewer(tester, audioSupported: true);
    expect(find.byIcon(Icons.volume_up), findsOneWidget);
    await _teardownViewer(tester);
  });
}
