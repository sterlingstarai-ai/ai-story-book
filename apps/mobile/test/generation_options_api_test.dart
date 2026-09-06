import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/models/book_spec.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('style preflight uses the current authenticated account', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) async {
      expect(request.method, 'GET');
      expect(request.uri.path, '/v1/books/generation-options');
      expect(request.headers.value('x-user-key'), 'synthetic-account');
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'allowed_styles': ['cartoon']
      }));
      await request.response.close();
    });
    final api = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'synthetic-account',
        enableLogging: false);
    addTearDown(api.close);
    expect(
        (await api.getGenerationOptions()).allowedStyles, [BookStyle.cartoon]);
  });
}
