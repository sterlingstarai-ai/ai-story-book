// Opt-in native UI + real local HTTP acceptance. Use only the isolated mock-AI
// preview API. Preferences and user identity are unique/in-memory; production
// Keychain credentials and notifications are never changed.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/screens.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/notification_scheduler.dart';
import 'package:ai_story_book/services/review_service.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:ai_story_book/widgets/content_report_sheet.dart';

class _IsolatedUser extends UserService {
  _IsolatedUser(super.preferences, {String? trialOwner})
    : key = trialOwner ?? const Uuid().v4();
  final String key;
  @override
  String getUserKey() => key;
}

class _NoNotifications implements NotificationScheduler {
  @override
  Future<void> initialize() async {}
  @override
  Future<bool> requestPermissions() async => false;
  @override
  Future<void> cancelBedtime() async {}
  @override
  Future<void> scheduleDailyBedtime({
    required int hour,
    required int minute,
    required String title,
    required String body,
    required String channelName,
    required String channelDescription,
  }) async {}
}

// Flutter's test pointer events cannot dismiss a native StoreKit rating sheet.
// Keep native review requests out of this synthetic journey and its captures.
class _NoStoreReview extends ReviewService {
  @override
  Future<void> requestReviewIfEligible(SharedPreferences prefs) async {}
}

class _LocalJourneyApi extends ApiClient {
  _LocalJourneyApi({
    required super.baseUrl,
    required super.userKey,
    required super.profileId,
    required this.holdCompletion,
  }) : super(enableLogging: false);

  final bool Function() holdCompletion;

