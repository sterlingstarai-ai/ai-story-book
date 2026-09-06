import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/services/selected_photo_cache.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_avatar_preview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> avatarJson(
        {String status = 'preview',
        int version = 1,
        bool photo = true,
        bool retry = true,
        String? url = 'https://example.test/avatar.png'}) =>
    {
      'character_id': 'avatar-1',
      'name': '시우',
      'master_description': '동화 속 주인공',
      'appearance': {
        'age_visual': '8',
        'face': 'round',
        'hair': 'black',
        'skin': 'warm',
        'body': 'child'
      },
      'clothing': {
        'top': 'blue',
        'bottom': 'yellow',
        'shoes': 'green',
        'accessories': 'none'
      },
      'personality_traits': ['curious'],
      'created_at': '2026-09-06T00:00:00Z',
      'from_photo': photo,
      'avatar_status': status,
      'avatar_url': url,
      'avatar_version': version,
      'avatar_retry_allowed': retry,
    };
Character avatar(
        {String status = 'preview',
        int version = 1,
        bool retry = true,
        String? url = 'https://example.test/avatar.png'}) =>
    Character.fromJson(
        avatarJson(status: status, version: version, retry: retry, url: url));

class AvatarApi extends ApiClient {
  AvatarApi(this.current)
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);
  Character current;
  int gets = 0;
  final approvals = <int>[];
  final regenerations = <int>[];
  Future<Character> Function()? read;
  Future<Character> Function(int)? approve;
  @override
  Future<Character> getCharacter(String id) async {
    gets++;
    return read == null ? current : await read!();
  }

  @override
  Future<List<Character>> getCharacters() async => [current];
  @override
  Future<Character> approveCharacterAvatar(String id,
      {required int version}) async {
    approvals.add(version);
    if (approve != null) return approve!(version);
    return current = avatar(status: 'approved', version: version, retry: false);
  }

  @override
  Future<Character> regenerateCharacterAvatar(String id,
      {required int version}) async {
    regenerations.add(version);
    return current =
        avatar(status: 'generating', version: version + 1, url: null);
  }
}

final _pixel = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGOYkHDgPwAF5AKwILSPKwAAAABJRU5ErkJggg==');
const _approve = ValueKey('character-avatar-approve');

Future<void> openPreview(
  WidgetTester tester,
  AvatarApi api, {
  Size size = const Size(402, 874),
  double scale = 1,
  Brightness brightness = Brightness.light,
  bool verified = true,
  bool brokenImage = false,
  CharacterAvatarPollPolicy policy = const CharacterAvatarPollPolicy(),
  ValueChanged<CharacterAvatarPreviewResult?>? onResult,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final gate = ParentalControlService();
  if (verified) gate.markAgeGateVerified();
  await tester.pumpWidget(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        parentalControlServiceProvider.overrideWithValue(gate),
        characterAvatarPollPolicyProvider.overrideWithValue(policy),
      ],
      child: MaterialApp(
          locale: const Locale('ko'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          theme: buildAppTheme(brightness),
          builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context)
                  .copyWith(textScaler: TextScaler.linear(scale)),
              child: child!),
          home: Builder(
              builder: (context) => Scaffold(
                  body: TextButton(
                      onPressed: () async {
                        final result = await Navigator.push<
                                CharacterAvatarPreviewResult>(
                            context,
                            MaterialPageRoute(
                                builder: (_) => CharacterAvatarPreviewScreen(
                                    characterId: api.current.id,
                                    initialCharacter: api.current,
                                    imageProviderBuilder: (_) => MemoryImage(
                                        brokenImage
                                            ? base64Decode('aW52YWxpZA==')
                                            : _pixel))));
                        onResult?.call(result);
                      },
                      child: const Text('open')))))));
  await tester.tap(find.text('open'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 350));
  await tester.runAsync(
      () async => Future<void>.delayed(const Duration(milliseconds: 30)));
  await tester.pump();
  await tester.pump();
}

Future<void> reach(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(target, 180,
      scrollable: find.byType(Scrollable).last);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
  expect(target.hitTestable(), findsOneWidget);
}

