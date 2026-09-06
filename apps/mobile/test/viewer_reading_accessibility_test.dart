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
  Future<Map<String, dynamic>> getSettings() async =>
      {'allow_kakao_share': false};
  @override
  Future<Map<String, dynamic>> getStreakInfo() async => {'current_streak': 1};
  @override
  Future<Map<String, dynamic>> recordReading(
      {required String bookId,
      int readingTime = 0,
      bool completed = false}) async {
    reads.add(completed);
    return {};
  }

  @override
  Future<Map<String, dynamic>> recordQuizAnswer(
      {required String bookId,
      required String quizType,
      required bool correct,
      int? pageNumber,
      int? questionIndex,
      String? term,
      String? userAnswer}) async {
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
            {'word': _word, 'meaning': _meaning}
          ],
          'comprehension_questions': [
            {
              'question': 'How did the friends help each other?',
              'answer': _meaning
            }
          ],
          'quiz': [
            {
              'question': 'How did the friends welcome the rabbit?',
              'options': [_option, 'They went to sleep.'],
              'answer_index': 0,
              'explanation': _meaning
            }
          ],
        }
      ],
    });

Future<_Api> _pump(WidgetTester tester, {bool small = true}) async {
  tester.view.physicalSize =
      small ? const Size(320, 480) : const Size(402, 874);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = 1.4;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  SharedPreferences.setMockInitialValues(
      {'review_first_book_completed_v1': true});
  final prefs = await SharedPreferences.getInstance();
  final api = _Api();
  await tester.pumpWidget(designCaptureBoundary(ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
      bookDetailProvider('book-1').overrideWith((ref) async => _book()),
      capabilitiesProvider
          .overrideWith((ref) async => {'audio_supported': true}),
    ],
    child: MaterialApp(
      theme: buildAppTheme(Brightness.dark),
      locale: const Locale('en'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const ViewerScreen(bookId: 'book-1'),
      routes: {
        '/library': (_) => const Scaffold(body: Text('library-destination'))
      },
    ),
  )));
  await _settle(tester);
  await tester.tap(find.byIcon(Icons.chevron_right));
  await _settle(tester);
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
    await tester.drag(
        find.byKey(const ValueKey('reader-content-1')), const Offset(0, -150));
    await _settle(tester);
  }
  expect(action.hitTestable(), findsOneWidget);
}

void main() {
  setUpAll(loadDesignFonts);

  testWidgets('follow reading preserves spaces, newlines and enlarged text',
      (tester) async {
    await _pump(tester, small: false);
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    await tester.tap(find.byIcon(Icons.more_vert));
    await _settle(tester);
    await tester.tap(find.text(l.viewerFollowReadingOn));
    await _settle(tester);
    final rich = find.byWidgetPredicate(
        (widget) => widget is RichText && widget.text.toPlainText() == _story);
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
        tester, 'reading-viewer-vocabulary-scrolled-dark-short');
    await tester.tap(find.text(l.viewerTabQuiz));
    await _settle(tester);
    final list = find
        .descendant(
            of: find.byType(TabBarView), matching: find.byType(Scrollable))
        .last;
    final option = find.text(_option);
    await tester.scrollUntilVisible(option, 100, scrollable: list);
    await _settle(tester);
    final optionInk =
        find.ancestor(of: option, matching: find.byType(InkWell)).first;
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
    await _settle(tester);
    await tester.tap(option);
    await _settle(tester);
    await tester.scrollUntilVisible(check, 100, scrollable: list);
    await _settle(tester);
    await tester.tap(check);
    await _settle(tester);
    expect(api.answers, 1,
        reason: 'Reopening learning must not duplicate the session answer.');
    await _dispose(tester);
    expect(api.reads, [false]);
  });

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
    await tester.scrollUntilVisible(library, 140,
        scrollable: find
            .descendant(
                of: find.byType(Dialog), matching: find.byType(Scrollable))
            .first);
    await _settle(tester);
    expect(library.hitTestable(), findsOneWidget);
    final button =
        find.ancestor(of: library, matching: find.byType(OutlinedButton)).first;
    expect(tester.getSize(button).height, greaterThanOrEqualTo(64));
    expect(tester.takeException(), isNull);
    await captureDesign(tester, 'reading-viewer-completion-dark-short');
    await tester.tap(library);
    await _settle(tester);
    expect(find.text('library-destination'), findsOneWidget);
    await _dispose(tester);
    expect(api.reads, [true],
        reason: 'Leaving after finishing must never also record abandoned.');
  });
}
