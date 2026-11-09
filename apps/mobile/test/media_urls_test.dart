import 'package:ai_story_book/core/media_urls.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('서명 URL만 만료 전에 갱신하고 외부 URL은 그대로 사용한다', () {
    const url =
        'https://s3.test/book.png?X-Amz-Date=20260905T090000Z&X-Amz-Expires=3600';
    expect(
      mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 9, 30)),
      isFalse,
    );
    expect(
      mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 9, 59)),
      isTrue,
    );
    expect(
      mediaUrlNeedsRefresh(url, now: DateTime.utc(2026, 9, 5, 12)),
      isTrue,
    );
    expect(mediaUrlNeedsRefresh('https://legacy.test/book.png'), isFalse);
    expect(mediaUrlNeedsRefresh(null), isFalse);
  });

  test('rotating S3 signing credentials preserve generated image identity', () {
    const origin = 'https://s3.test/storybooks/jobs/job_1';
    const object = '0123456789abcdef0123456789abcdef.png';
    const signed = 'X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature';
    const first = '$origin/$object?versionId=one&$signed=old&X-Amz-Date=old';
    const second = '$origin/$object?versionId=one&$signed=new&X-Amz-Date=new';
    final identity = illustrationCacheIdentity(first);
    expect(identity, '$origin/$object?versionId=one');
    expect(illustrationCacheIdentity(second), identity);
    expect(
      illustrationCacheIdentity(
        second.replaceFirst('versionId=one', 'versionId=two'),
      ),
      isNot(identity),
    );
    expect(
      illustrationCacheIdentity(second.replaceFirst('s3.test', 'other.test')),
      isNot(identity),
    );
    const mutable = '$origin/cover.png?$signed=old';
    expect(illustrationCacheIdentity(mutable), mutable);
    const external = 'https://s3.test/arbitrary/$object?$signed=old';
    expect(illustrationCacheIdentity(external), external);
    const ambiguous = '$first&X-Amz-Signature=unexpected';
    expect(illustrationCacheIdentity(ambiguous), ambiguous);
  });
}
