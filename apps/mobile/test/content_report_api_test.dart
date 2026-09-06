import 'dart:convert';
import 'dart:io';
import 'package:ai_story_book/models/content_report.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('report HTTP request keeps identity and sends only page and reason',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) async {
      expect(request.method, 'POST');
      expect(request.uri.path, '/v1/books/book_test/reports');
      expect(request.headers.value('x-user-key'), 'test-account');
      expect(request.headers.value('x-profile-id'), 'child-test');
      expect(request.headers.value('x-request-id'), isNotEmpty);
      expect(jsonDecode(await utf8.decoder.bind(request).join()),
          {'page_number': 2, 'reason': 'image_problem'});
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'report_id': 'report_test',
        'status': 'pending',
        'created_at': '2026-09-06'
      }));
      await request.response.close();
    });
    final api = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}',
        userKey: 'test-account',
        profileId: 'child-test',
        enableLogging: false);
    addTearDown(api.close);
    expect(
        (await api.reportBookContent('book_test',
                pageNumber: 2, reason: ContentReportReason.imageProblem))
            .reportId,
        'report_test');
  });
}
