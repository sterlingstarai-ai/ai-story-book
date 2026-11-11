import 'dart:async';
import 'package:dio/dio.dart';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/active_child_profile.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'character_avatar_flow_test.dart' show avatarJson;
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/page_audio_playback.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_source_sheet.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:ai_story_book/widgets/narration_style_previews.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'support/design_capture.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://test', userKey: 'test', enableLogging: false);
  int creditReads = 0;
  int balance = 3;
  bool loseFirstResponse = false;
  bool transportResponseLoss = false;
  final specs = <BookSpec>[];
  final attemptKeys = <String?>[];
  List<Character> characters = [];
  Future<Map<String, dynamic>>? profiles;

  @override
  Future<Map<String, dynamic>> getProfiles() async =>
      await (profiles ?? Future.value({'profiles': []}));
  @override
  Future<List<Character>> getCharacters() async => characters;
  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor]);
  @override
  Future<List<JobStatus>> getActiveBookGenerations() async => [];
  @override
  Future<int> getCreditsBalance() async {
    creditReads++;
    return balance;
  }

  @override
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    specs.add(spec);
    attemptKeys.add(idempotencyKey);
    if (loseFirstResponse && specs.length == 1) {
      balance--;
      if (transportResponseLoss) {
        throw DioException(
          requestOptions: RequestOptions(path: '/v1/books'),
          type: DioExceptionType.receiveTimeout,
        );
      }
      throw ApiError(code: 'TIMEOUT', message: '', statusCode: 0);
    }
    if (balance == 0 &&
        !(loseFirstResponse && idempotencyKey == attemptKeys.first)) {
      throw ApiError(code: 'PAYMENT_REQUIRED', message: '', statusCode: 402);
    }
    return CreateBookResponse(jobId: 'created', status: 'queued');
  }
}

const _profile = ActiveChildProfile(
  id: 'active',
  name: '토리',
  targetAge: TargetAge.age7to9,
);

class _PreviewPlayer implements NarrationPreviewPlayer {
  final assets = <String>[];
  bool disposed = false;

  @override
  Future<void> stop() async {}

  @override
  Future<void> setAsset(String asset) async => assets.add(asset);

  @override
  Future<void> play() async {}

  @override
  Future<void> dispose() async => disposed = true;
}

