import 'dart:async';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Characters extends CharactersNotifier {
  @override
  Future<List<Character>> build() async => [];
}

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'synthetic');
  List<BookStyle> styles = [BookStyle.watercolor, BookStyle.cartoon];
  Completer<GenerationOptions>? pending;
  bool fail = false;
  int optionReads = 0;
  int creditReads = 0;
  BookSpec? created;

  @override
  Future<GenerationOptions> getGenerationOptions() async {
    optionReads++;
    if (pending != null) return pending!.future;
    if (fail) throw StateError('private options failure');
    return GenerationOptions(styles);
  }

  @override
  Future<int> getCreditsBalance() async {
    creditReads++;
    return 3;
  }

  @override
  Future<CreateBookResponse> createBook(BookSpec spec,
      {String? idempotencyKey}) async {
    created = spec;
    return CreateBookResponse(jobId: 'synthetic-job', status: 'queued');
  }
}

Future<void> _pump(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(320, 480);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = 1.4;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
      charactersProvider.overrideWith(_Characters.new),
    ],
    child: MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const CreateScreen(),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('loading-route')),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

Future<void> _show(WidgetTester tester, Finder target,
    {double delta = 160}) async {
  await tester.scrollUntilVisible(target, delta,
      maxScrolls: 60,
      scrollable: find
          .descendant(
              of: find.byType(ListView).first,
              matching: find.byType(Scrollable))
          .first);
  await tester.pumpAndSettle();
}

PrimaryButton _submit(WidgetTester tester) =>
    tester.widget<PrimaryButton>(find.widgetWithText(PrimaryButton, '동화책 만들기'));

void main() {
  test('parsing accepts only server-authorized known styles', () {
    final options = GenerationOptions.fromJson({
      'allowed_styles': ['cartoon', 'future_style']
    });
    expect(options.allowedStyles, [BookStyle.cartoon]);
    for (final invalid in [
      null,
      [],
      ['future_style'],
      [4],
      'watercolor'
    ]) {
      expect(() => GenerationOptions.fromJson({'allowed_styles': invalid}),
          throwsFormatException);
    }
  });

  testWidgets('free choices and sent style come from the server',
      (tester) async {
    final api = _Api();
    await _pump(tester, api);
    await _show(tester, find.byType(TextFormField));
    await tester.enterText(find.byType(TextFormField), '숲속에서 친구를 만나는 토끼 이야기');
    await _show(tester, find.text('카툰'));
    expect(find.widgetWithText(ChoiceChip, '수채화'), findsOneWidget);
    expect(find.widgetWithText(ChoiceChip, '3D'), findsNothing);
    expect(find.widgetWithText(ChoiceChip, '픽셀아트'), findsNothing);
    await tester.tap(find.text('카툰'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('동화책 만들기'));
    await tester.pumpAndSettle();
    expect(api.created?.style, 'cartoon');
    expect(find.text('loading-route'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'paid choices remain available and failed refresh disables generation',
      (tester) async {
    final api = _Api()..styles = BookStyle.values;
    await _pump(tester, api);
    await _show(tester, find.text('3D'));
    expect(find.widgetWithText(ChoiceChip, '3D'), findsOneWidget);
    await tester.tap(find.text('3D'));
    await tester.pumpAndSettle();
    api.fail = true;
    final container =
        ProviderScope.containerOf(tester.element(find.byType(CreateScreen)));
    container.invalidate(generationOptionsProvider);
    await tester.pumpAndSettle();
    expect(_submit(tester).onPressed, isNull);
    expect(find.textContaining('private options failure'), findsNothing);
    expect(api.creditReads, 0);
    api.fail = false;
    api.styles = [BookStyle.watercolor];
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    await _show(tester, find.text('수채화'), delta: -160);
    expect(
        tester
            .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '수채화'))
            .selected,
        isTrue);
    expect(find.widgetWithText(ChoiceChip, '3D'), findsNothing);
    expect(_submit(tester).onPressed, isNotNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('unresolved entitlement lookup never enables creation',
      (tester) async {
    final api = _Api()..pending = Completer<GenerationOptions>();
    await _pump(tester, api);
    expect(_submit(tester).onPressed, isNull);
    expect(find.text('사용 가능한 그림체를 확인하고 있어요.'), findsOneWidget);
    expect(api.creditReads, 0);
    api.pending!.complete(const GenerationOptions([BookStyle.cartoon]));
    await tester.pumpAndSettle();
    expect(_submit(tester).onPressed, isNotNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('quick templates have a real 64px tappable surface',
      (tester) async {
    await _pump(tester, _Api());
    final chip = find.widgetWithText(ActionChip, '동물 친구');
    await _show(tester, chip);
    expect(tester.getSize(chip).height, greaterThanOrEqualTo(64));
    await tester.tap(chip);
    await tester.pumpAndSettle();
    await _show(tester, find.byType(TextFormField));
    expect(
        tester
            .widget<TextFormField>(find.byType(TextFormField))
            .controller!
            .text,
        '용감한 아기 동물이 숲에서 새 친구를 사귀는 이야기');
    expect(tester.takeException(), isNull);
  });

  test('known creation errors give distinct safe next steps in every locale',
      () async {
    for (final language in ['ko', 'en', 'ja']) {
      final l = await AppLocalizations.delegate.load(Locale(language));
      ApiError error(String code) =>
          ApiError(code: code, message: 'private raw detail', statusCode: 400);
      expect(createFailureMessage(l, error('SAFETY_INPUT')),
          l.createSafetyInputHint);
      expect(createFailureMessage(l, error('DAILY_LIMIT_EXCEEDED')),
          l.createDailyLimitHint);
      expect(createFailureMessage(l, error('CONNECTION_ERROR')),
          l.errorConnection);
      expect(createFailureMessage(l, error('UNKNOWN')), l.createFailedSnack);
      expect(createFailureMessage(l, error('SAFETY_OUTPUT')),
          isNot(contains('private')));
    }
  });
}
