import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/core/photo_consent.dart';
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

Widget _host(_FakeApi api, void Function(bool) onResult) {
  return MaterialApp(
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
    expect(find.text('사진으로 우리 아이 주인공 만들기'), findsOneWidget);
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

    expect(find.text('사진으로 우리 아이 주인공 만들기'), findsNothing); // 다이얼로그 미노출
    expect(result, isTrue);
    expect(api.grantCalled, isFalse); // 재동의 불필요
  });
}
