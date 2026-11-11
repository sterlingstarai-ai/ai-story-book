import 'dart:ui' show SemanticsAction;

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'support/design_capture.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test');
  final reads = <bool>[];
  int answers = 0;
  @override
  Future<Map<String, dynamic>> getSettings() async => {
    'allow_kakao_share': false,
  };
  @override
  Future<Map<String, dynamic>> getStreakInfo() async => {'current_streak': 1};
  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async {
    reads.add(completed);
    return {};
  }

  @override
  Future<Map<String, dynamic>> recordQuizAnswer({
    required String bookId,
    required String quizType,
    required bool correct,
    int? pageNumber,
    int? questionIndex,
    String? term,
    String? userAnswer,
  }) async {
    answers++;
    return {};
  }
}

const _story = 'The little rabbit  visited a garden.\nFriends welcomed him.';
const _word = 'A wonderful friendship';
const _meaning = 'Friends care for each other and share the things they enjoy.';
const _option =
    'They welcomed the little rabbit with kindness and a warm smile.';

BookResult _book() => BookResult.fromJson({
  'book_id': 'book-1',
  'title': 'The garden of friends',
  'language': 'en',
  'cover_image_url': '',
  'pages': [
    {
      'page_number': 1,
      'text': _story,
      'image_url': '',
      'vocab': [
        {'word': _word, 'meaning': _meaning},
      ],
      'comprehension_questions': [
        {
          'question': 'How did the friends help each other?',
          'answer': _meaning,
        },
      ],
      'quiz': [
        {
          'question': 'How did the friends welcome the rabbit?',
          'options': [_option, 'They went to sleep.'],
          'answer_index': 0,
          'explanation': _meaning,
        },
      ],
    },
  ],
});

Future<_Api> _pump(
  WidgetTester tester, {
  bool small = true,
  bool cover = false,
  bool iPhone16e = false,
  Size? androidSize,
  double textScale = 1.4,
  BookResult? book,
}) async {
  tester.view.physicalSize =
      androidSize ??
      (iPhone16e
          ? const Size(390, 844)
          : small
          ? const Size(320, 480)
          : const Size(402, 874));
  tester.view.devicePixelRatio = 1;
  // Physical size and DPR are overridden together; normalize the system bars
  // too, rather than treating the real device's 63 physical pixels as 63dp.
  tester.view.padding = iPhone16e
      ? const FakeViewPadding(top: 47, bottom: 34)
      : const FakeViewPadding(top: 24, bottom: 24);
  addTearDown(tester.view.resetPadding);
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  SharedPreferences.setMockInitialValues({
    'review_first_book_completed_v1': true,
  });
  final prefs = await SharedPreferences.getInstance();
  final api = _Api();
  await tester.pumpWidget(
    designCaptureBoundary(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(api),
          bookDetailProvider(
            'book-1',
          ).overrideWith((ref) async => book ?? _book()),
          capabilitiesProvider.overrideWith(
            (ref) async => {'audio_supported': true},
          ),
        ],
        child: MaterialApp(
          theme: buildAppTheme(Brightness.dark),
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: const ViewerScreen(bookId: 'book-1'),
          routes: {
            '/library': (_) =>
                const Scaffold(body: Text('library-destination')),
          },
        ),
      ),
    ),
  );
  await _settle(tester);
  if (!cover) {
    await tester.tap(find.byIcon(Icons.chevron_right));
    await _settle(tester);
  }
  expect(tester.takeException(), isNull);
  return api;
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 4));
}

Future<void> _bodyAction(WidgetTester tester, Finder action) async {
  for (var i = 0; i < 16 && action.hitTestable().evaluate().isEmpty; i++) {
    await tester.timedDrag(
      find.byKey(const ValueKey('reader-content-1')),
      const Offset(0, -150),
      const Duration(milliseconds: 400),
    );
    await _settle(tester);
  }
  expect(action.hitTestable(), findsOneWidget);
}

