// Opt-in native HTTP acceptance against an isolated LOCAL mock-AI API only.
// Injects a synthetic PNG instead of using ImagePicker or a real child's photo.
// This verifies native network-image rendering, consent, avatar confirmation and
// reuse; it does not verify the photo-library plugin or real-photo likeness.
// Run with --dart-define=FINAL_E2E_LOCAL_API=http://127.0.0.1:<preview-port>.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:ai_story_book/core/photo_consent.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/selected_photo_cache.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/age_gate_dialog.dart';
import 'package:ai_story_book/widgets/character_avatar_preview.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class _SyntheticUser extends UserService {
  _SyntheticUser(super.preferences);
  final key = const Uuid().v4();
  @override
  String getUserKey() => key;
}

class _ObservedApi extends ApiClient {
  _ObservedApi({required super.baseUrl, required super.userKey})
      : super(enableLogging: false);
  int approvalCalls = 0, regenerationCalls = 0, characterReads = 0;
  @override
  Future<Character> getCharacter(String id) {
    characterReads++;
    return super.getCharacter(id);
  }

  @override
  Future<Character> approveCharacterAvatar(String id, {required int version}) {
    approvalCalls++;
    return super.approveCharacterAvatar(id, version: version);
  }

  @override
  Future<Character> regenerateCharacterAvatar(String id,
      {required int version}) {
    regenerationCalls++;
    return super.regenerateCharacterAvatar(id, version: version);
  }
}

class _SyntheticUploadEntry extends ConsumerWidget {
  const _SyntheticUploadEntry({required this.image, required this.onApproved});
  final File image;
  final ValueChanged<Character> onApproved;
  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
      body: Center(
          child: FilledButton(
              key: const Key('synthetic-photo-upload'),
              child: const Text('합성 사진으로 테스트'),
              onPressed: () async {
                final api = ref.read(apiClientProvider);
                try {
                  if (!await ensureAgeGate(context, ref) || !context.mounted) {
                    return;
                  }
                  if (!await ensurePhotoConsent(context, api) ||
                      !context.mounted) {
                    return;
                  }
                  final response = await api.createCharacterFromPhoto(image,
                      name: '시우',
                      style: 'cartoon',
                      idempotencyKey: const Uuid().v4());
                  await deleteSelectedPhotoCache(XFile(image.path));
                  if (!context.mounted) return;
                  final character = Character.fromJson(response);
                  ref.invalidate(charactersProvider);
                  final result = await showCharacterAvatarPreview(context,
                      characterId: character.id, initialCharacter: character);
                  if (!context.mounted ||
                      result?.character?.canUseInBook != true) {
                    return;
                  }
                  onApproved(result!.character!);
                  ref.invalidate(charactersProvider);
                  Navigator.pushNamed(context, '/create', arguments: {
                    'characterIds': [result.character!.id]
                  });
                } finally {
                  await deleteSelectedPhotoCache(XFile(image.path));
                }
              })));
}