void main() {
  group('avatar contract model', () {
    test('legacy manual characters stay usable, legacy photos fail closed', () {
      final json = avatarJson()
        ..remove('avatar_status')
        ..remove('avatar_version')
        ..remove('avatar_url');
      expect(Character.fromJson({...json, 'from_photo': false}).canUseInBook,
          isTrue);
      final oldPhoto = Character.fromJson(json);
      expect(oldPhoto.avatarStatus, CharacterAvatarStatus.failed);
      expect(oldPhoto.canUseInBook, isFalse);
    });
    test(
        'only approved avatar with version and URL is usable, also for drawings',
        () {
      for (final status in [
        'not_required',
        'generating',
        'preview',
        'failed'
      ]) {
        expect(Character.fromJson(avatarJson(status: status)).canUseInBook,
            isFalse);
      }
      expect(avatar(status: 'approved').canUseInBook, isTrue);
      expect(avatar(status: 'approved', url: null).canUseInBook, isFalse);
      expect(avatar(status: 'approved', version: 0).canUseInBook, isFalse);
      expect(
          Character.fromJson(avatarJson(status: 'preview', photo: false))
              .canUseInBook,
          isFalse);
      expect(
          Character.fromJson(avatar(status: 'approved').toJson()).canUseInBook,
          isTrue);
    });
    test('unknown states and invalid versions are rejected', () {
      expect(() => Character.fromJson(avatarJson(status: 'imagined')),
          throwsFormatException);
      for (final version in [-1, 1.5, '1']) {
        expect(
            () => Character.fromJson(
                {...avatarJson(), 'avatar_version': version}),
            throwsFormatException);
      }
    });
  });
  group('picker cache deletion', () {
    test('selected cache is deleted, absent and null selections are harmless',
        () async {
      final dir = await Directory.systemTemp.createTemp('avatar-cleanup-');
      addTearDown(() => dir.delete(recursive: true));
      final file =
          await File('${dir.path}/selected.jpg').writeAsString('selected copy');
      await deleteSelectedPhotoCache(XFile(file.path));
      expect(await file.exists(), isFalse);
      await deleteSelectedPhotoCache(XFile(file.path));
      await deleteSelectedPhotoCache(null);
    });
    test('an original outside a cache boundary is preserved', () async {
      final dir = await Directory.current.createTemp('avatar-original-');
      addTearDown(() => dir.delete(recursive: true));
      final file =
          await File('${dir.path}/original.jpg').writeAsString('original');
      await deleteSelectedPhotoCache(XFile(file.path));
      expect(await file.readAsString(), 'original');
    });
    test('a cache symlink to an original is not followed for deletion',
        () async {
      final originalDir =
          await Directory.current.createTemp('avatar-original-');
      final cache = await Directory.systemTemp.createTemp('avatar-symlink-');
      addTearDown(() => originalDir.delete(recursive: true));
      addTearDown(() => cache.delete(recursive: true));
      final file = await File('${originalDir.path}/original.jpg')
          .writeAsString('original');
      final link = await Link('${cache.path}/selected.jpg').create(file.path);
      await deleteSelectedPhotoCache(XFile(link.path));
      expect(await file.exists(), isTrue);
      expect(await link.exists(), isTrue);
    });
  });
  testWidgets(
      'loaded preview approves exact version once and returns ready character',
      (tester) async {
    final api = AvatarApi(avatar(version: 2));
    CharacterAvatarPreviewResult? result;
    await openPreview(tester, api, onResult: (value) => result = value);
    await reach(tester, find.byKey(_approve));
    expect(
        tester.widget<FilledButton>(find.byKey(_approve)).onPressed, isNotNull);
    expect(
        tester.getSize(find.byKey(_approve)).height, greaterThanOrEqualTo(64));
    await tester.tap(find.byKey(_approve));
    await tester.pumpAndSettle();
    expect(api.approvals, [2]);
    expect(result?.character?.canUseInBook, isTrue);
    expect(find.text('open'), findsOneWidget);
  });
  testWidgets(
      'generation resumes on entry then enables approval only after loaded preview',
      (tester) async {
    final api = AvatarApi(avatar(status: 'generating', url: null));
    await openPreview(tester, api);
    expect(find.byKey(_approve), findsNothing);
    expect(api.gets, 1);
    api.current = avatar();
    await tester.pump(const Duration(seconds: 2));
    await tester.runAsync(
        () async => Future<void>.delayed(const Duration(milliseconds: 30)));
    await tester.pump();
    await tester.pump();
    await reach(tester, find.byKey(_approve));
    expect(
        tester.widget<FilledButton>(find.byKey(_approve)).onPressed, isNotNull);
    expect(api.approvals, isEmpty);
  });
  testWidgets(
      'regeneration is single explicit call and approval uses new version',
      (tester) async {
    final api = AvatarApi(avatar());
    await openPreview(tester, api);
    final regen = find.byKey(const ValueKey('character-avatar-regenerate'));
    await reach(tester, regen);
    await tester.tap(regen);
    await tester.pump();
    expect(api.regenerations, [1]);
    expect(api.approvals, isEmpty);
    expect(find.byKey(_approve), findsNothing);
    api.current = avatar(version: 2);
    await tester.pump(const Duration(seconds: 2));
    await tester.runAsync(
        () async => Future<void>.delayed(const Duration(milliseconds: 30)));
    await tester.pump();
    await tester.pump();
    await reach(tester, find.byKey(_approve));
    await tester.tap(find.byKey(_approve));
    await tester.pumpAndSettle();
    expect(api.approvals, [2]);
    expect(api.regenerations, [1]);
  });
  testWidgets(
      'version conflict reloads new preview without silently approving it',
      (tester) async {
    final api = AvatarApi(avatar());
    api.approve = (version) async {
      api.current = avatar(version: 2);
      throw StateError('conflict');
    };
    await openPreview(tester, api);
    await reach(tester, find.byKey(_approve));
    await tester.tap(find.byKey(_approve));
    await tester.pumpAndSettle();
    expect(api.approvals, [1]);
    expect(find.byType(CharacterAvatarPreviewScreen), findsOneWidget);
    expect(
        find.text('요청을 확인하지 못했어요. 최신 모습을 확인한 뒤 다시 선택해 주세요.'), findsOneWidget);
    expect(api.gets, 2);
  });
  testWidgets(
      'lost approval response accepts authoritative approved state without another write',
      (tester) async {
    final api = AvatarApi(avatar());
    api.approve = (version) async {
      api.current = avatar(status: 'approved');
      throw StateError('response lost');
    };
    CharacterAvatarPreviewResult? result;
    await openPreview(tester, api, onResult: (value) => result = value);
    await reach(tester, find.byKey(_approve));
    await tester.tap(find.byKey(_approve));
    await tester.pumpAndSettle();
    expect(api.approvals, [1]);
    expect(result?.character?.canUseInBook, isTrue);
  });
  testWidgets('broken image cannot be approved', (tester) async {
    final api = AvatarApi(avatar());
    await openPreview(tester, api, brokenImage: true);
    await reach(tester, find.byKey(_approve));
    expect(tester.widget<FilledButton>(find.byKey(_approve)).onPressed, isNull);
    await tester.tap(find.byKey(_approve));
    await tester.pump();
    expect(api.approvals, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'expired retry hides regeneration while another photo remains reachable',
      (tester) async {
    final api = AvatarApi(avatar(status: 'failed', retry: false, url: null));
    CharacterAvatarPreviewResult? result;
    await openPreview(tester, api,
        size: const Size(320, 480),
        scale: 1.4,
        brightness: Brightness.dark,
        onResult: (value) => result = value);
    expect(find.byKey(const ValueKey('character-avatar-regenerate')),
        findsNothing);
    expect(find.byKey(_approve), findsNothing);
    final other = find.byKey(const ValueKey('character-avatar-other-photo'));
    await reach(tester, other);
    await tester.tap(other);
    await tester.pumpAndSettle();
    expect(result?.chooseAnotherPhoto, isTrue);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'short large text preview keeps approval and leave actions scrollable',
      (tester) async {
    final api = AvatarApi(avatar());
    await openPreview(tester, api, size: const Size(320, 480), scale: 1.4);
    await reach(tester, find.byKey(_approve));
    expect(
        tester.getSize(find.byKey(_approve)).height, greaterThanOrEqualTo(64));
    await reach(tester, find.text('나중에 확인하기'));
    await tester.tap(find.text('나중에 확인하기'));
    await tester.pumpAndSettle();
    expect(api.approvals, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets('bounded polling pauses and a later entry resumes from server',
      (tester) async {
    final api = AvatarApi(avatar(status: 'generating', url: null));
    const policy = CharacterAvatarPollPolicy(
        interval: Duration(milliseconds: 10),
        timeout: Duration(seconds: 1),
        maxAttempts: 2);
    await openPreview(tester, api, policy: policy);
    await tester.pump(const Duration(milliseconds: 20));
    await tester.pump(const Duration(milliseconds: 20));
    final gets = api.gets;
    expect(gets, 2);
    await tester.pump(const Duration(seconds: 5));
    expect(api.gets, gets);
    await reach(tester, find.text('나중에 확인하기'));
    await tester.tap(find.text('나중에 확인하기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('open'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(api.gets, greaterThan(gets));
    expect(api.approvals, isEmpty);
  });
  testWidgets('read error can retry without a regeneration charge',
      (tester) async {
    final api = AvatarApi(avatar(status: 'generating', url: null))
      ..read = () async => throw StateError('offline');
    await openPreview(tester, api);
    final retry = find.text('다시 시도');
    await reach(tester, retry);
    api.read = null;
    api.current = avatar(status: 'failed', retry: false, url: null);
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(api.gets, 2);
    expect(api.regenerations, isEmpty);
    expect(api.approvals, isEmpty);
  });
  testWidgets('parent gate cancellation prevents approval', (tester) async {
    final api = AvatarApi(avatar());
    await openPreview(tester, api, verified: false);
    await reach(tester, find.byKey(_approve));
    await tester.tap(find.byKey(_approve));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.tap(find
        .descendant(
            of: find.byType(AlertDialog), matching: find.byType(TextButton))
        .first);
    await tester.pumpAndSettle();
    expect(api.approvals, isEmpty);
  });
  testWidgets(
      'already approved character is reused without another preview route',
      (tester) async {
    final ready = avatar(status: 'approved', retry: false);
    CharacterAvatarPreviewResult? result;
    await tester.pumpWidget(MaterialApp(
        home: Builder(
            builder: (context) => TextButton(
                onPressed: () async {
                  result = await showCharacterAvatarPreview(context,
                      characterId: ready.id, initialCharacter: ready);
                },
                child: const Text('reuse')))));
    await tester.tap(find.text('reuse'));
    await tester.pumpAndSettle();
    expect(result?.character, ready);
    expect(find.byType(CharacterAvatarPreviewScreen), findsNothing);
  });
}