void main() {
  setUpAll(loadDesignFonts);

  for (final cover in [true, false]) {
    testWidgets(
      'illustration action restores the reading controls (cover=$cover)',
      (tester) async {
        final semantics = tester.ensureSemantics();
        try {
          await _pump(tester, cover: cover);
          final l = AppLocalizations.of(
            tester.element(find.byType(ViewerScreen)),
          );
          final label = cover
              ? l.viewerCoverImageSemantics('The garden of friends')
              : l.viewerPageImageSemantics(1);
          final image = find.bySemanticsLabel(label);
          final controls = find.byKey(const Key('viewer_bottom_controls'));
          var node = tester.getSemantics(image);
          expect(node.hint, l.viewerHideReadingControls);
          expect(
            node.getSemanticsData().hasAction(SemanticsAction.tap),
            isTrue,
          );
          expect(controls, findsOneWidget);
          node.owner!.performAction(node.id, SemanticsAction.tap);
          await _settle(tester);
          expect(controls, findsNothing);

          node = tester.getSemantics(image);
          expect(node.hint, l.viewerShowReadingControls);
          node.owner!.performAction(node.id, SemanticsAction.tap);
          await _settle(tester);
          expect(controls, findsOneWidget);
          expect(tester.getSemantics(image).hint, l.viewerHideReadingControls);
          await _dispose(tester);
        } finally {
          semantics.dispose();
        }
      },
    );
  }

  testWidgets(
    'long cover titles can scroll fully above navigation at accessibility scale',
    (tester) async {
      const title =
          'The little rabbit and the extraordinary garden of friendship';
      await _pump(
        tester,
        cover: true,
        textScale: 2.5,
        book: BookResult(
          bookId: 'book-1',
          title: title,
          coverImageUrl: '',
          pages: _book().pages,
        ),
      );
      final coverTitle = find.text(title);
      expect(coverTitle, findsOneWidget);
      expect(tester.widget<Text>(coverTitle).maxLines, isNull);
      final scroll = find.ancestor(
        of: coverTitle,
        matching: find.byType(SingleChildScrollView),
      );
      final position = tester
          .state<ScrollableState>(
            find.descendant(of: scroll, matching: find.byType(Scrollable)),
          )
          .position;
      position.jumpTo(position.maxScrollExtent);
      await _settle(tester);
      expect(
        tester.getRect(coverTitle).bottom,
        lessThan(tester.getRect(find.byIcon(Icons.chevron_right)).top),
      );
      expect(tester.takeException(), isNull);
      await _dispose(tester);
    },
  );

  testWidgets('the last body line can scroll fully above visible controls', (
    tester,
  ) async {
    final story = List.filled(7, _story).join('\n');
    await _pump(
      tester,
      textScale: 1.6,
      book: BookResult(
        bookId: 'book-1',
        title: 'Readable story',
        coverImageUrl: '',
        pages: [
          PageResult(pageNumber: 1, text: story, imageUrl: ''),
          PageResult(pageNumber: 2, text: 'The end.', imageUrl: ''),
        ],
      ),
    );
    final reader = find.byKey(const ValueKey('reader-content-1'));
    final scrollable = find.descendant(
      of: reader,
      matching: find.byType(Scrollable),
    );
    final position = tester.state<ScrollableState>(scrollable).position;
    expect(position.maxScrollExtent, greaterThan(0));
    position.jumpTo(position.maxScrollExtent);
    await _settle(tester);
    final bodyBottom = tester.getRect(find.text(story)).bottom;
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    expect(bodyBottom, lessThanOrEqualTo(tester.getRect(reader).bottom));
    expect(
      bodyBottom,
      lessThan(tester.getRect(find.text(l.viewerPageIndicator(1, 2))).top),
    );
    expect(tester.takeException(), isNull);
    await _dispose(tester);
  });

  for (final scale in [1.0, 2.0, 1.65, 2.35]) {
    testWidgets(
      'natural body drag reaches last line above learning bar at $scale',
      (tester) async {
        final story = List.filled(
          5,
          '토끼는 숲속을 걸으며 새 친구들을 만났어요. 마지막까지 함께 웃었어요.',
        ).join('\n');
        await _pump(
          tester,
          small: false,
          iPhone16e: scale != 1.0 && scale != 2.0,
          androidSize: scale == 1.0
              ? const Size(360, 640)
              : scale == 2.0
              ? const Size(393, 873)
              : null,
          textScale: scale,
          book: BookResult(
            bookId: 'book-1',
            title: '동화',
            coverImageUrl: '',
            pages: [
              PageResult(
                pageNumber: 1,
                text: story,
                imageUrl: '',
                vocab: [VocabItem(word: '친구', meaning: '함께 지내는 사이')],
              ),
              PageResult(pageNumber: 2, text: '끝', imageUrl: ''),
            ],
          ),
        );
        final reader = find.byKey(const ValueKey('reader-content-1'));
        final state = tester.state<ScrollableState>(
          find.descendant(of: reader, matching: find.byType(Scrollable)),
        );
        final initial = state.position.pixels;
        await tester.timedDrag(
          reader,
          const Offset(0, -120),
          const Duration(milliseconds: 500),
        );
        await _settle(tester);
        expect(state.position.pixels, greaterThan(initial));
        for (var i = 0; i < 30 && state.position.extentAfter > 0; i++) {
          await tester.timedDrag(
            reader,
            const Offset(0, -160),
            const Duration(milliseconds: 400),
          );
          await _settle(tester);
        }
        expect(state.position.extentAfter, lessThan(1));
        expect(
          tester.getRect(find.text(story)).bottom,
          lessThan(
            tester.getRect(find.byKey(const Key('viewer_learning_bar'))).top,
          ),
        );
        expect(tester.takeException(), isNull);
        await _dispose(tester);
      },
    );
  }

  testWidgets('follow reading preserves spaces, newlines and enlarged text', (
    tester,
  ) async {
    await _pump(tester, small: false);
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    await tester.tap(find.byIcon(Icons.more_vert));
    await _settle(tester);
    await tester.tap(find.text(l.viewerFollowReadingOn));
    await _settle(tester);
    final rich = find.byWidgetPredicate(
      (widget) => widget is RichText && widget.text.toPlainText() == _story,
    );
    expect(rich, findsOneWidget);
    expect(tester.widget<RichText>(rich).textScaler.scale(20), 28);
    expect(tester.widget<RichText>(rich).text.style?.fontFamily, 'Pretendard');
    expect(tester.takeException(), isNull);
    await captureDesign(tester, 'reading-viewer-follow-dark');
    await _dispose(tester);
  });

  testWidgets(
    'learning tabs keep long words, 64px choices and one answer per question',
    (tester) async {
      final api = await _pump(tester);
      final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
      await tester.tap(find.byKey(const Key('viewer_learning_bar')));
      await _settle(tester);
      expect(find.text(_word), findsOneWidget);
      await captureDesign(tester, 'reading-viewer-vocabulary-dark-short');
      await tester.ensureVisible(find.text(_meaning));
      await _settle(tester);
      expect(tester.takeException(), isNull);
      await captureDesign(
        tester,
        'reading-viewer-vocabulary-scrolled-dark-short',
      );
      await tester.tap(find.text(l.viewerTabQuiz));
      await _settle(tester);
      final list = find
          .descendant(
            of: find.byType(TabBarView),
            matching: find.byType(Scrollable),
          )
          .last;
      final option = find.text(_option);
      await tester.scrollUntilVisible(option, 100, scrollable: list);
      await Scrollable.ensureVisible(tester.element(option), alignment: 0.5);
      await _settle(tester);
      final optionInk = find
          .ancestor(of: option, matching: find.byType(InkWell))
          .first;
      expect(tester.getSize(optionInk).height, greaterThanOrEqualTo(64));
      await tester.tap(option);
      await _settle(tester);
      final check = find.text(l.viewerCheckAnswer);
      await tester.scrollUntilVisible(check, 100, scrollable: list);
      await _settle(tester);
      expect(check.hitTestable(), findsOneWidget);
      await tester.tap(check);
      await _settle(tester);
      expect(api.answers, 1);
      await tester.ensureVisible(find.text(l.viewerQuizCorrect));
      await _settle(tester);
      await captureDesign(tester, 'reading-viewer-quiz-dark-short');
      expect(tester.takeException(), isNull);
      Navigator.of(tester.element(find.byType(TabBar))).pop();
      await _settle(tester);
      await tester.tap(find.byKey(const Key('viewer_learning_bar')));
      await _settle(tester);
      await tester.tap(find.text(l.viewerTabQuiz));
      await _settle(tester);
      await tester.scrollUntilVisible(option, 100, scrollable: list);
      await Scrollable.ensureVisible(tester.element(option), alignment: 0.5);
      await _settle(tester);
      await tester.tap(option);
      await _settle(tester);
      await tester.scrollUntilVisible(check, 100, scrollable: list);
      await _settle(tester);
      await tester.tap(check);
      await _settle(tester);
      expect(
        api.answers,
        1,
        reason: 'Reopening learning must not duplicate the session answer.',
      );
      await _dispose(tester);
      expect(api.reads, [false]);
    },
  );

  testWidgets(
    'explicit completion scrolls to the library and records one terminal read',
    (tester) async {
      final api = await _pump(tester);
      expect(api.reads, isEmpty);
      final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
      final finish = find.byKey(const Key('viewer-finish-reading'));
      await _bodyAction(tester, finish);
      await tester.tap(finish);
      await _settle(tester);
      expect(api.reads, [true]);
      final library = find.text(l.viewerGoToLibrary);
      await tester.scrollUntilVisible(
        library,
        140,
        scrollable: find
            .descendant(
              of: find.byType(Dialog),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await _settle(tester);
      expect(library.hitTestable(), findsOneWidget);
      final button = find
          .ancestor(of: library, matching: find.byType(OutlinedButton))
          .first;
      expect(tester.getSize(button).height, greaterThanOrEqualTo(64));
      expect(tester.takeException(), isNull);
      await captureDesign(tester, 'reading-viewer-completion-dark-short');
      await tester.tap(library);
      await _settle(tester);
      expect(find.text('library-destination'), findsOneWidget);
      await _dispose(tester);
      expect(
        api.reads,
        [true],
        reason: 'Leaving after finishing must never also record abandoned.',
      );
    },
  );
}