Future<File> _syntheticPng() async {
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.drawRect(const Rect.fromLTWH(0, 0, 256, 256),
      Paint()..color = const Color(0xfff5e9ce));
  canvas.drawCircle(
      const Offset(128, 110), 65, Paint()..color = const Color(0xffe4b998));
  canvas.drawCircle(
      const Offset(104, 108), 8, Paint()..color = const Color(0xff32251b));
  canvas.drawCircle(
      const Offset(152, 108), 8, Paint()..color = const Color(0xff32251b));
  canvas.drawRect(const Rect.fromLTWH(58, 178, 140, 78),
      Paint()..color = const Color(0xff7771b8));
  final picture = recorder.endRecording();
  final image = await picture.toImage(256, 256);
  picture.dispose();
  try {
    final bytes = (await image.toByteData(format: ui.ImageByteFormat.png))!
        .buffer
        .asUint8List();
    return File(
            '${(await getTemporaryDirectory()).path}/synthetic-avatar-${const Uuid().v4()}.png')
        .writeAsBytes(bytes);
  } finally {
    image.dispose();
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const baseUrl = String.fromEnvironment('FINAL_E2E_LOCAL_API');
  testWidgets(
      'synthetic photo: native preview, parent approval, approved character reuse',
      (tester) async {
    expect(Uri.parse(baseUrl).host, anyOf('127.0.0.1', 'localhost', '10.0.2.2'),
        reason: 'Only an isolated local mock-AI API is permitted.');
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final user = _SyntheticUser(prefs);
    final api = _ObservedApi(baseUrl: baseUrl, userKey: user.key);
    final container = ProviderContainer(overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      userServiceProvider.overrideWithValue(user),
      apiBaseUrlProvider.overrideWithValue(baseUrl),
      apiClientProvider.overrideWithValue(api),
    ]);
    final selected = await _syntheticPng();
    Character? approved;
    final boundary = GlobalKey();
    final output = Directory(
        '${(await getApplicationDocumentsDirectory()).path}/photo-character-e2e');
    await output.create(recursive: true);
    const captureUrl = String.fromEnvironment('FINAL_E2E_ARTIFACTS');
    if (captureUrl.isNotEmpty) {
      expect(Uri.parse(captureUrl).host,
          anyOf('127.0.0.1', 'localhost', '10.0.2.2'));
    }
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(milliseconds: 500));
      container.dispose();
      try {
        await api.deleteMyData();
      } finally {
        api.close();
        await deleteSelectedPhotoCache(XFile(selected.path));
      }
    });
    // This unique synthetic account is seeded with required consent only. Photo
    // consent and the parent challenge are completed through the actual UI.
    await api.grantConsent(privacy: true, photos: false, dataProcessing: true);
    await tester.pumpWidget(UncontrolledProviderScope(
        container: container,
        child: RepaintBoundary(
            key: boundary,
            child: MaterialApp(
                debugShowCheckedModeBanner: false,
                locale: const Locale('ko'),
                theme: buildAppTheme(Brightness.light),
                localizationsDelegates: AppLocalizations.localizationsDelegates,
                supportedLocales: AppLocalizations.supportedLocales,
                home: _SyntheticUploadEntry(
                    image: selected, onApproved: (value) => approved = value),
                onGenerateRoute: buildAppRoute))));
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    Future<void> until(Finder finder, {int seconds = 30}) async {
      for (var i = 0; i < seconds * 5 && finder.evaluate().isEmpty; i++) {
        await tester.pump(const Duration(milliseconds: 200));
      }
      expect(finder, findsWidgets);
      expect(tester.takeException(), isNull);
    }

    Future<void> tap(Finder finder) async {
      await until(finder);
      await tester.ensureVisible(finder.first);
      await tester.pump(const Duration(milliseconds: 250));
      await tester.tap(finder.first);
      await tester.pump(const Duration(milliseconds: 400));
    }

    Future<void> capture(String name) async {
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
      final render =
          boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await render.toImage(pixelRatio: 1);
      try {
        final bytes = (await image.toByteData(format: ui.ImageByteFormat.png))!
            .buffer
            .asUint8List();
        await File('${output.path}/$name.png').writeAsBytes(bytes);
        if (captureUrl.isNotEmpty) {
          final http = HttpClient();
          try {
            final request = await http.putUrl(Uri.parse(
                '$captureUrl/${Platform.isIOS ? 'ios' : 'android'}/$name.png'));
            request.contentLength = bytes.length;
            request.add(bytes);
            final response = await request.close();
            expect(response.statusCode, 201);
            await response.drain<void>();
          } finally {
            http.close();
          }
        }
      } finally {
        image.dispose();
      }
    }

    await tap(find.byKey(const Key('synthetic-photo-upload')));
    await until(find.byType(AlertDialog));
    final pattern = RegExp(r'^(\d+)\s*×\s*(\d+)\s*=\s*\?$');
    final question = tester
        .widgetList<Text>(find.descendant(
            of: find.byType(AlertDialog), matching: find.byType(Text)))
        .map((t) => t.data ?? '')
        .singleWhere(pattern.hasMatch);
    final match = pattern.firstMatch(question)!;
    await tester.enterText(
        find.descendant(
            of: find.byType(AlertDialog), matching: find.byType(TextField)),
        '${int.parse(match.group(1)!) * int.parse(match.group(2)!)}');
    await tap(find.widgetWithText(ElevatedButton, l.ageGateConfirm));
    await until(find.text(l.consentPhotoOptionalTitle));
    await tap(find.widgetWithText(TextButton, l.photoConsentAgree));
    await until(find.byType(CharacterAvatarPreviewScreen));
    expect(await selected.exists(), isFalse,
        reason: 'The picker copy must be removed before preview.');
    final loaded = find.descendant(
        of: find.byType(CharacterAvatarPreviewScreen),
        matching:
            find.byWidgetPredicate((w) => w is RawImage && w.image != null));
    await until(loaded, seconds: 360);
    await tester.pump(const Duration(milliseconds: 400));
    final approveButton = find.byKey(const Key('character-avatar-approve'));
    await tester.ensureVisible(approveButton);
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.widget<FilledButton>(approveButton).onPressed, isNotNull);
    await capture('photo-avatar-preview');
    await tap(approveButton);
    await until(find.byType(CreateScreen));
    // The route can be built while its native transition is still off-screen.
    await tester.pumpAndSettle();
    expect(approved?.canUseInBook, isTrue);
    expect(api.approvalCalls, 1);
    expect(api.regenerationCalls, 0);
    final card =
        find.byWidgetPredicate((w) => w is CharacterCard && w.name == '시우');
    await tester.scrollUntilVisible(card, 220,
        scrollable: find.byType(Scrollable).first);
    await tester.pump(const Duration(milliseconds: 350));
    expect(tester.widget<CharacterCard>(card).isSelected, isTrue);
    final readsBeforeReuse = api.characterReads;
    await tap(card);
    expect(tester.widget<CharacterCard>(card).isSelected, isFalse);
    await tap(card);
    expect(tester.widget<CharacterCard>(card).isSelected, isTrue);
    expect(find.byType(CharacterAvatarPreviewScreen), findsNothing);
    expect(api.approvalCalls, 1);
    expect(api.characterReads, readsBeforeReuse,
        reason:
            'Reselecting an approved character does not reopen or reload the preview.');
    expect(tester.widget<CharacterCard>(card).statusLabel,
        l.characterAvatarHeroLabel);
    await capture('photo-avatar-reused');
    final persisted = await api.getCharacter(approved!.id);
    expect(persisted.avatarStatus, CharacterAvatarStatus.approved);
    await File('${output.path}/result.txt').writeAsString(
        'synthetic_local_http=passed\navatar_approved=true\navatar_version=${persisted.avatarVersion}\napprovals=1\nregenerations=0\noriginal_picker_copy_deleted=true\napproved_reselection_without_preview=true\n');
  }, skip: baseUrl.isEmpty, timeout: const Timeout(Duration(minutes: 9)));
}
