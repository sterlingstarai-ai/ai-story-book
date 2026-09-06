// Opt-in real backend acceptance. No generation, purchase, or external message is
// sent. Fixture credentials stay in the ignored JSON file and in process memory.
// flutter test -d macos integration_test/live_backend_flow_test.dart \
//   --dart-define=LIVE_FIXTURE_PATH=/absolute/private-fixture.json
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/main.dart' show buildAppRoute;
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const fixturePath = String.fromEnvironment('LIVE_FIXTURE_PATH');
  testWidgets(
      'live backend library, full reading, free PDF gate, and revocable sharing',
      (tester) async {
    const viewportWidth = int.fromEnvironment('LIVE_VIEWPORT_WIDTH');
    const viewportHeight = int.fromEnvironment('LIVE_VIEWPORT_HEIGHT');
    if (viewportWidth > 0 && viewportHeight > 0) {
      tester.view.physicalSize =
          Size(viewportWidth.toDouble(), viewportHeight.toDouble());
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }
    const probeNativeStorage = bool.fromEnvironment('PROBE_NATIVE_STORAGE');
    if (probeNativeStorage) {
      const secure = FlutterSecureStorage();
      final probeKey =
          'acceptance_probe_${DateTime.now().microsecondsSinceEpoch}';
      try {
        await secure.write(key: probeKey, value: 'synthetic-probe');
        expect(await secure.read(key: probeKey), 'synthetic-probe');
      } finally {
        await secure.delete(key: probeKey);
      }
    }
    final fixtureFile = File(fixturePath);
    final fixture =
        jsonDecode(await fixtureFile.readAsString()) as Map<String, dynamic>;
    final api = ApiClient(
        baseUrl: fixture['base_url'] as String,
        userKey: fixture['user_key'] as String,
        enableLogging: false);
    addTearDown(api.close);
    final bookId = fixture['book_id'] as String;
    final book = await api.getBook(bookId);
    expect(book.pages.length, greaterThanOrEqualTo(8));
    SharedPreferences.setMockInitialValues({
      ParentalControlService.consentGrantedKey: true,
      ParentalControlService.onboardingDoneKey: true,
    });
    final prefs = await SharedPreferences.getInstance();
    final parent = ParentalControlService()..markAgeGateVerified();
    final boundary = GlobalKey();
    final container = ProviderContainer(overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
      parentalControlServiceProvider.overrideWithValue(parent),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
        container: container,
        child: RepaintBoundary(
            key: boundary,
            child: MaterialApp(
                locale: const Locale('ko'),
                localizationsDelegates: AppLocalizations.localizationsDelegates,
                supportedLocales: AppLocalizations.supportedLocales,
                theme: ThemeData(useMaterial3: true, fontFamily: 'Pretendard'),
                debugShowCheckedModeBanner: false,
                initialRoute: '/library',
                onGenerateRoute: buildAppRoute))));
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    Future<void> until(bool Function() ready) async {
      for (var i = 0; i < 200 && !ready(); i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(ready(), true);
    }

    Future<void> screenshot(String name) async {
      await tester.pump(const Duration(milliseconds: 600));
      final render =
          boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await render.toImage(pixelRatio: 1);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      await File('${fixtureFile.parent.path}/$name.png')
          .writeAsBytes(data!.buffer.asUint8List());
      image.dispose();
    }

    await until(() => find.text(book.title).evaluate().isNotEmpty);
    await tester.ensureVisible(find.text(book.title).first);
    await tester.pumpAndSettle();
    await until(() => find
        .byType(RawImage)
        .evaluate()
        .any((e) => (e.widget as RawImage).image != null));
    await screenshot('app-library');
    await tester.tap(find.text(book.title).first);
    await until(() =>
        find.byType(ViewerScreen).evaluate().isNotEmpty &&
        find.byType(PageView).evaluate().isNotEmpty);
    await until(() => find
        .byType(RawImage)
        .evaluate()
        .any((e) => (e.widget as RawImage).image != null));
    await until(() => find
        .descendant(
            of: find.byType(ViewerScreen), matching: find.byType(RawImage))
        .evaluate()
        .any((e) => (e.widget as RawImage).image != null));
    await tester.pump(const Duration(seconds: 2));
    await screenshot('app-cover');

    await tester.tap(find.byTooltip(l.viewerMoreOptionsTooltip));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text(l.viewerExportPdf));
    await tester.tap(find.text(l.viewerExportPdf));
    await until(() => find.text(l.creditBetaLimitTitle).evaluate().isNotEmpty);
    await screenshot('app-free-pdf-gate');
    await tester.ensureVisible(find.text(l.creditShortageClose));
    await tester.tap(find.text(l.creditShortageClose));
    await tester.pumpAndSettle();

    for (var page = 1; page <= book.pages.length; page++) {
      await tester.drag(find.byType(PageView), const Offset(-600, 0));
      await tester.pump(const Duration(milliseconds: 650));
      final pageView = tester.widget<PageView>(find.byType(PageView));
      expect(pageView.controller!.page!.round(), page);
      await until(
          () => find.byType(CircularProgressIndicator).evaluate().isEmpty);
      if (page == 1 || page == 4) {
        await screenshot('app-page-${page.toString().padLeft(2, '0')}');
      }
    }
    final finishReading = find.byKey(const Key('viewer-finish-reading'));
    await tester.ensureVisible(finishReading);
    await tester.tap(finishReading);
    await tester.pump(const Duration(milliseconds: 650));
    await until(() => find.text(l.viewerCompletionTitle).evaluate().isNotEmpty);
    await screenshot('app-reading-complete');

    final share = await api.createShareLink(bookId, expiresInDays: 1);
    final sharedUrl = Uri.parse(share['url'] as String);
    final http = HttpClient();
    addTearDown(http.close);
    final shared = await (await http.getUrl(sharedUrl)).close();
    expect(shared.statusCode, 200);
    await shared.drain<void>();
    await api.revokeShareLink(bookId);
    final revoked = await (await http.getUrl(sharedUrl)).close();
    expect(revoked.statusCode, anyOf(404, 410));
    await revoked.drain<void>();
    await File('${fixtureFile.parent.path}/mobile-verification.json')
        .writeAsString(const JsonEncoder.withIndent('  ').convert({
      'status': 'passed',
      'platform': Platform.operatingSystem,
      'source':
          'real local FastAPI/PostgreSQL/Celery/private S3 fixture; real saved AI book',
      'library_opened': true,
      'story_pages_read': book.pages.length,
      'free_pdf_gate_shown': true,
      'share_http_open_and_revoke': true,
      'credentials': 'in-memory fixture only; no secure-store overwrite',
      'not_exercised': [
        'Android/iOS secure storage',
        'native outbound sharing',
        'store purchases'
      ],
    }));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
  }, skip: fixturePath.isEmpty);
}
