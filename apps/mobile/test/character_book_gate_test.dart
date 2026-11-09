import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_avatar_preview.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'character_avatar_flow_test.dart' show avatarJson;

class _Api extends ApiClient {
  _Api(this.characters)
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);
  final List<Character> characters;
  int credits = 0, approvals = 0, reads = 0;
  Completer<void>? characterGate;
  final specs = <BookSpec>[];
  @override
  Future<List<Character>> getCharacters() async => characters;
  @override
  Future<Character> getCharacter(String id) async {
    reads++;
    await characterGate?.future;
    return characters.singleWhere((c) => c.id == id);
  }

  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor]);
  @override
  Future<int> getCreditsBalance() async {
    credits++;
    return 5;
  }

  @override
  Future<CreateBookResponse> createBook(BookSpec spec,
      {String? idempotencyKey}) async {
    specs.add(spec);
    return CreateBookResponse(jobId: 'job', status: 'queued');
  }

  @override
  Future<Character> approveCharacterAvatar(String id,
      {required int version}) async {
    approvals++;
    throw StateError('Unexpected reapproval');
  }
}

Character _character(String id,
        {bool photo = true, String status = 'approved'}) =>
    Character.fromJson({
      ...avatarJson(status: status, photo: photo),
      'character_id': id,
      'name': id
    });
Future<void> _open(WidgetTester tester, _Api api, List<String> selected) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        apiClientProvider.overrideWithValue(api),
        capabilitiesProvider
            .overrideWith((ref) async => {'audio_supported': false}),
      ],
      child: MaterialApp(
          theme: buildAppTheme(Brightness.light),
          locale: const Locale('ko'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          onGenerateInitialRoutes: (_) => [
                buildAppRoute(RouteSettings(
                    name: '/create', arguments: {'characterIds': selected}))
              ],
          onGenerateRoute: (settings) => MaterialPageRoute(
              builder: (_) => const Scaffold(body: Text('created'))))));
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextFormField).first, '함께 꽃을 키우는 아이');
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
}

Future<void> _submit(WidgetTester tester) async {
  final button = find.byType(PrimaryButton);
  await tester.ensureVisible(button);
  await tester.pumpAndSettle();
  await tester.tap(button);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  testWidgets(
      'pending character in route arguments opens approval before any credit or book request',
      (tester) async {
    final api = _Api([_character('photo', status: 'generating')]);
    await _open(tester, api, ['photo']);
    await _submit(tester);
    expect(find.byType(CharacterAvatarPreviewScreen), findsOneWidget);
    expect(api.credits, 0);
    expect(api.specs, isEmpty);
    await tester.ensureVisible(find.text('나중에 확인하기'));
    await tester.tap(find.text('나중에 확인하기'));
    await tester.pumpAndSettle();
    expect(api.credits, 0);
    expect(api.specs, isEmpty);
    expect(api.approvals, 0);
  });
  testWidgets(
      'approved photo is reused and precedes manual supporting character',
      (tester) async {
    final api = _Api([
      _character('manual', photo: false, status: 'not_required'),
      _character('photo')
    ]);
    await _open(tester, api, ['manual', 'photo']);
    await _submit(tester);
    await tester.pumpAndSettle();
    expect(find.byType(CharacterAvatarPreviewScreen), findsNothing);
    expect(api.approvals, 0);
    expect(api.specs.single.characterIds, ['photo', 'manual']);
    expect(api.credits, 0);
  });
  testWidgets('leaving during character validation does not submit a book',
      (tester) async {
    final api = _Api([_character('photo')])
      ..characterGate = Completer<void>();
    await _open(tester, api, ['photo']);
    await _submit(tester);
    expect(api.reads, 1);
    expect(api.specs, isEmpty);
    await tester.pumpWidget(const SizedBox());
    api.characterGate!.complete();
    await tester.pump();
    expect(api.specs, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'two photo IDs injected through route cannot create or consume credits',
      (tester) async {
    final api = _Api([_character('first'), _character('second')]);
    await _open(tester, api, ['first', 'second']);
    await _submit(tester);
    await tester.pumpAndSettle();
    expect(api.specs, isEmpty);
    expect(api.credits, 0);
  });
  testWidgets(
      'choosing another photo replaces the previous hero and keeps manual support',
      (tester) async {
    final api = _Api([
      _character('manual', photo: false, status: 'not_required'),
      _character('first'),
      _character('second')
    ]);
    await _open(tester, api, ['manual', 'first']);
    final second =
        find.byWidgetPredicate((w) => w is CharacterCard && w.name == 'second');
    await tester.scrollUntilVisible(second, 250,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(second);
    await tester.pumpAndSettle();
    await tester.tap(second);
    await tester.pumpAndSettle();
    final cards = tester.widgetList<CharacterCard>(find.byType(CharacterCard));
    expect(cards.singleWhere((c) => c.name == 'first').isSelected, isFalse);
    expect(cards.singleWhere((c) => c.name == 'second').isSelected, isTrue);
    expect(
        cards.singleWhere((c) => c.name == 'second').statusLabel, '이 책의 주인공');
    await _submit(tester);
    await tester.pumpAndSettle();
    expect(api.specs.single.characterIds, ['second', 'manual']);
    expect(api.approvals, 0);
  });
}
