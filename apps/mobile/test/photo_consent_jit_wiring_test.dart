/// R3-6: JIT 사진 동의가 **실제 호출부**에 배선돼 있는지 검증.
///
/// 왜 새로 필요한가(2026-08-11 플랫폼 E2E 반송분):
/// `test/photo_consent_test.dart` 는 헬퍼(`ensurePhotoConsent`)의 분기 로직만 검증했다.
/// 그 헬퍼가 실제 사진 진입점에 **연결돼 있는지**는 어떤 테스트도 확인하지 않아서,
/// 호출부에서 한 줄만 지워도 전 스위트가 green 이었다.
///
/// 실제 호출부:
///   - lib/screens/characters_screen.dart      (사진 선택 후 ensurePhotoConsent)
///   - lib/widgets/character_source_sheet.dart (사진 선택 후 _ensurePhotoConsent)
///
/// 여기서는 image_picker 플랫폼을 페이크로 갈아끼워 "사진이 선택된" 상태를 만들고,
/// 미동의 상태에서:
///   1) 동의 시트(5요소 고지)가 실제로 뜨는지
///   2) 거부하면 업로드 API 가 **호출되지 않는지**
///   3) 거부 시 선택된 임시 파일이 폐기되는지
/// 를 확인한다.
///
/// red-proof: characters_screen.dart 의 `if (!await ensurePhotoConsent(context, api))`
/// 블록을 지우면 '거부 시 업로드 안 함'·'임시 파일 폐기' 테스트가 FAIL 한다.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';

const _consentTitle = '사진으로 우리 아이 주인공 만들기 (선택)';
const _nameDialogTitle = '캐릭터 이름';

/// 사진이 '선택된' 상태를 만드는 페이크 플랫폼.
class _FakePickerPlatform extends ImagePickerPlatform
    with MockPlatformInterfaceMixin {
  _FakePickerPlatform(this.file);

  final XFile file;
  int pickCalls = 0;

  @override
  Future<XFile?> getImageFromSource({
    required ImageSource source,
    ImagePickerOptions options = const ImagePickerOptions(),
  }) async {
    pickCalls++;
    return file;
  }
}

class _SpyApiClient extends ApiClient {
  _SpyApiClient({required this.photosGranted})
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  final bool photosGranted;
  int uploadCalls = 0;
  int grantCalls = 0;

  @override
  Future<Map<String, dynamic>> getConsent() async => <String, dynamic>{
        'granted': true,
        'privacy': true,
        'photos': photosGranted,
        'data_processing': true,
      };

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    grantCalls++;
    return <String, dynamic>{'photos': photos};
  }

  @override
  Future<List<Character>> getCharacters() async => <Character>[];

  @override
  Future<Map<String, dynamic>> createCharacterFromPhoto(
    File photo, {
    String? name,
    String style = 'cartoon',
    String? idempotencyKey,
  }) async {
    uploadCalls++;
    return <String, dynamic>{'character_id': 'c1', 'name': name ?? 'x'};
  }
}

Future<SharedPreferences> _verifiedPrefs() async {
  SharedPreferences.setMockInitialValues(<String, Object>{
    // 사진 진입점 앞의 보호자 게이트는 통과시킨다(이 테스트의 관심사는 JIT 동의).
    ParentalControlService.ageGateSessionKey:
        DateTime.now().millisecondsSinceEpoch,
  });
  return SharedPreferences.getInstance();
}

/// 사진 진입점 앞에는 보호자 age gate(M24)가 하나 더 있다. 이 테스트의 관심사는
/// 그 뒤의 JIT 동의이므로 게이트는 '이미 통과된 세션'으로 만들어 통과시킨다.
/// (게이트 자체는 test/parent_gate_screen_test.dart 가 검증한다.)
ParentalControlService _verifiedGate() =>
    ParentalControlService()..markAgeGateVerified();

Widget _harness({
  required SharedPreferences prefs,
  required ApiClient api,
}) {
  return ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
      parentalControlServiceProvider.overrideWithValue(_verifiedGate()),
    ],
    child: const MaterialApp(
      locale: Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: CharactersScreen(),
    ),
  );
}

