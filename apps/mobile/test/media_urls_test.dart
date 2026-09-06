import 'package:ai_story_book/core/media_urls.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('서명 URL만 만료 전에 갱신하고 외부 URL은 그대로 사용한다', () {
    const url =
        'https://s3.test/book.png?X-Amz-Date=20260905T090000Z&X-Amz-Expires=3600';
    expect(mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 9, 30)),
        isFalse);
    expect(mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 9, 59)),
        isTrue);
    expect(
        mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 12)), isTrue);
    expect(mediaUrlNeedsRefresh('https://legacy.test/book.png'), isFalse);
    expect(mediaUrlNeedsRefresh(null), isFalse);
  });
}
