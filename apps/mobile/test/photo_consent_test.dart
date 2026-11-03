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
    'granted': true,
    'photos': alreadyGranted,
    'privacy': true,
    'data_processing': true,
    'revoked': false,
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
    return {
      'granted': privacy && dataProcessing,
      'privacy': privacy,
      'data_processing': dataProcessing,
      'photos': photos,
      'revoked': false,
    };
  }
}

/// H15: getConsent가 실패(순단·429·5xx)하는 변형.
class _ThrowingApi extends _FakeApi {
  @override
  Future<Map<String, dynamic>> getConsent() async =>
      throw Exception('consent fetch failed');
}

class _UntrustedConsentApi extends _FakeApi {
  _UntrustedConsentApi(this.current, {this.acknowledgment});

  final Map<String, dynamic> current;
  final Map<String, dynamic>? acknowledgment;

  @override
  Future<Map<String, dynamic>> getConsent() async => current;

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    await super.grantConsent(
      privacy: privacy,
      photos: photos,
      dataProcessing: dataProcessing,
      consentVersion: consentVersion,
    );
    return acknowledgment ?? {};
  }
}

Widget _host(
  _FakeApi api,
  void Function(bool) onResult, {
  Locale? locale,
  double textScale = 1,
}) {
  return MaterialApp(
    locale: locale ?? const Locale('ko'),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(
        context,
      ).copyWith(textScaler: TextScaler.linear(textScale)),
      child: child!,
    ),
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
  final completeConsent = <String, dynamic>{
    'granted': true,
    'privacy': true,
    'data_processing': true,
    'photos': true,
    'revoked': false,
  };

  for (final entry in <String, Map<String, dynamic>>{
    'required consent missing': {
      ...completeConsent,
      'privacy': false,
      'granted': false,
    },
    'data processing disabled': {
      ...completeConsent,
      'data_processing': false,
      'granted': false,
    },
    'consent revoked': {...completeConsent, 'revoked': true},
    'photo state malformed': {...completeConsent, 'photos': 'true'},
    'missing revoke state': {...completeConsent}..remove('revoked'),
  }.entries) {
    testWidgets('inconsistent consent is denied: ${entry.key}', (tester) async {
      final api = _UntrustedConsentApi(entry.value);
      bool? result;
      await tester.pumpWidget(_host(api, (value) => result = value));
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
      expect(result, isFalse);
      expect(api.grantCalled, isFalse);
      expect(find.text('동의'), findsNothing);
    });
  }

  testWidgets('incomplete grant acknowledgment does not authorize photo use', (
    tester,
  ) async {
    final api = _UntrustedConsentApi(
      {...completeConsent, 'photos': false},
      acknowledgment: {...completeConsent, 'granted': false},
    );
    bool? result;
    await tester.pumpWidget(_host(api, (value) => result = value));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('동의'));
    await tester.pumpAndSettle();
    expect(api.grantCalled, isTrue);
    expect(result, isFalse);
  });

  test('사진 고지는 세 언어 모두 원본 삭제 요청과 지연 가능성을 구분한다', () async {
    const expected = {
      'ko': ['삭제를 요청', '24시간', '재시도', '개인정보처리방침'],
      'en': ['request deletion', '24 hours', 'retry', 'privacy policy'],
      'ja': ['削除するよう依頼', '24時間', '再試行', 'プライバシーポリシー'],
    };
    for (final entry in expected.entries) {
      final localization = await AppLocalizations.delegate.load(
        Locale(entry.key),
      );
      final disclosure = localization.consentPhotoDisclosure.toLowerCase();
      for (final term in entry.value) {
        expect(disclosure, contains(term.toLowerCase()), reason: entry.key);
      }
      for (final falsePromise in ['즉시 파기', 'deleted immediately', '直ちに破棄']) {
        expect(disclosure, isNot(contains(falsePromise)), reason: entry.key);
      }
    }
  });

  testWidgets('JIT 사진 동의 — PIPA 5요소 고지 + 동의 시 grantConsent(기존 필수동의 echo)', (
    tester,
  ) async {
    final api = _FakeApi(alreadyGranted: false);
    bool? result;
    await tester.pumpWidget(_host(api, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    // 5요소 고지(수령자·항목·목적·보유기간·거부권)
    expect(find.textContaining('주인공 만들기'), findsOneWidget);
    expect(find.textContaining('외부 AI 처리업체'), findsOneWidget);
    expect(find.textContaining('보유·이용기간'), findsOneWidget);
    expect(find.textContaining('거부권'), findsOneWidget);
    // 서비스 저장소 삭제 요청과 완료를 구분하고 외부 업체 조건을 따로 안내한다.
    expect(
      find.textContaining('원본은 캐릭터 승인 시 서비스 저장소에서 삭제를 요청'),
      findsOneWidget,
    );
    expect(find.textContaining('저장소 장애 등으로 지연되면 재시도'), findsOneWidget);
    expect(find.textContaining('외부 업체의 처리·보관 조건'), findsOneWidget);
    expect(find.textContaining('철회·삭제 요청 시 즉시 파기'), findsNothing);
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

  for (final entry in {'ko': '동의', 'en': 'Agree', 'ja': '同意'}.entries) {
    testWidgets('${entry.key} 사진 동의 고지는 작은 화면과 큰 글씨에서 동의 가능', (tester) async {
      tester.view.physicalSize = const Size(320, 480);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _FakeApi();
      bool? result;
      await tester.pumpWidget(
        _host(
          api,
          (value) => result = value,
          locale: Locale(entry.key),
          textScale: 1.4,
        ),
      );
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text(entry.value), findsOneWidget);
      await tester.tap(find.text(entry.value));
      await tester.pumpAndSettle();
      expect(result, isTrue);
      expect(api.grantCalled, isTrue);
      expect(tester.takeException(), isNull);
    });
  }

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

  testWidgets('H15: getConsent 실패 시 grantConsent 미호출 + false(필수 동의 파괴 차단)', (
    tester,
  ) async {
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

  testWidgets('H16: en 로캘에서 PIPA 고지·버튼이 영어로 표시(한국어 하드코딩 제거)', (tester) async {
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