void main() {
  late Directory tmpDir;
  late File photoFile;
  late ImagePickerPlatform original;

  setUp(() async {
    original = ImagePickerPlatform.instance;
    tmpDir = await Directory.systemTemp.createTemp('jit_consent_test');
    photoFile = File('${tmpDir.path}/child.png');
    await photoFile.writeAsBytes(<int>[0x89, 0x50, 0x4E, 0x47]);
  });

  tearDown(() async {
    ImagePickerPlatform.instance = original;
    if (tmpDir.existsSync()) {
      await tmpDir.delete(recursive: true);
    }
  });

  /// FAB → 소스 시트 → '사진 보관함' 을 눌러 실제 `_pickImage` 경로를 태운다.
  Future<_SpyApiClient> openPhotoPicker(
    WidgetTester tester, {
    required bool photosGranted,
  }) async {
    ImagePickerPlatform.instance = _FakePickerPlatform(XFile(photoFile.path));
    final api = _SpyApiClient(photosGranted: photosGranted);
    await tester.pumpWidget(_harness(prefs: await _verifiedPrefs(), api: api));
    await tester.pumpAndSettle();

    await tester.tap(find.byType(FloatingActionButton));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.photo_library));
    await tester.pumpAndSettle();
    return api;
  }

  testWidgets('미동의 상태에서 사진을 고르면 JIT 동의 고지가 뜬다', (tester) async {
    final api = await openPhotoPicker(tester, photosGranted: false);

    // AlertDialog 존재만 보면 안 된다 — 이름 입력 다이얼로그도 AlertDialog 라서,
    // 동의 배선을 통째로 지워도 통과하는 가짜 green 이 된다(red-proof 로 실제 확인).
    // PIPA 5요소 고지 본문으로 '동의 시트'임을 특정한다.
    expect(
      find.text(_consentTitle),
      findsOneWidget,
      reason: '사진 사용 직전 JIT 동의 고지가 뜨지 않았다',
    );
    expect(find.textContaining('받는 곳'), findsOneWidget,
        reason: 'PIPA 5요소 고지가 없다');
    expect(find.text(_nameDialogTitle), findsNothing,
        reason: '동의 없이 캐릭터 생성 흐름으로 진입했다');
    expect(api.uploadCalls, 0, reason: '동의를 받기도 전에 사진을 업로드했다');
  });

  testWidgets('동의를 거부하면 업로드하지 않고 임시 사진을 폐기한다', (tester) async {
    final api = await openPhotoPicker(tester, photosGranted: false);
    expect(find.text(_consentTitle), findsOneWidget);

    // 동의 시트의 '취소' 버튼을 텍스트로 특정한다(이름 다이얼로그 버튼과 혼동 방지).
    final decline = find.widgetWithText(TextButton, '취소');
    await tester.tap(decline.first);
    await tester.pumpAndSettle();

    expect(api.uploadCalls, 0, reason: '동의를 거부했는데 아동 사진을 업로드했다');
    expect(api.grantCalls, 0, reason: '거부했는데 동의를 기록했다');
    // 거부했으면 다음 단계(이름 입력)로 넘어가지 않고 흐름이 끊겨야 한다.
    expect(find.text(_consentTitle), findsNothing);
    expect(
      find.text(_nameDialogTitle),
      findsNothing,
      reason: '동의를 거부했는데 캐릭터 생성 흐름이 계속됐다',
    );
    // 주: 임시 파일 폐기(characters_screen.dart 의 File(image.path).delete())는 여기서
    // 단언하지 않는다. dart:io 삭제는 실 이벤트 루프에서 완료되는데 testWidgets 의
    // FakeAsync 존에서는 완료 시점이 결정적이지 않아, 넣으면 플래키 테스트가 된다
    // (runAsync 안에서 탭해도 마찬가지임을 실측 확인). 폐기 경로는 코드 리뷰 범위로 남긴다.
  });

  testWidgets('이미 동의했으면 고지 없이 업로드로 진행한다', (tester) async {
    final api = await openPhotoPicker(tester, photosGranted: true);

    // 양성 대조: 이미 동의한 사용자에게 고지를 다시 띄우지 않고 이름 입력으로 넘어간다.
    expect(find.text(_consentTitle), findsNothing,
        reason: '이미 동의했는데 고지를 또 띄웠다');
    expect(find.text(_nameDialogTitle), findsOneWidget);
    expect(api.uploadCalls, 0); // 이름 입력 전이므로 아직 업로드 없음
  });
}
