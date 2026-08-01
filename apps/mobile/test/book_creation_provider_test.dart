import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';

// H18: 생성 재시도(타임아웃 후 재탭) 시 같은 멱등키를 재사용해 서버가 dedup → 이중차감 방지.
class _SpyApiClient extends ApiClient {
  _SpyApiClient()
      : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  final List<String?> keys = <String?>[];
  int calls = 0;

  @override
  Future<CreateBookResponse> createBook(BookSpec spec,
      {String? idempotencyKey}) async {
    calls++;
    keys.add(idempotencyKey);
    if (calls == 1) {
      throw Exception('timeout');
    }
    return CreateBookResponse(jobId: 'job-1', status: 'queued');
  }
}

void main() {
  test('createBook reuses idempotency key across retries, new after success',
      () async {
    final spy = _SpyApiClient();
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(spy)],
    );
    addTearDown(container.dispose);

    final spec = BookSpec(topic: 't', targetAge: '5-7', style: 'watercolor');
    final notifier = container.read(bookCreationProvider.notifier);

    // 1차 실패(타임아웃).
    await expectLater(notifier.createBook(spec), throwsException);
    // 2차 재시도 → 같은 spec이면 같은 키 재사용.
    final jobId = await notifier.createBook(spec);

    expect(jobId, 'job-1');
    expect(spy.keys.length, 2);
    expect(spy.keys[0], isNotNull);
    expect(spy.keys[0], spy.keys[1]); // 재시도 동일 키

    // 성공 후 새 생성은 새 키.
    await notifier.createBook(spec);
    expect(spy.keys.length, 3);
    expect(spy.keys[2], isNot(spy.keys[1]));
  });
}
