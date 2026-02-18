import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/services/api_client.dart';

void main() {
  group('ApiClient', () {
    test('addCredits sends admin key header and transaction_id payload', () async {
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
  });
}
