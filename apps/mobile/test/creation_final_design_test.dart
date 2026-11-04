import 'dart:async';
import 'dart:typed_data';

import 'support/design_capture.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/models/book_spec.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/branch_story_screen.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/screens/inpaint_screen.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/voice_profiles_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/character_source_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Characters extends CharactersNotifier {
  @override
  Future<List<Character>> build() async => [];
}

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'design-fixture');
  int voiceCalls = 0;
  bool failVoices = false;
  int choiceCalls = 0;

  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor, BookStyle.cartoon]);

  @override
  Future<Map<String, dynamic>> getVoiceProfiles() async {
    voiceCalls++;
    if (failVoices) throw StateError('private technical detail');
    return {'profiles': <Map<String, dynamic>>[]};
  }

  @override
  Future<Map<String, dynamic>> getBranchStoryGraph(String bookId) async => {
        'nodes': [
          {'node_key': 'start', 'page_number': 1, 'text': '별을 찾아 함께 떠났어요.'},
          {
            'node_key': 'private_internal_end',
            'page_number': 2,
            'text': '친구가 기다리고 있었어요.'
          },
        ],
        'edges': [
          {
            'from_node_key': 'start',
            'to_node_key': 'private_internal_end',
            'option_text': '함께 이야기를 나누며 반짝이는 별빛이 가득한 아주 먼 산 너머로 가요'
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> chooseBranchStoryOption(
    String bookId, {
    required String currentNodeKey,
    String? optionText,
    String? toNodeKey,
  }) async {
    choiceCalls++;
    return {
      'next_node': {
        'node_key': 'private_internal_end',
        'page_number': 2,
        'text': '친구가 기다리고 있었어요.'
      },
      'next_options': [],
      'status': 'end',
    };
  }
}

void _smallScreen(WidgetTester tester) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(320, 480);
  tester.platformDispatcher.textScaleFactorTestValue = 1.4;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.platformDispatcher.clearTextScaleFactorTestValue();
  });
}

Future<Widget> _app(
  Widget child, {
  String language = 'ko',
  Brightness brightness = Brightness.light,
  _Api? api,
  Map<String, dynamic> capabilities = const {'audio_supported': true},
  List<Override> overrides = const [],
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  return designCaptureBoundary(ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api ?? _Api()),
      capabilitiesProvider.overrideWith((ref) async => capabilities),
      charactersProvider.overrideWith(_Characters.new),
      ...overrides,
    ],
    child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(brightness),
      locale: Locale(language),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: child,
    ),
  ));
}

