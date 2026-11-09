import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/home_screen.dart';
import 'package:ai_story_book/screens/library_screen.dart';
import 'package:ai_story_book/screens/pronunciation_practice_screen.dart';
import 'package:ai_story_book/screens/reading_growth_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/utils/constants.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'support/design_capture.dart';

const _report = GrowthReport(
  booksRead: 7,
  currentStreak: 3,
  longestStreak: 5,
  totalReadingDays: 9,
  vocabLearned: 12,
  quizTotal: 8,
  quizCorrect: 6,
  quizAccuracy: .75,
  completion: .8,
  levelNumber: 4,
  levelKey: 'building_basics',
  levelLabel: '기초 다지기',
  scoreValue: 60,
);
const _peer = PeerComparison(
  ageBand: '5-7',
  peerCount: 42,
  isBaseline: false,
  showRanking: true,
  myBooks: 12,
  peerBooks: 8,
  myVocab: 84,
  peerVocab: 56,
  myAccuracy: .87,
  peerAccuracy: .72,
  myScore: 78,
  peerScore: 60,
  topPercent: 8,
  medal: 'gold',
);
const _streak = HomeStreakSnapshot(
  currentStreak: 2,
  longestStreak: 3,
  totalDays: 4,
  readToday: false,
  todayThemeName: '우정',
  todayTopic: '숲에서 만난 친구',
  todayBookId: 'book-1',
  readDates: {},
);

LibraryBook _book(String id) => LibraryBook(
  id: id,
  title: 'The little rabbit and the garden of wonderful friends',
  coverImageUrl: '',
  targetAge: '7-9',
  style: 'watercolor',
  createdAt: DateTime(2026, 9, 6),
);

class _Library extends LibraryNotifier {
  @override
  Future<List<LibraryBook>> build() async => [_book('book-1')];
}

class _Characters extends CharactersNotifier {
  @override
  Future<List<Character>> build() async => [];
}

class _Browse extends LibraryBrowseNotifier {
  _Browse({this.empty = false});
  final bool empty;
  @override
  Future<LibraryBrowseState> build() async =>
      LibraryBrowseState.initial().copyWith(
        books: empty ? [] : [_book('book-1'), _book('book-2')],
        total: empty ? 0 : 2,
      );
}

class _PracticeApi extends ApiClient {
  _PracticeApi() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test');
  final result = Completer<Map<String, dynamic>>();
  int calls = 0;
  @override
  Future<Map<String, dynamic>> evaluatePronunciation({
    required String bookId,
    required int pageNumber,
    required String transcript,
    String? expectedText,
    String? audioUrl,
  }) {
    calls++;
    return result.future;
  }
}

class _Picker extends FilePicker {
  final result = Completer<FilePickerResult?>();
  int calls = 0;
  @override
  Future<FilePickerResult?> pickFiles({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    bool allowCompression = true,
    int compressionQuality = 30,
    bool allowMultiple = false,
    bool withData = false,
    bool withReadStream = false,
    bool lockParentWindow = false,
    bool readSequential = false,
  }) {
    calls++;
    return result.future;
  }
}

void _smallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(320, 480);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = 1.4;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
}

Widget _harness(
  Widget screen, {
  String language = 'en',
  Brightness brightness = Brightness.light,
  List<Override> overrides = const [],
}) => designCaptureBoundary(
  ProviderScope(
    overrides: overrides,
    child: MaterialApp(
      theme: buildAppTheme(brightness),
      locale: Locale(language),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: screen,
      routes: {
        '/create': (_) => const Scaffold(body: Text('create-destination')),
      },
    ),
  ),
);

Future<void> _scrollTo(WidgetTester tester, Finder finder) async {
  final root = find.byKey(const Key('home_scroll')).evaluate().isNotEmpty
      ? find.byKey(const Key('home_scroll'))
      : find.byType(ListView).first;
  await tester.scrollUntilVisible(
    finder,
    150,
    scrollable: find
        .descendant(of: root, matching: find.byType(Scrollable))
        .first,
    maxScrolls: 50,
  );
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
}

