import 'dart:io';
import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/providers/active_child_profile.dart';
import 'package:ai_story_book/models/book_spec.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/services/selected_photo_cache.dart';
import 'package:ai_story_book/services/photo_upload_fingerprint.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_avatar_preview.dart';
import 'package:ai_story_book/widgets/character_source_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'character_avatar_flow_test.dart' show avatar, avatarJson;

class _Picker extends ImagePickerPlatform with MockPlatformInterfaceMixin {
  var image = XFile('/picker-cache/selected.png');
  Completer<XFile?>? pending;
  @override
  Future<XFile?> getImageFromSource({
    required ImageSource source,
    ImagePickerOptions options = const ImagePickerOptions(),
  }) async => pending == null ? image : await pending!.future;
}

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://test', userKey: 'user', enableLogging: false);
  bool photos = true, fail = false;
  int uploads = 0, drawings = 0;
  final uploadKeys = <String?>[];
  final uploadNames = <String?>[], drawingNames = <String?>[];
  @override
  Future<List<Character>> getCharacters() async => [];
  @override
  Future<Character> getCharacter(String id) async =>
      avatar(status: 'generating', url: null);
  @override
  Future<Map<String, dynamic>> getConsent() async => {
    'photos': photos,
    'privacy': true,
    'data_processing': true,
    'granted': true,
  };
  @override
  Future<Map<String, dynamic>> createCharacterFromPhoto(
    File photo, {
    String? name,
    String style = 'cartoon',
    String? idempotencyKey,
  }) async {
    uploads++;
    uploadKeys.add(idempotencyKey);
    uploadNames.add(name);
    if (fail) throw StateError('upload failed');
    return avatarJson(status: 'generating', url: null);
  }

  @override
  Future<Map<String, dynamic>> createCharacterFromDrawing(
    File drawing, {
    String? name,
    String style = 'cartoon',
    bool generateSheet = true,
    String? idempotencyKey,
  }) async {
    drawings++;
    drawingNames.add(name);
    if (fail) throw StateError('upload failed');
    return avatarJson(status: 'generating', url: null);
  }
}

