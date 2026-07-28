import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// 기기 IANA 타임존을 서버 사용자 설정에 동기화한다 (H2/G10).
///
/// 서버는 사용자별 tz로 스트릭·일일 한도·리포트의 '하루' 경계를 판정한다. 그런데 앱이
/// timezone을 한 번도 전송하지 않으면 모든 사용자가 기본값(Asia/Seoul)으로 고정돼,
/// 비KR 사용자의 스트릭이 한국 자정에 끊기고 리포트 날짜가 어긋난다 — 사용자별 타임존
/// 결정(G10)의 사용자 가시 효과가 0이 된다. 이 동기화가 그 배관의 마지막 연결이다.
typedef TimezoneResolver = Future<String> Function();

class TimezoneSync {
  /// 마지막으로 서버에 보낸 tz. 값이 그대로면 네트워크 호출을 건너뛴다(부팅 비용 0).
  static const prefsKey = 'synced_timezone_v1';

  /// 기기 tz가 마지막 동기화 값과 다를 때만 PATCH한다.
  ///
  /// 실패는 삼킨다 — 타임존 동기화가 부팅이나 설정 저장을 막아서는 안 되고, 다음 실행에
  /// 자연히 재시도된다(prefs를 성공 시에만 갱신하므로).
  /// [resolver]는 테스트에서 플랫폼 채널을 대체하기 위한 주입점.
  static Future<String?> sync({
    required ApiClient api,
    required SharedPreferences prefs,
    TimezoneResolver? resolver,
  }) async {
    try {
      final resolve = resolver ?? FlutterTimezone.getLocalTimezone;
      final timezone = (await resolve()).trim();
      if (timezone.isEmpty) {
        return null;
      }
      if (prefs.getString(prefsKey) == timezone) {
        return timezone;
      }
      await api.patchSettings({'timezone': timezone});
      await prefs.setString(prefsKey, timezone);
      return timezone;
    } catch (_) {
      return null;
    }
  }
}
