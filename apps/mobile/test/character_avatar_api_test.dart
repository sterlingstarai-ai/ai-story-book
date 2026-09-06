import 'dart:convert';
import 'dart:io';

import 'package:ai_story_book/models/character.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'character_avatar_flow_test.dart' show avatarJson;

void main() {
  for (final action in ['approve', 'regenerate']) {
    test('$action sends the exact version and profile ownership headers',
        () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      server.listen((request) async {
        expect(request.method, 'POST');
        expect(request.uri.path, '/v1/characters/avatar-1/avatar/$action');
        expect(request.headers.value('X-User-Key'), 'user');
        expect(request.headers.value('X-Profile-Id'), 'profile');
        expect(jsonDecode(await utf8.decoder.bind(request).join()),
            {'version': 2});
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode(avatarJson(
            status: action == 'approve' ? 'approved' : 'generating',
            version: action == 'approve' ? 2 : 3)));
        await request.response.close();
      });
      final api = ApiClient(
          baseUrl: 'http://${server.address.host}:${server.port}',
          userKey: 'user',
          profileId: 'profile',
          enableLogging: false);
      final result = action == 'approve'
          ? await api.approveCharacterAvatar('avatar-1', version: 2)
          : await api.regenerateCharacterAvatar('avatar-1', version: 2);
      expect(
          result.avatarStatus,
          action == 'approve'
              ? CharacterAvatarStatus.approved
              : CharacterAvatarStatus.generating);
      expect(result.avatarVersion, action == 'approve' ? 2 : 3);
    });
  }
  test('invalid avatar version never reaches the transport', () async {
    final api = ApiClient(
        baseUrl: 'http://invalid', userKey: 'user', enableLogging: false);
    await expectLater(
        api.approveCharacterAvatar('c', version: 0), throwsArgumentError);
    await expectLater(
        api.regenerateCharacterAvatar('c', version: -1), throwsArgumentError);
  });
  test('a conflict remains an error instead of a fabricated approval',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) async {
      request.response.statusCode = 409;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'error': {
          'code': 'CHARACTER_AVATAR_VERSION_CONFLICT',
          'message': 'Changed'
        }
      }));
      await request.response.close();
    });
    final api = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'user',
        enableLogging: false);
    await expectLater(api.approveCharacterAvatar('c', version: 1),
        throwsA(isA<DioException>()));
  });
}
