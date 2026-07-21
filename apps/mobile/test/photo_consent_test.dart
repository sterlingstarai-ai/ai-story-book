import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/core/photo_consent.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/services/api_client.dart';

/// getConsent/grantConsent만 가짜로 — JIT 사진 동의 흐름 검증용.
class _FakeApi extends ApiClient {
  _FakeApi({this.alreadyGranted = false})
      : super(baseUrl: 'http://localhost', userKey: 'k', enableLogging: false);

  final bool alreadyGranted;
  bool grantCalled = false;
  Map<String, dynamic>? grantArgs;

  @override
  Future<Map<String, dynamic>> getConsent() async => {
        'photos': alreadyGranted,
        'privacy': true,
        'data_processing': true,
      };

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    grantCalled = true;
    grantArgs = {
      'privacy': privacy,
      'photos': photos,
      'dataProcessing': dataProcessing,
    };
    return {'photos': true};
  }
}

/// H15: getConsent가 실패(순단·429·5xx)하는 변형.
class _ThrowingApi extends _FakeApi {
  @override
  Future<Map<String, dynamic>> getConsent() async =>
      throw Exception('consent fetch failed');
}

Widget _host(_FakeApi api, void Function(bool) onResult, {Locale? locale}) {
  return MaterialApp(
    locale: locale ?? const Locale('ko'),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: Builder(
        builder: (context) => ElevatedButton(
          onPressed: () async =>
              onResult(await ensurePhotoConsent(context, api)),
          child: const Text('go'),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('JIT 사진 동의 — PIPA 5요소 고지 + 동의 시 grantConsent(기존 필수동의 echo)',
      (tester) async {
    final api = _FakeApi(alreadyGranted: false);
    bool? result;
    await tester.pumpWidget(_host(api, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    // 5요소 고지(수령자·항목·목적·보유기간·거부권)
    expect(find.textContaining('주인공 만들기'), findsOneWidget);
    expect(find.textContaining('받는 곳'), findsOneWidget);
    expect(find.textContaining('보유·이용기간'), findsOneWidget);
    expect(find.textContaining('거부권'), findsOneWidget);
    // 고지-코드 정합성: 원본은 캐릭터 일관성 위해 보관·재사용되므로 '즉시 파기'는 거짓 고지였다.
    // 진실(보관 + 철회·삭제 시 파기)을 고지하고, 과거 거짓 문구가 되살아나지 않게 가드.
    expect(find.textContaining('서비스 이용 기간 동안 보관'), findsOneWidget);
    expect(find.textContaining('철회·삭제 요청 시 즉시 파기'), findsOneWidget);
    expect(find.textContaining('처리 후 원본 즉시 파기'), findsNothing);

    // 동의 → grantConsent(photos:true, 기존 privacy/data를 echo)
    await tester.tap(find.text('동의'));
    await tester.pumpAndSettle();
    expect(result, isTrue);
    expect(api.grantCalled, isTrue);
    expect(api.grantArgs!['photos'], isTrue);
    expect(api.grantArgs!['privacy'], isTrue); // 임의 위조 아니라 기존값 echo
    expect(api.grantArgs!['dataProcessing'], isTrue);
  });

  testWidgets('취소 시 동의 저장 안 함(false 반환)', (tester) async {
    final api = _FakeApi(alreadyGranted: false);
    bool? result;
    await tester.pumpWidget(_host(api, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(api.grantCalled, isFalse);
  });

  testWidgets('이미 동의했으면 다이얼로그 없이 통과', (tester) async {
    final api = _FakeApi(alreadyGranted: true);
    bool? result;
    await tester.pumpWidget(_host(api, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    expect(find.textContaining('주인공 만들기'), findsNothing); // 다이얼로그 미노출
    expect(result, isTrue);
    expect(api.grantCalled, isFalse); // 재동의 불필요
  });

  testWidgets('H15: getConsent 실패 시 grantConsent 미호출 + false(필수 동의 파괴 차단)',
      (tester) async {
    final api = _ThrowingApi();
    bool? result;
    await tester.pumpWidget(_host(api, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    // 동의 다이얼로그가 뜨지 않고, grantConsent(privacy:false...)로 필수 동의를 파괴하지 않는다.
    expect(find.textContaining('주인공 만들기'), findsNothing);
    expect(result, isFalse);
    expect(api.grantCalled, isFalse);
    // 재시도 안내 스낵바 노출
    expect(find.textContaining('다시 시도'), findsOneWidget);
  });

  testWidgets('H16: en 로캘에서 PIPA 고지·버튼이 영어로 표시(한국어 하드코딩 제거)',
      (tester) async {
    final api = _FakeApi(alreadyGranted: false);
    bool? result;
    await tester.pumpWidget(
      _host(api, (r) => result = r, locale: const Locale('en')),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    // 영어 고지·버튼
    expect(find.textContaining('Recipient'), findsOneWidget);
    expect(find.text('Agree'), findsOneWidget);
    expect(find.text('Cancel'), findsOneWidget);
    // 한국어 리터럴이 남아있지 않다.
    expect(find.textContaining('받는 곳'), findsNothing);
    expect(find.text('동의'), findsNothing);

    await tester.tap(find.text('Agree'));
    await tester.pumpAndSettle();
    expect(result, isTrue);
    expect(api.grantArgs!['privacy'], isTrue); // 기존 필수동의 echo 유지
  });
}
