// Opt-in native test with bundled artwork, a private temporary cache, and HTTP loopback.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/widgets/scoped_book_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _CoverUser extends UserService {
  _CoverUser(super.preferences);

  @override
  String getUserKey() => 'synthetic-cover-account';
}

Future<void> _until(
  WidgetTester tester,
  bool Function() ready, {
  Duration timeout = const Duration(seconds: 10),
}) async {
  final elapsed = Stopwatch()..start();
  while (!ready() && elapsed.elapsed < timeout) {
    await tester.pump(const Duration(milliseconds: 50));
  }
  expect(ready(), isTrue);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'first cover opens after overlapping detail and media scope requests',
    (tester) async {
      const bookId = 'cover-read';
      const title = '첫 장 시험 동화';
      final art = await rootBundle.load('assets/branding/creation-garden.jpg');
      final cache = await Directory.systemTemp.createTemp('asb-cover-open-');
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final registry = BookMediaRegistry(
        prefs,
        baseDirectory: () async => cache,
      );
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://127.0.0.1:${server.port}';
      const coverPath =
          '/books/jobs/job_cover/0123456789abcdef0123456789abcdef.jpg';
      final releaseScope = Completer<void>();
      final requests = <String>[];
      final api = ApiClient(
        baseUrl: base,
        userKey: _CoverUser(prefs).getUserKey(),
        enableLogging: false,
      );
      addTearDown(() async {
        if (!releaseScope.isCompleted) releaseScope.complete();
        await server.close(force: true);
        api.close();
        await registry.close();
        await cache.delete(recursive: true);
      });
      server.listen((request) async {
        final response = request.response;
        final path = request.uri.path;
        if (path == coverPath) {
          requests.add('cover');
          response.headers.contentType = ContentType('image', 'jpeg');
          response.add(
            art.buffer.asUint8List(art.offsetInBytes, art.lengthInBytes),
          );
        } else {
          response.headers.contentType = ContentType.json;
          Object body = const <String, Object>{};
          if (path == '/v1/account/media-scope') {
            requests.add('scope');
            await releaseScope.future;
            body = {'scope_id': 'a' * 64};
          } else if (path == '/v1/books/$bookId/detail') {
            requests.add('detail');
            body = {
              'book_id': bookId,
              'title': title,
              'cover_image_url': '$base$coverPath?X-Amz-Signature=fixture',
              'pages': [
                {'page_number': 1, 'text': '시험 본문', 'image_url': ''},
              ],
            };
          }
          response.write(jsonEncode(body));
        }
        await response.close();
      });
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiBaseUrlProvider.overrideWithValue(base),
            apiClientProvider.overrideWithValue(api),
            userServiceProvider.overrideWithValue(_CoverUser(prefs)),
            bookMediaRegistryProvider.overrideWithValue(registry),
          ],
          child: const MaterialApp(
            locale: Locale('ko'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: ViewerScreen(bookId: bookId),
          ),
        ),
      );
      await _until(
        tester,
        () => requests.contains('scope') && requests.contains('detail'),
        timeout: const Duration(seconds: 3),
      );
      expect(requests, unorderedEquals(['scope', 'detail']));
      expect(find.text(title), findsNothing);
      releaseScope.complete();
      await _until(
        tester,
        () => find
            .byWidgetPredicate(
              (widget) => widget is RawImage && widget.image != null,
            )
            .evaluate()
            .isNotEmpty,
      );
      expect(requests, unorderedEquals(['scope', 'detail', 'cover']));
      final container = ProviderScope.containerOf(
        tester.element(find.byType(ViewerScreen)),
        listen: false,
      );
      expect(
        container.read(bookMediaStoreProvider).requireValue.serverVerified,
        isTrue,
      );
      await tester.pumpWidget(const SizedBox.shrink());
    },
    skip: !const bool.fromEnvironment('RUN_LOCAL_SIGNED_ILLUSTRATION'),
  );

  for (final initialStatus in [HttpStatus.ok, HttpStatus.forbidden]) {
    testWidgets(
      'signed illustration renders after HTTP $initialStatus',
      (tester) async {
        const bookId = 'synthetic-signed-book';
        const firstKey = Key('initial-illustration');
        const secondKey = Key('renewed-illustration');
        final asset = await rootBundle.load(
          'assets/branding/creation-garden.jpg',
        );
        final art = asset.buffer.asUint8List(
          asset.offsetInBytes,
          asset.lengthInBytes,
        );
        final cache = await Directory.systemTemp.createTemp(
          'asb-signed-illustration-',
        );
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();
        final store = BookMediaStore(
          prefs,
          baseDirectory: () async => cache,
          scopeDigest: 'a' * 64,
        );
        final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
        final release = Completer<void>();
        addTearDown(() async {
          if (!release.isCompleted) release.complete();
          await server.close(force: true);
          await store.shutdown();
          await cache.delete(recursive: true);
        });
        final signatures = <String>[];
        server.listen((request) async {
          final signature = request.uri.queryParameters['X-Amz-Signature']!;
          signatures.add(signature);
          if (signature == 'old') await release.future;
          final response = request.response;
          response.statusCode = signature == 'old'
              ? initialStatus
              : HttpStatus.ok;
          if (response.statusCode == HttpStatus.ok) {
            response.headers.contentType = ContentType('image', 'jpeg');
            response.contentLength = art.length;
            response.add(art);
          }
          await response.close();
        });

        final base =
            'http://127.0.0.1:${server.port}/books/jobs/job_fixture/'
            '0123456789abcdef0123456789abcdef.jpg'
            '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=';
        ScopedBookImage illustration(Key key, String signature) =>
            ScopedBookImage(
              key: key,
              bookId: bookId,
              imageUrl: '$base$signature',
              width: 150,
              height: 150,
              placeholder: const Text('Waiting'),
              error: const Text('Image unavailable'),
            );
        final showingRenewal = ValueNotifier(false);
        addTearDown(showingRenewal.dispose);
        await tester.pumpWidget(
          ProviderScope(
            overrides: [
              bookMediaStoreProvider.overrideWith(
                (ref) async => BookMediaContext(store, serverVerified: true),
              ),
              bookMediaBlockedProvider(bookId).overrideWith((ref) => false),
            ],
            child: MaterialApp(
              home: Scaffold(
                body: ValueListenableBuilder<bool>(
                  valueListenable: showingRenewal,
                  builder: (_, renewed, _) => Column(
                    children: [
                      illustration(firstKey, 'old'),
                      if (renewed) illustration(secondKey, 'new'),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
        await _until(tester, () => signatures.isNotEmpty);
        expect(signatures, ['old']);

        showingRenewal.value = true;
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.byKey(secondKey), findsOneWidget);
        expect(signatures, ['old']);
        release.complete();

        final decoded = find.descendant(
          of: find.byKey(secondKey),
          matching: find.byWidgetPredicate(
            (widget) => widget is RawImage && widget.image != null,
          ),
        );
        await _until(tester, () => decoded.evaluate().isNotEmpty);
        expect(signatures, [
          'old',
          if (initialStatus == HttpStatus.forbidden) 'new',
        ]);
        await tester.pumpWidget(const SizedBox.shrink());
      },
      skip: !const bool.fromEnvironment('RUN_LOCAL_SIGNED_ILLUSTRATION'),
    );
  }
}
