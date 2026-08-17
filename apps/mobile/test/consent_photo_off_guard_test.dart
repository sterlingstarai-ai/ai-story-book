import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/services/api_client.dart';

// F1(감사 Q1/M9): 사진 동의를 끄고 제출하는데 서버에 활성 사진 동의가 있으면, grant 는 철회와
// 동일하게 아동 사진 파생물을 즉시·불가역 파기한다. 파괴적 확인 다이얼로그가 뜨고, 취소하면
// grantConsent 가 호출되지 않아야 한다(실수 파기 방지). 배선 회귀에 대한 위젯-레벨 봉인.
class _FakeApi extends ApiClient {
  _FakeApi({required this.serverPhotos})
      : super(baseUrl: 'http://localhost', userKey: 'k', enableLogging: false);

  final bool serverPhotos;
  bool grantCalled = false;

  @override
  Future<Map<String, dynamic>> getConsent() async => {
        'photos': serverPhotos,
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
    return {'photos': photos};
  }
}

Widget _host(_FakeApi api) {
  return ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api)],
    child: const MaterialApp(
      locale: Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: ConsentScreen(),
    ),
  );
}

void main() {
  testWidgets(
    '사진 미동의 제출 + 서버에 활성 사진동의 → 파괴적 확인 다이얼로그, 취소 시 grant 미호출',
    (tester) async {
      final api = _FakeApi(serverPhotos: true);
      await tester.pumpWidget(_host(api));
      await tester.pumpAndSettle();

      // 전체 동의(필수 2개 충족) → 사진만 해제 = privacy+data true, photo false.
      await tester.tap(find.byType(CheckboxListTile).first);
      await tester.pumpAndSettle();
      final photoBox = find.byType(CheckboxListTile).at(2);
      await tester.ensureVisible(photoBox);
      await tester.tap(photoBox);
      await tester.pumpAndSettle();

      // 수락 → 가드가 getConsent 조회 후 파괴적 확인을 띄운다.
      final acceptBtn = find.byType(ElevatedButton);
      await tester.ensureVisible(acceptBtn);
      await tester.tap(acceptBtn);
      await tester.pumpAndSettle();

      expect(find.textContaining('복구할 수 없'), findsOneWidget);
      expect(api.grantCalled, isFalse);

      // 취소 → grant 보류(실수 파기 방지).
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      await tester.tap(find.text(l.settingsCancel));
      await tester.pumpAndSettle();
      expect(api.grantCalled, isFalse);
    },
  );
}