  @override
  Future<JobStatus> getBookStatus(
    String jobId, {
    CancelToken? cancelToken,
  }) async {
    final status = await super.getBookStatus(jobId, cancelToken: cancelToken);
    // The mock worker may finish before the first frame. Release its real
    // result only once the waiting flow has moved to the library.
    if (status.isComplete && holdCompletion()) {
      return JobStatus(jobId: jobId, status: JobState.running, progress: 90);
    }
    return status;
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const baseUrl = String.fromEnvironment('FINAL_E2E_LOCAL_API');
  const trialOwner = String.fromEnvironment('FINAL_E2E_TRIAL_OWNER');
  const firstBookTrial = trialOwner != '';
  testWidgets(
    'full local HTTP journey: consent, profile, twelve pages, report, library and settings',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        final endpoint = Uri.parse(baseUrl);
        expect(
          endpoint.scheme == 'http' &&
              endpoint.userInfo.isEmpty &&
              const {
                '127.0.0.1',
                'localhost',
                '10.0.2.2',
              }.contains(endpoint.host),
          isTrue,
          reason:
              'This test creates and deletes a synthetic account; remote hosts are refused.',
        );
        if (firstBookTrial) {
          expect(Uuid.isValidUUID(fromString: trialOwner), isTrue);
        }
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();
        var holdCompletion = firstBookTrial;
        final user = _IsolatedUser(
          prefs,
          trialOwner: firstBookTrial ? trialOwner : null,
        );
        final container = ProviderContainer(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            userServiceProvider.overrideWithValue(user),
            apiBaseUrlProvider.overrideWithValue(baseUrl),
            apiClientProvider.overrideWith((ref) {
              final service = ref.watch(userServiceProvider);
              final api = _LocalJourneyApi(
                baseUrl: baseUrl,
                userKey: service.getUserKey(),
                profileId: service.getActiveProfileId(),
                holdCompletion: () => holdCompletion,
              );
              ref.onDispose(api.close);
              return api;
            }),
            notificationSchedulerProvider.overrideWithValue(_NoNotifications()),
            reviewServiceProvider.overrideWithValue(_NoStoreReview()),
          ],
        );
        final cleanup = ApiClient(
          baseUrl: baseUrl,
          userKey: user.key,
          enableLogging: false,
        );
        final output = Directory(
          '${(await getApplicationDocumentsDirectory()).path}/final-design-e2e',
        );
        await output.create(recursive: true);
        const captureUrl = String.fromEnvironment('FINAL_E2E_ARTIFACTS');
        if (captureUrl.isNotEmpty) {
          expect(
            Uri.parse(captureUrl).host,
            anyOf('127.0.0.1', 'localhost', '10.0.2.2'),
          );
        }
        final boundary = GlobalKey();
        final stages = <String>[];
        addTearDown(() async {
          await tester.pumpWidget(const SizedBox.shrink());
          await tester.pump(const Duration(seconds: 1));
          container.dispose();
          try {
            await cleanup.deleteMyData();
          } finally {
            cleanup.close();
          }
        });
        final caps = await cleanup.getCapabilities();
        expect(caps['audio_supported'], false);
        expect(caps['pod_ordering_supported'], false);
        if (firstBookTrial) {
          expect(caps['free_first_book_trial'], true);
          expect(caps['generation_invitation_supported'], true);
          expect(caps['purchases_supported'], false);
        }
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: RepaintBoundary(
              key: boundary,
              child: Consumer(
                builder: (context, ref, _) => MaterialApp(
                  debugShowCheckedModeBanner: false,
                  theme: buildAppTheme(Brightness.light),
                  darkTheme: buildAppTheme(Brightness.dark),
                  themeMode: ref.watch(appThemeModeProvider),
                  locale: const Locale('ko'),
                  localizationsDelegates:
                      AppLocalizations.localizationsDelegates,
                  supportedLocales: AppLocalizations.supportedLocales,
                  initialRoute: '/startup',
                  onGenerateRoute: buildAppRoute,
                ),
              ),
            ),
          ),
        );
        final l = await AppLocalizations.delegate.load(const Locale('ko'));
        Future<void> until(Finder finder, {int seconds = 30}) async {
          for (var i = 0; i < seconds * 5 && finder.evaluate().isEmpty; i++) {
            await tester.pump(const Duration(milliseconds: 200));
          }
          expect(finder, findsWidgets);
          await tester.pump(const Duration(milliseconds: 400));
          expect(tester.takeException(), isNull);
        }

        Future<void> tap(Finder finder) async {
          await until(finder);
          await tester.ensureVisible(finder.first);
          await tester.pump(const Duration(milliseconds: 200));
          await tester.tap(finder.first);
          await tester.pump(const Duration(milliseconds: 600));
        }

        Future<void> shot(String stage) async {
          await tester.pump(const Duration(milliseconds: 400));
          expect(tester.takeException(), isNull);
          final render =
              boundary.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          final image = await render.toImage(pixelRatio: 1);
          try {
            final data = await image.toByteData(format: ui.ImageByteFormat.png);
            final bytes = data!.buffer.asUint8List();
            await File('${output.path}/$stage.png').writeAsBytes(bytes);
            if (captureUrl.isNotEmpty) {
              final http = HttpClient();
              try {
                final request = await http.putUrl(
                  Uri.parse(
                    '$captureUrl/${Platform.isIOS ? 'ios' : 'android'}/$stage.png',
                  ),
                );
                request.contentLength = bytes.length;
                request.add(bytes);
                final response = await request.close();
                expect(response.statusCode, 201);
                await response.drain<void>();
              } finally {
                http.close();
              }
            }
          } finally {
            image.dispose();
          }
          stages.add(stage);
          await File(
            '${output.path}/stages.txt',
          ).writeAsString(stages.join('\n'));
        }

        Future<void> loadedImage(String label) async {
          final region = find.byWidgetPredicate(
            (w) => w is Semantics && w.properties.label == label,
          );
          await until(
            find.descendant(
              of: region,
              matching: find.byWidgetPredicate(
                (w) => w is RawImage && w.image != null,
              ),
            ),
          );
          await tester.pump(const Duration(seconds: 1));
        }

        Future<void> parentGate() async {
          await until(find.byType(AlertDialog));
          final pattern = RegExp(r'^(\d+)\s*×\s*(\d+)\s*=\s*\?$');
          final question = tester
              .widgetList<Text>(
                find.descendant(
                  of: find.byType(AlertDialog),
                  matching: find.byType(Text),
                ),
              )
              .map((t) => t.data ?? '')
              .singleWhere(pattern.hasMatch);
          final match = pattern.firstMatch(question)!;
          await tester.enterText(
            find.descendant(
              of: find.byType(AlertDialog),
              matching: find.byType(TextField),
            ),
            '${int.parse(match.group(1)!) * int.parse(match.group(2)!)}',
          );
          await tap(find.widgetWithText(ElevatedButton, l.ageGateConfirm));
        }

        await until(find.byType(ConsentScreen));
        await shot('01-consent');
        await tap(find.text(l.consentPrivacyRequired));
        await tap(find.text(l.consentDataProcessingRequired));
        await tap(find.text(l.consentAcceptButton));
        await until(find.byType(OnboardingScreen));
        await shot('02-onboarding');
        for (var i = 0; i < 5 && find.text('다음').evaluate().isNotEmpty; i++) {
          await tap(find.text('다음'));
        }
        await tap(find.text('시작하기'));
        await until(find.byType(HomeScreen));
        await shot('03-empty-home');
        await tap(find.byTooltip('설정'));
        await until(find.byType(SettingsScreen));
        await tap(find.text(l.settingsChildProfile));
        await until(find.byType(ProfilesScreen));
        await tap(find.byTooltip(l.profilesAddTooltip));
        const readerName = '가람';
        await tester.enterText(find.byType(TextField), readerName);
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        await tap(find.text(l.profilesAgeBand57));
        await until(find.text(l.profilesAgeBand79));
        await tap(find.text(l.profilesAgeBand79).last);
        await tap(find.widgetWithText(TextButton, l.profilesAddAction));
        await until(find.text(readerName));
        await shot('04-profile');
        final profiles = await cleanup.getProfiles();
        final profile = (profiles['profiles'] as List).single;
        expect(profile['name'], readerName);
        expect(profile['age_band'], '7-9');
        await tap(find.byType(BackButton));
        await tap(find.byType(BackButton));
        await until(find.byType(HomeScreen));
        await tap(find.byKey(const Key('home_create_book')));
        await until(find.byType(CreateScreen));
        if (firstBookTrial) {
          await until(find.textContaining(l.createFirstBookDuration));
          expect(await cleanup.getCreditsBalance(), 1);
          expect((await cleanup.getAccountMediaScope()).length, 64);
        }
        await tester.enterText(
          find.byType(TextFormField).first,
          '친구와 함께 작은 정원에 꽃을 피우는 이야기',
        );
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        final protagonist = find.byWidgetPredicate(
          (w) =>
              w is TextField && w.decoration?.hintText == l.createChildNameHint,
        );
        await tester.scrollUntilVisible(
          protagonist,
          200,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.ensureVisible(protagonist);
        await tester.enterText(protagonist, readerName);
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pump(const Duration(milliseconds: 300));

        await shot('05-create');
        await tap(find.byType(PrimaryButton));
        if (firstBookTrial) {
          await until(find.byType(LoadingScreen));
          await until(find.text(l.loadingInProgressHint), seconds: 90);
          expect(find.text(l.loadingTitle), findsOneWidget);
        }
        await shot('06-generation');
        if (firstBookTrial) {
          await tap(find.text(l.loadingBrowseLibrary));
          await until(find.byType(LibraryScreen));
          final browse = container.read(libraryBrowseProvider.notifier);
          await browse.setTargetAgeFilter('3-5');
          final openFinishedBook = find.text(l.libraryOpenCompletedStory);
          expect(openFinishedBook, findsNothing);
          holdCompletion = false;
          await until(openFinishedBook, seconds: 90);
          expect(
            container.read(libraryBrowseProvider).valueOrNull?.targetAge,
            '3-5',
          );
          await shot('06b-finished-in-filtered-library');
          await tap(openFinishedBook);
        }
        await until(find.byType(ViewerScreen), seconds: 90);
        await until(find.byType(PageView));
        final scoped = container.read(apiClientProvider);
        final library = await scoped.getLibrary();
        expect(library.books.length, 1);
        if (firstBookTrial) {
          expect(library.books.single.targetAge, '7-9');
          expect(await cleanup.getCreditsBalance(), 0);
        }
        final book = await scoped.getBook(library.books.single.id);
        expect(book.pages.length, 12);
        await loadedImage(l.viewerCoverImageSemantics(book.title));
        await shot('07-cover');
        for (var page = 1; page <= 3; page++) {
          await tap(find.byTooltip(l.viewerNextPageTooltip));
          if (firstBookTrial || page == 3) {
            await loadedImage(l.viewerPageImageSemantics(page));
          }
        }
        await shot('08-reader');
        await tap(find.byTooltip(l.viewerMoreOptionsTooltip));
        await tap(find.text(l.viewerCloseTooltip));
        if (firstBookTrial) {
          await until(find.byType(LibraryScreen));
          await container.read(libraryBrowseProvider.notifier).clearFilters();
          await tap(find.bySemanticsLabel(l.navShellHome));
        }
        await until(find.byType(HomeScreen));
        await tap(find.bySemanticsLabel(l.navShellLibrary));
        await until(find.text(book.title));
        await tap(find.text(book.title));
        await until(find.byType(PageView));
        expect(
          tester
              .widget<PageView>(find.byType(PageView))
              .controller!
              .page!
              .round(),
          3,
        );
        await tap(find.byTooltip(l.viewerMoreOptionsTooltip));
        await tap(find.text(l.reportContentTitle));
        await parentGate();
        await until(find.byType(ContentReportSheet));
        await shot('09-report-form');
        await tap(find.text(l.reportContentImage));
        await tap(find.text(l.reportContentSubmit));
        await until(find.text(l.reportContentReceived));
        await shot('10-report-received');
        await tap(find.text(l.reportContentClose));
        for (var page = 4; page <= 12; page++) {
          await tap(find.byTooltip(l.viewerNextPageTooltip));
          if (firstBookTrial) {
            await loadedImage(l.viewerPageImageSemantics(page));
          }
        }
        expect(find.text(l.viewerCompletionTitle), findsNothing);
        if (firstBookTrial) {
          await tap(find.byTooltip(l.viewerMoreOptionsTooltip));
          await tap(find.text(l.viewerCloseTooltip));
          await until(find.byType(LibraryScreen));
          await tap(find.text(book.title));
          await loadedImage(l.viewerPageImageSemantics(12));
          final controller = tester
              .widget<PageView>(find.byType(PageView))
              .controller;
          expect(controller?.page?.round(), 12);
          expect(find.text(l.viewerCompletionTitle), findsNothing);
          await shot('10b-resumed-last-page');
        }
        await tap(find.byKey(const Key('viewer-finish-reading')));
        await until(find.text(l.viewerCompletionTitle));
        await shot('11-complete');
        await tap(find.text(l.viewerGoToLibrary));
        await until(find.byType(LibraryScreen));
        await shot('12-library');
        await tap(find.bySemanticsLabel(l.navShellHome));
        await tap(find.byTooltip('설정'));
        await until(find.byType(SettingsScreen));
        await tap(find.text(l.settingsDarkMode));
        await tap(find.text(l.settingsSave));
        await until(find.text(l.settingsSaved));
        expect((await scoped.getSettings())['dark_mode'], true);
        await shot('13-settings-dark');
        await tester.scrollUntilVisible(
          find.text(l.settingsParentDashboard),
          -300,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pumpAndSettle();
        await tap(find.text(l.settingsParentDashboard));
        await until(find.byType(ParentDashboardScreen));
        await shot('14-parent-dashboard');
        await tap(find.text(l.parentDashboardSegmentMonthly));
        await shot('15-parent-monthly');
        await tap(find.byType(BackButton));
        await tap(find.text(l.settingsCreditsSubscription));
        await until(find.byType(CreditsScreen));
        await shot('16-credits');
        await tap(find.byType(BackButton));
        await tap(find.byType(BackButton));
        await tap(find.bySemanticsLabel(l.navShellCharacters));
        await until(find.byType(CharactersScreen));
        await shot('17-characters-dark');
        await File('${output.path}/passed.txt').writeAsString(
          'Native UI + local HTTP: passed.\n12 pages, profile, resume, reporting, explicit completion, settings, parent dashboard and disabled store status.\nAI providers mocked; no production/store/payment claim.\n',
        );
      } finally {
        semantics.dispose();
      }
    },
    skip: baseUrl.isEmpty,
    timeout: const Timeout(Duration(minutes: 6)),
  );
}
