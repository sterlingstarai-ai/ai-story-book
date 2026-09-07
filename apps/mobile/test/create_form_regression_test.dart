import 'dart:async';

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
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_source_sheet.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://test', userKey: 'test', enableLogging: false);
  int creditReads = 0;
  final specs = <BookSpec>[];
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
  Future<int> getCreditsBalance() async {
    creditReads++;
    return 3;
  }

  @override
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    specs.add(spec);
    return CreateBookResponse(jobId: 'created', status: 'queued');
  }
}

const _profile = ActiveChildProfile(
  id: 'active',
  name: '토리',
  targetAge: TargetAge.age7to9,
);

Future<void> _open(
  WidgetTester tester,
  _Api api, {
  Future<ActiveChildProfile?>? profile,
  bool startPhoto = false,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        activeChildProfileProvider.overrideWith((ref) async => await profile),
        capabilitiesProvider.overrideWith(
          (ref) async => {'audio_supported': false},
        ),
        characterPresetsProvider('ko').overrideWith((ref) async => []),
      ],
      child: MaterialApp(
        theme: buildAppTheme(Brightness.light),
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        onGenerateInitialRoutes: (_) => [
          buildAppRoute(
            RouteSettings(
              name: '/create',
              arguments: {'startPhotoCharacter': startPhoto},
            ),
          ),
        ],
        onGenerateRoute: (_) => MaterialPageRoute<void>(
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
    await _open(tester, api, profile: Future.value(_profile));
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
    expect(api.creditReads, 1);
  });

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
