// H2/G10: 기기 타임존이 실제로 서버에 전송되는지 — '사용자별 타임존'의 마지막 배관.
//
// 감사 §2: 서버 tz 배관은 완비됐으나 앱이 timezone을 한 번도 보내지 않아 전 사용자가
// Asia/Seoul 고정이었고, G10 결정의 사용자 가시 효과가 0이었다. 플랫폼 채널(기기 tz 조회)만
// 주입으로 대체하고 중복 억제·PATCH payload 등 실로직은 그대로 통과시킨다.
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/timezone_sync.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _CapturingApiClient extends ApiClient {
  _CapturingApiClient()
      : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test-user');

  final List<Map<String, dynamic>> patches = [];

  @override
  Future<void> patchSettings(Map<String, dynamic> payload) async {
    patches.add(payload);
  }
}

class _FailingApiClient extends _CapturingApiClient {
  @override
  Future<void> patchSettings(Map<String, dynamic> payload) async {
    patches.add(payload);
    throw Exception('network down');
  }
}

Future<SharedPreferences> _prefs() async {
  SharedPreferences.setMockInitialValues({});
  return SharedPreferences.getInstance();
}

void main() {
  test('기기 타임존을 서버 설정으로 전송한다 (G10)', () async {
    final api = _CapturingApiClient();
    final prefs = await _prefs();

    final result = await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'America/Los_Angeles',
    );

    expect(result, 'America/Los_Angeles');
    expect(api.patches.single['timezone'], 'America/Los_Angeles');
    expect(prefs.getString(TimezoneSync.prefsKey), 'America/Los_Angeles');
  });

  test('같은 타임존이면 재전송하지 않는다 (부팅 비용 0)', () async {
    final api = _CapturingApiClient();
    final prefs = await _prefs();

    await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'Asia/Tokyo',
    );
    await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'Asia/Tokyo',
    );

    expect(api.patches.length, 1);
  });

  test('타임존이 바뀌면 다시 전송한다 (여행·이주)', () async {
    final api = _CapturingApiClient();
    final prefs = await _prefs();

    await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'Asia/Seoul',
    );
    await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'Europe/Berlin',
    );

    expect(api.patches.map((p) => p['timezone']).toList(),
        ['Asia/Seoul', 'Europe/Berlin']);
  });

  test('전송 실패는 삼키되 캐시하지 않아 다음 실행에 재시도된다', () async {
    final api = _FailingApiClient();
    final prefs = await _prefs();

    final result = await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => 'America/New_York',
    );

    expect(result, isNull);
    // 실패했으므로 캐시에 남으면 안 된다(남으면 영영 재시도 안 함).
    expect(prefs.getString(TimezoneSync.prefsKey), isNull);
  });

  test('기기 tz 조회 실패는 부팅을 막지 않는다', () async {
    final api = _CapturingApiClient();
    final prefs = await _prefs();

    final result = await TimezoneSync.sync(
      api: api,
      prefs: prefs,
      resolver: () async => throw Exception('no platform channel'),
    );

    expect(result, isNull);
    expect(api.patches, isEmpty);
  });
}