void main() {
  setUpAll(loadDesignFonts);
  setUp(() => FilePicker.platform = _Picker());
  for (final language in ['ko', 'en', 'ja']) {
    for (final brightness in Brightness.values) {
      testWidgets(
        'growth $language $brightness scrolls every section at 320px and 1.4x',
        (tester) async {
          _smallScreen(tester);
          await tester.pumpWidget(
            _harness(
              const ReadingGrowthScreen(),
              language: language,
              brightness: brightness,
              overrides: [
                growthReportProvider.overrideWith((ref) async => _report),
                peerComparisonProvider.overrideWith((ref) async => _peer),
                weeklyReadingTrendProvider.overrideWith(
                  (ref) async => [1, 3, 5, 7],
                ),
              ],
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          expect(find.text('Lv.4'), findsOneWidget);
          await captureDesign(
            tester,
            'reading-growth-$language-${brightness.name}-short',
          );
          for (final key in [
            'growth_weekly_trend',
            'growth_peer_comparison',
            'growth_create_btn',
          ]) {
            await _scrollTo(tester, find.byKey(Key(key)));
          }
          final create = find.byKey(const Key('growth_create_btn'));
          final share = find.byKey(const Key('growth_share_btn'));
          expect(tester.getSize(create).height, greaterThanOrEqualTo(64));
          expect(tester.getSize(share).height, greaterThanOrEqualTo(64));
          await captureDesign(
            tester,
            'reading-growth-$language-${brightness.name}-actions',
          );
          await tester.tap(create);
          await tester.pumpAndSettle();
          expect(find.text('create-destination'), findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  testWidgets('growth error stays readable and retry recovers the report', (
    tester,
  ) async {
    _smallScreen(tester);
    var attempts = 0;
    await tester.pumpWidget(
      _harness(
        const ReadingGrowthScreen(),
        overrides: [
          growthReportProvider.overrideWith((ref) async {
            if (attempts++ == 0) throw StateError('private-debug-details');
            return _report;
          }),
          peerComparisonProvider.overrideWith((ref) async => _peer),
          weeklyReadingTrendProvider.overrideWith((ref) async => []),
        ],
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('private-debug'), findsNothing);
    final retry = find.byType(ElevatedButton);
    expect(retry.hitTestable(), findsOneWidget);
    expect(tester.getSize(retry).height, greaterThanOrEqualTo(64));
    await captureDesign(tester, 'reading-growth-error-short');
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('Lv.4'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'dark home keeps reading cards and the streak panel in dark colors',
    (tester) async {
      _smallScreen(tester);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        _harness(
          const HomeScreen(),
          brightness: Brightness.dark,
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            libraryProvider.overrideWith(_Library.new),
            charactersProvider.overrideWith(_Characters.new),
            homeStreakProvider.overrideWith((ref) async => _streak),
            growthReportProvider.overrideWith((ref) async => _report),
          ],
        ),
      );
      await tester.pumpAndSettle();
      final card = find.byKey(const Key('home_featured_book'));
      final palette = AppPalette.of(tester.element(card));
      final material = tester.widget<Material>(
        find.ancestor(of: card, matching: find.byType(Material)).first,
      );
      expect(material.color, palette.surface);
      await captureDesign(tester, 'reading-home-dark-short');
      await _scrollTo(tester, find.textContaining('2-day'));
      final gradients = tester
          .widgetList<Container>(find.byType(Container))
          .where(
            (w) =>
                w.decoration is BoxDecoration &&
                (w.decoration! as BoxDecoration).gradient != null,
          );
      expect(gradients, isNotEmpty);
      final gradient = (gradients.first.decoration! as BoxDecoration).gradient!;
      expect(gradient.colors, [palette.primaryLight, palette.surface]);
      await captureDesign(tester, 'reading-home-streak-dark-short');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'library long titles and filters remain usable at 320px and 1.4x',
    (tester) async {
      _smallScreen(tester);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        _harness(
          const LibraryScreen(),
          brightness: Brightness.dark,
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            libraryBrowseProvider.overrideWith(_Browse.new),
            activeBookGenerationsProvider.overrideWith((ref) async => []),
          ],
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
      await captureDesign(tester, 'reading-library-dark-short');
      final l = AppLocalizations.of(tester.element(find.byType(LibraryScreen)));
      final menu = find.byTooltip(l.libraryBookOptions).first;
      await tester.ensureVisible(menu);
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.getSize(menu).height, greaterThanOrEqualTo(64));
      await tester.tap(menu);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      final share = find.text(l.libraryMenuShare);
      await tester.ensureVisible(share);
      await tester.pump(const Duration(milliseconds: 300));
      expect(share.hitTestable(), findsOneWidget);
      await captureDesign(tester, 'reading-library-menu-dark-short');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'empty library keeps the first-book action reachable below filters',
    (tester) async {
      _smallScreen(tester);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        _harness(
          const LibraryScreen(),
          brightness: Brightness.dark,
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            libraryBrowseProvider.overrideWith(() => _Browse(empty: true)),
            activeBookGenerationsProvider.overrideWith((ref) async => []),
          ],
        ),
      );
      await tester.pumpAndSettle();
      final l = AppLocalizations.of(tester.element(find.byType(LibraryScreen)));
      final create = find.text(l.libraryCreateNew);
      await tester.ensureVisible(create);
      await tester.pumpAndSettle();
      expect(create.hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
      await captureDesign(tester, 'reading-library-empty-dark-short');
      await tester.tap(create);
      await tester.pumpAndSettle();
      expect(find.text('create-destination'), findsOneWidget);
    },
  );

  testWidgets('practice keeps one pending evaluation and scrolls to feedback', (
    tester,
  ) async {
    _smallScreen(tester);
    final api = _PracticeApi();
    await tester.pumpWidget(
      _harness(
        const PronunciationPracticeScreen(
          bookId: 'book-1',
          pageNumber: 1,
          expectedText: 'The little rabbit visited a garden.',
        ),
        brightness: Brightness.dark,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ),
    );
    await tester.pumpAndSettle();
    final l = AppLocalizations.of(
      tester.element(find.byType(PronunciationPracticeScreen)),
    );
    final transcript = find.widgetWithText(
      TextField,
      l.pronunciationTranscriptLabel,
    );
    await _scrollTo(tester, transcript);
    await tester.enterText(transcript, 'The little rabbit visited a garden.');
    final evaluate = find.byWidgetPredicate(
      (widget) => widget is ElevatedButton,
    );
    await _scrollTo(tester, evaluate);
    expect(tester.getSize(evaluate).height, greaterThanOrEqualTo(64));
    await tester.tap(evaluate);
    await tester.pump();
    expect(api.calls, 1);
    expect(tester.widget<ElevatedButton>(evaluate).onPressed, isNull);
    expect(
      tester.widget<OutlinedButton>(find.byType(OutlinedButton)).onPressed,
      isNull,
    );
    api.result.complete({
      'score': 91.5,
      'feedback': 'A clear and careful reading.',
    });
    await tester.pumpAndSettle();
    await _scrollTo(tester, find.text('A clear and careful reading.'));
    expect(find.text(l.pronunciationScore('91.5')), findsOneWidget);
    await captureDesign(tester, 'reading-practice-result-dark-short');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'audio picker failure recovers and leaving during selection is safe',
    (tester) async {
      final previous = FilePicker.platform;
      addTearDown(() => FilePicker.platform = previous);
      final picker = _Picker();
      FilePicker.platform = picker;
      await tester.pumpWidget(
        _harness(
          const PronunciationPracticeScreen(
            bookId: 'book-1',
            pageNumber: 1,
            expectedText: 'A little rabbit.',
          ),
        ),
      );
      await tester.pumpAndSettle();
      final upload = find.byType(OutlinedButton);
      await tester.ensureVisible(upload);
      await tester.tap(upload);
      await tester.pump();
      expect(tester.widget<OutlinedButton>(upload).onPressed, isNull);
      expect(picker.calls, 1);
      picker.result.completeError(StateError('synthetic-picker-error'));
      await tester.pumpAndSettle();
      expect(tester.widget<OutlinedButton>(upload).onPressed, isNotNull);
      expect(find.textContaining('synthetic-picker'), findsNothing);
      expect(tester.takeException(), isNull);
      final nextPicker = _Picker();
      FilePicker.platform = nextPicker;
      await tester.ensureVisible(upload);
      await tester.tap(upload);
      await tester.pump();
      await tester.pumpWidget(const SizedBox.shrink());
      nextPicker.result.complete(
        FilePickerResult([
          PlatformFile(
            name: 'voice.wav',
            size: 4,
            path: '/tmp/unused-voice.wav',
          ),
        ]),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
}