void main() {
  late ImagePickerPlatform old;
  late _Picker picker;
  setUp(() {
    old = ImagePickerPlatform.instance;
    picker = _Picker();
    ImagePickerPlatform.instance = picker;
  });
  tearDown(() => ImagePickerPlatform.instance = old);
  Future<void> open(
    WidgetTester tester,
    _Api api,
    List<String> removed, {
    required bool source,
    bool drawing = false,
    ActiveChildProfile? profile,
  }) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          activeChildProfileProvider.overrideWith((ref) async => profile),
          apiClientProvider.overrideWithValue(api),
          parentalControlServiceProvider.overrideWithValue(
            ParentalControlService()..markAgeGateVerified(),
          ),
          selectedPhotoCacheCleanerProvider.overrideWithValue((image) async {
            if (image != null) removed.add(image.path);
          }),
          // These picker paths represent the same selected synthetic photo.
          photoUploadFingerprintProvider.overrideWithValue(
            (image) async => image.path.contains('different-photo')
                ? 'different-photo-bytes'
                : 'same-photo-bytes',
          ),
          characterPresetsProvider('ko').overrideWith((ref) async => []),
        ],
        child: MaterialApp(
          locale: const Locale('ko'),
          theme: buildAppTheme(Brightness.light),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: source
              ? const Scaffold(body: CharacterSourceSheet())
              : const CharactersScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    if (source) {
      await tester.tap(find.text('갤러리'));
    } else {
      final l = AppLocalizations.of(
        tester.element(find.byType(CharactersScreen)),
      );
      await tester.tap(
        find.widgetWithText(ElevatedButton, l.charactersEmptyCreateButton),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byIcon(drawing ? Icons.brush_outlined : Icons.photo_library),
      );
    }
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  for (final source in [false, true]) {
    testWidgets(
      '${source ? 'source sheet' : 'characters'} retry of same photo with new cache path keeps upload key',
      (tester) async {
        final api = _Api()..fail = true;
        final removed = <String>[];
        await open(tester, api, removed, source: source);
        if (!source) {
          await tester.enterText(find.byType(TextField), '시우');
          await tester.tap(find.widgetWithText(TextButton, '확인'));
        }
        await tester.pumpAndSettle();
        expect(api.uploads, 1);
        picker.image = XFile('/picker-cache/same-photo-selected-again.png');
        if (source) {
          await tester.tap(find.text('갤러리'));
        } else {
          final l = AppLocalizations.of(
            tester.element(find.byType(CharactersScreen)),
          );
          await tester.tap(
            find.widgetWithText(ElevatedButton, l.charactersEmptyCreateButton),
          );
          await tester.pumpAndSettle();
          await tester.tap(find.byIcon(Icons.photo_library));
          await tester.pumpAndSettle();
          await tester.enterText(find.byType(TextField), '시우');
          await tester.tap(find.widgetWithText(TextButton, '확인'));
        }
        await tester.pumpAndSettle();
        expect(api.uploads, 2);
        expect(api.uploadKeys[0], isNotNull);
        expect(
          api.uploadKeys[1],
          api.uploadKeys[0],
          reason:
              'A new picker cache filename must not create a second paid operation after an uncertain upload.',
        );
        picker.image = XFile('/picker-cache/different-photo.png');
        if (source) {
          await tester.tap(find.text('갤러리'));
        } else {
          final l = AppLocalizations.of(
            tester.element(find.byType(CharactersScreen)),
          );
          await tester.tap(
            find.widgetWithText(ElevatedButton, l.charactersEmptyCreateButton),
          );
          await tester.pumpAndSettle();
          await tester.tap(find.byIcon(Icons.photo_library));
          await tester.pumpAndSettle();
          await tester.enterText(find.byType(TextField), '시우');
          await tester.tap(find.widgetWithText(TextButton, '확인'));
        }
        await tester.pumpAndSettle();
        expect(api.uploads, 3);
        expect(
          api.uploadKeys[2],
          isNot(api.uploadKeys[1]),
          reason: 'A different photo must remain a new upload attempt.',
        );
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
      },
    );
    testWidgets(
      '${source ? 'source sheet' : 'characters'} decline cleans cache without upload',
      (tester) async {
        final api = _Api()..photos = false;
        final removed = <String>[];
        await open(tester, api, removed, source: source);
        expect(find.text('사진으로 우리 아이 주인공 만들기 (선택)'), findsOneWidget);
        await tester.tap(find.widgetWithText(TextButton, '취소').first);
        await tester.pumpAndSettle();
        expect(api.uploads, 0);
        expect(removed, contains(picker.image.path));
      },
    );
    for (final fail in [false, true]) {
      testWidgets(
        '${source ? 'source sheet' : 'characters'} upload ${fail ? 'failure' : 'success'} cleans cache',
        (tester) async {
          final api = _Api()..fail = fail;
          final removed = <String>[];
          await open(tester, api, removed, source: source);
          if (!source) {
            await tester.enterText(find.byType(TextField), '시우');
            await tester.tap(find.widgetWithText(TextButton, '확인'));
            await tester.pump();
            await tester.pump(const Duration(milliseconds: 400));
          }
          expect(api.uploads, 1);
          expect(removed, contains(picker.image.path));
          expect(
            find.byType(CharacterAvatarPreviewScreen),
            fail ? findsNothing : findsOneWidget,
          );
          await tester.pumpWidget(const SizedBox());
          await tester.pump();
        },
      );
    }
    testWidgets(
      '${source ? 'source sheet' : 'characters'} leaving while picker returns cleans selection',
      (tester) async {
        picker.pending = Completer<XFile?>();
        final api = _Api();
        final removed = <String>[];
        await open(tester, api, removed, source: source);
        await tester.pumpWidget(const SizedBox());
        picker.pending!.complete(picker.image);
        await tester.pump();
        expect(api.uploads, 0);
        expect(removed, contains(picker.image.path));
      },
    );
  }
  testWidgets('name cancellation cleans selected cache without uploading', (
    tester,
  ) async {
    final api = _Api();
    final removed = <String>[];
    await open(tester, api, removed, source: false);
    await tester.tap(find.widgetWithText(TextButton, '취소'));
    await tester.pumpAndSettle();
    expect(api.uploads, 0);
    expect(removed, contains(picker.image.path));
  });
  for (final enteredName in <String?>[null, '다른 이름', '', 'cancel']) {
    testWidgets(
      'photo name defaults to active child and accepts $enteredName',
      (tester) async {
        final api = _Api();
        final removed = <String>[];
        await open(
          tester,
          api,
          removed,
          source: false,
          profile: const ActiveChildProfile(
            id: 'child',
            name: '토리',
            targetAge: TargetAge.age7to9,
          ),
        );
        expect(
          tester.widget<TextField>(find.byType(TextField)).controller?.text,
          '토리',
        );
        if (enteredName != null && enteredName != 'cancel') {
          await tester.enterText(find.byType(TextField), enteredName);
        }
        await tester.tap(
          find.widgetWithText(
            TextButton,
            enteredName == 'cancel' ? '취소' : '확인',
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
        expect(
          api.uploadNames,
          enteredName == 'cancel'
              ? []
              : [enteredName == '' ? null : enteredName ?? '토리'],
        );
        expect(removed, contains(picker.image.path));
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
      },
    );
  }
  for (final drawing in [false, true]) {
    for (final name in ['', '   ']) {
      testWidgets(
        '${drawing ? 'drawing' : 'photo'} empty optional name confirmation (${name.isEmpty ? 'blank' : 'spaces'}) uploads without a name',
        (tester) async {
          final api = _Api();
          final removed = <String>[];
          await open(tester, api, removed, source: false, drawing: drawing);
          if (name.isNotEmpty) {
            await tester.enterText(find.byType(TextField), name);
          }
          await tester.tap(find.widgetWithText(TextButton, '확인'));
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 400));
          expect(drawing ? api.drawings : api.uploads, 1);
          expect(drawing ? api.drawingNames : api.uploadNames, [null]);
          expect(removed, contains(picker.image.path));
          expect(find.byType(CharacterAvatarPreviewScreen), findsOneWidget);
          await tester.pumpWidget(const SizedBox());
          await tester.pump();
        },
      );
    }
  }
  testWidgets(
    'drawing upload enters the same one-avatar confirmation and cleans selection',
    (tester) async {
      final api = _Api();
      final removed = <String>[];
      await open(tester, api, removed, source: false, drawing: true);
      await tester.enterText(find.byType(TextField), '시우');
      await tester.tap(find.widgetWithText(TextButton, '확인'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(api.drawings, 1);
      expect(api.uploads, 0);
      expect(removed, contains(picker.image.path));
      expect(find.byType(CharacterAvatarPreviewScreen), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
}
