import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final action in ['account', 'voice', 'revoke', 'book', 'character']) {
    for (final pending in [false, true]) {
      test(
        '$action deletion distinguishes a committed request from media purge completion ($pending)',
        () async {
          final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
          addTearDown(() => server.close(force: true));
          server.listen((request) async {
            request.response.headers.contentType = ContentType.json;
            request.response.write(
              jsonEncode({
                'status': pending ? 'partial' : 'success',
                'purge_retry_pending': pending,
              }),
            );
            await request.response.close();
          });
          final client = ApiClient(
            baseUrl: 'http://127.0.0.1:${server.port}',
            userKey: 'test-account',
            enableLogging: false,
          );
          final Future<dynamic> response = switch (action) {
            'account' => client.deleteMyData(),
            'voice' => client.deleteVoiceProfile('voice'),
            'book' => client.deleteBook('book'),
          'character' => client.deleteCharacter('character'),
            _ => client.revokeVoiceProfileConsent('voice'),
          };
          if (pending) {
            await expectLater(response, throwsA(isA<StoragePurgePending>()));
          } else {
            await expectLater(response, completes);
          }
        },
      );
    }
  }
}
