import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/services/api_client.dart';

void main() {
  group('ApiClient', () {
    test('addCredits sends admin key header and transaction_id payload',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'POST' || request.uri.path != '/v1/credits/add') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');
        expect(request.headers.value('x-admin-key'), 'admin-secret');

        final body = await utf8.decoder.bind(request).join();
        final payload = jsonDecode(body) as Map<String, dynamic>;
        expect(payload['amount'], 7);
        expect(payload['transaction_id'], 'txn_123');

        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'new_balance': 42}));
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final newBalance = await client.addCredits(
        7,
        transactionId: 'txn_123',
        adminKey: 'admin-secret',
      );

      expect(newBalance, 42);
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('createShareLink posts to book share endpoint and parses url',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'POST' ||
            request.uri.path != '/v1/books/book-1/share') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }
        expect(request.headers.value('x-user-key'), 'test-user');
        final body = await utf8.decoder.bind(request).join();
        final payload = jsonDecode(body) as Map<String, dynamic>;
        expect(payload['expires_in_days'], 0);

        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'token': 'tok123',
          'url': 'https://share.x/share/tok123',
          'expires_at': null,
        }));
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final result = await client.createShareLink('book-1');
      expect(result['token'], 'tok123');
      expect(result['url'], 'https://share.x/share/tok123');
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('getCreditsBalance parses numeric string payload', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'GET' ||
            request.uri.path != '/v1/credits/balance') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');

        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'credits': '12'}));
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final credits = await client.getCreditsBalance();

      expect(credits, 12);
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('getCharacters throws on malformed list entries', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'GET' || request.uri.path != '/v1/characters') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');

        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'characters': ['invalid-item'],
            'total': 1,
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      expect(
        () => client.getCharacters(),
        throwsA(isA<FormatException>()),
      );
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('CreateBookResponse.fromJson stringifies non-string values', () {
      final parsed = CreateBookResponse.fromJson({
        'job_id': 12345,
        'status': 1,
      });

      expect(parsed.jobId, '12345');
      expect(parsed.status, '1');
    });

    test('CreateBookResponse.fromJson throws on missing required fields', () {
      expect(
        () => CreateBookResponse.fromJson({'status': 'queued'}),
        throwsA(isA<FormatException>()),
      );
    });

    test('getLibrary sends active profile header when configured', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'GET' || request.uri.path != '/v1/library') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');
        expect(request.headers.value('x-profile-id'), 'profile-1');

        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'books': [],
            'total': 0,
            'next_cursor': null,
            'has_more': false,
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        profileId: 'profile-1',
        enableLogging: false,
      );

      final response = await client.getLibrary();

      expect(response.books, isEmpty);
      expect(response.total, 0);
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('patchSettings sends payload to settings endpoint', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'PATCH' || request.uri.path != '/v1/settings') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');

        final body = await utf8.decoder.bind(request).join();
        final payload = jsonDecode(body) as Map<String, dynamic>;
        expect(payload['language'], 'en');
        expect(payload['dark_mode'], true);
        expect(payload['screen_time_enabled'], true);
        expect(payload['daily_limit_minutes'], 45);

        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'status': 'success'}));
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      await client.patchSettings({
        'language': 'en',
        'dark_mode': true,
        'screen_time_enabled': true,
        'daily_limit_minutes': 45,
      });
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('createPodOrder sends nested shipping address payload', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'POST' || request.uri.path != '/v1/pod/orders') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');

        final body = await utf8.decoder.bind(request).join();
        final payload = jsonDecode(body) as Map<String, dynamic>;
        expect(payload['book_id'], 'book-1');
        expect(payload['quantity'], 2);
        final shipping = payload['shipping_address'] as Map<String, dynamic>;
        expect(shipping['name'], '홍길동');
        expect(shipping['country'], 'KR');

        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'order_id': 'pod_1',
            'status': 'created',
            'provider': 'printful',
            'total_price': 39000,
            'currency': 'KRW',
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final order = await client.createPodOrder(
        bookId: 'book-1',
        quantity: 2,
        shippingAddress: const {
          'name': '홍길동',
          'line1': '서울시 강남구',
          'postal_code': '12345',
          'country': 'KR',
        },
      );

      expect(order['order_id'], 'pod_1');
      expect(order['provider'], 'printful');
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('createPodOrder sends X-Idempotency-Key header (H6)', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      String? seenKey;
      server.listen((request) async {
        seenKey = request.headers.value('x-idempotency-key');
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'order_id': 'pod_1', 'status': 'created'}));
        await request.response.close();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );
      await client.createPodOrder(
        bookId: 'book-1',
        quantity: 1,
        shippingAddress: const {'name': 'A', 'line1': 'B', 'city': 'C',
          'postal_code': '1', 'country': 'KR'},
        idempotencyKey: 'pod-key-1',
      );
      expect(seenKey, 'pod-key-1');
    });

    test('getPodQuote parses region price and currency (H20)', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      server.listen((request) async {
        expect(request.uri.path, '/v1/pod/quote');
        expect(request.uri.queryParameters['country'], 'US');
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'unit_price': 20, 'shipping_fee': 5, 'total_price': 25, 'currency': 'USD'}));
        await request.response.close();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );
      final quote = await client.getPodQuote(country: 'US', quantity: 1);
      expect(quote['total_price'], 25);
      expect(quote['currency'], 'USD');
    });

    test('getBookStatus parses generation warnings and page asset status',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'GET' || request.uri.path != '/v1/books/job-1') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');
        expect(request.headers.value('x-request-id'), isNotNull);

        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'job_id': 'job-1',
            'status': 'done',
            'progress': 100,
            'current_step': '완료',
            'result': {
              'book_id': 'book-1',
              'title': '테스트 동화',
              'language': 'ko',
              'target_age': '5-7',
              'style': 'watercolor',
              'cover_image_url': 'https://placeholder.invalid/cover.png',
              'created_at': '2026-03-07T00:00:00Z',
              'generation_warnings': [
                {
                  'code': 'page_placeholder_image',
                  'message': '일부 페이지 이미지 생성이 실패해 임시 이미지를 표시하고 있습니다.',
                  'asset': 'image',
                  'page_number': 1,
                },
              ],
              'pages': [
                {
                  'page_number': 1,
                  'text': '첫 페이지',
                  'image_url': 'https://placeholder.invalid/page-1.png',
                  'audio_url': null,
                  'asset_status': {
                    'image': {
                      'state': 'degraded',
                      'reason': 'placeholder_image',
                      'url': 'https://placeholder.invalid/page-1.png',
                    },
                    'audio': {
                      'state': 'missing',
                      'reason': 'audio_not_generated',
                    },
                  },
                },
              ],
            },
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final status = await client.getBookStatus('job-1');

      expect(status.status, JobState.done);
      expect(status.result, isNotNull);
      expect(status.result!.hasGenerationWarnings, isTrue);
      expect(
        status.result!.generationWarnings.single.code,
        'page_placeholder_image',
      );
      expect(status.result!.pages.single.hasDegradedImage, isTrue);
      expect(
        status.result!.pages.single.assetStatus['image']?.state,
        'degraded',
      );
      expect(
        status.result!.pages.single.assetStatus['audio']?.state,
        'missing',
      );
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('ApiError keeps requestId from standard error envelope', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'GET' || request.uri.path != '/v1/settings') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        request.response.statusCode = HttpStatus.serviceUnavailable;
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'request_id': 'req-p5-123',
            'error': {
              'code': 'SERVICE_UNAVAILABLE',
              'message': '일시 장애',
            },
            'detail': '일시 장애',
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      try {
        await client.getSettings();
        fail('Expected getSettings to throw');
      } on DioException catch (error) {
        expect(error.error, isA<ApiError>());
        final apiError = error.error as ApiError;
        expect(apiError.requestId, 'req-p5-123');
        expect(apiError.code, 'SERVICE_UNAVAILABLE');
      }
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('evaluatePronunciation sends expected payload and parses response',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      final requestHandled = Completer<void>();
      server.listen((request) async {
        if (request.method != 'POST' ||
            request.uri.path != '/v1/pronunciation/evaluate') {
          request.response.statusCode = HttpStatus.notFound;
          await request.response.close();
          return;
        }

        expect(request.headers.value('x-user-key'), 'test-user');

        final body = await utf8.decoder.bind(request).join();
        final payload = jsonDecode(body) as Map<String, dynamic>;
        expect(payload['book_id'], 'book-1');
        expect(payload['page_number'], 2);
        expect(payload['transcript'], '토끼가 숲속으로 걸어갔어요');
        expect(payload['expected_text'], '토끼가 숲속으로 천천히 걸어갔어요');
        expect(payload['audio_url'], 'https://example.com/audio.m4a');

        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'status': 'success',
            'score': 88.5,
            'feedback': '좋아요',
          }),
        );
        await request.response.close();
        requestHandled.complete();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );

      final result = await client.evaluatePronunciation(
        bookId: 'book-1',
        pageNumber: 2,
        transcript: '토끼가 숲속으로 걸어갔어요',
        expectedText: '토끼가 숲속으로 천천히 걸어갔어요',
        audioUrl: 'https://example.com/audio.m4a',
      );

      expect(result['status'], 'success');
      expect(result['score'], 88.5);
      await requestHandled.future.timeout(const Duration(seconds: 1));
    });

    test('createSeriesBook sends style/target_age/language (H19)', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));

      Map<String, dynamic>? seen;
      server.listen((request) async {
        final body = await utf8.decoder.bind(request).join();
        seen = jsonDecode(body) as Map<String, dynamic>;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'job_id': 'j1', 'status': 'queued'}));
        await request.response.close();
      });

      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-user',
        enableLogging: false,
      );
      await client.createSeriesBook(
        characterId: 'c1', topic: 't', previousBookId: 'b0',
        style: '3d', targetAge: '7-9', language: 'en',
      );
      expect(seen!['style'], '3d');
      expect(seen!['target_age'], '7-9');
      expect(seen!['language'], 'en');
    });
  });
}
