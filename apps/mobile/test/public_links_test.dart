import 'package:ai_story_book/services/public_links.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
      'public pages support hosting addresses and reject missing or unsafe URLs',
      () async {
    final opened = <Uri>[];
    final links = PublicLinks(launch: (uri) async {
      opened.add(uri);
      return true;
    });
    for (final value in [
      '',
      'http://example.com/privacy',
      '/privacy',
      'https://',
      'https://user:password@example.com'
    ]) {
      expect(await links.open(value), isFalse);
    }
    expect(opened, isEmpty);
    expect(await links.open('https://storybook.pages.dev/privacy'), isTrue);
    expect(opened.single.host, 'storybook.pages.dev');
  });

  test('launch failures return a recoverable result', () async {
    expect(
        await PublicLinks(launch: (_) async => false)
            .open('https://example.com'),
        isFalse);
    expect(
        await PublicLinks(launch: (_) async => throw Exception('unavailable'))
            .open('https://example.com'),
        isFalse);
  });
}
