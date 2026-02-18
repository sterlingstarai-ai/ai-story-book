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
  });
}
