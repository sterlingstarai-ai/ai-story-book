import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_avatar_preview.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'character_avatar_flow_test.dart' show avatarJson;

Character _character({String status = 'approved', bool photo = true}) =>
    Character.fromJson({
      ...avatarJson(status: status, photo: photo),
      'master_description':
          'INTERNAL PROMPT: Preserve exact character anatomy.',
      'personality_traits': ['INTERNAL TRAIT'],
      'appearance': {
        for (final key in ['age_visual', 'face', 'hair', 'skin', 'body'])
          key: 'INTERNAL APPEARANCE'
      },
      'clothing': {
        for (final key in ['top', 'bottom', 'shoes', 'accessories'])
          key: 'INTERNAL CLOTHING'
      },
      'visual_style_notes': 'INTERNAL STYLE',
      'distinctive_features': ['INTERNAL IDENTITY'],
    });

class _Api extends ApiClient {
  _Api(this.character)
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);
  final Character character;
  @override
  Future<List<Character>> getCharacters() async => [character];
  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor]);
}

Future<void> _open(WidgetTester tester, Widget screen, Character character,
    String locale) async {
  tester.view.physicalSize = const Size(320, 480);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(_Api(character)),
        capabilitiesProvider
            .overrideWith((ref) async => {'audio_supported': false}),
      ],
      child: MaterialApp(
          theme: buildAppTheme(Brightness.dark),
          locale: Locale(locale),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context)
                  .copyWith(textScaler: const TextScaler.linear(1.4)),
              child: child!),
          home: screen)));
  await tester.pumpAndSettle();
}

void main() {
  for (final language in ['ko', 'en', 'ja']) {
    test('photo descriptions in $language are localized for every state',
        () async {
      final l = await AppLocalizations.delegate.load(Locale(language));
      expect(characterDisplayDescription(l, _character()),
          l.characterAvatarApprovedDescription);
      expect(characterDisplayDescription(l, _character(status: 'generating')),
          l.characterAvatarPreparingDescription);
      expect(characterDisplayDescription(l, _character(status: 'preview')),
          l.characterAvatarNeedsApproval);
      expect(characterDisplayDescription(l, _character(status: 'failed')),
          l.characterAvatarFailedDescription);
      final text = _character(photo: false, status: 'not_required');
      expect(characterDisplayDescription(l, text), text.masterDescription);
    });
    testWidgets(
        'create photo card in $language shows guidance instead of generation instructions',
        (tester) async {
      final l = await AppLocalizations.delegate.load(Locale(language));
      await _open(tester, const CreateScreen(), _character(), language);
      final card = find.byType(CharacterCard);
      await tester.scrollUntilVisible(card, 240,
          scrollable: find.byType(Scrollable).first);
      await tester.pumpAndSettle();
      expect(tester.widget<CharacterCard>(card).description,
          l.characterAvatarApprovedDescription);
      expect(find.textContaining('INTERNAL'), findsNothing);
      expect(tester.takeException(), isNull);
    });
    testWidgets(
        'photo list and detail in $language hide all private prompt fields',
        (tester) async {
      final l = await AppLocalizations.delegate.load(Locale(language));
      await _open(tester, const CharactersScreen(), _character(), language);
      await tester.scrollUntilVisible(
          find.text(l.characterAvatarApprovedDescription), 180,
          scrollable: find.byType(Scrollable).first);
      await tester.pumpAndSettle();
      expect(find.text(l.characterAvatarApprovedDescription), findsOneWidget);
      expect(find.textContaining('INTERNAL'), findsNothing);
      await tester.ensureVisible(find.text('시우'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('시우'));
      await tester.pumpAndSettle();
      expect(find.textContaining('INTERNAL'), findsNothing);
      expect(find.text(l.charactersDetailAppearance), findsNothing);
      expect(find.text(l.charactersDetailClothing), findsNothing);
      expect(find.text(l.charactersDetailPersonality), findsNothing);
      final action = find.widgetWithText(
          PrimaryButton, l.charactersDetailCreateBookButton);
      await tester.scrollUntilVisible(action, 160,
          scrollable: find.byType(Scrollable).last);
      await tester.pumpAndSettle();
      expect(action.hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('manual character descriptions and detail remain available',
      (tester) async {
    final manual = _character(photo: false, status: 'not_required');
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await _open(tester, const CharactersScreen(), manual, 'ko');
    expect(find.text(manual.masterDescription), findsOneWidget);
    expect(find.text('INTERNAL TRAIT'), findsOneWidget);
    await tester.tap(find.text('시우'));
    await tester.pumpAndSettle();
    final appearance = find.text(l.charactersDetailAppearance);
    await tester.scrollUntilVisible(appearance, 180,
        scrollable: find.byType(Scrollable).last);
    await tester.pumpAndSettle();
    expect(appearance, findsOneWidget);
    expect(find.text('INTERNAL APPEARANCE'), findsWidgets);
  });
}
