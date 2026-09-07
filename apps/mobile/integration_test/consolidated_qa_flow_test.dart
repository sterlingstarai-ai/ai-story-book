// Opt-in native regression against one existing isolated job. This never starts
// generation, uploads photos, buys credits, or deletes the live fixture account.
// Pass --dart-define-from-file=<ignored private-fixture.json> on a QA simulator.
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:ai_story_book/services/local_media_cleanup.dart';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/screens/legal_document_screen.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/services/review_service.dart';
import 'package:ai_story_book/utils/app_theme.dart';

const _base = String.fromEnvironment('base_url');
const _user = String.fromEnvironment('user_key');
const _profile = String.fromEnvironment('profile_id');
const _job = String.fromEnvironment('job_id');
const _artifacts = String.fromEnvironment('NATIVE_QA_ARTIFACTS');

class _NoReview extends ReviewService {
  @override
  Future<void> requestReviewIfEligible(SharedPreferences preferences) async {}
}

class _FixtureUser extends UserService {
  _FixtureUser(super.preferences);
  @override
  String getUserKey() => _user;
  @override
  String? getActiveProfileId() => _profile.isEmpty ? null : _profile;
}

class _FixtureApi extends ApiClient {
  _FixtureApi()
    : super(
        baseUrl: _base,
        userKey: _user,
        profileId: _profile.isEmpty ? null : _profile,
        enableLogging: false,
      );
  BookResult? layoutFixture;
  @override
  Future<BookResult> getBook(String id) async =>
      layoutFixture?.bookId == id ? layoutFixture! : await super.getBook(id);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native policy full text, existing real job completion and enlarged learning-page reading',
    (tester) async {
      expect(Uri.parse(_base).host, anyOf('127.0.0.1', 'localhost'));
      expect(_user.isNotEmpty && _job.isNotEmpty, isTrue);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final cachedFile = await DefaultCacheManager().putFile(
        'https://synthetic.invalid/native-cache-probe',
        Uint8List.fromList([1, 2, 3]),
      );
      expect(await cachedFile.exists(), true);
      await purgeAppImageCache();
      expect(await cachedFile.exists(), false);
      final api = _FixtureApi();
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          userServiceProvider.overrideWithValue(_FixtureUser(prefs)),
          apiClientProvider.overrideWithValue(api),
          reviewServiceProvider.overrideWithValue(_NoReview()),
        ],
      );
      addTearDown(api.close);
      addTearDown(container.dispose);
      final directory = Directory(
        '${(await getApplicationDocumentsDirectory()).path}/consolidated-qa',
      );
      await directory.create(recursive: true);
      final boundary = GlobalKey();
      final scale = ValueNotifier(1.0);
      addTearDown(scale.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: RepaintBoundary(
            key: boundary,
            child: ValueListenableBuilder<double>(
              valueListenable: scale,
              builder: (context, value, _) => MaterialApp(
                debugShowCheckedModeBanner: false,
                locale: const Locale('ko'),
                localizationsDelegates: AppLocalizations.localizationsDelegates,
                supportedLocales: AppLocalizations.supportedLocales,
                theme: buildAppTheme(Brightness.light),
                builder: (context, child) => MediaQuery(
                  data: MediaQuery.of(
                    context,
                  ).copyWith(textScaler: TextScaler.linear(value)),
                  child: child!,
                ),
                onGenerateRoute: buildAppRoute,
                home: const ConsentScreen(),
              ),
            ),
          ),
        ),
      );
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      Future<void> until(
        bool Function() ready, {
        Duration budget = const Duration(seconds: 30),
      }) async {
        final deadline = DateTime.now().add(budget);
        while (!ready() && DateTime.now().isBefore(deadline)) {
          await tester.pump(const Duration(milliseconds: 300));
        }
        expect(ready(), true);
      }

      Future<void> persist(String name, List<int> bytes) async {
        await File('${directory.path}/$name').writeAsBytes(bytes);
        if (_artifacts.isEmpty) return;
        final target = Uri.parse('$_artifacts/$name');
        expect(target.host, anyOf('127.0.0.1', 'localhost'));
        final client = HttpClient();
        try {
          final request = await client.putUrl(target);
          request.contentLength = bytes.length;
          request.add(bytes);
          final response = await request.close();
          expect(response.statusCode, 201);
          await response.drain<void>();
        } finally {
          client.close();
        }
      }

      Future<void> capture(String name) async {
        await tester.pump(const Duration(milliseconds: 400));
        final render =
            boundary.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await render.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await persist('$name.png', bytes!.buffer.asUint8List());
        image.dispose();
      }

      final results = <String, dynamic>{
        'native_logical_width':
            tester.view.physicalSize.width / tester.view.devicePixelRatio,
        'native_logical_height':
            tester.view.physicalSize.height / tester.view.devicePixelRatio,
        'creates_sent_by_this_test': 0,
        'physical_cache_file_removed': true,
        'photo_uploads_sent_by_this_test': 0,
      };
      await until(() => find.byType(ConsentScreen).evaluate().isNotEmpty);
      for (final title in [l.settingsPrivacyPolicy, l.settingsTermsOfService]) {
        await tester.ensureVisible(find.text(title));
        await tester.pumpAndSettle();
        await tester.tap(find.text(title));
        await until(
          () =>
              find.byType(LegalDocumentScreen).evaluate().isNotEmpty &&
              find.text(l.legalDraftNotice).evaluate().isNotEmpty,
        );
        scale.value = 2.35;
        await tester.pumpAndSettle();
        await capture(
          title == l.settingsPrivacyPolicy
              ? 'privacy-native-top'
              : 'terms-native-top',
        );
        final list = find.descendant(
          of: find.byType(LegalDocumentScreen),
          matching: find.byType(Scrollable),
        );
        final state = tester.state<ScrollableState>(list);
        for (var i = 0; i < 100 && state.position.extentAfter > 0; i++) {
          await tester.drag(list, const Offset(0, -500));
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(state.position.extentAfter, lessThan(1));
        await capture(
          title == l.settingsPrivacyPolicy
              ? 'privacy-native-end'
              : 'terms-native-end',
        );
        scale.value = 1;
        await tester.pumpAndSettle();
        await tester.tap(find.byType(BackButton));
        await tester.pumpAndSettle();
      }
      results['policy_full_text_before_consent'] = true;
      final firstStatus = await api.getBookStatus(_job);
      results['attached_job_state'] = firstStatus.status.name;
      results['attached_job_progress'] = firstStatus.progress;
      Navigator.of(tester.element(find.byType(ConsentScreen))).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => const LoadingScreen(jobId: _job),
        ),
      );
      await tester.pump(const Duration(seconds: 1));
      await capture('real-job-attached');
      await until(
        () => find.byType(ViewerScreen).evaluate().isNotEmpty,
        budget: const Duration(minutes: 10),
      );
      await until(
        () => container
            .read(
              bookDetailProvider(
                container
                    .read(jobPollingProvider(_job))
                    .valueOrNull!
                    .result!
                    .bookId,
              ),
            )
            .hasValue,
      );
      final status = await api.getBookStatus(_job);
      expect(status.status, JobState.done);
      final book = status.result!;
      expect(book.pages.length, 12);
      Future<void> illustrationReady() async {
        await until(
          () =>
              tester
                  .widgetList<RawImage>(find.byType(RawImage))
                  .any((widget) => widget.image != null) &&
              find.byType(CircularProgressIndicator).evaluate().isEmpty,
        );
        await tester.pump(const Duration(milliseconds: 600));
      }

      await illustrationReady();
      await capture('real-book-cover');
      for (var pageIndex = 0; pageIndex < book.pages.length; pageIndex++) {
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump(const Duration(milliseconds: 500));
        await illustrationReady();
        if (pageIndex == 0) await capture('real-book-first-page');
        if (pageIndex == book.pages.length - 1) {
          await capture('real-book-last-page');
        }
      }
      results['actual_page_images_rendered'] = book.pages.length;
      for (var pageIndex = 0; pageIndex < book.pages.length; pageIndex++) {
        await tester.tap(find.byIcon(Icons.chevron_left));
        await tester.pump(const Duration(milliseconds: 450));
      }
      var index = book.pages.indexWhere((page) => page.hasLearningContent);
      results['learning_content_source'] = index >= 0
          ? 'real_book'
          : 'synthetic_layout_fixture';
      if (index < 0) {
        final page = book.pages.first;
        api.layoutFixture = BookResult(
          bookId: book.bookId,
          title: book.title,
          coverImageUrl: book.coverImageUrl,
          language: book.language,
          pages: [
            PageResult(
              pageNumber: page.pageNumber,
              text: page.getText(book.language ?? 'ko'),
              imageUrl: page.imageUrl,
              vocab: [VocabItem(word: '친구', meaning: '함께 지내는 사이')],
            ),
            ...book.pages.skip(1),
          ],
        );
        container.invalidate(bookDetailProvider(book.bookId));
        await until(
          () => container.read(bookDetailProvider(book.bookId)).hasValue,
        );
        await tester.pump(const Duration(milliseconds: 500));
        index = 0;
      }
      for (var i = 0; i <= index; i++) {
        await tester.tap(find.byIcon(Icons.chevron_right));
        await tester.pump(const Duration(milliseconds: 450));
      }
      scale.value = 2.35;
      await tester.pumpAndSettle();
      final page = book.pages[index];
      final reader = find.byKey(ValueKey('reader-content-${page.pageNumber}'));
      final scrollable = find.descendant(
        of: reader,
        matching: find.byType(Scrollable),
      );
      final body = tester.state<ScrollableState>(scrollable);
      final initial = body.position.pixels;
      await tester.drag(reader, const Offset(0, -150));
      await tester.pump(const Duration(milliseconds: 300));
      expect(body.position.pixels, greaterThan(initial));
      for (var i = 0; i < 50 && body.position.extentAfter > 0; i++) {
        await tester.drag(reader, const Offset(0, -160));
        await tester.pump(const Duration(milliseconds: 150));
      }
      expect(body.position.extentAfter, lessThan(1));
      final lastLineBottom = tester
          .getRect(find.text(page.getText(book.language ?? 'ko')))
          .bottom;
      final controlsTop = tester
          .getRect(find.byKey(const Key('viewer_learning_bar')))
          .top;
      expect(lastLineBottom, lessThan(controlsTop));
      results.addAll({
        'real_job_reached_viewer': true,
        'book_page_count': book.pages.length,
        'large_text_scale': 2.35,
        'learning_page_number': page.pageNumber,
        'body_bottom': lastLineBottom,
        'learning_controls_top': controlsTop,
        'body_drag_reaches_end': true,
      });
      await capture('learning-layout-large-text-end');
      await persist('result.json', utf8.encode(jsonEncode(results)));
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 1));
    },
    timeout: const Timeout(Duration(minutes: 15)),
    skip: _base.isEmpty,
  );
}
