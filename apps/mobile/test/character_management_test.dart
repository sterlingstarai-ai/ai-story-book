import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'character_avatar_flow_test.dart' show avatarJson;

class _Parent extends ParentalControlService {
  _Parent() {
    markAgeGateVerified();
  }
  @override
  Future<void> loadAgeGateSession(SharedPreferences prefs) async {}
}

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://test', userKey: 'test', enableLogging: false);
  final data = avatarJson(status: 'approved', url: null)..['name'] = '캐릭터';
  int renames = 0;
  bool deleted = false;
  bool purgePending = false;
  @override
  Future<List<Character>> getCharacters() async =>
      deleted ? [] : [Character.fromJson(data)];
  @override
  Future<void> deleteCharacter(String id) async {
    deleted = true;
    if (purgePending) throw const StoragePurgePending();
  }
  @override
  Future<void> renameCharacter(String id, String name) async {
    expect(id, data['character_id']);
    renames++;
    data['name'] = name;
  }
}

void main() {
  testWidgets('character deletion reports files still being deleted',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final api = _Api()..purgePending = true;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(api),
          parentalControlServiceProvider.overrideWithValue(_Parent()),
        ],
        child: const MaterialApp(
          locale: Locale('ko'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CharactersScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final l = AppLocalizations.of(tester.element(find.byType(CharactersScreen)));
    await tester.tap(find.byTooltip('캐릭터 관리'));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.charactersDeleteDialogTitle));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, l.charactersDelete));
    await tester.pumpAndSettle();
    expect(find.text(l.characterDeletionPending), findsOneWidget);
    expect(find.text(l.charactersDeletedSnack), findsNothing);
    expect(api.deleted, isTrue);
  });

  testWidgets(
    'visible menu renames an approved character without regenerating appearance',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final api = _Api();
      final before = {...api.data};
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(api),
            parentalControlServiceProvider.overrideWithValue(_Parent()),
          ],
          child: const MaterialApp(
            locale: Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: CharactersScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('캐릭터 관리'));
      await tester.pumpAndSettle();
      expect(find.text('캐릭터 삭제'), findsOneWidget);
      await tester.tap(find.text('이름 바꾸기'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '   ');
      await tester.tap(find.widgetWithText(TextButton, '저장'));
      await tester.pumpAndSettle();
      expect(api.renames, 0);
      expect(find.byType(AlertDialog), findsOneWidget);
      await tester.enterText(find.byType(TextFormField), '토리');
      await tester.tap(find.widgetWithText(TextButton, '저장'));
      await tester.pumpAndSettle();
      expect(api.renames, 1);
      expect(find.text('토리'), findsOneWidget);
      expect({...api.data}..remove('name'), {...before}..remove('name'));
      expect(tester.takeException(), isNull);
    },
  );
}