void main() {
  testWidgets('first-book age preview compares the same scene before creation',
      (tester) async {
    tester.view.physicalSize = const Size(393, 852);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(await _app(
      const CreateScreen(),
      capabilities: const {'free_first_book_trial': true},
    ));
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.createAgeHelp3to5), findsOneWidget);
    expect(find.text(l.createAgePreview3to5), findsNothing);
    await tester.tap(find.text(l.createAgePreviewTitle));
    await tester.pumpAndSettle();
    expect(find.text(l.createAgePreview3to5), findsOneWidget);
    await tester.tap(find.widgetWithText(ChoiceChip, l.libraryAge5to7));
    await tester.pumpAndSettle();
    expect(find.text(l.createAgeHelp5to7), findsOneWidget);
    expect(find.text(l.createAgePreview5to7), findsOneWidget);
    await tester.tap(find.widgetWithText(ChoiceChip, l.libraryAge7to9));
    await tester.pumpAndSettle();
    expect(find.text(l.createAgePreview7to9), findsOneWidget);
    expect(find.text(l.createAgePreview3to5), findsNothing);
    await captureDesign(tester, 'creation-age-preview-7-to-9');
  });

  setUpAll(loadDesignFonts);
  for (final language in ['ko', 'en', 'ja']) {
    for (final brightness in Brightness.values) {
      testWidgets(
          '$language $brightness character form actions stay reachable at 320x480 x1.4',
          (tester) async {
        _smallScreen(tester);
        await tester.pumpWidget(await _app(const CharactersScreen(),
            language: language, brightness: brightness));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        if (language == 'ko') {
          await captureDesign(
              tester, 'creation-characters-empty-${brightness.name}');
        }
        final l = await AppLocalizations.delegate.load(Locale(language));
        await tester.tap(find.byTooltip(l.charactersAddTooltip));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.ensureVisible(find.text(l.charactersOptionTextTitle));
        await tester.tap(find.text(l.charactersOptionTextTitle));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        if (language == 'ko') {
          await captureDesign(
              tester, 'creation-character-form-${brightness.name}');
        }
        final firstRole = find
            .ancestor(
                of: find.text(l.charactersRoleChild),
                matching: find.byType(GestureDetector))
            .first;
        expect(tester.getSize(firstRole).height, greaterThanOrEqualTo(64));
        await tester.tap(firstRole);
        await tester.pump();
        final submit = find.byKey(const Key('character-form-submit'));
        await tester.ensureVisible(submit);
        await tester.pumpAndSettle();
        expect(submit.hitTestable(), findsOneWidget);
        if (language == 'ko') {
          await captureDesign(
              tester, 'creation-character-form-end-${brightness.name}');
        }
        expect(tester.getSize(submit).height, greaterThanOrEqualTo(64));
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        await tester.pumpAndSettle();
      });
    }
  }

  for (final language in ['ko', 'en', 'ja']) {
    testWidgets(
        '$language creation choices and final button remain reachable in dark mode',
        (tester) async {
      _smallScreen(tester);
      await tester.pumpWidget(await _app(const CreateScreen(),
          language: language, brightness: Brightness.dark));
      await tester.pumpAndSettle();
      final l = await AppLocalizations.delegate.load(Locale(language));
      expect(tester.takeException(), isNull);
      if (language == 'ko') {
        await captureDesign(tester, 'creation-book-form-dark');
      }
      await tester.scrollUntilVisible(find.text(l.createForbiddenRude), 240,
          scrollable: find.byType(Scrollable).first);
      await tester.pumpAndSettle();
      final chip = find.widgetWithText(FilterChip, l.createForbiddenRude);
      expect(tester.getSize(chip).height, greaterThanOrEqualTo(64));
      expect(chip.hitTestable(), findsOneWidget);
      final submit = find.widgetWithText(ElevatedButton, l.createMakeButton);
      expect(submit.hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (language == 'ko') {
        await captureDesign(tester, 'creation-book-form-end-dark');
      }
    });
  }

  testWidgets('voice list failure has retry and no technical payload',
      (tester) async {
    _smallScreen(tester);
    final api = _Api()..failVoices = true;
    await tester.pumpWidget(await _app(const VoiceProfilesScreen(),
        api: api, brightness: Brightness.dark));
    await tester.pumpAndSettle();
    expect(find.textContaining('private technical'), findsNothing);
    await captureDesign(tester, 'creation-voices-error-dark');
    final retry = find.widgetWithText(ElevatedButton, '다시 시도');
    await tester.ensureVisible(retry);
    api.failVoices = false;
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(api.voiceCalls, 2);
    expect(find.byIcon(Icons.add), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('saved voice management hides unsupported collection on small screens',
      (tester) async {
    _smallScreen(tester);
    await tester.pumpWidget(
        await _app(const VoiceProfilesScreen(), brightness: Brightness.dark));
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.add), findsNothing);
    expect(find.byType(TextFormField), findsNothing);
    expect(find.text('저장된 음성 관리'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('long branch choice wraps and previous/restart remain reachable',
      (tester) async {
    _smallScreen(tester);
    final api = _Api();
    await tester.pumpWidget(await _app(
        const BranchStoryScreen(bookId: 'fixture'),
        api: api,
        brightness: Brightness.dark));
    await tester.pumpAndSettle();
    expect(find.textContaining('start'), findsNothing);
    final option = find.widgetWithText(
        ElevatedButton, '함께 이야기를 나누며 반짝이는 별빛이 가득한 아주 먼 산 너머로 가요');
    await tester.ensureVisible(option);
    await tester.pumpAndSettle();
    expect(tester.getSize(option).height, greaterThanOrEqualTo(64));
    await captureDesign(tester, 'creation-branch-choice-dark');
    await tester.tap(option);
    await tester.pumpAndSettle();
    expect(api.choiceCalls, 1);
    expect(find.textContaining('private_internal_end'), findsNothing);
    final restart = find.widgetWithText(OutlinedButton, '처음부터');
    await tester.ensureVisible(restart);
    await tester.pumpAndSettle();
    expect(restart.hitTestable(), findsOneWidget);
    await tester.tap(restart);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('preset sheet retries and scrolls to the final preset',
      (tester) async {
    _smallScreen(tester);
    var attempts = 0;
    await tester.pumpWidget(await _app(
        const Scaffold(body: CharacterSourceSheet()),
        brightness: Brightness.dark,
        overrides: [
          characterPresetsProvider('ko').overrideWith((ref) async {
            attempts++;
            if (attempts == 1) throw StateError('fixture');
            return List.generate(12,
                (index) => {'preset_id': '$index', 'name': '이야기 친구 $index'});
          })
        ]));
    await tester.pumpAndSettle();
    final retry = find.text('다시 시도');
    await tester.ensureVisible(retry);
    await tester.tap(retry);
    await tester.pumpAndSettle();
    final last = find.byKey(const Key('preset_11'));
    await tester.ensureVisible(last);
    await tester.pumpAndSettle();
    expect(last.hitTestable(), findsOneWidget);
    await captureDesign(tester, 'creation-preset-sheet-end-dark');
    expect(tester.getSize(last).height, greaterThanOrEqualTo(64));
    expect(attempts, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('inpaint prompt and apply remain reachable with the keyboard',
      (tester) async {
    _smallScreen(tester);
    await tester.pumpWidget(await _app(
        InpaintScreen(
            imageProvider: MemoryImage(Uint8List(0)),
            jobId: 'fixture',
            bookId: 'fixture',
            pageNumber: 1,
            imageUrl: 'http://127.0.0.1:1/image'),
        brightness: Brightness.dark));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    final prompt = find.byType(TextField);
    await tester.ensureVisible(prompt);
    await tester.enterText(prompt, '별빛을 따뜻하게 바꿔 주세요');
    tester.view.viewInsets = const FakeViewPadding(bottom: 140);
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    final apply = find.widgetWithText(ElevatedButton, l.inpaintApply);
    await tester.ensureVisible(apply);
    await tester.pump();
    expect(apply.hitTestable(), findsOneWidget);
    await captureDesign(tester, 'creation-inpaint-keyboard-dark');
    expect(tester.widget<ElevatedButton>(apply).onPressed, isNull,
        reason: 'An unloaded illustration cannot be edited.');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  });

  testWidgets(
      'unknown loading stage stays user-friendly and reduced motion settles',
      (tester) async {
    _smallScreen(tester);
    tester.platformDispatcher.accessibilityFeaturesTestValue =
        const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
    await tester.pumpWidget(await _app(const LoadingScreen(jobId: 'fixture'),
        brightness: Brightness.dark,
        overrides: [
          jobPollingProvider('fixture').overrideWith((ref) => Stream.value(
              JobStatus(
                  jobId: 'fixture',
                  status: JobState.running,
                  progress: 40,
                  currentStep: 'backend_internal_stage'))),
        ]));
    await tester.runAsync(() => precacheImage(
        const AssetImage('assets/branding/creation-garden.jpg'),
        tester.element(find.byType(LoadingScreen))));
    await tester.pumpAndSettle();
    expect(find.text('backend_internal_stage'), findsNothing);
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.loadingStepPreparing), findsOneWidget);
    await captureDesign(tester, 'creation-loading-dark-reduced-motion');
    expect(tester.takeException(), isNull);
  });

  testWidgets('sample art and real progress fit the normal phone layout',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(await _app(const LoadingScreen(jobId: 'fixture'),
        brightness: Brightness.light,
        overrides: [
          jobPollingProvider('fixture').overrideWith((ref) => Stream.value(
              JobStatus(
                  jobId: 'fixture',
                  status: JobState.running,
                  progress: 72,
                  currentStep: 'generate_images'))),
        ]));
    await tester.runAsync(() => precacheImage(
        const AssetImage('assets/branding/creation-garden.jpg'),
        tester.element(find.byType(LoadingScreen))));
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.loadingIllustrationExample), findsOneWidget);
    expect(find.text(l.loadingStepGenerateImages), findsOneWidget);
    expect(find.text('72%'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await captureDesign(tester, 'creation-loading-light');
  });
}
