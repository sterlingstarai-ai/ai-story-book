import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/services/api_client.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('media scope must be an opaque server-issued value', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    var requests = 0;
    server.listen((request) async {
      requests++;
      expect(request.uri.path, '/v1/account/media-scope');
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({'scope_id': requests == 1 ? 'a' * 64 : 'invalid'}),
      );
      await request.response.close();
    });
    final client = ApiClient(
      baseUrl: 'http://${server.address.host}:${server.port}',
      userKey: 'synthetic-user',
      enableLogging: false,
    );
    addTearDown(client.close);
    expect(await client.getAccountMediaScope(), 'a' * 64);
    await expectLater(client.getAccountMediaScope(), throwsStateError);
  });

  test(
    'scoped receipt confirms a committed deletion but not storage erasure',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final seen = <String>[];
      server.listen((request) async {
        seen.add('${request.method} ${request.uri.path}');
        expect(request.headers.value('x-user-key'), 'synthetic-user');
        expect(request.headers.value('x-profile-id'), 'profile-a');
        expect(request.headers.value('x-deletion-request-id'), 'a' * 32);
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode(
            request.method == 'DELETE'
                ? {
                    'deletion_committed': true,
                    'purge_retry_pending': true,
                    'status': 'partial',
                  }
                : {
                    'deletion_committed': true,
                    'storage_purge_status': 'unknown',
                  },
          ),
        );
        await request.response.close();
      });
      final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'synthetic-user',
        profileId: 'profile-a',
        enableLogging: false,
      );
      addTearDown(client.close);
      final deletion = await client.deleteBookWithReceipt('book-a', 'a' * 32);
      expect(deletion['purge_retry_pending'], isTrue);
      await client.confirmBookDeletion('book-a', 'a' * 32);
      expect(seen, [
        'DELETE /v1/library/book-a',
        'GET /v1/library/book-a/deletion-receipt',
      ]);
    },
  );

  test('missing or ambiguous receipts never confirm deletion', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    var requests = 0;
    server.listen((request) async {
      requests++;
      request.response.headers.contentType = ContentType.json;
      if (requests == 1) {
        request.response.statusCode = 404;
        request.response.write('{}');
      } else {
        request.response.write(jsonEncode({'deletion_committed': true}));
      }
      await request.response.close();
    });
    final client = ApiClient(
      baseUrl: 'http://${server.address.host}:${server.port}',
      userKey: 'synthetic-user',
      enableLogging: false,
    );
    addTearDown(client.close);
    await expectLater(
      client.confirmBookDeletion('book-a', 'a' * 32),
      throwsA(isA<DioException>()),
    );
    await expectLater(
      client.confirmBookDeletion('book-a', 'a' * 32),
      throwsStateError,
    );
    await expectLater(
      client.deleteBookWithReceipt('../bad', 'a' * 32),
      throwsArgumentError,
    );
    await expectLater(
      client.deleteBookWithReceipt('book-a', 'bad'),
      throwsArgumentError,
    );
    expect(requests, 2);
  });
}
