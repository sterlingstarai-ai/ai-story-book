import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

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
        final shipping =
            payload['shipping_address'] as Map<String, dynamic>;
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
  });
}