Future<void> _open(
  WidgetTester tester,
  _Api api, {
  Future<ActiveChildProfile?>? profile,
  bool startPhoto = false,
  bool fromProfileWatcher = false,
  _PreviewPlayer? previewPlayer,
}) async {
  SharedPreferences.setMockInitialValues({
    if (previewPlayer != null) narrationVoicePreferenceKey: 'deep',
  });
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        activeChildProfileProvider.overrideWith((ref) async => await profile),
        capabilitiesProvider.overrideWith(
          (ref) async => {
            'narration_supported': previewPlayer != null,
            'narration_style_selection_supported': previewPlayer != null,
            'narration_preview_provider': 'google_gemini',
          },
        ),
        if (previewPlayer != null)
          narrationPreviewPlayerFactoryProvider.overrideWithValue(
            () => previewPlayer,
          ),
        characterPresetsProvider('ko').overrideWith((ref) async => []),
      ],
      child: MaterialApp(
        builder: (_, child) => designCaptureBoundary(child!),
        theme: buildAppTheme(Brightness.light),
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        onGenerateInitialRoutes: (_) => [
          if (fromProfileWatcher)
            MaterialPageRoute<void>(
              builder: (_) => Consumer(
                builder: (context, ref, _) {
                  final name = ref
                      .watch(activeChildProfileProvider)
                      .valueOrNull
                      ?.name;
                  return Scaffold(
                    body: TextButton(
                      onPressed: () => Navigator.pushNamed(context, '/create'),
                      child: Text('Create for ${name ?? "child"}'),
                    ),
                  );
                },
              ),
            )
          else
            buildAppRoute(
              RouteSettings(
                name: '/create',
                arguments: {'startPhotoCharacter': startPhoto},
              ),
            ),
        ],
        onGenerateRoute: (settings) => settings.name == '/create'
            ? buildAppRoute(settings)
            : MaterialPageRoute<void>(
                builder: (_) => const Scaffold(body: Text('created')),
              ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Finder get _name => find.byWidgetPredicate(
  (widget) => widget is TextField && widget.maxLength == 40,
);

void main() {
  testWidgets('creation previews then saves a selected style', (tester) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final api = _Api();
    final player = _PreviewPlayer();
    await loadDesignFonts();
    await _open(tester, api, previewPlayer: player);
    final prefs = await SharedPreferences.getInstance();

    final launch = find.text('세 가지 낭독 미리 듣기');
    await tester.ensureVisible(launch);
    await tester.pumpAndSettle();
    await tester.tap(launch);
    await tester.pumpAndSettle();
    await captureDesign(tester, 'create-narration-previews-small');

    for (final style in ['natural', 'animated', 'bedtime']) {
      final button = find.byKey(ValueKey('narration-preview-$style'));
      await tester.ensureVisible(button);
      await tester.pumpAndSettle();
      expect(tester.getSize(button).height, greaterThanOrEqualTo(64));
      await tester.tap(button);
      await tester.pumpAndSettle();
    }
    expect(player.assets, [
      'assets/audio/narration_preview_google_male_natural.mp3',
      'assets/audio/narration_preview_google_male_animated.mp3',
      'assets/audio/narration_preview_google_male_bedtime.mp3',
    ]);
    final close = find.descendant(
      of: find.byType(BottomSheet),
      matching: find.byTooltip('닫기'),
    );
    await tester.ensureVisible(close);
    await tester.pumpAndSettle();
    await tester.tap(close);
    await tester.pumpAndSettle();
    expect(player.disposed, isTrue);
    expect(prefs.getString(narrationStylePreferenceKey), isNull);
    expect(find.byType(CreateScreen), findsOneWidget);
    expect(api.specs, isEmpty);

    await tester.tap(launch);
    await tester.pumpAndSettle();
    final stylePicker = find.byKey(
      const ValueKey('create-default-narration-style'),
    );
    await tester.ensureVisible(stylePicker);
    await tester.pumpAndSettle();
    expect(tester.getSize(stylePicker).height, greaterThanOrEqualTo(64));
    await captureDesign(tester, 'create-narration-default-style-small');
    await tester.tap(stylePicker);
    await tester.pumpAndSettle();
    await tester.tap(find.text('구연동화').last);
    await tester.pumpAndSettle();
    expect(prefs.getString(narrationStylePreferenceKey), 'animated');
    expect(find.byType(BottomSheet), findsNothing);
    expect(api.specs, isEmpty);
  });

  testWidgets(
    'adding a hero returns to the same form with its draft and selection',
    (tester) async {
      final api = _Api()
        ..characters = [
          Character.fromJson(
            avatarJson(status: 'not_required', photo: false, url: null),
          ),
        ];
      await _open(tester, api);
      final topic = find.byType(TextFormField);
      await tester.ensureVisible(topic);
      await tester.enterText(topic, '친구와 함께 떠나는 숲속 모험');
      await tester.ensureVisible(_name);
      await tester.enterText(_name, '토리');
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      final add = find.text('캐릭터 추가');
      await tester.scrollUntilVisible(
        add,
        250,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
      expect(add.hitTestable(), findsOneWidget);
      await tester.tap(add);
      await tester.pumpAndSettle();
      expect(find.byType(CharactersScreen), findsOneWidget);
      await tester.tap(find.text('시우'));
      await tester.pumpAndSettle();
      expect(find.byType(CharactersScreen), findsNothing);
      expect(tester.widget<TextField>(_name).controller!.text, '토리');
      expect(find.text('친구와 함께 떠나는 숲속 모험'), findsOneWidget);
      expect(
        tester.widget<CharacterCard>(find.byType(CharacterCard)).isSelected,
        isTrue,
      );
      expect(api.specs, isEmpty);
    },
  );

  for (final topic in ['', '   ', '짧음']) {
    testWidgets(
      'offscreen invalid topic "$topic" blocks API and reveals field',
      (tester) async {
        tester.view.physicalSize = const Size(320, 480);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.textScaleFactorTestValue = 1.4;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final api = _Api();
        await _open(tester, api);
        final topicField = find.byType(TextFormField);
        await tester.ensureVisible(topicField);
        await tester.enterText(topicField, topic);
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        await tester.drag(find.byType(ListView).first, const Offset(0, -3000));
        await tester.pumpAndSettle();
        expect(topicField.hitTestable(), findsNothing);
        await tester.tap(find.byType(PrimaryButton));
        await tester.pumpAndSettle();
        expect(api.specs, isEmpty);
        expect(api.creditReads, 0);
        final l = AppLocalizations.of(
          tester.element(find.byType(CreateScreen)),
        );
        expect(
          find.text(
            topic.trim().isEmpty
                ? l.createTopicRequired
                : l.createTopicTooShort,
          ),
          findsOneWidget,
        );
        expect(topicField.hitTestable(), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('active child defaults reach request and remain editable', (
    tester,
  ) async {
    final api = _Api();
    await _open(
      tester,
      api,
      profile: Future.value(_profile),
      fromProfileWatcher: true,
    );
    await tester.tap(find.text('Create for 토리'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(tester.widget<TextField>(_name).controller!.text, '토리');
    expect(
      tester
          .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '7-9세'))
          .selected,
      isTrue,
    );
    await tester.ensureVisible(_name);
    await tester.enterText(_name, '별이');
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.ensureVisible(find.byType(TextFormField));
    await tester.enterText(find.byType(TextFormField), '다 같이 도서관에 가는 이야기');
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.tap(find.byType(PrimaryButton));
    await tester.pumpAndSettle();
    expect(api.specs.single.protagonistName, '별이');
    expect(api.specs.single.targetAge, '7-9');
    expect(api.creditReads, 0);
  });

  testWidgets(
    'retry reopens the accepted first book after the response is lost',
    (tester) async {
      final api = _Api()
        ..balance = 1
        ..loseFirstResponse = true;
      addTearDown(api.close);
      await _open(tester, api);
      await tester.enterText(find.byType(TextFormField), '숲에서 친구를 만나는 이야기');
      FocusManager.instance.primaryFocus?.unfocus();
      final submit = find.byType(PrimaryButton);
      await tester.ensureVisible(submit);
      await tester.pumpAndSettle();

      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(api.balance, 0);
      expect(api.attemptKeys.single, isNotNull);
      expect(find.byType(CreateScreen), findsOneWidget);

      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(api.attemptKeys, [api.attemptKeys.first, api.attemptKeys.first]);
      expect(api.creditReads, 0);
      expect(api.balance, 0);
      expect(find.text('created'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'a lost transport response opens the accepted book without another tap',
    (tester) async {
      final api = _Api()
        ..balance = 1
        ..loseFirstResponse = true
        ..transportResponseLoss = true;
      addTearDown(api.close);
      await _open(tester, api);
      await tester.enterText(find.byType(TextFormField), '숲에서 친구를 만나는 이야기');
      FocusManager.instance.primaryFocus?.unfocus();
      final submit = find.byType(PrimaryButton);
      await tester.ensureVisible(submit);
      await tester.pumpAndSettle();
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(api.balance, 0);
      expect(api.attemptKeys, hasLength(2));
      expect(api.attemptKeys.first, api.attemptKeys.last);
      expect(api.creditReads, 0);
      expect(find.text('created'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'a genuine server credit rejection still shows the credit dialog',
    (tester) async {
      final api = _Api()..balance = 0;
      addTearDown(api.close);
      await _open(tester, api);
      await tester.enterText(find.byType(TextFormField), '숲에서 친구를 만나는 이야기');
      FocusManager.instance.primaryFocus?.unfocus();
      final submit = find.byType(PrimaryButton);
      await tester.ensureVisible(submit);
      await tester.pumpAndSettle();
      await tester.tap(submit);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(api.specs, hasLength(1));
      expect(api.creditReads, 0);
      expect(find.text('이용 가능한 기능과 잔액을 확인해요'), findsOneWidget);
      expect(find.text('created'), findsNothing);
      Navigator.of(tester.element(find.byType(BottomSheet))).pop();
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('late defaults never overwrite cleared name or selected age', (
    tester,
  ) async {
    final pending = Completer<ActiveChildProfile?>();
    await _open(tester, _Api(), profile: pending.future);
    await tester.tap(find.widgetWithText(ChoiceChip, '3-5세'));
    await tester.ensureVisible(_name);
    await tester.enterText(_name, '직접 입력');
    await tester.enterText(_name, '');
    pending.complete(_profile);
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(_name).controller!.text, isEmpty);
    expect(
      tester
          .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '3-5세'))
          .selected,
      isTrue,
    );
  });

  testWidgets(
    'home photo shortcut passes loaded profile name into source sheet',
    (tester) async {
      await _open(
        tester,
        _Api(),
        profile: Future.value(_profile),
        startPhoto: true,
      );
      expect(
        tester
            .widget<CharacterSourceSheet>(find.byType(CharacterSourceSheet))
            .childName,
        '토리',
      );
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'profile defaults match active child only; adult and missing stay unset',
    () async {
      for (final age in ['7-9', 'adult', 'unknown']) {
        SharedPreferences.setMockInitialValues({
          'active_profile_id_v1': 'active',
        });
        final prefs = await SharedPreferences.getInstance();
        final api = _Api()
          ..profiles = Future.value({
            'profiles': [
              {
                'id': 'other',
                'name': '다른 아이',
                'age_band': '3-5',
                'is_default': true,
              },
              {'id': 'active', 'name': ' 토리 ', 'age_band': age},
            ],
          });
        final container = ProviderContainer(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(api),
          ],
        );
        final result = await container.read(activeChildProfileProvider.future);
        if (age == '7-9') {
          expect(result?.name, '토리');
          expect(result?.targetAge, TargetAge.age7to9);
        } else {
          expect(result, isNull);
        }
        container.dispose();
      }
    },
  );
}
