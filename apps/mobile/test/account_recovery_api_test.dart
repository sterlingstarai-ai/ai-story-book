import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

const _oldKey = '11111111-2222-4333-8444-555555555555';
final _code = 'ASB-R1-${List.filled(43, 'A').join()}';
void main() {
  test(
      'public recovery HTTP request excludes previous user and profile credentials',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) async {
      expect(request.uri.path, '/v1/account/recover');
      expect(request.headers.value('x-user-key'), isNull);
      expect(request.headers.value('x-profile-id'), isNull);
      expect(request.headers.value('x-request-id'), isNotEmpty);
      final data = jsonDecode(await utf8.decoder.bind(request).join());
      expect(data['recovery_code'], _code);
      request.response.headers.contentType = ContentType.json;
      request.response
          .write(jsonEncode({'status': 'recovered', 'recovery_code': null}));
      await request.response.close();
    });
    final client = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: _oldKey,
        profileId: 'old-profile',
        enableLogging: false);
    addTearDown(client.close);
    expect(
        await client.recoverAccount(
            recoveryCode: _code, newUserKey: 'new-test-key'),
        isNull);
  });
}
