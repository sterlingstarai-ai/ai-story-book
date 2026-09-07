import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';

// F1(감사 Q1/M9): 사진 동의를 끄고 제출하는데 서버에 활성 사진 동의가 있으면, grant 는 철회와
// 동일하게 아동 사진 파생물을 즉시·불가역 파기한다. 파괴적 확인 다이얼로그가 뜨고, 취소하면
// grantConsent 가 호출되지 않아야 한다(실수 파기 방지). 배선 회귀에 대한 위젯-레벨 봉인.
class _FakeApi extends ApiClient {
  _FakeApi({required this.serverPhotos})
    : super(baseUrl: 'http://localhost', userKey: 'k', enableLogging: false);

  bool serverPhotos;
  bool grantCalled = false;
  bool lookupFails = false;

  @override
  Future<Map<String, dynamic>> getConsent() async {
    if (lookupFails) throw Exception('synthetic unavailable consent lookup');
    return {
      'photos': serverPhotos,
      'privacy': true,
      'data_processing': true,
      'revoked': false,
    };
  }

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    grantCalled = true;
    serverPhotos = photos;
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
    'unknown previous photo consent cannot trigger destructive opt-out',
    (tester) async {
      final api = _FakeApi(serverPhotos: true)..lookupFails = true;
      await tester.pumpWidget(_host(api));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckboxListTile).first);
      await tester.pump();
      await tester.tap(find.byType(ElevatedButton));
      await tester.pumpAndSettle();
      expect(api.grantCalled, isFalse);
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      expect(find.text(l.consentSaveError), findsOneWidget);
    },
  );

  testWidgets(
    'photo opt-out cleanup failure stays pending and retries before entering app',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = _FakeApi(serverPhotos: true);
      var cleanups = 0;
      final cleanup = LocalMediaCleanup(
        prefs,
        purge: () async {
          cleanups++;
          if (cleanups == 1) throw Exception('synthetic disk cleanup failure');
        },
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(api),
            sharedPreferencesProvider.overrideWithValue(prefs),
            localMediaCleanupProvider.overrideWithValue(cleanup),
          ],
          child: MaterialApp(
            locale: const Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            routes: {
              '/onboarding': (_) => const Scaffold(body: Text('app entered')),
            },
            home: const ConsentScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckboxListTile).first);
      await tester.pump();
      await tester.tap(find.byType(ElevatedButton));
      await tester.pumpAndSettle();
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      await tester.tap(find.text(l.settingsRevoke));
      await tester.pumpAndSettle();
      expect(api.serverPhotos, isFalse);
      expect(prefs.getBool(localMediaCleanupPendingKey), isTrue);
      expect(find.text(l.localMediaCleanupFailed), findsOneWidget);
      expect(find.text('app entered'), findsNothing);
      await tester.tap(find.byType(ElevatedButton));
      await tester.pumpAndSettle();
      expect(cleanups, 2);
      expect(prefs.getBool(localMediaCleanupPendingKey), isNull);
      expect(find.text('app entered'), findsOneWidget);
    },
  );

  testWidgets('사진 미동의 제출 + 서버에 활성 사진동의 → 파괴적 확인 다이얼로그, 취소 시 grant 미호출', (
    tester,
  ) async {
    final api = _FakeApi(serverPhotos: true);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();

    // 필수 항목 전체 동의는 선택 사진 동의를 켜지 않는다.
    await tester.tap(find.byType(CheckboxListTile).first);
    await tester.pumpAndSettle();
    expect(
      tester.widget<CheckboxListTile>(find.byType(CheckboxListTile).last).value,
      isFalse,
    );

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
  });
}
